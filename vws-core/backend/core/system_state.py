"""R-02/R-09: durable latching state; only audited operator reset can lower it."""

from __future__ import annotations

from decimal import Decimal, localcontext
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import Clock
from backend.core.config import Settings
from backend.core.database import SystemControl, SystemEvent, transaction
from backend.core.errors import (
    DataIntegrityError,
    LedgerIntegrityError,
    SafetyError,
    StateTransitionError,
)
from backend.core.ledger import Ledger
from backend.core.money import decimal_money
from backend.core.notifier import DeduplicatingNotifier, Notifier


class SystemState(StrEnum):
    """CRO-01 ordered operating modes; lowering a mode requires an operator."""

    RUNNING = "RUNNING"
    REDUCE_ONLY = "REDUCE_ONLY"
    HALTED = "HALTED"


_RANK = {SystemState.RUNNING: 0, SystemState.REDUCE_ONLY: 1, SystemState.HALTED: 2}


def state_allows(state: SystemState, intent: str, source: str) -> bool:
    """CRO-01/R-09: HALTED permits only explicitly manual reductions/exits."""
    if (
        not isinstance(state, SystemState)
        or not isinstance(intent, str)
        or not isinstance(source, str)
    ):
        return False
    if intent not in {"ENTRY", "ADD", "REDUCE", "EXIT"}:
        return False
    if source not in {"SIGNAL", "SYSTEM", "MANUAL"}:
        return False
    if state == SystemState.HALTED:
        return source == "MANUAL" and intent in {"REDUCE", "EXIT"}
    if state == SystemState.REDUCE_ONLY:
        return intent in {"REDUCE", "EXIT"}
    return state == SystemState.RUNNING


def financial_state(
    equity: Decimal,
    high_water_mark: Decimal,
    day_start_equity: Decimal,
    config: Settings,
) -> SystemState:
    """CRO-09 pure latched tiers; CRO-10 is a session-scoped entry rule.

    Daily baseline integrity remains mandatory, but an ordinary daily loss does
    not change persisted operating state. Only drawdown tiers latch here.
    """
    for value in (equity, high_water_mark, day_start_equity):
        if not isinstance(value, Decimal):
            raise DataIntegrityError("CRO-09/CRO-10: financial state requires exact Decimal values")
        decimal_money(value)
    if not isinstance(config, Settings):
        raise DataIntegrityError("CRO-09/CRO-10: financial state requires validated settings")
    if equity <= 0 or high_water_mark <= 0 or day_start_equity <= 0:
        return SystemState.HALTED
    values = (
        equity,
        high_water_mark,
        day_start_equity,
        config.dd_halt,
        config.dd_reduce_only,
    )
    with localcontext() as context:
        context.prec = 80 + sum(len(value.as_tuple().digits) for value in values)
        loss_from_high = max(Decimal(0), high_water_mark - equity)
        if loss_from_high >= config.dd_halt * high_water_mark:
            return SystemState.HALTED
        if loss_from_high >= config.dd_reduce_only * high_water_mark:
            return SystemState.REDUCE_ONLY
    return SystemState.RUNNING


