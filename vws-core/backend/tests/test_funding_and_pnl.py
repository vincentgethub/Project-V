"""FN/PL: retries/rollback, urgent withdrawal and hand-computed flow-adjusted series."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import CashFlow, DailyPnL, PortfolioState
from backend.core.errors import DataIntegrityError, ReconciliationError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.funding.models import Activity
from backend.funding.tracker import FundingTracker
from backend.pnl.models import DayInput, PnLDay, build_day
from backend.pnl.stats import statistics
from backend.pnl.storage import read_days, record_day


def baseline(ledger: Ledger) -> PortfolioState:
    return ledger.append(
        PortfolioState,
        account_id="tax",
        account_type="CASH",
        as_of=ledger.clock.now() - timedelta(hours=1),
        equity=Decimal(1000),
        cash=Decimal(1000),
        settled_cash=Decimal(1000),
        positions={},
        high_water_mark=Decimal(1100),
        day_start_equity=Decimal(1000),
    )


def activity(
    clock: FrozenClock,
    *,
    amount: str = "100",
    kind: str = "CSD",
    identity: str = "one",
    historical: bool = False,
) -> Activity:
    when = clock.now() - timedelta(days=1) if historical else clock.now()
    return Activity(
        account_id="tax",
        env="PAPER",
        activity_id=identity,
        type=kind,
        amount=Decimal(amount),
        date=when.date(),
        observed_at=clock.now(),
        occurred_at=when,
        source="BROKER",
        payload_sha256="a" * 64,
    )


def test_atomic_cash_dedup_and_no_false_gain(engine: Engine, clock: FrozenClock) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    baseline(state.ledger)
    tracker = FundingTracker(state, "tax", "PAPER")
    initial = Activity.model_validate(
        activity(clock).model_copy(
            update={
                "observed_at": clock.now() - timedelta(seconds=1),
                "occurred_at": clock.now() - timedelta(seconds=1),
            }
        )
    )
    row, fresh = tracker.record(initial)
    assert fresh and row.baseline_effect == "SCALED"
    duplicate, fresh = tracker.record(
        activity(clock).model_copy(update={"occurred_at": initial.occurred_at})
    )
    assert not fresh and duplicate.id == row.id
    with Session(engine) as session:
        portfolios = tuple(session.scalars(select(PortfolioState).order_by(PortfolioState.seq)))
        assert len(portfolios) == 2 and len(tuple(session.scalars(select(CashFlow)))) == 1
        latest = portfolios[-1]
        assert (
            latest.equity,
            latest.high_water_mark,
            latest.day_start_equity,
            latest.settled_cash,
        ) == (Decimal(1100), Decimal(1210), Decimal(1100), Decimal(1000))
    state.ledger.verify_chain()


def test_historical_inclusion_and_urgent_withdrawal(engine: Engine, clock: FrozenClock) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    prior = baseline(state.ledger)
    tracker = FundingTracker(state, "tax", "PAPER")
    old, fresh = tracker.record(activity(clock, historical=True), historical_inclusion=True)
    assert fresh and old.baseline_effect == "INCLUDED" and old.portfolio_state_id == prior.id
    withdrawal = activity(clock, amount="-50", kind="CSW", identity="withdraw")
    tracker.record(withdrawal)
    message, urgent = tracker.message(withdrawal, Decimal(999))
    assert urgent and "secure your broker account" in message and "PAPER" in message
    with Session(engine) as session:
        latest = session.scalar(select(PortfolioState).order_by(PortfolioState.seq.desc()))
        assert latest is not None and latest.equity == Decimal(950)


def test_fault_rolls_back_flow_and_baseline_then_latches(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    baseline(state.ledger)
    original = state.ledger.append_in_session

    def fail(session: Session, model: type[CashFlow], **fields: object) -> CashFlow:
        if model is CashFlow:
            raise DataIntegrityError("injected activity persistence fault")
        return original(session, model, **fields)

    monkeypatch.setattr(state.ledger, "append_in_session", fail)
    with pytest.raises(ReconciliationError):
        FundingTracker(state, "tax", "PAPER").record(activity(clock))
    assert state.current() == SystemState.HALTED
    with Session(engine) as session:
        assert len(tuple(session.scalars(select(PortfolioState)))) == 1
        assert not tuple(session.scalars(select(CashFlow)))
    state.ledger.verify_chain()


def test_conflicting_id_and_unproven_inclusion_halt(engine: Engine, clock: FrozenClock) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    baseline(state.ledger)
    tracker = FundingTracker(state, "tax", "PAPER")
    with pytest.raises(ReconciliationError):
        tracker.record(activity(clock), historical_inclusion=True)
    assert state.current() == SystemState.HALTED
    tracker.record(activity(clock))
    with pytest.raises(ReconciliationError):
        tracker.record(activity(clock, amount="101"))


def day(
    clock: FrozenClock, session: date, start: str, end: str, *, flow: str = "0", owner: str = "tax"
) -> PnLDay:
    return build_day(
        DayInput(
            account_id=owner,
            env="PAPER",
            session=session,
            as_of=clock.now(),
            equity_start=Decimal(start),
            equity=Decimal(end),
            cash=Decimal(end),
            long_market_value=Decimal(0),
            external_flows=Decimal(flow),
            realized=Decimal(0),
            dividends=Decimal(0),
            interest=Decimal(0),
            fees=Decimal(0),
            source="BROKER",
            provenance_sha256="b" * 64,
        )
    )


def golden(clock: FrozenClock) -> tuple[PnLDay, ...]:
    return (
        day(clock, date(2026, 9, 23), "1000", "1100"),
        day(clock, date(2026, 9, 24), "1100", "2100", flow="1000"),
        day(clock, date(2026, 9, 25), "2100", "1440", flow="-500"),
        day(clock, date(2026, 9, 28), "1440", "1440"),
    )


def test_multiday_deposit_withdrawal_twr_golden(clock: FrozenClock) -> None:
    days = golden(clock)
    assert [row.day_pnl for row in days] == [Decimal(100), Decimal(0), Decimal(-160), Decimal(0)]
    assert [row.day_ret for row in days] == [Decimal(".1"), Decimal(0), Decimal("-.1"), Decimal(0)]
    spy = tuple(
        (session, Decimal(price))
        for session, price in [
            (date(2026, 9, 22), "100"),
            (date(2026, 9, 23), "101"),
            (date(2026, 9, 24), "102"),
            (date(2026, 9, 25), "103"),
            (date(2026, 9, 28), "104"),
        ]
    )
    stats = statistics(days, "inception", MarketCalendar(), spy_closes=spy)
    assert (
        stats.total_pnl,
        stats.average_dollars,
        stats.average_return,
        stats.twr,
        stats.spy_price_only,
    ) == (Decimal(-60), Decimal(-15), Decimal(0), Decimal("-.01"), Decimal(".04"))
    assert (stats.up, stats.down, stats.flat, stats.best_session, stats.worst_session) == (
        1,
        1,
        2,
        date(2026, 9, 23),
        date(2026, 9, 25),
    )
    assert (stats.max_drawdown, stats.drawdown_peak_session, stats.drawdown_trough_session) == (
        Decimal(".1"),
        date(2026, 9, 23),
        date(2026, 9, 25),
    )
    assert statistics(days, "today", MarketCalendar()).sessions == 1
    for window in ("week", "month", "mtd", "ytd"):
        assert statistics(days, window, MarketCalendar()).sessions == 4


def test_daily_identity_mismatch_is_computed(clock: FrozenClock) -> None:
    original = golden(clock)[0].observation
    changed = DayInput.model_validate(
        original.model_copy(update={"reported_unrealized_change": Decimal("99.98")})
    )
    result = build_day(changed)
    assert result.source == "COMPUTED" and result.alerts
    exact_cent = build_day(
        DayInput.model_validate(
            original.model_copy(update={"reported_unrealized_change": Decimal("99.99")})
        )
    )
    assert exact_cent.source == "BROKER" and not exact_cent.alerts


def test_append_daily_correction_and_separate_accounts(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    original = golden(clock)[0]
    first = record_day(ledger, original)
    assert record_day(ledger, original).id == first.id
    corrected = day(clock, original.observation.session, "1000", "1101")
    second = record_day(ledger, corrected)
    assert second.supersedes == first.id
    record_day(ledger, day(clock, original.observation.session, "1000", "1000", owner="reset"))
    assert read_days(ledger, "tax", "PAPER") == (corrected,)
    assert read_days(ledger, "tax", "LIVE") == ()
    with Session(engine) as session:
        assert len(tuple(session.scalars(select(DailyPnL)))) == 3
    ledger.verify_chain()
    with pytest.raises(DataIntegrityError):
        statistics(
            (corrected, day(clock, date(2026, 9, 24), "1101", "1101", owner="reset")),
            "inception",
            MarketCalendar(),
        )
