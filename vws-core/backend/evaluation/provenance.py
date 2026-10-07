"""EV-01: code-produced costs and equity bound to the immutable proposal."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.data.historical_spread import SpreadMeasurement
from backend.domain.models import FrozenModel, Money, SessionDate, UTCDateTime
from backend.evaluation.costs import CostContext


class EvaluationProvenance(FrozenModel):
    cohort: Literal["PAPER", "LIVE"]
    expires_at: UTCDateTime
    yaml_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    settings_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_session: SessionDate
    cost_context: CostContext
    initial_equity: Money
    spread_measurement: SpreadMeasurement | None = None

    @model_validator(mode="after")
    def bound(self) -> Self:
        measurement = self.spread_measurement
        median = None if measurement is None else measurement.half_spread_bps
        if self.cost_context.measured_half_spread_bps != median or (
            measurement is not None and measurement.session != self.evidence_session
        ):
            raise ValueError("CM-01: recorded cost differs from its quote evidence")
        return self

    @classmethod
    def from_recorded(cls, payload: dict[str, Any]) -> EvaluationProvenance:
        try:
            values = dict(payload)
            values["expires_at"] = datetime.fromisoformat(values["expires_at"])
            values["evidence_session"] = date.fromisoformat(values["evidence_session"])
            if values.get("spread_measurement") is not None:
                measurement = dict(values["spread_measurement"])
                measurement["session"] = date.fromisoformat(measurement["session"])
                for name in ("window_start", "window_end", "fetched_at"):
                    measurement[name] = datetime.fromisoformat(measurement[name])
                values["spread_measurement"] = measurement
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError(
                "EV-01: recorded cost/expiry provenance is unverifiable"
            ) from None