class SystemStateStore:
    """CRO-01/R-02: atomic control row plus append-only transition evidence.

    PostgreSQL locks the control row and append allocator in one transaction;
    SQLite takes BEGIN IMMEDIATE. A database failure also latches this process
    HALTED. Storage recovery never silently clears that process latch.
    """

    def __init__(
        self, engine: Engine, clock: Clock, notifier: Notifier, *, verify: bool = True
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.notifier = DeduplicatingNotifier(notifier)
        self._emergency_halt = False
        self.ledger = Ledger(engine, clock, halt_callback=self._notify)
        if verify:
            self.startup()

    def _notify(self, reason: str) -> None:
        try:
            self.notifier.notify(SystemState.HALTED.value, reason)
        except Exception as exc:
            self._emergency_halt = True
            raise StateTransitionError("R-02: halt notification failed") from exc

    def _verify_projection(self, session: Session, control: SystemControl) -> None:
        """R-02: a mutable projection cannot silently erase immutable halt evidence."""
        latest = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1))
        expected = SystemState.RUNNING.value if latest is None else latest.state
        version = session.scalar(select(func.count()).select_from(SystemEvent))
        if control.state != expected or control.version != version:
            raise LedgerIntegrityError("R-02: operating state disagrees with immutable events")

    def startup(self) -> None:
        """R-02: chain verification is mandatory before accepting proposals."""
        try:
            self.ledger.verify_chain()
            self.current()
        except SafetyError as exc:
            self._emergency_halt = True
            self._notify("startup integrity or database verification failed")
            raise exc

    def current(self) -> SystemState:
        """CRO-01: read persisted state; a failed read cannot imply RUNNING."""
        if self._emergency_halt:
            return SystemState.HALTED
        try:
            with transaction(self.engine) as session:
                control = session.get(SystemControl, 1)
                if control is None:
                    raise StateTransitionError("R-02: missing state control row")
                try:
                    state = SystemState(control.state)
                except ValueError as exc:
                    raise StateTransitionError("R-02: invalid persisted state") from exc
                self._verify_projection(session, control)
                return state
        except SafetyError:
            self._emergency_halt = True
            self._notify("system state could not be verified")
            raise

    def escalate(self, target: SystemState, reason: str) -> SystemState:
        """CRO-01: an automatic request can only preserve or increase severity."""
        if not isinstance(target, SystemState) or not isinstance(reason, str) or not reason.strip():
            raise StateTransitionError("R-02: escalation needs valid state and reason")
        try:
            with transaction(self.engine) as session:
                control = session.scalar(
                    select(SystemControl).where(SystemControl.id == 1).with_for_update()
                )
                if control is None:
                    raise StateTransitionError("R-02: missing state control row")
                try:
                    current = SystemState(control.state)
                except ValueError as exc:
                    raise StateTransitionError("R-02: invalid persisted state") from exc
                self._verify_projection(session, control)
                if _RANK[target] > _RANK[current]:
                    control.state = target.value
                    control.version += 1
                    self.ledger.append_in_session(
                        session,
                        SystemEvent,
                        state=target.value,
                        reason=reason,
                        operator_id=None,
                        event_type="ESCALATE",
                    )
                    current = target
            if target == SystemState.HALTED:
                self._notify(reason)
            return SystemState.HALTED if self._emergency_halt else current
        except SafetyError:
            self._emergency_halt = True
            self._notify("state escalation failed; process latched HALTED")
            raise

    def operator_reset(
        self, operator_id: str, reason: str, target: SystemState = SystemState.RUNNING
    ) -> SystemState:
        """CRO-01: auditable reset; corrupted ledgers must be repaired first.

        Operator authentication belongs to a future service boundary. This local
        administrative API requires attribution and is never called by rules.
        """
        if (
            not isinstance(operator_id, str)
            or not isinstance(reason, str)
            or not operator_id.strip()
            or not reason.strip()
        ):
            raise StateTransitionError("R-02: reset requires operator ID and reason")
        if not isinstance(target, SystemState):
            raise StateTransitionError("R-02: invalid reset target")
        try:
            self.ledger.verify_chain()
            with transaction(self.engine) as session:
                control = session.scalar(
                    select(SystemControl).where(SystemControl.id == 1).with_for_update()
                )
                if control is None:
                    raise StateTransitionError("R-02: missing state control row")
                self._verify_projection(session, control)
                self.ledger.append_in_session(
                    session,
                    SystemEvent,
                    state=target.value,
                    reason=reason,
                    operator_id=operator_id,
                    event_type="OPERATOR_RESET",
                )
                control.state = target.value
                control.version += 1
            self._emergency_halt = False
            self.notifier.reset()
            if target == SystemState.HALTED:
                self._notify(reason)
            return target
        except SafetyError:
            self._emergency_halt = True
            self._notify("operator reset failed; process latched HALTED")
            raise

    def halt_for_error(self, error: Exception) -> SystemState:
        """R-02: stale data, integrity, reconciliation, clock and provider faults halt."""
        return self.escalate(SystemState.HALTED, f"fault: {type(error).__name__}")

    def apply_financial_limits(
        self,
        equity: Decimal,
        high_water_mark: Decimal,
        day_start_equity: Decimal,
        config: Settings,
    ) -> SystemState:
        """CRO-09: latch drawdown/faults only; daily loss never needs a reset."""
        try:
            target = financial_state(equity, high_water_mark, day_start_equity, config)
        except DataIntegrityError:
            self.escalate(SystemState.HALTED, "unverifiable financial state")
            raise
        except Exception as exc:
            self.escalate(SystemState.HALTED, "financial state evaluation failed")
            raise DataIntegrityError("CRO-09/CRO-10: financial state evaluation failed") from exc
        return self.escalate(target, "financial limits evaluated")


def require_integrity(store: SystemStateStore) -> None:
    """R-02: reverify on demand, persist and notify any chain failure."""
    try:
        store.ledger.verify_chain()
    except LedgerIntegrityError:
        store.halt_for_error(LedgerIntegrityError("ledger verification failed"))
        raise
