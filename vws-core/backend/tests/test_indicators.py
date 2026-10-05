"""R-02/R-03/R-13/DAT-02/GD-03: independently hand-computed indicator fixtures."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, cast

import numpy as np
import pytest
from pydantic import ValidationError

from backend.agents import indicators
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar


def _prices(*values: int) -> tuple[Decimal, ...]:
    return tuple(Decimal(value).quantize(Decimal("0.01")) for value in values)


def _bar(index: int, *, high: int, low: int, close: int, volume: int = 1) -> Bar:
    return Bar(
        timestamp=datetime(2026, 9, 21, 4, tzinfo=UTC) + timedelta(days=index),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
    )


def test_gd03_ema_sma_seed_hand_computed_and_internal_unrounded_recursion() -> None:
    assert indicators.ema(_prices(1, 2, 3, 4, 8), 3) == (
        None,
        None,
        Decimal("2.00"),
        Decimal("3.00"),
        Decimal("5.50"),
    )
    # Seed 1.50, then 2/3*3+1/3*1.50=2.50; alpha never rounds internally.
    assert indicators.ema(_prices(1, 2, 3), 2) == (None, Decimal("1.50"), Decimal("2.50"))
    assert indicators.ema(_prices(7), 1) == (Decimal("7.00"),)


@pytest.mark.parametrize("period", [20, 50, 200])
def test_gd03_ema_required_periods_seed_and_exact_warmup(period: int) -> None:
    assert indicators.ema(_prices(*(10 for _ in range(period - 1))), period) == (None,) * (
        period - 1
    )
    assert indicators.ema(_prices(*(10 for _ in range(period))), period)[-1] == Decimal("10.00")


def test_gd03_rsi_wilder_hand_computed_gains_losses_and_recurrence() -> None:
    # Changes +1,-1,+2: initial gain=1, loss=1/3, RSI=75.
    # Next -1: gain=2/3, loss=5/9; ratio=6/5, RSI=600/11.
    assert indicators.rsi(_prices(10, 11, 10, 12, 11), 3) == (
        None,
        None,
        None,
        Decimal("75.000000"),
        Decimal("54.545455"),
    )
    assert indicators.rsi(_prices(10, 11, 12), 2)[-1] == Decimal("100.000000")
    assert indicators.rsi(_prices(12, 11, 10), 2)[-1] == Decimal("0.000000")
    assert indicators.rsi(_prices(10, 10, 10), 2)[-1] is None
    assert indicators.rsi(_prices(10), 14) == (None,)


def test_gd03_rsi14_wilder_initial_average_hand_computed() -> None:
    # Fourteen changes: seven +2 and seven -1 => gains=1, losses=.5 => RSI=200/3.
    prices = tuple(
        Decimal(10 + 2 * (index // 2) + (2 if index % 2 else 0) - index // 2) for index in range(15)
    )
    assert indicators.rsi(prices)[-1] == Decimal("66.666667")


def test_gd03_macd_hand_computed_fast_slow_signal_histogram() -> None:
    result = indicators.macd(_prices(1, 2, 3, 4, 8), fast=2, slow=3, signal=2)
    assert result.line == (None, None, Decimal("0.50"), Decimal("0.50"), Decimal("1.00"))
    assert result.signal == (None, None, None, Decimal("0.50"), Decimal("0.83"))
    assert result.histogram == (None, None, None, Decimal("0.00"), Decimal("0.17"))
    assert indicators.macd(_prices(10, 11)).line == (None, None)
    with pytest.raises(ValidationError):
        result.line = ()


def test_gd03_macd12_26_9_default_linear_fixture_and_signal_warmup() -> None:
    result = indicators.macd(_prices(*range(1, 41)))
    # A linear sequence has SMA-seeded EMA lag (n-1)/2: MACD=(25-11)/2=7.
    assert result.line[:25] == (None,) * 25
    assert result.line[25:] == (Decimal("7.00"),) * 15
    assert result.signal[:33] == (None,) * 33
    assert result.signal[33:] == (Decimal("7.00"),) * 7
    assert result.histogram[33:] == (Decimal("0.00"),) * 7


def test_gd03_atr_wilder_hand_computed_gap_and_recursive_average() -> None:
    bars = (
        _bar(0, high=11, low=9, close=10),
        _bar(1, high=13, low=11, close=12),
        _bar(2, high=14, low=10, close=11),
        _bar(3, high=12, low=10, close=11),
    )
    # True ranges 2,3,4 seed=3; next=(2*3+2)/3=8/3.
    assert indicators.atr(bars, 3) == (None, None, Decimal("3.00"), Decimal("2.67"))
    assert indicators.atr(bars[:1], 1) == (Decimal("2.00"),)
    assert indicators.atr(bars[:1]) == (None,)


def test_gd03_atr14_zero_range_is_zero_not_nan() -> None:
    bars = tuple(_bar(index, high=10, low=10, close=10) for index in range(14))
    assert indicators.atr(bars)[-1] == Decimal("0.00")


def test_gd03_rvol_hand_computed_excludes_current_and_zero_baseline() -> None:
    assert indicators.rvol((10, 20, 30, 60), 3) == (None, None, None, Decimal("3.000000"))
    assert indicators.rvol((0, 0, 0, 60), 3)[-1] is None
    assert indicators.rvol((10, 20, 30, 0), 3)[-1] == Decimal("0.000000")
    assert indicators.rvol((100,) * 20 + (150,))[-1] == Decimal("1.500000")


def test_gd03_anchored_vwap_hand_computed_hlc_typical_prices_and_zero_volume() -> None:
    bars = (
        _bar(0, high=12, low=9, close=9, volume=3),
        _bar(1, high=15, low=12, close=12, volume=6),
        _bar(2, high=21, low=18, close=18, volume=9),
    )
    # Typical prices 10,13,19; cumulative 30/3,108/9,279/18.
    assert indicators.anchored_vwap(bars, 0) == (
        Decimal("10.00"),
        Decimal("12.00"),
        Decimal("15.50"),
    )
    assert indicators.anchored_vwap(bars, 1) == (None, Decimal("13.00"), Decimal("16.60"))
    zero = _bar(0, high=12, low=9, close=9, volume=0)
    assert indicators.anchored_vwap((zero,), 0) == (None,)


@pytest.mark.parametrize("period", [0, -1, 10_001, True, Decimal(2), "2", None])
def test_r02_gd03_invalid_periods_fail_closed(period: object) -> None:
    with pytest.raises(DataIntegrityError):
        indicators.ema(_prices(1), cast(int, period))


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        1,
        1.0,
        "1.00",
        Decimal("1.001"),
        Decimal(0),
        Decimal(-1),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("10000000000000"),
    ],
)
def test_r13_gd03_price_input_never_coerces_float_missing_subcent_or_invalid(value: object) -> None:
    with pytest.raises(DataIntegrityError):
        indicators.ema(cast(tuple[Decimal, ...], (value,)), 1)


@pytest.mark.parametrize("value", [(), [], [Decimal("1.00")], None])
def test_r02_gd03_nonimmutable_or_empty_prices_fail_closed(value: object) -> None:
    with pytest.raises(DataIntegrityError):
        indicators.rsi(cast(tuple[Decimal, ...], value))


@pytest.mark.parametrize(
    "value", [(), [], (True,), (-1,), (1.0,), (Decimal(1),), (None,), (2**53 + 1,)]
)
def test_r13_dat02_volume_input_requires_whole_exact_counts(value: object) -> None:
    with pytest.raises(DataIntegrityError):
        indicators.rvol(cast(tuple[int, ...], value), 1)


@pytest.mark.parametrize("value", [(), [], (None,)])
def test_r02_dat02_bar_input_fail_closed(value: object) -> None:
    with pytest.raises(DataIntegrityError):
        indicators.atr(cast(tuple[Bar, ...], value))


def test_dat02_forged_bar_and_nonmonotonic_bars_fail_closed() -> None:
    bar = _bar(0, high=12, low=10, close=11)
    with pytest.raises(DataIntegrityError):
        indicators.atr((bar.model_copy(update={"high": Decimal(1)}),))
    for values in ((bar, bar), (_bar(1, high=12, low=10, close=11), bar)):
        with pytest.raises(DataIntegrityError):
            indicators.atr(values)


@pytest.mark.parametrize("anchor", [-1, 1, True, None, Decimal(0)])
def test_gd03_invalid_anchor_index_fail_closed(anchor: object) -> None:
    with pytest.raises(DataIntegrityError):
        indicators.anchored_vwap((_bar(0, high=12, low=10, close=11),), cast(int, anchor))


def test_gd03_invalid_macd_period_order_and_forged_output_models() -> None:
    with pytest.raises(DataIntegrityError):
        indicators.macd(_prices(1), 3, 3, 1)
    for values in (
        {"line": (), "signal": (), "histogram": ()},
        {"line": (Decimal(1),), "signal": (), "histogram": (None,)},
        {"line": (Decimal("0.001"),), "signal": (None,), "histogram": (None,)},
    ):
        with pytest.raises(ValidationError):
            indicators.MACDSeries.model_validate(values)


@pytest.mark.parametrize("function", [indicators.ema, indicators.rsi, indicators.macd])
def test_r02_gd03_unexpected_numpy_fault_is_typed(
    function: Callable[..., object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("untrusted computational failure")

    monkeypatch.setattr(np, "asarray", broken)
    with pytest.raises(DataIntegrityError, match="computation failed"):
        if function is indicators.ema:
            function(_prices(1), 1)
        else:
            function(_prices(1))


def test_r02_gd03_nonfinite_computation_is_rejected_and_outputs_are_context_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(DataIntegrityError):
        indicators._export(np.asarray([np.inf], dtype=np.float64), Decimal("0.01"))
    expected = indicators.ema(_prices(1, 2, 3, 4, 8), 3)
    with localcontext() as context:
        context.prec = 2
        assert (
            indicators.ema(
                (
                    Decimal("1.00"),
                    Decimal("2.00"),
                    Decimal("3.00"),
                    Decimal("4.00"),
                    Decimal("8.00"),
                ),
                3,
            )
            == expected
        )


def test_gd03_indicator_prefix_is_unchanged_by_future_observations() -> None:
    prices = _prices(*range(1, 42))
    for prefix in (20, 26, 33, 40):
        assert indicators.ema(prices, 20)[:prefix] == indicators.ema(prices[:prefix], 20)
        assert indicators.rsi(prices)[:prefix] == indicators.rsi(prices[:prefix])
        assert indicators.macd(prices).line[:prefix] == indicators.macd(prices[:prefix]).line
    bars = tuple(_bar(index, high=12, low=10, close=11, volume=index + 1) for index in range(20))
    assert indicators.atr(bars)[:16] == indicators.atr(bars[:16])
    assert indicators.anchored_vwap(bars, 0)[:16] == indicators.anchored_vwap(bars[:16], 0)
    assert indicators.rvol(tuple(range(30)), 20)[:25] == indicators.rvol(tuple(range(25)), 20)
