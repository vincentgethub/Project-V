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


async def offline_raise_approval(harness: Harness, built: Any, entry: Any) -> Any:
    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import HeldExitObservation, stop_raise_plan

    inputs = await built._fresh_exit_inputs(entry)
    observed = await built._held_observation(entry, inputs)
    assert entry.stop_price is not None
    observed = HeldExitObservation.model_validate(
        {**observed.model_dump(), "close": entry.stop_price + Decimal(7)}
    )
    plan = stop_raise_plan(
        built._held_entry(entry),
        observed,
        built.calendar,
        harness.clock.now(),
        raise_id=uuid4(),
        qty=entry.qty,
        old_stop=entry.stop_price,
        last_trade=inputs.market.last_price,
        quote_at=inputs.market.last_price_ts,
        stale_quote_seconds=harness.settings.stale_quote_seconds,
        trail_atr_mult=Decimal(3),
        config_hash=harness.settings.config_hash,
        yaml_hash=harness.config.config_hash,
    )
    assert plan is not None
    harness.state.ledger.append(
        SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
    )
    return plan


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_orphan_cleanup_rechecks_position_and_halts_without_canceling_exits(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        parent = client.orders[entry.client_order_id]
        parent["status"] = "canceled"
        assert (
            await built._finalize_entry_cancellation(entry, reason="offline broker canceled entry")
            == "CANCELED"
        )
        reads = 0
        reasons: list[str] = []
        original_orphans = built._exits_are_orphaned

        def positions() -> list[dict[str, Any]]:
            nonlocal reads
            reads += 1
            if reads >= 2:
                # A newer position snapshot contradicts the zero-share proof.
                client.positions = [
                    {"symbol": entry.symbol, "qty": "1", "side": "long", "asset_class": "us_equity"}
                ]
            return client.positions

        def forbidden_cancel(identity: Any) -> None:
            raise AssertionError("A fresh position mismatch must leave contingent exits alone")

        async def orphaned(managed: Any) -> bool:
            try:
                return await original_orphans(managed)
            except ReconciliationError as error:
                reasons.append(str(error))
                raise

        monkeypatch.setattr(client, "get_all_positions", positions)
        monkeypatch.setattr(client, "_cancel_paper", forbidden_cancel)
        monkeypatch.setattr(built, "_exits_are_orphaned", orphaned)
        with pytest.raises(ReconciliationError) as failed:
            await built.reconcile()
        assert type(failed.value) is ReconciliationError
        assert str(failed.value) == "Broker reconciliation failed closed"
        assert reasons == ["Orphan cleanup cannot reconcile broker-held shares"]
        assert len(client.posts) == 1 and all(row["status"] == "held" for row in parent["legs"])
        assert client.positions[0]["qty"] == "1"
        assert harness.state.current() == SystemState.HALTED and not built.modes.entries_enabled
        # This deliberately inconsistent broker position is reported, never
        # guessed away or sold. Independent admission also refuses it.
        with pytest.raises(ExecutionDisabledError) as refused:
            await built.enter(uuid4())
        assert type(refused.value) is ExecutionDisabledError
        assert str(refused.value) == "Protection veto: NVDA has held shares but no active stop"
        assert len(client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "panic_cancel_timeout_seconds": 1}], indirect=True)
