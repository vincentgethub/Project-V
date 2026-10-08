"""OPS-03/04: real ledger/online encrypted backups and injected time/notices."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.agents.orchestrator import JobName
from backend.core.database import JobRun, SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.ops.backups import BackupService
from backend.ops.maintenance import NightlyMaintenance
from backend.ops.watchdog import Watchdog
from backend.tests.test_broker_clock import MovingClock
from backend.tests.test_security_cli import MemorySecrets


def service(engine: Engine, instant: str) -> tuple[Watchdog, list[str], MovingClock]:
    clock = MovingClock(datetime.fromisoformat(instant))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    notices: list[str] = []

    async def notify(message: str) -> None:
        notices.append(message)

    return Watchdog(state, MarketCalendar(), clock, notify), notices, clock


def run(
    watch: Watchdog,
    job: JobName,
    outcome: Literal["PASS", "FAIL", "SKIPPED"],
    started: datetime | None = None,
    finished: datetime | None = None,
) -> None:
    instant = watch.clock.now()
    watch.state.ledger.append(
        JobRun,
        job=job.value,
        started_at=started or instant,
        finished_at=finished or instant,
        outcome=outcome,
        counts={},
        duration_ms=0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "instant,expected",
    [
        ("2026-09-29T21:29:59+00:00", 0),
        ("2026-09-29T21:30:00+00:00", 1),
        ("2026-11-27T19:29:59+00:00", 0),
        ("2026-11-27T19:30:00+00:00", 1),
        ("2026-11-26T23:30:00+00:00", 0),
        ("2026-10-03T23:30:00+00:00", 0),
        ("2026-03-06T22:30:00+00:00", 1),
        ("2026-03-09T21:30:00+00:00", 1),
    ],
)
async def test_OPS_03_scan_deadline_uses_actual_close_holiday_dst(
    engine: Engine, instant: str, expected: int
) -> None:
    watch, notices, _ = service(engine, instant)
    assert await watch.check() == expected
    assert len(notices) == expected
    assert await watch.check() == 0
    watch.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_OPS_03_success_before_deadline_pass_late_success_still_reports_missed_deadline(
    engine: Engine,
) -> None:
    watch, notices, clock = service(engine, "2026-09-29T21:30:00+00:00")
    run(
        watch,
        JobName.DAILY_SCAN,
        "PASS",
        datetime(2026, 9, 29, 20, 30, tzinfo=UTC),
        datetime(2026, 9, 29, 21, tzinfo=UTC),
    )
    assert await watch.check() == 0 and not notices
    clock.current += timedelta(days=1)
    run(watch, JobName.DAILY_SCAN, "PASS")
    # Exact deadline success counts; the following day is intentionally late.
    assert await watch.check() == 0
    clock.current += timedelta(days=1, minutes=1)
    run(watch, JobName.DAILY_SCAN, "PASS")
    assert await watch.check() == 1 and len(notices) == 1


@pytest.mark.asyncio
async def test_OPS_03_three_consecutive_failures_one_notice_per_episode_survives_restart(
    engine: Engine,
) -> None:
    watch, notices, clock = service(engine, "2026-09-29T15:00:00+00:00")
    for expected in (0, 0, 1, 0):
        run(watch, JobName.POSITION_MONITOR, "FAIL")
        assert await watch.check() == expected
    assert len(notices) == 1
    restarted = Watchdog(watch.state, watch.calendar, clock, watch.notify)
    assert await restarted.check() == 0
    run(watch, JobName.POSITION_MONITOR, "PASS")
    for _ in range(3):
        run(watch, JobName.POSITION_MONITOR, "FAIL")
    assert await restarted.check() == 1 and len(notices) == 2


@pytest.mark.asyncio
async def test_OPS_03_skipped_run_breaks_failure_streak_and_jobs_are_independent(
    engine: Engine,
) -> None:
    watch, notices, _ = service(engine, "2026-09-29T15:00:00+00:00")
    for outcome in ("FAIL", "FAIL", "SKIPPED", "FAIL", "FAIL"):
        run(watch, JobName.DAILY_SCAN, outcome)
    run(watch, JobName.NEWS_WATCH, "FAIL")
    assert await watch.check() == 0 and not notices
    run(watch, JobName.DAILY_SCAN, "FAIL")
    assert await watch.check() == 1


@pytest.mark.asyncio
async def test_OPS_03_failed_delivery_retries_and_concurrent_checks_do_not_double_send(
    engine: Engine,
) -> None:
    watch, notices, _ = service(engine, "2026-09-29T21:30:00+00:00")

    async def failed(message: str) -> None:
        raise OSError("TEST_ONLY_PRIVATE_PROVIDER_ERROR")

    watch.notify = failed
    assert await watch.check() == 0
    with transaction(engine) as session:
        evidence = session.scalar(
            select(SecurityEvent).where(SecurityEvent.kind == "WATCHDOG_NOTIFICATION_FAILED")
        )
        assert evidence is not None and "TEST_ONLY_PRIVATE" not in str(evidence.detail)

    async def notify(message: str) -> None:
        await asyncio.sleep(0)
        notices.append(message)

    watch.notify = notify
    results = await asyncio.gather(watch.check(), watch.check(), watch.check())
    assert sum(results) == 1 and len(notices) == 1


def backup_service(engine: Engine, tmp_path: Path) -> tuple[BackupService, MovingClock]:
    clock = MovingClock(datetime(2026, 9, 1, tzinfo=UTC))
    ledger = Ledger(engine, clock)
    ledger.append(SecurityEvent, kind="NIGHTLY_TEST_FIXTURE", detail={"synthetic": True})
    return BackupService(ledger, clock, MemorySecrets(), tmp_path / "backups"), clock


def test_OPS_04_nightly_verifies_new_backup_then_prunes_only_authenticated_expired_files(
    engine: Engine, tmp_path: Path
) -> None:
    backups, clock = backup_service(engine, tmp_path)
    old = backups.create()
    unknown = backups.directory / "owner-keeps-this.txt"
    unknown.write_bytes(b"not a managed backup")
    clock.current += timedelta(days=15)
    recent = backups.create()
    clock.current += timedelta(days=21)
    counts = NightlyMaintenance(backups).run()
    assert counts.counts == {"backup_verified": 1, "expired_backups": 1}
    assert not old.path.exists() and recent.path.exists() and unknown.exists()
    assert all(not path.name.endswith(".sqlite3") for path in backups.directory.iterdir())
    backups.ledger.verify_chain()


def test_OPS_04_corrupt_owned_backup_blocks_all_retention_deletion(
    engine: Engine, tmp_path: Path
) -> None:
    backups, clock = backup_service(engine, tmp_path)
    old, corrupted = backups.create(), backups.create()
    corrupted.path.write_bytes(b"TEST_ONLY_INVALID_AUTHENTICATION")
    clock.current += timedelta(days=31)
    with pytest.raises(DataIntegrityError):
        NightlyMaintenance(backups).run()
    assert old.path.exists() and corrupted.path.exists()
    assert backups.restore_test(old.path).seq >= 1


@pytest.mark.parametrize("phase", ["create", "restore_test"])
def test_OPS_04_failed_new_backup_never_prunes_old_files(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    backups, clock = backup_service(engine, tmp_path)
    old = backups.create()
    clock.current += timedelta(days=31)

    def failed(*args: object, **kwargs: object) -> None:
        raise DataIntegrityError("injected nightly backup failure")

    if phase == "create":
        monkeypatch.setattr(backups, "create", failed)
    else:
        monkeypatch.setattr(backups, "restore_test", failed)
    with pytest.raises(DataIntegrityError):
        NightlyMaintenance(backups).run()
    assert old.path.exists()


@pytest.mark.parametrize("days", [0, 366, True])
def test_OPS_04_retention_is_bounded(engine: Engine, tmp_path: Path, days: int) -> None:
    backups, _ = backup_service(engine, tmp_path)
    with pytest.raises(Exception, match="retention"):
        NightlyMaintenance(backups, days)
