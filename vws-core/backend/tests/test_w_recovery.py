"""W recovery: durable notices, independent transports and bounded polling."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.config import RealtimeConfig, Settings, YamlConfig
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemStateStore
from backend.data.fee_schedule import load_fee_schedule
from backend.learning.journal import Cause
from backend.learning.service import LearningService
from backend.ops.macro_events import MacroCalendar
from backend.realtime import checks
from backend.realtime.desk import RealtimeDesk
from backend.realtime.models import ContextTag, Feed, FeedHealth, HealthStatus, RealtimeEvent
from backend.realtime.schedules import Schedules
from backend.realtime.storage import RealtimeStore
from backend.realtime.supervisor import Supervisor
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from backend.tests.test_system_state import RecordingNotifier
from backend.tests.test_telegram_security import MovingClock
from backend.tests.test_w_core import CAL, HASH, SCOPE, FakeReader, event
from backend.tests.test_w_learning_feeds import baseline as baseline

harness = make_research_harness


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("NEWS_NEG", ContextTag.NEWS_NEG),
        ("DILUTION", ContextTag.DILUTION),
        ("HALT", ContextTag.HALT),
    ],
)
def test_LJ_loss_day_evidence_is_causal_and_does_not_rewrite_open_context(
    engine: Engine, baseline: YamlConfig, tmp_path: Path, kind: str, expected: ContextTag
) -> None:
    clock = MovingClock()
    ledger = Ledger(engine, clock)
    learning = LearningService(
        ledger,
        SCOPE,
        baseline,
        CAL,
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
        tmp_path,
    )
    start, end = clock.now() - timedelta(minutes=30), clock.now()
    store = RealtimeStore(ledger, SCOPE, baseline.config_hash)
    row = event(end, feed="news" if kind != "HALT" else "halts", kind=kind)
    store.receive(row)
    assert learning._cause_context("NVDA", start, end) == (expected,)
    assert learning._cause_context("SPY", start, end) == ()
    clock.instant += timedelta(seconds=1)
    # A later received, backdated item cannot change the earlier classification.
    store.receive(event(end, provider_id="later-receipt", kind="NEWS_NEG", feed="news"))
    assert learning._cause_context("NVDA", start, end) == (expected,)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_LJ_actual_loss_uses_news_receipt_and_remains_byte_stable(harness: Harness) -> None:
    from backend.tests.test_v_verdict_source import SCOPE as physical_scope
    from backend.tests.test_v_verdict_source import close_split_trade

    h = harness
    await close_split_trade(h)
    store = RealtimeStore(h.state.ledger, physical_scope, h.config.config_hash)
    store.receive(event(h.clock.now(), feed="news", kind="NEWS_NEG"))
    learning = LearningService(
        h.state.ledger,
        physical_scope,
        h.config,
        CAL,
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
        Path(__file__).resolve().parents[2],
    )
    assert learning.sync() > 0
    losses = tuple(row for row in learning.journal.rows() if row.trigger == "LOSS")
    assert len(losses) == 1 and losses[0].cause_tag == Cause.NEWS_SHOCK
    assert losses[0].observation.cause_context_tags == (ContextTag.NEWS_NEG,)
    assert ContextTag.NEWS_NEG not in losses[0].observation.context_tags
    frozen = learning.journal.replay()
    assert learning.sync() == 0 and learning.journal.replay() == frozen


@pytest.mark.asyncio
async def test_AC_notice_retry_keeps_one_flag_and_one_delivery_receipt(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path
) -> None:
    store = RealtimeStore(Ledger(engine, clock), SCOPE, baseline.config_hash)
    desk = RealtimeDesk(
        store,
        baseline,
        CAL,
        Schedules(store.ledger, MacroCalendar(tmp_path / "missing.csv"), tmp_path / "missing.yaml"),
        lambda: True,
    )
    row = event(clock.now())
    with pytest.raises(DataIntegrityError, match="durable received flag"):
        store.delivered_notice(row)
    store.receive(row)
    attempts = []

    async def held(symbol: str) -> bool:
        return symbol == "NVDA"

    async def notice(text: str, urgent: bool) -> None:
        attempts.append((text, urgent))
        if len(attempts) == 1:
            raise ProviderError("Synthetic private delivery failure")

    async def forbidden_exit(value: RealtimeEvent) -> None:
        pytest.fail("A trading halt must never trigger AX-29")

    with pytest.raises(ProviderError):
        await desk.dispatch(row, held, notice, forbidden_exit)
    assert not store.notice_delivered(row)
    await desk.dispatch(row, held, notice, forbidden_exit)
    await desk.dispatch(row, held, notice, forbidden_exit)
    assert len(attempts) == 2 and all(urgent for _, urgent in attempts)
    with Session(engine) as session:
        kinds = tuple(session.scalars(select(SecurityEvent.kind)))
    assert kinds.count("REALTIME_FLAG") == kinds.count("REALTIME_NOTICE_DELIVERED") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("age,expected", [(119, "OK"), (121, "UNAVAILABLE")])
async def test_RT_failed_news_transport_cannot_erase_or_refresh_other_heartbeat(
    engine: Engine, age: int, expected: str
) -> None:
    clock = MovingClock()
    state = SystemStateStore(engine, clock, RecordingNotifier())
    store = RealtimeStore(state.ledger, SCOPE, HASH)
    original = FeedHealth(
        feed="news",
        status=HealthStatus.OK,
        observed_at=clock.now() - timedelta(seconds=age),
        detail="Other verified transport",
    )
    store.mark(original)

    async def dispatch(row: RealtimeEvent) -> None:
        pass

    async def symbols() -> tuple[str, ...]:
        return ("NVDA",)

    supervisor = Supervisor(
        store, RealtimeConfig(), FakeReader(clock.now(), fail=True), dispatch, symbols, state
    )
    assert not await supervisor.once("news")
    actual = store.health()[0]
    assert actual.status.value == expected
    if expected == "OK":
        assert actual == original  # Failure never invents a successful heartbeat.
    await supervisor.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "feed,success,expected", [("assets", True, 55.0), ("halts", True, 55.0), ("halts", False, 55.0)]
)
async def test_RT_poll_spacing_counts_io_and_keeps_nasdaq_minute_floor(
    engine: Engine, feed: Feed, success: bool, expected: float
) -> None:
    clock = MovingClock()
    state = SystemStateStore(engine, clock, RecordingNotifier())
    store = RealtimeStore(state.ledger, SCOPE, HASH)
    waits = []

    async def dispatch(row: RealtimeEvent) -> None:
        pass

    async def symbols() -> tuple[str, ...]:
        return ("NVDA",)

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        supervisor.stopping = True

    class Reader(FakeReader):
        async def poll(self, name: Feed) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]:
            clock.instant += timedelta(seconds=5)
            self.now = clock.now()
            return await super().poll(name)

    supervisor = Supervisor(
        store,
        RealtimeConfig(),
        Reader(clock.now(), fail=not success),
        dispatch,
        symbols,
        state,
        sleep=sleep,
    )
    await supervisor._poll(feed, 60)
    assert waits == [expected]
    await supervisor.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
async def test_AC_doctor_uses_bound_reads_without_dispatching_feed_events(
    engine: Engine,
    clock: FrozenClock,
    baseline: YamlConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    automatic: bool,
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    calls: list[Feed] = []
    closed = []
    reads: Any = SimpleNamespace()

    class Reader:
        def __init__(
            self,
            settings: Settings,
            config: object,
            client: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            assert client is reads

        async def poll(self, feed: Feed) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]:
            calls.append(feed)
            return FeedHealth(
                feed=feed,
                status=HealthStatus.OK,
                observed_at=clock.now(),
                detail="Fake authenticated read",
                symbols=tuple(sorted(baseline.watchlist)) if feed == "assets" else (),
            ), (event(clock.now()),) if feed == "halts" else ()

        async def aclose(self) -> None:
            closed.append(True)

    monkeypatch.setattr(checks, "RealtimeReader", Reader)
    settings = Settings(
        _env_file=None,
        broker_account_type="CASH",
        execution_mode="AUTO_PAPER" if automatic else "MANUAL",
    )
    secrets: Any = SimpleNamespace(get=lambda name: None)
    result = await checks.checklist(
        settings, baseline, state, CAL, secrets, reads, tmp_path, SCOPE.account_id
    )
    by_name = {row.name: row for row in result}
    assert calls == ["clock", "halts", "news", "assets", "fred", "macro"] and closed == [True]
    assert by_name["learning_journal"].status == "PASS"
    assert by_name["rt_edgar"].status == by_name["rt_identification"].status == "UNVERIFIED"
    assert by_name["rt_identification"].required is automatic
    store = RealtimeStore(state.ledger, SCOPE, baseline.config_hash)
    assert store.events(pending_only=True) == (event(clock.now()),)
    assert not store.notice_delivered(event(clock.now()))
