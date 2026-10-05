"""GD-01/GD-03/GD-05/R-10/R-14: immutable evidence, expiry and replay defenses."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, insert, inspect, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import (
    Alert,
    AlertEvent,
    AppendControl,
    ApprovalEvent,
    ConfigSnapshot,
    DataSnapshot,
    LedgerRecord,
    LLMCall,
    Order,
    ResearchReport,
    SchemaMeta,
    Signal,
    SystemControl,
    TradeTicket,
    create_database,
    create_schema,
    transaction,
)
from backend.core.errors import DatabaseError, LedgerIntegrityError, SafetyError
from backend.core.ledger import GENESIS_HASH, Ledger, row_digest, ticket_digest

RecordT = TypeVar("RecordT", bound=LedgerRecord)


def _candidate(ledger: Ledger, clock: FrozenClock) -> Alert:
    snapshot = ledger.append(
        DataSnapshot,
        symbol="AAPL",
        timeframe="1Day",
        range_start=clock.now() - timedelta(days=1),
        range_end=clock.now(),
        feed="SIP",
        adjustment="ALL",
        fetched_at=clock.now(),
        bar_count=0,
        sha256="a" * 64,
    )
    signal = ledger.append(
        Signal,
        agent_name="deterministic-fixture",
        symbol="AAPL",
        direction="BUY",
        confidence=Decimal("0.85"),
        structured_thesis={"source": "fixture"},
        invalidation="close below structural stop",
        data_snapshot_id=snapshot.id,
    )
    proposal = ledger.append(
        Order,
        proposal_id=uuid4(),
        signal_id=signal.id,
        client_order_id=str(uuid4()),
        account_id="isolated-paper-account",
        symbol="AAPL",
        side="BUY",
        intent="ENTRY",
        qty=2,
        limit_price=Decimal("100.00"),
        stop_price=Decimal("95.00"),
        target_price=Decimal("110.00"),
        source="SIGNAL",
    )
    return ledger.append(
        Alert,
        proposal_id=proposal.proposal_id,
        signal_id=signal.id,
        symbol="AAPL",
        playbook="BASE_BREAKOUT",
        score=Decimal("8.50"),
        card_text="deterministic fixture card",
        config_hash="b" * 64,
        expires_at=clock.now() + timedelta(hours=1),
    )


def _deliver(ledger: Ledger, alert: Alert) -> AlertEvent:
    return ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=-123,
        telegram_message_id=456,
        reason="observed delivery succeeded",
    )


def _ticket(ledger: Ledger, alert: Alert) -> TradeTicket:
    return ledger.record_trade_ticket(
        alert.id,
        telegram_user_id=789,
        reasons=[{"rule_id": "CRO-01", "passed": True}],
        valid_until=alert.expires_at,
    )


def _raw_append(ledger: Ledger, model: type[RecordT], **fields: Any) -> RecordT:
    """R-02: simulate hash-valid malicious INSERT that bypasses the local writer."""
    with transaction(ledger.engine) as session:
        control = session.get(AppendControl, 1)
        assert control is not None
        values = {column.name: None for column in model.__table__.columns if column.nullable}
        values.update(fields)
        record = model(**values)
        record.id = uuid4()
        record.seq = control.next_seq
        record.created_at = ledger.clock.now()
        previous = session.scalar(select(model).order_by(model.seq.desc()).limit(1))
        record.prev_hash = GENESIS_HASH if previous is None else previous.row_hash
        record.row_hash = row_digest(record)
        session.execute(
            insert(model),
            {column.name: record.__dict__[column.name] for column in model.__table__.columns},
        )
        control.next_seq += 1
    return record


def test_GD_05_R_14_delivery_is_an_appended_actionable_projection(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    assert alert.alert_id == alert.id
    assert ledger.current_alert_status(alert.id) == "PENDING"
    assert not ledger.alert_is_actionable(alert.id)
    _deliver(ledger, alert)
    assert ledger.current_alert_status(alert.id) == "SENT"
    assert ledger.alert_is_actionable(alert.id)
    with Session(engine) as session:
        original = session.get(Alert, alert.id)
        assert original is not None and original.status == "PENDING"
        assert original.telegram_message_id is None
        assert list(session.scalars(select(AlertEvent.state).order_by(AlertEvent.seq))) == [
            "PENDING",
            "SENT",
        ]
    ledger.verify_chain()


def test_GD_05_R_05_delivery_cannot_predate_its_parent_alert(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    with pytest.raises(LedgerIntegrityError, match="precedes"):
        ledger.append(
            AlertEvent,
            alert_id=alert.id,
            state="SENT",
            telegram_chat_id=-123,
            telegram_message_id=456,
            reason="invalid earlier delivery timestamp",
            created_at=clock.now() - timedelta(seconds=1),
        )
    assert ledger.current_alert_status(alert.id) == "PENDING"
    with Session(engine) as session:
        assert len(list(session.scalars(select(AlertEvent)))) == 1
    ledger.verify_chain()


def test_GD_05_R_05_approval_cannot_postdate_its_own_creation(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    later = Ledger(engine, FrozenClock(clock.now() + timedelta(seconds=2)))
    with pytest.raises(LedgerIntegrityError, match="timestamp"):
        later.append(
            ApprovalEvent,
            alert_id=alert.id,
            action="USER_VETOED",
            telegram_user_id=789,
            ts=later.clock.now(),
            created_at=clock.now() + timedelta(seconds=1),
            reasons=[],
        )
    assert later.current_alert_status(alert.id) == "SENT"
    with Session(engine) as session:
        assert session.scalar(select(ApprovalEvent)) is None
    later.verify_chain()


def test_GD_05_R_10_R_14_manual_ticket_binds_exact_local_proposal(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    ticket = _ticket(ledger, alert)
    assert ticket.ticket_id == ticket.id
    assert ticket.ticket_sha256 == ticket_digest(ticket)
    assert ticket.alert_id == alert.id
    assert ticket.qty == 2 and ticket.limit_price == Decimal("100.00")
    assert ticket.limit_price.as_tuple().exponent == -2
    assert ticket.stop_price == Decimal("95.00") and ticket.target_price == Decimal("110.00")
    assert ledger.current_alert_status(alert.id) == "APPROVED"
    assert not ledger.alert_is_actionable(alert.id)
    ledger.verify_chain()
    with Session(engine) as session:
        loaded_ticket = session.get(TradeTicket, ticket.id)
        assert loaded_ticket is not None and loaded_ticket.limit_price.as_tuple().exponent == -2
        decision = session.scalar(select(ApprovalEvent))
        assert decision is not None
        assert decision.event_id == decision.id
        assert decision.action == "MANUALLY_APPROVED" and decision.telegram_user_id == 789


def test_GD_05_R_14_replay_and_concurrent_tickets_are_single_use(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)

    def attempt(_: int) -> UUID | None:
        try:
            return _ticket(ledger, alert).id
        except LedgerIntegrityError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert sum(result is not None for result in results) == 1
    with pytest.raises(LedgerIntegrityError):
        _ticket(ledger, alert)
    with Session(engine) as session:
        assert len(list(session.scalars(select(ApprovalEvent)))) == 1
        assert len(list(session.scalars(select(TradeTicket)))) == 1
    ledger.verify_chain()


@pytest.mark.parametrize("seconds", [-1, 0, 3601])
def test_GD_05_R_14_invalid_ticket_interval_rolls_back_human_decision(
    engine: Engine, clock: FrozenClock, seconds: int
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    with pytest.raises(LedgerIntegrityError):
        ledger.record_trade_ticket(
            alert.id,
            telegram_user_id=789,
            reasons=[],
            valid_until=clock.now() + timedelta(seconds=seconds),
        )
    assert ledger.current_alert_status(alert.id) == "SENT"
    with Session(engine) as session:
        assert session.scalar(select(ApprovalEvent)) is None
        assert session.scalar(select(TradeTicket)) is None
    ledger.verify_chain()


def test_GD_05_R_14_expiry_at_exact_boundary_is_terminal(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    expired = Ledger(engine, FrozenClock(alert.expires_at))
    assert not expired.alert_is_actionable(alert.id)
    with pytest.raises(LedgerIntegrityError, match="Expired"):
        _ticket(expired, alert)
    expired.append(ApprovalEvent, alert_id=alert.id, action="EXPIRED", reasons=[])
    assert expired.current_alert_status(alert.id) == "EXPIRED"
    expired.verify_chain()


@pytest.mark.parametrize("action", ["USER_VETOED", "REVALIDATION_FAILED"])
def test_GD_05_R_14_terminal_decisions_cannot_later_create_tickets(
    engine: Engine, clock: FrozenClock, action: str
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    ledger.append(
        ApprovalEvent,
        alert_id=alert.id,
        action=action,
        telegram_user_id=789,
        reasons=[{"rule_id": "CRO-07", "passed": False}],
    )
    with pytest.raises(LedgerIntegrityError):
        _ticket(ledger, alert)
    assert ledger.current_alert_status(alert.id) in {"REJECTED", "REVALIDATION_FAILED"}
    ledger.verify_chain()


@pytest.mark.parametrize(
    "fields",
    [
        {"action": "MANUALLY_APPROVED", "telegram_user_id": None},
        {"action": "MANUALLY_APPROVED", "telegram_user_id": True},
        {"action": "MANUALLY_APPROVED", "telegram_user_id": -1},
        {"action": "EXPIRED"},
        {"action": "REVALIDATION_FAILED", "reasons": []},
        {"action": "UNRECOGNIZED"},
    ],
)
def test_GD_05_R_14_bad_approval_evidence_cannot_consume_alert(
    engine: Engine, clock: FrozenClock, fields: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    values: dict[str, Any] = {
        "alert_id": alert.id,
        "telegram_user_id": 789,
        "reasons": [{"rule_id": "CRO-01", "passed": True}],
    }
    values.update(fields)
    with pytest.raises(SafetyError):
        ledger.append(ApprovalEvent, **values)
    assert ledger.current_alert_status(alert.id) == "SENT"
    ledger.verify_chain()


@pytest.mark.parametrize("operation", ["verify", "status", "actionable", "ticket"])
def test_GD_05_R_14_hash_valid_raw_approval_without_delivery_halts(
    engine: Engine, clock: FrozenClock, operation: str
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    approval = _raw_append(
        ledger,
        ApprovalEvent,
        alert_id=alert.id,
        action="MANUALLY_APPROVED",
        telegram_user_id=789,
        ts=clock.now(),
        reasons=[],
    )
    _raw_append(
        ledger,
        AlertEvent,
        alert_id=alert.id,
        state="APPROVED",
        approval_event_id=approval.id,
        reason="forged event",
    )
    with pytest.raises(LedgerIntegrityError, match="HALTED"):
        if operation == "verify":
            ledger.verify_chain()
        elif operation == "status":
            ledger.current_alert_status(alert.id)
        elif operation == "actionable":
            ledger.alert_is_actionable(alert.id)
        else:
            _ticket(ledger, alert)
    with Session(engine) as session:
        state = session.get(SystemControl, 1)
        assert state is not None and state.state == "HALTED"


def test_GD_05_R_14_rehashed_ticket_tampering_cannot_change_qty(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    _deliver(ledger, alert)
    ticket = _ticket(ledger, alert)
    ticket.qty += 1
    ticket.ticket_sha256 = ticket_digest(ticket)
    digest = row_digest(ticket)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_trade_tickets_update")
        connection.execute(
            text("UPDATE trade_tickets SET qty = :qty, ticket_sha256 = :ticket, row_hash = :row"),
            {"qty": ticket.qty, "ticket": ticket.ticket_sha256, "row": digest},
        )
    with pytest.raises(LedgerIntegrityError, match="HALTED"):
        ledger.verify_chain()


def _llm_values() -> dict[str, Any]:
    return {
        "provider": "fixture-provider",
        "base_url_host": "example.invalid",
        "model": "explicit-fixture-model",
        "prompt_hash": "c" * 64,
        "input_tokens": 10,
        "output_tokens": 20,
        "est_cost_usd": Decimal("0.000001"),
        "latency_ms": 1,
        "outcome": "VALID",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"est_cost_usd": Decimal("-0.000001")},
        {"est_cost_usd": Decimal("NaN")},
        {"est_cost_usd": 0.01},
        {"est_cost_usd": None},
        {"input_tokens": None},
        {"input_tokens": -1},
        {"input_tokens": Decimal("1.5")},
        {"output_tokens": True},
        {"latency_ms": -1},
        {"outcome": "BUDGET"},
        {"outcome": "UNKNOWN"},
        {"base_url_host": "https://user:secret@example.invalid/v1"},
    ],
)
def test_GD_01_R_02_llm_usage_and_cost_fail_closed(
    engine: Engine, clock: FrozenClock, changes: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    fields = _llm_values()
    fields.update(changes)
    with pytest.raises(SafetyError):
        ledger.append(LLMCall, **fields)
    with Session(engine) as session:
        assert session.scalar(select(LLMCall)) is None
    ledger.verify_chain()


def test_GD_01_timeout_usage_is_unknown_and_budget_veto_is_zero_cost(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    fields = _llm_values()
    fields.update(outcome="TIMEOUT", input_tokens=None, output_tokens=None, est_cost_usd=None)
    transport_failure = ledger.append(LLMCall, **fields)
    assert transport_failure.est_cost_usd is None
    fields.update(outcome="BUDGET", input_tokens=0, output_tokens=0, est_cost_usd=Decimal(0))
    budget = ledger.append(LLMCall, **fields)
    assert budget.est_cost_usd == Decimal(0)
    ledger.verify_chain()


@pytest.mark.parametrize(
    "changes",
    [
        {"est_cost_usd": Decimal("-0.000001")},
        {"est_cost_usd": None},
        {"input_tokens": -1},
        {"outcome": "BUDGET", "input_tokens": None, "output_tokens": None, "est_cost_usd": None},
        {"outcome": "UNKNOWN"},
    ],
)
def test_GD_01_raw_SQL_llm_cost_and_usage_checks_cannot_be_bypassed(
    engine: Engine, clock: FrozenClock, changes: dict[str, Any]
) -> None:
    fields = _llm_values()
    fields.update(
        id=uuid4(),
        seq=1,
        created_at=clock.now(),
        prev_hash=GENESIS_HASH,
        row_hash=GENESIS_HASH,
    )
    fields.update(changes)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(insert(LLMCall).values(**fields))
    Ledger(engine, clock).verify_chain()


@pytest.mark.parametrize(
    "settings",
    [
        {"providers": [{"password": "sensitive-fixture"}]},
        {"providers": [{"inner": [{"api_key": "sensitive-fixture"}]}]},
        [{"max_weight": "0.10"}],
    ],
)
def test_R_07_config_secret_fields_in_nested_arrays_and_bad_outer_shape_reject(
    engine: Engine, clock: FrozenClock, settings: Any
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(SafetyError):
        ledger.append(ConfigSnapshot, config_hash="d" * 64, settings=settings)
    ledger.verify_chain()


@pytest.mark.parametrize(
    "model,changes",
    [
        (Alert, {"signal_id": None}),
        (Alert, {"score": Decimal("10.01")}),
        (Alert, {"score": Decimal("0.99")}),
        (Alert, {"status": "APPROVED"}),
        (Alert, {"signal_id": uuid4()}),
        (Alert, {"proposal_id": uuid4()}),
        (AlertEvent, {"state": "SENT", "telegram_chat_id": None}),
        (AlertEvent, {"state": "SENT", "telegram_message_id": None}),
        (AlertEvent, {"state": "APPROVED", "approval_event_id": None}),
    ],
)
def test_GD_03_GD_05_raw_SQL_checks_and_foreign_keys_reject_bad_evidence(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], changes: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    alert = _candidate(ledger, clock)
    if model is Alert:
        values = {column.name: alert.__dict__[column.name] for column in model.__table__.columns}
    else:
        values = {
            "alert_id": alert.id,
            "state": "SENT",
            "telegram_chat_id": -123,
            "telegram_message_id": 456,
            "approval_event_id": None,
            "reason": "fixture",
            "created_at": clock.now(),
            "prev_hash": GENESIS_HASH,
            "row_hash": GENESIS_HASH,
        }
    values.update(id=uuid4(), seq=1000)
    values.update(changes)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(insert(model).values(**values))
    ledger.verify_chain()


def test_R_02_schema_version_guard_does_not_silently_extend_an_old_ledger(tmp_path: Path) -> None:
    engine = create_database(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE signals (id TEXT PRIMARY KEY)")
        with pytest.raises(DatabaseError, match="migration"):
            create_schema(engine)
        assert inspect(engine).get_table_names() == ["signals"]
    finally:
        engine.dispose()


def test_R_02_schema_version_tampering_is_rejected(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(update(SchemaMeta).values(version=1))
    with pytest.raises(DatabaseError, match="incompatible"):
        create_schema(engine)


def test_GD_03_R_02_research_missing_alert_provenance_rejects(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(SafetyError):
        ledger.append(
            ResearchReport,
            alert_id=uuid4(),
            agent_name="fixture",
            status="UNAVAILABLE",
            payload={"reason": "provider unavailable"},
        )
    ledger.verify_chain()
