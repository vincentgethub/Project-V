"""EX-06: read-only paper raise and pinned cancellation evidence for live admission."""

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import YamlConfig
from backend.core.database import ExecutionOrderRecord, SecurityEvent
from backend.core.errors import LedgerIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import Digest
from backend.domain.models import FrozenModel, UTCDateTime
from backend.execution.exit_variants import StopMoved
from backend.execution.models import BrokerOrder, payload_instant
from backend.execution.storage import bindings


class CancelSemanticsProof(FrozenModel):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Literal["PAPER"] = "PAPER"
    yaml_hash: Digest
    config_hash: Digest
    sdk_version: Literal["0.44.0"] = "0.44.0"
    oto_entry_id: UUID
    oto_stop_id: UUID
    oco_exit_id: UUID
    oco_stop_id: UUID
    observed_at: UTCDateTime

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "CancelSemanticsProof":
        return cls.model_validate(
            {**payload, "observed_at": payload_instant(payload["observed_at"])}
        )


def verify_cancel_semantics(
    session: Session, proof: CancelSemanticsProof, *, before_seq: int
) -> None:
    checked = CancelSemanticsProof.model_validate(proof)
    ids = (checked.oto_entry_id, checked.oto_stop_id, checked.oco_exit_id, checked.oco_stop_id)
    if len(set(ids)) != 4:
        raise LedgerIntegrityError("EX-06: four distinct paper order identities required")
    records = tuple(session.get(ExecutionOrderRecord, key) for key in ids)
    if any(
        row is None
        or row.seq >= before_seq
        or row.account_id != checked.account_id
        or row.environment != "PAPER"
        or row.config_hash != checked.config_hash
        for row in records
    ):
        raise LedgerIntegrityError(
            "EX-06: cancellation proof is not bound to recorded paper orders"
        )
    oto, oto_stop, oco, oco_stop = (cast(ExecutionOrderRecord, row) for row in records)
    proved = bindings(session, before_seq=before_seq)
    orders = tuple(proved.get(key) for key in ids)
    if any(row is None or row.submitted_at > checked.observed_at for row in orders):
        raise LedgerIntegrityError("EX-06: cancellation proof lacks broker observations")
    parent, stop, target, paired_stop = (cast(BrokerOrder, row) for row in orders)
    if (
        oto.role != "ENTRY"
        or oto.target_price is not None
        or parent.order_class != "oto"
        or parent.status not in {"filled", "canceled"}
        or oto_stop.role != "STOP"
        or oto_stop.parent_execution_id != oto.id
        or stop.status != "canceled"
        or stop.parent_id != parent.order_id
        or oco.role != "REPAIR"
        or oco.order_type != "LIMIT"
        or oco.target_price is None
        or target.order_class != "oco"
        or target.status != "canceled"
        or oco_stop.role != "STOP"
        or oco_stop.parent_execution_id != oco.parent_execution_id
        or paired_stop.status != "canceled"
        or paired_stop.parent_id != target.order_id
    ):
        raise LedgerIntegrityError(
            "EX-06: OTO stop and both OCO exits must show confirmed cancellation"
        )


def raise_history_reasons(
    moves: tuple[StopMoved, ...],
    proofs: tuple[CancelSemanticsProof, ...],
    *,
    yaml_hash: str,
    now: datetime,
) -> tuple[str, ...]:
    instant = ensure_utc(now)
    if (
        not isinstance(moves, tuple)
        or len(moves) > 100000
        or not isinstance(proofs, tuple)
        or len(proofs) > 1000
    ):
        raise LedgerIntegrityError("EX-06: bounded immutable paper evidence required")
    moves = tuple(StopMoved.model_validate(row) for row in moves)
    proofs = tuple(CancelSemanticsProof.model_validate(row) for row in proofs)
    if len({row.approval.raise_id for row in moves}) != len(moves):
        raise LedgerIntegrityError("EX-06: repeated raises cannot multiply paper evidence")
    scoped = tuple(
        StopMoved.model_validate(row)
        for row in moves
        if row.approval.environment == "PAPER" and row.approval.yaml_hash == yaml_hash
    )
    accounts = {row.approval.account_id for row in scoped}
    qualified = tuple(
        account
        for account in accounts
        if sum(row.status == "APPLIED" for row in scoped if row.approval.account_id == account)
        >= 30
    )
    if len(qualified) != 1:
        return ("EX-06: one verified AUTO_PAPER account needs at least 30 successful stop raises",)
    account = qualified[0]
    relevant = tuple(row for row in scoped if row.approval.account_id == account)
    reasons = []
    hashes = {row.approval.config_hash for row in relevant}
    if len(hashes) != 1 or any(
        row.completed_at > instant or row.status != "APPLIED" or row.window_ms > 30000
        for row in relevant
    ):
        reasons.append(
            "EX-06: paper raises require one configuration, zero failures and no window over 30 seconds"
        )
    if not any(
        row.account_id == account
        and row.yaml_hash == yaml_hash
        and row.config_hash in hashes
        and row.observed_at <= instant
        for row in proofs
    ):
        reasons.append(
            "EX-06: pinned paper integration must prove OTO stop and OCO sibling cancellation"
        )
    return tuple(reasons)


def live_raise_reasons(ledger: Ledger, config: YamlConfig) -> tuple[str, ...]:
    if config.exits.variant != "SPLIT_1R_TRAIL":
        return ()
    try:
        ledger.verify_chain()
        with Session(ledger.engine) as session:
            records = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind.in_(("STOP_MOVED", "PAPER_CANCEL_SEMANTICS")))
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
            if len(records) > 100000:
                raise LedgerIntegrityError("EX-06: paper evidence exceeds its bound")
            moves = tuple(
                StopMoved.recorded(row.detail) for row in records if row.kind == "STOP_MOVED"
            )
            proofs = tuple(
                CancelSemanticsProof.recorded(row.detail)
                for row in records
                if row.kind == "PAPER_CANCEL_SEMANTICS"
            )
            for row in records:
                if row.kind == "PAPER_CANCEL_SEMANTICS":
                    proof = CancelSemanticsProof.recorded(row.detail)
                    verify_cancel_semantics(session, proof, before_seq=row.seq)
                    if (
                        proof.observed_at != ensure_utc(row.ts)
                        or proof.observed_at > row.created_at
                    ):
                        raise LedgerIntegrityError(
                            "EX-06: paper cancellation proof is future or misdated"
                        )
        return raise_history_reasons(
            moves, proofs, yaml_hash=config.config_hash, now=ledger.clock.now()
        )
    except Exception:
        return ("EX-06: paper stop-raise and OCO/OTO integration evidence is UNVERIFIED",)
