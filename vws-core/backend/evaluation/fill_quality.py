"""XA-01/02: execution cost evidence and drift flags; no settings writes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.domain.models import FrozenModel, Money, Playbook, Price, Side, Symbol, UTCDateTime
from backend.evaluation.costs import Exact, FeeSchedule
from backend.indicators.statistics import circular_bootstrap
from backend.ops.trading_controls import ControlScope

if TYPE_CHECKING:
    from backend.core.config import Settings, YamlConfig
    from backend.core.ledger import Ledger

Bucket = Literal["HIGH", "MID", "LOW"]


class FillQuality(FrozenModel):
    scope: ControlScope
    fill_id: UUID
    symbol: Symbol
    side: Side
    filled_at: UTCDateTime
    qty: int = Field(strict=True, gt=0, le=10**9)
    fill_price: Price
    decision_price: Price | None
    limit_price: Price | None
    arrival_price: Price | None
    arrival_at: UTCDateTime | None
    modeled_price: Price | None
    model_half_spread_bps: Money | None = Field(ge=0)
    bucket: Bucket
    is_stop: bool = Field(strict=True)
    unavailable_reason: str | None = Field(strict=True, min_length=1, max_length=280)

    @model_validator(mode="after")
    def availability(self) -> FillQuality:
        available = all(
            value is not None
            for value in (
                self.decision_price,
                self.arrival_price,
                self.arrival_at,
                self.modeled_price,
                self.model_half_spread_bps,
            )
        )
        available = available and (self.is_stop or self.limit_price is not None)
        if (
            available != (self.unavailable_reason is None)
            or (self.arrival_at is None) != (self.arrival_price is None)
            or self.arrival_at is not None
            and self.arrival_at > self.filled_at
        ):
            raise ValueError(
                "XA-01: missing or future arrival/model evidence cannot be treated as verified"
            )
        return self

    def slippage(self, reference: Decimal | None) -> Decimal | None:
        checked = FillQuality.model_validate(self)
        if reference is None:
            return None
        if not isinstance(reference, Decimal) or not reference.is_finite() or reference <= 0:
            raise DataIntegrityError("XA-01: exact positive reference required")
        with localcontext() as context:
            context.prec = 256
            sign = Decimal(1) if checked.side == Side.BUY else Decimal(-1)
            return (sign * (checked.fill_price / reference - 1) * 10000).quantize(
                Decimal("0.000001")
            )

    @property
    def arrival_slippage_bps(self) -> Decimal | None:
        return self.slippage(self.arrival_price)

    @property
    def model_slippage_bps(self) -> Decimal | None:
        return self.slippage(self.modeled_price)


class QualityBucket(FrozenModel):
    scope: ControlScope
    month: str = Field(strict=True, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    bucket: Bucket
    n: int = Field(strict=True, ge=0)
    unavailable: int = Field(strict=True, ge=0)
    p50_bps: Money | None
    p90_bps: Money | None
    stop_p90_bps: Money | None
    calibrated_half_spread_bps: Money = Field(ge=0)


def percentile(values: tuple[Decimal, ...], quantile: Decimal) -> Decimal | None:
    if (
        not isinstance(values, tuple)
        or not isinstance(quantile, Decimal)
        or not quantile.is_finite()
        or not 0 <= quantile <= 1
        or any(not isinstance(x, Decimal) or not x.is_finite() for x in values)
    ):
        raise DataIntegrityError("XA-01: immutable exact sample required")
    if not values:
        return None
    ordered = sorted(values)
    with localcontext() as context:
        context.prec = 256
        index = quantile * (len(ordered) - 1)
        lower = int(index)
        return (
            ordered[lower]
            + (index - lower) * (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower])
        ).quantize(Decimal("0.000001"))


def monthly(
    scope: ControlScope, month: str, bucket: Bucket, fills: tuple[FillQuality, ...], model: Decimal
) -> QualityBucket:
    checked = ControlScope.model_validate(scope)
    try:
        start = date.fromisoformat(month + "-01")
    except Exception:
        raise DataIntegrityError("XA-01: YYYY-MM required") from None
    if (
        not isinstance(fills, tuple)
        or len(fills) > 100000
        or not isinstance(model, Decimal)
        or not model.is_finite()
        or model < 0
    ):
        raise DataIntegrityError("XA-01: bounded immutable fills and exact model required")
    rows = tuple(FillQuality.model_validate(row) for row in fills)
    if len({row.fill_id for row in rows}) != len(rows):
        raise DataIntegrityError("XA-01: duplicate physical fill identity")
    selected = tuple(
        row
        for row in rows
        if row.scope == checked
        and row.bucket == bucket
        and (
            row.filled_at.astimezone(ZoneInfo("America/New_York")).year,
            row.filled_at.astimezone(ZoneInfo("America/New_York")).month,
        )
        == (start.year, start.month)
    )
    verified = tuple(row for row in selected if row.unavailable_reason is None)
    slip = tuple(value for row in verified if (value := row.arrival_slippage_bps) is not None)
    stops = tuple(
        value for row in verified if row.is_stop and (value := row.arrival_slippage_bps) is not None
    )
    median = percentile(slip, Decimal("0.5"))
    calibration = model
    if len(verified) >= 20 and median is not None and median > model + 2:
        calibration = max(model, median)
    return QualityBucket(
        scope=checked,
        month=month,
        bucket=bucket,
        n=len(verified),
        unavailable=len(selected) - len(verified),
        p50_bps=median,
        p90_bps=percentile(slip, Decimal("0.9")),
        stop_p90_bps=percentile(stops, Decimal("0.9")),
        calibrated_half_spread_bps=calibration,
    )


def edge_drift(
    paper: tuple[Decimal, ...], oos: tuple[Decimal, ...], *, seed: int = 20261006
) -> bool | None:
    # Validate even short samples. Missing OOS remains unavailable, never clear.
    estimate = circular_bootstrap(oos, seed=seed)
    circular_bootstrap(paper, seed=seed)
    if len(paper) < 30 or estimate is None:
        return None
    with localcontext() as context:
        context.prec = 256
        return sum(paper, Decimal(0)) / len(paper) < estimate.lower


class DriftCheck(FrozenModel):
    """XA-02: after-cost paper and OOS stay separately identified."""

    scope: ControlScope
    playbook: Playbook
    paper: tuple[Exact, ...] = Field(max_length=100000)
    oos: tuple[Exact, ...] = Field(max_length=100000)
    seed: int = Field(strict=True, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def paper_only(self) -> DriftCheck:
        if self.scope.environment != "PAPER":
            raise ValueError("XA-02: only physical paper trades can measure paper edge drift")
        return self

    @property
    def flag(self) -> bool | None:
        return edge_drift(self.paper, self.oos, seed=self.seed)


def drift_rows(
    ledger: Ledger,
    settings: Settings,
    config: YamlConfig,
    scope: ControlScope,
    schedule: FeeSchedule,
) -> tuple[DriftCheck, ...]:
    from backend.evaluation.availability import GradeStore
    from backend.evaluation.physical import resolved_trades

    physical = resolved_trades(ledger, scope, schedule, config=config)
    oos = GradeStore(ledger, settings, config).oos_by_playbook()
    return tuple(
        DriftCheck(
            scope=scope,
            playbook=Playbook(name),
            paper=tuple(row.r_multiple for row in physical if row.playbook.value == name),
            oos=oos.get(Playbook(name), ()),
            seed=config.qv.seed,
        )
        for name in config.enabled_playbooks
    )
