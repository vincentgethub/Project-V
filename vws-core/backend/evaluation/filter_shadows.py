"""ER-04: immutable counterfactuals; never order approvals or broker instructions."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import select

from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, SetupCandidate, SizeEvidence
from backend.evaluation.provenance import EvaluationProvenance
from backend.ops.trading_controls import ControlScope

Filter = Literal["PR_FILTER", "RS_FILTER", "SZ_FILTER", "CRO_VETO"]
NAMESPACE = UUID("5d176ad9-6d26-44a0-a80b-80122f9e1c2b")


def filters(factors: SizeEvidence, *, accepted_qty: int | None = None) -> tuple[Filter, ...]:
    checked = SizeEvidence.model_validate(factors)
    result: list[Filter] = []
    if any(
        value < 1
        for value in (
            checked.regime,
            checked.ramp,
            checked.correlation,
            checked.volatility,
            checked.events,
        )
    ):
        result.append("PR_FILTER")
    if checked.relative_strength < 1:
        result.append("RS_FILTER")
    if checked.confidence < 1:
        result.append("SZ_FILTER")
    if accepted_qty is not None:
        if type(accepted_qty) is not int or not 0 <= accepted_qty <= checked.qty:
            raise DataIntegrityError("ER-04: CRO cap must not increase overlay quantity")
        if accepted_qty < checked.qty:
            result.append("CRO_VETO")
    return tuple(result)


class FilterShadow(FrozenModel):
    identity: UUID
    scope: ControlScope
    data_snapshot_id: UUID
    candidate: SetupCandidate
    factors: SizeEvidence
    provenance: EvaluationProvenance
    cro_cap: int | None = Field(
        default=None, strict=True, ge=0, le=10**9, exclude_if=lambda v: v is None
    )

    @property
    def cohorts(self) -> tuple[Filter, ...]:
        return filters(self.factors, accepted_qty=self.cro_cap)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (
            self.candidate.qty != self.factors.base_qty
            or not self.cohorts
            or self.candidate.size_evidence is not None
            or min(self.factors.qty, self.cro_cap if self.cro_cap is not None else self.factors.qty)
            != 0
            or self.provenance.cohort != self.scope.environment
        ):
            raise ValueError("ER-04: zero-sized shadow must retain its unsized, scoped proof")
        expected = uuid5(
            NAMESPACE,
            f"{self.scope.account_id}/{self.scope.environment}/{self.data_snapshot_id}/{self.candidate.playbook}/{self.candidate.as_of}/{self.provenance.yaml_hash}",
        )
        if self.identity != expected:
            raise ValueError("ER-04: shadow identity differs from its immutable source")
        return self

    @classmethod
    def recorded(cls, values: dict[str, Any]) -> "FilterShadow":
        try:
            payload = dict(values)
            candidate = dict(payload["candidate"])
            candidate["as_of"] = datetime.fromisoformat(candidate["as_of"])
            for key in ("entry_price", "stop_price", "target_price"):
                candidate[key] = Decimal(candidate[key])
            payload["candidate"] = candidate
            payload["provenance"] = EvaluationProvenance.from_recorded(payload["provenance"])
            return cls.model_validate(payload)
        except Exception:
            raise DataIntegrityError("ER-04: recorded filter proof is unverifiable") from None


def record(ledger: Ledger, shadow: FilterShadow) -> None:
    checked = FilterShadow.model_validate(shadow)
    if checked.candidate.as_of > ledger.clock.now():
        raise DataIntegrityError("ER-04: future filter shadow refused")
    ledger.verify_chain()
    with transaction(ledger.engine) as session:
        ledger._verify_in_session(session)
        previous = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "FILTER_SHADOW",
                SecurityEvent.detail["identity"].as_string() == str(checked.identity),
            )
            .limit(1)
        )
        if previous is not None:
            if FilterShadow.recorded(previous.detail) != checked:
                raise DataIntegrityError("ER-04: repeated shadow changed its evidence")
            return
        ledger.append_in_session(
            session, SecurityEvent, kind="FILTER_SHADOW", detail=checked.model_dump(mode="json")
        )
