"""GD-03: typed public research protocols and explicit unavailable/fake providers."""

from datetime import datetime
from decimal import Decimal
from typing import Protocol, Self

from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.data.news import FakeNewsProvider as FakeNewsProvider
from backend.data.news import NewsProvider as NewsProvider
from backend.domain.models import (
    EarningsInfo,
    EarningsStatus,
    FlowSignal,
    FrozenModel,
    Money,
    ProviderStatus,
    Symbol,
    UTCDateTime,
    validate_symbol,
)


class FlowProvider(Protocol):
    async def get(self, symbol: str, as_of: datetime) -> FlowSignal: ...


class EarningsProvider(Protocol):
    async def get(self, symbol: str, as_of: datetime) -> EarningsInfo: ...


class IVComparison(FrozenModel):
    """Annualized public ratios. Unavailable evidence carries no values."""

    symbol: Symbol
    as_of: UTCDateTime
    status: ProviderStatus
    implied_volatility: Money | None = Field(default=None, ge=0, le=Decimal("10"))
    historical_volatility: Money | None = Field(default=None, ge=0, le=Decimal("10"))
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        values = (self.implied_volatility, self.historical_volatility)
        if self.status == ProviderStatus.OK:
            if None in values or not self.evidence_ids:
                raise ValueError("OK IV comparison needs both public values and evidence")
        elif any(value is not None for value in values) or self.evidence_ids:
            raise ValueError("unavailable IV cannot carry values or evidence")
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or any(
            not value.strip() or len(value) > 100 for value in self.evidence_ids
        ):
            raise ValueError("IV evidence identifiers must be bounded and unique")
        return self


class IVProvider(Protocol):
    async def get(self, symbol: str, as_of: datetime) -> IVComparison: ...


class NullFlowProvider:
    async def get(self, symbol: str, as_of: datetime) -> FlowSignal:
        validate_symbol(symbol)
        ensure_utc(as_of)
        return FlowSignal(status=ProviderStatus.UNAVAILABLE)


class NullIVProvider:
    async def get(self, symbol: str, as_of: datetime) -> IVComparison:
        return IVComparison(
            symbol=symbol, as_of=ensure_utc(as_of), status=ProviderStatus.UNAVAILABLE
        )


class NullEarningsProvider:
    async def get(self, symbol: str, as_of: datetime) -> EarningsInfo:
        validate_symbol(symbol)
        ensure_utc(as_of)
        return EarningsInfo(status=EarningsStatus.UNKNOWN, source="unavailable")


class FakeFlowProvider:
    def __init__(self, symbol: str, result: FlowSignal) -> None:
        self.symbol, self.result = validate_symbol(symbol), FlowSignal.model_validate(result)

    async def get(self, symbol: str, as_of: datetime) -> FlowSignal:
        validate_symbol(symbol)
        ensure_utc(as_of)
        return (
            FlowSignal.model_validate(self.result)
            if symbol == self.symbol
            else FlowSignal(status=ProviderStatus.UNAVAILABLE)
        )


class FakeIVProvider:
    def __init__(self, result: IVComparison) -> None:
        self.result = IVComparison.model_validate(result)

    async def get(self, symbol: str, as_of: datetime) -> IVComparison:
        instant = ensure_utc(as_of)
        if symbol == self.result.symbol and self.result.as_of <= instant:
            return IVComparison.model_validate(self.result)
        return IVComparison(symbol=symbol, as_of=instant, status=ProviderStatus.UNAVAILABLE)


class FakeEarningsProvider:
    def __init__(self, symbol: str, result: EarningsInfo) -> None:
        self.symbol, self.result = validate_symbol(symbol), EarningsInfo.model_validate(result)

    async def get(self, symbol: str, as_of: datetime) -> EarningsInfo:
        validate_symbol(symbol)
        ensure_utc(as_of)
        if symbol == self.symbol:
            return EarningsInfo.model_validate(self.result)
        return EarningsInfo(status=EarningsStatus.UNKNOWN, source="unavailable")
