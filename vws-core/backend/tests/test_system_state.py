"""CRO-01/CRO-09/CRO-10/R-09: persistent state, limits and fault branches."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any, cast

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import SystemControl, SystemEvent, transaction
from backend.core.errors import (
    DatabaseError,
    DataIntegrityError,
    LedgerIntegrityError,
    StateTransitionError,
)
from backend.core.system_state import (
    SystemState,
    SystemStateStore,
    financial_state,
    require_integrity,
    state_allows,
)


class RecordingNotifier:
    """R-02: observable notification boundary without external messages."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def notify(self, state: str, reason: str) -> None:
        self.calls.append((state, reason))
        if self.fail:
            raise RuntimeError("notification fault")


@pytest.mark.parametrize("state", list(SystemState))
@pytest.mark.parametrize("intent", ["ENTRY", "ADD", "REDUCE", "EXIT", "UNKNOWN"])
@pytest.mark.parametrize("source", ["SIGNAL", "SYSTEM", "MANUAL", "UNKNOWN"])
def test_CRO_01_R_09_state_gate(state: SystemState, intent: str, source: str) -> None:
    valid = intent != "UNKNOWN" and source != "UNKNOWN"
    expected = valid and (
        state == SystemState.RUNNING
        or (
            intent in {"REDUCE", "EXIT"}
            and (state == SystemState.REDUCE_ONLY or source == "MANUAL")
        )
    )
    assert state_allows(state, intent, source) == expected


@pytest.mark.parametrize(
    ("equity", "hwm", "start", "expected"),
    [
        ("100", "100", "100", SystemState.RUNNING),
        ("100.01", "100", "100", SystemState.RUNNING),
        ("92.01", "100", "92.01", SystemState.RUNNING),
        ("92", "100", "92", SystemState.REDUCE_ONLY),
        ("88.01", "100", "88.01", SystemState.REDUCE_ONLY),
        ("88", "100", "88", SystemState.HALTED),
        ("98.01", "100", "100", SystemState.RUNNING),
        ("98", "100", "100", SystemState.RUNNING),
        ("0", "100", "100", SystemState.HALTED),
        ("100", "0", "100", SystemState.HALTED),
        ("100", "100", "0", SystemState.HALTED),
    ],
)
def test_CRO_09_CRO_10_exact_boundaries(
    equity: str, hwm: str, start: str, expected: SystemState
) -> None:
    assert (
        financial_state(
            Decimal(equity),
            Decimal(hwm),
            Decimal(start),
            Settings(
                broker_account_type="CASH",
            ),
        )
        == expected
    )


def test_CRO_01_R_02_latch_restart_reset(engine: Engine, clock: FrozenClock) -> None:
    notifier = RecordingNotifier()
    store = SystemStateStore(engine, clock, notifier)
    assert store.current() == SystemState.RUNNING
    assert store.escalate(SystemState.REDUCE_ONLY, "drawdown") == SystemState.REDUCE_ONLY
    assert store.escalate(SystemState.RUNNING, "recovered") == SystemState.REDUCE_ONLY
    assert store.escalate(SystemState.HALTED, "stale data") == SystemState.HALTED
    restarted = SystemStateStore(engine, clock, notifier)
    assert restarted.current() == SystemState.HALTED
    assert restarted.escalate(SystemState.RUNNING, "recovered") == SystemState.HALTED
    assert restarted.operator_reset("local-operator", "verified fresh state") == SystemState.RUNNING
    with transaction(engine) as session:
        events = session.scalars(select(SystemEvent).order_by(SystemEvent.seq)).all()
        assert [event.event_type for event in events] == ["ESCALATE", "ESCALATE", "OPERATOR_RESET"]
        assert events[-1].operator_id == "local-operator"
    assert len(notifier.calls) == 1
    require_integrity(restarted)


