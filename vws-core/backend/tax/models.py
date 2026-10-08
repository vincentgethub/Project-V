"""TX-01..10: immutable, exact owner/account and executed accounting evidence."""

from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.domain.compliance_models import ExternalAccount, TaxStatus
from backend.domain.models import (
    FrozenModel,
    Identifier,
    Money,
    PositiveQty,
    Price,
    Side,
    Symbol,
    UTCDateTime,
)

NOTICE = "Estimate and record-keeping aid, not tax advice. Your broker's 1099-B is the official record; consult a tax professional."
SIMULATED = "SIMULATED - NOT FOR FILING"
Environment = Literal["PAPER", "LIVE"]
LotMethod = Literal["ALPACA_COMPRESSED_FIFO", "FIFO"]


class TaxAccount(FrozenModel):
    id: Identifier = Field(max_length=128)
    name: Identifier = Field(max_length=128)
    tax_status: TaxStatus
    source: Literal["ALPACA", "CSV"]
    lot_method: LotMethod | None = None
    fills_csv: str | None = Field(default=None, min_length=1, max_length=512)
    form_box_st: Literal["A", "B", "C"] | None = None
    form_box_lt: Literal["D", "E", "F"] | None = None

    @model_validator(mode="after")
    def source_bound(self) -> Self:
        if (self.source == "CSV") != (self.fills_csv is not None):
            raise ValueError("TX-01: external accounts require their owner-supplied fills CSV")
        return self

    @property
    def method(self) -> LotMethod:
        return self.lot_method or ("ALPACA_COMPRESSED_FIFO" if self.source == "ALPACA" else "FIFO")

    @property
    def ownership(self) -> ExternalAccount:
        return ExternalAccount(account_id=self.id, tax_status=self.tax_status)


class TaxAccounts(FrozenModel):
    accounts: tuple[TaxAccount, ...] = Field(max_length=1000)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({row.id for row in self.accounts}) != len(self.accounts):
            raise ValueError("TX-01: owned account IDs must be unique")
        return self


class TaxFill(FrozenModel):
    fill_id: UUID
    activity_id: Identifier = Field(max_length=128)
    account_id: Identifier = Field(max_length=128)
    env: Environment
    symbol: Symbol
    side: Side
    qty: PositiveQty = Field(le=10**9)
    price: Price
    fees: Money = Field(ge=0)
    ts: UTCDateTime
    is_drip: bool = Field(default=False, strict=True)
    fee_source: Literal["BROKER", "MODELED", "CSV"]
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.is_drip and self.side != Side.BUY:
            raise ValueError("TX-02: a DRIP observation must be an acquisition")
        return self

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "TaxFill":
        try:
            values = dict(payload)
            values["ts"] = datetime.fromisoformat(str(values["ts"]))
            values["fill_id"] = UUID(str(values["fill_id"]))
            values["price"] = Decimal(str(values["price"]))
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("TX-02: stored fill cannot be verified") from None


class TaxIncome(FrozenModel):
    activity_id: Identifier = Field(max_length=128)
    account_id: Identifier = Field(max_length=128)
    env: Environment
    type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")
    date: date
    amount: Money
    dividend_class: Literal["unclassified", "qualified", "nonqualified", "exempt"] = "unclassified"
    classification_proof_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def documented_classification(self) -> Self:
        if self.dividend_class != "unclassified" and (
            not self.type.startswith("DIV") or self.classification_proof_sha256 is None
        ):
            raise ValueError("TX-06: classified dividends require explicit 1099-DIV evidence")
        return self

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "TaxIncome":
        try:
            values = dict(payload)
            values["date"] = date.fromisoformat(str(values["date"]))
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("TX-06: stored income cannot be verified") from None


class OpenTaxLot(FrozenModel):
    lot_id: UUID
    acquisition_id: UUID
    account_id: Identifier
    env: Environment
    symbol: Symbol
    qty: PositiveQty
    acquired_at: UTCDateTime
    holding_period_start: UTCDateTime
    basis: Money = Field(gt=0)
    wash_basis: Money = Field(ge=0)

    @model_validator(mode="after")
    def tacked(self) -> Self:
        if self.holding_period_start > self.acquired_at or self.wash_basis > self.basis:
            raise ValueError("TX-04: lot basis and holding-period evidence contradict acquisition")
        return self


class TaxSale(FrozenModel):
    sale_id: UUID
    fill_id: UUID
    acquisition_id: UUID
    account_id: Identifier
    env: Environment
    symbol: Symbol
    qty: PositiveQty
    acquired_at: UTCDateTime
    sold_at: UTCDateTime
    holding_period_start: UTCDateTime
    proceeds: Money
    basis: Money = Field(gt=0)
    economic_gain: Money
    wash_basis: Money = Field(ge=0)
    wash_disallowed: Money = Field(ge=0)
    permanent_disallowed: Money = Field(ge=0)
    taxable_gain: Money
    term: Literal["ST", "LT"]

    @model_validator(mode="after")
    def totals(self) -> Self:
        with localcontext() as precision:
            precision.prec = 80
            if (
                self.acquired_at > self.sold_at
                or self.holding_period_start > self.acquired_at
                or self.permanent_disallowed > self.wash_disallowed
                or self.wash_basis > self.basis
                or self.economic_gain != self.proceeds - self.basis
                or self.taxable_gain != self.economic_gain + self.wash_disallowed
                or self.wash_disallowed > max(-self.economic_gain, Decimal(0))
            ):
                raise ValueError("TX-03/05: sale basis, loss and wash allocation must reconcile")
        return self

    @property
    def realized_before_wash(self) -> Decimal:
        """PL-01: economic realization excludes prior deferred tax-basis additions."""
        with localcontext() as precision:
            precision.prec = 80
            return self.economic_gain + self.wash_basis
