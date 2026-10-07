"""DQ-01: independent adjusted-return credits, native fills and causal shares."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.fee_schedule import load_fee_schedule
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries, KnownSplit
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.costs import CostContext
from backend.evaluation.dividends import DistributionCredit, distribution_rates
from backend.evaluation.edge import EdgeKey
from backend.evaluation.equity import build_equity_curve
from backend.evaluation.outcomes import Outcome, simulate_outcome
from backend.tests.test_outcomes_history import bar, frozen, setup

D = Decimal


def scaled(row: Bar, factor: Decimal) -> Bar:
    return Bar.model_validate(
        {
            **row.model_dump(),
            "open": row.open * factor,
            "high": row.high * factor,
            "low": row.low * factor,
            "close": row.close * factor,
        }
    )


def dividend_history(*, split: bool = False) -> FrozenHistory:
    native: tuple[Bar, ...] = (
        bar(15),
        bar(16),
        bar(17, opening="90", high="91", low="89", closing="90"),
        bar(18, high="121", low="89"),
    )
    signal: tuple[Bar, ...] = native
    actions: tuple[KnownSplit, ...] = ()
    if split:
        native = (
            *native[:2],
            *(scaled(item, D(".5")) for item in native[2:]),
        )
        signal = tuple(scaled(item, D(".5") if i < 2 else D(1)) for i, item in enumerate(native))
        actions = (
            KnownSplit(symbol="AAPL", effective_session=date(2026, 9, 17), new_shares_per_old=D(2)),
        )
    total = tuple(scaled(item, D(".9") if i < 2 else D(1)) for i, item in enumerate(signal))
    return frozen(
        HistoryBundle(
            series=(
                HistorySeries(symbol="AAPL", adjustment="ALL", bars=total),
                HistorySeries(symbol="AAPL", adjustment="RAW", bars=native),
                HistorySeries(symbol="AAPL", adjustment="SPLIT", bars=signal),
            ),
            splits=actions,
        )
    )


@pytest.mark.parametrize("split", [False, True])
def test_DQ_01_replay_distribution_uses_preceding_held_shares_and_native_fills(split: bool) -> None:
    history = dividend_history(split=split)
    calendar = MarketCalendar(start=date(2026, 9, 1), end=date(2026, 11, 30))
    fees = load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")
    ctx = CostContext(median_dollar_volume_20=D(100000000), atr14=D(4))
    result = simulate_outcome(
        setup(cohort="REPLAY_IN_SAMPLE", stop=D(80), target=D(120)), history, ctx, calendar, fees
    )
    paper = simulate_outcome(setup(stop=D(80), target=D(120)), history, ctx, calendar, fees)
    assert len(result.distributions) == 1 and not paper.distributions
    assert result.distributions[0].amount == D(1000)
    assert result.distributions[0].qty == (200 if split else 100)
    assert result.distributions[0].per_share == (D(5) if split else D(10))
    extra_taf = D(".02") if split else D(0)
    assert result.net_money == D("2994.71") - extra_taf
    assert paper.net_money == D("1994.71") - extra_taf
    assert result.entry_fill == paper.entry_fill and result.exit_fill == paper.exit_fill
    assert Outcome.from_recorded(result.model_dump(mode="json")) == result
    key = EdgeKey(
        playbook=result.setup.playbook,
        variant="baseline",
        cohort="REPLAY_IN_SAMPLE",
        disposition="APPROVED",
    )
    curve = build_equity_curve(
        key,
        (result,),
        history,
        calendar,
        initial_equity=D(20000),
        start=date(2026, 9, 15),
        end=date(2026, 9, 18),
    ).curve
    assert curve is not None
    assert tuple(point.equity for point in curve.points) == (
        D(20000),
        D("19994.99"),
        D("19994.99"),
        D("22994.71") - extra_taf,
    )


def test_DQ_01_no_distribution_on_entry_day_and_future_factor_cancels() -> None:
    history = dividend_history()
    calendar = MarketCalendar(start=date(2026, 9, 1), end=date(2026, 11, 30))
    fees = load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")
    result = simulate_outcome(
        setup(
            cohort="REPLAY_IN_SAMPLE", decision_session=date(2026, 9, 16), stop=D(80), target=D(120)
        ),
        history,
        CostContext(median_dollar_volume_20=D(100000000), atr14=D(4)),
        calendar,
        fees,
    )
    assert not result.distributions
    series = tuple(
        HistorySeries(
            symbol=item.symbol,
            adjustment=item.adjustment,
            bars=tuple(scaled(row, D(".8")) for row in item.bars),
        )
        if item.adjustment == "ALL"
        else item
        for item in history.bundle.series
    )
    changed = frozen(HistoryBundle(series=series))
    assert distribution_rates(changed, "AAPL", date(2026, 9, 17)) == distribution_rates(
        history, "AAPL", date(2026, 9, 17)
    )


@pytest.mark.parametrize("fault", ["ambiguous", "reversal"])
def test_DQ_01_ambiguous_distribution_is_not_guessed(fault: str) -> None:
    history = dividend_history()
    total = history.bundle.for_symbol("AAPL", "ALL")
    bars = list(total.bars)
    if fault == "ambiguous":
        bars[0] = bars[0].model_copy(update={"high": bars[0].high + D(".01")})
    else:
        bars[2] = scaled(history.bundle.for_symbol("AAPL", "SPLIT").bars[2], D(".8"))
    changed = frozen(
        HistoryBundle(
            series=tuple(
                HistorySeries(symbol="AAPL", adjustment="ALL", bars=tuple(bars))
                if item.adjustment == "ALL"
                else item
                for item in history.bundle.series
            )
        )
    )
    with pytest.raises(DataIntegrityError):
        distribution_rates(changed, "AAPL")


def test_DQ_01_distribution_schema_refuses_invented_money() -> None:
    with pytest.raises(ValidationError):
        DistributionCredit(session=date(2026, 9, 17), qty=100, per_share=D(10), amount=D(1001))
