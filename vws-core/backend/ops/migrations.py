"""OPS-05: explicit backed-up, additive SQLite migrations; never rewrite rows.

Known v2/v3/v4 layouts share all persisted column contracts. A private restore
copy can add empty missing tables to verify the original record chains with
current code. No approval, fill, history or lifecycle evidence is fabricated.
Unknown layouts and unverifiable legacy evidence are refused before DDL.
"""

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

from pydantic import Field
from sqlalchemy import inspect, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.database import (
    LEDGER_MODELS,
    SCHEMA_VERSION,
    Base,
    CashFlow,
    DailyPnL,
    JobRun,
    NewsHeadlineRecord,
    SchemaMeta,
    SchemaVersion,
    SecurityEvent,
    TaxEvent,
    TicketEvent,
    create_database,
    create_schema,
    install_append_only_triggers,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel
from backend.ops.anchors import controlled_path
from backend.ops.backups import MAX_BACKUP_BYTES, BackupService
from backend.security.secrets import SecretStore


class MigrationResult(FrozenModel):
    source_version: int = Field(strict=True, ge=2)
    target_version: int = Field(strict=True, ge=2)
    applied: bool = Field(strict=True)
    backup_path: Path | None
    backup_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    original_records: int = Field(strict=True, ge=0)


def _tables(version: int) -> set[str]:
    if version not in {2, 3, 4, 5, 6} or SCHEMA_VERSION != 6:
        raise DataIntegrityError("Unknown schema version; no migration is authorized")
    names = set(Base.metadata.tables)
    if version < 6:
        names -= {CashFlow.__tablename__, DailyPnL.__tablename__, TaxEvent.__tablename__}
    if version < 5:
        names.remove(SchemaVersion.__tablename__)
    if version < 4:
        names -= {TicketEvent.__tablename__, JobRun.__tablename__}
    if version == 2:
        names.remove(NewsHeadlineRecord.__tablename__)
    return names


def validate_layout(bind: Engine | Connection) -> int:
    """OPS-05: exact inventories, not an approximate version hint."""
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())
    if "schema_meta" not in existing:
        raise DataIntegrityError("Schema metadata is absent; migration is refused")
    if isinstance(bind, Engine):
        with bind.connect() as connection:
            version = connection.scalar(select(SchemaMeta.version).where(SchemaMeta.id == 1))
    else:
        version = bind.scalar(select(SchemaMeta.version).where(SchemaMeta.id == 1))
    if type(version) is not int or existing != _tables(version):
        raise DataIntegrityError("Legacy table inventory cannot be verified")
    for name in existing:
        if {column["name"] for column in inspector.get_columns(name)} != {
            column.name for column in Base.metadata.tables[name].columns
        }:
            raise DataIntegrityError("Legacy columns differ; immutable rows cannot be rewritten")
    return version


def prepare_verification_copy(engine: Engine) -> None:
    """Only a private scratch restore calls this; original files are untouched."""
    version = validate_layout(engine)
    if version < SCHEMA_VERSION:
        with engine.begin() as connection:
            missing = _tables(SCHEMA_VERSION) - _tables(version)
            Base.metadata.create_all(
                connection, tables=[Base.metadata.tables[name] for name in sorted(missing)]
            )
            connection.execute(
                update(SchemaMeta).where(SchemaMeta.id == 1).values(version=SCHEMA_VERSION)
            )
    create_schema(engine)


def _prefix(session: Session, tables: set[str], limit: int | None = None) -> tuple[int, str]:
    entries = sorted(
        (row.seq, model.__tablename__, row.row_hash)
        for model in LEDGER_MODELS
        if model.__tablename__ in tables
        for row in session.scalars(select(model).order_by(model.seq))
        if limit is None or row.seq <= limit
    )
    digest = hashlib.sha256()
    for seq, name, row_hash in entries:
        digest.update(f"{seq}:{name}:{row_hash}\n".encode("ascii"))
    return len(entries), digest.hexdigest()


