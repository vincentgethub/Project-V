"""GD-04/R-09: held exits and open-ticket warnings, including during HALT."""

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal, Self

from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    EarningsStatus,
    FrozenModel,
    MarketContext,
    MarketStatus,
    PortfolioSnapshot,
    PositiveQty,
    Price,
    Symbol,
    UTCDateTime,
)
from backend.risk.risk_cro import earnings_rule


class Protection(FrozenModel):
    symbol: Symbol
    qty: PositiveQty
    stop: Price
    target: Price | None = None
    kind: Literal["HELD", "OPEN_TICKET"] = "HELD"

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.target is not None and self.target <= self.stop:
            raise ValueError("GD-04: target must exceed the protective stop")
        return self


class ExitSuggestion(FrozenModel):
    symbol: Symbol
    qty: int = Field(strict=True, ge=0)
    last_price: Price
    quote_at: UTCDateTime
    reason: Literal[
        "STOP_BREACHED", "TARGET_REACHED", "EARNINGS_BLACKOUT", "SUSPECT", "OPEN_TICKET_WARNING"
    ]
    urgent: bool = Field(strict=True)
    text: str = Field(min_length=1, max_length=1000)


def monitor(
    protection: Protection,
    portfolio: PortfolioSnapshot,
    market: MarketContext,
    *,
    now: datetime,
    quote_feed: Literal["IEX"],
    settings: Settings,
    calendar: MarketCalendar,
) -> tuple[ExitSuggestion, ...]:
    """No entry-risk gate or mode may trap a held exit warning.

    Open tickets produce warnings with zero sell shares until a holding is
    actually observed. The owner verifies protection before placing an exit.
    """
    try:
        item, snapshot, facts = (
            Protection.model_validate(protection),
            PortfolioSnapshot.model_validate(portfolio),
            MarketContext.model_validate(market),
        )
        policy = Settings.validated_copy(settings)
        instant = ensure_utc(now)
        if quote_feed != "IEX":
            raise DataIntegrityError("GD-04: monitor feed must be explicit IEX")
        age = instant - facts.last_price_ts
        if age < timedelta(0) or age > timedelta(seconds=policy.stale_quote_seconds):
            raise DataIntegrityError("GD-04: monitor requires a fresh IEX last trade")
        if snapshot.as_of > instant or instant - snapshot.as_of > timedelta(
            seconds=policy.stale_quote_seconds
        ):
            raise DataIntegrityError("GD-04: monitor requires a fresh broker holding")
        held = snapshot.positions.get(item.symbol)
        qty = min(item.qty, held.qty if held is not None else 0)
        if item.kind == "HELD" and qty == 0:
            return ()
        reason: (
            Literal[
                "STOP_BREACHED",
                "TARGET_REACHED",
                "EARNINGS_BLACKOUT",
                "SUSPECT",
                "OPEN_TICKET_WARNING",
            ]
            | None
        ) = None
        if facts.last_price <= item.stop:
            reason = "STOP_BREACHED"
        elif item.target is not None and facts.last_price >= item.target:
            reason = "TARGET_REACHED"
        elif facts.status == MarketStatus.SUSPECT:
            reason = "SUSPECT"
        elif (
            facts.earnings is not None
            and facts.earnings.status == EarningsStatus.KNOWN
            and not earnings_rule(facts, instant, policy, calendar).passed
        ):
            reason = "EARNINGS_BLACKOUT"
        if reason is None:
            return ()
        urgent = reason == "STOP_BREACHED"
        if item.kind == "OPEN_TICKET" and qty == 0:
            return (
                ExitSuggestion(
                    symbol=item.symbol,
                    qty=0,
                    last_price=facts.last_price,
                    quote_at=facts.last_price_ts,
                    reason="OPEN_TICKET_WARNING",
                    urgent=urgent,
                    text=f"{item.symbol} open ticket: {reason}. Recheck or skip the entry; no holding observed. IEX last trade ${facts.last_price:.2f}.",
                ),
            )
        quantity = "$•••" if policy.telegram_mask_amounts else str(qty)
        return (
            ExitSuggestion(
                symbol=item.symbol,
                qty=qty,
                last_price=facts.last_price,
                quote_at=facts.last_price_ts,
                reason=reason,
                urgent=urgent,
                text=f"{item.symbol} EXIT/REDUCE suggestion: {reason}. Held cap {quantity} shares. IEX last trade ${facts.last_price:.2f}. Check broker stops and remaining shares before a manual exit.",
            ),
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("GD-04: held protection evidence is invalid") from None


def distance_to_stop(last_price: Decimal, stop: Decimal) -> Decimal:
    """Exact informational percent distance for /positions."""
    from backend.core.money import validate_cent_price

    latest, level = validate_cent_price(last_price), validate_cent_price(stop)
    with localcontext() as context:
        context.prec = 80
        return (latest - level) / latest * 100
