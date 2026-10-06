"""TX-08: owner defaults and exact rates, shared by setup and tax reporting.

No federal ST/LT rate exists in TX-08. Unknown rates prohibit set-aside
estimates. External account reminders never create accounts or tax lots.
"""

from decimal import Decimal
from typing import Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FilingStatus: TypeAlias = Literal[
    "single",
    "married_filing_jointly",
    "married_filing_separately",
    "head_of_household",
    "qualifying_surviving_spouse",
]
DEFAULT_FILING_STATUS: FilingStatus = "single"
DEFAULT_STATE = "Texas"
DEFAULT_STATE_RATE: Decimal = Decimal("0")
DEFAULT_NIIT_RATE: Decimal = Decimal("0")
EXTERNAL_LOT_REMINDERS = (
    "IRA or Roth IRA: enter or import marked lots",
    "Merrill brokerage (taxable): enter or import marked lots",
    "401(k): enter or import marked lots for wash-sale awareness; treatment requires review",
)
TAX_ESTIMATE_NOTICE = "Estimates only; not tax advice. Broker 1099-B is authoritative."


class TaxProfile(BaseModel):
    """User-supplied rates are fractions; none is unavailable, never zero."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        revalidate_instances="always",
    )

    filing_status: FilingStatus = DEFAULT_FILING_STATUS
    state: str = Field(default=DEFAULT_STATE, min_length=1, max_length=64)
    federal_st_rate: Decimal | None = None
    federal_lt_rate: Decimal | None = None
    state_rate: Decimal | None = DEFAULT_STATE_RATE
    niit_rate: Decimal | None = DEFAULT_NIIT_RATE

    @field_validator("state")
    @classmethod
    def bounded_state(cls, value: str) -> str:
        if not value.strip() or value != value.strip() or not value.isprintable():
            raise ValueError("state requires plain trimmed text")
        return value

    @field_validator("federal_st_rate", "federal_lt_rate", "state_rate", "niit_rate", mode="before")
    @classmethod
    def exact_rate(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
            raise ValueError("tax rates require exact decimal text, not float or bool")
        try:
            rate = Decimal(value)
        except (ValueError, ArithmeticError) as exc:
            raise ValueError("invalid tax rate") from exc
        if not rate.is_finite() or not 0 <= rate <= 1:
            raise ValueError("tax rates must be finite fractions between zero and one")
        return rate

    @model_validator(mode="after")
    def state_default_bound(self) -> Self:
        if self.state != DEFAULT_STATE and "state_rate" not in self.model_fields_set:
            raise ValueError(
                "a changed state requires its explicit rate; Texas zero cannot carry over"
            )
        return self

    @property
    def estimate_available(self) -> bool:
        """TX-08: all four rates are required even when a realized total is zero."""
        return all(
            rate is not None
            for rate in (
                self.federal_st_rate,
                self.federal_lt_rate,
                self.state_rate,
                self.niit_rate,
            )
        )