@pytest.mark.parametrize(("operator", "reason"), [("", "why"), ("who", " ")])
def test_CRO_01_reset_needs_attribution(
    engine: Engine, clock: FrozenClock, operator: str, reason: str
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(StateTransitionError):
        store.operator_reset(operator, reason)


def test_R_02_notifications_after_durable_halt(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(fail=True))
    with pytest.raises(StateTransitionError):
        store.halt_for_error(RuntimeError("provider"))
    assert store.current() == SystemState.HALTED
    assert SystemStateStore(engine, clock, RecordingNotifier()).current() == SystemState.HALTED


def test_CRO_09_CRO_10_apply_tiers(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    assert (
        store.apply_financial_limits(
            Decimal(98),
            Decimal(100),
            Decimal(100),
            Settings(
                broker_account_type="CASH",
            ),
        )
        == SystemState.RUNNING
    )
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(
            Decimal("NaN"),
            Decimal(100),
            Decimal(100),
            Settings(
                broker_account_type="CASH",
            ),
        )
    assert store.current() == SystemState.HALTED


def test_R_02_missing_control_halts(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with transaction(engine) as session:
        session.execute(delete(SystemControl))
    with pytest.raises(StateTransitionError):
        store.current()
    assert store.current() == SystemState.HALTED


def test_R_02_database_fault_latches(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.core.system_state as state_module

    store = SystemStateStore(engine, clock, RecordingNotifier())

    def broken_transaction(database: Engine) -> None:
        raise DatabaseError("injected storage failure")

    monkeypatch.setattr(state_module, "transaction", broken_transaction)
    with pytest.raises(DatabaseError):
        store.current()
    assert store.current() == SystemState.HALTED


def test_R_02_clock_is_injected(engine: Engine) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    store = SystemStateStore(engine, clock, RecordingNotifier())
    store.halt_for_error(RuntimeError("unknown fault"))
    with transaction(engine) as session:
        event = session.scalar(select(SystemEvent))
        assert event is not None
        assert event.created_at == clock.now()


def test_CRO_01_invalid_transition_arguments(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify_ledger=False)
    with pytest.raises(StateTransitionError):
        store.escalate(cast(SystemState, "BAD"), "reason")
    with pytest.raises(StateTransitionError):
        store.escalate(SystemState.HALTED, " ")
    with pytest.raises(StateTransitionError):
        store.operator_reset("operator", "reason", cast(SystemState, "BAD"))
    assert (
        store.operator_reset("operator", "remain halted", SystemState.HALTED) == SystemState.HALTED
    )


def test_R_02_startup_failure_notifies(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify_ledger=False)

    def broken_verify() -> None:
        raise LedgerIntegrityError("injected chain corruption")

    monkeypatch.setattr(store.ledger, "verify_chain", broken_verify)
    with pytest.raises(LedgerIntegrityError):
        store.startup()
    assert store.current() == SystemState.HALTED
    with pytest.raises(LedgerIntegrityError):
        store.operator_reset("operator", "cannot clear corrupt ledger")
    with pytest.raises(LedgerIntegrityError):
        require_integrity(store)


@pytest.mark.parametrize("action", ["current", "escalate", "reset"])
def test_R_02_unverifiable_control_branches(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify_ledger=False)
    with transaction(engine) as session:
        session.execute(delete(SystemControl))
    monkeypatch.setattr(store.ledger, "verify_chain", lambda: None)
    with pytest.raises(StateTransitionError):
        if action == "current":
            store.current()
        elif action == "escalate":
            store.escalate(SystemState.HALTED, "fault")
        else:
            store.operator_reset("operator", "reason")
    assert store.current() == SystemState.HALTED


@pytest.mark.parametrize("action", ["current", "escalate"])
def test_R_02_invalid_control_branches(engine: Engine, clock: FrozenClock, action: str) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify_ledger=False)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        connection.execute(update(SystemControl).values(state="INVALID"))
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
    with pytest.raises(StateTransitionError):
        if action == "current":
            store.current()
        else:
            store.escalate(SystemState.HALTED, "fault")


def test_R_02_emergency_latch_survives_successful_read(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier(), verify_ledger=False)

    def broken_verify() -> None:
        raise LedgerIntegrityError("fault")

    monkeypatch.setattr(store.ledger, "verify_chain", broken_verify)
    with pytest.raises(LedgerIntegrityError):
        store.startup()
    assert store.escalate(SystemState.RUNNING, "healthy storage now") == SystemState.HALTED


def test_CRO_09_R_04_low_precision_cannot_mask_boundaries() -> None:
    config = Settings(
        broker_account_type="CASH",
    )
    with localcontext() as context:
        context.prec = 2
        assert (
            financial_state(Decimal("8801"), Decimal("10000"), Decimal("8801"), config)
            == SystemState.REDUCE_ONLY
        )
        assert (
            financial_state(Decimal("9201"), Decimal("10000"), Decimal("9201"), config)
            == SystemState.RUNNING
        )


@pytest.mark.parametrize("bad", [100, "100", float("100"), True, None, Decimal("NaN")])
def test_R_02_R_04_financial_input_fault_halts(
    engine: Engine, clock: FrozenClock, bad: Any
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(
            bad,
            Decimal("100"),
            Decimal("100"),
            Settings(
                broker_account_type="CASH",
            ),
        )
    assert store.current() == SystemState.HALTED


def test_R_02_unvalidated_financial_config_halts(engine: Engine, clock: FrozenClock) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(
            Decimal("100"), Decimal("100"), Decimal("100"), cast(Settings, None)
        )
    assert store.current() == SystemState.HALTED


def test_R_02_unexpected_financial_fault_is_typed_and_halts(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.core.system_state as state_module

    def broken(*args: object) -> SystemState:
        raise RuntimeError("unexpected evaluation fault")

    store = SystemStateStore(engine, clock, RecordingNotifier())
    monkeypatch.setattr(state_module, "financial_state", broken)
    with pytest.raises(DataIntegrityError):
        store.apply_financial_limits(
            Decimal("100"),
            Decimal("100"),
            Decimal("100"),
            Settings(
                broker_account_type="CASH",
            ),
        )
    assert store.current() == SystemState.HALTED


@pytest.mark.parametrize("bad", [None, 42, [], True])
def test_R_02_state_admin_arguments_raise_typed_errors(
    engine: Engine, clock: FrozenClock, bad: Any
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(StateTransitionError):
        store.escalate(SystemState.HALTED, bad)
    with pytest.raises(StateTransitionError):
        store.operator_reset(bad, "reason")
    with pytest.raises(StateTransitionError):
        store.operator_reset("operator", bad)
    assert not state_allows(cast(SystemState, bad), "ENTRY", "SIGNAL")
    assert not state_allows(SystemState.RUNNING, bad, "SIGNAL")
    assert not state_allows(SystemState.RUNNING, "ENTRY", bad)


@pytest.mark.parametrize("action", ["current", "escalate", "reset"])
@pytest.mark.parametrize("field", ["state", "version"])
def test_R_02_mutable_projection_cannot_clear_immutable_halt(
    engine: Engine, clock: FrozenClock, action: str, field: str
) -> None:
    store = SystemStateStore(engine, clock, RecordingNotifier())
    store.escalate(SystemState.HALTED, "confirmed fault")
    values: dict[str, str | int] = {"state": "RUNNING"} if field == "state" else {"version": 0}
    with engine.begin() as connection:
        connection.execute(update(SystemControl).values(**values))
    with pytest.raises(LedgerIntegrityError):
        if action == "current":
            store.current()
        elif action == "escalate":
            store.escalate(SystemState.REDUCE_ONLY, "must not overwrite evidence")
        else:
            store.operator_reset("operator", "unverified recovery")
    assert store.current() == SystemState.HALTED
