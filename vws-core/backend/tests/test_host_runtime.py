"""OPS-02: real temp ledger/scheduler, fake polling and broker-time boundary."""

import asyncio
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.agents.orchestrator import JobCounts, JobName, Orchestrator
from backend.core.clock import FrozenClock
from backend.core.config import Settings, load_yaml_config
from backend.core.database import JobRun, SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.ops.doctor import Check, DoctorResult
from backend.ops.process import ProcessLock, heartbeat_is_fresh
from backend.ops.runtime import HostRuntime, SafetyNotifications
from backend.ops.watchdog import Watchdog


class Bot:
    def __init__(self, fail: str = "") -> None:
        self.fail = fail
        self.calls: list[str] = []
        self.messages: list[str] = []

    async def start(self) -> None:
        self.calls.append("start")
        if self.fail == "start":
            raise ProviderError("fake partial polling start")

    async def stop(self) -> None:
        self.calls.append("stop")

    async def notify(self, text: str, urgent: bool) -> None:
        assert urgent
        if self.fail == "notify":
            raise ProviderError("fake delivery outage")
        self.messages.append(text)


def doctor_result(status: Literal["PASS", "RED", "UNVERIFIED"] = "PASS") -> DoctorResult:
    return DoctorResult(
        checks=(
            Check(
                name="fake_required",
                status=status,
                required=True,
                message="Synthetic required check",
                fix="Synthetic fixture only",
            ),
        )
    )


def make(
    engine: Engine, clock: FrozenClock, tmp_path: Path, *, fault: str = ""
) -> tuple[HostRuntime, asyncio.Event, list[str], Bot]:
    settings = Settings(_env_file=None, broker_account_type="CASH")
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    project = Path(__file__).resolve().parents[2]
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    stop, closed, bot = asyncio.Event(), [], Bot(fault)

    async def body() -> JobCounts:
        return JobCounts()

    async def check() -> DoctorResult:
        return doctor_result("UNVERIFIED" if fault == "doctor" else "PASS")

    async def close() -> None:
        closed.append("closed")

    async def verify() -> object:
        if fault == "clock":
            raise DataIntegrityError("fake broker clock mismatch")
        stop.set()  # first complete iteration then graceful shutdown, no sleep
        return None

    orchestrator = Orchestrator(
        config, MarketCalendar(), state, clock, dict.fromkeys(JobName, body)
    )
    watchdog = Watchdog(state, orchestrator.calendar, clock, lambda text: bot.notify(text, True))
    runtime = HostRuntime(
        settings,
        state,
        orchestrator,
        bot,
        watchdog,
        tmp_path / "heartbeat.json",
        check,
        close_resources=close,
        verify_broker_time=verify,
    )
    return runtime, stop, closed, bot


@pytest.mark.asyncio
async def test_TX_startup_fault_keeps_polling_and_held_monitor_available(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    runtime, stop, closed, bot = make(engine, clock, tmp_path)

    async def unavailable() -> None:
        assert bot.calls == ["start"]
        raise DataIntegrityError("Synthetic missing tax history")

    runtime.initialize_account = unavailable
    await runtime.run(stop)
    assert runtime.state.current() == SystemState.HALTED
    assert bot.calls == ["start", "stop"] and closed == ["closed"]
    runtime.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("halted", [False, True])
async def test_OPS_02_start_stop_health_and_persisted_halt(
    engine: Engine, clock: FrozenClock, tmp_path: Path, halted: bool
) -> None:
    runtime, stop, closed, bot = make(engine, clock, tmp_path)
    if halted:
        runtime.state.escalate(SystemState.HALTED, "Synthetic prior operator halt")
    lock = tmp_path / "runtime.lock"
    with ProcessLock(lock):
        await runtime.run(stop)
        assert heartbeat_is_fresh(runtime.heartbeat_path, lock, clock)
    assert not heartbeat_is_fresh(runtime.heartbeat_path, lock, clock)
    assert closed == ["closed"] and bot.calls == ["start", "stop"]
    assert runtime.state.current() == (SystemState.HALTED if halted else SystemState.RUNNING)
    assert "MANUAL, paper" in bot.messages[0]
    if halted:
        assert "Synthetic prior operator halt" in bot.messages[0]
    with Session(engine) as session:
        kinds = set(session.scalars(select(SecurityEvent.kind)))
    assert {"HOST_STARTED", "HOST_STOPPED"}.issubset(kinds)
    runtime.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["doctor", "start", "clock", "notify"])
