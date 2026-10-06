"""TX-08 owner defaults and sale review over the shared wash-sale engine.

Stage J adds imports, durable tax events and authoritative 1099-B reconciliation.
This module never logs into external accounts and never moves money.
"""

from decimal import Decimal, localcontext
from uuid import UUID

from pydantic import Field

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.money import decimal_money
from backend.domain.compliance_models import TaxLot, TradeRecord
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import FrozenModel, Money
from backend.domain.tax_profile import EXTERNAL_LOT_REMINDERS, TAX_ESTIMATE_NOTICE, TaxProfile
from backend.risk.wash_sales import WashSaleMatcher


class SaleReview(FrozenModel):
    sale_id: UUID
    external_lot_ids: tuple[UUID, ...]
    prompts: tuple[str, ...] = Field(max_length=5)
    notice: str = TAX_ESTIMATE_NOTICE


class SetAside(FrozenModel):
    net_st: Money
    net_lt: Money
    estimate: Money | None = Field(default=None, ge=0)
    notice: str = TAX_ESTIMATE_NOTICE


class TaxTracker:
    def __init__(self, settings: Settings, registry: InstrumentRegistry) -> None:
        self.profile = Settings.validated_copy(settings).tax_profile
        self.matcher = WashSaleMatcher(registry)

    def review_sale(
        self, sale: TradeRecord, marked_external_lots: tuple[TaxLot, ...]
    ) -> SaleReview:
        """Every recorded sale asks for owner-entered lots; exits remain available."""
        matches = self.matcher.marked_external_lots(sale, marked_external_lots)
        prompts = (
            EXTERNAL_LOT_REMINDERS
            + (
                (
                    "Possible overlapping external lots need review; 401(k) treatment is not inferred.",
                )
                if matches
                else ()
            )
            + ("Keep checking replacement purchases through 30 days after a loss sale.",)
        )
        return SaleReview(
            sale_id=TradeRecord.model_validate(sale).trade_id,
            external_lot_ids=tuple(lot.lot_id for lot in matches),
            prompts=prompts,
        )

    def set_aside(self, net_st: Decimal, net_lt: Decimal) -> SetAside:
        """TX-08: totals only until all rates are supplied; no invented brackets."""
        try:
            profile = TaxProfile.model_validate(self.profile)
            st, lt = decimal_money(net_st), decimal_money(net_lt)
            estimate = None
            if profile.estimate_available:
                rates = (
                    profile.federal_st_rate,
                    profile.federal_lt_rate,
                    profile.state_rate,
                    profile.niit_rate,
                )
                # The revalidated property's all-four condition establishes this.
                st_rate, lt_rate, state, niit = (rate for rate in rates if rate is not None)
                with localcontext() as context:
                    context.prec = 80
                    estimate = max(Decimal(0), st) * (st_rate + state + niit) + max(
                        Decimal(0), lt
                    ) * (lt_rate + state + niit)
            return SetAside(net_st=st, net_lt=lt, estimate=estimate)
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("TX-08: invalid estimate evidence") from None
