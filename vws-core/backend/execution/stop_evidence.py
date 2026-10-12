"""EX-05: ledger-backed protective levels; no order capability or source writes."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionOrderRecord, SecurityEvent
from backend.core.errors import LedgerIntegrityError
from backend.execution.exit_variants import StopMoved, StopRaiseApproval


def stop_approvals(
    session: Session, entry: ExecutionOrderRecord, before_seq: int | None = None
) -> tuple[StopRaiseApproval, ...]:
    query = select(SecurityEvent).where(
        SecurityEvent.kind == "STOP_RAISE_APPROVAL",
        SecurityEvent.detail["entry_id"].as_string() == str(entry.id),
    )
    if before_seq is not None:
        query = query.where(SecurityEvent.seq < before_seq)
    rows = tuple(session.scalars(query.order_by(SecurityEvent.seq).limit(1001)))
    if len(rows) > 1000:
        raise LedgerIntegrityError("EX-05: stop approval history exceeds its bound")
    return tuple(StopRaiseApproval.recorded(row.detail) for row in rows)


def moved_stops(
    session: Session, entry: ExecutionOrderRecord, before_seq: int | None = None
) -> tuple[StopMoved, ...]:
    query = select(SecurityEvent).where(
        SecurityEvent.kind == "STOP_MOVED",
        SecurityEvent.detail["approval"]["entry_id"].as_string() == str(entry.id),
    )
    if before_seq is not None:
        query = query.where(SecurityEvent.seq < before_seq)
    rows = tuple(session.scalars(query.order_by(SecurityEvent.seq).limit(1001)))
    if len(rows) > 1000:
        raise LedgerIntegrityError("EX-05: stop movement history exceeds its bound")
    return tuple(StopMoved.recorded(row.detail) for row in rows)


def current_stop(
    session: Session, entry: ExecutionOrderRecord, before_seq: int | None = None
) -> Decimal:
    if entry.stop_price is None:
        raise LedgerIntegrityError("EX-05: managed entry has no initial stop")
    level: Decimal = entry.stop_price
    for move in moved_stops(session, entry, before_seq):
        if (move.approval.account_id, move.approval.environment, move.approval.symbol) != (
            entry.account_id,
            entry.environment,
            entry.symbol,
        ) or move.approval.old_stop != level:
            raise LedgerIntegrityError(
                "EX-05: stop movement changed account, symbol or lowered coverage"
            )
        if move.confirmed_stop is not None:
            level = move.confirmed_stop
    return level


def authorized_stop(
    session: Session, entry: ExecutionOrderRecord, record: ExecutionOrderRecord
) -> bool:
    level = current_stop(session, entry, record.seq)
    if record.stop_price == level:
        return True
    if record.role == "STOP":
        root = child_root(session, entry, record.client_order_id, record.seq)
        if root is not None and root.role == "REPAIR" and root.stop_price == record.stop_price:
            return authorized_stop(session, entry, root)
    return any(
        plan.new_stop == record.stop_price
        and record.client_order_id
        in {"vws-m-" + plan.raise_id.hex, "vws-m-" + plan.raise_id.hex + "-r"}
        and plan.qty == record.qty
        and (plan.account_id, plan.environment, plan.symbol)
        == (entry.account_id, entry.environment, entry.symbol)
        for plan in stop_approvals(session, entry, record.seq)
    )


def child_root(
    session: Session, entry: ExecutionOrderRecord, client_order_id: str, before_seq: int
) -> ExecutionOrderRecord | None:
    from backend.execution.storage import bindings

    proved = bindings(session, before_seq=before_seq)
    roots = (entry,) + tuple(
        session.scalars(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.parent_execution_id == entry.id,
                ExecutionOrderRecord.role == "REPAIR",
                ExecutionOrderRecord.order_type == "LIMIT",
                ExecutionOrderRecord.seq < before_seq,
            )
        )
    )
    matching = tuple(
        row
        for row in roots
        if (broker := proved.get(row.id)) is not None
        and any(child.client_order_id == client_order_id for child in broker.legs)
    )
    if len(matching) > 1:
        raise LedgerIntegrityError("EX-05: stop child has multiple broker parents")
    return None if not matching else matching[0]


def validate_stop_event(session: Session, record: SecurityEvent) -> None:
    """Admission and chain verification use the same immutable identity checks."""
    from backend.execution.models import BindingEvidence
    from backend.execution.storage import held_quantity

    if record.kind == "STOP_RAISE_APPROVAL":
        plan = StopRaiseApproval.recorded(record.detail)
    else:
        move = StopMoved.recorded(record.detail)
        plan = move.approval
    entry = session.get(ExecutionOrderRecord, plan.entry_id)
    if (
        entry is None
        or entry.role != "ENTRY"
        or entry.seq >= record.seq
        or (entry.account_id, entry.environment, entry.symbol)
        != (plan.account_id, plan.environment, plan.symbol)
        or plan.old_stop != current_stop(session, entry, record.seq)
        or plan.checked_at > record.created_at
    ):
        raise LedgerIntegrityError("EX-05: stop evidence is not bound to its proved held entry")
    approvals = stop_approvals(session, entry, record.seq)
    if record.kind == "STOP_RAISE_APPROVAL":
        if plan.qty != held_quantity(session, entry.id, before_seq=record.seq) or any(
            item.raise_id == plan.raise_id or item.session == plan.session for item in approvals
        ):
            raise LedgerIntegrityError("EX-05: one bounded daily stop authorization required")
        return
    if (
        tuple(item for item in approvals if item.raise_id == plan.raise_id) != (plan,)
        or any(
            item.approval.raise_id == plan.raise_id
            for item in moved_stops(session, entry, record.seq)
        )
        or move.completed_at > record.created_at
    ):
        raise LedgerIntegrityError("EX-05: stop movement lacks one unused exact authorization")
    if move.confirmed_stop is None:
        return
    observations = tuple(
        BindingEvidence.model_validate(row.detail)
        for row in session.scalars(
            select(SecurityEvent).where(
                SecurityEvent.kind == "EXECUTION_ORDER_OBSERVED", SecurityEvent.seq < record.seq
            )
        )
    )
    latest = {item.execution_order_id: item.broker_order for item in observations}
    children = tuple(
        session.scalars(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.parent_execution_id == entry.id,
                ExecutionOrderRecord.seq < record.seq,
            )
        )
    )
    covered = sum(
        broker.qty - broker.filled_qty
        for child in children
        if (broker := latest.get(child.id)) is not None
        and broker.order_type == "stop"
        and broker.is_open
        and broker.status not in {"held", "suspended", "pending_cancel"}
        and broker.stop_price == move.confirmed_stop
    )
    if covered != plan.qty or held_quantity(session, entry.id, before_seq=record.seq) != plan.qty:
        raise LedgerIntegrityError("EX-05: stop movement claims unconfirmed or oversized coverage")
