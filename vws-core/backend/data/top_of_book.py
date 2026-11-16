"""OPS-SPREAD: validated IEX top-of-book evidence and the pure entry spread rule.

Default bound: 10 basis points of the quote midpoint, ``(ask - bid) / mid``.
The watchlist is liquid US ETFs and large caps priced well above the $5 floor.
For those, a normal one- to three-cent IEX spread is about 0.2-3 bps (SPY at
$600 with one cent is 0.17 bps; a $185 stock with two cents is 1.1 bps).
Anything wider than 10 bps signals a thin, halted, auctioning or disorderly
book for these names, which is exactly when a limit entry would overpay. The
configured bound is limited to 1-50 bps, so it can never be zero, negative or
large enough to disable the gate. Quotes older than ``stale_quote_seconds``,
quotes from the future, missing, crossed, locked or zero-sided quotes refuse.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from pydantic import Field, field_validator

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.domain.models import FrozenModel, UTCDateTime, validate_symbol

DEFAULT_MAX_ENTRY_SPREAD = Decimal("0.0010")
SPREAD_BOUNDS = (Decimal("0.0001"), Decimal("0.0050"))


class TopOfBook(FrozenModel):
    """One IEX latest quote; refusal decisions belong to ``spread_refusal``."""

    symbol: str
    bid: Decimal = Field(ge=Decimal(0))
    ask: Decimal = Field(ge=Decimal(0))
    quoted_at: UTCDateTime

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        return validate_symbol(value)


def _bps(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = 40
        return f"{(value * 10000).quantize(Decimal('0.1'))} bps"


def spread_refusal(
    top: TopOfBook | None,
    now: datetime,
    *,
    max_spread: Decimal,
    max_age_seconds: int,
) -> str | None:
    """Return a refusal reason, or None when the quote admits a new entry."""
    lower, upper = SPREAD_BOUNDS
    if not isinstance(max_spread, Decimal) or not lower <= max_spread <= upper:
        raise DataIntegrityError("OPS-SPREAD: entry spread bound is outside 1-50 bps")
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 300:
        raise DataIntegrityError("OPS-SPREAD: quote age bound is outside 1-300 seconds")
    if top is None:
        return "bid/ask quote is missing"
    if top.bid == 0 or top.ask == 0:
        return "bid/ask quote has a zero side"
    if top.ask < top.bid:
        return "bid/ask quote is crossed"
    if top.ask == top.bid:
        return "bid/ask quote is locked"
    age = ensure_utc(now) - top.quoted_at
    if age < timedelta(0):
        return "bid/ask quote is timestamped in the future"
    if age > timedelta(seconds=max_age_seconds):
        return "bid/ask quote is stale"
    with localcontext() as context:
        context.prec = 40
        spread = (top.ask - top.bid) / ((top.ask + top.bid) / 2)
    if spread > max_spread:
        return f"quoted spread {_bps(spread)} exceeds the {_bps(max_spread)} entry bound"
    return None
