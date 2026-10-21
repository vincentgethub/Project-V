"""AX-16/26/31: immutable execution identities, truthful fills and reconciliation.

No SDK or executor import. MANUAL ledger verification can validate these rows.
Broker-generated bracket children are proved by the persisted nested parent;
unbound non-vws orders remain reconciliation faults.
"""

from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.database import (
    Alert,
    AlertEvent,
    ApprovalEvent,
    ExecutionFillRecord,
    ExecutionOrderRecord,
    Fill,
    LedgerRecord,
    Order,
    OrderEvent,
    ResearchReport,
    SecurityEvent,
)
from backend.core.errors import LedgerIntegrityError
from backend.execution.models import (
    BindingEvidence,
    BrokerOrder,
    EntryApprovalEvidence,
    ExitApprovalEvidence,
    ExitCycleEvidence,
    SubmitOutcome,
)
from backend.execution.stop_evidence import authorized_stop, child_root, validate_stop_event

if TYPE_CHECKING:
    from backend.core.ledger import Ledger


def approval_evidence(
    session: Session, proposal_id: UUID, before_seq: int
) -> EntryApprovalEvidence | None:
    for row in session.scalars(
        select(SecurityEvent)
        .where(SecurityEvent.kind == "AUTO_ENTRY_APPROVAL", SecurityEvent.seq < before_seq)
        .order_by(SecurityEvent.seq.desc())
    ):
        evidence = EntryApprovalEvidence.model_validate(row.detail)
        if evidence.proposal_id == proposal_id:
            return evidence
    return None


def bindings(session: Session, *, before_seq: int | None = None) -> dict[UUID, BrokerOrder]:
    query = select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_ORDER_OBSERVED")
    if before_seq is not None:
        query = query.where(SecurityEvent.seq < before_seq)
    result: dict[UUID, BrokerOrder] = {}
    for row in session.scalars(query.order_by(SecurityEvent.seq)):
        checked = BindingEvidence.model_validate(row.detail)
        result[checked.execution_order_id] = checked.broker_order
    return result


def exit_cycles(
    session: Session, *, before_seq: int | None = None
) -> tuple[ExitCycleEvidence, ...]:
    query = select(SecurityEvent).where(SecurityEvent.kind == "AUTO_EXIT_CYCLE")
    if before_seq is not None:
        query = query.where(SecurityEvent.seq < before_seq)
    return tuple(
        ExitCycleEvidence.model_validate(row.detail)
        for row in session.scalars(query.order_by(SecurityEvent.seq))
    )


def exit_approvals(
    session: Session, *, before_seq: int | None = None
) -> tuple[ExitApprovalEvidence, ...]:
    query = select(SecurityEvent).where(SecurityEvent.kind == "AUTO_EXIT_APPROVAL")
    if before_seq is not None:
        query = query.where(SecurityEvent.seq < before_seq)
    return tuple(
        ExitApprovalEvidence.model_validate(row.detail)
        for row in session.scalars(query.order_by(SecurityEvent.seq))
    )


def entry_quantity(session: Session, order_id: UUID) -> int | None:
    rows = tuple(
        session.scalars(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.order_id == order_id,
                ExecutionOrderRecord.role == "ENTRY",
            )
        )
    )
    return None if not rows else sum(row.qty for row in rows)


def filled_quantity(session: Session, execution_id: UUID, *, before_seq: int | None = None) -> int:
    query = select(ExecutionFillRecord).where(
        ExecutionFillRecord.execution_order_id == execution_id
    )
    if before_seq is not None:
        query = query.where(ExecutionFillRecord.seq < before_seq)
    return sum(row.qty for row in session.scalars(query))


def held_quantity(session: Session, entry_id: UUID, *, before_seq: int | None = None) -> int:
    bought = filled_quantity(session, entry_id, before_seq=before_seq)
    children = session.scalars(
        select(ExecutionOrderRecord).where(
            ExecutionOrderRecord.parent_execution_id == entry_id,
        )
    )
    return bought - sum(filled_quantity(session, row.id, before_seq=before_seq) for row in children)


