"""EG-01..04: fixed stock-only earnings-gap checklist and gap-period stop."""

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

from backend.agents.indicators import IndicatorSeries, _bars
from backend.agents.setup_hunter import PlaybookEvidence
from backend.core.config import SizingConfig
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.data_layer import Bar
from backend.data.earnings_reports import EarningsReport, gap_sessions
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import AssetClass, Instrument, Playbook, SetupCriterion

ZERO = Decimal(0)
ONE = Decimal(1)


def evaluate_earnings_gap(
    instrument: Instrument,
    bars: tuple[Bar, ...],
    series: IndicatorSeries,
    spy_bars: tuple[Bar, ...],
    reports: tuple[EarningsReport, ...],
    sizing: SizingConfig,
    as_of: datetime,
    calendar: MarketCalendar,
    *,
    stock_return_bars: tuple[Bar, ...] | None = None,
) -> PlaybookEvidence | None:
    asset, tape, indicators, policy = (
        Instrument.model_validate(instrument),
        _bars(bars),
        IndicatorSeries.model_validate(series),
        SizingConfig.model_validate(sizing),
    )
    benchmark = _bars(spy_bars)
    returns = tape if stock_return_bars is None else _bars(stock_return_bars)
    if asset.asset_class != AssetClass.STOCK:
        return None
    if (
        len(tape) != len(indicators.ema50)
        or len(tape) < 200
        or not isinstance(reports, tuple)
        or len(reports) > 5000
    ):
        raise DataIntegrityError("EG: bounded matching completed evidence required")
    if any(row.symbol != asset.symbol for row in reports):
        raise DataIntegrityError("EG-02: report issuer differs")
    last = tape[-1]
    if any(
        bar.timestamp > as_of or calendar.session_close(bar.session_date) > as_of
        for bar in (*tape, *benchmark, *returns)
    ):
        raise DataIntegrityError("EG-02: future or incomplete bar refused")
    possible = {day for report in reports for day in gap_sessions(report, as_of, calendar)}
    indexes = [
        i
        for i, bar in enumerate(tape)
        if bar.session_date in possible and 1 <= len(tape) - 1 - i <= 3
    ]
    for i in reversed(indexes):
        gap, previous = tape[i], tape[i - 1]
        if tuple(bar.session_date for bar in tape[i:]) != tuple(
            calendar.add_sessions(gap.session_date, offset) for offset in range(len(tape) - i)
        ):
            raise DataIntegrityError("EG-03: gap window has missing exchange sessions")
        e50, e200, atr, rvol = (
            indicators.ema50[-1],
            indicators.ema200[-1],
            indicators.atr14[-1],
            indicators.rvol20[i],
        )
        if any(value is None for value in (e50, e200, atr, rvol)):
            continue
        with localcontext() as precision:
            precision.prec = 80
            gap_fraction = gap.open / previous.close - 1
            low = min(bar.low for bar in tape[i:])
            if not (
                gap_fraction >= Decimal("0.04")
                and rvol is not None
                and rvol >= 2
                and low > previous.close
                and last.close >= (gap.high + gap.low) / 2
                and e50 is not None
                and last.close > e50
            ):
                continue
            if atr is None or atr <= 0 or e200 is None:
                continue
            entry = last.high + CENT
            stop = min(entry - policy.stop_atr_mult * atr, low - CENT).quantize(
                CENT, rounding=ROUND_FLOOR
            )
            if stop <= 0 or (entry - stop) / entry > policy.max_stop_pct:
                continue
            target = (entry + policy.target_r * (entry - stop)).quantize(
                CENT, rounding=ROUND_CEILING
            )
            range_pos = (
                ZERO if gap.high == gap.low else (gap.close - gap.low) / (gap.high - gap.low)
            )
            stock_rs = ZERO
            if (
                len(benchmark) >= 64
                and len(returns) >= 64
                and tuple(bar.session_date for bar in benchmark[-64:])
                == tuple(bar.session_date for bar in returns[-64:])
            ):
                stock_rs = (
                    ONE
                    if returns[-1].close / returns[-64].close
                    > benchmark[-1].close / benchmark[-64].close
                    else ZERO
                )
            points = (
                (
                    "gap",
                    Decimal(2) if gap_fraction <= Decimal("0.08") else ONE,
                    f"gap={gap_fraction}",
                ),
                ("relative_volume", Decimal(2) if rvol >= 3 else ONE, f"gap RVOL={rvol}"),
                (
                    "range_position",
                    Decimal(2)
                    if range_pos >= Decimal("0.7")
                    else ONE
                    if range_pos >= Decimal("0.5")
                    else ZERO,
                    f"gap range position={range_pos}",
                ),
                ("trend", Decimal(2) if e50 > e200 else ZERO, f"EMA50={e50}; EMA200={e200}"),
                (
                    "relative_strength",
                    stock_rs,
                    "stock vs SPY 63-session return; unavailable earns zero",
                ),
                (
                    "atr_risk",
                    ONE if entry - stop <= 2 * atr else ZERO,
                    f"entry-stop={entry - stop}; ATR14={atr}",
                ),
            )
            return PlaybookEvidence(
                playbook=Playbook.EARNINGS_GAP,
                score=sum((points for _, points, _ in points), ZERO),
                criteria=tuple(
                    SetupCriterion(name=name, points=points, reason=reason)
                    for name, points, reason in points
                ),
                entry=entry,
                stop=stop,
                target=target,
            )
    return None
