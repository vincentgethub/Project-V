"""EX-03: independently specified close signals and protected next-open exits."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.history import HistorySeries, KnownSplit
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.costs import FeeSchedule
from backend.evaluation.outcomes import Outcome
from backend.indicators.portfolio import causal_split_ema
from backend.tests.test_outcomes_history import bar, bundle, frozen, run, setup

D = Decimal


@pytest.mark.parametrize("case", ["open", "resolved", "same_day"])
def test_EX_01_equity_uses_partial_proceeds_and_only_remaining_shares(
    case: str,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    from backend.evaluation.edge import EdgeKey
    from backend.evaluation.equity import build_equity_curve

    tape = bundle(
        (
            bar(15),
            bar(16, high="111" if case == "same_day" else "107.01", closing="105"),
            bar(
                17,
                opening="105",
                high="110.01" if case == "resolved" else "106",
                low="104",
                closing="104",
            ),
        )
    )
    result = run(
        setup(variant="SPLIT_1R", qty=5), tape, calendar, schedule, exit_variant="SPLIT_1R"
    )
    key = EdgeKey(
        playbook=result.setup.playbook, variant="SPLIT_1R", cohort="PAPER", disposition="APPROVED"
    )
    built = build_equity_curve(
        key,
        (result,),
        frozen(tape),
        calendar,
        initial_equity=D(1000),
        start=date(2026, 9, 15),
        end=date(2026, 9, 17),
    )
    assert built.status == "AVAILABLE" and built.curve is not None
    if case != "open":
        assert result.net_money is not None
        assert built.curve.points[-1].equity == D(1000) + result.net_money
    else:
        assert result.entry_fees is not None
        partial = result.partial_exits[0]
        expected = (
            D(1000)
            - D("100.02") * 5
            - result.entry_fees.total
            + D(107) * 2
            - partial.fees.total
            + D(104) * 3
        )
        assert built.curve.points[-1].equity == expected


@pytest.mark.parametrize("qty", [2, 3, 5, 100])
def test_EX_01_odd_shares_and_separate_leg_cashflows(
    qty: int,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    result = run(
        setup(qty=qty, variant="SPLIT_1R"),
        bundle(
            (
                bar(15),
                bar(16, high="107.01", closing="105"),
                bar(17, opening="105", high="110.01", low="104", closing="109"),
            )
        ),
        calendar,
        schedule,
        exit_variant="SPLIT_1R",
    )
    assert result.status == "RESOLVED" and result.reason == "TARGET"
    assert result.entry_fill is not None and result.entry_fill.qty == qty
    a = result.partial_exits[0]
    assert a.fill.qty == qty // 2 and a.fill.price == D(107)
    assert a.session == date(2026, 9, 16)
    assert result.exit_fill is not None and result.exit_fill.qty == qty - qty // 2
    assert result.exit_fill.price == D(110)
    assert result.entry_fees is not None and result.exit_fees is not None
    expected = D(107) * (qty // 2) + D(110) * (qty - qty // 2) - D("100.02") * qty
    expected -= result.entry_fees.total + a.fees.total + result.exit_fees.total
    assert result.net_money == expected
    assert result.r_multiple == (expected / (D(6) * qty)).quantize(D("0.000001"))
    assert Outcome.from_recorded(result.model_dump(mode="json")) == result


def test_EX_01_same_bar_stop_wins_over_both_targets(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    result = run(
        setup(variant="SPLIT_1R", qty=5),
        bundle((bar(15), bar(16, high="111", low="94"))),
        calendar,
        schedule,
        exit_variant="SPLIT_1R",
    )
    assert result.reason == "STOP" and not result.partial_exits
    assert result.exit_fill is not None and result.exit_fill.qty == 5


def test_EX_02_close_raise_only_applies_next_open_and_gap_is_protected(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    # Flat warm-up TR=2. Entry TR=8.01: ATR14=2.43, so close(107)-3*ATR=99.71.
    result = run(
        setup(variant="SPLIT_1R_TRAIL", qty=5),
        bundle(
            warm(calendar)
            + (
                bar(16, high="107.01", closing="107"),
                bar(17, opening="98", high="100", low="97", closing="99"),
            )
        ),
        calendar,
        schedule,
        exit_variant="SPLIT_1R_TRAIL",
    )
    assert result.reason == "GAP_STOP" and len(result.stop_moves) == 1
    move = result.stop_moves[0]
    assert move.old_stop == D(95) and move.new_stop == D("99.71")
    assert move.decided_session == date(2026, 9, 16)
    assert move.effective_session == date(2026, 9, 17)
    assert result.exit_fill is not None and result.exit_fill.qty == 3
    assert result.exit_fill.price == D("97.98")
    assert result.partial_exits[0].fill.qty == 2
    assert Outcome.from_recorded(result.model_dump(mode="json")) == result


def test_EX_01_single_share_split_is_refused(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    with pytest.raises(DataIntegrityError, match="at least two"):
        run(
            setup(variant="SPLIT_1R", qty=1),
            bundle((bar(15), bar(16))),
            calendar,
            schedule,
            exit_variant="SPLIT_1R",
        )


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 8, 1), end=date(2026, 11, 30))


@pytest.fixture(scope="module")
def schedule() -> FeeSchedule:
    from pathlib import Path

    from backend.data.fee_schedule import load_fee_schedule

    return load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")


def warm(calendar: MarketCalendar) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            timestamp=datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=4),
            open=D(100),
            high=D(101),
            low=D(99),
            close=D(100),
            volume=20000,
        )
        for day in calendar.previous_sessions(date(2026, 9, 15), 25)
    ) + (bar(15),)


def trail(
    calendar: MarketCalendar, schedule: FeeSchedule, bars: tuple[Bar, ...], **kw: Any
) -> Outcome:
    return run(
        setup(variant="TRAIL_EMA20"),
        bundle(warm(calendar) + bars),
        calendar,
        schedule,
        exit_variant="TRAIL_EMA20",
        **kw,
    )


@pytest.mark.parametrize("peak,exit_reason", [("106.01", "HISTORY_PENDING"), ("106.02", "SIGNAL")])
def test_EX_03_one_R_boundary_and_next_open(
    peak: str,
    exit_reason: str,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    result = trail(
        calendar,
        schedule,
        (
            bar(16, high=peak, closing="105"),
            bar(17, opening="105", high="105.01", low="98", closing="99"),
            bar(18, opening="102", high="109", low="96", closing="104"),
        ),
    )
    assert result.reason == exit_reason
    if exit_reason == "SIGNAL":
        assert result.exit_session == date(2026, 9, 18)
        assert result.exit_fill is not None and result.exit_fill.price == D("101.97")
        assert result.entry_fill is not None and result.entry_fill.price == D("100.02")
        assert result.initial_risk_money == D(600)
    else:
        assert result.status == "OPEN" and result.exit_fill is None


def test_EX_03_stop_before_target_and_signal(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    result = trail(calendar, schedule, (bar(16, high="111", low="94"),))
    assert result.reason == "STOP" and result.exit_session == date(2026, 9, 16)


def test_EX_03_gap_stop_overrides_pending_close_exit(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    result = trail(
        calendar,
        schedule,
        (
            bar(16, high="106.02", closing="105"),
            bar(17, opening="105", high="105.01", low="98", closing="99"),
            bar(18, opening="90", high="91", low="89", closing="90"),
        ),
    )
    assert result.reason == "GAP_STOP"
    assert result.exit_fill is not None and result.exit_fill.price == D("89.98")


def test_EX_03_missing_warmup_is_unavailable(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    result = run(
        setup(variant="TRAIL_EMA20"),
        bundle((bar(15), bar(16))),
        calendar,
        schedule,
        exit_variant="TRAIL_EMA20",
    )
    assert result.status == "INCOMPLETE" and result.entry_fill is None


def test_EX_03_split_ema_preserves_economic_close_and_future_causality(
    calendar: MarketCalendar,
) -> None:
    before = warm(calendar)
    action = KnownSplit(symbol="AAPL", effective_session=date(2026, 9, 16), new_shares_per_old=D(2))
    split_bar = bar(16, opening="50", high="51", low="49", closing="50")
    future = bar(17, opening="1", high="900", low="1", closing="899")
    native = HistorySeries(symbol="AAPL", adjustment="RAW", bars=before + (split_bar, future))
    array = causal_split_ema(native, (action,), 20, date(2026, 9, 16))
    assert array[date(2026, 9, 15)] == D(100)
    assert array[date(2026, 9, 16)] == D(50)
    assert date(2026, 9, 17) not in array
    original = HistorySeries(symbol="AAPL", adjustment="RAW", bars=before)
    assert causal_split_ema(original, (), 20, date(2026, 9, 15)) == {
        day: value for day, value in array.items() if day <= date(2026, 9, 15)
    }


def test_EX_03_unregistered_intent_and_unknown_exit_refused(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    with pytest.raises(DataIntegrityError, match="supported exit variant"):
        run(
            setup(),
            bundle(warm(calendar) + (bar(16),)),
            calendar,
            schedule,
            exit_variant="TRAIL_EMA20",
        )
    with pytest.raises(DataIntegrityError, match="supported exit variant"):
        run(
            setup(), bundle(warm(calendar) + (bar(16),)), calendar, schedule, exit_variant="UNKNOWN"
        )
