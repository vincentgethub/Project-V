"""AX-22/42: pure market-hours and live-ceiling checks; no execution capability."""

from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.config import Settings, YamlConfig
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.money import CENT, validate_cent_price
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    MarketContext,
    MarketStatus,
    PortfolioSnapshot,
    Severity,
    TradeProposal,
)
from backend.risk.risk_cro import earnings_rule

ExitReason = Literal["TIME", "EARNINGS", "SUSPECT", "EMA20"]


def exit_limit(last_price: Decimal, offset: Decimal) -> Decimal:
    """AX-29/R-13: fixed offset, rounded downward to a valid cent SELL limit."""
    last_price = validate_cent_price(last_price)
    if (
        not isinstance(offset, Decimal)
        or not offset.is_finite()
        or not Decimal(0) <= offset <= Decimal("0.01")
    ):
        raise DataIntegrityError("Exit offset must be an exact fraction from zero through 0.01")
    with localcontext() as context:
        context.prec = 40
        return validate_cent_price((last_price * (1 - offset)).quantize(CENT, rounding=ROUND_DOWN))


def automatic_exit_reason(
    settings: Settings,
    config: YamlConfig,
    calendar: MarketCalendar,
    first_fill: datetime,
    market: MarketContext,
    now: datetime,
) -> ExitReason | None:
    """AX-29: only fixed time, verified earnings blackout or SUSPECT evidence."""
    settings, config = Settings.validated_copy(settings), YamlConfig.model_validate(config)
    first_fill, now = ensure_utc(first_fill), ensure_utc(now)
    market = MarketContext.model_validate(market)
    if first_fill > now:
        raise DataIntegrityError("Held position starts in the future")
    if not settings.auto_exits:
        return None
    if market.status == MarketStatus.SUSPECT:
        return "SUSPECT"
    opening_day = first_fill.astimezone(ZoneInfo("America/New_York")).date()
    maturity = calendar.session_close(
        calendar.add_sessions(opening_day, config.evaluation.max_hold_sessions - 1)
    )
    if now >= maturity:
        return "TIME"
    if settings.auto_exit_before_earnings:
        earnings = earnings_rule(market, now, settings, calendar)
        if not earnings.passed and earnings.severity == Severity.BLOCK:
            return "EARNINGS"
    return None


def entry_window(settings: Settings, calendar: MarketCalendar, now: datetime) -> bool:
    settings = Settings.validated_copy(settings)
    now = ensure_utc(now)
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    if not calendar.is_session(day):
        return False
    opening, closing = calendar.session_open(day), calendar.session_close(day)
    early = closing - opening < timedelta(hours=6, minutes=30)
    stop_minutes = max(settings.auto_no_trade_close_minutes, 60 if early else 0)
    return (
        opening + timedelta(minutes=settings.auto_no_trade_open_minutes)
        <= now
        < closing - timedelta(minutes=stop_minutes)
    )


def require_live_limits(settings: Settings) -> None:
    if any(
        value is None
        for value in (
            settings.live_max_order_notional,
            settings.live_max_daily_orders,
            settings.live_max_open_positions,
            settings.live_max_gross_exposure_pct,
            settings.live_max_risk_per_trade,
            settings.live_daily_loss_limit,
        )
    ):
        raise ConfigurationError("AUTO_LIVE requires all six explicit LIVE_* ceilings")


def live_ceiling_reasons(
    settings: Settings,
    proposal: TradeProposal,
    portfolio: PortfolioSnapshot,
    daily_entries: int,
) -> tuple[str, ...]:
    settings = Settings.validated_copy(settings)
    proposal, portfolio = (
        TradeProposal.model_validate(proposal),
        PortfolioSnapshot.model_validate(portfolio),
    )
    require_live_limits(settings)
    if type(daily_entries) is not int or daily_entries < 0:
        raise DataIntegrityError("Entry count must be a nonnegative integer")
    # The explicit checks above narrow these optional values without relying on a cast.
    notional_cap, daily_cap, positions_cap = (
        settings.live_max_order_notional,
        settings.live_max_daily_orders,
        settings.live_max_open_positions,
    )
    gross_cap, risk_cap, loss_cap = (
        settings.live_max_gross_exposure_pct,
        settings.live_max_risk_per_trade,
        settings.live_daily_loss_limit,
    )
    if (
        notional_cap is None
        or daily_cap is None
        or positions_cap is None
        or gross_cap is None
        or risk_cap is None
        or loss_cap is None
    ):
        raise ConfigurationError("Live ceilings are unavailable")
    reasons: list[str] = []
    from backend.risk.overlays import open_risk

    if proposal.stop_price is None:
        raise DataIntegrityError("AX-42: live entry stop is unavailable")
    total_risk = open_risk(portfolio) + (proposal.limit_price - proposal.stop_price) * proposal.qty
    if (
        total_risk
        > min(settings.live_max_open_risk, settings.portfolio_max_open_risk) * portfolio.equity
    ):
        reasons.append("AX-42: live total open-risk ceiling")
    notional = proposal.qty * proposal.limit_price
    if notional > min(notional_cap, settings.max_single_stock_weight * portfolio.equity):
        reasons.append("AX-42: live order notional ceiling")
    if daily_entries >= min(daily_cap, 5):
        reasons.append("AX-42: live daily entry ceiling")
    names = {name for name, position in portfolio.positions.items() if position.qty > 0}
    names.update(order.symbol for order in portfolio.open_orders if order.side.value == "BUY")
    if len(names | {proposal.symbol}) > min(positions_cap, settings.max_open_positions):
        reasons.append("AX-42: live open-position ceiling")
    gross = sum((position.value for position in portfolio.positions.values()), Decimal(0))
    gross += sum(
        (
            order.qty * order.limit_price
            for order in portfolio.open_orders
            if order.side.value == "BUY"
        ),
        Decimal(0),
    )
    if gross + notional > min(gross_cap, settings.max_gross_exposure) * portfolio.equity:
        reasons.append("AX-42: live gross-exposure ceiling")
    if proposal.stop_price is None:
        reasons.append("AX-42: missing protective stop")
    elif (
        proposal.qty
        * (
            proposal.limit_price
            - proposal.stop_price
            + proposal.limit_price * settings.stop_slippage_buffer
        )
        > min(risk_cap, settings.max_risk_per_trade) * portfolio.equity
    ):
        reasons.append("AX-42: live per-trade risk ceiling")
    if portfolio.equity <= portfolio.day_start_equity * (
        1 - min(loss_cap, settings.daily_loss_limit)
    ):
        reasons.append("AX-42: live daily loss blocks new entries")
    return tuple(reasons)