async def test_OPS_02_startup_fault_never_certifies_health_and_closes_resources(
    engine: Engine, clock: FrozenClock, tmp_path: Path, fault: str
) -> None:
    runtime, stop, closed, bot = make(engine, clock, tmp_path, fault=fault)
    with pytest.raises((ConfigurationError, DataIntegrityError, ProviderError)):
        await runtime.run(stop)
    assert closed == ["closed"]
    assert bot.calls == ([] if fault == "doctor" else ["start", "stop"])
    assert not runtime.heartbeat_path.exists()
    assert runtime.state.current() == SystemState.HALTED
    runtime.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_OPS_03_failed_urgent_message_remains_pending_until_delivered(
    engine: Engine, clock: FrozenClock
) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    queue, bot = SafetyNotifications(), Bot("notify")
    queue.notify("HALTED", "Synthetic urgent warning")
    with pytest.raises(ProviderError):
        await queue.flush(bot, state)
    assert queue.pending == ("HALTED", "Synthetic urgent warning")
    bot.fail = ""
    await queue.flush(bot, state)
    await queue.flush(bot, state)
    assert queue.pending is None and len(bot.messages) == 1
    with Session(engine) as session:
        assert tuple(session.scalars(select(SecurityEvent.kind).order_by(SecurityEvent.seq))) == (
            "SAFETY_NOTIFICATION_FAILED",
            "SAFETY_NOTIFICATION_DELIVERED",
        )


@pytest.mark.asyncio
async def test_OPS_02_scheduler_drains_active_job_and_cancellation_audit_before_close(
    engine: Engine, clock: FrozenClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _, _, _ = make(engine, clock, tmp_path)
    # Use a known due dispatcher time without changing the ledger's UTC clock.
    monkeypatch.setattr(runtime.orchestrator, "due", lambda _name, _at: True)
    begun, finalized = asyncio.Event(), asyncio.Event()

    async def active_body() -> JobCounts:
        begun.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()
        return JobCounts()

    runtime.orchestrator.jobs[JobName.POSITION_MONITOR] = active_body
    worker = asyncio.create_task(runtime.orchestrator.tick(JobName.POSITION_MONITOR))
    await begun.wait()
    await runtime.orchestrator.aclose()
    assert worker.done() and worker.cancelled() and finalized.is_set()
    assert runtime.state.current() == SystemState.HALTED
    with Session(engine) as session:
        assert session.scalar(select(JobRun.outcome)) == "FAIL"
    runtime.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_OPS_02_constructor_never_accepts_auto_or_live(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    runtime, _, _, _ = make(engine, clock, tmp_path)
    auto = Settings(_env_file=None, broker_account_type="CASH", execution_mode="AUTO_PAPER")
    with pytest.raises(ConfigurationError):
        HostRuntime(
            auto,
            runtime.state,
            runtime.orchestrator,
            runtime.bot,
            runtime.watchdog,
            runtime.heartbeat_path,
            runtime.doctor,
            close_resources=runtime.close_resources,
            verify_broker_time=runtime.verify_broker_time,
        )


def test_OPS_03_notification_queue_has_bounded_failure() -> None:
    queue = SafetyNotifications()
    for _ in range(100):
        queue.notify("HALTED", "Synthetic queue test")
    with pytest.raises(ProviderError):
        queue.notify("HALTED", "Synthetic overflow")


@pytest.mark.asyncio
async def test_OPS_02_cancellation_is_audited_and_cleanup_runs(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    runtime, stop, closed, bot = make(engine, clock, tmp_path)

    async def cancel() -> object:
        raise asyncio.CancelledError

    runtime.verify_broker_time = cancel
    with pytest.raises(asyncio.CancelledError):
        await runtime.run(stop)
    assert runtime.state.current() == SystemState.HALTED
    assert bot.calls == ["start", "stop"] and closed == ["closed"]
    assert not runtime.heartbeat_path.exists()
    runtime.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_OPS_02_cleanup_failure_still_closes_other_components_and_latches_halt(
    engine: Engine, clock: FrozenClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, stop, closed, bot = make(engine, clock, tmp_path)
    original = runtime.orchestrator.aclose

    async def failed_close() -> None:
        await original()
        raise ProviderError("Synthetic scheduler-close failure")

    monkeypatch.setattr(runtime.orchestrator, "aclose", failed_close)
    with pytest.raises(ProviderError, match="shutdown"):
        await runtime.run(stop)
    assert bot.calls == ["start", "stop"] and closed == ["closed"]
    assert runtime.state.current() == SystemState.HALTED
    with Session(engine) as session:
        stopped = session.scalar(select(SecurityEvent).where(SecurityEvent.kind == "HOST_STOPPED"))
        assert stopped is not None and stopped.detail["cleanup_verified"] is False
    runtime.state.ledger.verify_chain()
