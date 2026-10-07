"""GD-04: XNYS timing, durable failures and protection while halted."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.agents.orchestrator import JobCounts, JobName, Orchestrator
from backend.core.config import load_yaml_config
from backend.core.database import JobRun
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry


class Clock:
    def __init__(self, now: datetime) -> None:
        self.instant = now

    def now(self) -> datetime:
        return self.instant


def make(engine: Engine, instant: str) -> tuple[Orchestrator, list[str], Clock]:
    clock = Clock(datetime.fromisoformat(instant))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    project = Path(__file__).resolve().parents[2]
    config = load_yaml_config(
        project / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(project / "config").symbols,
    )
    calls: list[str] = []

    async def body() -> JobCounts:
        calls.append("ran")
        return JobCounts(counts={"alerts": 1})

    return (
        Orchestrator(config, MarketCalendar(), state, clock, dict.fromkeys(JobName, body)),
        calls,
        clock,
    )


@pytest.mark.parametrize(
    "instant,job,expected",
    [
        ("2026-09-30T20:29:59+00:00", JobName.DAILY_SCAN, False),
        ("2026-09-30T20:30:00+00:00", JobName.DAILY_SCAN, True),
        ("2026-11-27T18:30:00+00:00", JobName.DAILY_SCAN, True),
        ("2026-11-26T18:30:00+00:00", JobName.DAILY_SCAN, False),
        ("2026-03-06T21:30:00+00:00", JobName.DAILY_SCAN, True),
        ("2026-03-09T20:30:00+00:00", JobName.DAILY_SCAN, True),
        ("2026-09-30T12:45:00+00:00", JobName.PREMARKET_CHECK, True),
        ("2026-11-27T13:45:00+00:00", JobName.PREMARKET_CHECK, True),
        ("2026-10-02T20:30:00+00:00", JobName.WEEKLY_REPORT, True),
        ("2026-10-01T20:30:00+00:00", JobName.WEEKLY_REPORT, False),
        ("2026-11-27T18:30:00+00:00", JobName.WEEKLY_REPORT, True),
        ("2026-09-30T13:30:00+00:00", JobName.POSITION_MONITOR, True),
        ("2026-11-27T18:00:00+00:00", JobName.POSITION_MONITOR, False),
        ("2026-09-30T03:00:00+00:00", JobName.NEWS_WATCH, True),
        ("2026-09-30T06:00:00+00:00", JobName.HOUSEKEEPING, True),
        ("2026-09-30T06:02:00+00:00", JobName.HOUSEKEEPING, False),
    ],
)
def test_GD_04_calendar_schedule(
    engine: Engine, instant: str, job: JobName, expected: bool
) -> None:
    scheduler, _, clock = make(engine, instant)
    assert scheduler.due(job, clock.now()) == expected
    assert all(
        j.max_instances == 1 and j.coalesce and j.misfire_grace_time == 60
        for j in scheduler.scheduler.get_jobs()
    )


@pytest.mark.asyncio
async def test_GD_04_each_due_run_once_and_job_evidence(engine: Engine) -> None:
    scheduler, calls, _ = make(engine, "2026-09-30T20:30:00+00:00")
    await scheduler.tick(JobName.DAILY_SCAN)
    await scheduler.tick(JobName.DAILY_SCAN)
    assert calls == ["ran"]
    with Session(engine) as session:
        run = session.scalar(select(JobRun))
        assert run is not None and run.outcome == "PASS" and run.counts == {"alerts": 1}
    scheduler.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_04_halted_entries_skipped_monitors_continue(engine: Engine) -> None:
    scheduler, calls, clock = make(engine, "2026-09-30T13:30:00+00:00")
    scheduler.state.escalate(SystemState.HALTED, "fixture")
    await scheduler.tick(JobName.POSITION_MONITOR)
    assert calls == ["ran"]
    clock.instant = datetime(2026, 9, 30, 20, 30, tzinfo=UTC)
    await scheduler.tick(JobName.DAILY_SCAN)
    assert calls == ["ran"]
    with Session(engine) as session:
        assert tuple(session.scalars(select(JobRun.outcome).order_by(JobRun.seq))) == (
            "PASS",
            "SKIPPED",
        )


@pytest.mark.asyncio
async def test_GD_04_failure_and_cancellation_audited_no_repeat(engine: Engine) -> None:
    scheduler, _, clock = make(engine, "2026-09-30T20:30:00+00:00")

    async def fault() -> JobCounts:
        raise RuntimeError("unsafe detail must not be audited")

    scheduler.jobs[JobName.DAILY_SCAN] = fault
    await scheduler.tick(JobName.DAILY_SCAN)
    assert scheduler.state.current() == SystemState.HALTED

    async def cancelled() -> JobCounts:
        raise asyncio.CancelledError

    scheduler.jobs[JobName.HOUSEKEEPING] = cancelled
    clock.instant = datetime(2026, 10, 1, 6, tzinfo=UTC)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.tick(JobName.HOUSEKEEPING)
    with Session(engine) as session:
        assert tuple(session.scalars(select(JobRun.outcome))) == ("FAIL", "FAIL")
    scheduler.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_04_concurrent_dispatch_is_one_instance(engine: Engine) -> None:
    scheduler, calls, _ = make(engine, "2026-09-30T20:30:00+00:00")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def body() -> JobCounts:
        calls.append("one")
        entered.set()
        await release.wait()
        return JobCounts()

    scheduler.jobs[JobName.DAILY_SCAN] = body
    task = asyncio.create_task(scheduler.tick(JobName.DAILY_SCAN))
    await entered.wait()
    await scheduler.tick(JobName.DAILY_SCAN)
    release.set()
    await task
    assert calls == ["one"]


@pytest.mark.parametrize("counts", [{"a": True}, {"a": -1}, {"bad key": 1}, {"a": 10**10}])
def test_GD_04_invalid_count_fails_closed(counts: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        JobCounts.model_validate({"counts": counts})
