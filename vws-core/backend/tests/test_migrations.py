"""OPS-05: populated known-layout copies, authenticated backup and rollback."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import (
    SCHEMA_VERSION,
    Base,
    SchemaMeta,
    SchemaVersion,
    SecurityEvent,
    create_schema,
)
from backend.core.errors import DatabaseError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.ops.backups import BackupService
from backend.ops.migrations import MigrationRunner
from backend.tests.test_ledger import _signal
from backend.tests.test_security_cli import MemorySecrets


def legacy(
    engine: Engine, clock: FrozenClock, version: int
) -> tuple[dict[int, str], MemorySecrets]:
    ledger = Ledger(engine, clock)
    _signal(ledger, clock)
    ledger.append(SecurityEvent, kind="LEGACY_MIGRATION_FIXTURE", detail={"synthetic": True})
    with Session(engine) as session:
        from backend.core.database import LEDGER_MODELS

        original = {
            row.seq: row.row_hash
            for model in LEDGER_MODELS
            for row in session.scalars(select(model))
        }
    missing = {"execution_orders", "execution_fills", "auto_job_runs"}
    if version < 6:
        missing |= {"cash_flows", "daily_pnl", "tax_events"}
    if version < 5:
        missing.add("schema_version")
    if version < 4:
        missing |= {"ticket_events", "job_runs"}
    if version == 2:
        missing.add("news_headlines")
    with engine.begin() as connection:
        for name in sorted(missing):
            Base.metadata.tables[name].drop(connection)
        connection.execute(update(SchemaMeta).values(version=version))
    return original, MemorySecrets()


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6])
def test_OPS_05_additive_migration_keeps_all_original_hashes_and_verifies_legacy_backup(
    engine: Engine, clock: FrozenClock, tmp_path: Path, version: int
) -> None:
    original, store = legacy(engine, clock, version)
    with pytest.raises(DatabaseError):
        create_schema(engine)
    result = MigrationRunner(engine, clock, store, tmp_path / "backups").run("Test Owner")
    assert (
        result.applied
        and result.source_version == version
        and result.target_version == SCHEMA_VERSION
    )
    assert result.original_records == len(original)
    assert result.backup_path is not None and result.backup_path.exists()
    assert b"SQLite format 3" not in result.backup_path.read_bytes()
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables)
    with Session(engine) as session:
        from backend.core.database import LEDGER_MODELS

        unchanged = {
            row.seq: row.row_hash
            for model in LEDGER_MODELS
            for row in session.scalars(select(model))
            if row.seq in original
        }
        assert unchanged == original
        stamp = session.scalar(select(SchemaVersion))
        assert (
            stamp is not None
            and stamp.source_version == version
            and stamp.backup_sha256 == result.backup_sha256
        )
        assert session.scalar(select(SchemaMeta.version)) == SCHEMA_VERSION
    ledger = Ledger(engine, clock)
    ledger.verify_chain()
    service = BackupService(ledger, clock, store, tmp_path / "backups")
    restored = service.restore_test(result.backup_path)
    assert restored.seq == len(original)
    assert restored.plaintext_sha256 == result.backup_sha256
    second = MigrationRunner(engine, clock, store, tmp_path / "backups").run("Test Owner")
    assert not second.applied and second.backup_path is None
    create_schema(engine)


@pytest.mark.parametrize("failure", ["backup", "ddl", "audit", "interrupt"])
def test_OPS_05_failed_migration_rolls_back_schema_and_never_rewrites_records(
    engine: Engine,
    clock: FrozenClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    original, store = legacy(engine, clock, 4)
    runner = MigrationRunner(engine, clock, store, tmp_path / "backups")
    if failure == "backup":

        def bad_image() -> bytes:
            raise DataIntegrityError("injected backup failure")

        monkeypatch.setattr(runner, "_image", bad_image)
    elif failure == "ddl":
        import backend.ops.migrations as module

        def bad_triggers(*args: object) -> None:
            raise DataIntegrityError("injected migration DDL failure")

        # Private copy verification uses database.py's protection function;
        # only the actual migration DDL call is made to fail.
        monkeypatch.setattr(module, "install_append_only_triggers", bad_triggers)
    else:
        original_append = Ledger.append_in_session

        def bad_append(
            self: Ledger, session: Session, model: type[SchemaVersion], **fields: object
        ) -> SchemaVersion:
            if model is SchemaVersion:
                if failure == "interrupt":
                    raise KeyboardInterrupt
                raise DataIntegrityError("injected migration audit failure")
            return original_append(self, session, model, **fields)

        monkeypatch.setattr(Ledger, "append_in_session", bad_append)
    with pytest.raises((DataIntegrityError, KeyboardInterrupt)):
        runner.run("Test Owner")
    assert "schema_version" not in inspect(engine).get_table_names()
    with Session(engine) as session:
        assert session.scalar(select(SchemaMeta.version)) == 4
        assert {
            row.seq: row.row_hash
            for row in session.scalars(select(SecurityEvent))
            if row.seq in original
        } == {seq: row_hash for seq, row_hash in original.items() if seq == max(original)}
    if failure == "backup":
        assert not (tmp_path / "backups").exists()
    else:
        assert len(tuple((tmp_path / "backups").glob("*.vwsbak"))) == 1


@pytest.mark.parametrize("fault", ["unknown_version", "extra_table", "corrupt_hash"])
def test_OPS_05_unknown_or_corrupt_source_refused_without_source_changes(
    engine: Engine, clock: FrozenClock, tmp_path: Path, fault: str
) -> None:
    _, store = legacy(engine, clock, 4)
    with engine.begin() as connection:
        if fault == "unknown_version":
            connection.execute(update(SchemaMeta).values(version=999))
        elif fault == "extra_table":
            connection.exec_driver_sql("CREATE TABLE unexpected (id INTEGER)")
        else:
            connection.exec_driver_sql("DROP TRIGGER vws_security_events_update")
            connection.exec_driver_sql("UPDATE security_events SET row_hash = '" + "0" * 64 + "'")
    with pytest.raises(DataIntegrityError):
        MigrationRunner(engine, clock, store, tmp_path / "backups").run("Test Owner")
    assert "schema_version" not in inspect(engine).get_table_names()
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("operator", ["", "\n", "x" * 129])
def test_OPS_05_host_operator_required_before_backup(
    engine: Engine, clock: FrozenClock, tmp_path: Path, operator: str
) -> None:
    _, store = legacy(engine, clock, 4)
    with pytest.raises(DataIntegrityError):
        MigrationRunner(engine, clock, store, tmp_path / "backups").run(operator)
    assert not (tmp_path / "backups").exists()