def entry_filled_quantity(session: Session, order_id: UUID) -> int:
    return sum(
        filled_quantity(session, row.id)
        for row in session.scalars(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.order_id == order_id, ExecutionOrderRecord.role == "ENTRY"
            )
        )
    )


def finalize_shared_order(
    ledger: "Ledger", session: Session, order_id: UUID, *, reason: str
) -> str | None:
    """EX-01/SEC-73: terminal state requires every entry leg and matching fills."""
    latest = session.scalar(
        select(OrderEvent)
        .where(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.seq.desc())
        .limit(1)
    )
    if latest is None:
        raise LedgerIntegrityError("Shared order has no lifecycle")
    if latest.state in {"FILLED", "CANCELED", "REJECTED"}:
        return latest.state
    legs = tuple(
        session.scalars(
            select(ExecutionOrderRecord)
            .where(ExecutionOrderRecord.order_id == order_id, ExecutionOrderRecord.role == "ENTRY")
            .order_by(ExecutionOrderRecord.seq)
        )
    )
    if not legs:
        return None
    proved = bindings(session)
    outcomes = {}
    for row in session.scalars(
        select(SecurityEvent)
        .where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
        .order_by(SecurityEvent.seq)
    ):
        evidence = SubmitOutcome.model_validate(row.detail)
        outcomes[evidence.execution_order_id] = evidence.outcome
    statuses = []
    for leg in legs:
        quantity = filled_quantity(session, leg.id)
        broker = proved.get(leg.id)
        if broker is None:
            outcome = outcomes.get(leg.id)
            if quantity or outcome not in {"NOT_SENT", "REJECTED"}:
                return None
            statuses.append("rejected" if outcome == "REJECTED" else "not_sent")
        else:
            if (
                broker.status not in {"filled", "canceled", "expired", "rejected"}
                or broker.filled_qty != quantity
            ):
                return None
            statuses.append(broker.status)
    total = sum(filled_quantity(session, leg.id) for leg in legs)
    if total == sum(leg.qty for leg in legs):
        state = "FILLED"
    elif (
        not total
        and all(status == "rejected" for status in statuses)
        and latest.state != "CANCEL_REQUESTED"
    ):
        state = "REJECTED"
    else:
        state = "CANCELED"
    if len(legs) == 2 and all(status == "rejected" for status in statuses):
        if state == "CANCELED":
            reason += "; canceled"
        reason += "; both legs broker-rejected"
    ledger.append_in_session(
        session, OrderEvent, order_id=order_id, state=state, reason=reason, broker_order_id=None
    )
    return state


