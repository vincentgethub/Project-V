"""XA-01: physical fills, immutable arrival evidence and upward cost calibration."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import (
    ExecutionFillRecord,
    ExecutionOrderRecord,
    Order,
    SecurityEvent,
    Signal,
    transaction,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, MarketContext, Price, Side, UTCDateTime
from backend.evaluation.costs import CostOrder, arrival_reference, half_spread
from backend.evaluation.fill_quality import Bucket, FillQuality, QualityBucket, monthly
from backend.evaluation.provenance import EvaluationProvenance
from backend.ops.trading_controls import ControlScope


class ArrivalEvidence(FrozenModel):
    execution_order_id: UUID
    scope: ControlScope
    quote: Price
    quoted_at: UTCDateTime
    observed_at: UTCDateTime
    stale_seconds: int = Field(strict=True, ge=1, le=300)

    @model_validator(mode="after")
    def fresh(self) -> "ArrivalEvidence":
        if (
            not timedelta(0)
            <= self.observed_at - self.quoted_at
            <= timedelta(seconds=self.stale_seconds)
        ):
            raise ValueError("XA-01: stale or future quote cannot prove order arrival")
        return self

    @classmethod
    def recorded(cls, values: dict[str, Any]) -> "ArrivalEvidence":
        return cls.model_validate(
            {
                **values,
                "quote": Decimal(values["quote"]),
                "quoted_at": datetime.fromisoformat(values["quoted_at"]),
                "observed_at": datetime.fromisoformat(values["observed_at"]),
            }
        )


def record_arrival(
    ledger: Ledger,
    instruction: ExecutionOrderRecord,
    market: MarketContext | None,
    stale_seconds: int,
) -> None:
    if market is None:
        return
    checked = MarketContext.model_validate(market)
    now = ledger.clock.now()
    if not timedelta(0) <= now - checked.last_price_ts <= timedelta(seconds=stale_seconds):
        return  # Monitoring/protection never waits for optional arrival evidence.
    proof = ArrivalEvidence(
        execution_order_id=instruction.id,
        scope=ControlScope.model_validate(
            {"account_id": instruction.account_id, "environment": instruction.environment}
        ),
        quote=checked.last_price,
        quoted_at=checked.last_price_ts,
        observed_at=now,
        stale_seconds=stale_seconds,
    )
    with Session(ledger.engine) as session:
        previous = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "ORDER_ARRIVAL",
                SecurityEvent.detail["execution_order_id"].as_string() == str(instruction.id),
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if previous is not None:
            old = ArrivalEvidence.recorded(previous.detail)
            if (old.scope, old.quote, old.quoted_at) == (proof.scope, proof.quote, proof.quoted_at):
                return
    ledger.append(SecurityEvent, kind="ORDER_ARRIVAL", detail=proof.model_dump(mode="json"))


def quality_recorded(payload: dict[str, Any]) -> FillQuality:
    values = dict(payload)
    values["filled_at"] = datetime.fromisoformat(values["filled_at"])
    values["arrival_at"] = (
        None if values["arrival_at"] is None else datetime.fromisoformat(values["arrival_at"])
    )
    for field in ("fill_price", "decision_price", "limit_price", "arrival_price", "modeled_price"):
        values[field] = None if values[field] is None else Decimal(values[field])
    return FillQuality.model_validate(values)


def capture(ledger: Ledger, fill: ExecutionFillRecord) -> FillQuality:
    """One physical identity; unavailable arrival is visible and cannot calibrate."""
    with transaction(ledger.engine) as session:
        ledger._verify_in_session(session)
        prior = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "FILL_QUALITY",
                SecurityEvent.detail["fill_id"].as_string() == str(fill.id),
            )
            .limit(1)
        )
        if prior is not None:
            return quality_recorded(prior.detail)
        instruction = session.get(ExecutionOrderRecord, fill.execution_order_id)
        if instruction is None:
            raise DataIntegrityError("XA-01: canonical physical instruction unavailable")
        order = session.get(Order, instruction.order_id)
        signal = None if order is None else session.get(Signal, order.signal_id)
        provenance = (
            None
            if signal is None or "evaluation_provenance" not in signal.structured_thesis
            else EvaluationProvenance.from_recorded(
                signal.structured_thesis["evaluation_provenance"]
            )
        )
        arrivals = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "ORDER_ARRIVAL",
                    SecurityEvent.detail["execution_order_id"].as_string() == str(instruction.id),
                    SecurityEvent.created_at <= fill.filled_at,
                    SecurityEvent.created_at >= (fill.filled_at - timedelta(minutes=5))
                    if instruction.order_type == "STOP"
                    else SecurityEvent.created_at >= instruction.created_at,
                )
                .order_by(SecurityEvent.seq.desc())
                .limit(101)
            )
        )
        if len(arrivals) > 100:
            raise DataIntegrityError("XA-01: arrival evidence exceeds its bound")
        scope = ControlScope.model_validate(
            {"account_id": instruction.account_id, "environment": instruction.environment}
        )
        arrival = None
        for event in arrivals:
            proof = ArrivalEvidence.recorded(event.detail)
            if (
                proof.execution_order_id != instruction.id
                or proof.scope != scope
                or proof.observed_at > event.created_at
            ):
                raise DataIntegrityError("XA-01: arrival evidence is unbound or future")
            if proof.observed_at <= fill.filled_at:
                if (
                    instruction.order_type == "STOP"
                    and fill.filled_at - proof.quoted_at > timedelta(seconds=proof.stale_seconds)
                ):
                    continue
                arrival = proof
                break
        ctx = None if provenance is None else provenance.cost_context
        is_stop = instruction.order_type == "STOP"
        decision = instruction.stop_price if is_stop else instruction.limit_price
        spread = None if ctx is None else half_spread(ctx)[0]
        volume = None if ctx is None else ctx.median_dollar_volume_20
        bucket: Bucket = (
            "HIGH"
            if volume is not None and volume >= 500000000
            else "MID"
            if volume is not None and volume >= 50000000
            else "LOW"
        )
        modeled = None
        if arrival is not None and ctx is not None and decision is not None:
            modeled = arrival_reference(
                CostOrder(
                    side=Side(instruction.side),
                    kind="ENTRY"
                    if instruction.role == "ENTRY"
                    else "STOP"
                    if is_stop
                    else "TARGET"
                    if instruction.role == "TARGET" or instruction.target_price is not None
                    else "SIGNAL",
                    qty=fill.qty,
                    level=decision
                    if instruction.role in {"ENTRY", "TARGET"}
                    or is_stop
                    or instruction.target_price is not None
                    else None,
                    decision_session=fill.filled_at.date(),
                ),
                arrival.quote,
                ctx,
            )
        quality = FillQuality(
            scope=scope,
            fill_id=fill.id,
            symbol=instruction.symbol,
            side=Side(instruction.side),
            filled_at=fill.filled_at,
            qty=fill.qty,
            fill_price=fill.price,
            decision_price=decision,
            limit_price=instruction.limit_price,
            arrival_price=None if arrival is None else arrival.quote,
            arrival_at=None if arrival is None else arrival.quoted_at,
            modeled_price=modeled,
            model_half_spread_bps=spread,
            bucket=bucket,
            is_stop=is_stop,
            unavailable_reason=None
            if modeled is not None
            else "Arrival quote or immutable CM evidence unavailable",
        )
        ledger.append_in_session(
            session, SecurityEvent, kind="FILL_QUALITY", detail=quality.model_dump(mode="json")
        )
        return quality


def inventory(ledger: Ledger, scope: ControlScope) -> tuple[FillQuality, ...]:
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        events = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "FILL_QUALITY")
                .order_by(SecurityEvent.seq)
                .limit(100001)
            )
        )
        if len(events) > 100000:
            raise DataIntegrityError("XA-01: bounded fill-quality inventory required")
        rows = tuple(quality_recorded(event.detail) for event in events)
        for row in rows:
            fill = session.get(ExecutionFillRecord, row.fill_id)
            instruction = (
                None if fill is None else session.get(ExecutionOrderRecord, fill.execution_order_id)
            )
            if (
                fill is None
                or instruction is None
                or (fill.price, fill.qty, fill.filled_at)
                != (row.fill_price, row.qty, row.filled_at)
                or (
                    instruction.account_id,
                    instruction.environment,
                    instruction.symbol,
                    instruction.side,
                )
                != (row.scope.account_id, row.scope.environment, row.symbol, row.side.value)
            ):
                raise DataIntegrityError("XA-01: quality differs from its canonical physical fill")
        return tuple(row for row in rows if row.scope == scope)


def capture_pending(ledger: Ledger, scope: ControlScope) -> None:
    """Weekly reconciliation adds missing legacy quality rows as UNAVAILABLE."""
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        quality_events = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "FILL_QUALITY").limit(100001)
            )
        )
        if len(quality_events) > 100000:
            raise DataIntegrityError("XA-01: quality inventory exceeds its bound")
        known = {quality_recorded(row.detail).fill_id for row in quality_events}
        fills = tuple(
            session.scalars(
                select(ExecutionFillRecord)
                .join(
                    ExecutionOrderRecord,
                    ExecutionFillRecord.execution_order_id == ExecutionOrderRecord.id,
                )
                .where(
                    ExecutionOrderRecord.account_id == scope.account_id,
                    ExecutionOrderRecord.environment == scope.environment,
                )
                .order_by(ExecutionFillRecord.seq)
                .limit(100001)
            )
        )
        if len(fills) > 100000 or any(row.filled_at > ledger.clock.now() for row in fills):
            raise DataIntegrityError("XA-01: bounded past physical inventory required")
    for fill in fills:
        if fill.id not in known:
            capture(ledger, fill)


def calibration(
    ledger: Ledger, scope: ControlScope, month: str, bucket: str, model: Decimal
) -> QualityBucket:
    if bucket not in {"HIGH", "MID", "LOW"}:
        raise DataIntegrityError("XA-01: known liquidity bucket required")
    from typing import cast

    from backend.evaluation.calibrated_costs import snapshot
    from backend.evaluation.fill_quality import Bucket

    prior = snapshot(ledger, scope.environment, scope=scope)
    previous_cost = {"HIGH": prior.high, "MID": prior.mid, "LOW": prior.low}[bucket]
    result = monthly(
        scope, month, cast(Bucket, bucket), inventory(ledger, scope), max(model, previous_cost)
    )
    with transaction(ledger.engine) as session:
        ledger._verify_in_session(session)
        latest = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "COST_CALIBRATION",
                SecurityEvent.detail["scope"]["account_id"].as_string() == scope.account_id,
                SecurityEvent.detail["scope"]["environment"].as_string() == scope.environment,
                SecurityEvent.detail["month"].as_string() == month,
                SecurityEvent.detail["bucket"].as_string() == bucket,
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if latest is None or QualityBucket.model_validate(latest.detail) != result:
            ledger.append_in_session(
                session,
                SecurityEvent,
                kind="COST_CALIBRATION",
                detail=result.model_dump(mode="json"),
            )
    return result