class MigrationRunner:
    def __init__(
        self, engine: Engine, clock: Clock, store: SecretStore, backup_directory: Path
    ) -> None:
        self.engine, self.clock, self.store, self.directory = engine, clock, store, backup_directory

    def _image(self) -> bytes:
        source = self.engine.raw_connection()
        try:
            driver = source.driver_connection
            if not isinstance(driver, sqlite3.Connection):
                raise DataIntegrityError("Migration backup requires the verified SQLite driver")
            target = sqlite3.connect(":memory:")
            try:
                driver.backup(target)
                image = target.serialize()
            finally:
                target.close()
        finally:
            source.close()
        if not image or len(image) > MAX_BACKUP_BYTES:
            raise DataIntegrityError("Migration backup exceeds its supported size bound")
        return image

    def _verify_image(self, image: bytes, version: int) -> tuple[int, str]:
        with tempfile.TemporaryDirectory(prefix="vws-migration-verify-") as scratch:
            os.chmod(scratch, 0o700)
            path = controlled_path(Path(scratch) / "copy.sqlite3")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(image)
                handle.flush()
                os.fsync(handle.fileno())
            copy = create_database("sqlite:///" + path.as_posix())
            try:
                if validate_layout(copy) != version:
                    raise DataIntegrityError("Migration backup version differs from the source")
                prepare_verification_copy(copy)
                ledger = Ledger(copy, self.clock)
                ledger.verify_chain()
                with Session(copy) as session:
                    return _prefix(session, _tables(version))
            finally:
                copy.dispose()

    def run(self, operator: str) -> MigrationResult:
        """Hold a SQLite write reservation from snapshot through commit."""
        if (
            not isinstance(operator, str)
            or not operator.strip()
            or len(operator) > 128
            or not operator.isprintable()
        ):
            raise DataIntegrityError("An explicit host operator is required for migration")
        if self.engine.dialect.name != "sqlite":
            raise DataIntegrityError(
                "Automated PostgreSQL migration is UNVERIFIED; follow the documented pg_dump/restore procedure"
            )
        if (
            self.engine.url.database in {None, "", ":memory:"}
            or not Path(str(self.engine.url.database)).is_file()
        ):
            raise DataIntegrityError("Migration requires an existing file-backed SQLite ledger")
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    version = validate_layout(connection)
                    if version == SCHEMA_VERSION:
                        with Session(bind=connection) as session:
                            Ledger(self.engine, self.clock)._verify_in_session(session)
                            count, _ = _prefix(session, _tables(version))
                        connection.rollback()
                        return MigrationResult(
                            source_version=version,
                            target_version=version,
                            applied=False,
                            backup_path=None,
                            original_records=count,
                        )
                    image = self._image()
                    original_count, original_digest = self._verify_image(image, version)
                    service = BackupService(
                        Ledger(self.engine, self.clock), self.clock, self.store, self.directory
                    )
                    header, payload = service.encrypt_bytes(image)
                    directory = controlled_path(self.directory)
                    directory.mkdir(exist_ok=True, mode=0o700)
                    name = (
                        "vws-"
                        + ensure_utc(self.clock.now()).strftime("%Y%m%dT%H%M%SZ")
                        + "-"
                        + uuid4().hex
                        + ".vwsbak"
                    )
                    path = controlled_path(self.directory / name)
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    # Authenticate the actual durable artifact before any DDL.
                    checked, restored = service.decrypt_bytes(path.read_bytes())
                    if (
                        checked != header
                        or restored != image
                        or self._verify_image(restored, version)
                        != (original_count, original_digest)
                    ):
                        raise DataIntegrityError("Migration backup failed durable verification")
                    missing = _tables(SCHEMA_VERSION) - _tables(version)
                    Base.metadata.create_all(
                        connection, tables=[Base.metadata.tables[name] for name in sorted(missing)]
                    )
                    install_append_only_triggers(connection)
                    result = connection.execute(
                        update(SchemaMeta)
                        .where(SchemaMeta.id == 1, SchemaMeta.version == version)
                        .values(version=SCHEMA_VERSION)
                    )
                    if result.rowcount != 1:
                        raise DataIntegrityError("Migration metadata changed concurrently")
                    ledger = Ledger(self.engine, self.clock)
                    with Session(bind=connection, expire_on_commit=False) as session:
                        ledger._verify_in_session(session)
                        if _prefix(session, _tables(version)) != (original_count, original_digest):
                            raise DataIntegrityError("Migration changed original record identities")
                        ledger.append_in_session(
                            session,
                            SchemaVersion,
                            version=SCHEMA_VERSION,
                            source_version=version,
                            backup_sha256=header.plaintext_sha256,
                        )
                        ledger.append_in_session(
                            session,
                            SecurityEvent,
                            kind="SCHEMA_MIGRATED",
                            telegram_user_id=None,
                            detail={
                                "source_version": version,
                                "target_version": SCHEMA_VERSION,
                                "operator": operator.strip(),
                                "backup_sha256": header.plaintext_sha256,
                            },
                            ts=ensure_utc(self.clock.now()),
                        )
                        ledger._verify_in_session(session)
                        session.flush()
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
            create_schema(self.engine)
            Ledger(self.engine, self.clock).verify_chain()
            return MigrationResult(
                source_version=version,
                target_version=SCHEMA_VERSION,
                applied=True,
                backup_path=path,
                backup_sha256=header.plaintext_sha256,
                original_records=original_count,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise DataIntegrityError(
                "Migration was refused or failed; preserve the encrypted backup and stop startup until verification succeeds"
            ) from None