def validate_record(session: Session, record: LedgerRecord) -> None:
    if isinstance(record, ExecutionOrderRecord):
        original = session.get(Order, record.order_id)
        if (
            original is None
            or original.side != "BUY"
            or record.qty > original.qty
            or record.account_id != original.account_id
            or record.symbol != original.symbol
            or record.qty <= 0
            or record.environment not in {"PAPER", "LIVE"}
            or record.role not in {"ENTRY", "TARGET", "STOP", "EXIT", "REPAIR"}
        ):
            raise LedgerIntegrityError(
                "Execution instruction differs from its approved long proposal"
            )
        parent = (
            None
            if record.parent_execution_id is None
            else session.get(ExecutionOrderRecord, record.parent_execution_id)
        )
        if record.role == "ENTRY":
            evidence = approval_evidence(session, original.proposal_id, record.seq)
            latest = session.scalar(
                select(OrderEvent)
                .where(
                    OrderEvent.order_id == original.id,
                    OrderEvent.seq < record.seq,
                )
                .order_by(OrderEvent.seq.desc())
                .limit(1)
            )
            priors = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.order_id == original.id,
                        ExecutionOrderRecord.role == "ENTRY",
                        ExecutionOrderRecord.seq < record.seq,
                    )
                )
            )
            split = evidence is not None and evidence.exit_variant in {"SPLIT_1R", "SPLIT_1R_TRAIL"}
            base_id = "vws-" + original.proposal_id.hex
            expected_id, expected_qty, expected_target = (
                base_id,
                None if evidence is None else evidence.qty,
                original.target_price,
            )
            if split and evidence is not None:
                leg_a = record.client_order_id == base_id + "-a"
                expected_id = base_id + ("-a" if leg_a else "-b")
                expected_qty = evidence.qty // 2 if leg_a else evidence.qty - evidence.qty // 2
                if original.stop_price is None:
                    raise LedgerIntegrityError("EX-01: split proposal has no stop")
                expected_target = (
                    original.limit_price + (original.limit_price - original.stop_price)
                    if leg_a
                    else (
                        None if evidence.exit_variant == "SPLIT_1R_TRAIL" else original.target_price
                    )
                )
                if (
                    evidence.qty < 2
                    or (leg_a and priors)
                    or (
                        not leg_a
                        and (len(priors) != 1 or priors[0].client_order_id != base_id + "-a")
                    )
                ):
                    raise LedgerIntegrityError("EX-01: exactly one A followed by one B required")
            if (
                parent is not None
                or record.parent_execution_id is not None
                or (not split and bool(priors))
                or latest is None
                or latest.state != "APPROVED"
                or record.side != "BUY"
                or record.client_order_id != expected_id
                or record.order_type != "LIMIT"
                or record.limit_price != original.limit_price
                or record.stop_price != original.stop_price
                or record.target_price != expected_target
                or (
                    record.target_price is None
                    and not (
                        split
                        and evidence is not None
                        and evidence.exit_variant == "SPLIT_1R_TRAIL"
                        and record.client_order_id.endswith("-b")
                    )
                )
                or record.time_in_force != "GTC"
                or record.valid_until is None
                or record.valid_until <= record.created_at
                or evidence is None
                or expected_qty != record.qty
                or evidence.account_id != record.account_id
                or evidence.environment != record.environment
                or evidence.config_hash != record.config_hash
            ):
                raise LedgerIntegrityError("Entry intent lacks one exact approved bracket")
        else:
            if (
                parent is None
                or parent.role != "ENTRY"
                or parent.order_id != record.order_id
                or parent.seq >= record.seq
                or parent.qty < record.qty
                or parent.environment != record.environment
                or parent.account_id != record.account_id
                or record.side != "SELL"
                or record.valid_until is not None
            ):
                raise LedgerIntegrityError("Exit or stop is not bound to a managed entry")
            if record.role in {"STOP", "REPAIR"}:
                oco = record.role == "REPAIR" and record.order_type == "LIMIT"
                if (
                    (record.order_type != "STOP" and not oco)
                    or not authorized_stop(session, parent, record)
                    or (not oco and record.limit_price is not None)
                    or (
                        oco
                        and (
                            parent.target_price is None
                            or record.limit_price != parent.target_price
                            or record.target_price != parent.target_price
                        )
                    )
                    or record.time_in_force != "GTC"
                ):
                    raise LedgerIntegrityError(
                        "Protective stop differs from recorded stop coverage"
                    )
            elif record.order_type != "LIMIT" or record.limit_price is None:
                raise LedgerIntegrityError("Non-stop exit must be an exact limit")
            if record.role == "TARGET" and (
                record.limit_price != parent.target_price or record.time_in_force != "GTC"
            ):
                raise LedgerIntegrityError("Target differs from recorded broker bracket")
            if record.role in {"STOP", "TARGET"}:
                root = child_root(session, parent, record.client_order_id, record.seq)
                proved = (
                    None if root is None else bindings(session, before_seq=record.seq).get(root.id)
                )
                if proved is None or not any(
                    leg.client_order_id == record.client_order_id for leg in proved.legs
                ):
                    raise LedgerIntegrityError(
                        "Generated child is absent from its persisted nested parent"
                    )
            else:
                if not record.client_order_id.startswith("vws-") or record.qty > held_quantity(
                    session, parent.id, before_seq=record.seq
                ):
                    raise LedgerIntegrityError("Exit or repair would oversell managed held shares")
                if record.role == "EXIT" and record.time_in_force != "DAY":
                    raise LedgerIntegrityError("Automated exit must be a DAY limit")
                if record.role == "EXIT":
                    authorizations = tuple(
                        row
                        for row in exit_approvals(session, before_seq=record.seq)
                        if row.client_order_id == record.client_order_id
                    )
                    if len(authorizations) != 1:
                        raise LedgerIntegrityError(
                            "Exit lacks one exact fixed-reason authorization"
                        )
                    evidence_exit = authorizations[0]
                    if (
                        evidence_exit.entry_id != parent.id
                        or evidence_exit.account_id != record.account_id
                        or evidence_exit.environment != record.environment
                        or evidence_exit.config_hash != record.config_hash
                        or evidence_exit.qty != record.qty
                        or evidence_exit.limit_price != record.limit_price
                        or record.stop_price is not None
                        or record.target_price is not None
                    ):
                        raise LedgerIntegrityError(
                            "Exit instruction differs from fixed-reason authorization"
                        )
    elif isinstance(record, SecurityEvent) and record.kind == "PAPER_CANCEL_SEMANTICS":
        from backend.execution.stop_readiness import CancelSemanticsProof, verify_cancel_semantics

        proof = CancelSemanticsProof.recorded(record.detail)
        if proof.observed_at != ensure_utc(record.ts) or proof.observed_at > record.created_at:
            raise LedgerIntegrityError(
                "EX-06: cancellation integration evidence is future or misdated"
            )
        verify_cancel_semantics(session, proof, before_seq=record.seq)
    elif isinstance(record, SecurityEvent) and record.kind in {"STOP_RAISE_APPROVAL", "STOP_MOVED"}:
        validate_stop_event(session, record)
    elif isinstance(record, ExecutionFillRecord):
        intent = session.get(ExecutionOrderRecord, record.execution_order_id)
        proved = bindings(session, before_seq=record.seq).get(record.execution_order_id)
        if intent is not None and intent.role == "ENTRY":
            latest = session.scalar(
                select(OrderEvent)
                .where(OrderEvent.order_id == intent.order_id, OrderEvent.seq < record.seq)
                .order_by(OrderEvent.seq.desc())
                .limit(1)
            )
            if latest is None or latest.state not in {
                "SUBMITTED",
                "PARTIALLY_FILLED",
                "CANCEL_REQUESTED",
            }:
                raise LedgerIntegrityError("Invalid appended order lifecycle transition")
        if (
            intent is None
            or proved is None
            or intent.seq >= record.seq
            or record.qty <= 0
            or record.filled_at > record.created_at
            or record.filled_at < intent.created_at
            or filled_quantity(session, intent.id, before_seq=record.seq) + record.qty > intent.qty
            or session.scalar(select(Fill).where(Fill.broker_fill_id == record.broker_fill_id))
            is not None
        ):
            raise LedgerIntegrityError("Execution fill identity, time or quantity is unverifiable")
        if (
            intent.order_type == "LIMIT"
            and intent.limit_price is not None
            and (
                (intent.side == "BUY" and record.price > intent.limit_price)
                or (intent.side == "SELL" and record.price < intent.limit_price)
            )
        ):
            raise LedgerIntegrityError("Execution fill violates its recorded LIMIT")
        if intent.side == "SELL" and (
            intent.parent_execution_id is None
            or record.qty
            > held_quantity(session, intent.parent_execution_id, before_seq=record.seq)
        ):
            raise LedgerIntegrityError("Execution sell exceeds managed held shares")
    elif isinstance(record, SecurityEvent) and record.kind == "AUTO_EXIT_CYCLE":
        cycle = ExitCycleEvidence.model_validate(record.detail)
        entry = session.get(ExecutionOrderRecord, cycle.entry_id)
        prior_cycles = tuple(
            row
            for row in exit_cycles(session, before_seq=record.seq)
            if row.cycle_id == cycle.cycle_id
        )
        if (
            entry is None
            or entry.role != "ENTRY"
            or entry.seq >= record.seq
            or entry.account_id != cycle.account_id
            or entry.environment != cycle.environment
            or cycle.session_date > record.ts.astimezone(ZoneInfo("America/New_York")).date()
        ):
            raise LedgerIntegrityError("Exit cycle is not bound to this managed entry and session")
        if cycle.state == "ACTIVE":
            if prior_cycles or held_quantity(session, cycle.entry_id, before_seq=record.seq) <= 0:
                raise LedgerIntegrityError("Exit cycle requires unconsumed held shares")
        elif (
            len(prior_cycles) != 1
            or prior_cycles[0].state != "ACTIVE"
            or prior_cycles[0].model_dump(exclude={"state"}) != cycle.model_dump(exclude={"state"})
        ):
            raise LedgerIntegrityError("Exit cycle has no matching active predecessor")
        if (
            cycle.state == "DONE"
            and held_quantity(session, cycle.entry_id, before_seq=record.seq) != 0
        ):
            raise LedgerIntegrityError("Completed exit still has managed held shares")
    elif isinstance(record, SecurityEvent) and record.kind == "AUTO_EXIT_APPROVAL":
        evidence_exit = ExitApprovalEvidence.model_validate(record.detail)
        cycles = tuple(
            row
            for row in exit_cycles(session, before_seq=record.seq)
            if row.cycle_id == evidence_exit.cycle_id
        )
        entry = session.get(ExecutionOrderRecord, evidence_exit.entry_id)
        previous_approvals = tuple(
            row
            for row in exit_approvals(session, before_seq=record.seq)
            if row.cycle_id == evidence_exit.cycle_id
        )
        if (
            entry is None
            or entry.role != "ENTRY"
            or entry.seq >= record.seq
            or len(cycles) != 1
            or cycles[0].state != "ACTIVE"
            or cycles[0].entry_id != entry.id
            or entry.account_id != evidence_exit.account_id
            or entry.environment != evidence_exit.environment
            or cycles[0].config_hash != evidence_exit.config_hash
            or evidence_exit.attempt != len(previous_approvals) + 1
            or evidence_exit.qty > held_quantity(session, entry.id, before_seq=record.seq)
            or not entry.created_at
            <= evidence_exit.quote_at
            <= evidence_exit.checked_at
            <= record.created_at
            or any(
                row.client_order_id == evidence_exit.client_order_id
                for row in exit_approvals(session, before_seq=record.seq)
            )
        ):
            raise LedgerIntegrityError("Exit approval lacks a fresh, bounded, managed exit cycle")
    elif isinstance(record, SecurityEvent) and record.kind == "AUTO_ENTRY_APPROVAL":
        evidence = EntryApprovalEvidence.model_validate(record.detail)
        original = session.scalar(select(Order).where(Order.proposal_id == evidence.proposal_id))
        alert = session.get(Alert, evidence.alert_id)
        delivery = session.scalar(
            select(AlertEvent)
            .where(AlertEvent.alert_id == evidence.alert_id, AlertEvent.seq < record.seq)
            .order_by(AlertEvent.seq.desc())
            .limit(1)
        )
        desk = session.scalar(
            select(ResearchReport).where(
                ResearchReport.alert_id == evidence.alert_id,
                ResearchReport.agent_name == "desk_policy",
                ResearchReport.seq < record.seq,
            )
        )
        if (
            original is None
            or alert is None
            or original.seq >= record.seq
            or alert.seq >= record.seq
            or evidence.proposal_id != alert.proposal_id
            or evidence.account_id != original.account_id
            or original.side != "BUY"
            or original.intent != "ENTRY"
            or evidence.qty > original.qty
            or evidence.config_hash != alert.config_hash
            or delivery is None
            or delivery.state != "SENT"
            or desk is None
            or desk.status != "OK"
            or desk.payload != {"yaml_hash": evidence.yaml_hash}
            or not original.created_at
            <= evidence.checked_at
            <= record.created_at
            < alert.expires_at
            or approval_evidence(session, evidence.proposal_id, record.seq) is not None
            or session.scalar(
                select(ApprovalEvent).where(
                    ApprovalEvent.alert_id == alert.id, ApprovalEvent.seq < record.seq
                )
            )
            is not None
            or session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.order_id == original.id,
                    ExecutionOrderRecord.seq < record.seq,
                )
            )
            is not None
        ):
            raise LedgerIntegrityError(
                "Auto approval lacks fresh, delivered, single-use research evidence"
            )
    elif isinstance(record, SecurityEvent) and record.kind == "EXECUTION_SUBMIT_OUTCOME":
        evidence_outcome = SubmitOutcome.model_validate(record.detail)
        instruction = session.get(ExecutionOrderRecord, evidence_outcome.execution_order_id)
        if (
            instruction is None
            or instruction.seq >= record.seq
            or instruction.account_id != evidence_outcome.account_id
            or instruction.environment != evidence_outcome.environment
            or (evidence_outcome.outcome == "ACCEPTED") != (evidence_outcome.error_type == "NONE")
        ):
            raise LedgerIntegrityError("Order outcome is not bound to a durable account intent")
    elif isinstance(record, SecurityEvent) and record.kind == "EXECUTION_ORDER_OBSERVED":
        checked = BindingEvidence.model_validate(record.detail)
        intent = session.get(ExecutionOrderRecord, checked.execution_order_id)
        broker = checked.broker_order
        if (
            intent is None
            or intent.seq >= record.seq
            or checked.observed_at != ensure_utc(record.ts)
            or checked.observed_at > record.created_at
            or broker.submitted_at > checked.observed_at
            or (broker.rejected_at is not None and broker.rejected_at > checked.observed_at)
            or broker.client_order_id != intent.client_order_id
            or broker.qty > intent.qty
            or broker.symbol != intent.symbol
            or broker.side.upper() != intent.side
            or broker.order_type.upper() != intent.order_type
            or broker.time_in_force.upper() != intent.time_in_force
            or broker.limit_price != intent.limit_price
            or broker.stop_price != (intent.stop_price if intent.order_type == "STOP" else None)
        ):
            raise LedgerIntegrityError("Broker order differs from persisted exact intent")
        prior_bindings = bindings(session, before_seq=record.seq)
        if broker.qty != intent.qty and (
            intent.role not in {"STOP", "TARGET"}
            or intent.parent_execution_id is None
            or broker.qty - broker.filled_qty
            != held_quantity(session, intent.parent_execution_id, before_seq=record.seq)
        ):
            raise LedgerIntegrityError(
                "Broker resized an order without matching recorded held shares"
            )
        expected_class = "oto" if intent.target_price is None else "bracket"
        if intent.role == "ENTRY" and (
            broker.order_class != expected_class
            or any(
                (leg.order_type == "stop" and leg.stop_price != intent.stop_price)
                or (leg.order_type == "limit" and leg.limit_price != intent.target_price)
                for leg in broker.legs
            )
        ):
            raise LedgerIntegrityError("Broker bracket differs from the approved protective levels")
        if (
            intent.role == "REPAIR"
            and intent.order_type == "LIMIT"
            and (
                broker.order_class != "oco"
                or len(broker.legs) != 1
                or broker.legs[0].order_type != "stop"
                or broker.legs[0].stop_price != intent.stop_price
            )
        ):
            raise LedgerIntegrityError("EX-05: OCO differs from exact protected exit intent")
        old = prior_bindings.get(intent.id)
        if old is not None and (
            old.order_id != broker.order_id
            or broker.qty > old.qty
            or old.filled_qty > broker.filled_qty
            or (not old.is_open and old.status != broker.status)
        ):
            raise LedgerIntegrityError("Broker order identity or lifecycle moved backwards")
        if any(
            row.order_id == broker.order_id
            for key, row in prior_bindings.items()
            if key != intent.id
        ):
            raise LedgerIntegrityError("One broker order is bound to multiple intents")
        if intent.role in {"STOP", "TARGET"}:
            held_entry = session.get(ExecutionOrderRecord, intent.parent_execution_id)
            root = (
                None
                if held_entry is None
                else child_root(session, held_entry, intent.client_order_id, record.seq)
            )
            proved_parent = prior_bindings.get(root.id) if root is not None else None
            if proved_parent is None or not any(
                leg.order_id == broker.order_id
                and leg.client_order_id == broker.client_order_id
                and broker.parent_id == proved_parent.order_id
                for leg in proved_parent.legs
            ):
                raise LedgerIntegrityError("Child broker identity is not proved by its bracket")
