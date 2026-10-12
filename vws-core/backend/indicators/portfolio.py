"""PR-02/03 numerical returns; float64 remains inside indicator math."""

from datetime import date
from decimal import Decimal, localcontext

import numpy as np

from backend.agents.indicators import _export, _fail_closed, _period
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.history import HistorySeries, KnownSplit
from backend.indicators.statistics import _exact, _samples
from backend.indicators.vectorized import average

Prices = tuple[tuple[date, Decimal], ...]


@_fail_closed
def causal_split_ema(
    native: HistorySeries,
    actions: tuple[KnownSplit, ...],
    period: int,
    end: date,
) -> dict[date, Decimal | None]:
    """EX-03/PF-03: one causal EMA array, quantized on each native share basis."""
    source, count = HistorySeries.model_validate(native), _period(period)
    if (
        source.adjustment != "RAW"
        or type(end) is not date
        or not isinstance(actions, tuple)
        or len(actions) > 10000
    ):
        raise DataIntegrityError("EX-03: bounded native split evidence required")
    checked = tuple(KnownSplit.model_validate(row) for row in actions)
    if len({(row.symbol, row.effective_session) for row in checked}) != len(checked):
        raise DataIntegrityError("EX-03: duplicate split action")
    splits = {
        row.effective_session: row.new_shares_per_old
        for row in checked
        if row.symbol == source.symbol and row.effective_session <= end
    }
    tape = tuple(bar for bar in source.bars if bar.session_date <= end)
    if not tape:
        raise DataIntegrityError("EX-03: completed EMA history unavailable")
    economic, bases = [], []
    basis = Decimal(1)
    with localcontext() as precision:
        precision.prec = 80
        for bar in tape:
            basis *= splits.get(bar.session_date, Decimal(1))
            economic.append(bar.close * basis)
            bases.append(basis)
    values = average(_samples(tuple(economic)), count, np.float64(2) / (count + 1))
    endpoints = _export(values / _samples(tuple(bases)), CENT)
    return dict(zip((bar.session_date for bar in tape), endpoints, strict=True))


@_fail_closed
def causal_split_atr(
    native: HistorySeries, actions: tuple[KnownSplit, ...], end: date
) -> dict[date, Decimal | None]:
    """EX-02: Wilder ATR14 in the native basis of each completed session."""
    source = HistorySeries.model_validate(native)
    # Reuse the evidence boundary, including duplicate actions and bounded dates.
    causal_split_ema(source, actions, 14, end)
    splits = {
        row.effective_session: row.new_shares_per_old
        for row in actions
        if row.symbol == source.symbol and row.effective_session <= end
    }
    tape = tuple(bar for bar in source.bars if bar.session_date <= end)
    highs, lows, closes, bases = [], [], [], []
    basis = Decimal(1)
    with localcontext() as precision:
        precision.prec = 80
        for bar in tape:
            basis *= splits.get(bar.session_date, Decimal(1))
            highs.append(bar.high * basis)
            lows.append(bar.low * basis)
            closes.append(bar.close * basis)
            bases.append(basis)
    high, low, close = _samples(tuple(highs)), _samples(tuple(lows)), _samples(tuple(closes))
    ranges = high - low
    if len(tape) > 1:
        ranges[1:] = np.maximum(
            np.maximum(ranges[1:], np.abs(high[1:] - close[:-1])), np.abs(low[1:] - close[:-1])
        )
    endpoints = _export(average(ranges, 14, np.float64(1) / 14) / _samples(tuple(bases)), CENT)
    return dict(zip((bar.session_date for bar in tape), endpoints, strict=True))


@_fail_closed
def prices(values: Prices) -> Prices:
    if not isinstance(values, tuple) or not 1 <= len(values) <= 20000:
        raise DataIntegrityError("PR/RS: bounded immutable prices required")
    if any(
        type(day) is not date or not isinstance(price, Decimal) or price <= 0
        for day, price in values
    ):
        raise DataIntegrityError("PR/RS: exact positive prices and dates required")
    _samples(tuple(price for _, price in values))
    if any(a[0] >= b[0] for a, b in zip(values, values[1:], strict=False)):
        raise DataIntegrityError("PR/RS: sessions must be unique and increasing")
    return values


@_fail_closed
def correlation(candidate: Prices, held: Prices) -> Decimal | None:
    first, second = prices(candidate), prices(held)

    # Returns must share both endpoints, not just an ending date across missing sessions.
    def returns(rows: Prices) -> dict[tuple[date, date], np.float64]:
        return {
            (a[0], b[0]): np.log(np.float64(b[1]) / np.float64(a[1]))
            for a, b in zip(rows, rows[1:], strict=False)
        }

    x, y = returns(first), returns(second)
    common = sorted(x.keys() & y.keys())[-60:]
    if len(common) < 50:
        return None
    observed_x = np.asarray([x[day] for day in common], dtype=np.float64)
    observed_y = np.asarray([y[day] for day in common], dtype=np.float64)
    if np.std(observed_x) <= 0 or np.std(observed_y) <= 0:
        return None
    return _exact(np.corrcoef(observed_x, observed_y)[0, 1])


@_fail_closed
def volatility(values: Prices, fallback: Decimal = Decimal("0.16")) -> tuple[Decimal, Decimal]:
    checked = prices(values)
    if not isinstance(fallback, Decimal) or not fallback.is_finite() or not 0 < fallback <= 1:
        raise DataIntegrityError("PR-03: exact anchor required")
    if len(checked) < 21:
        raise DataIntegrityError("PR-03: twenty completed log returns required")
    observed = np.log(_samples(tuple(price for _, price in checked)))
    returns = np.diff(observed)
    sigma = np.std(returns[-20:], ddof=1) * np.sqrt(np.float64(252))
    anchor = fallback
    if len(returns) >= 1279:
        windows = np.lib.stride_tricks.sliding_window_view(returns[-1279:], 20)
        anchor = _exact(np.median(np.std(windows, axis=1, ddof=1) * np.sqrt(np.float64(252))))
    return _exact(sigma), anchor
