"""LJ/RT/EVT/AC: safety boundaries, durable faults and full-session evidence."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import EventsPolicy, RealtimeConfig, Settings, load_yaml_config
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.learning.journal import Cause, MistakeJournal, Observation
from backend.ops.macro_events import MacroEvent
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import (
    REQUIRED,
    ContextTag,
    Feed,
    FeedHealth,
    HealthStatus,
    RealtimeContext,
    RealtimeEvent,
)
from backend.realtime.policy import clock_status, context, exit_event, expiry_session
from backend.realtime.storage import HealthSample, RealtimeStore, healthy_sessions
from backend.realtime.supervisor import Supervisor
from backend.tests.test_system_state import RecordingNotifier

SCOPE = ControlScope(account_id="w-paper-fixture", environment="PAPER")
HASH = "a" * 64
CAL = MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def health(now: datetime, *, bad: Feed | None = None) -> tuple[FeedHealth, ...]:
    return tuple(
        FeedHealth(
            feed=name,
            status=HealthStatus.UNAVAILABLE if name == bad else HealthStatus.OK,
            observed_at=now,
            detail="Synthetic verified heartbeat",
            symbols=("NVDA",) if name == "assets" else (),
        )
        for name in (*REQUIRED, "fred")
    )


def event(now: datetime, **updates: object) -> RealtimeEvent:
    return RealtimeEvent.model_validate(
        {
            "feed": "halts",
            "provider_id": "fixture-1",
            "kind": "HALT",
            "symbol": "NVDA",
            "occurred_at": now,
            "observed_at": now,
            "expires_at": now + timedelta(days=10),
            **updates,
        }
    )


def observation(now: datetime, **updates: object) -> Observation:
    return Observation.model_validate(
        {
            "trade_id": UUID(int=1),
            "proposal_id": UUID(int=2),
            "scope": SCOPE,
            "symbol": "NVDA",
            "playbook": "TREND_50EMA",
            "at": now,
            "entry_at": now - timedelta(days=1),
            "exit_at": now,
            "entry_price": Decimal(100),
            "exit_price": Decimal(98),
            "r_after_costs": Decimal("-1.1"),
            "stop": Decimal(98),
            "target": Decimal(104),
            **updates,
        }
    )


@pytest.mark.parametrize(
    ("ms", "expected"),
    [
        (0, "OK"),
        (500, "OK"),
        (501, "DEGRADED"),
        (2000, "DEGRADED"),
        (2001, "UNAVAILABLE"),
        (-2001, "UNAVAILABLE"),
    ],
)
def test_RT_01_clock_boundaries(ms: int, expected: str) -> None:
    assert clock_status(Decimal(ms), RealtimeConfig()).value == expected


@pytest.mark.parametrize("bad", REQUIRED)
@pytest.mark.parametrize("auto", [False, True])
def test_RT_10_missing_required_feed_only_blocks_auto(
    clock: FrozenClock, bad: Feed, auto: bool
) -> None:
    row = context(
        SCOPE,
        "NVDA",
        clock.now(),
        HASH,
        RealtimeConfig(),
        EventsPolicy(),
        health(clock.now(), bad=bad),
        (),
        (),
        CAL,
        auto=auto,
        schedules_verified=True,
    )
    assert row.entry_multiplier == (0 if auto else 1) and bool(row.warnings)
    assert ContextTag.UNAVAILABLE in row.tags


def test_RT_10_stale_news_and_unconfirmed_calendar_fail_closed(clock: FrozenClock) -> None:
    rows = tuple(
        row.model_copy(update={"observed_at": clock.now() - timedelta(seconds=121)})
        if row.feed == "news"
        else row
        for row in health(clock.now())
    )
    result = context(
        SCOPE,
        "NVDA",
        clock.now(),
        HASH,
        RealtimeConfig(),
        EventsPolicy(),
        rows,
        (),
        (),
        CAL,
        auto=True,
        schedules_verified=False,
    )
    assert result.blocked and len(result.warnings) == 2


@pytest.mark.parametrize("action", ["annotate", "half_size", "no_new_entries"])
def test_EVT_fomc_exact_reducing_factor(clock: FrozenClock, action: str) -> None:
    macro = MacroEvent(
        date=clock.now().date(),
        release_at=clock.now(),
        event="FOMC",
        source="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    )
    row = context(
        SCOPE,
        "NVDA",
        clock.now(),
        HASH,
        RealtimeConfig(),
        EventsPolicy.model_validate({"fomc": action}),
        health(clock.now()),
        (),
        (macro,),
        CAL,
        auto=True,
        schedules_verified=True,
    )
    assert (
        Decimal(40) * row.entry_multiplier
        == {"annotate": 40, "half_size": 20, "no_new_entries": 0}[action]
    )
    assert ContextTag.FOMC in row.tags


@pytest.mark.parametrize("auto", [False, True])
def test_RT_halt_resume_does_not_gate_held_exit(clock: FrozenClock, auto: bool) -> None:
    halted = event(clock.now() - timedelta(seconds=1))
    row = context(
        SCOPE,
        "NVDA",
        clock.now(),
        HASH,
        RealtimeConfig(),
        EventsPolicy(),
        health(clock.now()),
        (halted,),
        (),
        CAL,
        auto=auto,
        schedules_verified=True,
    )
    assert row.blocked and not exit_event(halted, RealtimeConfig(), held=True)
    resumed = event(clock.now(), kind="RESUME", provider_id="resume-1")
    row = context(
        SCOPE,
        "NVDA",
        clock.now(),
        HASH,
        RealtimeConfig(),
        EventsPolicy(),
        health(clock.now()),
        (resumed, halted),
        (),
        CAL,
        auto=auto,
        schedules_verified=True,
    )
    assert not row.blocked


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("DILUTION", False), ("DELIST", True), ("NEWS_NEG", False), ("HALT", False)],
)
def test_RT_11_only_configured_confirmed_exit(
    kind: str, expected: bool, clock: FrozenClock
) -> None:
    row = event(clock.now(), kind=kind)
    assert exit_event(row, RealtimeConfig(), held=True) is expected
    assert not exit_event(row, RealtimeConfig(), held=False)


@pytest.mark.parametrize("value", [Decimal("1.0001"), 1.5, Decimal("NaN"), Decimal("-0.1")])
def test_EVT_no_size_increase(value: object, clock: FrozenClock) -> None:
    with pytest.raises(ValidationError):
        RealtimeContext.model_validate(
            {
                "scope": SCOPE,
                "symbol": "NVDA",
                "as_of": clock.now(),
                "policy_sha256": HASH,
                "entry_multiplier": value,
                "blocked": False,
            }
        )


def test_RT_09_holiday_opex_and_quarterly_witching() -> None:
    assert expiry_session(date(2025, 4, 17), CAL) == (ContextTag.OPEX,)
    assert expiry_session(date(2025, 4, 18), CAL) == ()
    assert expiry_session(date(2026, 9, 18), CAL) == (ContextTag.OPEX, ContextTag.WITCHING)


@pytest.mark.parametrize(
    ("updates", "cause"),
    [
        ({}, Cause.UNCLASSIFIED),
        ({"gap_open": Decimal(97)}, Cause.GAP_THROUGH_STOP),
        (
            {"fill_vs_model_bps": Decimal(11), "bucket_p90_bps": Decimal(10)},
            Cause.SLIPPAGE_ABOVE_MODEL,
        ),
        ({"context_tags": (ContextTag.NEWS_NEG,)}, Cause.NEWS_SHOCK),
        ({"oos_abs_mean": Decimal("0.5"), "oos_stddev": Decimal("0.6")}, Cause.NORMAL_VARIANCE),
    ],
)
def test_LJ_goldens_dedupe_and_replay(
    engine: Engine, clock: FrozenClock, updates: dict[str, object], cause: Cause
) -> None:
    store = MistakeJournal(Ledger(engine, clock), SCOPE)
    row = observation(clock.now(), **updates)
    added = store.record(row)
    assert added == (2 if cause == Cause.SLIPPAGE_ABOVE_MODEL else 1)
    frozen = store.replay()
    assert store.record(row) == 0 and store.replay() == frozen
    assert store.rows()[0].cause_tag == cause
    assert "w-paper-fixture" not in store.recent()
    with pytest.raises(DataIntegrityError, match="changed"):
        store.record(row.model_copy(update={"exit_price": Decimal(97)}))


def test_AC_durable_event_duplicates_and_flag(engine: Engine, clock: FrozenClock) -> None:
    store = RealtimeStore(Ledger(engine, clock), SCOPE, HASH)
    row = event(clock.now())
    with pytest.raises(DataIntegrityError, match="durable"):
        store.flag_once(row, held=True)
    assert store.receive(row) and not store.receive(row)
    with pytest.raises(DataIntegrityError, match="changed"):
        store.receive(row.model_copy(update={"text": "changed"}))
    assert store.flag_once(row, held=True) and not store.flag_once(row, held=True)
    assert len(store.events(pending_only=True)) == 1
    store.complete(row)
    store.complete(row)
    assert store.events(pending_only=True) == ()
    assert len(store.events()) == 1


def session_samples(day: date) -> tuple[HealthSample, ...]:
    opened, closed = CAL.session_open(day), CAL.session_close(day)
    result = []
    now = opened
    while now <= closed:
        result.append(
            HealthSample(
                scope=SCOPE, policy_sha256=HASH, at=now, symbols=("NVDA",), feeds=health(now)[:4]
            )
        )
        now += timedelta(seconds=30)
    return tuple(result)


def test_RT_14_five_whole_sessions_not_closing_snapshots() -> None:
    days = CAL.previous_sessions(date(2026, 9, 30), 5)
    samples = tuple(row for day in days for row in session_samples(day))
    now = datetime(2026, 9, 30, 0, tzinfo=UTC)
    assert healthy_sessions(samples, now, CAL, RealtimeConfig()) == days
    assert (
        healthy_sessions(
            tuple(row for row in samples if row.at == CAL.session_close(row.at.date())),
            now,
            CAL,
            RealtimeConfig(),
        )
        == ()
    )
    assert healthy_sessions(samples[1:], now, CAL, RealtimeConfig()) == days[1:]
    broken = samples[:10] + samples[11:]
    assert healthy_sessions(broken, now, CAL, RealtimeConfig()) == days[1:]
    with pytest.raises(DataIntegrityError):
        healthy_sessions(samples[::-1], now, CAL, RealtimeConfig())


@dataclass
class FakeReader:
    now: datetime
    fail: bool = False

    async def poll(self, feed: Feed) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]:
        if self.fail:
            raise ProviderError("synthetic outage")
        return FeedHealth(
            feed=feed, status=HealthStatus.OK, observed_at=self.now, detail="Fake"
        ), ()

    async def stream(self, receive: object) -> None:
        raise ProviderError("synthetic stream disconnect")

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_RT_supervisor_durable_duplicate_collision_and_reconnect(
    engine: Engine, clock: FrozenClock
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    store = RealtimeStore(state.ledger, SCOPE, HASH)
    seen = []

    async def dispatch(row: RealtimeEvent) -> None:
        seen.append(row.provider_id)

    async def symbols() -> tuple[str, ...]:
        return ("NVDA",)

    reader = FakeReader(clock.now())
    supervisor = Supervisor(store, RealtimeConfig(), reader, dispatch, symbols, state)
    row = event(clock.now())
    assert await supervisor.receive(row) and not await supervisor.receive(row)
    with pytest.raises(DataIntegrityError):
        await supervisor.receive(row.model_copy(update={"text": "collision"}))
    await supervisor.drain()
    await supervisor.drain()
    assert seen == [row.provider_id]
    assert all(0 < supervisor.delay(attempt) <= 30 for attempt in range(1, 50))
    assert await supervisor.once("clock")
    reader.fail = True
    assert not await supervisor.once("clock")
    assert store.health()[0].status == HealthStatus.UNAVAILABLE
    assert state.current() == SystemState.RUNNING
    await supervisor.aclose()


@pytest.mark.parametrize("minimum", [0, 4, True])
def test_RT_14_live_session_floor(minimum: object) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"auto_live_min_rt_sessions": minimum})


def test_W_current_yaml_validated() -> None:
    from pathlib import Path

    from backend.tests.test_yaml_config import ALLOWED_SYMBOLS

    config = load_yaml_config(
        Path(__file__).resolve().parents[2] / "config/config.yaml", allowed_symbols=ALLOWED_SYMBOLS
    )
    assert config.lj.min_tag_n == 15 and config.rt.required_feeds == REQUIRED
    assert config.events_policy.pce == "annotate"
