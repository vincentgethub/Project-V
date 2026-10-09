"""R-01/R-02/R-04/R-05/R-08: immutable ledger and fail-closed inventory tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.content import headline_digest, headline_stable_id
from backend.core.database import (
    LEDGER_MODELS,
    Alert,
    AlertEvent,
    AppendControl,
    ComplianceCheck,
    ConfigSnapshot,
    DataSnapshot,
    Fill,
    LedgerRecord,
    LLMCall,
    NewsHeadlineRecord,
    Order,
    OrderEvent,
    PortfolioState,
    ResearchReport,
    RiskDecision,
    RiskRuleResult,
    SchemaVersion,
    SecurityEvent,
    Signal,
    SystemControl,
    SystemEvent,
    create_schema,
    transaction,
)
from backend.core.errors import (
    DataIntegrityError,
    LedgerIntegrityError,
    ReconciliationError,
    SafetyError,
)
from backend.core.ledger import GENESIS_HASH, Ledger, row_digest


def _snapshot(ledger: Ledger, clock: FrozenClock) -> DataSnapshot:
    return ledger.append(
        DataSnapshot,
        symbol="AAPL",
        timeframe="1Day",
        range_start=clock.now() - timedelta(days=1),
        range_end=clock.now(),
        feed="SIP",
        adjustment="ALL",
        fetched_at=clock.now(),
        bar_count=1,
        sha256="a" * 64,
        bars=[{"close": "100"}],
    )


def _signal(ledger: Ledger, clock: FrozenClock) -> Signal:
    snapshot = _snapshot(ledger, clock)
    return ledger.append(
        Signal,
        agent_name="deterministic_fixture",
        symbol="AAPL",
        direction="BUY",
        confidence=Decimal("0.8"),
        structured_thesis={"reason": "fixture"},
        invalidation="under stop",
        data_snapshot_id=snapshot.id,
        prompt_hash=None,
    )


def _order(ledger: Ledger, clock: FrozenClock, **overrides: Any) -> Order:
    signal = _signal(ledger, clock)
    fields: dict[str, Any] = {
        "proposal_id": uuid4(),
        "signal_id": signal.id,
        "client_order_id": str(uuid4()),
        "account_id": "paper-fixture",
        "symbol": "AAPL",
        "side": "BUY",
        "intent": "ENTRY",
        "qty": 2,
        "limit_price": Decimal(100),
        "stop_price": Decimal(95),
        "source": "SIGNAL",
    }
    fields.update(overrides)
    return ledger.append(Order, **fields)


def _submitted(ledger: Ledger, clock: FrozenClock) -> Order:
    order = _order(ledger, clock)
    for state in ("APPROVED", "SUBMITTED"):
        ledger.append(
            OrderEvent,
            order_id=order.id,
            state=state,
            reason="fixture",
            broker_order_id=None,
        )
    return order


def _all_records(ledger: Ledger, clock: FrozenClock) -> dict[type[LedgerRecord], LedgerRecord]:
    digest = headline_digest("Fixture public company results")
    ledger.append(
        NewsHeadlineRecord,
        stable_id=headline_stable_id("FAKE", "fixture-1", digest),
        provider="FAKE",
        provider_id="fixture-1",
        headline="Fixture public company results",
        headline_sha256=digest,
        published_at=clock.now() - timedelta(minutes=1),
        details={"symbols": ["AAPL"], "summary_allowed": True},
    )
    order = _submitted(ledger, clock)
    fill = ledger.record_fill(
        order.id,
        broker_fill_id="observed-1",
        qty=1,
        price=Decimal(99),
        filled_at=clock.now(),
    )
    verdict = ledger.append(
        RiskDecision,
        proposal_id=order.proposal_id,
        decision="APPROVED",
        config_hash="b" * 64,
        snapshot_hash="c" * 64,
        evaluated_at=clock.now(),
    )
    ledger.append(
        RiskRuleResult,
        risk_decision_id=verdict.id,
        rule_id="CRO-01",
        passed=1,
        severity="BLOCK",
        observed={"state": "RUNNING"},
        limit={},
        message="allowed",
    )
    ledger.append(
        ComplianceCheck,
        proposal_id=order.proposal_id,
        rule_id="CMP-01",
        passed=1,
        severity="WARN",
        observed={},
        limit={},
        message="no loss sale",
        checked_at=clock.now(),
    )
    ledger.append(
        PortfolioState,
        account_id="paper-fixture",
        account_type="CASH",
        as_of=clock.now(),
        equity=Decimal(1000),
        cash=Decimal(901),
        settled_cash=Decimal(901),
        positions={"AAPL": {"qty": 1}},
        high_water_mark=Decimal(1000),
        day_start_equity=Decimal(1000),
    )
    with transaction(ledger.engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None
        control.state = "REDUCE_ONLY"
        control.version += 1
        ledger.append_in_session(
            session,
            SystemEvent,
            state="REDUCE_ONLY",
            reason="fixture",
            operator_id=None,
            event_type="ESCALATE",
        )
    ledger.append(ConfigSnapshot, config_hash="d" * 64, settings={"paper_trading": True})
    ledger.append(SchemaVersion, version=5, source_version=4, backup_sha256="e" * 64)
    alert = ledger.append(
        Alert,
        proposal_id=order.proposal_id,
        signal_id=order.signal_id,
        symbol=order.symbol,
        playbook="BASE_BREAKOUT",
        score=Decimal("8.50"),
        card_text="audit fixture candidate",
        config_hash="d" * 64,
        expires_at=clock.now() + timedelta(hours=1),
    )
    ledger.append(
        ResearchReport,
        alert_id=alert.id,
        agent_name="flow",
        status="UNAVAILABLE",
        payload={"reason": "provider unavailable"},
    )
    ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=123,
        telegram_message_id=456,
        reason="delivery fixture",
    )
    ticket = ledger.record_trade_ticket(
        alert.id,
        telegram_user_id=789,
        reasons=[{"rule_id": "CRO-01", "passed": True}],
        valid_until=alert.expires_at,
    )
    from backend.core.database import JobRun, TicketEvent

    ledger.append(TicketEvent, ticket_id=ticket.id, action="TICKET_PLACED", telegram_user_id=789)
    ledger.append(
        JobRun,
        job="daily_scan",
        started_at=clock.now(),
        finished_at=clock.now(),
        outcome="PASS",
        counts={"alerts": 1},
        duration_ms=0,
    )
    ledger.append(
        LLMCall,
        provider="fixture",
        base_url_host="example.invalid",
        model="test-model",
        prompt_hash="e" * 64,
        input_tokens=10,
        output_tokens=20,
        est_cost_usd=Decimal("0.000123"),
        latency_ms=15,
        outcome="VALID",
    )
    ledger.append(
        SecurityEvent,
        kind="BAD_HMAC",
        telegram_user_id=999,
        detail={"reason": "fixture signature rejected"},
    )
    from backend.core.database import CashFlow
    from backend.domain.models import Side
    from backend.funding.models import Activity
    from backend.pnl.models import DayInput, build_day
    from backend.pnl.storage import record_day
    from backend.tax.models import TaxFill
    from backend.tax.storage import append_evidence

    activity = Activity(
        account_id="paper-fixture",
        env="PAPER",
        activity_id="div-fixture",
        type="DIV",
        amount=Decimal(1),
        date=clock.now().date(),
        observed_at=clock.now(),
        occurred_at=clock.now(),
        source="BROKER",
        payload_sha256="a" * 64,
    )
    ledger.append(
        CashFlow,
        account_id=activity.account_id,
        env=activity.env,
        activity_id=activity.activity_id,
        type=activity.type,
        amount=activity.amount,
        date=activity.date.isoformat(),
        payload_sha256=activity.payload_sha256,
        payload=activity.model_dump(mode="json"),
        baseline_effect="NONE",
    )
    record_day(
        ledger,
        build_day(
            DayInput(
                account_id="paper-fixture",
                env="PAPER",
                session=clock.now().date(),
                as_of=clock.now(),
                equity_start=Decimal(1000),
                equity=Decimal(1000),
                cash=Decimal(1000),
                long_market_value=Decimal(0),
                external_flows=Decimal(0),
                realized=Decimal(0),
                dividends=Decimal(0),
                interest=Decimal(0),
                fees=Decimal(0),
                source="BROKER",
                provenance_sha256="b" * 64,
            )
        ),
    )
    tax_fill = TaxFill(
        fill_id=fill.id,
        activity_id="fill-fixture",
        account_id="paper-fixture",
        env="PAPER",
        symbol="AAPL",
        side=Side.BUY,
        qty=1,
        price=Decimal("100.00"),
        fees=Decimal(0),
        ts=clock.now(),
        fee_source="BROKER",
        payload_sha256="c" * 64,
    )
    append_evidence(
        ledger,
        tax_fill.account_id,
        tax_fill.env,
        "FILL",
        tax_fill.activity_id,
        tax_fill.payload_sha256,
        tax_fill.model_dump(mode="json"),
    )
    assert fill.id is not None
    from backend.tests.test_execution_storage import append_execution_fixture

    append_execution_fixture(ledger, clock)
    with Session(ledger.engine) as session:
        result: dict[type[LedgerRecord], LedgerRecord] = {}
        for model in LEDGER_MODELS:
            record = session.scalar(select(model).order_by(model.seq).limit(1))
            assert record is not None
            result[model] = record
        return result


def test_R_02_R_04_R_05_all_tables_roundtrip_and_global_chain(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    records = _all_records(ledger, clock)
    ledger.verify_chain()
    assert records[DataSnapshot].prev_hash == GENESIS_HASH
    with Session(engine) as session:
        order = session.scalar(select(Order))
        assert order is not None
        assert order.limit_price == Decimal(100)
        assert order.created_at == clock.now()
        assert order.created_at.tzinfo is not None
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT limit_price, typeof(limit_price) FROM orders ORDER BY seq LIMIT 1")
        ).one()
        assert stored == (100_000_000, "integer")


@pytest.mark.parametrize("model", LEDGER_MODELS, ids=lambda model: model.__tablename__)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_R_02_raw_SQL_append_only_every_table(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], operation: str
) -> None:
    ledger = Ledger(engine, clock)
    _all_records(ledger, clock)
    statement = (
        f"UPDATE {model.__tablename__} SET seq = seq"
        if operation == "UPDATE"
        else f"DELETE FROM {model.__tablename__}"
    )
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.exec_driver_sql(statement)
    ledger.verify_chain()


@pytest.mark.parametrize("model", LEDGER_MODELS, ids=lambda model: model.__tablename__)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_R_02_ORM_append_only_every_table(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], operation: str
) -> None:
    ledger = Ledger(engine, clock)
    records = _all_records(ledger, clock)
    with pytest.raises(LedgerIntegrityError, match="Append-only"), transaction(engine) as session:
        record = session.get(model, records[model].id)
        assert record is not None
        if operation == "UPDATE":
            record.created_at = clock.now() - timedelta(seconds=1)
        else:
            session.delete(record)
    ledger.verify_chain()


@pytest.mark.parametrize("model", LEDGER_MODELS, ids=lambda model: model.__tablename__)
@pytest.mark.parametrize("conflict", ["id", "seq"])
def test_R_02_raw_SQL_replace_cannot_delete_immutable_rows(
    engine: Engine, clock: FrozenClock, model: type[LedgerRecord], conflict: str
) -> None:
    """R-02: SQLite REPLACE's implicit DELETE must invoke the append-only trigger."""
    ledger = Ledger(engine, clock)
    original = _all_records(ledger, clock)[model]
    values = {column.name: original.__dict__[column.name] for column in model.__table__.columns}
    if conflict == "id":
        values["seq"] = original.seq + 10_000
    else:
        values["id"] = uuid4()
    values["created_at"] = clock.now() - timedelta(seconds=1)
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(insert(model).prefix_with("OR REPLACE").values(**values))
    with Session(engine) as session:
        unchanged = session.get(model, original.id)
        assert unchanged is not None
        assert unchanged.seq == original.seq and unchanged.created_at == original.created_at
        assert unchanged.row_hash == original.row_hash
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1
    ledger.verify_chain()


