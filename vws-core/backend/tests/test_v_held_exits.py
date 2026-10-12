"""EX-03/04: actual protected exit workflow and causal daily observations."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionOrderRecord
from backend.core.errors import ReconciliationError
from backend.core.system_state import SystemState
from backend.data.data_layer import Bar
from backend.data.history import HistorySeries
from backend.data.market_calendar import MarketCalendar
from backend.execution.exit_variants import (
    HeldEntry,
    HeldExitObservation,
    HeldQuoteObservation,
    observe_held_exit,
)
from backend.notifications.callbacks import FreshInputs
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_auto_exits import refresh_quotes
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from backend.tests.test_v_execution import variant

harness = make_research_harness
D = Decimal


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 8, 1), end=date(2026, 11, 30))


def held(calendar: MarketCalendar) -> HeldEntry:
    return HeldEntry(
        entry_id=uuid4(),
        account_id="fake-paper",
        environment="PAPER",
        symbol="AAPL",
        first_fill=calendar.session_open(date(2026, 9, 15)) + timedelta(minutes=10),
        filled_qty=5,
        entry_cost=D(500),
        entry_limit=D(101),
        initial_stop=D(95),
        variant="TRAIL_EMA20",
        hold_sessions=20,
    )


def tape(calendar: MarketCalendar) -> HistorySeries:
    days = calendar.previous_sessions(date(2026, 9, 16), 25) + (date(2026, 9, 16),)
    return HistorySeries(
        symbol="AAPL",
        adjustment="SPLIT",
        bars=tuple(
            Bar(
                timestamp=datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=4),
                open=D(100),
                high=D(150) if day == date(2026, 9, 15) else D(101),
                low=D(98),
                close=D(99) if day == days[-1] else D(100),
                volume=20000,
            )
            for day in days
        ),
    )


def test_EX_03_pre_entry_high_and_next_session_quote_do_not_retroactively_arm(
    calendar: MarketCalendar,
) -> None:
    entry = held(calendar)
    now = calendar.session_open(date(2026, 9, 17)) + timedelta(minutes=35)
    result = observe_held_exit(
        entry, tape(calendar), calendar, now, scan_delay_minutes=30, last_trade=D(150), trade_at=now
    )
    assert result.verified_peak == D(101) and not result.ema_signal
    observed_at = calendar.session_close(date(2026, 9, 16)) - timedelta(minutes=5)
    peak = HeldQuoteObservation(
        entry_id=entry.entry_id,
        account_id=entry.account_id,
        environment="PAPER",
        symbol="AAPL",
        price=D(106),
        trade_at=observed_at,
        known_at=observed_at,
    )
    armed = observe_held_exit(
        entry, tape(calendar), calendar, now, scan_delay_minutes=30, verified_peaks=(peak,)
    )
    assert armed.ema_signal and armed.verified_peak == D(106)
    assert HeldExitObservation.recorded(armed.model_dump(mode="json")) == armed
    assert HeldQuoteObservation.recorded(peak.model_dump(mode="json")) == peak


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("state", ["RUNNING", "HALTED", "MANUAL"])
async def test_EX_03_original_policy_uses_protected_next_session_exit_during_downgrade(
    harness: Harness,
    state: str,
) -> None:
    h = harness
    variant(h, "TRAIL_EMA20")
    alert = await deliver(h)
    client = FakeTradingClient(h)
    ex = executor(h, client)

    async def observation(entry: HeldEntry, fresh: FreshInputs) -> HeldExitObservation:
        day = ex.calendar.last_completed_session(h.clock.now() - timedelta(minutes=30))
        return HeldExitObservation(
            entry=entry,
            session=day,
            known_at=ex.calendar.session_close(day) + timedelta(minutes=30),
            history_sha256="a" * 64,
            close=D(100),
            ema20=D(101),
            atr14=D(2),
            verified_peak=entry.entry_limit + (entry.entry_limit - entry.initial_stop),
        )

    ex.held_exit_observation = observation
    await ex.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, ex)
    entry_day = h.clock.now().astimezone(ex.calendar.session_open(date(2026, 9, 29)).tzinfo).date()
    next_day = ex.calendar.add_sessions(entry_day, 1)
    h.clock.current = ex.calendar.session_open(next_day) + timedelta(minutes=35)
    refresh_quotes(h)
    if state == "HALTED":
        h.state.escalate(SystemState.HALTED, "offline halt")
    elif state == "MANUAL":
        ex.modes.downgrade("MANUAL", actor="offline owner")
    await ex.monitor()
    assert len(client.posts) == 2
    assert client.posts[-1]["side"] == "sell" and client.posts[-1]["type"] == "limit"
    assert client.posts[-1]["qty"] == parent["qty"]
    assert all(row["status"] == "canceled" for row in parent["legs"])
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_03_lost_evidence_halts_entries_while_confirmed_stop_is_retained(
    harness: Harness,
) -> None:
    h = harness
    variant(h, "TRAIL_EMA20")
    alert = await deliver(h)
    client = FakeTradingClient(h)
    ex = executor(h, client)

    async def observation(entry: HeldEntry, fresh: FreshInputs) -> HeldExitObservation:
        raise AssertionError("not consumed during entry")

    ex.held_exit_observation = observation
    await ex.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, ex)
    ex.held_exit_observation = None
    with pytest.raises(ReconciliationError):
        await ex.monitor()
    assert h.state.current() == SystemState.HALTED and len(client.posts) == 1
    assert all(row["status"] == "new" for row in parent["legs"])
    with Session(h.state.engine) as session:
        rows = tuple(
            session.scalars(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
            )
        )
        assert ex._held_entry(rows[0]).variant == "TRAIL_EMA20"
    h.state.ledger.verify_chain()
