"""R-02/R-04/R-05/R-13, CMP-01..05: immutable tax-accounting evidence.

Execution prices are exact Decimal cents. Tax basis and realized loss are
micro-unit money because wash adjustments can create fractional-cent basis.
All accounts are caller-attested accounts of the same taxpayer; spouse and
controlled-entity classification remains an operator verification duty.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.domain.models import (
    FrozenModel,
    Identifier,
    Money,
    PositiveQty,
    Price,
    SessionDate,
    Side,
    Symbol,
    UTCDateTime,
)


class TaxStatus(StrEnum):
    """CMP-01/CMP-02: a taxable deduction cannot arise inside an IRA/Roth."""

    TAXABLE = "TAXABLE"
    IRA = "IRA"
    ROTH = "ROTH"


class ExternalAccount(FrozenModel):
    """CMP-01/CMP-02: explicit same-taxpayer account ownership and tax status."""

    account_id: Identifier
    tax_status: TaxStatus


class TaxLot(FrozenModel):
    """CMP-02/CMP-03: available whole shares and attested per-share tax basis.

    acquisition_trade_id, when known, identifies the original executed BUY.
    acquired_at is the actual purchase timestamp; a separately tacked holding
    start requires that original BUY ID and its record in supplied history.
    funding_settlement_date=None means settlement evidence is unavailable.
    """

    lot_id: UUID
    account_id: Identifier
    symbol: Symbol
    qty: PositiveQty
    acquired_at: UTCDateTime
    cost_basis: Money = Field(gt=Decimal(0))
    funding_settlement_date: SessionDate | None = None
    acquisition_trade_id: UUID | None = None
    holding_period_start: UTCDateTime | None = None

    @model_validator(mode="after")
    def validate_holding_period(self) -> Self:
        """R-02/CMP-02: tacking cannot guess or overwrite an acquisition date."""
        if self.holding_period_start is not None:
            if self.holding_period_start > self.acquired_at:
                raise ValueError("lot holding period cannot begin after actual acquisition")
            if self.holding_period_start < self.acquired_at and self.acquisition_trade_id is None:
                raise ValueError("previously tacked lot requires its original acquisition ID")
        return self


class TradeRecord(FrozenModel):
    """CMP-01..05: an executed whole-share trade, including DRIP purchases.

    realized_loss is attested total positive loss, including earlier basis
    adjustments. Each loss SELL represents one acquisition lot and supplies
    its holding-period start. An explicit acquisition ID disambiguates fills.
    Without that ID, holding_period_start attests the actual untacked purchase
    timestamp; previously tacked lots require the original acquisition ID.
    Aggregate multi-lot losses must be split by the caller before evaluation.
    """

    trade_id: UUID
    account_id: Identifier
    symbol: Symbol
    side: Side
    qty: PositiveQty
    price: Price
    ts: UTCDateTime
    realized_loss: Money = Field(default=Decimal(0), ge=Decimal(0))
    holding_period_start: UTCDateTime | None = None
    is_drip: bool = Field(default=False, strict=True)
    acquisition_trade_id: UUID | None = None

    @model_validator(mode="after")
    def validate_loss(self) -> Self:
        """R-02/CMP-02: loss and disposal evidence cannot contradict execution."""
        if self.realized_loss > 0 and (self.side != Side.SELL or self.holding_period_start is None):
            raise ValueError("realized loss requires a SELL and holding-period start")
        if self.holding_period_start is not None and self.holding_period_start > self.ts:
            raise ValueError("holding period cannot start after the executed trade")
        if self.acquisition_trade_id is not None and self.side != Side.SELL:
            raise ValueError("an acquisition reference belongs only to a SELL")
        if self.is_drip and self.side != Side.BUY:
            raise ValueError("a DRIP record must be a BUY")
        return self


class WashAdjustment(FrozenModel):
    """CMP-01/CMP-02: one disjoint loss-share/replacement-share allocation.

    acquired_date is the sold lot's original acquisition date, for Form 8949.
    adjusted_basis is the total basis of the matched replacement slice;
    holding_period_start is its tacked start. IRA/Roth basis stays unchanged.
    """

    loss_trade_id: UUID
    replacement_trade_id: UUID
    loss_account_id: Identifier
    replacement_account_id: Identifier
    symbol: Symbol
    qty: PositiveQty
    sale_date: SessionDate
    acquired_date: SessionDate
    proceeds: Money = Field(ge=Decimal(0))
    cost_basis: Money = Field(gt=Decimal(0))
    disallowed_loss: Money = Field(gt=Decimal(0))
    adjusted_basis: Money | None = None
    holding_period_start: UTCDateTime
    permanent_loss: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_allocation(self) -> Self:
        """R-02/CMP-02: every exported sale slice must reconcile exactly."""
        with localcontext() as context:
            context.prec = 80
            if self.cost_basis - self.proceeds != self.disallowed_loss:
                raise ValueError("matched sale basis must reconcile to its disallowed loss")
        if self.acquired_date > self.sale_date:
            raise ValueError("sold lot acquisition cannot follow its sale")
        if self.permanent_loss:
            if self.adjusted_basis is not None:
                raise ValueError("IRA/Roth permanent loss cannot increase replacement basis")
        elif self.adjusted_basis is None or self.adjusted_basis <= self.disallowed_loss:
            raise ValueError("taxable replacement requires its positive adjusted basis")
        return self


class Form8949Row(FrozenModel):
    """CMP-02: disjoint matched sale slice with positive code-W adjustment."""

    account_id: Identifier
    loss_trade_id: UUID
    description: Identifier
    date_acquired: SessionDate
    date_sold: SessionDate
    proceeds: Money
    cost_basis: Money
    code: Literal["W"] = "W"
    adjustment: Money = Field(gt=Decimal(0))
    gain_or_loss: Money

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        """R-02/CMP-02: adjustment changes gain/loss without reducing basis."""
        with localcontext() as context:
            context.prec = 80
            if self.proceeds - self.cost_basis + self.adjustment != self.gain_or_loss:
                raise ValueError("Form 8949 proceeds, basis and adjustment must reconcile")
        if self.date_acquired > self.date_sold:
            raise ValueError("Form 8949 acquisition cannot follow sale")
        return self