@pytest.mark.parametrize(
    "fields",
    [
        {"qty": 0},
        {"qty": -1},
        {"qty": Decimal("1.5")},
        {"qty": True},
        {"limit_price": Decimal(0)},
        {"side": "SHORT"},
        {"order_type": "MARKET"},
        {"stop_price": None},
        {"stop_price": Decimal(100)},
        {"signal_id": uuid4()},
        {"signal_id": None},
        {"source": "SYSTEM"},
    ],
)
def test_R_01_R_02_constraints_reject_bad_order(
    engine: Engine, clock: FrozenClock, fields: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(SafetyError):
        _order(ledger, clock, **fields)
    ledger.verify_chain()
    with Session(engine) as session:
        assert session.scalar(select(Order)) is None


def test_R_02_order_unique_client_id_and_proposal_FK(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    first = _order(ledger, clock)
    with pytest.raises(SafetyError):
        _order(ledger, clock, client_order_id=first.client_order_id)
    with pytest.raises(SafetyError):
        ledger.append(
            RiskDecision,
            proposal_id=uuid4(),
            decision="APPROVED",
            config_hash="a" * 64,
            snapshot_hash="b" * 64,
            evaluated_at=clock.now(),
        )
    ledger.verify_chain()


def test_R_02_corrupt_row_detected_and_halt_survives_restart(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    _snapshot(ledger, clock)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_data_snapshots_update")
        connection.exec_driver_sql("UPDATE data_snapshots SET symbol = 'CORRUPTED'")
    create_schema(engine)
    with pytest.raises(LedgerIntegrityError, match="HALTED"):
        ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
    with pytest.raises(LedgerIntegrityError):
        Ledger(engine, clock).verify_chain()


def test_R_02_mutable_control_cannot_clear_halt(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    with transaction(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None
        control.state = "HALTED"
        control.version += 1
        ledger.append_in_session(
            session,
            SystemEvent,
            state="HALTED",
            reason="fixture",
            operator_id=None,
            event_type="ESCALATE",
        )
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE system_control SET state = 'RUNNING'")
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
    ledger.verify_chain()


def test_R_02_lifecycle_and_readonly_fill_recording(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    order = _submitted(ledger, clock)
    for index in (1, 2):
        ledger.record_fill(
            order.id,
            broker_fill_id=f"fill-{index}",
            qty=1,
            price=Decimal(99),
            filled_at=clock.now(),
        )
    ledger.verify_chain()
    with Session(engine) as session:
        states = list(session.scalars(select(OrderEvent.state).order_by(OrderEvent.seq)))
    assert states == ["PROPOSED", "APPROVED", "SUBMITTED", "PARTIALLY_FILLED", "FILLED"]
    with pytest.raises(LedgerIntegrityError):
        ledger.append(
            OrderEvent,
            order_id=order.id,
            state="APPROVED",
            reason="bad",
            broker_order_id=None,
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"qty": 3},
        {"qty": 0},
        {"qty": True},
        {"price": Decimal(101)},
        {"price": Decimal("NaN")},
        {"filled_at": datetime(2099, 1, 1, tzinfo=UTC)},
        {"filled_at": datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)},
        {"order_id": uuid4()},
    ],
)
def test_R_02_bad_observed_fill_halts(
    engine: Engine, clock: FrozenClock, fields: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    order = _submitted(ledger, clock)
    values: dict[str, Any] = {
        "order_id": order.id,
        "broker_fill_id": "bad-fill",
        "qty": 1,
        "price": Decimal(99),
        "filled_at": clock.now(),
    }
    values.update(fields)
    with pytest.raises(ReconciliationError):
        ledger.record_fill(**values)
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
        assert session.scalar(select(Fill)) is None
    ledger.verify_chain()


def test_R_02_raw_invalid_transition_detected_even_with_recomputed_hash(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    _order(ledger, clock)
    with Session(engine) as session:
        record = session.scalar(select(OrderEvent))
        assert record is not None
        session.expunge(record)
    record.state = "SUBMITTED"
    new_hash = row_digest(record)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_order_events_update")
        connection.execute(
            text("UPDATE order_events SET state = 'SUBMITTED', row_hash = :hash"),
            {"hash": new_hash},
        )
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()


@pytest.mark.parametrize(
    "broker,local",
    [
        ({"AAPL": 1}, {"AAPL": 2}),
        ({"AAPL": -1}, {}),
        ({"AAPL": True}, {}),
        ({"AAPL": Decimal("1.5")}, {}),
        ({"": 1}, {}),
    ],
)
def test_R_01_R_02_reconciliation_break_persists_halt(
    engine: Engine, clock: FrozenClock, broker: dict[str, Any], local: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(ReconciliationError):
        ledger.reconcile(broker, local)
    ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"


def test_R_01_R_02_matching_reconciliation_accepts_zero_absence(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    ledger.reconcile({"AAPL": 2, "MSFT": 0}, {"AAPL": 2})
    ledger.verify_chain()


def test_R_02_concurrent_appends_have_one_global_sequence(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)

    def append_one(index: int) -> UUID:
        record = ledger.append(
            ConfigSnapshot, config_hash=f"{index:064x}", settings={"index": index}
        )
        return record.id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(append_one, range(20)))
    assert len(set(ids)) == 20
    ledger.verify_chain()
    with Session(engine) as session:
        assert list(
            session.scalars(select(ConfigSnapshot.seq).order_by(ConfigSnapshot.seq))
        ) == list(range(1, 21))


@pytest.mark.parametrize("settings", [{"limit": 0.1}, {"broker_secret": "sensitive"}])
def test_R_04_R_07_ledger_rejects_float_and_secrets(
    engine: Engine, clock: FrozenClock, settings: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(DataIntegrityError):
        ledger.append(ConfigSnapshot, config_hash="a" * 64, settings=settings)
    ledger.verify_chain()


def test_R_02_allocation_corruption_halts(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    _snapshot(ledger, clock)
    with transaction(engine) as session:
        allocation = session.get(AppendControl, 1)
        assert allocation is not None
        allocation.next_seq = 10
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"


def _portfolio(ledger: Ledger, clock: FrozenClock, **changes: Any) -> PortfolioState:
    fields: dict[str, Any] = {
        "account_id": "paper-account",
        "account_type": "CASH",
        "as_of": clock.now(),
        "equity": Decimal("100"),
        "cash": Decimal("100"),
        "settled_cash": Decimal("60"),
        "positions": {},
        "high_water_mark": Decimal("120"),
        "day_start_equity": Decimal("110"),
    }
    fields.update(changes)
    return ledger.append(PortfolioState, **fields)


@pytest.mark.parametrize(
    "amount,high,day,settled",
    [
        (Decimal("50"), Decimal("180"), Decimal("165"), Decimal("60")),
        (Decimal("-30"), Decimal("84"), Decimal("77"), Decimal("30")),
        (Decimal("-80"), Decimal("24"), Decimal("22"), Decimal("0")),
    ],
)
def test_CRO_09_CRO_10_R_08_cash_flow_scales_both_marks_without_changing_loss(
    engine: Engine,
    clock: FrozenClock,
    amount: Decimal,
    high: Decimal,
    day: Decimal,
    settled: Decimal,
) -> None:
    ledger = Ledger(engine, clock)
    prior = _portfolio(ledger, clock)
    current = ledger.record_cash_flow("paper-account", amount, clock.now(), Decimal("100"))
    assert current.high_water_mark == high
    assert current.day_start_equity == day
    assert current.settled_cash == settled
    assert current.equity == current.cash == Decimal("100") + amount
    assert current.equity * prior.high_water_mark == prior.equity * current.high_water_mark
    assert current.equity * prior.day_start_equity == prior.equity * current.day_start_equity
    assert current.cash_flow_amount == amount and current.cash_flow_at == clock.now()
    ledger.verify_chain()


def test_CRO_09_CRO_10_cash_flow_rational_marks_round_conservatively_up(
    engine: Engine,
    clock: FrozenClock,
) -> None:
    ledger = Ledger(engine, clock)
    _portfolio(
        ledger,
        clock,
        equity=Decimal("3"),
        cash=Decimal("3"),
        settled_cash=Decimal("1"),
        high_water_mark=Decimal("10"),
        day_start_equity=Decimal("7"),
    )
    current = ledger.record_cash_flow("paper-account", Decimal("1"), clock.now(), Decimal("3"))
    assert current.high_water_mark == Decimal("13.333334")
    assert current.day_start_equity == Decimal("9.333334")
    ledger.verify_chain()


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "missing"},
        {"equity_before": Decimal("0")},
        {"equity_before": Decimal("99")},
        {"amount": Decimal("-100")},
        {"amount": Decimal("NaN")},
        {"amount": "1"},
        {"ts": datetime(2099, 1, 1, tzinfo=UTC)},
        {"ts": datetime(2020, 1, 1, tzinfo=UTC)},
    ],
)
def test_CRO_09_R_02_unverifiable_cash_flow_halts(
    engine: Engine,
    clock: FrozenClock,
    changes: dict[str, Any],
) -> None:
    ledger = Ledger(engine, clock)
    _portfolio(ledger, clock)
    fields: dict[str, Any] = {
        "account_id": "paper-account",
        "amount": Decimal("1"),
        "ts": clock.now(),
        "equity_before": Decimal("100"),
    }
    fields.update(changes)
    with pytest.raises(ReconciliationError):
        ledger.record_cash_flow(**fields)
    ledger.verify_chain()
    with Session(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"


def test_R_07_snapshot_permits_token_path_metadata_but_rejects_nested_credentials(
    engine: Engine,
    clock: FrozenClock,
) -> None:
    ledger = Ledger(engine, clock)
    ledger.append(
        ConfigSnapshot,
        config_hash="a" * 64,
        settings={
            "plaid_token_path": "C:/private/token.enc",
            "database_identity": {"driver": "sqlite"},
        },
    )
    with pytest.raises(DataIntegrityError):
        ledger.append(
            ConfigSnapshot, config_hash="b" * 64, settings={"broker": {"password": "secret"}}
        )
    ledger.verify_chain()


def test_R_02_INITIALIZED_cannot_deescalate_or_repeat(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    with transaction(engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None
        control.state = "HALTED"
        control.version = 1
        ledger.append_in_session(
            session,
            SystemEvent,
            state="HALTED",
            reason="fixture",
            event_type="ESCALATE",
            operator_id=None,
        )
    for state in ("RUNNING", "HALTED"):
        with pytest.raises(LedgerIntegrityError):
            ledger.append(
                SystemEvent,
                state=state,
                reason="invalid initializer",
                event_type="INITIALIZED",
                operator_id=None,
            )
    ledger.verify_chain()