@pytest.mark.parametrize("outcome", ["pending", "unknown"])
async def test_SEC_73_repeated_unconfirmed_panic_keeps_one_intent_and_never_guesses(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import AppendControl, OrderEvent

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    canceled: list[str] = []
    try:
        if outcome == "unknown":
            client.failure = "ambiguous-missing"
            with pytest.raises(ProviderError) as failed:
                await built.enter(alert.proposal_id)
            assert type(failed.value) is ProviderError
            assert str(failed.value) == "Automatic entry failed closed; inspect persisted intent"
            await built.prepare_fills(("NVDA",))
        else:
            await built.enter(alert.proposal_id)
            harness.state.escalate(SystemState.HALTED, "offline pending broker cancellation")

            def pending(identity: Any) -> None:
                canceled.append(str(identity))
                next(iter(client.orders.values()))["status"] = "pending_cancel"

            monkeypatch.setattr(client, "_cancel_paper", pending)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        for _ in range(2):
            with pytest.raises(ReconciliationError) as unresolved:
                await built.cancel_unfilled_entries()
            assert type(unresolved.value) is ReconciliationError
            assert str(
                unresolved.value
            ) == "Panic cancellation incomplete; unresolved orders: " + str(entry.order_id)
            assert harness.state.current() == SystemState.HALTED and not built.modes.entries_enabled
            assert len(client.posts) == 1
        with Session(harness.state.engine) as session:
            states = [
                row.state
                for row in session.scalars(
                    select(OrderEvent)
                    .where(OrderEvent.order_id == entry.order_id)
                    .order_by(OrderEvent.seq)
                )
            ]
        assert states.count("CANCEL_REQUESTED") == 1 and states[-1] == "CANCEL_REQUESTED"
        assert len(canceled) == (1 if outcome == "pending" else 0)
        assert client.positions == []
        if outcome == "pending":
            parent = next(iter(client.orders.values()))
            parent["status"] = "canceled"
            for leg in parent["legs"]:
                leg["status"] = "canceled"
            await built.cancel_unfilled_entries()
            with Session(harness.state.engine) as session:
                before = session.scalar(select(AppendControl.next_seq))
            await built.cancel_unfilled_entries()
            with Session(harness.state.engine) as session:
                assert session.scalar(select(AppendControl.next_seq)) == before
            assert len(canceled) == 1 and len(client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("interruption", ["before_submit", "candidate_canceled", "unknown_intent"])
async def test_EX_05_restart_of_an_approved_raise_requires_exact_live_protection(
    harness: Harness, interruption: str
) -> None:
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.execution.stop_evidence import current_stop
    from backend.tests.test_v_stop_raises import entered

    built, client, entry = await entered(harness)
    try:
        plan = await offline_raise_approval(harness, built, entry)
        journal = built._begin_protection_repair(
            entry, entry.qty, plan.old_stop, plan.new_stop, plan
        )
        if interruption == "unknown_intent":
            harness.state.ledger.append(
                ExecutionOrderRecord,
                order_id=entry.order_id,
                parent_execution_id=entry.id,
                client_order_id=journal["new_client_id"],
                account_id=entry.account_id,
                environment=entry.environment,
                symbol=entry.symbol,
                role="REPAIR",
                side="SELL",
                order_type="STOP",
                qty=entry.qty,
                limit_price=None,
                stop_price=plan.new_stop,
                target_price=None,
                time_in_force="GTC",
                config_hash=harness.settings.config_hash,
                valid_until=None,
            )
            with pytest.raises(ReconciliationError) as refused:
                await built._raise_repair(entry, plan)
            assert type(refused.value) is ReconciliationError
            assert str(refused.value) == "EX-05: unknown sell outcome forbids overlapping repair"
            assert len(client.posts) == 2 and built._protection_repairs()
            assert not built.modes.entries_enabled
        else:
            await built._cancel_sells(entry)
            if interruption == "candidate_canceled":
                broker = await built._repair_stop_attempt(entry, journal, restore=False)
                intent = next(
                    row
                    for row in built._instructions()
                    if row.client_order_id == journal["new_client_id"]
                )
                await built._cancel_confirmed(intent, broker)
            await built._resume_protection_repairs()
            assert built._protection_repairs() == () and built.modes.entries_enabled
            assert harness.state.current() == SystemState.RUNNING
            assert len(client.posts) == (4 if interruption == "candidate_canceled" else 3)
            assert client.posts[-1]["type"] == "stop" and client.posts[-1]["stop_price"] == format(
                plan.old_stop, ".2f"
            )
            with Session(harness.state.engine) as session:
                assert current_stop(session, entry) == plan.old_stop
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "day_trade_regime": "LEGACY_PDT"}], indirect=True)
@pytest.mark.parametrize("completed", [0, 1])
async def test_AX_25_legacy_day_trade_count_below_two_permits_the_approved_entry(
    harness: Harness, completed: int
) -> None:
    from datetime import timedelta

    from backend.domain.compliance_models import TradeRecord
    from backend.domain.models import Side

    alert = await deliver(harness)
    history = (
        tuple(
            TradeRecord(
                trade_id=uuid4(),
                account_id="offline-paper",
                symbol="NVDA",
                side=side,
                qty=1,
                price=Decimal(100),
                ts=harness.clock.now() - timedelta(days=1, minutes=minute),
            )
            for minute, side in ((4, Side.BUY), (3, Side.SELL))
        )
        if completed
        else ()
    )
    harness.source.inputs = harness.source.inputs.model_copy(update={"history": history})
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        submission = await built.enter(alert.proposal_id)
        assert submission.broker_order.is_open and submission.broker_order.side == "buy"
        assert len(client.posts) == 1 and client.posts[0]["type"] == "limit"
        assert harness.state.current() == SystemState.RUNNING
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_fill_identity_refresh_does_not_read_unrequested_symbols(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import AppendControl

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        with Session(harness.state.engine) as session:
            before = session.scalar(select(AppendControl.next_seq))

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("An unrelated symbol must not trigger a broker identity lookup")

        monkeypatch.setattr(client, "get_order_by_client_id", forbidden)
        monkeypatch.setattr(client, "get_order_by_id", forbidden)
        await built.prepare_fills(("JNJ",))
        with Session(harness.state.engine) as session:
            assert session.scalar(select(AppendControl.next_seq)) == before
        assert len(client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_held_quote_audit_retains_changed_trade_without_duplicate_identical_rows(
    harness: Harness,
) -> None:
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.tests.test_v_stop_raises import entered

    built, client, entry = await entered(harness)
    try:
        inputs = await built._fresh_exit_inputs(entry)
        held = built._held_entry(entry)
        built._record_held_quote(held, inputs)
        with Session(harness.state.engine) as session:
            before = tuple(
                session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "HELD_QUOTE_OBSERVED")
                )
            )
        built._record_held_quote(held, inputs)
        with Session(harness.state.engine) as session:
            assert len(
                tuple(
                    session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "HELD_QUOTE_OBSERVED")
                    )
                )
            ) == len(before)
        harness.clock.current += timedelta(seconds=1)
        changed = inputs.model_copy(
            update={
                "market": inputs.market.model_copy(
                    update={
                        "last_price": inputs.market.last_price + Decimal("0.01"),
                        "last_price_ts": harness.clock.now(),
                    }
                )
            }
        )
        built._record_held_quote(held, changed)
        with Session(harness.state.engine) as session:
            rows = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "HELD_QUOTE_OBSERVED")
                    .order_by(SecurityEvent.seq)
                )
            )
        assert len(rows) == len(before) + 1
        assert rows[-1].detail["price"] == str(changed.market.last_price)
        assert len(client.posts) == 2
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_changed_held_quantity_refuses_the_stale_raise_approval_before_submit(
    harness: Harness,
) -> None:
    from uuid import UUID

    from backend.core.errors import EntryAdmissionRevoked
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.tests.test_v_stop_raises import entered

    built, client, entry = await entered(harness)
    try:
        plan = await offline_raise_approval(harness, built, entry)
        journal = built._begin_protection_repair(
            entry, entry.qty, plan.old_stop, plan.new_stop, plan
        )
        parent = client.orders[entry.client_order_id]
        stop = next(row for row in parent["legs"] if row["type"] == "stop")
        stop["status"], stop["filled_qty"] = "partially_filled", "1"
        client.positions[0]["qty"] = str(int(client.positions[0]["qty"]) - 1)
        instruction = next(
            row for row in built._instructions() if row.client_order_id == stop["client_order_id"]
        )
        await built._read_bound(instruction)
        built.observe_fill(
            ObservedFill(
                account_id=entry.account_id,
                broker_fill_id="reduce-before-approved-raise",
                broker_order_id=UUID(stop["id"]),
                symbol=entry.symbol,
                side=Side.SELL,
                qty=1,
                price=plan.old_stop,
                filled_at=harness.clock.now(),
            )
        )
        with pytest.raises(EntryAdmissionRevoked) as refused:
            await built._repair_stop_attempt(entry, journal, restore=False)
        assert type(refused.value) is EntryAdmissionRevoked
        assert str(refused.value) == "Stop-raise quantity changed before journaled submit"
        assert len(client.posts) == 2 and built._protection_repairs()
        assert not built.modes.entries_enabled
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_unresolved_later_sell_intent_keeps_existing_protection_on_restart(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.core.database import ExecutionOrderRecord

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    cancellations: list[str] = []
    original_cancel = client._cancel_paper

    def cancel(identity: Any) -> None:
        cancellations.append(str(identity))
        original_cancel(identity)

    try:
        await built.enter(alert.proposal_id)
        parent, _ = await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        # A process can die after recording its intent and before recording any
        # physical outcome. Absence on lookup does not prove it was never sent.
        harness.state.ledger.append(
            ExecutionOrderRecord,
            order_id=entry.order_id,
            parent_execution_id=entry.id,
            client_order_id=journal["new_client_id"],
            account_id=entry.account_id,
            environment=entry.environment,
            symbol=entry.symbol,
            role="REPAIR",
            side="SELL",
            order_type="STOP",
            qty=entry.qty,
            limit_price=None,
            stop_price=entry.stop_price,
            target_price=None,
            time_in_force="GTC",
            config_hash=harness.settings.config_hash,
            valid_until=None,
        )
        monkeypatch.setattr(client, "_cancel_paper", cancel)
        with pytest.raises(ReconciliationError) as failed:
            await built.monitor()
        assert type(failed.value) is ReconciliationError
        assert str(failed.value) == "Automatic monitor failed closed"
        assert cancellations == [], (
            "An unresolved later sell must be checked before any stop is canceled"
        )
        assert all(row["status"] == "new" for row in parent["legs"])
        assert len(client.posts) == 1
        assert harness.state.current() == SystemState.HALTED and not built.modes.entries_enabled
        assert built._protection_repairs()[0]["phase"] == "FAILED"
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_SEC_73_late_canceled_leg_observation_waits_for_its_fill_before_finalizing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import OrderEvent
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.alpaca_executor import parse_order

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    captured = None
    injected = False
    try:
        await built.enter(alert.proposal_id)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        root = client.orders[entry.client_order_id]
        original_read = built._read_bound
        pending_states: list[str] = []

        async def capture_late_fill() -> None:
            await asyncio.sleep(0)
            with Session(harness.state.engine) as session:
                latest = session.scalar(
                    select(OrderEvent)
                    .where(OrderEvent.order_id == entry.order_id)
                    .order_by(OrderEvent.seq.desc())
                )
                assert latest is not None
                pending_states.append(latest.state)
            assert entry.limit_price is not None
            built.observe_fill(
                ObservedFill(
                    account_id=entry.account_id,
                    broker_fill_id="cancel-terminal-late-fill",
                    broker_order_id=UUID(root["id"]),
                    symbol=entry.symbol,
                    side=Side.BUY,
                    qty=1,
                    price=entry.limit_price,
                    filled_at=harness.clock.now(),
                )
            )

        async def read(instruction: Any) -> Any:
            nonlocal injected, captured
            broker = await original_read(instruction)
            if (
                instruction.id == entry.id
                and not injected
                and broker is not None
                and broker.status == "canceled"
            ):
                injected = True
                # An independent broker update reaches the durable binding after
                # this read's snapshot, before its activity batch is captured.
                root["filled_qty"] = "1"
                client.positions = [
                    {"symbol": entry.symbol, "qty": "1", "side": "long", "asset_class": "us_equity"}
                ]
                built._observe(entry, parse_order(root))
                captured = asyncio.create_task(capture_late_fill())
            return broker

        monkeypatch.setattr(built, "_read_bound", read)
        harness.state.escalate(SystemState.HALTED, "offline terminal-observation race")
        await built.cancel_unfilled_entries()
        assert captured is not None
        await captured
        assert injected and pending_states == ["CANCEL_REQUESTED"]
        assert root["status"] == "canceled" and root["filled_qty"] == "1"
        assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
        assert client.posts[-1]["qty"] == "1"
        with Session(harness.state.engine) as session:
            states = [
                row.state
                for row in session.scalars(
                    select(OrderEvent)
                    .where(OrderEvent.order_id == entry.order_id)
                    .order_by(OrderEvent.seq)
                )
            ]
        assert states[-2:] == ["CANCEL_REQUESTED", "CANCELED"]
        assert harness.state.current() == SystemState.HALTED and not built.modes.entries_enabled
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        if captured is not None:
            await captured
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_repair_starting_after_entry_intent_still_vetoes_physical_buy(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord, OrderEvent
    from backend.core.errors import EntryAdmissionRevoked
    from backend.domain.models import Position
    from backend.tests.test_auto_admission import recorded_imported_card

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        _, fill = await fill_entry(harness, client, built)
        held = next(row for row in built._instructions() if row.role == "ENTRY")
        order = recorded_imported_card(harness, "valid", symbol="JNJ")
        harness.source.inputs = harness.source.inputs.model_copy(
            update={
                "market": harness.source.inputs.market.model_copy(
                    update={"last_price": Decimal(100)}
                ),
                "portfolio": harness.source.inputs.portfolio.model_copy(
                    update={
                        "equity": Decimal(100000),
                        "cash": Decimal(99000),
                        "settled_cash": Decimal(99000),
                        "high_water_mark": Decimal(100000),
                        "day_start_equity": Decimal(100000),
                        "positions": {
                            held.symbol: Position(
                                qty=fill.qty, avg_cost=fill.price, last_price=fill.price
                            )
                        },
                    }
                ),
            }
        )
        original_positions = client.get_all_positions
        started = False

        def positions() -> list[dict[str, Any]]:
            nonlocal started
            with Session(harness.state.engine) as session:
                intended = session.scalar(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.symbol == "JNJ")
                )
            if intended is not None and not started:
                assert held.stop_price is not None
                built._begin_protection_repair(held, held.qty, held.stop_price, held.stop_price)
                started = True
            return original_positions()

        monkeypatch.setattr(client, "get_all_positions", positions)
        with pytest.raises(EntryAdmissionRevoked) as refused:
            await built.enter(order.proposal_id)
        assert started and type(refused.value) is EntryAdmissionRevoked
        assert str(refused.value) == "Open protection repair blocks entry"
        assert len(client.posts) == 1 and built._protection_repairs()
        assert not built.modes.entries_enabled
        with Session(harness.state.engine) as session:
            latest = session.scalar(
                select(OrderEvent)
                .where(OrderEvent.order_id == order.id)
                .order_by(OrderEvent.seq.desc())
            )
            assert latest is not None and latest.state == "CANCELED"
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("path", ["reconcile", "recovery"])
async def test_AX_30_one_holdings_failure_does_not_suppress_other_verified_protection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    from backend.tests.test_v_stop_raises import entered

    built, client, _ = await entered(harness)
    entries = [row for row in built._instructions() if row.role == "ENTRY"]
    notices: list[tuple[str, bool]] = []
    checked: list[Any] = []
    original_ensure = built._ensure_stop

    async def ensure(entry: Any, qty: int) -> None:
        checked.append(entry.id)
        await original_ensure(entry, qty)

    async def notify(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    built.notify = notify
    monkeypatch.setattr(built, "_ensure_stop", ensure)
    try:
        if path == "reconcile":
            refresh = harness.source.refresh
            failed = False

            async def unavailable(symbol: str) -> Any:
                nonlocal failed
                if not failed:
                    failed = True
                    raise ProviderError("offline first-holding quote unavailable")
                return await refresh(symbol)

            monkeypatch.setattr(harness.source, "refresh", unavailable)
            with pytest.raises(ReconciliationError) as caught:
                await built.reconcile()
            assert type(caught.value) is ReconciliationError
            assert str(caught.value) == "Broker reconciliation failed closed"
            assert type(caught.value.__context__) is ReconciliationError
            assert (
                str(caught.value.__context__)
                == "Held protection failed; other verified holdings were checked"
            )
            assert set(checked) == {row.id for row in entries}
        else:
            original_read = client.get_order_by_id
            first_root = client.orders[entries[0].client_order_id]["id"]

            def unavailable_root(identity: Any, filter: object = None) -> dict[str, Any]:
                if str(identity) == first_root:
                    raise ProviderError("offline first-holding broker read unavailable")
                return original_read(identity, filter)

            monkeypatch.setattr(client, "get_order_by_id", unavailable_root)
            await built._recover_verified_protection(protection_only=True)
            assert checked == [entries[1].id]
            assert notices[0] == (
                "PAPER \u00b7 HALTED: verified protection recovery failed for NVDA; inspect broker stops urgently.",
                True,
            )
        assert harness.state.current() == SystemState.HALTED and not built.modes.entries_enabled
        assert len(client.posts) == 2
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("path", ["ordinary", "old_level", "expired"])
async def test_EX_05_legacy_repair_contract_keeps_old_level_and_physical_quote_guard(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.core.errors import EntryAdmissionRevoked
    from backend.tests.test_v_stop_raises import entered

    built, client, entry = await entered(harness)
    try:
        assert entry.stop_price is not None
        plan = None if path == "ordinary" else await offline_raise_approval(harness, built, entry)
        journal = built._begin_protection_repair(
            entry,
            entry.qty,
            entry.stop_price,
            entry.stop_price if plan is None else plan.new_stop,
            plan,
        )
        await built._cancel_sells(entry)
        if path == "expired":
            original_acquire = built.worker.bucket.acquire
            expired = False

            async def acquire() -> None:
                nonlocal expired
                await original_acquire()
                with Session(harness.state.engine) as session:
                    intent = session.scalar(
                        select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "REPAIR")
                    )
                if intent is not None and not expired:
                    expired = True
                    harness.clock.current += timedelta(
                        seconds=harness.settings.stale_quote_seconds + 1
                    )

            monkeypatch.setattr(built.worker.bucket, "acquire", acquire)
            with pytest.raises(ReconciliationError) as refused:
                await built._repair_stop(entry, entry.qty, approval=plan)
            assert type(refused.value) is ReconciliationError
            assert str(refused.value) == "Protective stop could not be confirmed; HALTED"
            assert type(refused.value.__context__) is EntryAdmissionRevoked
            assert str(refused.value.__context__) == "EX-05: stop-raise quote expired before submit"
            assert expired and len(client.posts) == 2
            assert harness.state.current() == SystemState.HALTED
        confirmed = await built._repair_stop(
            entry,
            entry.qty,
            approval=plan,
            repair=plan is not None,
            repair_level=None if plan is None else plan.old_stop,
        )
        assert confirmed.is_open and confirmed.order_type == "stop"
        assert confirmed.qty == entry.qty and confirmed.stop_price == entry.stop_price
        assert len(client.posts) == 3
        if plan is not None:
            built._stop_moved(plan, "REPAIRED", plan.old_stop)
        built._finish_protection_repair(journal, result="RESTORED")
        assert built._protection_repairs() == ()
        assert built.modes.entries_enabled is (path != "expired")
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("refused", [False, True])
async def test_EX_05_pre_journal_approval_replays_without_blind_submit(
    harness: Harness, refused: bool
) -> None:
    from backend.tests.test_v_stop_raises import entered

    built, client, sibling = await entered(harness)
    try:
        entry = next(
            row for row in built._instructions() if row.role == "ENTRY" and row.id != sibling.id
        )
        plan = await offline_raise_approval(harness, built, entry)
        # Reconstruct the already-approved, pre-journal ledger sequence. Its
        # caller confirmed terminal old exits before the original submit.
        for child in [row for row in built._instructions() if row.parent_execution_id == entry.id]:
            broker = await built._read_bound(child)
            assert broker is not None
            if broker.is_open:
                await built._cancel_confirmed(child, broker)
        if refused:
            client.raise_fault = "reject-once"
            with pytest.raises(ReconciliationError) as error:
                await built._repair_stop(entry, entry.qty, approval=plan)
            assert type(error.value) is ReconciliationError
            assert str(error.value) == "Protective stop could not be confirmed; HALTED"
        else:
            await built._repair_stop(entry, entry.qty, approval=plan)
        assert built._protection_repairs() == ()
        before = len(client.posts)
        await built._resume_stop_moves(entry, entry.qty)
        assert len(client.posts) == before + int(refused)
        assert (
            sum(row["client_order_id"] == "vws-m-" + plan.raise_id.hex for row in client.posts) == 1
        )
        assert harness.state.current() == (SystemState.HALTED if refused else SystemState.RUNNING)
        assert_paper_shares_protected(harness, client)
        posts = len(client.posts)
        await built._resume_stop_moves(entry, entry.qty)
        assert len(client.posts) == posts
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile"])
@pytest.mark.parametrize("difference", [-1, 1])
async def test_AX_27_restart_position_disagreement_halts_before_touching_existing_stops(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, operation: str, difference: int
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    cancellations: list[str] = []

    def cancel(identity: Any) -> None:
        cancellations.append(str(identity))
        raise AssertionError("Unreconciled holdings cannot authorize removing a stop")

    try:
        await built.enter(alert.proposal_id)
        parent, _ = await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        built._begin_protection_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
        client.positions[0]["qty"] = str(entry.qty + difference)
        monkeypatch.setattr(client, "_cancel_paper", cancel)
        with pytest.raises(ReconciliationError) as refused:
            if operation == "monitor":
                await built.monitor()
            else:
                await built.reconcile()
        assert type(refused.value) is ReconciliationError
        assert str(refused.value) == (
            "Automatic monitor failed closed"
            if operation == "monitor"
            else "Broker reconciliation failed closed"
        )
        assert type(refused.value.__context__) is ReconciliationError
        assert (
            str(refused.value.__context__)
            == "Protection repair cannot reconcile broker-held shares"
        )
        assert cancellations == [] and len(client.posts) == 1
        assert all(leg["status"] == "new" for leg in parent["legs"])
        assert harness.state.current() == SystemState.HALTED
        assert built._protection_repairs() and not built.modes.entries_enabled
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("resume", [False, True])
async def test_AX_27_exit_fill_closes_its_repair_flat_without_selling_the_sibling(
    harness: Harness, resume: bool
) -> None:
    from sqlalchemy.orm import Session

    from backend.execution.storage import held_quantity
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, sibling = await entered(harness)
    try:
        entry = next(
            row for row in built._instructions() if row.role == "ENTRY" and row.id != sibling.id
        )
        assert entry.stop_price is not None
        built._begin_protection_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
        await target_filled(harness, built, client)
        if resume:
            await built._resume_protection_repairs()
        else:
            level, _ = await built._journaled_stop_repair(
                entry, entry.qty, entry.stop_price, entry.stop_price
            )
            assert level == entry.stop_price
        assert built._protection_repairs() == () and built.modes.entries_enabled
        assert len(client.posts) == 2
        with Session(harness.state.engine) as session:
            assert held_quantity(session, entry.id) == 0
            assert held_quantity(session, sibling.id) == sibling.qty
        assert harness.state.current() == SystemState.RUNNING
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_standalone_repair_requires_recorded_approval(harness: Harness) -> None:
    import re

    from backend.core.errors import DataIntegrityError

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        message = "Standalone stop repair requires a recorded approval"
        with pytest.raises(DataIntegrityError, match="^" + re.escape(message) + "$") as caught:
            await built._journaled_stop_repair(
                entry, entry.qty, entry.stop_price, entry.stop_price, standalone_repair=True
            )
        assert type(caught.value) is DataIntegrityError
        assert str(caught.value) == message
        assert len(client.posts) == 1
        assert len(built._protection_repairs()) == 1 and not built.modes.entries_enabled
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_unresolved_physical_work_blocks_repair_before_any_cancellation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import threading

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    release, started = threading.Event(), threading.Event()
    task = None
    cancellations: list[str] = []

    def unresolved() -> list[dict[str, Any]]:
        started.set()
        assert release.wait(5)
        return client.positions

    def cancel(identity: Any) -> None:
        cancellations.append(str(identity))
        raise AssertionError("Unresolved physical work must not remove protection")

    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        monkeypatch.setattr(client, "_cancel_paper", cancel)
        task = asyncio.create_task(built.worker.attempt(unresolved))
        assert await asyncio.to_thread(started.wait, 2)
        with pytest.raises(ReconciliationError) as refused:
            await built._journaled_stop_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
        assert type(refused.value) is ReconciliationError
        assert (
            str(refused.value)
            == "Journaled protection and old-level restoration could not be confirmed; HALTED"
        )
        assert type(refused.value.__cause__) is ReconciliationError
        assert (
            str(refused.value.__cause__)
            == "EX-05: unresolved physical attempt forbids a conflicting repair"
        )
        assert cancellations == [] and len(client.posts) == 1
        assert harness.state.current() == SystemState.HALTED
        assert (
            built._protection_repairs()[0]["phase"] == "FAILED" and not built.modes.entries_enabled
        )
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        release.set()
        if task is not None:
            await task
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_short_oco_stop_never_counts_as_full_protection_and_restores_old_level(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import HeldExitObservation, stop_raise_plan
    from backend.execution.stop_evidence import current_stop
    from backend.tests.test_v_stop_raises import entered

    built, client, sibling = await entered(harness)
    try:
        entry = next(
            row for row in built._instructions() if row.role == "ENTRY" and row.id != sibling.id
        )
        inputs = await built._fresh_exit_inputs(entry)
        observed = await built._held_observation(entry, inputs)
        assert entry.stop_price is not None
        observed = HeldExitObservation.model_validate(
            {**observed.model_dump(), "close": entry.stop_price + Decimal(7)}
        )
        plan = stop_raise_plan(
            built._held_entry(entry),
            observed,
            built.calendar,
            harness.clock.now(),
            raise_id=uuid4(),
            qty=entry.qty,
            old_stop=entry.stop_price,
            last_trade=inputs.market.last_price,
            quote_at=inputs.market.last_price_ts,
            stale_quote_seconds=harness.settings.stale_quote_seconds,
            trail_atr_mult=Decimal(3),
            config_hash=harness.settings.config_hash,
            yaml_hash=harness.config.config_hash,
        )
        assert plan is not None
        harness.state.ledger.append(
            SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
        )
        assert entry.stop_price is not None and entry.qty > 1
        original_submit = client._submit_paper
        original_attempt = built._repair_stop_attempt
        refusals: list[str] = []

        def submit(request: Any) -> dict[str, Any]:
            assert built._protection_repairs() and not built.modes.entries_enabled
            raw = original_submit(request)
            if raw["order_class"] == "oco":
                raw["legs"][0]["qty"] = str(entry.qty - 1)
            return raw

        async def attempt(*args: Any, **kwargs: Any) -> Any:
            try:
                return await original_attempt(*args, **kwargs)
            except ReconciliationError as error:
                refusals.append(str(error))
                raise

        monkeypatch.setattr(client, "_submit_paper", submit)
        monkeypatch.setattr(built, "_repair_stop_attempt", attempt)
        level, journal = await built._journaled_stop_repair(
            entry, entry.qty, plan.old_stop, plan.new_stop, approval=plan
        )
        assert level == plan.old_stop
        built._stop_moved(plan, "REPAIRED", level)
        built._finish_protection_repair(journal, result="RESTORED")
        assert refusals == ["Journaled replacement lacks exact live stop coverage"]
        assert len(client.posts) == 4
        assert client.posts[-1]["type"] == "stop"
        assert client.posts[-1]["qty"] == str(entry.qty)
        assert client.posts[-1]["stop_price"] == format(entry.stop_price, ".2f")
        assert harness.state.current() == SystemState.RUNNING
        assert built.modes.entries_enabled and built._protection_repairs() == ()
        with Session(harness.state.engine) as session:
            assert current_stop(session, entry) == entry.stop_price
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_stale_quote_after_approval_restores_only_the_old_proved_stop(
    harness: Harness,
) -> None:
    from datetime import timedelta

    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import stop_raise_plan
    from backend.execution.stop_evidence import current_stop
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    try:
        await target_filled(harness, built, client)
        inputs = await built._fresh_exit_inputs(entry)
        assert entry.stop_price is not None
        plan = stop_raise_plan(
            built._held_entry(entry),
            await built._held_observation(entry, inputs),
            built.calendar,
            harness.clock.now(),
            raise_id=uuid4(),
            qty=entry.qty,
            old_stop=entry.stop_price,
            last_trade=inputs.market.last_price,
            quote_at=inputs.market.last_price_ts,
            stale_quote_seconds=harness.settings.stale_quote_seconds,
            trail_atr_mult=Decimal(3),
            config_hash=harness.settings.config_hash,
            yaml_hash=harness.config.config_hash,
        )
        assert plan is not None
        harness.state.ledger.append(
            SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
        )
        await built._cancel_sells(entry)
        harness.source.inputs = harness.source.inputs.model_copy(
            update={
                "market": inputs.market.model_copy(
                    update={
                        "last_price_ts": harness.clock.now()
                        - timedelta(seconds=harness.settings.stale_quote_seconds + 1)
                    }
                )
            }
        )
        level, journal = await built._journaled_stop_repair(
            entry, entry.qty, plan.old_stop, plan.new_stop, approval=plan
        )
        assert level == plan.old_stop
        assert client.posts[-1]["type"] == "stop"
        assert client.posts[-1]["stop_price"] == format(plan.old_stop, ".2f")
        assert len(client.posts) == 3
        assert not built.modes.entries_enabled and built._protection_repairs()
        built._stop_moved(plan, "REPAIRED", level)
        built._finish_protection_repair(journal, result="RESTORED")
        assert built.modes.entries_enabled and built._protection_repairs() == ()
        with Session(harness.state.engine) as session:
            assert current_stop(session, entry) == plan.old_stop
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_host_resume_during_physical_repair_guard_cannot_send_a_sell(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.core.errors import EntryAdmissionRevoked

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    resumed = False
    original_acquire = built.worker.bucket.acquire

    async def acquire() -> None:
        nonlocal resumed
        await original_acquire()
        with Session(harness.state.engine) as session:
            intent = session.scalar(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "REPAIR")
            )
        if intent is not None and not resumed:
            built.modes.resume(operator="offline owner", phrase="RESUME")
            resumed = True

    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        await built._cancel_sells(entry)
        monkeypatch.setattr(built.worker.bucket, "acquire", acquire)
        with pytest.raises(EntryAdmissionRevoked) as refused:
            await built._repair_stop_attempt(entry, journal, restore=False)
        assert resumed and type(refused.value) is EntryAdmissionRevoked
        assert str(refused.value) == "Protection repair lost its durable entry block"
        assert len(client.posts) == 1
        with pytest.raises(ReconciliationError) as halted:
            await built.monitor()
        assert type(halted.value) is ReconciliationError
        assert str(halted.value) == "Automatic monitor failed closed"
        assert harness.state.current() == SystemState.HALTED
        assert built._protection_repairs() and not built.modes.entries_enabled
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_unrecorded_terminal_client_id_cannot_be_reused_for_protection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        parent, _ = await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        await built._cancel_sells(entry)
        client.orders[journal["new_client_id"]] = {
            **parent["legs"][-1],
            "id": str(uuid4()),
            "client_order_id": journal["new_client_id"],
            "status": "canceled",
        }

        def open_orders(filter: Any) -> list[dict[str, Any]]:
            from backend.execution.alpaca_executor import parse_order

            assert filter.status.value == "open" and filter.nested
            return [row for row in client.orders.values() if parse_order(row).is_open]

        # OPEN inventory excludes terminal history, but client-ID lookup must
        # still find it and prevent reuse without a durable managed intent.
        monkeypatch.setattr(client, "get_orders", open_orders)
        with pytest.raises(ReconciliationError) as refused:
            await built._repair_stop_attempt(entry, journal, restore=False)
        assert type(refused.value) is ReconciliationError
        assert (
            str(refused.value) == "Journaled protection client ID exists without its durable intent"
        )
        assert len(client.posts) == 1
        assert built._protection_repairs() and not built.modes.entries_enabled
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("outcome", ["reject", "ambiguous-missing"])
async def test_AX_27_persisted_repair_refusal_or_ambiguity_never_reposts_the_same_id(
    harness: Harness, outcome: str
) -> None:
    from backend.core.errors import OrderRejectedError

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        await built._cancel_sells(entry)
        client.failure = outcome
        first_type = OrderRejectedError if outcome == "reject" else ProviderError
        with pytest.raises(first_type) as first:
            await built._repair_stop_attempt(entry, journal, restore=False)
        assert type(first.value) is first_type
        assert str(first.value) == (
            "Broker rejected the order; client-ID lookup confirmed no order"
            if outcome == "reject"
            else "Order was refused or remains unconfirmed; no retry"
        )
        posts = len(client.posts)
        assert posts == 2
        client.failure = None
        error_type = OrderRejectedError if outcome == "reject" else ReconciliationError
        with pytest.raises(error_type) as refused:
            await built._repair_stop_attempt(entry, journal, restore=False)
        assert type(refused.value) is error_type
        assert str(refused.value) == (
            "Journaled protection attempt was refused; never resubmit its client ID"
            if outcome == "reject"
            else "Journaled protection outcome is unresolved; no duplicate submit"
        )
        assert len(client.posts) == posts
        assert built._protection_repairs() and not built.modes.entries_enabled
        # The independent veto remains active while resolution is outstanding.
        with pytest.raises(ExecutionDisabledError) as veto:
            await built.enter(alert.proposal_id)
        assert type(veto.value) is ExecutionDisabledError
        assert str(veto.value) == "Open protection repair blocks entry"
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("condition", ["open_buy", "held", "repair_resumed"])
async def test_AX_27_exit_cancel_requires_current_authority_and_keeps_protection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    cancellations: list[str] = []

    def cancel(identity: Any) -> None:
        cancellations.append(str(identity))
        raise AssertionError("Unauthorized cancellation reached the broker")

    try:
        await built.enter(alert.proposal_id)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        if condition != "open_buy":
            await fill_entry(harness, client, built)
        if condition == "repair_resumed":
            assert entry.stop_price is not None
            built._begin_protection_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
            built.modes.resume(operator="offline owner", phrase="RESUME")
        monkeypatch.setattr(client, "_cancel_paper", cancel)
        with pytest.raises(ReconciliationError) as caught:
            await built._cancel_sells(entry)
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == (
            "Repair cancellation requires a durable entry block"
            if condition == "repair_resumed"
            else "Exit cancellation requires terminal, flatten or journaled repair proof"
        )
        assert cancellations == [] and len(client.posts) == 1
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["foreign_account", "invalid_phase", "missing_entry"])
async def test_AX_27_repair_audit_replay_scopes_accounts_and_refuses_unverifiable_context(
    harness: Harness, fault: str
) -> None:
    from backend.core.database import SecurityEvent

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        await built._ensure_stop(entry, entry.qty)
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        built._finish_protection_repair(journal, result="LIVE")
        detail = {**journal, "phase": "OPEN"}
        if fault == "foreign_account":
            detail["account_id"] = "another-paper-account"
        elif fault == "invalid_phase":
            detail["phase"] = "UNVERIFIED"
        else:
            detail["entry_id"] = str(uuid4())
            built.modes.downgrade("PAUSE", actor="offline recovery")
        harness.state.ledger.append(SecurityEvent, kind="PROTECTION_REPAIR", detail=detail)
        if fault == "foreign_account":
            assert built._protection_repairs() == ()
            await built.reconcile()
            assert harness.state.current() == SystemState.RUNNING and built.modes.entries_enabled
        else:
            with pytest.raises(ReconciliationError) as caught:
                await built._resume_protection_repairs()
            assert type(caught.value) is ReconciliationError
            assert str(caught.value) == (
                "Protection repair journal has an invalid phase"
                if fault == "invalid_phase"
                else "Open protection repair has no managed entry"
            )
        assert len(client.posts) == 1
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_zero_fill_repair_cannot_submit_a_sell_or_claim_a_flat_held_position(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        with pytest.raises(ReconciliationError) as caught:
            await built._repair_stop_attempt(entry, journal, restore=True)
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == "Protection repair has no remaining held shares"
        assert len(client.posts) == 1
        await fill_entry(harness, client, built)
        with pytest.raises(ReconciliationError) as nonflat:
            built._finish_protection_repair(journal, result="FLAT")
        assert type(nonflat.value) is ReconciliationError
        assert (
            str(nonflat.value) == "Cannot close a protection repair without confirmed stop coverage"
        )
        assert built._protection_repairs() and not built.modes.entries_enabled
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile"])
@pytest.mark.parametrize("restore", [False, True])
async def test_AX_27_restart_after_live_stop_confirmation_never_resubmits(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, operation: str, restore: bool
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import AppendControl

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    restarted = None
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        built._begin_protection_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
        await built._cancel_sells(entry)
        original_submit = client._submit_paper
        attempted = False

        def submit(request: Any) -> dict[str, Any]:
            nonlocal attempted
            client.failure = "reject" if restore and not attempted else None
            attempted = True
            return original_submit(request)

        def interrupted(journal: dict[str, Any], *, result: str) -> None:
            assert_paper_shares_protected(harness, client)
            raise RuntimeError("offline process stopped before journal close")

        monkeypatch.setattr(client, "_submit_paper", submit)
        monkeypatch.setattr(built, "_finish_protection_repair", interrupted)
        with pytest.raises(RuntimeError) as stopped:
            await built._ensure_stop(entry, entry.qty)
        assert type(stopped.value) is RuntimeError
        assert str(stopped.value) == "offline process stopped before journal close"
        assert len(built._protection_repairs()) == 1
        assert not built.modes.entries_enabled
        posts = len(client.posts)
        assert posts == (3 if restore else 2)
        restarted = executor(harness, client)
        journal = restarted._protection_repairs()[0]
        proved = await restarted._repair_stop_attempt(entry, journal, restore=restore)
        assert proved.is_open and proved.qty - proved.filled_qty == entry.qty
        assert len(client.posts) == posts and restarted._protection_repairs()
        if operation == "monitor":
            await restarted.monitor()
        else:
            await restarted.reconcile()
        assert restarted._protection_repairs() == () and restarted.modes.entries_enabled
        assert len(client.posts) == posts
        assert harness.state.current() == SystemState.RUNNING
        assert_paper_shares_protected(harness, client)
        with Session(harness.state.engine) as session:
            before = session.scalar(select(AppendControl.next_seq))
        restarted._finish_protection_repair(journal, result="LIVE")
        with Session(harness.state.engine) as session:
            assert session.scalar(select(AppendControl.next_seq)) == before
        harness.state.ledger.verify_chain()
    finally:
        await built.close()
        if restarted is not None:
            await restarted.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile"])
async def test_AX_27_resumed_host_cannot_make_an_unfinished_repair_silent(
    harness: Harness, operation: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    notices: list[tuple[str, bool]] = []

    async def notify(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        built._begin_protection_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
        built.modes.resume(operator="offline owner", phrase="RESUME")
        built.notify = notify
        with pytest.raises(ReconciliationError) as caught:
            if operation == "monitor":
                await built.monitor()
            else:
                await built.reconcile()
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == (
            "Automatic monitor failed closed"
            if operation == "monitor"
            else "Broker reconciliation failed closed"
        )
        assert type(caught.value.__context__) is ReconciliationError
        assert (
            str(caught.value.__context__)
            == "Open protection repair has lost its durable entry block"
        )
        assert notices[0] == (
            "PAPER · HALTED: unfinished protection repair lost its entry block.",
            True,
        )
        assert harness.state.current() == SystemState.HALTED
        assert not built.modes.entries_enabled and built._protection_repairs()
        assert len(client.posts) == 1
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fill_stage", ["before_submit", "confirmation"])
async def test_AX_27_repair_captures_another_partial_fill_and_restores_exact_coverage(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fill_stage: str
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        root, first_fill = await fill_entry(harness, client, built, partial=True)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        injected = False

        def additional_fill() -> None:
            nonlocal injected
            assert built._protection_repairs() and not built.modes.entries_enabled
            injected = True
            root["filled_qty"] = "2"
            client.positions[0]["qty"] = "2"
            built.observe_fill(
                ObservedFill(
                    account_id="offline-paper",
                    broker_fill_id="during-repair-" + uuid4().hex,
                    broker_order_id=UUID(root["id"]),
                    symbol="NVDA",
                    side=Side.BUY,
                    qty=1,
                    price=first_fill.price,
                    filled_at=harness.clock.now(),
                )
            )

        original_acquire = built.worker.bucket.acquire
        original_lookup = client.get_order_by_id
        original_submit = client._submit_paper

        async def acquire() -> None:
            await original_acquire()
            if injected or fill_stage != "before_submit":
                return
            with Session(harness.state.engine) as session:
                pending = session.scalar(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "REPAIR")
                )
            if pending is not None:
                additional_fill()

        def lookup(identity: Any, filter: object = None) -> dict[str, Any]:
            raw = original_lookup(identity, filter)
            client_id = raw["client_order_id"]
            if (
                not injected
                and fill_stage == "confirmation"
                and client_id.startswith("vws-j-")
                and client_id.endswith("-new")
            ):
                additional_fill()
            return raw

        def submit(request: Any) -> dict[str, Any]:
            assert built._protection_repairs() and not built.modes.entries_enabled
            assert int(request.qty) <= int(client.positions[0]["qty"])
            return original_submit(request)

        monkeypatch.setattr(built.worker.bucket, "acquire", acquire)
        monkeypatch.setattr(client, "get_order_by_id", lookup)
        monkeypatch.setattr(client, "_submit_paper", submit)
        await built._ensure_stop(entry, 1)
        assert injected
        assert built._protection_repairs() == () and built.modes.entries_enabled
        assert harness.state.current() == SystemState.RUNNING
        assert client.posts[-1]["type"] == "stop" and client.posts[-1]["qty"] == "2"
        assert len(client.posts) == (2 if fill_stage == "before_submit" else 3)
        assert sum(row["side"] == "buy" for row in client.posts) == 1
        assert_paper_shares_protected(harness, client)
        await built.monitor()
        assert root["status"] == "canceled"
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_open_repair_with_foreign_sell_halts_before_cancel_or_submit(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.tests.test_auto_execution import journal_existing_partial_repair

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built, partial=True)
        journal_existing_partial_repair(built)
        client.orders["outside-account-order"] = {
            "id": str(uuid4()),
            "client_order_id": "outside-account-order",
            "symbol": "NVDA",
            "side": "sell",
            "type": "limit",
            "order_class": "simple",
            "time_in_force": "day",
            "qty": "1",
            "filled_qty": "0",
            "status": "new",
            "limit_price": "150.00",
            "submitted_at": harness.clock.now().isoformat(),
            "legs": None,
        }
        cancellations: list[Any] = []
        original_cancel = client._cancel_paper

        def cancel(identity: Any) -> None:
            cancellations.append(identity)
            original_cancel(identity)

        monkeypatch.setattr(client, "_cancel_paper", cancel)
        with pytest.raises(ReconciliationError) as caught:
            await built.monitor()
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == "Automatic monitor failed closed"
        assert type(caught.value.__context__) is ReconciliationError
        assert str(caught.value.__context__) == (
            "Unknown broker order forbids a journaled protection repair"
        )
        assert len(client.posts) == 1 and cancellations == []
        assert harness.state.current() == SystemState.HALTED
        assert not built.modes.entries_enabled and built._protection_repairs()
        assert client.orders["outside-account-order"]["status"] == "new"
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "price_delta", [Decimal(-4), Decimal("-0.01"), Decimal(0), Decimal("0.01")]
)
@pytest.mark.parametrize("reject", [False, True])
async def test_EX_05_journaled_raise_repair_keeps_original_fresh_price_contract(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, price_delta: Decimal, reject: bool
) -> None:
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import stop_raise_plan
    from backend.execution.stop_evidence import current_stop
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    notices: list[tuple[str, bool]] = []

    async def notify(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    built.notify = notify
    try:
        await target_filled(harness, built, client)
        assert_paper_shares_protected(harness, client)
        inputs = await built._fresh_exit_inputs(entry)
        assert entry.stop_price is not None
        plan = stop_raise_plan(
            built._held_entry(entry),
            await built._held_observation(entry, inputs),
            built.calendar,
            harness.clock.now(),
            raise_id=uuid4(),
            qty=entry.qty,
            old_stop=entry.stop_price,
            last_trade=inputs.market.last_price,
            quote_at=inputs.market.last_price_ts,
            stale_quote_seconds=harness.settings.stale_quote_seconds,
            trail_atr_mult=Decimal(3),
            config_hash=harness.settings.config_hash,
            yaml_hash=harness.config.config_hash,
        )
        assert plan is not None
        harness.state.ledger.append(
            SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
        )
        await built._cancel_sells(entry)
        harness.source.inputs = harness.source.inputs.model_copy(
            update={
                "market": inputs.market.model_copy(
                    update={"last_price": plan.new_stop + price_delta}
                )
            }
        )
        original_cancel = client._cancel_paper
        original_submit = client._submit_paper

        def cancel(identity: Any) -> None:
            assert not built.modes.entries_enabled and len(built._protection_repairs()) == 1
            original_cancel(identity)

        def submit(request: Any) -> dict[str, Any]:
            assert not built.modes.entries_enabled and len(built._protection_repairs()) == 1
            return original_submit(request)

        monkeypatch.setattr(client, "_cancel_paper", cancel)
        monkeypatch.setattr(client, "_submit_paper", submit)
        client.raise_fault = "reject-both" if reject else None
        before = len(client.posts)
        cannot_restore = plan.old_stop >= harness.source.inputs.market.last_price
        if reject or cannot_restore:
            with pytest.raises(ReconciliationError) as caught:
                await built._raise_repair(entry, plan)
            assert type(caught.value) is ReconciliationError
            assert str(caught.value) == ("Protective stop could not be confirmed; HALTED")
            assert harness.state.current() == SystemState.HALTED
            assert not built.modes.entries_enabled
            assert built._protection_repairs()[0]["phase"] == "FAILED"
            assert notices[-1] == (
                "PAPER · HALTED: journaled protection repair failed for NVDA; entries blocked; inspect broker stops urgently.",
                True,
            )
            assert len(client.posts) - before == (
                0 if cannot_restore else 2 if price_delta > 0 else 1
            )
        else:
            level = await built._raise_repair(entry, plan)
            expected = plan.new_stop if price_delta > 0 else plan.old_stop
            assert level == expected < harness.source.inputs.market.last_price
            assert client.posts[-1] == {
                "symbol": entry.symbol,
                "qty": str(entry.qty),
                "side": "sell",
                "type": "stop",
                "time_in_force": "gtc",
                "stop_price": f"{expected:.2f}",
                "client_order_id": "vws-m-" + plan.raise_id.hex + "-r",
            }
            assert len(client.posts) == before + 1
            assert built._protection_repairs() == () and built.modes.entries_enabled
            assert_paper_shares_protected(harness, client)
            built._stop_moved(plan, "REPAIRED", level)
            with Session(harness.state.engine) as session:
                assert current_stop(session, entry) == expected
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("condition", ["journal", "short_stop", "missing_stop", "closed_healthy"])
async def test_AX_27_entry_veto_is_independent_of_resume_and_checks_account_protection(
    harness: Harness, restart: bool, condition: str
) -> None:
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from backend.core.database import AppendControl, SecurityEvent
    from backend.domain.models import Position
    from backend.tests.test_auto_admission import recorded_imported_card

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    original = built
    try:
        await built.enter(alert.proposal_id)
        raw, fill = await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        if condition in {"journal", "closed_healthy"}:
            for row in built._instructions():
                if row.order_type == "STOP":
                    await built._read_bound(row)
            journal = built._begin_protection_repair(
                entry, entry.qty, entry.stop_price, entry.stop_price
            )
            if condition == "closed_healthy":
                built._finish_protection_repair(journal, result="LIVE")
        elif condition == "short_stop":
            stop = next(row for row in raw["legs"] if row["type"] == "stop")
            stop["qty"] = str(fill.qty - 1)
        else:
            for row in raw["legs"]:
                row["status"] = "canceled"
        if restart:
            built = executor(harness, client)
        built.modes.resume(operator="offline owner", phrase="RESUME")
        assert built.modes.entries_enabled
        order = recorded_imported_card(harness, "valid", symbol="JNJ")
        harness.source.inputs = harness.source.inputs.model_copy(
            update={
                "market": harness.source.inputs.market.model_copy(
                    update={"last_price": Decimal(100)}
                ),
                "portfolio": harness.source.inputs.portfolio.model_copy(
                    update={
                        "equity": Decimal(100000),
                        "cash": Decimal(99000),
                        "settled_cash": Decimal(99000),
                        "high_water_mark": Decimal(100000),
                        "day_start_equity": Decimal(100000),
                        "positions": {
                            entry.symbol: Position(
                                qty=fill.qty, avg_cost=fill.price, last_price=fill.price
                            )
                        },
                    }
                ),
            }
        )
        posts_before = len(client.posts)
        instructions_before = tuple(row.id for row in built._instructions())
        with Session(harness.state.engine) as session:
            before_seq = session.scalar(select(func.max(SecurityEvent.seq))) or 0
            before_next = session.get(AppendControl, 1)
            assert before_next is not None
            next_seq = before_next.next_seq
        if condition == "closed_healthy":
            await built.enter(order.proposal_id)
            assert len(client.posts) == posts_before + 1
            assert client.posts[-1]["symbol"] == "JNJ"
            assert_paper_shares_protected(harness, client)
        else:
            with pytest.raises(ExecutionDisabledError) as refused:
                await built.enter(order.proposal_id)
            expected = {
                "journal": "Open protection repair blocks entry",
                "short_stop": "Protection veto: NVDA held shares exceed protected shares",
                "missing_stop": "Protection veto: NVDA has held shares but no active stop",
            }[condition]
            assert type(refused.value) is ExecutionDisabledError
            assert str(refused.value) == expected
            assert len(client.posts) == posts_before
            assert tuple(row.id for row in built._instructions()) == instructions_before
            with Session(harness.state.engine) as session:
                added = tuple(
                    session.scalars(select(SecurityEvent).where(SecurityEvent.seq > before_seq))
                )
                assert len(added) == 1
                assert added[0].kind == "AUTO_ENTRY_BLOCKED"
                assert added[0].detail == {
                    "proposal_id": str(order.proposal_id),
                    "reason": expected,
                }
                after_next = session.get(AppendControl, 1)
                assert after_next is not None and after_next.next_seq == next_seq + 1
            if condition == "journal" and restart:
                # The resumed host remains vetoed until the durable journal is
                # actually closed with confirmed coverage, including on restart.
                built._finish_protection_repair(journal, result="LIVE")
                await built.enter(order.proposal_id)
                assert len(client.posts) == posts_before + 1
                assert client.posts[-1]["symbol"] == "JNJ"
                assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()
        if built is not original:
            await original.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_host_resume_cannot_admit_a_buy_during_an_open_protection_repair(
    harness: Harness,
) -> None:
    from backend.domain.models import Position
    from backend.tests.test_auto_admission import recorded_imported_card

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        raw, fill = await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        built._begin_protection_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
        await built._cancel_sells(entry)
        assert not built.modes.entries_enabled
        assert len(built._protection_repairs()) == 1
        assert all(row["status"] == "canceled" for row in raw["legs"])
        assert int(client.positions[0]["qty"]) == fill.qty > 0

        # A genuine host RESUME must not erase an independent repair obligation.
        built.modes.resume(operator="offline owner", phrase="RESUME")
        order = recorded_imported_card(harness, "valid", symbol="JNJ")
        harness.source.inputs = harness.source.inputs.model_copy(
            update={
                "market": harness.source.inputs.market.model_copy(
                    update={"last_price": Decimal(100)}
                ),
                "portfolio": harness.source.inputs.portfolio.model_copy(
                    update={
                        "equity": Decimal(100000),
                        "cash": Decimal(99000),
                        "settled_cash": Decimal(99000),
                        "high_water_mark": Decimal(100000),
                        "day_start_equity": Decimal(100000),
                        "positions": {
                            entry.symbol: Position(
                                qty=fill.qty, avg_cost=fill.price, last_price=fill.price
                            )
                        },
                    }
                ),
            }
        )
        posts_before = len(client.posts)
        with pytest.raises(ExecutionDisabledError) as refused:
            await built.enter(order.proposal_id)
        assert type(refused.value) is ExecutionDisabledError
        assert str(refused.value) == "Open protection repair blocks entry"
        harness.state.ledger.verify_chain()
        assert len(built._protection_repairs()) == 1
        assert len(client.posts) == posts_before, (
            "An unresolved repair must block a new BUY even after host RESUME"
        )
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fill_at", [0, 1, 2, 3])
@pytest.mark.parametrize(
    "operations",
    [
        ("monitor", "reconcile", "monitor", "reconcile"),
        ("reconcile", "monitor", "reconcile", "monitor"),
    ],
)
async def test_AX_27_monitor_reconcile_state_walk_always_covers_held_shares(
    harness: Harness, fill_at: int, operations: tuple[str, ...]
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        assert_paper_shares_protected(harness, client)
        for step, operation in enumerate(operations):
            if step == fill_at:
                await fill_entry(harness, client, built)
                assert_paper_shares_protected(harness, client)
            if operation == "monitor":
                await built.monitor()
            else:
                await built.reconcile()
            assert_paper_shares_protected(harness, client)
            assert built._protection_repairs() == ()
            assert built.modes.entries_enabled
            assert harness.state.current() == SystemState.RUNNING
        assert len(client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("close_first", [0, 1])
@pytest.mark.parametrize("operator_pause", [False, True])
async def test_AX_27_all_account_repairs_must_finish_before_owned_pause_is_released(
    harness: Harness, close_first: int, operator_pause: bool
) -> None:
    from backend.tests.test_v_stop_raises import entered

    built, client, _ = await entered(harness)
    try:
        assert_paper_shares_protected(harness, client)
        for instruction in built._instructions():
            if instruction.order_type == "STOP":
                assert await built._read_bound(instruction) is not None
        entries = [row for row in built._instructions() if row.role == "ENTRY"]
        journals = []
        for entry in entries:
            assert entry.stop_price is not None
            journals.append(
                built._begin_protection_repair(entry, entry.qty, entry.stop_price, entry.stop_price)
            )
            assert not built.modes.entries_enabled
        assert journals[0]["pause_actor"] == journals[1]["pause_actor"]
        built._finish_protection_repair(journals[close_first], result="LIVE")
        assert not built.modes.entries_enabled
        if operator_pause:
            built.modes.downgrade("PAUSE", actor="offline operator")
        built._finish_protection_repair(journals[1 - close_first], result="LIVE")
        assert built._protection_repairs() == ()
        assert built.modes.entries_enabled is (not operator_pause)
        assert_paper_shares_protected(harness, client)
        assert len(client.posts) == 2
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_unconfirmed_gap_cannot_close_its_journal_or_release_entries(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        await built._cancel_sells(entry)
        with pytest.raises(ReconciliationError) as caught:
            built._finish_protection_repair(journal, result="LIVE")
        assert type(caught.value) is ReconciliationError
        assert (
            str(caught.value) == "Cannot close a protection repair without confirmed stop coverage"
        )
        assert len(built._protection_repairs()) == 1
        assert not built.modes.entries_enabled
        assert len(client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("path", ["raise_step", "raise_repair"])
@pytest.mark.parametrize("fault", [None, "reject-once", "reject-both"])
async def test_EX_05_journaled_raise_paths_restore_original_level_and_keep_entries_blocked(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, path: str, fault: str | None
) -> None:
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import stop_raise_plan
    from backend.execution.stop_evidence import current_stop
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    await target_filled(harness, built, client)
    assert entry.stop_price is not None
    assert_paper_shares_protected(harness, client)
    original_cancel = client._cancel_paper
    original_submit = client._submit_paper
    physical: list[str] = []

    def cancel(order_id: Any) -> None:
        assert not built.modes.entries_enabled
        assert len(built._protection_repairs()) == 1
        physical.append("cancel")
        original_cancel(order_id)

    def submit(order_data: Any) -> dict[str, Any]:
        assert not built.modes.entries_enabled
        assert len(built._protection_repairs()) == 1
        physical.append("stop")
        return original_submit(order_data)

    monkeypatch.setattr(client, "_cancel_paper", cancel)
    monkeypatch.setattr(client, "_submit_paper", submit)
    client.raise_fault = fault
    try:
        plan = None
        if path == "raise_repair":
            inputs = await built._fresh_exit_inputs(entry)
            plan = stop_raise_plan(
                built._held_entry(entry),
                await built._held_observation(entry, inputs),
                built.calendar,
                harness.clock.now(),
                raise_id=uuid4(),
                qty=entry.qty,
                old_stop=entry.stop_price,
                last_trade=inputs.market.last_price,
                quote_at=inputs.market.last_price_ts,
                stale_quote_seconds=harness.settings.stale_quote_seconds,
                trail_atr_mult=Decimal(3),
                config_hash=harness.settings.config_hash,
                yaml_hash=harness.config.config_hash,
            )
            assert plan is not None
            harness.state.ledger.append(
                SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
            )
            await built._cancel_sells(entry)
        if fault == "reject-both":
            with pytest.raises(ReconciliationError) as caught:
                if path == "raise_step":
                    await built._raise_step(entry, entry.qty)
                else:
                    assert plan is not None
                    await built._raise_repair(entry, plan)
            assert type(caught.value) is ReconciliationError
            assert str(caught.value) == (
                "Protective stop could not be confirmed; HALTED"
                if path == "raise_repair"
                else "Journaled protection and old-level restoration could not be confirmed; HALTED"
            )
            assert harness.state.current() == SystemState.HALTED
            assert not built.modes.entries_enabled
            assert built._protection_repairs()[0]["phase"] == "FAILED"
        else:
            expected_level = entry.stop_price + (Decimal(4) if fault is None else Decimal(0))
            if path == "raise_step":
                await built._raise_step(entry, entry.qty)
            else:
                assert plan is not None
                level = await built._raise_repair(entry, plan)
                assert level == expected_level
                # The approved repair now closes after live confirmation;
                # the caller records the canonical movement before its next await.
                assert built._protection_repairs() == () and built.modes.entries_enabled
                built._stop_moved(plan, "REPAIRED", level)
                await built._resume_protection_repairs()
            assert built._protection_repairs() == ()
            assert built.modes.entries_enabled
            assert harness.state.current() == SystemState.RUNNING
            assert_paper_shares_protected(harness, client)
            with Session(harness.state.engine) as session:
                assert current_stop(session, entry) == expected_level
            assert client.posts[-1]["stop_price"] == f"{expected_level:.2f}"
        assert physical[0] == "cancel"
        assert physical.count("stop") == (1 if fault is None else 2)
        assert sum(row["side"] == "buy" for row in client.posts) == 2
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile_then_monitor"])
async def test_AX_27_partial_buy_remainder_cancel_preserves_independent_filled_share_stop(
    harness: Harness, operation: str
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import OrderEvent
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side

    track = False
    cancels: list[str] = []

    class ProtectedPartialPaperBroker(FakeTradingClient):
        def _cancel_paper(self, order_id: Any) -> None:
            if track:
                assert_paper_shares_protected(harness, self)
                cancels.append(str(order_id))
            super()._cancel_paper(order_id)
            if track:
                assert_paper_shares_protected(harness, self)

    alert = await deliver(harness)
    client = ProtectedPartialPaperBroker(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        parent = client.orders[entry.client_order_id]
        parent["status"], parent["filled_qty"] = "partially_filled", "1"
        client.positions = [
            {"symbol": entry.symbol, "qty": "1", "side": "long", "asset_class": "us_equity"}
        ]
        await built.prepare_fills((entry.symbol,))
        assert entry.limit_price is not None
        built.observe_fill(
            ObservedFill(
                account_id=entry.account_id,
                broker_fill_id="protected-partial-entry",
                broker_order_id=UUID(parent["id"]),
                symbol=entry.symbol,
                side=Side.BUY,
                qty=1,
                price=entry.limit_price,
                filled_at=harness.clock.now(),
            )
        )
        assert entry.stop_price is not None
        # The partial fill's independent live stop is established inside its
        # durable repair window before remainder-cancellation is exercised.
        built._begin_protection_repair(entry, 1, entry.stop_price, entry.stop_price)
        await built._ensure_stop(entry, 1)
        assert_paper_shares_protected(harness, client)
        independent = client.orders[client.posts[-1]["client_order_id"]]
        assert independent["type"] == "stop" and independent["status"] == "new"
        track = True
        if operation == "reconcile_then_monitor":
            await built.reconcile()
            assert parent["status"] == "partially_filled"
            assert_paper_shares_protected(harness, client)
        await built.monitor()
        assert parent["status"] == "canceled"
        assert independent["status"] == "new"
        assert cancels == [parent["id"]]
        assert len(client.posts) == 2
        assert_paper_shares_protected(harness, client)
        with Session(harness.state.engine) as session:
            states = [
                row.state for row in session.scalars(select(OrderEvent).order_by(OrderEvent.seq))
            ]
        assert states[-2:] == ["CANCEL_REQUESTED", "CANCELED"]
        assert harness.state.current() == SystemState.RUNNING
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile"])
@pytest.mark.parametrize("fault", ["no_active_stop", "short_coverage"])
async def test_AX_27_cycle_fail_safe_halts_before_any_further_cancel(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, operation: str, fault: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        parent, _ = await fill_entry(harness, client, built)
        assert_paper_shares_protected(harness, client)
        stop = next(row for row in parent["legs"] if row["type"] == "stop")
        if fault == "no_active_stop":
            stop["status"] = "suspended"
        else:
            stop["status"], stop["filled_qty"] = "partially_filled", "1"
        cancels: list[str] = []
        alerts: list[tuple[str, bool]] = []

        def forbidden_cancel(order_id: Any) -> None:
            cancels.append(str(order_id))
            raise AssertionError("A protection-gap refusal must not cancel any further exit")

        async def notify(text: str, urgent: bool) -> None:
            alerts.append((text, urgent))

        monkeypatch.setattr(client, "_cancel_paper", forbidden_cancel)
        built.notify = notify
        with pytest.raises(ReconciliationError) as caught:
            if operation == "monitor":
                await built.monitor()
            else:
                await built.reconcile()
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == (
            "Automatic monitor failed closed"
            if operation == "monitor"
            else "Broker reconciliation failed closed"
        )
        assert type(caught.value.__context__) is ReconciliationError
        assert (
            str(caught.value.__context__) == "Held shares exceed confirmed broker stop protection"
        )
        assert cancels == [] and len(client.posts) == 1
        assert harness.state.current() == SystemState.HALTED
        assert not built.modes.entries_enabled
        assert alerts[0] == (
            "PAPER · HALTED: NVDA held shares exceed confirmed broker stop protection; entries blocked; no further automatic cancellation.",
            True,
        )
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile"])
@pytest.mark.parametrize("restoration", ["success", "rejected"])
async def test_AX_27_restart_in_journaled_gap_restores_old_stop_or_halts_without_entries(
    harness: Harness, operation: str, restoration: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    restarted = None
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        assert_paper_shares_protected(harness, client)
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        await built._cancel_sells(entry)
        assert not built.modes.entries_enabled
        # A recognized durable window is the sole exception to the live-stop
        # invariant. It is not treated as an ordinary healthy holding.
        await built._check_cycle_protection()
        assert harness.state.current() == SystemState.RUNNING
        restarted = executor(harness, client)
        assert not restarted.modes.entries_enabled
        client.failure = "reject" if restoration == "rejected" else None
        if restoration == "rejected":
            with pytest.raises(ReconciliationError) as caught:
                if operation == "monitor":
                    await restarted.monitor()
                else:
                    await restarted.reconcile()
            assert type(caught.value) is ReconciliationError
            assert str(caught.value) == (
                "Automatic monitor failed closed"
                if operation == "monitor"
                else "Broker reconciliation failed closed"
            )
            assert harness.state.current() == SystemState.HALTED
            assert not restarted.modes.entries_enabled
            assert restarted._protection_repairs()[0]["phase"] == "FAILED"
        else:
            if operation == "monitor":
                await restarted.monitor()
            else:
                await restarted.reconcile()
            assert restarted._protection_repairs() == ()
            assert restarted.modes.entries_enabled
            assert harness.state.current() == SystemState.RUNNING
            assert_paper_shares_protected(harness, client)
        assert client.posts[-1]["client_order_id"] == journal["old_client_id"]
        assert client.posts[-1]["stop_price"] == journal["old_stop"]
        assert sum(row["side"] == "buy" for row in client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()
        if restarted is not None:
            await restarted.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["none", "new_rejected", "both_rejected"])
async def test_AX_27_journaled_ensure_stop_confirms_new_or_restores_old_and_blocks_entries(
    harness: Harness, fault: str
) -> None:
    from backend.execution.alpaca_executor import ExactLimit, ExactStop

    built = None
    physical: list[str] = []
    attempts = 0

    class RepairPaperBroker(FakeTradingClient):
        def _cancel_paper(self, order_id: Any) -> None:
            assert built is not None and not built.modes.entries_enabled
            assert len(built._protection_repairs()) == 1
            physical.append("cancel")
            super()._cancel_paper(order_id)

        def _submit_paper(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            nonlocal attempts
            assert order_data.side is not None
            if order_data.side.value == "sell":
                assert built is not None and not built.modes.entries_enabled
                assert len(built._protection_repairs()) == 1
                physical.append("stop")
                attempts += 1
                self.failure = (
                    "reject"
                    if fault == "both_rejected" or (fault == "new_rejected" and attempts == 1)
                    else None
                )
            try:
                return super()._submit_paper(order_data)
            finally:
                self.failure = None

    alert = await deliver(harness)
    client = RepairPaperBroker(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        parent, _ = await fill_entry(harness, client, built)
        assert_paper_shares_protected(harness, client)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        # Resume a real durable repair window after the original stop ceases
        # to be active; the entry block precedes this simulated broker change.
        next(row for row in parent["legs"] if row["type"] == "stop")["status"] = "suspended"
        if fault == "both_rejected":
            with pytest.raises(ReconciliationError) as caught:
                await built._ensure_stop(entry, entry.qty)
            assert type(caught.value) is ReconciliationError
            assert (
                str(caught.value)
                == "Journaled protection and old-level restoration could not be confirmed; HALTED"
            )
            assert harness.state.current() == SystemState.HALTED
            assert built._protection_repairs()[0]["phase"] == "FAILED"
            assert not built.modes.entries_enabled
        else:
            await built._ensure_stop(entry, entry.qty)
            assert built._protection_repairs() == ()
            assert built.modes.entries_enabled
            assert harness.state.current() == SystemState.RUNNING
            assert_paper_shares_protected(harness, client)
            assert client.posts[-1]["stop_price"] == journal["old_stop"]
        assert attempts == (1 if fault == "none" else 2)
        assert physical[0] == "cancel"
        assert physical.count("stop") == attempts
        assert sum(row["side"] == "buy" for row in client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("interruption", ["restart", "operator_pause", "halt"])
async def test_AX_27_repair_pause_is_durable_owned_and_never_erases_operator_controls(
    harness: Harness, interruption: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    restarted = None
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        for instruction in built._instructions():
            if instruction.order_type == "STOP":
                assert await built._read_bound(instruction) is not None
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        assert built.modes.entries_enabled
        journal = built._begin_protection_repair(
            entry, entry.qty, entry.stop_price, entry.stop_price
        )
        assert not built.modes.entries_enabled
        with pytest.raises(ExecutionDisabledError) as blocked:
            await built.enter(uuid4())
        assert type(blocked.value) is ExecutionDisabledError
        assert str(blocked.value) == "Open protection repair blocks entry"
        restarted = executor(harness, client)
        assert not restarted.modes.entries_enabled
        assert restarted._protection_repairs() == (journal,)
        if interruption == "operator_pause":
            restarted.modes.downgrade("PAUSE", actor="offline operator")
        elif interruption == "halt":
            harness.state.escalate(SystemState.HALTED, "Offline operator HALT during repair")
        restarted._finish_protection_repair(journal, result="LIVE")
        assert restarted._protection_repairs() == ()
        assert restarted.modes.entries_enabled is (interruption == "restart")
        if interruption == "halt":
            assert harness.state.current() == SystemState.HALTED
        assert_paper_shares_protected(harness, client)
        assert len(client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()
        if restarted is not None:
            await restarted.close()


def assert_paper_shares_protected(h: Harness, client: FakeTradingClient) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.execution.storage import held_quantity

    with Session(h.state.engine) as session:
        held = sum(
            held_quantity(session, row.id)
            for row in session.scalars(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
            )
        )
    broker = sum(int(row["qty"]) for row in client.positions)
    protected = sum(
        int(row["qty"]) - int(row["filled_qty"])
        for parent in client.orders.values()
        for row in (parent, *(parent["legs"] or ()))
        if row["type"] == "stop" and row["status"] in {"new", "accepted", "partially_filled"}
    )
    assert held == broker
    assert protected >= held


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile"])
@pytest.mark.parametrize("ending", ["late_fill", "terminal_cancel"])
async def test_AX_24_working_entry_cycles_preserve_future_fill_protection_and_terminal_cleanup(
    harness: Harness, operation: str, ending: str
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import OrderEvent

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        assert_paper_shares_protected(harness, client)
        for _ in range(2):
            if operation == "monitor":
                await built.monitor()
            else:
                await built.reconcile()
            assert_paper_shares_protected(harness, client)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        if ending == "late_fill":
            await fill_entry(harness, client, built)
        else:
            assert (
                await built._finalize_entry_cancellation(entry, reason="Offline terminal cleanup")
                == "CANCELED"
            )
        assert_paper_shares_protected(harness, client)
        if operation == "monitor":
            await built.monitor()
        else:
            await built.reconcile()
        assert_paper_shares_protected(harness, client)
        with Session(harness.state.engine) as session:
            latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()).limit(1))
            assert latest is not None
            assert latest.state == ("FILLED" if ending == "late_fill" else "CANCELED")
        assert len(client.posts) == 1
        assert harness.state.current() == SystemState.RUNNING
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["monitor", "reconcile"])
async def test_AX_24_working_unfilled_entry_keeps_its_contingent_broker_protection(
    harness: Harness, operation: str
) -> None:
    from backend.execution.alpaca_executor import parse_order

    cancels: list[str] = []

    class AuditedPaperBroker(FakeTradingClient):
        def _cancel_paper(self, order_id: Any) -> None:
            cancels.append(str(order_id))
            super()._cancel_paper(order_id)

    alert = await deliver(harness)
    client = AuditedPaperBroker(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        parent = next(raw for raw in client.orders.values() if raw["side"] == "buy")
        assert parent["status"] == "new" and parent["filled_qty"] == "0"
        assert [child["status"] for child in parent["legs"]] == ["held", "held"]
        assert harness.state.current() == SystemState.RUNNING
        if operation == "monitor":
            await built.monitor()
        else:
            await built.reconcile()
        actual = {
            "cancel_requests": len(cancels),
            "parent_status": parent["status"],
            "parent_open": parse_order(parent).is_open,
            "child_statuses": [child["status"] for child in parent["legs"]],
            "state": harness.state.current().value,
            "entry_submissions": sum(row["side"] == "buy" for row in client.posts),
        }
        harness.state.ledger.verify_chain()
        assert actual == {
            "cancel_requests": 0,
            "parent_status": "new",
            "parent_open": True,
            "child_statuses": ["held", "held"],
            "state": "RUNNING",
            "entry_submissions": 1,
        }
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["pending_worker", "inactive_previous", "low_price"])
async def test_EX_05_repair_respects_unresolved_work_durable_identity_and_price(
    harness: Harness, fault: str
) -> None:
    import asyncio
    import threading

    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import stop_raise_plan
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    await target_filled(harness, built, client)
    inputs = await built._fresh_exit_inputs(entry)
    assert entry.stop_price is not None
    plan = stop_raise_plan(
        built._held_entry(entry),
        await built._held_observation(entry, inputs),
        built.calendar,
        harness.clock.now(),
        raise_id=uuid4(),
        qty=entry.qty,
        old_stop=entry.stop_price,
        last_trade=inputs.market.last_price,
        quote_at=inputs.market.last_price_ts,
        stale_quote_seconds=harness.settings.stale_quote_seconds,
        trail_atr_mult=Decimal(3),
        config_hash=harness.settings.config_hash,
        yaml_hash=harness.config.config_hash,
    )
    assert plan is not None
    harness.state.ledger.append(
        SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
    )
    if fault == "pending_worker":
        started, release = threading.Event(), threading.Event()

        def slow_paper_read() -> dict[str, Any]:
            started.set()
            assert release.wait(5)
            return client.get_account()

        task = asyncio.create_task(built.worker.attempt(slow_paper_read))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            with pytest.raises(ReconciliationError) as caught:
                await built._raise_repair(entry, plan)
            assert type(caught.value) is ReconciliationError
            assert (
                str(caught.value)
                == "EX-05: unresolved physical attempt forbids a conflicting repair"
            )
            assert len(client.posts) == 2
        finally:
            release.set()
            await task
    else:
        await built._cancel_sells(entry)
        if fault == "low_price":
            harness.source.inputs = harness.source.inputs.model_copy(
                update={"market": inputs.market.model_copy(update={"last_price": plan.new_stop})}
            )
        level = await built._raise_repair(entry, plan)
        assert level == (plan.old_stop if fault == "low_price" else plan.new_stop)
        repair = client.orders[client.posts[-1]["client_order_id"]]
        assert repair["type"] == "stop" and repair["stop_price"] == f"{level:.2f}"
        assert len(client.posts) == 3
        with Session(harness.state.engine) as session:
            assert (
                held_quantity(session, entry.id)
                == int(client.positions[0]["qty"])
                == int(repair["qty"])
                == entry.qty
            )
        if fault == "inactive_previous":
            repair["status"] = "held"
            with pytest.raises(ReconciliationError) as previous_error:
                await built._raise_repair(entry, plan)
            assert type(previous_error.value) is ReconciliationError
            assert str(previous_error.value) == "EX-05: durable repair cannot be repeated"
            assert len(client.posts) == 3
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_quote_expiring_at_physical_raise_restores_old_stop_before_releasing_entries(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Callable
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord, SecurityEvent
    from backend.core.errors import EntryAdmissionRevoked
    from backend.execution.stop_evidence import current_stop
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    await target_filled(harness, built, client)
    acquire = built.worker.bucket.acquire
    original_attempt = built.worker.attempt
    expired = False
    refusals: list[str] = []

    async def expire_after_intent() -> None:
        nonlocal expired
        with Session(harness.state.engine) as session:
            intent = session.scalar(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "REPAIR")
            )
        if intent is not None and not expired:
            expired = True
            harness.clock.current += timedelta(seconds=61)
        await acquire()

    async def observe_real_attempt(
        operation: Callable[[], Any], *, guard: Callable[[], None] = lambda: None
    ) -> Any:
        try:
            return await original_attempt(operation, guard=guard)
        except EntryAdmissionRevoked as error:
            assert type(error) is EntryAdmissionRevoked
            refusals.append(str(error))
            raise

    monkeypatch.setattr(built.worker.bucket, "acquire", expire_after_intent)
    monkeypatch.setattr(built.worker, "attempt", observe_real_attempt)
    await built._raise_step(entry, entry.qty)
    assert refusals == ["EX-05: stop-raise quote expired before submit"]
    assert expired and len(client.posts) == 3
    assert sum(row["side"] == "buy" for row in client.posts) == 2
    stop = client.orders[client.posts[-1]["client_order_id"]]
    assert stop["status"] == "new" and stop["type"] == "stop"
    assert stop["stop_price"] == f"{entry.stop_price:.2f}"
    with Session(harness.state.engine) as session:
        assert (
            held_quantity(session, entry.id)
            == int(client.positions[0]["qty"])
            == int(stop["qty"])
            == entry.qty
        )
        assert current_stop(session, entry) == entry.stop_price
        moves = tuple(
            session.scalars(select(SecurityEvent).where(SecurityEvent.kind == "STOP_MOVED"))
        )
        assert len(moves) == 1 and moves[0].detail["status"] == "REPAIRED"
    assert harness.state.current() == SystemState.RUNNING
    assert built.modes.entries_enabled
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("check", ["entry", "raise_readiness", "raise_working", "raise_account"])
async def test_EX_06_environment_drift_during_evidence_cannot_reach_an_order_write(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, check: str
) -> None:
    from backend.execution.exit_variants import HeldEntry, HeldExitObservation
    from backend.notifications.callbacks import FreshInputs
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    posted = len(client.posts)
    if check == "entry":
        # Isolated binding snapshot only. Settings, persisted modes, endpoints,
        # approvals, orders and the fake client all remain paper-bound.
        monkeypatch.setattr(built.modes, "environment", "LIVE")
        with pytest.raises(ExecutionDisabledError) as caught:
            built._assert_entry_variant()
        assert type(caught.value) is ExecutionDisabledError
        assert (
            str(caught.value)
            == "EX-06: live paper-raise and OCO/OTO integration evidence unavailable"
        )
    else:
        await target_filled(harness, built, client)
        original = built.held_exit_observation
        assert original is not None

        async def binding_changes_during_evidence(
            held: HeldEntry, fresh: FreshInputs
        ) -> HeldExitObservation:
            observation = await original(held, fresh)
            monkeypatch.setattr(built.modes, "environment", "LIVE")
            return observation

        built.held_exit_observation = binding_changes_during_evidence
        if check != "raise_readiness":
            built.stop_raise_readiness = lambda: ()
            built.entry_variant_allowed = lambda: check == "raise_account"
        if check == "raise_account":
            original_account = client.get_account

            def inactive_account() -> dict[str, Any]:
                return {**original_account(), "status": "INACTIVE"}

            monkeypatch.setattr(client, "get_account", inactive_account)
        error_type = ReconciliationError if check == "raise_account" else ExecutionDisabledError
        with pytest.raises(error_type) as raise_error:
            await built._raise_step(entry, entry.qty)
        assert type(raise_error.value) is error_type
        assert str(raise_error.value) == (
            "EX-06: live paper-raise and OCO/OTO integration evidence unavailable"
            if check == "raise_readiness"
            else "EX-06: live stop raises require current WORKING evidence"
            if check == "raise_working"
            else "Alpaca account identity, status or restrictions differ"
        )
    assert len(client.posts) == posted
    assert harness.settings.execution_mode == "AUTO_PAPER" and harness.settings.paper_trading
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["opening_window", "no_raise", "allocation"])
async def test_EX_05_stop_raise_requires_session_price_improvement_and_allocated_shares(
    harness: Harness, fault: str
) -> None:
    from datetime import timedelta

    from backend.execution.exit_variants import HeldEntry, HeldExitObservation
    from backend.notifications.callbacks import FreshInputs
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    await target_filled(harness, built, client)
    posted = len(client.posts)
    assert entry.stop_price is not None
    if fault == "opening_window":
        tomorrow = built.calendar.add_sessions(harness.clock.now().date(), 1)
        harness.clock.current = built.calendar.session_open(tomorrow) + timedelta(minutes=10)
    elif fault == "no_raise":
        original = built.held_exit_observation
        assert original is not None

        async def lower_close(held: HeldEntry, fresh: FreshInputs) -> HeldExitObservation:
            observed = await original(held, fresh)
            return observed.model_copy(update={"close": held.initial_stop + Decimal(1)})

        built.held_exit_observation = lower_close
    else:
        client.positions[0]["qty"] = str(entry.qty + 1)
    if fault == "allocation":
        with pytest.raises(ReconciliationError) as caught:
            await built._raise_step(entry, entry.qty)
        assert type(caught.value) is ReconciliationError
        assert (
            str(caught.value) == "EX-05: allocated broker quantity differs from managed held shares"
        )
    else:
        await built._raise_step(entry, entry.qty)
    assert len(client.posts) == posted
    assert harness.state.current() == SystemState.RUNNING
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["recovery", "panic"])
async def test_SEC_73_unavailable_account_inventory_is_reported_without_guessing(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    notices: list[tuple[str, bool]] = []

    async def notify(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    built.notify = notify
    monkeypatch.setattr(client, "get_all_positions", lambda: {})
    if operation == "panic":
        harness.state.escalate(SystemState.HALTED, "Offline panic inventory unavailable")
        with pytest.raises(ReconciliationError) as caught:
            await built.cancel_unfilled_entries()
        assert type(caught.value) is ReconciliationError
        assert (
            str(caught.value)
            == "Panic cancellation incomplete; unresolved orders: account-reconciliation"
        )
        assert notices[-2:] == [
            (
                "PAPER · Panic reconciliation failed: Broker position collection is unavailable or unbounded",
                True,
            ),
            (
                "PAPER · Panic: canceled 1 orders; filled-and-protected 0 legs; failed 1. HALTED.",
                True,
            ),
        ]
    else:
        await built._recover_verified_protection()
        assert notices == [
            (
                "PAPER · HALTED: recovery cannot prove held protection; inspect broker stops urgently.",
                True,
            )
        ]
    assert harness.state.current() == SystemState.HALTED
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["repair", "reconcile", "panic"])
async def test_AX_27_inactive_replacement_stop_is_a_durable_failure_not_protection(
    harness: Harness, operation: str
) -> None:
    from sqlalchemy.orm import Session

    from backend.execution.alpaca_executor import ExactLimit, ExactStop
    from backend.execution.storage import held_quantity

    class InactivePaperStop(FakeTradingClient):
        def _submit_paper(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            raw = super()._submit_paper(order_data)
            if raw["type"] == "stop":
                raw["status"] = "held"
            return raw

    alert = await deliver(harness)
    client = InactivePaperStop(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built, partial=True)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    notices: list[tuple[str, bool]] = []

    async def notify(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    built.notify = notify
    if operation == "panic":
        harness.state.escalate(SystemState.HALTED, "Paper panic stop failure")
    else:
        await built._finalize_entry_cancellation(entry, reason="Paper remainder canceled")
        if operation == "reconcile":
            # Reconciliation resumes a durable repair. A gap without such a
            # journal is covered separately by the fail-safe refusal tests.
            assert entry.stop_price is not None
            built._begin_protection_repair(entry, 1, entry.stop_price, entry.stop_price)
    with pytest.raises(ReconciliationError) as caught:
        if operation == "repair":
            await built._repair_stop(entry, 1)
        elif operation == "reconcile":
            await built.reconcile()
        else:
            await built.cancel_unfilled_entries()
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == (
        "Protective stop could not be confirmed; HALTED"
        if operation == "repair"
        else "Broker reconciliation failed closed"
        if operation == "reconcile"
        else f"Panic cancellation incomplete; unresolved orders: {entry.id}"
    )
    assert harness.state.current() == SystemState.HALTED
    # Panic must try both the replacement and the explicitly required
    # restoration of the original stop; neither held response proves coverage.
    assert len(client.posts) == (3 if operation == "panic" else 2)
    assert client.posts[-1]["side"] == "sell" and client.posts[-1]["qty"] == "1"
    with Session(harness.state.engine) as session:
        assert held_quantity(session, entry.id) == int(client.positions[0]["qty"]) == 1
    if operation == "panic":
        assert notices[-1] == (
            "PAPER · Panic: canceled 1 orders; filled-and-protected 0 legs; failed 1. HALTED.",
            True,
        )
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("refusal", ["veto", "rejected"])
async def test_EX_01_first_leg_refusal_proves_sibling_was_not_sent(
    harness: Harness, refusal: str
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import (
        ExecutionFillRecord,
        ExecutionOrderRecord,
        OrderEvent,
        SecurityEvent,
    )
    from backend.core.errors import EntryAdmissionRevoked, OrderRejectedError
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    if refusal == "rejected":
        client.failure = "reject"
    else:

        def veto_after_intent() -> None:
            with Session(harness.state.engine) as session:
                if session.scalar(select(ExecutionOrderRecord.id)) is not None:
                    raise ExecutionDisabledError("Paper final admission veto")

        built.configuration_check = veto_after_intent
    try:
        with pytest.raises(ExecutionDisabledError) as caught:
            await built.enter(alert.proposal_id)
        assert type(caught.value) is (
            OrderRejectedError if refusal == "rejected" else EntryAdmissionRevoked
        )
        assert str(caught.value) == (
            "Broker rejected the order; client-ID lookup confirmed no order"
            if refusal == "rejected"
            else "Paper final admission veto"
        )
        with Session(harness.state.engine) as session:
            latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()).limit(1))
            assert latest is not None and latest.state == "CANCELED"
            outcomes = [
                row.detail
                for row in session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
                    .order_by(SecurityEvent.seq)
                )
            ]
            assert [row["outcome"] for row in outcomes] == (
                ["REJECTED", "NOT_SENT"] if refusal == "rejected" else ["NOT_SENT", "NOT_SENT"]
            )
            assert all(row["error_type"] != "NONE" for row in outcomes)
            assert tuple(session.scalars(select(ExecutionFillRecord))) == ()
        assert client.orders == {} and client.positions == []
        assert len(client.posts) == (1 if refusal == "rejected" else 0)
        built.configuration_check = None
        harness.state.escalate(SystemState.HALTED, "offline refused split")
        await built.cancel_unfilled_entries()
        assert harness.state.current() == SystemState.HALTED
        assert client.orders == {} and client.positions == []
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_failure_budget_ignores_other_accounts_and_no_send_without_erasing_failures(
    harness: Harness,
) -> None:
    from typing import cast

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.clock import FrozenClock
    from backend.core.database import ExecutionOrderRecord, SystemEvent
    from backend.tests.test_execution_storage import append_execution_fixture

    _, historical, _ = append_execution_fixture(
        harness.state.ledger, cast(FrozenClock, harness.clock)
    )

    class HistoricalPaperBroker(FakeTradingClient):
        def get_account(self) -> dict[str, Any]:
            return {**super().get_account(), "id": "paper-fixture"}

    client = FakeTradingClient(harness)
    current = executor(harness, client)
    previous = executor(harness, HistoricalPaperBroker(harness), account_id="paper-fixture")
    try:
        alert = await deliver(harness)
        await current.enter(alert.proposal_id)
        with Session(harness.state.engine) as session:
            entry = session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.account_id == "offline-paper",
                    ExecutionOrderRecord.role == "ENTRY",
                )
            )
            assert entry is not None
        previous._outcome(historical, "ERROR", ProviderError("Historical paper error"))
        current._outcome(entry, "ERROR", ProviderError("Current paper error"))
        current._outcome(entry, "NOT_SENT", ExecutionDisabledError("Paper request not sent"))
        current._outcome(entry, "ERROR", ProviderError("Current paper error"))
        assert harness.state.current() == SystemState.RUNNING
        current._outcome(entry, "ERROR", ProviderError("Current paper error"))
        assert harness.state.current() == SystemState.HALTED
        with Session(harness.state.engine) as session:
            halt = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1))
            assert halt is not None
            assert (
                halt.reason
                == "AX-31 consecutive order failures; manual trading belongs in a different account"
            )
        assert len(client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await current.close()
        await previous.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("quantity", [1, 9])
async def test_EX_01_legacy_fill_writer_cannot_finalize_a_shared_auto_order(
    harness: Harness, quantity: int
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import LEDGER_MODELS, ExecutionOrderRecord, Fill
    from backend.core.errors import LedgerIntegrityError
    from backend.core.ledger import canonical_json
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)

    def rows() -> list[tuple[int, str, str]]:
        with Session(harness.state.engine) as session:
            return sorted(
                (row.seq, canonical_json(row), row.row_hash)
                for model in LEDGER_MODELS
                for row in session.scalars(select(model))
            )

    try:
        await built.enter(alert.proposal_id)
        with Session(harness.state.engine) as session:
            entry = session.scalar(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
            )
            assert entry is not None
        before = rows()
        with pytest.raises(LedgerIntegrityError) as caught:
            harness.state.ledger.append(
                Fill,
                order_id=entry.order_id,
                broker_fill_id="refused-legacy-auto-overwrite",
                qty=quantity,
                price=entry.limit_price,
                filled_at=harness.clock.now(),
            )
        assert type(caught.value) is LedgerIntegrityError
        assert str(caught.value) == "Auto fills require their exact execution instruction"
        assert rows() == before
        assert client.positions == [] and len(client.posts) == 2
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_01_pending_fills_preserve_intent_and_terminal_orders_refuse_new_fills(
    harness: Harness,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import (
        LEDGER_MODELS,
        ExecutionFillRecord,
        ExecutionOrderRecord,
        OrderEvent,
    )
    from backend.core.errors import LedgerIntegrityError
    from backend.core.ledger import canonical_json
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)

    def rows() -> list[tuple[int, str, str]]:
        with Session(harness.state.engine) as session:
            return sorted(
                (row.seq, canonical_json(row), row.row_hash)
                for model in LEDGER_MODELS
                for row in session.scalars(select(model))
            )

    try:
        await built.enter(alert.proposal_id)
        with Session(harness.state.engine) as session:
            entry = session.scalar(
                select(ExecutionOrderRecord)
                .where(ExecutionOrderRecord.role == "ENTRY")
                .order_by(ExecutionOrderRecord.seq)
                .limit(1)
            )
            assert entry is not None
        harness.state.ledger.append(
            OrderEvent,
            order_id=entry.order_id,
            state="CANCEL_REQUESTED",
            reason="offline durable intent",
            broker_order_id=None,
        )
        root, _ = await fill_entry(harness, client, built, partial=True)
        with Session(harness.state.engine) as session:
            assert (
                tuple(session.scalars(select(OrderEvent.state).order_by(OrderEvent.seq)))[-1]
                == "CANCEL_REQUESTED"
            )
            assert sum(row.qty for row in session.scalars(select(ExecutionFillRecord))) == 1
        for forbidden in ("REJECTED", "PARTIALLY_FILLED"):
            before = rows()
            with pytest.raises(LedgerIntegrityError) as caught:
                harness.state.ledger.append(
                    OrderEvent,
                    order_id=entry.order_id,
                    state=forbidden,
                    reason="offline forbidden transition",
                    broker_order_id=None,
                )
            assert type(caught.value) is LedgerIntegrityError
            assert str(caught.value) == "Invalid appended order lifecycle transition"
            assert rows() == before
        harness.state.ledger.append(
            OrderEvent,
            order_id=entry.order_id,
            state="CANCELED",
            reason="offline terminal guard proof",
            broker_order_id=None,
        )
        before = rows()
        with pytest.raises(LedgerIntegrityError) as caught:
            harness.state.ledger.append(
                ExecutionFillRecord,
                execution_order_id=entry.id,
                broker_fill_id="refused-after-terminal",
                qty=int(root["qty"]) - 1,
                price=Decimal(root["limit_price"]),
                filled_at=harness.clock.now(),
            )
        assert type(caught.value) is LedgerIntegrityError
        assert str(caught.value) == "Invalid appended order lifecycle transition"
        assert rows() == before
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("timing", ["before", "during", "after"])
async def test_EX_01_rejection_timing_cannot_finalize_away_the_other_leg_fill(
    harness: Harness, reverse: bool, timing: str
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord, OrderEvent
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        with Session(harness.state.engine) as session:
            entries = tuple(
                session.scalars(
                    select(ExecutionOrderRecord)
                    .where(ExecutionOrderRecord.role == "ENTRY")
                    .order_by(ExecutionOrderRecord.seq)
                )
            )
        roots = list(client.orders.values())
        accepted, rejected = (roots[1], roots[0]) if reverse else (roots[0], roots[1])
        accepted_entry = entries[1] if reverse else entries[0]

        async def reject() -> None:
            rejected["status"] = "rejected"
            rejected["reject_reason"] = "Paper sibling rejection"
            rejected["failed_at"] = harness.clock.now().isoformat()
            for child in rejected["legs"]:
                child["status"] = "canceled"
            await built._read_bound(entries[0] if reverse else entries[1])
            await built._finalize_entry_cancellation(
                accepted_entry, reason="paper rejection timing", cancel_open=False
            )

        if timing == "before":
            await reject()
        accepted["status"], accepted["filled_qty"] = "filled", accepted["qty"]
        for child in accepted["legs"]:
            child["status"] = "new"
        client.positions = [
            {"symbol": "NVDA", "qty": accepted["qty"], "side": "long", "asset_class": "us_equity"}
        ]
        if timing == "during":
            await reject()
        built.observe_fill(
            ObservedFill(
                account_id="offline-paper",
                broker_fill_id="paper-rejection-timing",
                broker_order_id=UUID(accepted["id"]),
                symbol="NVDA",
                side=Side.BUY,
                qty=int(accepted["qty"]),
                price=Decimal(accepted["limit_price"]),
                filled_at=harness.clock.now(),
            )
        )
        if timing == "after":
            await reject()
        harness.state.escalate(SystemState.HALTED, "offline split rejection timing")
        await built.cancel_unfilled_entries()
        with Session(harness.state.engine) as session:
            held = sum(held_quantity(session, row.id) for row in entries)
            latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()).limit(1))
            assert latest is not None and latest.state == "CANCELED"
        protected = sum(
            int(row["qty"])
            for root in roots
            for row in root["legs"]
            if row["type"] == "stop" and row["status"] == "new"
        )
        assert (
            held
            == sum(int(row["qty"]) for row in client.positions)
            == protected
            == (5 if reverse else 4)
        )
        assert len(client.posts) == 2 and harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "panic_cancel_timeout_seconds": 1}], indirect=True)
@pytest.mark.parametrize("fault", ["pending", "read"])
async def test_SEC_73_pending_cancel_timeout_processes_other_leg_and_resumes_after_restart(
    harness: Harness,
    fault: str,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import LEDGER_MODELS, ExecutionOrderRecord, OrderEvent, SecurityEvent
    from backend.core.ledger import canonical_json
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    canceled: list[str] = []

    class PendingPaperBroker(FakeTradingClient):
        release = False

        def cancel_order_by_id(self, order_id: Any) -> None:
            first = next(iter(self.orders.values()))
            if first["id"] == str(order_id):
                canceled.append(str(order_id))
                first["status"] = "pending_cancel"
                return
            canceled.append(str(order_id))
            super()._cancel_paper(order_id)

        def get_order_by_id(self, order_id: Any, filter: object = None) -> dict[str, Any]:
            first = next(iter(self.orders.values()))
            if fault == "read" and not self.release and first["id"] == str(order_id):
                raise TimeoutError("Paper first leg is unavailable")
            if self.release and first["id"] == str(order_id):
                first["status"] = "canceled"
                for child in first["legs"]:
                    child["status"] = "canceled"
            return super().get_order_by_id(order_id, filter)

    settings = harness.settings
    alert = await deliver(harness)
    client = PendingPaperBroker(harness)
    built = executor(harness, client, settings)
    notices: list[str] = []

    async def notice(text: str, urgent: bool) -> None:
        notices.append(text)

    built.notify = notice
    try:
        await built.enter(alert.proposal_id)
        harness.state.escalate(SystemState.HALTED, "offline bounded panic")
        with pytest.raises(ReconciliationError) as caught:
            await built.cancel_unfilled_entries()
        roots = list(client.orders.values())
        with Session(harness.state.engine) as session:
            latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()).limit(1))
            assert latest is not None and latest.state == "CANCEL_REQUESTED"
            order_id = latest.order_id
            entries = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
                )
            )
            held = sum(held_quantity(session, row.id) for row in entries)
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == "Panic cancellation incomplete; unresolved orders: " + str(
            order_id
        )
        assert any(
            "Cancellation confirmation unresolved for legs: " + roots[0]["client_order_id"] in text
            for text in notices
        )
        assert (
            notices[-1]
            == "PAPER · Panic: canceled 0 orders; filled-and-protected 0 legs; failed 1. HALTED."
        )
        assert roots[0]["status"] == ("pending_cancel" if fault == "pending" else "new")
        assert roots[1]["status"] == "canceled"
        expected_cancels = (
            [roots[0]["id"], roots[1]["id"]] if fault == "pending" else [roots[1]["id"]]
        )
        assert canceled == expected_cancels
        assert all(child["status"] == "held" for child in roots[0]["legs"])
        assert client.positions == [] and len(client.posts) == 2
        protected = sum(
            int(row["qty"]) - int(row["filled_qty"])
            for root in client.orders.values()
            for row in (root, *(root.get("legs") or ()))
            if row["type"] == "stop" and row["status"] in {"new", "accepted", "partially_filled"}
        )
        assert held == sum(int(row["qty"]) for row in client.positions) == protected == 0
        harness.state.ledger.verify_chain()
    finally:
        await built.close()
    client.release = True
    resumed = executor(harness, client, settings)
    try:
        await resumed.cancel_unfilled_entries()
        with Session(harness.state.engine) as session:
            events = tuple(session.scalars(select(OrderEvent).order_by(OrderEvent.seq)))
            assert (
                events[-1].state == "CANCELED"
                and sum(row.state == "CANCEL_REQUESTED" for row in events) == 1
            )
            summary = session.scalar(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "PANIC_CANCEL_RESULT")
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
            assert summary is not None and summary.detail["failed_orders"] == []
            assert sum(held_quantity(session, row.id) for row in entries) == 0
            before = sorted(
                (row.seq, canonical_json(row), row.row_hash)
                for model in LEDGER_MODELS
                for row in session.scalars(select(model))
            )
        await resumed.cancel_unfilled_entries()
        with Session(harness.state.engine) as session:
            assert (
                sorted(
                    (row.seq, canonical_json(row), row.row_hash)
                    for model in LEDGER_MODELS
                    for row in session.scalars(select(model))
                )
                == before
            )
        assert canceled == expected_cancels
        assert (
            client.positions == []
            and len(client.posts) == 2
            and harness.state.current() == SystemState.HALTED
        )
        harness.state.ledger.verify_chain()
    finally:
        await resumed.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "panic_cancel_timeout_seconds": 1}], indirect=True)
@pytest.mark.parametrize("fault", ["pending", "read"])
async def test_SEC_73_expired_leg_scan_preserves_panic_account_reconciliation(
    harness: Harness, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expire during A's read; B must not consume a second unresolved worker slot."""
    import asyncio

    original_executor = executor
    expired_reads: list[str] = []

    def scheduled_executor(*args: Any, **kwargs: Any) -> Any:
        built = original_executor(*args, **kwargs)
        loop = asyncio.get_running_loop()
        real_time = loop.time
        original_thread = asyncio.to_thread
        release = asyncio.Event()
        expired = False
        expiry = 0.0
        original_cancel = built._cancel_confirmed
        original_read = built._read_bound
        original_panic = built.cancel_unfilled_entries
        original_finalize = built._finalize_entry_cancellation

        async def delayed_thread(function: Any, *args: Any, **kwargs: Any) -> Any:
            closure = dict(
                zip(
                    function.__code__.co_freevars,
                    (cell.cell_contents for cell in function.__closure__ or ()),
                    strict=True,
                )
            )
            operation = closure.get("operation")
            if expired and "_read_bound" in getattr(operation, "__qualname__", ""):
                # Model a physical read that has not completed when its caller expires.
                await release.wait()
            return await original_thread(function, *args, **kwargs)

        async def cancel(instruction: Any, broker: Any, **kwargs: Any) -> Any:
            nonlocal expired
            result = await original_cancel(instruction, broker, **kwargs)
            roots = list(args[1].orders.values())
            if len(roots) == 2 and roots[1]["status"] == "canceled":
                expired = True
            return result

        async def read(instruction: Any) -> Any:
            if expired:
                expired_reads.append(instruction.client_order_id)
                monkeypatch.setattr(loop, "time", lambda: expiry)
            return await original_read(instruction)

        async def finalize(instruction: Any, **kwargs: Any) -> Any:
            nonlocal expiry
            expiry = kwargs["deadline"]
            return await original_finalize(instruction, **kwargs)

        async def panic() -> None:
            try:
                with pytest.MonkeyPatch.context() as scheduling:
                    scheduling.setattr(asyncio, "to_thread", delayed_thread)
                    await original_panic()
            finally:
                monkeypatch.setattr(loop, "time", real_time)
                release.set()

        monkeypatch.setattr(built, "_finalize_entry_cancellation", finalize)
        monkeypatch.setattr(built, "_cancel_confirmed", cancel)
        monkeypatch.setattr(built, "_read_bound", read)
        monkeypatch.setattr(built, "cancel_unfilled_entries", panic)
        return built

    from backend.tests import test_auto_safety as safety_tests

    monkeypatch.setattr(safety_tests, "executor", scheduled_executor)
    # Retain every exact-message, held/protected, durable-HALT, restart and no-op assertion.
    await test_SEC_73_pending_cancel_timeout_processes_other_leg_and_resumes_after_restart(
        harness, fault
    )
    assert len(expired_reads) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_SEC_73_expired_cancel_deadline_does_not_start_broker_work(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import re

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import OrderEvent
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    loop = asyncio.get_running_loop()
    real_time = loop.time
    try:
        await built.enter(alert.proposal_id)
        harness.state.escalate(SystemState.HALTED, "offline expired panic deadline")
        entries = tuple(row for row in built._instructions() if row.role == "ENTRY")

        def forbidden_read(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("An expired cancellation must not start another broker read")

        monkeypatch.setattr(client, "get_order_by_id", forbidden_read)
        expected = "Cancellation confirmation unresolved for legs: " + ", ".join(
            row.client_order_id for row in entries
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        real_time = loop.time
        monkeypatch.setattr(loop, "time", lambda: deadline)
        with pytest.raises(ReconciliationError, match="^" + re.escape(expected) + "$") as caught:
            await built._finalize_entry_cancellation(
                entries[0],
                reason="offline expired panic",
                deadline=deadline,
            )
        monkeypatch.setattr(loop, "time", real_time)
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == expected
        assert not built.worker.has_pending_attempts
        with Session(harness.state.engine) as session:
            latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()).limit(1))
            assert latest is not None and latest.state == "CANCEL_REQUESTED"
            assert sum(held_quantity(session, row.id) for row in entries) == 0
        assert client.positions == [] and len(client.posts) == 2
        assert all(root["status"] == "new" for root in client.orders.values())
        assert all(
            child["status"] == "held" for root in client.orders.values() for child in root["legs"]
        )
        assert harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        monkeypatch.setattr(loop, "time", real_time)
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
async def test_EX_01_both_rejections_keep_leg_reasons_and_classify_pending_cancellation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, pending: bool, reverse: bool
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionFillRecord, OrderEvent, SecurityEvent
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    rejected_at = harness.clock.now().isoformat()

    class RejectBothPaperBroker(FakeTradingClient):
        def reject(self) -> None:
            for suffix, root in zip(("A", "B"), self.orders.values(), strict=True):
                root["status"] = "rejected"
                root["reject_reason"] = "Paper broker rejected " + suffix
                root["failed_at"] = rejected_at
                for child in root["legs"]:
                    child["status"] = "canceled"

        def cancel_order_by_id(self, order_id: Any) -> None:
            self.reject()

    alert = await deliver(harness)
    client = RejectBothPaperBroker(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        ordered = built._instructions
        if reverse:
            monkeypatch.setattr(built, "_instructions", lambda: tuple(reversed(ordered())))
        if not pending:
            client.reject()
        harness.state.escalate(SystemState.HALTED, "offline broker rejection evidence")
        await built.cancel_unfilled_entries()
        with Session(harness.state.engine) as session:
            events = tuple(session.scalars(select(OrderEvent).order_by(OrderEvent.seq)))
            assert events[-1].state == ("CANCELED" if pending else "REJECTED")
            assert events[-1].reason.endswith("; both legs broker-rejected")
            assert sum(event.state == "CANCEL_REQUESTED" for event in events) == int(pending)
            rejections = [
                row.detail
                for row in session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_ORDER_OBSERVED")
                )
                if row.detail["broker_order"]["status"] == "rejected"
            ]
            assert len(rejections) == 2
            assert {row["broker_order"]["rejection_reason"] for row in rejections} == {
                "Paper broker rejected A",
                "Paper broker rejected B",
            }
            assert all(
                row["broker_order"]["rejected_at"] == rejected_at.replace("+00:00", "Z")
                for row in rejections
            )
            assert tuple(session.scalars(select(ExecutionFillRecord))) == ()
        assert client.positions == []
        assert (
            sum(
                int(row["qty"])
                for root in client.orders.values()
                for row in root["legs"]
                if row["type"] == "stop"
                and row["status"] in {"new", "accepted", "partially_filled"}
            )
            == 0
        )
        assert len(client.posts) == 2 and harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("reverse", [False, True])
async def test_EX_01_aggregate_fill_waits_for_both_broker_terminal_confirmations(
    harness: Harness, reverse: bool
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord, OrderEvent
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        roots = list(client.orders.values())
        if reverse:
            roots.reverse()
        for index, root in enumerate(roots):
            root["filled_qty"] = root["qty"]
            root["status"] = "filled" if index == 0 else "pending_cancel"
            for child in root["legs"]:
                child["status"] = "new"
            total = sum(int(row["filled_qty"]) for row in roots)
            client.positions = [
                {"symbol": "NVDA", "qty": str(total), "side": "long", "asset_class": "us_equity"}
            ]
            await built.prepare_fills(("NVDA",))
            built.observe_fill(
                ObservedFill(
                    account_id="offline-paper",
                    broker_fill_id="aggregate-paper-" + str(index),
                    broker_order_id=UUID(root["id"]),
                    symbol="NVDA",
                    side=Side.BUY,
                    qty=int(root["qty"]),
                    price=Decimal(root["limit_price"]),
                    filled_at=harness.clock.now(),
                )
            )
        with Session(harness.state.engine) as session:
            assert "FILLED" not in tuple(session.scalars(select(OrderEvent.state)))
        roots[-1]["status"] = "filled"
        harness.state.escalate(SystemState.HALTED, "offline final aggregate observation")
        await built.reconcile()
        with Session(harness.state.engine) as session:
            states = tuple(session.scalars(select(OrderEvent.state).order_by(OrderEvent.seq)))
            entries = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
                )
            )
            held = sum(held_quantity(session, row.id) for row in entries)
        assert states[-1] == "FILLED" and states.count("FILLED") == 1
        protected = sum(
            int(row["qty"])
            for root in roots
            for row in root["legs"]
            if row["type"] == "stop" and row["status"] == "new"
        )
        assert held == sum(int(row["qty"]) for row in client.positions) == protected == 9
        assert len(client.posts) == 2 and harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_01_guard_revoked_between_split_submits_retains_racing_fill(
    harness: Harness,
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.core.errors import EntryAdmissionRevoked
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")

    class VetoPaperBroker(FakeTradingClient):
        def cancel_order_by_id(self, order_id: Any) -> None:
            root = next(iter(self.orders.values()))
            assert root["id"] == str(order_id)
            root["status"], root["filled_qty"] = "filled", root["qty"]
            for child in root["legs"]:
                child["status"] = "new"
            self.positions = [
                {"symbol": "NVDA", "qty": root["qty"], "side": "long", "asset_class": "us_equity"}
            ]
            built.observe_fill(
                ObservedFill(
                    account_id="offline-paper",
                    broker_fill_id="guard-race-paper",
                    broker_order_id=UUID(root["id"]),
                    symbol="NVDA",
                    side=Side.BUY,
                    qty=int(root["qty"]),
                    price=Decimal(root["limit_price"]),
                    filled_at=harness.clock.now(),
                )
            )

    alert = await deliver(harness)
    client = VetoPaperBroker(harness)
    built = executor(harness, client)
    built.entry_variant_allowed = lambda: not client.posts
    try:
        with pytest.raises(EntryAdmissionRevoked) as caught:
            await built.enter(alert.proposal_id)
        assert type(caught.value) is EntryAdmissionRevoked
        assert (
            str(caught.value) == "EX-06: configured exit needs current registered WORKING evidence"
        )
        harness.state.escalate(SystemState.HALTED, "offline split admission veto")
        await built.cancel_unfilled_entries()
        with Session(harness.state.engine) as session:
            entries = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
                )
            )
            held = sum(held_quantity(session, row.id) for row in entries)
        protected = sum(
            int(row["qty"])
            for root in client.orders.values()
            for row in root["legs"]
            if row["type"] == "stop" and row["status"] == "new"
        )
        assert held == sum(int(row["qty"]) for row in client.positions) == protected == 4
        assert len(client.posts) == 1 and harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_01_rejected_second_leg_does_not_prevent_first_leg_fill_capture(
    harness: Harness,
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.core.errors import OrderRejectedError
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.alpaca_executor import ExactLimit, ExactStop
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")

    class RejectSecondPaperBroker(FakeTradingClient):
        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            raw = super()._submit_paper(order_data)
            if len(self.posts) == 2:
                raw["status"] = "rejected"
                raw["legs"] = None
            return raw

    alert = await deliver(harness)
    client = RejectSecondPaperBroker(harness)
    built = executor(harness, client)
    try:
        with pytest.raises(OrderRejectedError) as caught:
            await built.enter(alert.proposal_id)
        assert type(caught.value) is OrderRejectedError
        assert str(caught.value) == "Broker order reports a confirmed rejection"
        first, second = client.orders.values()
        assert first["status"] == "new" and second["status"] == "rejected"
        first["status"], first["filled_qty"] = "filled", first["qty"]
        for child in first["legs"]:
            child["status"] = "new"
        client.positions = [
            {"symbol": "NVDA", "qty": first["qty"], "side": "long", "asset_class": "us_equity"}
        ]
        built.observe_fill(
            ObservedFill(
                account_id="offline-paper",
                broker_fill_id="accepted-before-sibling-reject",
                broker_order_id=UUID(first["id"]),
                symbol="NVDA",
                side=Side.BUY,
                qty=int(first["qty"]),
                price=Decimal(first["limit_price"]),
                filled_at=harness.clock.now(),
            )
        )
        harness.state.escalate(SystemState.HALTED, "paper sibling rejection")
        await built.cancel_unfilled_entries()
        with Session(harness.state.engine) as session:
            entries = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
                )
            )
            held = sum(held_quantity(session, row.id) for row in entries)
        protected = sum(
            int(child["qty"]) - int(child["filled_qty"])
            for root in client.orders.values()
            for child in (root, *(root.get("legs") or ()))
            if child["type"] == "stop"
            and child["status"] in {"new", "accepted", "partially_filled"}
        )
        assert (
            held
            == sum(int(row["qty"]) for row in client.positions)
            == protected
            == int(first["qty"])
        )
        assert len(client.posts) == 2
        assert harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("timing", ["before", "between", "after", "both", "multiple"])
@pytest.mark.parametrize("writer", ["panic", "monitor", "recovery"])
async def test_SEC_73_split_cancel_timings_keep_fills_pending_until_all_legs_finish(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, reverse: bool, timing: str, writer: str
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import LEDGER_MODELS, OrderEvent
    from backend.core.ledger import canonical_json
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    requests: list[str] = []
    delivered: list[str] = []

    class PendingPaperBroker(FakeTradingClient):
        def fill(self, root: dict[str, Any], qty: int) -> None:
            accumulated = int(root["filled_qty"]) + qty
            root["filled_qty"] = str(accumulated)
            root["status"] = "filled" if accumulated == int(root["qty"]) else "partially_filled"
            for child in root["legs"]:
                child["status"] = "new" if root["status"] == "filled" else "held"
            total = sum(
                int(row["filled_qty"]) for row in self.orders.values() if row["side"] == "buy"
            )
            self.positions = [
                {"symbol": "NVDA", "qty": str(total), "side": "long", "asset_class": "us_equity"}
            ]
            built.observe_fill(
                ObservedFill(
                    account_id="offline-paper",
                    broker_fill_id="pending-paper-" + str(len(delivered)),
                    broker_order_id=UUID(root["id"]),
                    symbol="NVDA",
                    side=Side.BUY,
                    qty=qty,
                    price=Decimal(root["limit_price"]),
                    filled_at=harness.clock.now(),
                )
            )
            delivered.append(root["id"])
            with Session(harness.state.engine) as session:
                latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()).limit(1))
                assert latest is not None
                if requests:
                    assert latest.state == "CANCEL_REQUESTED"
            harness.state.ledger.verify_chain()

        def finish(self) -> None:
            if delivered:
                return
            roots = [row for row in self.orders.values() if row["side"] == "buy"]
            target = roots[0] if reverse else roots[-1]
            if timing == "both":
                for root in roots:
                    self.fill(root, int(root["qty"]))
            elif timing == "multiple":
                self.fill(target, 1)
                self.fill(target, int(target["qty"]) - 1)
            else:
                self.fill(target, int(target["qty"]))
            for root in roots:
                if root["status"] != "filled" and root["id"] in requests:
                    root["status"] = "canceled"
                    for child in root["legs"]:
                        child["status"] = "canceled"

        def cancel_order_by_id(self, order_id: Any) -> None:
            root = next(
                (
                    row
                    for row in self.orders.values()
                    if row["side"] == "buy" and row["id"] == str(order_id)
                ),
                None,
            )
            if root is None:
                super()._cancel_paper(order_id)
                return
            requests.append(root["id"])
            if timing == "before":
                super()._cancel_paper(order_id)
                return
            root["status"] = "pending_cancel"
            if timing == "between" and len(requests) == 1:
                self.finish()

        def get_order_by_id(self, order_id: Any, filter: object = None) -> dict[str, Any]:
            if timing in {"after", "both", "multiple"} and len(requests) == 2:
                self.finish()
            return super().get_order_by_id(order_id, filter)

    alert = await deliver(harness)
    client = PendingPaperBroker(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        physical_entries = tuple(dict(row) for row in client.posts)
        instructions = built._instructions
        if reverse:
            monkeypatch.setattr(built, "_instructions", lambda: tuple(reversed(instructions())))
        if timing == "before":
            client.finish()
        harness.state.escalate(SystemState.HALTED, "paper split cancellation timing")
        entries = [row for row in built._instructions() if row.role == "ENTRY"]
        if writer == "panic":
            await built.cancel_unfilled_entries()
        elif writer == "monitor":
            await built.monitor()
        else:
            await built._recover_verified_protection(protection_only=True)
        with Session(harness.state.engine) as session:
            held = sum(held_quantity(session, row.id) for row in entries)
            states = tuple(session.scalars(select(OrderEvent.state).order_by(OrderEvent.seq)))
        roots = [row for row in client.orders.values() if row["side"] == "buy"]
        expected = (
            sum(int(row["qty"]) for row in roots)
            if timing == "both"
            else int((roots[0] if reverse else roots[-1])["qty"])
        )
        protected = sum(
            int(row["qty"]) - int(row["filled_qty"])
            for root in client.orders.values()
            for row in (root, *(root.get("legs") or ()))
            if row["type"] == "stop" and row["status"] in {"new", "accepted", "partially_filled"}
        )
        assert held == sum(int(row["qty"]) for row in client.positions) == protected == expected
        assert states[-1] == ("FILLED" if timing == "both" else "CANCELED")
        assert states.count("CANCEL_REQUESTED") == 1
        assert tuple(row for row in client.posts if row["side"] == "buy") == physical_entries
        assert harness.state.current() == SystemState.HALTED
        assert delivered and len(delivered) == (2 if timing in {"both", "multiple"} else 1)
        harness.state.ledger.verify_chain()
        if writer == "panic":

            def rows() -> list[tuple[int, str, str]]:
                with Session(harness.state.engine) as session:
                    return sorted(
                        (row.seq, canonical_json(row), row.row_hash)
                        for model in LEDGER_MODELS
                        for row in session.scalars(select(model))
                    )

            before_repeat = rows()
            await built.cancel_unfilled_entries()
            assert rows() == before_repeat
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_01_third_entry_leg_is_rejected_without_changing_ledger(
    harness: Harness,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import LEDGER_MODELS, AppendControl, ExecutionOrderRecord
    from backend.core.errors import LedgerIntegrityError
    from backend.core.ledger import canonical_json
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)

    def snapshot() -> tuple[list[tuple[str, int, str, str, str]], int | None]:
        with Session(harness.state.engine) as session:
            rows = sorted(
                (model.__tablename__, row.seq, canonical_json(row), row.prev_hash, row.row_hash)
                for model in LEDGER_MODELS
                for row in session.scalars(select(model))
            )
            return rows, session.scalar(select(AppendControl.next_seq))

    try:
        await built.enter(alert.proposal_id)
        with Session(harness.state.engine) as session:
            entries = tuple(
                session.scalars(
                    select(ExecutionOrderRecord)
                    .where(ExecutionOrderRecord.role == "ENTRY")
                    .order_by(ExecutionOrderRecord.seq)
                )
            )
            assert len(entries) == 2
            second = entries[1]
            fields = {
                "order_id": second.order_id,
                "parent_execution_id": second.parent_execution_id,
                "client_order_id": second.client_order_id,
                "account_id": second.account_id,
                "environment": second.environment,
                "symbol": second.symbol,
                "role": second.role,
                "side": second.side,
                "order_type": second.order_type,
                "qty": second.qty,
                "limit_price": second.limit_price,
                "stop_price": second.stop_price,
                "target_price": second.target_price,
                "time_in_force": second.time_in_force,
                "config_hash": second.config_hash,
                "valid_until": second.valid_until,
            }
        fields["client_order_id"] = "vws-" + alert.proposal_id.hex + "-c"
        before = snapshot()
        with pytest.raises(LedgerIntegrityError) as caught:
            harness.state.ledger.append(ExecutionOrderRecord, **fields)
        assert type(caught.value) is LedgerIntegrityError
        assert str(caught.value) == "EX-01: exactly one A followed by one B required"
        assert snapshot() == before
        assert len(client.posts) == 2
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_SEC_73_fill_during_panic_cancel_keeps_newly_held_shares_protected(
    harness: Harness,
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.storage import held_quantity

    races: list[str] = []

    class FillDuringCancelPaperBroker(FakeTradingClient):
        def cancel_order_by_id(self, order_id: Any) -> None:
            root = next(row for row in self.orders.values() if row["side"] == "buy")
            if str(order_id) == root["id"] and not races:
                races.append(root["id"])
                root["status"], root["filled_qty"] = "filled", root["qty"]
                for child in root["legs"]:
                    child["status"] = "new"
                self.positions = [
                    {
                        "symbol": root["symbol"],
                        "qty": root["qty"],
                        "side": "long",
                        "asset_class": "us_equity",
                    }
                ]
                # Canonical activities can arrive while the broker cancel is pending.
                # No record/validator is patched or bypassed.
                built.observe_fill(
                    ObservedFill(
                        account_id="offline-paper",
                        broker_fill_id="paper-panic-cancel-race",
                        broker_order_id=UUID(root["id"]),
                        symbol=root["symbol"],
                        side=Side.BUY,
                        qty=int(root["qty"]),
                        price=Decimal(root["limit_price"]),
                        filled_at=harness.clock.now(),
                    )
                )
                return
            super()._cancel_paper(order_id)

    alert = await deliver(harness)
    client = FillDuringCancelPaperBroker(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    harness.state.escalate(SystemState.HALTED, "offline panic before broker fill")
    try:
        await built.cancel_unfilled_entries()
    finally:
        await built.close()
    root = next(iter(client.orders.values()))
    assert races == [root["id"]] and root["status"] == "filled"
    with Session(harness.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
        assert entry is not None
        held = held_quantity(session, entry.id)
    assert held == int(root["qty"]) > 0
    harness.state.ledger.verify_chain()
    active_stops = [
        order
        for parent in client.orders.values()
        for order in (parent, *(parent.get("legs") or ()))
        if order["side"] == "sell"
        and order["type"] == "stop"
        and order["status"] in {"new", "accepted", "partially_filled"}
    ]
    assert sum(int(order["qty"]) - int(order["filled_qty"]) for order in active_stops) == held
    assert harness.state.current() == SystemState.HALTED
    assert len(client.posts) == 1 and client.posts[0]["side"] == "buy"


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "scenario", ["partial", "after-cancel", "already-canceled", "multiple", "multiple-last"]
)
async def test_SEC_73_panic_races_preserve_captured_shares_and_continue(
    harness: Harness, scenario: str
) -> None:
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord, OrderEvent, SecurityEvent, SystemEvent
    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side
    from backend.execution.storage import held_quantity
    from backend.tests.test_v_execution import variant

    if scenario in {"multiple", "multiple-last"}:
        variant(harness, "SPLIT_1R")
    cancel_sent: list[str] = []
    captured: list[str] = []

    class RacingPaperBroker(FakeTradingClient):
        def capture(self, root: dict[str, Any]) -> None:
            qty = 1 if scenario == "partial" else int(root["qty"])
            root["filled_qty"] = str(qty)
            root["status"] = "partially_filled" if scenario == "partial" else "filled"
            for child in root["legs"]:
                child["status"] = "held" if scenario == "partial" else "new"
            self.positions = [
                {
                    "symbol": root["symbol"],
                    "qty": str(qty),
                    "side": "long",
                    "asset_class": "us_equity",
                }
            ]
            built.observe_fill(
                ObservedFill(
                    account_id="offline-paper",
                    broker_fill_id="paper-panic-" + scenario,
                    broker_order_id=UUID(root["id"]),
                    symbol=root["symbol"],
                    side=Side.BUY,
                    qty=qty,
                    price=Decimal(root["limit_price"]),
                    filled_at=harness.clock.now(),
                )
            )
            captured.append(root["id"])

        def cancel_order_by_id(self, order_id: Any) -> None:
            roots = [row for row in self.orders.values() if row["side"] == "buy"]
            first = roots[-1] if scenario == "multiple-last" else roots[0]
            if str(order_id) == first["id"] and scenario != "already-canceled":
                cancel_sent.append(str(order_id))
                if scenario == "after-cancel":
                    return
                if not captured:
                    self.capture(first)
                if scenario in {"multiple", "multiple-last"}:
                    return
            super()._cancel_paper(order_id)

        def get_order_by_id(self, order_id: Any, filter: object = None) -> dict[str, Any]:
            first = next(iter(self.orders.values()))
            if scenario == "after-cancel" and cancel_sent and not captured:
                assert str(order_id) == first["id"]
                self.capture(first)
            return super().get_order_by_id(order_id, filter)

    alert = await deliver(harness)
    client = RacingPaperBroker(harness)
    built = executor(harness, client)
    notices: list[tuple[str, bool]] = []

    async def notice(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    built.notify = notice
    await built.enter(alert.proposal_id)
    entry_posts = tuple(dict(post) for post in client.posts)
    harness.state.escalate(SystemState.HALTED, "paper panic race test")
    try:
        await built.cancel_unfilled_entries()
        if scenario == "already-canceled":
            # A repeated panic must not append another terminal lifecycle event.
            from backend.core.database import AppendControl

            with Session(harness.state.engine) as session:
                before_repeat = session.scalar(select(AppendControl.next_seq))
            await built.cancel_unfilled_entries()
            with Session(harness.state.engine) as session:
                assert session.scalar(select(AppendControl.next_seq)) == before_repeat
        with Session(harness.state.engine) as session:
            entries = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
                )
            )
            held = sum(held_quantity(session, entry.id) for entry in entries)
            latest = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1))
            assert latest is not None and latest.state == "HALTED"
            summaries = tuple(
                session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "PANIC_CANCEL_RESULT")
                )
            )
            summary = summaries[-1].detail
            terminal = tuple(
                session.scalars(
                    select(OrderEvent).where(OrderEvent.state.in_(["FILLED", "CANCELED"]))
                )
            )
            assert len(terminal) == len({entry.order_id for entry in entries})
            assert len(summary["filled_orders"]) == (0 if scenario == "already-canceled" else 1)
            assert len(summary["canceled_orders"]) == (0 if scenario == "after-cancel" else 1)
        roots = [root for root in client.orders.values() if root["side"] == "buy"]
        filled_root = roots[-1] if scenario == "multiple-last" else roots[0]
        expected = (
            0
            if scenario == "already-canceled"
            else 1
            if scenario == "partial"
            else int(filled_root["qty"])
        )
        assert held == expected
        assert filled_root["status"] == (
            "canceled" if scenario in {"partial", "already-canceled"} else "filled"
        )
        if scenario in {"multiple", "multiple-last"}:
            unfilled_root = roots[0] if scenario == "multiple-last" else roots[1]
            assert len(roots) == 2 and unfilled_root["status"] == "canceled"
        stops = [
            row
            for root in client.orders.values()
            for row in (root, *(root.get("legs") or ()))
            if row["side"] == "sell"
            and row["type"] == "stop"
            and row["status"] in {"new", "accepted", "partially_filled"}
        ]
        assert sum(int(row["qty"]) - int(row["filled_qty"]) for row in stops) == held
        assert tuple(post for post in client.posts if post["side"] == "buy") == entry_posts
        assert harness.state.current() == SystemState.HALTED
        if scenario == "already-canceled":
            assert notices[-1] == ("PAPER · Panic already complete; HALTED.", False)
        else:
            assert notices[-1] == (
                f"PAPER · Panic: canceled {len(summary['canceled_orders'])} orders; filled-and-protected {len(summary['filled_orders'])} legs; failed 0. HALTED.",
                True,
            )
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["intact", "canceled", "stale", "rejected", "quantity"])
async def test_EX_05_restart_repairs_only_proved_stop_levels_and_records_outcome(
    harness: Harness, fault: str
) -> None:
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import StopMoved, stop_raise_plan
    from backend.execution.stop_evidence import current_stop
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    assert entry.stop_price is not None
    await target_filled(harness, built, client)
    inputs = await built._fresh_exit_inputs(entry)
    plan = stop_raise_plan(
        built._held_entry(entry),
        await built._held_observation(entry, inputs),
        built.calendar,
        harness.clock.now(),
        raise_id=uuid4(),
        qty=entry.qty,
        old_stop=entry.stop_price,
        last_trade=inputs.market.last_price,
        quote_at=inputs.market.last_price_ts,
        stale_quote_seconds=harness.settings.stale_quote_seconds,
        trail_atr_mult=Decimal(3),
        config_hash=harness.settings.config_hash,
        yaml_hash=harness.config.config_hash,
    )
    assert plan is not None and plan.new_stop == entry.stop_price + Decimal(4)
    harness.state.ledger.append(
        SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
    )
    if fault == "quantity":
        with pytest.raises(ReconciliationError) as caught:
            await built._resume_stop_moves(entry, entry.qty + 1)
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == "EX-05: unfinished stop raise has changed held shares"
        assert len(client.posts) == 2
        await built.close()
        return
    if fault != "intact":
        await built._cancel_sells(entry, deadline_seconds=10)
    if fault == "stale":
        harness.source.inputs = harness.source.inputs.model_copy(
            update={
                "market": harness.source.inputs.market.model_copy(
                    update={"last_price_ts": harness.clock.now() - timedelta(seconds=61)}
                )
            }
        )
    if fault == "rejected":
        client.raise_fault = "reject-both"
        with pytest.raises(ReconciliationError) as caught:
            await built._resume_stop_moves(entry, entry.qty)
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == "Protective stop could not be confirmed; HALTED"
    else:
        await built._resume_stop_moves(entry, entry.qty)
    with Session(harness.state.engine) as session:
        events = tuple(
            session.scalars(select(SecurityEvent).where(SecurityEvent.kind == "STOP_MOVED"))
        )
        assert len(events) == 1
        moved = StopMoved.recorded(events[0].detail)
        assert moved.approval == plan
        assert moved.status == ("FAILED" if fault == "rejected" else "REPAIRED")
        expected = plan.new_stop if fault == "canceled" else plan.old_stop
        assert moved.confirmed_stop == (None if fault == "rejected" else expected)
        assert current_stop(session, entry) == expected
    # The approved journaled recovery also attempts the original level if the
    # raised replacement is refused; both refusals remain a durable failure.
    assert len(client.posts) == (2 if fault == "intact" else 4 if fault == "rejected" else 3)
    assert harness.state.current() == SystemState.HALTED
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("fault", ["configuration", "pause", "account", "marks", "portfolio"])
async def test_AX_30_monitor_faults_cancel_remainders_and_preserve_verified_stops(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, partial: bool, fault: str
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SystemEvent
    from backend.core.errors import ConfigurationError

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    if partial:
        await fill_entry(harness, client, built, partial=True)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        await built._ensure_stop(entry, 1)
        assert_paper_shares_protected(harness, client)
    if fault in {"configuration", "pause"}:

        def configuration() -> None:
            if fault == "configuration":
                raise ConfigurationError("Paper configuration drift")
            built.modes.downgrade("PAUSE", actor="offline owner")

        built.configuration_check = configuration
    else:

        async def portfolio() -> Any:
            if fault == "portfolio":
                raise ProviderError("Paper snapshot unavailable")
            current = harness.source.inputs.portfolio
            return (
                current.model_copy(update={"account_id": "other-paper"})
                if fault == "account"
                else current
            )

        built.portfolio = portfolio
        if fault == "marks":
            monkeypatch.setattr(built.risk, "marks", None)
    await built.monitor()
    expected = SystemState.RUNNING if fault == "pause" else SystemState.HALTED
    assert harness.state.current() == expected
    if fault == "pause":
        assert built.modes.entries_enabled is False
    else:
        with Session(harness.state.engine) as session:
            halt = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()))
            assert halt is not None and halt.state == "HALTED"
            error_name = (
                "ConfigurationError"
                if fault == "configuration"
                else "ProviderError"
                if fault == "portfolio"
                else "ReconciliationError"
            )
            assert halt.reason == "fault: " + error_name
    root = next(iter(client.orders.values()))
    assert root["status"] == "canceled"
    assert len(client.posts) == (2 if partial else 1)
    if partial:
        assert client.posts[-1]["side"] == "sell" and client.posts[-1]["type"] == "stop"
        assert client.posts[-1]["qty"] == "1"
        assert client.posts[-1]["stop_price"] == root["stop_loss"]["stop_price"]
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["missing", "state", "settings", "account", "locked"])
async def test_AX_41_live_readiness_refuses_before_any_transport_use(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from types import SimpleNamespace
    from typing import cast

    from backend.core.config import Settings
    from backend.core.errors import ConfigurationError
    from backend.execution.alpaca_executor import AlpacaExecutor
    from backend.execution.modes import ModeStore
    from backend.net.egress import EgressPolicy, build_allowlist
    from backend.tests.test_security_cli import MemorySecrets

    client = FakeTradingClient(harness)
    paper = executor(harness, client)
    # This snapshot is confined to a refusal test. The only broker is the paper fake;
    # every case must fail before a transport is acquired or an order is inspected.
    settings = Settings.validated_copy(
        harness.settings.model_copy(
            update={
                "execution_mode": "AUTO_LIVE",
                "paper_trading": False,
                "live_trading_enabled": True,
                "live_trading_confirm": "I_ACCEPT_REAL_MONEY_RISK",
            }
        )
    )
    store = MemorySecrets()
    store.set("ALPACA_LIVE_KEY_ID", settings.broker_api_key)
    store.set("ALPACA_LIVE_SECRET", settings.broker_secret_key)
    modes = ModeStore(settings, harness.state, "offline-paper")
    monkeypatch.setattr(paper.risk.cro, "config", settings)
    monkeypatch.setattr(paper.compliance.engine, "config", settings)

    def locked() -> None:
        raise ExecutionDisabledError("Paper-only test: live readiness stays locked")

    guard = SimpleNamespace(
        state=object() if fault == "state" else harness.state,
        settings=harness.settings if fault == "settings" else settings,
        account_id="another-account" if fault == "account" else "offline-paper",
        assert_ready=locked,
    )

    async def forbidden_notice(text: str, urgent: bool) -> None:
        raise AssertionError("No live executor may be acquired")

    error_type = (
        ConfigurationError if fault in {"state", "settings", "account"} else ExecutionDisabledError
    )
    with pytest.raises(error_type) as caught:
        AlpacaExecutor(
            settings,
            harness.config,
            harness.state,
            modes,
            harness.source,
            paper.risk,
            paper.compliance,
            paper.calendar,
            paper.worker,
            store,
            paper.prerequisites.model_copy(
                update={"environment": "LIVE", "config_hash": settings.config_hash}
            ),
            policy=EgressPolicy(build_allowlist(mode="AUTO_LIVE"), harness.state.ledger),
            notify=forbidden_notice,
            client=client,
            live_guard=None if fault == "missing" else cast(Any, guard),
        )
    assert type(caught.value) is error_type
    assert str(caught.value) == (
        "AUTO_LIVE is locked: history, drill, READY and healthy feeds required"
        if fault == "missing"
        else "Paper-only test: live readiness stays locked"
        if fault == "locked"
        else "Live readiness guard account or configuration differs"
    )
    assert client.posts == [] and client.lookups == []
    assert client._base_url == "https://paper-api.alpaca.markets"
    if fault in {"missing", "locked"}:
        paper.settings = settings
        paper.live_guard = None if fault == "missing" else cast(Any, guard)
        with pytest.raises(ExecutionDisabledError) as refreshed:
            paper._assert_ops()
        assert type(refreshed.value) is ExecutionDisabledError
        assert str(refreshed.value) == (
            "AUTO_LIVE readiness is unavailable"
            if fault == "missing"
            else "Paper-only test: live readiness stays locked"
        )
        assert client.posts == [] and client.lookups == []
    await paper.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault,message",
    [
        ("zero", "Stop repair has no verified positive held shares or level"),
        ("no_stop", "Stop repair has no verified positive held shares or level"),
        ("excess", "Protective sell exceeds verified managed broker shares"),
        ("no_position", "Protective sell exceeds verified managed broker shares"),
        ("unapproved_level", "EX-05: repair cannot lower proved protection"),
        ("client_collision", "New stop client ID already exists without a local intent"),
    ],
)
async def test_AX_27_stop_repair_refuses_unproved_quantity_level_or_identity(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str, message: str
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import ExecutionOrderRecord

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built, partial=True)
    with Session(harness.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
        assert entry is not None
    qty = 1
    options: dict[str, Any] = {}
    if fault == "zero":
        qty = 0
    elif fault == "no_stop":
        entry.stop_price = None
    elif fault == "excess":
        qty = 2
    elif fault == "no_position":
        client.positions.clear()
    elif fault == "unapproved_level":
        options["repair_level"] = Decimal("1.00")
    else:

        def existing(client_id: str) -> dict[str, Any]:
            return {
                "id": str(uuid4()),
                "client_order_id": client_id,
                "symbol": "NVDA",
                "side": "sell",
                "type": "stop",
                "order_class": "simple",
                "time_in_force": "gtc",
                "qty": "1",
                "filled_qty": "0",
                "status": "new",
                "limit_price": None,
                "stop_price": "90.00",
                "submitted_at": harness.clock.now().isoformat(),
                "legs": None,
            }

        monkeypatch.setattr(client, "get_order_by_client_id", existing)
    with pytest.raises(ReconciliationError) as caught:
        await built._repair_stop(entry, qty, **options)
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == message
    assert len(client.posts) == 1
    with Session(harness.state.engine) as session:
        assert (
            tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "REPAIR")
                )
            )
            == ()
        )
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("missing", [False, True])
async def test_XK_02_trade_notice_binds_the_published_proposal_and_ct_time(
    harness: Harness, missing: bool
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import Order
    from backend.core.errors import DataIntegrityError

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    calls: list[tuple[str, bool, object]] = []

    async def notice(text: str, urgent: bool, proposal_id: Any) -> None:
        calls.append((text, urgent, proposal_id))

    built.trade_notice = notice
    with Session(harness.state.engine) as session:
        order = session.scalar(select(Order).where(Order.proposal_id == alert.proposal_id))
        assert order is not None
    if missing:
        with pytest.raises(DataIntegrityError) as caught:
            await built._trade_notice("PAPER · Position protected", True, uuid4())
        assert type(caught.value) is DataIntegrityError
        assert str(caught.value) == "XK-02: trade FYI requires a bound proposal"
        assert calls == []
    else:
        await built._trade_notice("PAPER · Position protected", True, order.id)
        assert calls == [
            ("PAPER · Position protected · Wed Sep 30, 10:00 AM CT", True, alert.proposal_id)
        ]
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_20_unpublished_proposal_refuses_before_broker_submission(
    harness: Harness,
) -> None:
    from backend.core.errors import DataIntegrityError

    client = FakeTradingClient(harness)
    built = executor(harness, client)
    with pytest.raises(DataIntegrityError) as caught:
        built._loaded(uuid4(), None)
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "Auto entry has no published local research proposal"
    assert client.posts == [] and client.lookups == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_22_closed_market_refuses_before_broker_lookup(harness: Harness) -> None:
    from datetime import timedelta

    client = FakeTradingClient(harness)
    built = executor(harness, client)
    harness.clock.current += timedelta(hours=7)
    now = harness.clock.now()
    built.prerequisites = built.prerequisites.model_copy(
        update={"backup_verified_at": now, "telegram_verified_at": now, "clock_verified_at": now}
    )
    with pytest.raises(ExecutionDisabledError) as caught:
        await built.enter(uuid4())
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == "AX-22 market-hours guard blocks entry"
    assert client.posts == [] and client.lookups == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("evidence", [None, False])
async def test_EX_06_entry_requires_registered_exit_evidence(
    harness: Harness, evidence: bool | None
) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    built.entry_variant_allowed = None if evidence is None else lambda: evidence
    with pytest.raises(ExecutionDisabledError) as caught:
        built._assert_entry_variant()
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == (
        "EX-06: registered WORKING exit evidence unavailable"
        if evidence is None
        else "EX-06: configured exit needs current registered WORKING evidence"
    )
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("variant", ["SPLIT_1R_TRAIL", "TRAIL_EMA20"])
async def test_EX_06_trailing_entry_requires_completed_held_observation(
    harness: Harness, variant: str
) -> None:
    from backend.core.config import YamlConfig

    client = FakeTradingClient(harness)
    built = executor(harness, client)
    values = harness.config.model_dump(mode="python")
    values["exits"]["variant"] = variant
    built.config = YamlConfig.model_validate(values)
    with pytest.raises(ExecutionDisabledError) as caught:
        built._assert_entry_variant()
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == "EX: required held-exit observation hook is unavailable"
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["disabled", "no_evidence", "not_working"])
async def test_EG_01_executor_requires_enabled_registered_playbook(
    harness: Harness, fault: str
) -> None:
    from backend.core.config import YamlConfig

    client = FakeTradingClient(harness)
    built = executor(harness, client)
    values = harness.config.model_dump(mode="python")
    values["playbooks"]["enabled"] = ["TREND_50EMA"] if fault == "disabled" else ["EARNINGS_GAP"]
    built.config = YamlConfig.model_validate(values)
    built.playbook_allowed = (lambda _: False) if fault == "not_working" else None
    with pytest.raises(ExecutionDisabledError) as caught:
        built._assert_playbook("EARNINGS_GAP")
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == (
        "EG-01: configured playbook is disabled"
        if fault == "disabled"
        else "EG-01: AUTO earnings-gap requires registered WORKING walk-forward evidence"
    )
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("raw", [None, {}, [None] * 500])
async def test_AX_31_incomplete_open_order_inventory_blocks_reconciliation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, raw: object
) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    monkeypatch.setattr(client, "get_orders", lambda _: raw)
    with pytest.raises(ReconciliationError) as caught:
        await built._open_orders()
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Complete open-order collection cannot be verified"
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "findings,message",
    [
        (None, "EX-06: live paper-raise and OCO/OTO integration evidence unavailable"),
        ([], "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (("missing drill",) * 51, "EX-06: typed paper-raise evidence is UNVERIFIED"),
        ((1,), "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (("",), "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (("x" * 501,), "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (
            ("missing drill", "unverified OCO"),
            "EX-06: live stop raises locked: missing drill; unverified OCO",
        ),
    ],
)
async def test_EX_06_readiness_requires_bounded_typed_evidence_and_exact_refusal(
    harness: Harness, findings: Any, message: str
) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    built.stop_raise_readiness = None if findings is None else lambda: findings
    with pytest.raises(ExecutionDisabledError) as caught:
        built._assert_live_raises()
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == message
    assert built.environment == "PAPER"
    assert client.posts == [] and client.lookups == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "risk_state",
        "compliance_state",
        "risk_clock",
        "compliance_clock",
        "risk_config",
        "compliance_config",
    ],
)
async def test_AX_15_executor_refuses_defenses_from_another_context(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from backend.core.config import Settings
    from backend.core.errors import ConfigurationError

    if fault == "risk_state":
        monkeypatch.setattr(harness.gate.risk, "state", object())
    elif fault == "compliance_state":
        monkeypatch.setattr(harness.gate.compliance, "state", object())
    elif fault == "risk_clock":
        monkeypatch.setattr(harness.gate.risk, "clock", object())
    elif fault == "compliance_clock":
        monkeypatch.setattr(harness.gate.compliance, "clock", object())
    else:
        changed = Settings.validated_copy(
            harness.settings.model_copy(update={"auto_min_score": Decimal("7.6")})
        )
        if fault == "risk_config":
            monkeypatch.setattr(harness.gate.risk.cro, "config", changed)
        else:
            monkeypatch.setattr(harness.gate.compliance.engine, "config", changed)
    client = FakeTradingClient(harness)
    with pytest.raises(ConfigurationError) as caught:
        executor(harness, client)
    assert type(caught.value) is ConfigurationError
    assert str(caught.value) == "Execution defense policies or state differ"
    assert client.posts == [] and client.lookups == []


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_15_executor_refuses_unbound_paper_client_endpoint(harness: Harness) -> None:
    from backend.core.errors import ConfigurationError

    client = FakeTradingClient(harness)
    client._base_url = None  # type: ignore[assignment]
    with pytest.raises(ConfigurationError) as caught:
        executor(harness, client)
    assert type(caught.value) is ConfigurationError
    assert str(caught.value) == "Execution client endpoint is unavailable"
    assert client.posts == [] and client.lookups == []


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("manual", [False, True])
async def test_AX_30_recovery_cannot_acquire_execution_without_managed_evidence(
    harness: Harness, manual: bool
) -> None:
    from backend.core.config import Settings
    from backend.execution.alpaca_executor import ProtectionRecovery

    client = FakeTradingClient(harness)
    settings = (
        Settings.validated_copy(harness.settings.model_copy(update={"execution_mode": "MANUAL"}))
        if manual
        else harness.settings
    )
    with pytest.raises(ExecutionDisabledError) as caught:
        executor(harness, client, settings=settings, constructor=ProtectionRecovery)
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == (
        "Configured MANUAL cannot import or acquire a protection executor"
        if manual
        else "Protection recovery requires existing managed execution evidence"
    )
    assert client.posts == [] and client.lookups == []


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault,message",
    [
        ("unavailable", "Broker position collection is unavailable or unbounded"),
        ("unbounded", "Broker position collection is unavailable or unbounded"),
        ("nonobject", "Broker position is not a verified long equity"),
        ("short", "Broker position is not a verified long equity"),
        ("crypto", "Broker position is not a verified long equity"),
        ("symbol_type", "Broker position is not a verified long equity"),
        ("invalid_symbol", "Broker position symbol is invalid"),
        ("duplicate", "Broker positions contain a duplicate symbol"),
    ],
)
async def test_AX_31_position_inventory_refuses_ambiguity_before_reserving_sells(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str, message: str
) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    row: dict[str, object] = {
        "symbol": "NVDA",
        "qty": "1",
        "side": "long",
        "asset_class": "us_equity",
    }
    raw: object = [row]
    if fault == "unavailable":
        raw = None
    elif fault == "unbounded":
        raw = [row] * 501
    elif fault == "nonobject":
        raw = [None]
    elif fault == "short":
        row["side"] = "short"
    elif fault == "crypto":
        row["asset_class"] = "crypto"
    elif fault == "symbol_type":
        row["symbol"] = 123
    elif fault == "invalid_symbol":
        row["symbol"] = "nvda"
    else:
        raw = [row, dict(row)]
    monkeypatch.setattr(client, "get_all_positions", lambda: raw)
    with pytest.raises(ReconciliationError) as caught:
        await built._positions()
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == message
    assert client.posts == [] and client.lookups == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_11_refreshed_prerequisites_veto_before_paper_entry(harness: Harness) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    alert = await deliver(harness)
    checks: list[str] = []
    built.configuration_check = lambda: checks.append("configuration")
    changed = built.prerequisites.model_copy(update={"doctor_fully_green": False})
    built.prerequisites_source = lambda: changed
    with pytest.raises(ExecutionDisabledError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is ExecutionDisabledError
    assert (
        str(caught.value) == "AUTO prerequisites are unverified, stale or bound to another account"
    )
    assert checks == ["configuration"]
    assert client.posts == [] and client.lookups == []
    await built.close()


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
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing_root",
        "wrong_role",
        "manual",
        "unbound_root",
        "missing_leg",
        "oco_stop_inactive",
    ],
)
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
    if fault == "oco_stop_inactive":
        original_submit = client._submit_paper

        def inactive_oco(order_data: Any) -> dict[str, Any]:
            raw = original_submit(order_data)
            if raw["order_class"] == "oco":
                raw["legs"][0]["status"] = "held"
            return raw

        monkeypatch.setattr(client, "_submit_paper", inactive_oco)
        with pytest.raises(ReconciliationError) as inactive_error:
            await ex._repair_stop(a, a.qty, approval=plan)
        assert type(inactive_error.value) is ReconciliationError
        assert str(inactive_error.value) == "Protective stop could not be confirmed; HALTED"
        assert type(inactive_error.value.__context__) is ReconciliationError
        assert (
            str(inactive_error.value.__context__) == "EX-05: OCO stop child is not confirmed active"
        )
        assert h.state.current() == SystemState.HALTED
        assert len(client.posts) == 3
        with Session(h.state.engine) as session:
            assert (
                tuple(
                    session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "PAPER_CANCEL_SEMANTICS")
                    )
                )
                == ()
            )
        h.state.ledger.verify_chain()
        await ex.close()
        return
    if fault == "unbound_root":
        client.raise_fault = "reject-both"
        with pytest.raises(ReconciliationError) as rejected:
            await ex._repair_stop(a, a.qty, approval=plan)
        assert type(rejected.value) is ReconciliationError
        assert str(rejected.value) == "Protective stop could not be confirmed; HALTED"
        with Session(h.state.engine) as session:
            unbound = session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.role == "REPAIR",
                    ExecutionOrderRecord.order_type == "LIMIT",
                )
            )
            assert unbound is not None
        client.raise_fault = None
        client.failure = None
        await ex._ensure_stop(a, a.qty)
        posted = len(client.posts)
        with pytest.raises(DataIntegrityError) as caught:
            await ex.record_paper_cancel_semantics(b.id, unbound.id)
        assert type(caught.value) is DataIntegrityError
        assert str(caught.value) == "EX-06: previously bound paper root required"
        assert len(client.posts) == posted
        with Session(h.state.engine) as session:
            assert (
                tuple(
                    session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "PAPER_CANCEL_SEMANTICS")
                    )
                )
                == ()
            )
        assert h.state.current() == SystemState.HALTED
        h.state.ledger.verify_chain()
        await ex.close()
        return
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
        raw = original(identity, filter)
        if fault == "missing_leg" and raw["client_order_id"] == b.client_order_id:
            return {**raw, "legs": []}
        return raw

    monkeypatch.setattr(client, "get_order_by_id", read)
    if fault == "manual":
        ex.modes.downgrade("MANUAL", actor="offline owner")
    if fault:
        error_type = ExecutionDisabledError if fault == "manual" else DataIntegrityError
        with pytest.raises(error_type) as publisher_error:
            await ex.record_paper_cancel_semantics(
                uuid4() if fault == "missing_root" else b.id,
                b.id if fault == "wrong_role" else oco.id,
            )
        assert type(publisher_error.value) is error_type
        assert str(publisher_error.value) == (
            "EX-06: explicit AUTO_PAPER integration only"
            if fault == "manual"
            else "EX-06: two recorded generated stop legs required"
            if fault == "missing_leg"
            else "EX-06: bound canonical paper roots required"
        )
        if fault == "missing_leg":
            assert [nested for _, nested in reads] == [True, True]
        else:
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
            Decimal(4) if fault is None else Decimal(0)
        )
    assert (
        len(client.posts)
        == {None: 3, "reject-once": 4, "reject-both": 4, "cancel": 2, "ambiguous-missing": 3}[fault]
    )
    assert harness.state.current() == (
        SystemState.RUNNING if fault in {None, "reject-once"} else SystemState.HALTED
    )
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
    from backend.tests.test_auto_execution import journal_existing_partial_repair

    journal_existing_partial_repair(built)
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
        from backend.tests.test_auto_execution import journal_existing_partial_repair

        journal_existing_partial_repair(built)
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
