"""PF-01: pandas/numpy calculations with the reference's exact public boundary."""

from decimal import Decimal

import numpy as np
import pandas as pd

from backend.agents.indicators import (
    MICRO,
    Array,
    MACDSeries,
    Series,
    _bars,
    _export,
    _fail_closed,
    _period,
    _prices,
    _volumes,
)
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.data_layer import Bar
from backend.indicators.seeding import sma_seed


def average(values: Array, period: int, alpha: np.float64) -> Array:
    """SMA seed followed by compiled adjust=False recursion; no future rows."""
    result = np.full(values.shape, np.nan, dtype=np.float64)
    if len(values) >= period:
        seeded = np.concatenate(
            (np.asarray([sma_seed(values, period)], dtype=np.float64), values[period:])
        )
        result[period - 1 :] = (
            pd.Series(seeded)
            .ewm(alpha=float(alpha), adjust=False)
            .mean()
            .to_numpy(dtype=np.float64)
        )
    return result


@_fail_closed
def ema(prices: tuple["Decimal", ...], period: int) -> Series:
    count = _period(period)
    return _export(average(_prices(prices), count, np.float64(2) / (count + 1)), CENT)


@_fail_closed
def rsi(prices: tuple["Decimal", ...], period: int = 14) -> Series:
    count, values = _period(period), _prices(prices)
    change = np.diff(values)
    gains = average(np.maximum(change, 0), count, np.float64(1) / count)
    losses = average(np.maximum(-change, 0), count, np.float64(1) / count)
    computed = np.full(gains.shape, np.nan, dtype=np.float64)
    positive = losses > 0
    computed[positive] = 100 - 100 / (1 + gains[positive] / losses[positive])
    computed[(losses == 0) & (gains > 0)] = 100
    return _export(np.concatenate((np.asarray([np.nan], dtype=np.float64), computed)), MICRO)


@_fail_closed
def atr(bars: tuple[Bar, ...], period: int = 14) -> Series:
    count, checked = _period(period), _bars(bars)
    high = _prices(tuple(bar.high for bar in checked))
    low = _prices(tuple(bar.low for bar in checked))
    close = _prices(tuple(bar.close for bar in checked))
    ranges = high - low
    if len(checked) > 1:
        ranges[1:] = np.maximum(
            np.maximum(ranges[1:], np.abs(high[1:] - close[:-1])), np.abs(low[1:] - close[:-1])
        )
    return _export(average(ranges, count, np.float64(1) / count), CENT)


@_fail_closed
def macd(
    prices: tuple["Decimal", ...], fast: int = 12, slow: int = 26, signal: int = 9
) -> MACDSeries:
    fast, slow, signal = _period(fast), _period(slow), _period(signal)
    if fast >= slow:
        raise DataIntegrityError("PF-01: MACD fast period must precede slow period")
    values = _prices(prices)
    line = average(values, fast, np.float64(2) / (fast + 1)) - average(
        values, slow, np.float64(2) / (slow + 1)
    )
    signal_line = np.full(values.shape, np.nan, dtype=np.float64)
    if len(values) >= slow:
        signal_line[slow - 1 :] = average(line[slow - 1 :], signal, np.float64(2) / (signal + 1))
    return MACDSeries(
        line=_export(line, CENT),
        signal=_export(signal_line, CENT),
        histogram=_export(line - signal_line, CENT),
    )


@_fail_closed
def rvol(volumes: tuple[int, ...], period: int = 20) -> Series:
    count, values = _period(period), _volumes(volumes)
    prior = (
        pd.Series(values)
        .shift(1)
        .rolling(window=count, min_periods=count)
        .mean()
        .to_numpy(dtype=np.float64)
    )
    result = np.full(values.shape, np.nan, dtype=np.float64)
    np.divide(values, prior, out=result, where=prior > 0)
    return _export(result, MICRO)


@_fail_closed
def anchored_vwap(bars: tuple[Bar, ...], anchor_index: int) -> Series:
    checked = _bars(bars)
    if type(anchor_index) is not int or not 0 <= anchor_index < len(checked):
        raise DataIntegrityError("PF-01: AVWAP anchor must identify an input bar")
    high, low, close = (
        _prices(tuple(bar.high for bar in checked)),
        _prices(tuple(bar.low for bar in checked)),
        _prices(tuple(bar.close for bar in checked)),
    )
    volume = _volumes(tuple(bar.volume for bar in checked))
    cumulative_volume = np.cumsum(volume[anchor_index:], dtype=np.float64)
    weighted = np.cumsum(
        (high + low + close)[anchor_index:] / 3 * volume[anchor_index:], dtype=np.float64
    )
    result = np.full(high.shape, np.nan, dtype=np.float64)
    np.divide(weighted, cumulative_volume, out=result[anchor_index:], where=cumulative_volume > 0)
    return _export(result, CENT)
