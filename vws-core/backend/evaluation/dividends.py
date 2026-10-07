"""DQ-01: causal ALL/SPLIT distribution-return estimates for historical replay.

This is an adjusted-price return estimate, not a broker dividend activity or a
claim about payment dates. Amounts accrue outside settled entry cash. The ratio
of adjacent ALL/SPLIT factors cancels later vendor back-adjustments. RAW supplies
the native prior close; a same-day known split converts it to the current share
basis. An ambiguous adjustment is rejected rather than invented as income.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Self

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.history import FrozenHistory
from backend.domain.models import FrozenModel, Money, PositiveQty, SessionDate
from backend.evaluation.costs import Exact

NOTICE = "Replay uses ALL/SPLIT distribution-return estimates, accrued outside settled entry cash; these are not actual dividend payments."


class DistributionCredit(FrozenModel):
    session: SessionDate
    qty: PositiveQty = Field(le=10**9)
    per_share: Exact = Field(gt=0)
    amount: Money = Field(gt=0)

    @model_validator(mode="after")
    def bound(self) -> Self:
        with localcontext() as precision:
            precision.prec = 256
            if self.amount != (self.per_share * self.qty).quantize(CENT, rounding=ROUND_FLOOR):
                raise ValueError("DQ-01: distribution credit differs from shares and its estimate")
        return self


def distribution_rates(
    history: FrozenHistory, symbol: str, end: date | None = None
) -> dict[date, Decimal]:
    """Use only adjacent completed observations; future actions cannot leak back."""
    try:
        raw = history.bundle.for_symbol(symbol, "RAW")
        split = history.bundle.for_symbol(symbol, "SPLIT")
        total = history.bundle.for_symbol(symbol, "ALL")
        actions = {
            item.effective_session: item.new_shares_per_old
            for item in history.bundle.splits
            if item.symbol == symbol
        }
        rates: dict[date, Decimal] = {}
        with localcontext() as precision:
            precision.prec = 256
            previous = None
            for native, signal, adjusted in zip(raw.bars, split.bars, total.bars, strict=True):
                day = native.session_date
                if end is not None and day > end:
                    break
                # Cents-rounded vendor factors that differ across OHLC do not
                # establish an exact distribution. No approximate cash is guessed.
                if any(
                    a * signal.close != s * adjusted.close
                    for a, s in zip(
                        (adjusted.open, adjusted.high, adjusted.low),
                        (signal.open, signal.high, signal.low),
                        strict=True,
                    )
                ):
                    raise ValueError("ALL/SPLIT adjustment is ambiguous within a bar")
                if previous is not None:
                    prior_native, prior_signal, prior_total = previous
                    ratio = (prior_total.close * signal.close) / (
                        prior_signal.close * adjusted.close
                    )
                    if ratio > 1:
                        raise ValueError("ALL/SPLIT factor reverses; distribution unavailable")
                    per_share = (
                        prior_native.close / actions.get(day, Decimal(1)) * (1 - ratio)
                    ).quantize(Decimal("0.00000001"), rounding=ROUND_FLOOR)
                    if per_share > 0:
                        rates[day] = per_share
                previous = (native, signal, adjusted)
        return rates
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("DQ-01: frozen distribution adjustment is unverifiable") from None


def distribution_credit(day: date, qty: int, rate: Decimal | None) -> DistributionCredit | None:
    if rate is None:
        return None
    with localcontext() as precision:
        precision.prec = 256
        amount = (rate * qty).quantize(CENT, rounding=ROUND_FLOOR)
        return (
            None
            if amount == 0
            else DistributionCredit(session=day, qty=qty, per_share=rate, amount=amount)
        )
