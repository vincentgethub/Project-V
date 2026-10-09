"""AX-26/31: truthful stop fills, immutable intent identity and no overselling."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import (
    Alert,
    AlertEvent,
    AutoJobRun,
    ExecutionOrderRecord,
    Order,
    OrderEvent,
    ResearchReport,
    SecurityEvent,
)
from backend.core.errors import LedgerIntegrityError, ReconciliationError
from backend.core.ledger import Ledger
from backend.domain.models import RuleResult, Severity
from backend.execution.models import BindingEvidence, BrokerOrder, EntryApprovalEvidence
from backend.execution.storage import held_quantity


def append_execution_fixture(
    ledger: Ledger, clock: FrozenClock
) -> tuple[Order, ExecutionOrderRecord, ExecutionOrderRecord]:
    from backend.tests.test_ledger import _order

    proposal_id = uuid4()
    order = _order(
        ledger,
        clock,
        proposal_id=proposal_id,
        client_order_id="vws-" + proposal_id.hex,
        qty=4,
        target_price=Decimal(105),
    )
    alert = ledger.append(
        Alert,
        proposal_id=order.proposal_id,
        signal_id=order.signal_id,
        symbol=order.symbol,
        playbook="BASE_BREAKOUT",
        score=Decimal("8.50"),
        card_text="auto fixture",
        config_hash="a" * 64,
        expires_at=clock.now() + timedelta(hours=1),
    )
    ledger.append(
        ResearchReport,
        alert_id=alert.id,
        agent_name="desk_policy",
        status="OK",
        payload={"yaml_hash": "b" * 64},
    )
    ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=123,
        telegram_message_id=456,
        reason="fixture delivery",
    )
    evidence = EntryApprovalEvidence(
        proposal_id=proposal_id,
        alert_id=alert.id,
        account_id=order.account_id,
        environment="PAPER",
        actor="auto",
        config_hash="a" * 64,
        yaml_hash="b" * 64,
        snapshot_hash="c" * 64,
        compliance_input_hash="d" * 64,
        qty=2,
        checked_at=clock.now(),
        risk_results=tuple(
            RuleResult(
                rule_id=f"CRO-{n:02d}",
                passed=True,
                severity=Severity.BLOCK,
                observed="fixture",
                limit="fixture",
                message="fixture",
            )
            for n in range(1, 14)
        ),
        compliance_results=tuple(
            RuleResult(
                rule_id=f"CMP-{n:02d}",
                passed=True,
                severity=Severity.BLOCK,
                observed="fixture",
                limit="fixture",
                message="fixture",
            )
            for n in range(1, 8)
        ),
    )
    ledger.append(
        SecurityEvent, kind="AUTO_ENTRY_APPROVAL", detail=evidence.model_dump(mode="json")
    )
    ledger.append(
        OrderEvent,
        order_id=order.id,
        state="APPROVED",
        reason="AUTO_APPROVED fixture",
        broker_order_id=None,
    )
    instruction = ledger.append(
        ExecutionOrderRecord,
        order_id=order.id,
        parent_execution_id=None,
        client_order_id=order.client_order_id,
        account_id=order.account_id,
        environment="PAPER",
        symbol="AAPL",
        role="ENTRY",
        side="BUY",
        order_type="LIMIT",
        qty=2,
        limit_price=Decimal(100),
        stop_price=Decimal(95),
        target_price=Decimal(105),
        time_in_force="GTC",
        config_hash="a" * 64,
        valid_until=clock.now() + timedelta(hours=1),
    )
    parent_id = uuid4()
    stop = BrokerOrder(
        order_id=uuid4(),
        client_order_id="broker-generated-child-" + uuid4().hex,
        symbol="AAPL",
        side="sell",
        order_type="stop",
        order_class="simple",
        time_in_force="gtc",
        qty=2,
        filled_qty=0,
        status="new",
        stop_price=Decimal(95),
        submitted_at=clock.now(),
        parent_id=parent_id,
    )
    broker = BrokerOrder(
        order_id=parent_id,
        client_order_id=order.client_order_id,
        symbol="AAPL",
        side="buy",
        order_type="limit",
        order_class="bracket",
        time_in_force="gtc",
        qty=2,
        filled_qty=0,
        status="new",
        limit_price=Decimal(100),
        submitted_at=clock.now(),
        legs=(stop,),
    )
    ledger.append(
        SecurityEvent,
        kind="EXECUTION_ORDER_OBSERVED",
        detail=BindingEvidence(
            execution_order_id=instruction.id, broker_order=broker, observed_at=clock.now()
        ).model_dump(mode="json"),
    )
    ledger.append(
        OrderEvent,
        order_id=order.id,
        state="SUBMITTED",
        reason="fixture broker accepted",
        broker_order_id=str(parent_id),
    )
    ledger.record_fill(
        order.id,
        execution_order_id=instruction.id,
        broker_fill_id="auto-buy-" + uuid4().hex,
        qty=2,
        price=Decimal(99),
        filled_at=clock.now(),
    )
    child = ledger.append(
        ExecutionOrderRecord,
        order_id=order.id,
        parent_execution_id=instruction.id,
        client_order_id=stop.client_order_id,
        account_id=order.account_id,
        environment="PAPER",
        symbol="AAPL",
        role="STOP",
        side="SELL",
        order_type="STOP",
        qty=2,
        limit_price=None,
        stop_price=Decimal(95),
        target_price=None,
        time_in_force="GTC",
        config_hash="a" * 64,
        valid_until=None,
    )
    ledger.append(
        SecurityEvent,
        kind="EXECUTION_ORDER_OBSERVED",
        detail=BindingEvidence(
            execution_order_id=child.id, broker_order=stop, observed_at=clock.now()
        ).model_dump(mode="json"),
    )
    ledger.record_fill(
        order.id,
        execution_order_id=child.id,
        broker_fill_id="auto-stop-" + uuid4().hex,
        qty=1,
        price=Decimal(80),
        filled_at=clock.now(),
    )
    ledger.append(
        AutoJobRun,
        job="auto_entry",
        account_id=order.account_id,
        environment="PAPER",
        config_hash="a" * 64,
        started_at=clock.now(),
        finished_at=clock.now(),
        duration_ms=0,
        outcome="PASS",
        counts={"entries": 1},
    )
    return order, instruction, child


def test_AX_26_stop_market_gap_is_recorded_truthfully_and_ramp_qty_binds(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    order, entry, child = append_execution_fixture(ledger, clock)
    ledger.verify_chain()
    with Session(engine) as session:
        assert held_quantity(session, entry.id) == 1
        latest = session.scalar(
            select(OrderEvent)
            .where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.seq.desc())
        )
        assert latest is not None and latest.state == "FILLED"
    assert child.order_type == "STOP" and child.limit_price is None
    ledger.record_fill(
        order.id,
        execution_order_id=child.id,
        broker_fill_id="stop-final",
        qty=1,
        price=Decimal(79),
        filled_at=clock.now(),
    )
    ledger.verify_chain()
    with Session(engine) as session:
        assert held_quantity(session, entry.id) == 0
    with pytest.raises(ReconciliationError):
        ledger.record_fill(
            order.id,
            execution_order_id=child.id,
            broker_fill_id="would-short",
            qty=1,
            price=Decimal(78),
            filled_at=clock.now(),
        )
    ledger.verify_chain()


def test_AX_16_unknown_generated_child_cannot_claim_a_managed_parent(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    order, entry, _ = append_execution_fixture(ledger, clock)
    with pytest.raises(LedgerIntegrityError, match="nested parent"):
        ledger.append(
            ExecutionOrderRecord,
            order_id=order.id,
            parent_execution_id=entry.id,
            client_order_id="unbound-non-vws",
            account_id=order.account_id,
            environment="PAPER",
            symbol="AAPL",
            role="STOP",
            side="SELL",
            order_type="STOP",
            qty=1,
            limit_price=None,
            stop_price=Decimal(95),
            target_price=None,
            time_in_force="GTC",
            config_hash="a" * 64,
            valid_until=None,
        )
    ledger.verify_chain()
