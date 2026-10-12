"""XA/CM/QV: frozen, scoped cost increases; never writes fees or parameters."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, Money, UTCDateTime
from backend.evaluation.costs import CostContext
from backend.evaluation.fill_quality import QualityBucket
from backend.ops.trading_controls import ControlScope


class CostCalibration(FrozenModel):
    scope: ControlScope | None = None
    source_ids: tuple[UUID, ...] = Field(default=(), max_length=1000)
    high: Money = Field(default=Decimal(0), ge=0, le=10000)
    mid: Money = Field(default=Decimal(0), ge=0, le=10000)
    low: Money = Field(default=Decimal(0), ge=0, le=10000)
    observed_at: UTCDateTime | None = None

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.scope is None:
            if (
                self.source_ids
                or self.observed_at is not None
                or any((self.high, self.mid, self.low))
            ):
                raise ValueError("XA-01: absent calibration cannot claim measured costs")
        elif (
            not self.source_ids
            or self.observed_at is None
            or len(set(self.source_ids)) != len(self.source_ids)
        ):
            raise ValueError("XA-01: scoped calibration requires distinct immutable sources")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def context(self, cost: CostContext) -> CostContext:
        source = CostContext.model_validate(cost)
        if self.scope is None:
            return source
        volume = source.median_dollar_volume_20
        value = (
            self.high
            if volume is not None and volume >= 500000000
            else self.mid
            if volume is not None and volume >= 50000000
            else self.low
        )
        return CostContext.model_validate(
            {
                **source.model_dump(),
                "calibrated_half_spread_bps": max(
                    value, source.calibrated_half_spread_bps or Decimal(0)
                ),
                "calibration_sha256": self.sha256,
            }
        )

    @classmethod
    def recorded(cls, values: dict[str, Any]) -> "CostCalibration":
        return cls.model_validate(
            {
                **values,
                "observed_at": None
                if values["observed_at"] is None
                else datetime.fromisoformat(values["observed_at"]),
            }
        )


def snapshot(
    ledger: Ledger, environment: Literal["PAPER", "LIVE"], *, scope: ControlScope | None = None
) -> CostCalibration:
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        events = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "COST_CALIBRATION")
                .order_by(SecurityEvent.seq)
                .limit(1001)
            )
        )
        if len(events) > 1000:
            raise DataIntegrityError("XA-01: calibration inventory exceeds its bound")
        selected = []
        for event in events:
            row = QualityBucket.model_validate(event.detail)
            if event.created_at > ledger.clock.now():
                raise DataIntegrityError("XA-01: future cost calibration")
            if row.scope.environment == environment and (scope is None or row.scope == scope):
                selected.append((event, row))
        if not selected:
            return CostCalibration()
        scopes = {row.scope for _, row in selected}
        if len(scopes) != 1:
            raise DataIntegrityError("XA-01: multiple account calibrations cannot be mixed")
        values = {
            bucket: max(
                (row.calibrated_half_spread_bps for _, row in selected if row.bucket == bucket),
                default=Decimal(0),
            )
            for bucket in ("HIGH", "MID", "LOW")
        }
        return CostCalibration(
            scope=selected[-1][1].scope,
            source_ids=tuple(event.id for event, _ in selected),
            high=values["HIGH"],
            mid=values["MID"],
            low=values["LOW"],
            observed_at=selected[-1][0].created_at,
        )
