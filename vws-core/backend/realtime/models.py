"""RT/EVT/AC: bounded frozen public observations and exact reducing context."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.data.history import Digest
from backend.domain.models import FrozenModel, Money, Symbol, UTCDateTime
from backend.ops.trading_controls import ControlScope

Feed = Literal["clock", "halts", "news", "assets", "ca", "edgar", "fred", "macro"]
REQUIRED: tuple[Feed, ...] = ("clock", "halts", "news", "assets")


class HealthStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class ContextTag(StrEnum):
    HALT = "halt"
    NEWS_NEG = "news_neg"
    VIX_STRESS = "vix_stress"
    FOMC = "fomc_day"
    CPI = "cpi_day"
    JOBS = "jobs_day"
    GDP = "gdp_day"
    PCE = "pce_day"
    OPEX = "opex"
    WITCHING = "witching"
    EARLY_CLOSE = "early_close"
    CA_PENDING = "ca_pending"
    DELIST = "delisting"
    DILUTION = "edgar_dilution"
    ASSET_INACTIVE = "asset_inactive"
    MWC1 = "mwc1"
    MWC2 = "mwc2"
    MWC3 = "mwc3"
    UNAVAILABLE = "rt_unavailable"
    CLOCK_SKEW = "clock_skew"


class FeedHealth(FrozenModel):
    feed: Feed
    status: HealthStatus
    observed_at: UTCDateTime
    detail: str = Field(strict=True, min_length=1, max_length=280)
    symbols: tuple[Symbol, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if self.symbols != tuple(sorted(set(self.symbols))):
            raise ValueError("RT: asset coverage is ordered and unique")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "FeedHealth":
        try:
            values = dict(payload)
            values["observed_at"] = datetime.fromisoformat(values["observed_at"])
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("RT: stored feed health is malformed") from None


class RealtimeEvent(FrozenModel):
    feed: Feed
    provider_id: str = Field(strict=True, min_length=1, max_length=160)
    kind: Literal[
        "NEWS_NEG",
        "HALT_NEWS",
        "OTHER",
        "HALT",
        "RESUME",
        "MWC1",
        "MWC2",
        "MWC3",
        "ASSET_INACTIVE",
        "ASSET_ACTIVE",
        "CA_PENDING",
        "DELIST",
        "DILUTION",
        "FILING",
        "VIX",
    ]
    symbol: Symbol | None = None
    occurred_at: UTCDateTime
    observed_at: UTCDateTime
    expires_at: UTCDateTime
    text: str = Field(default="Public feed observation", strict=True, max_length=1000)
    value: Money | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def causal(self) -> Self:
        global_kind = self.kind in {"MWC1", "MWC2", "MWC3", "VIX"}
        if (
            self.occurred_at > self.observed_at
            or self.expires_at <= self.occurred_at
            or global_kind != (self.symbol is None)
            or (self.kind == "VIX") != (self.value is not None)
        ):
            raise ValueError("RT: causal, scoped public event required")
        return self

    @property
    def critical(self) -> bool:
        return not (self.feed == "news" and self.kind == "OTHER")

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "RealtimeEvent":
        try:
            values = dict(payload)
            for name in ("occurred_at", "observed_at", "expires_at"):
                values[name] = datetime.fromisoformat(values[name])
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("RT: stored event is malformed") from None


class RealtimeContext(FrozenModel):
    scope: ControlScope
    symbol: Symbol
    as_of: UTCDateTime
    policy_sha256: Digest
    tags: tuple[ContextTag, ...] = Field(default=(), max_length=21)
    entry_multiplier: Money = Field(ge=0, le=1)
    warnings: tuple[str, ...] = Field(default=(), max_length=10)
    blocked: bool = Field(strict=True)

    @model_validator(mode="after")
    def exact(self) -> Self:
        if (
            len(set(self.tags)) != len(self.tags)
            or any(
                not isinstance(value, str) or not 1 <= len(value) <= 280 for value in self.warnings
            )
            or self.blocked != (self.entry_multiplier == Decimal(0))
        ):
            raise ValueError("RT/EVT: bounded unique context cannot raise exposure")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "RealtimeContext":
        try:
            values = dict(payload)
            values["as_of"] = datetime.fromisoformat(values["as_of"])
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("RT: stored proposal context is malformed") from None
