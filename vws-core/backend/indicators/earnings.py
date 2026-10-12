"""EG/PF: reuse causal arrays, evaluating only the three possible gap sessions."""

from datetime import timedelta
from decimal import Decimal, localcontext

import numpy as np

from backend.agents.earnings_gap import evaluate_earnings_gap
from backend.agents.indicators import MICRO, Array, IndicatorSeries, MACDSeries, _export
from backend.agents.setup_hunter import PlaybookEvidence
from backend.core.config import YamlConfig
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.data_layer import Bar
from backend.data.earnings_reports import EarningsReport
from backend.data.history import HistorySeries
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import Instrument


def earnings_gate(
    raw: HistorySeries,
    index: int,
    factors: tuple[Decimal, ...],
    arrays: dict[str, Array],
    instrument: Instrument | None,
    reports: tuple[EarningsReport, ...] | None,
    spy: HistorySeries | None,
    stock: HistorySeries | None,
    config: YamlConfig,
    calendar: MarketCalendar | None,
) -> PlaybookEvidence | None:
    if instrument is None or reports is None or spy is None or stock is None or calendar is None:
        raise DataIntegrityError("EG-02: frozen earnings evidence unavailable")
    # Effective splits only; do not round a subcent historical gate into a pass.
    tape = []
    with localcontext() as precision:
        precision.prec = 256
        for bar, factor in zip(raw.bars[: index + 1], factors[: index + 1], strict=True):
            prices = tuple(
                value * factor / factors[index]
                for value in (bar.open, bar.high, bar.low, bar.close)
            )
            volume = Decimal(bar.volume) * factors[index] / factor
            if any(value != value.quantize(CENT) for value in prices) or volume != int(volume):
                return None
            tape.append(
                Bar(
                    timestamp=bar.timestamp,
                    open=prices[0],
                    high=prices[1],
                    low=prices[2],
                    close=prices[3],
                    volume=int(volume),
                )
            )
    count = index + 1
    empty = (None,) * count
    series = IndicatorSeries(
        **{
            name: _export(arrays[name][:count] / np.float64(factors[index]), CENT)
            for name in ("ema20", "ema50", "ema200", "atr14")
        },
        rsi14=_export(arrays["rsi14"][:count], MICRO),
        rvol20=_export(arrays["rvol20"][:count], MICRO),
        macd=MACDSeries(line=empty, signal=empty, histogram=empty),
        anchored_vwap=empty,
    )
    day = raw.bars[index].session_date
    spy_bars = tuple(bar for bar in spy.bars if bar.session_date <= day)
    stock_bars = tuple(bar for bar in stock.bars if bar.session_date <= day)
    if not spy_bars or not stock_bars:
        raise DataIntegrityError("EG-03: completed return evidence unavailable")
    return evaluate_earnings_gap(
        instrument,
        tuple(tape),
        series,
        spy_bars,
        reports,
        config.sizing,
        calendar.session_close(day) + timedelta(minutes=16),
        calendar,
        stock_return_bars=stock_bars,
    )
