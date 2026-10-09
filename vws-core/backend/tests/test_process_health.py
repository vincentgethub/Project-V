"""OPS-02/03: isolated OS locks and fake clock, no owner's process or keys."""

import errno
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import create_database, create_schema, enable_sqlite_wal
from backend.core.errors import DatabaseError, DataIntegrityError
from backend.ops.process import (
    Heartbeat,
    ProcessBusyError,
    ProcessLock,
    heartbeat_is_fresh,
    write_heartbeat,
)


def test_OPS_02_os_lock_rejects_second_process_and_releases_after_exception(tmp_path: Path) -> None:
    first, second = ProcessLock(tmp_path / "process.lock"), ProcessLock(tmp_path / "process.lock")
    with pytest.raises(RuntimeError), first:
        with pytest.raises(ProcessBusyError):
            second.__enter__()
        raise RuntimeError("simulated host shutdown")
    with second:
        assert second.fd is not None
    assert second.fd is None


@pytest.mark.parametrize(
    "fault", ["", "stale", "future", "unheld", "malformed", "large", "unavailable"]
)
def test_OPS_02_health_requires_fresh_utc_bound_heartbeat_and_held_lock(
    tmp_path: Path, clock: FrozenClock, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, lock = tmp_path / "heartbeat.json", tmp_path / "process.lock"
    at = (
        clock.now() - timedelta(seconds=181)
        if fault == "stale"
        else clock.now() + timedelta(seconds=1)
        if fault == "future"
        else clock.now()
    )
    beat = Heartbeat(
        run_id=uuid4(), updated_at=at, mode="MANUAL", paper=True, scheduler_running=True
    )
    write_heartbeat(path, beat)
    if fault in {"malformed", "large"}:
        path.write_bytes(b"{" if fault == "malformed" else b"x" * 2049)
    if fault == "unavailable":
        from backend.ops import process

        def unavailable(_self: ProcessLock) -> ProcessLock:
            raise OSError(errno.EIO, "fake OS locking unavailable")

        monkeypatch.setattr(process.ProcessLock, "__enter__", unavailable)
        assert not heartbeat_is_fresh(path, lock, clock)
    elif fault == "unheld":
        assert not heartbeat_is_fresh(path, lock, clock)
    else:
        with ProcessLock(lock):
            assert heartbeat_is_fresh(path, lock, clock) == (fault == "")
        assert not tuple(tmp_path.glob(".heartbeat-*"))


@pytest.mark.parametrize(
    "mode,paper,running",
    [("AUTO_PAPER", False, True), ("AUTO_LIVE", True, True), ("MANUAL", True, False)],
)
def test_OPS_02_stopped_or_mismatched_heartbeat_refuses_before_write(
    tmp_path: Path, clock: FrozenClock, mode: str, paper: bool, running: bool
) -> None:
    with pytest.raises(DataIntegrityError):
        write_heartbeat(
            tmp_path / "heartbeat.json",
            Heartbeat(
                run_id=uuid4(),
                updated_at=clock.now(),
                mode=mode,
                paper=paper,
                scheduler_running=running,
            ),
        )
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize(
    "mode,paper", [("MANUAL", True), ("MANUAL", False), ("AUTO_PAPER", True), ("AUTO_LIVE", False)]
)
def test_OPS_02_bound_heartbeat_certifies_liveness_without_unlocking_trading(
    tmp_path: Path, clock: FrozenClock, mode: str, paper: bool
) -> None:
    path, lock = tmp_path / "heartbeat.json", tmp_path / "process.lock"
    write_heartbeat(
        path,
        Heartbeat(
            run_id=uuid4(), updated_at=clock.now(), mode=mode, paper=paper, scheduler_running=True
        ),
    )
    assert not heartbeat_is_fresh(path, lock, clock)
    with ProcessLock(lock):
        assert heartbeat_is_fresh(path, lock, clock)
    assert not heartbeat_is_fresh(path, lock, clock)


def test_OPS_02_file_sqlite_wal_is_explicit_and_keeps_busy_timeout(engine: Engine) -> None:
    enable_sqlite_wal(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 10000
    ram = create_database("sqlite:///:memory:")
    try:
        create_schema(ram)
        with pytest.raises(DatabaseError):
            enable_sqlite_wal(ram)
    finally:
        ram.dispose()
