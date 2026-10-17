"""AX-30/31: entry faults preserve only independently provable held protection."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from backend.core.errors import ExecutionDisabledError, ProviderError, ReconciliationError
from backend.core.system_state import SystemState
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "elapsed_ms,exceeded", [(0, False), (30000, False), (30001, True), (86401002, True)]
)
async def test_EX_05_stop_window_audit_preserves_exact_elapsed_time(
    harness: Harness, elapsed_ms: int, exceeded: bool
) -> None:
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import StopMoved, stop_raise_plan
    from backend.tests.test_v_stop_raises import entered

    h = harness
    built, client, entry = await entered(h)
    assert entry.stop_price is not None
    inputs = await built._fresh_exit_inputs(entry)
    plan = stop_raise_plan(
        built._held_entry(entry),
        await built._held_observation(entry, inputs),
        built.calendar,
        h.clock.now(),
        raise_id=uuid4(),
        qty=entry.qty,
        old_stop=entry.stop_price,
        last_trade=inputs.market.last_price,
        quote_at=inputs.market.last_price_ts,
        stale_quote_seconds=h.settings.stale_quote_seconds,
        trail_atr_mult=Decimal(3),
        config_hash=h.settings.config_hash,
        yaml_hash=h.config.config_hash,
    )
    assert plan is not None
    h.state.ledger.append(
        SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
    )
    h.clock.current += timedelta(milliseconds=elapsed_ms)
    built._stop_moved(plan, "FAILED", None)
    with Session(h.state.engine) as session:
        events = tuple(
            session.scalars(select(SecurityEvent).where(SecurityEvent.kind == "STOP_MOVED"))
        )
        alarms = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "STOP_WINDOW_EXCEEDED")
            )
        )
    assert len(events) == 1
    moved = StopMoved.recorded(events[0].detail)
    assert moved.approval == plan and moved.status == "FAILED" and moved.confirmed_stop is None
    assert moved.completed_at == h.clock.now() and moved.window_ms == elapsed_ms
    assert [row.detail for row in alarms] == (
        [
            {
                "raise_id": str(plan.raise_id),
                "account_id": "offline-paper",
                "environment": "PAPER",
                "window_ms": elapsed_ms,
            }
        ]
        if exceeded
        else []
    )
    assert len(client.posts) == 2
    h.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", [None, "lost_response", "unconfirmed"])
async def test_AX_24_cancellation_never_repeats_delete_or_guesses_protection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord, SecurityEvent
    from backend.execution.alpaca_executor import parse_order

    h = harness
    alert = await deliver(h)
    deletes: list[object] = []

    class CancelPaperBroker(FakeTradingClient):
        def cancel_order_by_id(self, order_id: Any) -> None:
            deletes.append(order_id)
            if fault != "unconfirmed":
                row = next(row for row in self.orders.values() if row["id"] == str(order_id))
                row["status"] = "canceled"
                for child in row["legs"] or ():
                    child["status"] = "canceled"
            if fault:
                raise TimeoutError("Paper cancellation response unavailable")

    client = CancelPaperBroker(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    with Session(h.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
    assert entry is not None
    raw = client.orders[entry.client_order_id]
    broker = parse_order(raw)
    reads: list[object] = []
    delays: list[float] = []
    get = client.get_order_by_id

    def read(identity: Any, filter: object = None) -> Any:
        reads.append(identity)
        return get(identity, filter)

    async def delay(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(client, "get_order_by_id", read)
    monkeypatch.setattr(asyncio, "sleep", delay)
    if fault == "unconfirmed":
        with pytest.raises(ProviderError) as caught:
            await built._cancel_confirmed(entry, broker)
        assert type(caught.value) is ProviderError
        assert str(caught.value) == "Cancellation is unconfirmed; no replacement or retry"
        assert reads == [broker.order_id] * 3 and delays == [0.2, 0.2]
    else:
        cancelled = await built._cancel_confirmed(entry, broker)
        assert cancelled.status == "canceled" and cancelled.filled_qty == 0
        assert await built._cancel_confirmed(entry, cancelled) == cancelled
        assert reads == [broker.order_id] and delays == []
    assert deletes == [broker.order_id] and len(client.posts) == 1
    with Session(h.state.engine) as session:
        events = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_CANCEL_AMBIGUOUS")
            )
        )
    assert [row.detail for row in events] == (
        []
        if fault is None
        else [
            {
                "account_id": "offline-paper",
                "environment": "PAPER",
                "execution_order_id": str(entry.id),
                "error_type": "TimeoutError",
            }
        ]
    )
    h.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "account_id",
        "environment",
        "config_hash",
        "doctor_fully_green",
        "watchdog_enabled",
        "backup_chain_verified",
        "backup_old",
        "backup_future",
        "telegram_old",
        "telegram_future",
        "clock_old",
        "clock_future",
    ],
)
async def test_AX_11_prerequisite_faults_refuse_before_any_paper_order(
    harness: Harness, fault: str
) -> None:
    from datetime import timedelta

    h = harness
    client = FakeTradingClient(h)
    built = executor(h, client)
    updates: dict[str, Any] = {
        "account_id": "other-paper-account",
        "environment": "LIVE",
        "config_hash": "0" * 64,
        "doctor_fully_green": False,
        "watchdog_enabled": False,
        "backup_chain_verified": False,
    }
    if fault.endswith(("_old", "_future")):
        category, age = fault.split("_")
        field = category + "_verified_at"
        delta = timedelta(hours=26) if category == "backup" else timedelta(minutes=5, seconds=1)
        updates = {
            field: h.clock.now() - delta
            if age == "old"
            else h.clock.now() + timedelta(microseconds=1)
        }
    else:
        updates = {fault: updates[fault]}
    built.prerequisites = built.prerequisites.model_copy(update=updates)
    with pytest.raises(ExecutionDisabledError) as caught:
        built._assert_ops()
    assert type(caught.value) is ExecutionDisabledError
    assert (
        str(caught.value) == "AUTO prerequisites are unverified, stale or bound to another account"
    )
    assert built.environment == "PAPER" and client.posts == [] and client.lookups == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other-paper"),
        ("status", "ACCOUNT_UPDATED"),
        ("currency", "CAD"),
        ("trading_blocked", True),
        ("account_blocked", True),
        ("trade_suspended_by_user", True),
        ("trading_blocked", 0),
        ("account_blocked", None),
    ],
)
async def test_AX_15_account_get_never_authorizes_ambiguous_restrictions(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    raw = client.get_account()
    raw[field] = value
    monkeypatch.setattr(client, "get_account", lambda: raw)
    with pytest.raises(ReconciliationError) as caught:
        await built._verify_account()
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Alpaca account identity, status or restrictions differ"
    assert client.posts == [] and client.lookups == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "outcome,absent",
    [("NOT_SENT", True), ("REJECTED", True), ("ERROR", False), ("ACCEPTED", False)],
)
async def test_AX_16_only_latest_bound_submit_evidence_proves_absence(
    harness: Harness, outcome: str, absent: bool
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord

    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    with Session(h.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
    assert entry is not None
    assert built._confirmed_absence(entry) is False
    built._outcome(
        entry, outcome, None if outcome == "ACCEPTED" else ProviderError("Paper broker outcome")
    )
    assert built._confirmed_absence(entry) is absent
    # A later acceptance invalidates old negative evidence for this same instruction.
    built._outcome(entry, "ACCEPTED")
    assert built._confirmed_absence(entry) is False
    assert len(client.posts) == 1
    h.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", [None, "missing", "other_entry", "future", "stale"])
async def test_EX_completed_held_evidence_is_bound_and_quotes_are_idempotent(
    harness: Harness, fault: str | None
) -> None:
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.core.errors import DataIntegrityError
    from backend.tests.test_v_stop_raises import entered

    h = harness
    built, client, entry = await entered(h)
    inputs = await built._fresh_exit_inputs(entry)
    held = built._held_entry(entry)
    original = built.held_exit_observation
    assert original is not None
    if fault == "missing":
        built.held_exit_observation = None
    elif fault:

        async def changed(held_entry: Any, fresh: Any) -> Any:
            value = await original(held_entry, fresh)
            updates = {
                "other_entry": {"entry": held_entry.model_copy(update={"entry_id": uuid4()})},
                "future": {"known_at": h.clock.now() + timedelta(seconds=1)},
                "stale": {"session": built.calendar.previous_sessions(value.session, 2)[0]},
            }
            return value.model_copy(update=updates[fault])

        built.held_exit_observation = changed
    if fault:
        with pytest.raises(DataIntegrityError) as caught:
            await built._held_observation(entry, inputs)
        assert type(caught.value) is DataIntegrityError
        assert str(caught.value) == (
            "EX: completed held-exit observation unavailable"
            if fault == "missing"
            else "EX: held-exit evidence has another entry, future or stale session"
        )
    else:
        observation = await built._held_observation(entry, inputs)
        assert observation.entry == held
        assert observation.known_at <= h.clock.now()
        await built._held_observation(entry, inputs)
    with Session(h.state.engine) as session:
        events = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "HELD_QUOTE_OBSERVED")
            )
        )
    assert len(events) == 1
    assert events[0].detail == {
        "entry_id": str(entry.id),
        "account_id": "offline-paper",
        "environment": "PAPER",
        "symbol": entry.symbol,
        "price": str(inputs.market.last_price),
        "trade_at": inputs.market.last_price_ts.isoformat().replace("+00:00", "Z"),
        "known_at": h.clock.now().isoformat().replace("+00:00", "Z"),
    }
    assert len(client.posts) == 2
    h.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", [None, "missing_root", "wrong_role", "manual"])
async def test_EX_06_publisher_requires_fresh_cancelled_roots_and_writes_no_orders(
    harness: Harness, fault: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord, SecurityEvent
    from backend.core.errors import DataIntegrityError
    from backend.execution.exit_variants import stop_raise_plan
    from backend.execution.stop_readiness import CancelSemanticsProof, verify_cancel_semantics
    from backend.tests.test_v_stop_raises import entered

    h = harness
    ex, client, b = await entered(h)
    with Session(h.state.engine) as session:
        a = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.role == "ENTRY", ExecutionOrderRecord.id != b.id
            )
        )
    assert a is not None and a.stop_price is not None
    inputs = await ex._fresh_exit_inputs(a)
    observation = await ex._held_observation(a, inputs)
    observation = observation.model_copy(update={"close": a.stop_price + Decimal(7)})
    plan = stop_raise_plan(
        ex._held_entry(a),
        observation,
        ex.calendar,
        h.clock.now(),
        raise_id=uuid4(),
        qty=a.qty,
        old_stop=a.stop_price,
        last_trade=inputs.market.last_price,
        quote_at=inputs.market.last_price_ts,
        stale_quote_seconds=h.settings.stale_quote_seconds,
        trail_atr_mult=Decimal(3),
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
        stop = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.parent_execution_id == b.id,
                ExecutionOrderRecord.role == "STOP",
            )
        )
    assert oco is not None and stop is not None
    for intent in (oco, stop):
        broker = await ex._read_bound(intent)
        assert broker is not None
        assert (await ex._cancel_confirmed(intent, broker)).status == "canceled"
    await ex._ensure_stop(a, a.qty)
    await ex._ensure_stop(b, b.qty)
    posted = len(client.posts)
    reads: list[tuple[object, object]] = []
    original = client.get_order_by_id

    def read(identity: Any, filter: Any = None) -> Any:
        reads.append((identity, getattr(filter, "nested", None)))
        return original(identity, filter)

    monkeypatch.setattr(client, "get_order_by_id", read)
    if fault == "manual":
        ex.modes.downgrade("MANUAL", actor="offline owner")
    if fault:
        error_type = ExecutionDisabledError if fault == "manual" else DataIntegrityError
        with pytest.raises(error_type) as caught:
            await ex.record_paper_cancel_semantics(
                uuid4() if fault == "missing_root" else b.id,
                b.id if fault == "wrong_role" else oco.id,
            )
        assert type(caught.value) is error_type
        assert str(caught.value) == (
            "EX-06: explicit AUTO_PAPER integration only"
            if fault == "manual"
            else "EX-06: bound canonical paper roots required"
        )
        assert reads == []
    else:
        await ex.record_paper_cancel_semantics(b.id, oco.id)
        assert [nested for _, nested in reads] == [True, True, None, None]
    with Session(h.state.engine) as session:
        events = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "PAPER_CANCEL_SEMANTICS")
            )
        )
        assert len(events) == (0 if fault else 1)
        if not fault:
            proof = CancelSemanticsProof.recorded(events[0].detail)
            assert proof.oto_entry_id == b.id and proof.oco_exit_id == oco.id
            assert proof.oto_stop_id == stop.id
            assert proof.account_id == "offline-paper" and proof.environment == "PAPER"
            assert (
                proof.config_hash == h.settings.config_hash
                and proof.yaml_hash == h.config.config_hash
            )
            assert proof.observed_at == h.clock.now() and proof.sdk_version == "0.44.0"
            verify_cancel_semantics(session, proof, before_seq=events[0].seq)
    assert len(client.posts) == posted
    h.state.ledger.verify_chain()
    await ex.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("target_done", [False, True])
async def test_EX_split_trail_requires_real_sibling_target_fills(
    harness: Harness, target_done: bool
) -> None:
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    assert entry.stop_price is not None
    assert built._split_profit_taken(entry) is False
    if target_done:
        await target_filled(harness, built, client)
    assert built._split_profit_taken(entry) is target_done
    await built.monitor()
    assert len(client.posts) == (3 if target_done else 2)
    if target_done:
        assert client.posts[-1]["side"] == "sell"
        assert client.posts[-1]["qty"] == str(entry.qty)
        assert client.posts[-1]["stop_price"] == f"{entry.stop_price + Decimal(4):.2f}"
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault", [None, "reject-once", "reject-both", "cancel", "ambiguous-missing"]
)
async def test_EX_stop_raise_faults_preserve_exact_audited_protection(
    harness: Harness, fault: str | None
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import StopMoved
    from backend.execution.stop_evidence import current_stop
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    assert entry.stop_price is not None
    await target_filled(harness, built, client)
    client.raise_fault = fault
    if fault in {"reject-both", "cancel", "ambiguous-missing"}:
        with pytest.raises(ReconciliationError) as caught:
            await built.monitor()
        assert type(caught.value) is ReconciliationError
        # The enclosing monitor has one stable, redacted operator-facing refusal.
        assert str(caught.value) == "Automatic monitor failed closed"
    else:
        await built.monitor()
    with Session(harness.state.engine) as session:
        events = tuple(
            session.scalars(select(SecurityEvent).where(SecurityEvent.kind == "STOP_MOVED"))
        )
        assert len(events) == 1
        moved = StopMoved.recorded(events[0].detail)
        assert moved.approval.entry_id == entry.id
        assert moved.approval.qty == entry.qty
        assert moved.approval.old_stop == entry.stop_price
        assert moved.approval.new_stop == entry.stop_price + Decimal(4)
        expected = {
            None: "APPLIED",
            "reject-once": "REPAIRED",
            "reject-both": "FAILED",
            "cancel": "CANCEL_UNCONFIRMED",
            "ambiguous-missing": "FAILED",
        }[fault]
        assert moved.status == expected
        assert current_stop(session, entry) == entry.stop_price + (
            Decimal(4) if fault in {None, "reject-once"} else Decimal(0)
        )
    assert (
        len(client.posts)
        == {None: 3, "reject-once": 4, "reject-both": 4, "cancel": 2, "ambiguous-missing": 3}[fault]
    )
    assert harness.state.current() == (SystemState.RUNNING if fault is None else SystemState.HALTED)
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("symbol", ["AMD", "UNLISTED"])
async def test_AX_30_unrelated_position_halts_but_repairs_verified_held_stop(
    harness: Harness, symbol: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    client.positions.append(
        {"symbol": symbol, "qty": "1", "side": "long", "asset_class": "us_equity"}
    )
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == 2
    assert client.posts[-1]["type"] == "stop" and client.posts[-1]["qty"] == "1"
    assert client.posts[-1]["stop_price"] == f"{h.request.candidate.stop_price:.2f}"
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("partial", [False, True])
async def test_SEC_73_panic_cancels_remainders_without_exit_analysis(
    harness: Harness, partial: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    if partial:
        await fill_entry(h, client, built, partial=True)
    with pytest.raises(ExecutionDisabledError, match="HALT first"):
        await built.cancel_unfilled_entries()
    h.state.escalate(SystemState.HALTED, "local panic fixture")

    async def forbidden(symbol: str) -> object:
        raise AssertionError("Panic must not request entry or time/earnings exit analysis")

    monkeypatch.setattr(h.source, "refresh", forbidden)
    await built.cancel_unfilled_entries()
    assert (
        next(row for row in client.orders.values() if row["side"] == "buy")["status"] == "canceled"
    )
    assert len(client.posts) == (2 if partial else 1)
    assert all(row["type"] == "stop" and row["qty"] == "1" for row in client.posts[1:])
    assert h.state.current() == SystemState.HALTED
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["held_quantity", "foreign_sell", "repair_rejection"])
async def test_AX_30_recovery_never_guesses_holdings_or_overlaps_unknown_sell(
    harness: Harness, fault: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)
    if fault == "held_quantity":
        client.positions[0]["qty"] = "2"
    elif fault == "foreign_sell":
        client.orders["foreign-manual"] = {
            "id": str(uuid4()),
            "client_order_id": "foreign-manual",
            "symbol": "NVDA",
            "side": "sell",
            "type": "limit",
            "order_class": "simple",
            "time_in_force": "day",
            "qty": "1",
            "filled_qty": "0",
            "status": "new",
            "limit_price": "150.00",
            "submitted_at": h.clock.now().isoformat(),
            "legs": None,
        }
    else:
        client.positions.append(
            {"symbol": "AMD", "qty": "1", "side": "long", "asset_class": "us_equity"}
        )
        client.failure = "reject"
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == (2 if fault == "repair_rejection" else 1)
    assert all(Decimal(row["qty"]) <= 1 for row in client.posts[1:])
    if fault != "repair_rejection":
        assert parent["status"] == "partially_filled"
    h.state.ledger.verify_chain()
