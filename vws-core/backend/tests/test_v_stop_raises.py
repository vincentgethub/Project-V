"""EX-05: deterministic protective raises, bounded cancellation and recovery."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionOrderRecord, SecurityEvent
from backend.core.errors import DataIntegrityError, ReconciliationError
from backend.core.system_state import SystemState
from backend.data.fill_polling import ObservedFill
from backend.domain.models import Side
from backend.execution.alpaca_executor import AlpacaExecutor
from backend.execution.exit_variants import (
    HeldEntry,
    HeldExitObservation,
    StopMoved,
    stop_raise_plan,
)
from backend.execution.stop_evidence import current_stop
from backend.execution.stop_readiness import CancelSemanticsProof, verify_cancel_semantics
from backend.notifications.callbacks import FreshInputs
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_auto_exits import refresh_quotes
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from backend.tests.test_v_execution import variant
from backend.tests.test_v_held_exits import calendar as calendar_fixture
from backend.tests.test_v_held_exits import held, tape

harness = make_research_harness
calendar = calendar_fixture
D = Decimal


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_06_integration_publisher_reads_real_bound_shapes_without_order_writes(
    harness: Harness,
) -> None:
    h = harness
    ex, client, b = await entered(h)
    with Session(h.state.engine) as session:
        a = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.role == "ENTRY", ExecutionOrderRecord.id != b.id
            )
        )
        assert a is not None and a.stop_price is not None and a.limit_price is not None
    inputs = await ex._fresh_exit_inputs(a)
    observed = await ex._held_observation(a, inputs)
    observed = HeldExitObservation.model_validate(
        {**observed.model_dump(), "close": a.stop_price + D(7)}
    )
    plan = stop_raise_plan(
        ex._held_entry(a),
        observed,
        ex.calendar,
        h.clock.now(),
        raise_id=uuid4(),
        qty=a.qty,
        old_stop=a.stop_price,
        last_trade=inputs.market.last_price,
        quote_at=inputs.market.last_price_ts,
        stale_quote_seconds=h.settings.stale_quote_seconds,
        trail_atr_mult=D(3),
        config_hash=h.settings.config_hash,
        yaml_hash=h.config.config_hash,
    )
    assert plan is not None
    h.state.ledger.append(
        SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
    )
    await ex._cancel_sells(a, deadline_seconds=10)
    await ex._repair_stop(a, a.qty, approval=plan)
    ex._stop_moved(plan, "APPLIED", plan.new_stop)
    with Session(h.state.engine) as session:
        oco = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.role == "REPAIR", ExecutionOrderRecord.order_type == "LIMIT"
            )
        )
        oto_stop = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.parent_execution_id == b.id,
                ExecutionOrderRecord.role == "STOP",
            )
        )
        assert oco is not None and oto_stop is not None
    oco_broker, oto_broker = await ex._read_bound(oco), await ex._read_bound(oto_stop)
    assert oco_broker is not None and oto_broker is not None
    assert (await ex._cancel_confirmed(oco, oco_broker)).status == "canceled"
    assert (await ex._cancel_confirmed(oto_stop, oto_broker)).status == "canceled"
    await ex._ensure_stop(a, a.qty)
    await ex._ensure_stop(b, b.qty)
    posts = len(client.posts)
    await ex.record_paper_cancel_semantics(b.id, oco.id)
    assert len(client.posts) == posts
    with Session(h.state.engine) as session:
        event = session.scalar(
            select(SecurityEvent).where(SecurityEvent.kind == "PAPER_CANCEL_SEMANTICS")
        )
        assert event is not None
        proof = CancelSemanticsProof.recorded(event.detail)
        verify_cancel_semantics(session, proof, before_seq=event.seq)
    h.state.ledger.verify_chain()


@pytest.mark.parametrize("minute", [0, 29, 30, 359, 360, 389])
def test_EX_05_regular_hours_and_half_ATR_boundary(calendar: Any, minute: int) -> None:
    entry = held(calendar)
    day = tape(calendar).sessions[-1]
    now = calendar.session_open(calendar.add_sessions(day, 1)) + timedelta(minutes=minute)
    observation = HeldExitObservation(
        entry=entry,
        session=day,
        known_at=calendar.session_close(day) + timedelta(minutes=30),
        history_sha256="a" * 64,
        close=D("107.01"),
        atr14=D(2),
        ema20=None,
        verified_peak=None,
    )
    arguments = dict(
        raise_id=uuid4(),
        qty=entry.filled_qty,
        old_stop=D(95),
        last_trade=D("102.01"),
        quote_at=now,
        stale_quote_seconds=60,
        trail_atr_mult=D(3),
        config_hash="b" * 64,
        yaml_hash="c" * 64,
    )
    plan = stop_raise_plan(entry, observation, calendar, now, **arguments)
    assert (plan is not None) is (30 <= minute < 360)
    if plan is not None:
        assert plan.new_stop == D("101.01")
        arguments["last_trade"] = D("102.00")
        assert stop_raise_plan(entry, observation, calendar, now, **arguments) is None
        arguments["quote_at"] = now - timedelta(seconds=61)
        with pytest.raises(DataIntegrityError, match="fresh quote"):
            stop_raise_plan(entry, observation, calendar, now, **arguments)


RaiseClient = FakeTradingClient


async def entered(h: Harness) -> tuple[AlpacaExecutor, RaiseClient, ExecutionOrderRecord]:
    variant(h, "SPLIT_1R_TRAIL")
    alert = await deliver(h)
    client = RaiseClient(h)
    ex = executor(h, client)

    async def observation(entry: HeldEntry, fresh: FreshInputs) -> HeldExitObservation:
        day = ex.calendar.last_completed_session(h.clock.now() - timedelta(minutes=30))
        return HeldExitObservation(
            entry=entry,
            session=day,
            known_at=ex.calendar.session_close(day) + timedelta(minutes=30),
            history_sha256="a" * 64,
            close=entry.initial_stop + D(10),
            atr14=D(2),
            ema20=None,
            verified_peak=None,
        )

    ex.held_exit_observation = observation
    await ex.enter(alert.proposal_id)
    buys = tuple(client.orders.values())
    total = sum(int(raw["qty"]) for raw in buys)
    for raw in buys:
        raw["status"], raw["filled_qty"] = "filled", raw["qty"]
        for child in raw["legs"]:
            child["status"] = "new"
    client.positions = [
        {"symbol": buys[0]["symbol"], "qty": str(total), "side": "long", "asset_class": "us_equity"}
    ]
    await ex.prepare_fills((buys[0]["symbol"],))
    for raw in buys:
        ex.observe_fill(
            ObservedFill(
                account_id="offline-paper",
                broker_fill_id="buy-" + uuid4().hex,
                broker_order_id=UUID(raw["id"]),
                symbol=raw["symbol"],
                side=Side.BUY,
                qty=int(raw["qty"]),
                price=D(raw["limit_price"]) - D("0.01"),
                filled_at=h.clock.now(),
            )
        )
    with Session(h.state.engine) as session:
        b = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.client_order_id == buys[1]["client_order_id"]
            )
        )
        assert b is not None and b.stop_price is not None
    next_day = ex.calendar.add_sessions(h.clock.now().date(), 1)
    h.clock.current = ex.calendar.session_open(next_day) + timedelta(minutes=35)
    refresh_quotes(h)
    h.source.inputs = FreshInputs.model_validate(
        h.source.inputs.model_copy(
            update={
                "market": h.source.inputs.market.model_copy(
                    update={"last_price": b.stop_price + D(8)}
                ),
            }
        )
    )
    return ex, client, b


async def target_filled(h: Harness, ex: AlpacaExecutor, client: RaiseClient) -> None:
    a = next(raw for raw in client.orders.values() if raw["client_order_id"].endswith("-a"))
    target = next(row for row in a["legs"] if row["type"] == "limit")
    target["status"], target["filled_qty"] = "filled", target["qty"]
    for row in a["legs"]:
        if row["type"] == "stop":
            row["status"] = "canceled"
    client.positions[0]["qty"] = str(int(client.positions[0]["qty"]) - int(target["qty"]))
    with Session(h.state.engine) as session:
        intent = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.client_order_id == target["client_order_id"]
            )
        )
        assert intent is not None
    await ex._read_bound(intent)
    ex.observe_fill(
        ObservedFill(
            account_id="offline-paper",
            broker_fill_id="target-" + uuid4().hex,
            broker_order_id=UUID(target["id"]),
            symbol=target["symbol"],
            side=Side.SELL,
            qty=int(target["qty"]),
            price=D(target["limit_price"]),
            filled_at=h.clock.now(),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "accepted-timeout",
        "reject-once",
        "reject-both",
        "ambiguous-missing",
        "cancel",
        "manual",
    ],
)
async def test_EX_05_raise_recovery_never_lowers_or_blindly_retries(
    harness: Harness, fault: str | None
) -> None:
    h = harness
    ex, client, b = await entered(h)
    assert b.stop_price is not None
    await ex.monitor()
    assert len(client.posts) == 2, "A entry fill alone cannot arm B's trail"
    await target_filled(h, ex, client)
    client.raise_fault = None if fault == "manual" else fault
    if fault == "manual":
        ex.modes.downgrade("MANUAL", actor="offline owner")
    if fault in {"reject-both", "ambiguous-missing", "cancel"}:
        with pytest.raises(ReconciliationError):
            await ex.monitor()
    else:
        await ex.monitor()
    with Session(h.state.engine) as session:
        rows = tuple(
            session.scalars(select(SecurityEvent).where(SecurityEvent.kind == "STOP_MOVED"))
        )
        if fault == "manual":
            assert not rows and len(client.posts) == 2
            assert (
                session.scalar(
                    select(SecurityEvent).where(SecurityEvent.kind == "STOP_RAISE_SUGGESTED")
                )
                is not None
            )
        else:
            assert len(rows) == 1
            moved = StopMoved.recorded(rows[0].detail)
            assert moved.approval.qty == b.qty and moved.approval.new_stop == b.stop_price + D(4)
            expected = (
                "REPAIRED"
                if fault == "reject-once"
                else "FAILED"
                if fault in {"reject-both", "ambiguous-missing"}
                else "CANCEL_UNCONFIRMED"
                if fault == "cancel"
                else "APPLIED"
            )
            assert moved.status == expected
            assert current_stop(session, b) == (
                b.stop_price + D(4) if expected == "APPLIED" else b.stop_price
            )
            assert len(client.posts) == (
                4 if fault in {"reject-once", "reject-both"} else 2 if fault == "cancel" else 3
            )
    if fault in {"reject-both", "ambiguous-missing", "cancel"}:
        assert h.state.current() == SystemState.HALTED
    elif fault == "reject-once":
        # Approved journaled fallback restores the old stop, closes the repair,
        # and releases only its own entry pause after broker confirmation.
        assert h.state.current() == SystemState.RUNNING
        assert ex._protection_repairs() == () and ex.modes.entries_enabled
    if fault in {None, "accepted-timeout", "reject-once"}:
        await ex.monitor()
        assert len(client.posts) == (4 if fault == "reject-once" else 3)
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_OCO_replacement_binds_one_target_and_one_proved_stop(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    ex = executor(h, client)
    await ex.enter(alert.proposal_id)
    await fill_entry(h, client, ex)
    with Session(h.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
        assert entry is not None and entry.stop_price is not None and entry.limit_price is not None
    h.clock.current = ex.calendar.session_open(
        ex.calendar.add_sessions(h.clock.now().date(), 1)
    ) + timedelta(minutes=35)
    refresh_quotes(h)
    held_entry = ex._held_entry(entry)
    day = ex.calendar.previous_sessions(h.clock.now().date(), 1)[0]
    observed = HeldExitObservation(
        entry=held_entry,
        session=day,
        known_at=ex.calendar.session_close(day) + timedelta(minutes=30),
        history_sha256="a" * 64,
        close=entry.stop_price + D(7),
        atr14=D(2),
        ema20=None,
        verified_peak=None,
    )
    plan = stop_raise_plan(
        held_entry,
        observed,
        ex.calendar,
        h.clock.now(),
        raise_id=uuid4(),
        qty=entry.qty,
        old_stop=entry.stop_price,
        last_trade=entry.limit_price,
        quote_at=h.clock.now(),
        stale_quote_seconds=h.settings.stale_quote_seconds,
        trail_atr_mult=D(3),
        config_hash=h.settings.config_hash,
        yaml_hash=h.config.config_hash,
    )
    assert plan is not None
    h.state.ledger.append(
        SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
    )
    await ex._cancel_sells(entry, deadline_seconds=10)
    broker = await ex._repair_stop(entry, entry.qty, approval=plan)
    ex._stop_moved(plan, "APPLIED", plan.new_stop)
    assert broker.order_class == "oco" and len(broker.legs) == 1
    assert client.posts[-1]["take_profit"]["limit_price"] == f"{entry.target_price:.2f}"
    assert "limit_price" not in client.posts[-1]
    assert broker.legs[0].stop_price == plan.new_stop and broker.qty == entry.qty
    await ex.monitor()
    assert len(client.posts) == 2
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_restart_finishes_confirmed_raise_before_protection_check(
    harness: Harness,
) -> None:
    h = harness
    ex, client, b = await entered(h)
    assert b.stop_price is not None
    await target_filled(h, ex, client)
    inputs = await ex._fresh_exit_inputs(b)
    plan = stop_raise_plan(
        ex._held_entry(b),
        await ex._held_observation(b, inputs),
        ex.calendar,
        h.clock.now(),
        raise_id=uuid4(),
        qty=b.qty,
        old_stop=b.stop_price,
        last_trade=inputs.market.last_price,
        quote_at=inputs.market.last_price_ts,
        stale_quote_seconds=h.settings.stale_quote_seconds,
        trail_atr_mult=D(3),
        config_hash=h.settings.config_hash,
        yaml_hash=h.config.config_hash,
    )
    assert plan is not None
    h.state.ledger.append(
        SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
    )
    await ex._cancel_sells(b, deadline_seconds=10)
    await ex._repair_stop(b, b.qty, approval=plan)
    # Simulated process loss after broker acceptance, before STOP_MOVED.
    restarted = executor(h, client)
    restarted.held_exit_observation = ex.held_exit_observation
    await restarted.monitor()
    assert len(client.posts) == 3
    with Session(h.state.engine) as session:
        assert current_stop(session, b) == plan.new_stop
        events = tuple(
            session.scalars(select(SecurityEvent).where(SecurityEvent.kind == "STOP_MOVED"))
        )
        assert len(events) == 1 and StopMoved.recorded(events[0].detail).status == "APPLIED"
    h.state.ledger.verify_chain()
