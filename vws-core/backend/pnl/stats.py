"""PL-03/04: one explicit account/environment, deterministic 80-digit Decimal math."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field

from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, Money, SessionDate
from backend.pnl.models import MAX_PNL_SESSIONS, PnLDay, Ratio

Window = Literal["today", "week", "month", "mtd", "ytd", "inception"]


class PnLStats(FrozenModel):
    account_id: str = Field(min_length=1, max_length=128)
    env: Literal["PAPER", "LIVE"]
    start: SessionDate
    end: SessionDate
    sessions: int = Field(strict=True, gt=0, le=MAX_PNL_SESSIONS)
    total_pnl: Money
    average_dollars: Ratio
    average_return: Ratio
    twr: Ratio
    up: int = Field(strict=True, ge=0)
    down: int = Field(strict=True, ge=0)
    flat: int = Field(strict=True, ge=0)
    best_session: SessionDate
    worst_session: SessionDate
    best_pnl: Money
    worst_pnl: Money
    max_drawdown: Ratio
    drawdown_peak_session: SessionDate
    drawdown_trough_session: SessionDate
    spy_price_only: Ratio | None


def statistics(
    days: tuple[PnLDay, ...],
    window: Window,
    calendar: MarketCalendar,
    *,
    spy_closes: tuple[tuple[date, Decimal], ...] | None = None,
) -> PnLStats:
    try:
        if (
            not isinstance(days, tuple)
            or not 0 < len(days) <= MAX_PNL_SESSIONS
            or window not in {"today", "week", "month", "mtd", "ytd", "inception"}
        ):
            raise ValueError("PL-03: explicit bounded daily window required")
        checked = tuple(PnLDay.model_validate(row) for row in days)
        if (
            not isinstance(calendar, MarketCalendar)
            or any(not calendar.is_session(row.observation.session) for row in checked)
            or any(
                calendar.add_sessions(previous.observation.session, 1)
                != current.observation.session
                for previous, current in zip(checked, checked[1:], strict=False)
            )
        ):
            raise ValueError("PL-01: missing or invalid exchange sessions require backfill")
        bound = checked[0].observation
        if (
            any(
                (row.observation.account_id, row.observation.env) != (bound.account_id, bound.env)
                for row in checked
            )
            or tuple(sorted(checked, key=lambda row: row.observation.session)) != checked
            or len({row.observation.session for row in checked}) != len(checked)
        ):
            raise ValueError("PL-04: accounts, environments and resets cannot mix")
        if any(
            current.observation.equity_start != previous.observation.equity
            for previous, current in zip(checked, checked[1:], strict=False)
        ):
            raise ValueError("PL-02: daily equity continuity is unavailable")
        end = checked[-1].observation.session
        count = {"today": 1, "week": 7, "month": 30}.get(window)
        chosen = (
            checked[-count:]
            if count is not None
            else tuple(
                row
                for row in checked
                if window == "inception"
                or (
                    row.observation.session.year == end.year
                    and (window == "ytd" or row.observation.session.month == end.month)
                )
            )
        )
        with localcontext() as precision:
            precision.prec = 80
            index = peak = Decimal(1)
            drawdown = Decimal(0)
            peak_day = peak_at = trough_at = calendar.previous_sessions(
                chosen[0].observation.session, 1
            )[0]
            for row in chosen:
                index *= 1 + row.day_ret
                if index > peak:
                    peak, peak_day = index, row.observation.session
                current = (peak - index) / peak
                if current > drawdown:
                    drawdown, peak_at, trough_at = current, peak_day, row.observation.session
            total = sum((row.day_pnl for row in chosen), Decimal(0))
            best = max(chosen, key=lambda row: row.day_pnl)
            worst = min(chosen, key=lambda row: row.day_pnl)
            spy = None
            if spy_closes is not None:
                if not isinstance(spy_closes, tuple) or len(spy_closes) > MAX_PNL_SESSIONS + 1:
                    raise ValueError("PL-03: bounded SPY price-only observations required")
                marks = dict(spy_closes)
                if len(marks) != len(spy_closes) or any(
                    type(day) is not date
                    or not isinstance(price, Decimal)
                    or not price.is_finite()
                    or price <= 0
                    for day, price in spy_closes
                ):
                    raise ValueError("PL-03: exact positive SPY prices required")
                preceding = calendar.previous_sessions(chosen[0].observation.session, 1)[0]
                if preceding in marks and all(row.observation.session in marks for row in chosen):
                    spy = marks[end] / marks[preceding] - 1
            return PnLStats(
                account_id=bound.account_id,
                env=bound.env,
                start=chosen[0].observation.session,
                end=end,
                sessions=len(chosen),
                total_pnl=total,
                average_dollars=total / len(chosen),
                average_return=sum((row.day_ret for row in chosen), Decimal(0)) / len(chosen),
                twr=index - 1,
                up=sum(row.day_pnl > 0 for row in chosen),
                down=sum(row.day_pnl < 0 for row in chosen),
                flat=sum(row.day_pnl == 0 for row in chosen),
                best_session=best.observation.session,
                worst_session=worst.observation.session,
                best_pnl=best.day_pnl,
                worst_pnl=worst.day_pnl,
                max_drawdown=drawdown,
                drawdown_peak_session=peak_at,
                drawdown_trough_session=trough_at,
                spy_price_only=spy,
            )
    except Exception:
        raise DataIntegrityError("PL-02..04: performance series cannot be verified") from None
