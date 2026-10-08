"""PL-01..04: exact flow-adjusted daily accounting and immutable observations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.domain.models import FrozenModel, Identifier, Money, SessionDate, UTCDateTime
from backend.tax.models import Environment

MAX_PNL_SESSIONS = 20000


def exact_ratio(value: object) -> Decimal:
    if (
        not isinstance(value, (Decimal, str, int))
        or isinstance(value, bool)
        or len(str(value)) > 256
    ):
        raise ValueError("PL-02: finite exact ratio required")
    try:
        result = Decimal(value)
        if not result.is_finite() or result.copy_abs() > Decimal("1e12"):
            raise ValueError("PL-02: ratio exceeds its bound")
        exponent = result.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -100:
            raise ValueError("PL-02: ratio exceeds its bound")
        return result
    except ArithmeticError:
        raise ValueError("PL-02: invalid ratio") from None


Ratio = Annotated[Decimal, BeforeValidator(exact_ratio)]


class DayInput(FrozenModel):
    account_id: Identifier
    env: Environment
    session: SessionDate
    as_of: UTCDateTime
    equity_start: Money = Field(ge=0)
    equity: Money = Field(gt=0)
    cash: Money = Field(ge=0)
    long_market_value: Money = Field(ge=0)
    external_flows: Money
    realized: Money
    dividends: Money
    interest: Money
    fees: Money = Field(ge=0)
    source: Literal["BROKER", "COMPUTED"]
    reported_unrealized_change: Money | None = None
    provenance_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def long_account(self) -> Self:
        with localcontext() as precision:
            precision.prec = 80
            if self.equity_start + self.external_flows <= 0 or abs(
                self.equity - self.cash - self.long_market_value
            ) > Decimal("0.01"):
                raise ValueError(
                    "PL-01: equity components or flow-adjusted starting equity contradict"
                )
        return self


class PnLDay(FrozenModel):
    observation: DayInput
    day_pnl: Money
    day_ret: Ratio
    unrealized_change: Money
    source: Literal["BROKER", "COMPUTED"]
    alerts: tuple[str, ...] = Field(max_length=2)

    @model_validator(mode="after")
    def exact_day(self) -> Self:
        source = self.observation
        with localcontext() as precision:
            precision.prec = 80
            pnl = source.equity - source.equity_start - source.external_flows
            ret = source.equity / (source.equity_start + source.external_flows) - 1
            unrealized = pnl - source.realized - source.dividends - source.interest + source.fees
            alerts = (
                ("PL-02: reported component identity differs by more than one cent",)
                if source.reported_unrealized_change is not None
                and abs(source.reported_unrealized_change - unrealized) > Decimal("0.01")
                else ()
            )
            if (
                self.day_pnl != pnl
                or self.day_ret != ret
                or self.unrealized_change != unrealized
                or self.alerts != alerts
                or self.source != ("COMPUTED" if alerts else source.source)
            ):
                raise ValueError("PL-02: daily math/status differs from exact observations")
        return self

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> PnLDay:
        try:
            values = dict(payload)
            raw = values["observation"]
            if not isinstance(raw, dict):
                raise ValueError("missing daily observation")
            observation = dict(raw)
            observation["session"] = date.fromisoformat(observation["session"])
            observation["as_of"] = datetime.fromisoformat(observation["as_of"])
            values["observation"] = DayInput.model_validate(observation)
            alerts = values["alerts"]
            if not isinstance(alerts, (list, tuple)):
                raise ValueError("missing daily alerts")
            values["alerts"] = tuple(alerts)
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("PL-01: stored daily evidence cannot be verified") from None


def build_day(observation: DayInput) -> PnLDay:
    try:
        source = DayInput.model_validate(observation)
        with localcontext() as precision:
            precision.prec = 80
            pnl = source.equity - source.equity_start - source.external_flows
            ret = source.equity / (source.equity_start + source.external_flows) - 1
            unrealized = pnl - source.realized - source.dividends - source.interest + source.fees
            alerts = (
                ("PL-02: reported component identity differs by more than one cent",)
                if source.reported_unrealized_change is not None
                and abs(source.reported_unrealized_change - unrealized) > Decimal("0.01")
                else ()
            )
        return PnLDay(
            observation=source,
            day_pnl=pnl,
            day_ret=ret,
            unrealized_change=unrealized,
            source="COMPUTED" if alerts else source.source,
            alerts=alerts,
        )
    except Exception:
        raise DataIntegrityError("PL-01/02: daily accounting input is unverifiable") from None
