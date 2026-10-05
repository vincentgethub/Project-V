"""R-03/R-04/R-13/GD-03: pure indicators with exact immutable boundaries.

All arrays and float64 arithmetic stay inside this module. Prices supplied by
callers must already be positive Decimal cents; computed price-valued outputs
use ROUND_HALF_EVEN cents, dimensionless outputs use six decimal places. None
means insufficient observations or an undefined ratio, never neutral evidence.
EMA uses a simple-average seed; Wilder averages use a simple-average seed and
alpha=1/period. RSI needs period changes, ATR starts with first-bar high-low.
RVOL compares each volume with the preceding period volumes, excluding itself.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from functools import wraps
from typing import ParamSpec, Self, TypeVar

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from backend.core.errors import DataIntegrityError
from backend.core.money import CENT, decimal_money, validate_cent_price
from backend.data.data_layer import Bar
from backend.domain.models import FrozenModel, Money

Series = tuple[Decimal | None, ...]
Array = NDArray[np.float64]
MICRO = Decimal("0.000001")
Arguments = ParamSpec("Arguments")
Result = TypeVar("Result")


def _fail_closed(function: Callable[Arguments, Result]) -> Callable[Arguments, Result]:
    """R-02: unexpected indicator failures are typed and cannot produce evidence."""

    @wraps(function)
    def checked(*args: Arguments.args, **kwargs: Arguments.kwargs) -> Result:
        try:
            return function(*args, **kwargs)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("GD-03: indicator computation failed") from exc

    return checked


def _period(value: int) -> int:
    """R-02/GD-03: a period is a bounded positive whole observation count."""
    if type(value) is not int or not 1 <= value <= 10_000:
        raise DataIntegrityError("GD-03: indicator period must be an integer from 1 to 10000")
    return value


def _prices(values: tuple[Decimal, ...]) -> Array:
    """R-13: detach exact immutable price input before internal float math."""
    if not isinstance(values, tuple) or not values:
        raise DataIntegrityError("GD-03: indicators require a nonempty price tuple")
    for value in values:
        validate_cent_price(value)
    return np.asarray(values, dtype=np.float64)


def _volumes(values: tuple[int, ...]) -> Array:
    """R-13/DAT-02: reject fractional, boolean, negative and huge volume."""
    if not isinstance(values, tuple) or not values:
        raise DataIntegrityError("GD-03: indicators require a nonempty volume tuple")
    if any(type(value) is not int or not 0 <= value <= 2**53 for value in values):
        raise DataIntegrityError("DAT-02: volume must be a whole exact float64-safe count")
    return np.asarray(values, dtype=np.float64)


def _bars(values: tuple[Bar, ...]) -> tuple[Bar, ...]:
    """DAT-02/R-02: forged models and nonmonotonic input are rejected."""
    if not isinstance(values, tuple) or not values:
        raise DataIntegrityError("GD-03: indicators require a nonempty bar tuple")
    checked: list[Bar] = []
    try:
        for bar in values:
            item = Bar.model_validate(bar)
            item.validate_integrity()
            if checked and item.timestamp <= checked[-1].timestamp:
                raise DataIntegrityError("DAT-02: indicator bar times must increase")
            checked.append(item)
        return tuple(checked)
    except DataIntegrityError:
        raise
    except Exception as exc:
        raise DataIntegrityError("DAT-02: invalid indicator bar input") from exc


def _export(values: Array, quantum: Decimal) -> Series:
    """R-04/R-13: leave float math through a finite quantized Decimal boundary."""
    result: list[Decimal | None] = []
    with localcontext() as context:
        context.prec = 80
        for value in values:
            if np.isnan(value):
                result.append(None)
            elif not np.isfinite(value):
                raise DataIntegrityError("GD-03: nonfinite indicator computation")
            else:
                amount = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_EVEN)
                result.append(decimal_money(amount))
    return tuple(result)


def _average(values: Array, period: int, alpha: np.float64) -> Array:
    """GD-03: seed after period finite observations, then recurse exactly once."""
    result = np.full(values.shape, np.nan, dtype=np.float64)
    if len(values) >= period:
        result[period - 1] = np.mean(values[:period], dtype=np.float64)
        for index in range(period, len(values)):
            result[index] = alpha * values[index] + (1 - alpha) * result[index - 1]
    return result


@_fail_closed
def ema(prices: tuple[Decimal, ...], period: int) -> Series:
    """R-03/R-13/GD-03: SMA-seeded exponential moving average in cents."""
    count = _period(period)
    values = _prices(prices)
    return _export(_average(values, count, np.float64(2) / (count + 1)), CENT)


@_fail_closed
def rsi(prices: tuple[Decimal, ...], period: int = 14) -> Series:
    """GD-03: Wilder RSI; no changes means undefined, not bullish/neutral."""
    count = _period(period)
    values = _prices(prices)
    changes = np.diff(values)
    gains = _average(np.maximum(changes, 0), count, np.float64(1) / count)
    losses = _average(np.maximum(-changes, 0), count, np.float64(1) / count)
    result = np.full(values.shape, np.nan, dtype=np.float64)
    for index in range(count, len(values)):
        gain, loss = gains[index - 1], losses[index - 1]
        if loss > 0:
            result[index] = 100 - 100 / (1 + gain / loss)
        elif gain > 0:
            result[index] = 100
    return _export(result, MICRO)


class MACDSeries(FrozenModel):
    """R-03/R-13/GD-03: signed price differences in immutable cent series."""

    line: tuple[Money | None, ...]
    signal: tuple[Money | None, ...]
    histogram: tuple[Money | None, ...]

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        """R-02/R-13: every component has matching lengths and cent precision."""
        if (
            not self.line
            or len(self.line) != len(self.signal)
            or len(self.line) != len(self.histogram)
        ):
            raise ValueError("MACD components need equal nonzero lengths")
        with localcontext() as context:
            context.prec = 80
            for value in (*self.line, *self.signal, *self.histogram):
                if value is not None and value != value.quantize(CENT):
                    raise ValueError("MACD outputs must have cent precision")
        return self


@_fail_closed
def macd(
    prices: tuple[Decimal, ...], fast: int = 12, slow: int = 26, signal: int = 9
) -> MACDSeries:
    """GD-03: SMA-seeded EMA difference and EMA signal, without rounded recursion."""
    fast, slow, signal = _period(fast), _period(slow), _period(signal)
    if fast >= slow:
        raise DataIntegrityError("GD-03: MACD fast period must precede slow period")
    values = _prices(prices)
    line = _average(values, fast, np.float64(2) / (fast + 1)) - _average(
        values, slow, np.float64(2) / (slow + 1)
    )
    signal_line = np.full(values.shape, np.nan, dtype=np.float64)
    if len(values) >= slow:
        signal_line[slow - 1 :] = _average(line[slow - 1 :], signal, np.float64(2) / (signal + 1))
    return MACDSeries(
        line=_export(line, CENT),
        signal=_export(signal_line, CENT),
        histogram=_export(line - signal_line, CENT),
    )


@_fail_closed
def atr(bars: tuple[Bar, ...], period: int = 14) -> Series:
    """DAT-02/GD-03: Wilder true range includes prior-close gaps and first range."""
    count = _period(period)
    checked = _bars(bars)
    highs = _prices(tuple(bar.high for bar in checked))
    lows = _prices(tuple(bar.low for bar in checked))
    closes = _prices(tuple(bar.close for bar in checked))
    ranges = highs - lows
    if len(checked) > 1:
        ranges[1:] = np.maximum(
            np.maximum(ranges[1:], np.abs(highs[1:] - closes[:-1])),
            np.abs(lows[1:] - closes[:-1]),
        )
    return _export(_average(ranges, count, np.float64(1) / count), CENT)


@_fail_closed
def rvol(volumes: tuple[int, ...], period: int = 20) -> Series:
    """GD-03: current volume / preceding-period mean; zero baseline is undefined."""
    count = _period(period)
    values = _volumes(volumes)
    result = np.full(values.shape, np.nan, dtype=np.float64)
    for index in range(count, len(values)):
        average = np.mean(values[index - count : index], dtype=np.float64)
        if average > 0:
            result[index] = values[index] / average
    return _export(result, MICRO)


@_fail_closed
def anchored_vwap(bars: tuple[Bar, ...], anchor_index: int) -> Series:
    """DAT-03/GD-03: cumulative HLC/3 times volume, beginning at a known anchor."""
    checked = _bars(bars)
    if type(anchor_index) is not int or not 0 <= anchor_index < len(checked):
        raise DataIntegrityError("GD-03: anchored VWAP index must identify an input bar")
    high = _prices(tuple(bar.high for bar in checked))
    low = _prices(tuple(bar.low for bar in checked))
    close = _prices(tuple(bar.close for bar in checked))
    volumes = _volumes(tuple(bar.volume for bar in checked))
    cumulative_volume = np.cumsum(volumes[anchor_index:], dtype=np.float64)
    weighted = np.cumsum(((high + low + close) / 3 * volumes)[anchor_index:], dtype=np.float64)
    result = np.full(high.shape, np.nan, dtype=np.float64)
    for offset, volume in enumerate(cumulative_volume):
        if volume > 0:
            result[anchor_index + offset] = weighted[offset] / volume
    return _export(result, CENT)
