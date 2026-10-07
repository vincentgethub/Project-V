"""PF-01: causal seeded indicators, goldens and randomized equivalence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.agents.indicators import _average
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.indicators import reference, vectorized

D = Decimal


def bars(prices: tuple[Decimal, ...]) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            timestamp=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=index),
            open=price,
            high=price + D(1),
            low=max(D("0.01"), price - D(1)),
            close=price,
            volume=10000 + index * 100,
        )
        for index, price in enumerate(prices)
    )


@settings(max_examples=60, deadline=None)
@given(
    st.lists(st.integers(min_value=1, max_value=100000), min_size=1, max_size=300),
    st.integers(min_value=1, max_value=30),
)
def test_PF_01_exact_quantized_equivalence(cents: list[int], period: int) -> None:
    prices = tuple(D(value) / 100 for value in cents)
    observed = bars(prices)
    assert vectorized.ema(prices, period) == reference.ema(prices, period)
    assert vectorized.rsi(prices, period) == reference.rsi(prices, period)
    assert vectorized.atr(observed, period) == reference.atr(observed, period)
    assert vectorized.rvol(tuple(bar.volume for bar in observed), period) == reference.rvol(
        tuple(bar.volume for bar in observed), period
    )
    assert vectorized.macd(prices) == reference.macd(prices)
    assert vectorized.anchored_vwap(observed, len(observed) // 2) == reference.anchored_vwap(
        observed, len(observed) // 2
    )
    # Before the shared quantizer, relative difference must also meet 1e-9.
    array = np.asarray(prices, dtype=np.float64)
    alpha = np.float64(2) / (period + 1)
    assert np.allclose(
        vectorized.average(array, period, alpha),
        _average(array, period, alpha),
        rtol=1e-9,
        atol=0,
        equal_nan=True,
    )


def test_PF_01_wilder_first_fourteen_sma_golden() -> None:
    values = tuple(D(100 + index) for index in range(16))
    result = vectorized.atr(bars(values))
    assert result[:13] == (None,) * 13 and result[13:] == (D(2), D(2), D(2))
    assert vectorized.rsi(values)[:14] == (None,) * 14
    assert vectorized.rsi(values)[14:] == (D(100), D(100))
    assert vectorized.rsi((D(100),) * 20) == (None,) * 20
    assert vectorized.rsi(tuple(reversed(values)))[14:] == (D(0), D(0))
    assert vectorized.rvol((0,) * 30) == (None,) * 30


def test_PF_01_no_future_values_enter_prefix() -> None:
    prices = tuple(D(100 + index) for index in range(220))
    for operation in (vectorized.ema, reference.ema):
        assert operation((*prices, D(1)), 20)[:-1] == operation(prices, 20)
    assert vectorized.rsi((*prices, D(1)))[:-1] == vectorized.rsi(prices)
    assert vectorized.atr(bars((*prices, D(1))))[:-1] == vectorized.atr(bars(prices))
    assert vectorized.macd((*prices, D(1))).line[:-1] == vectorized.macd(prices).line


@pytest.mark.parametrize(
    "operation,arguments",
    [
        (vectorized.ema, ((D(1),), True)),
        (vectorized.rsi, ((1.0,),)),
        (vectorized.atr, ((),)),
        (vectorized.macd, ((D(1),), 26, 12)),
        (vectorized.rvol, ((True,),)),
        (vectorized.anchored_vwap, (bars((D(1),)), -1)),
    ],
)
def test_PF_01_forged_inputs_fail_closed(operation: Any, arguments: tuple[Any, ...]) -> None:
    with pytest.raises(DataIntegrityError):
        operation(*arguments)
