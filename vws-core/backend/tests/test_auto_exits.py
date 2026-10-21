"""AX-24..31: protected recovery, fixed exits, capped shares and bounded attempts."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import DataSnapshot, ExecutionOrderRecord
from backend.core.errors import (
    ExecutionDisabledError,
    OrderRejectedError,
    ProviderError,
    ReconciliationError,
)
from backend.core.system_state import SystemState
from backend.data.data_layer import AsyncAlpacaMarketData, _bars_digest
from backend.data.fill_polling import ObservedFill
from backend.domain.models import MarketStatus, Side
from backend.execution.alpaca_executor import ProtectionRecovery
from backend.execution.modes import ModeStore
from backend.tests.test_auto_execution import (
    AUTO,
    FakeTradingClient,
    executor,
    fill_entry,
    journal_existing_partial_repair,
)
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("scenario", ["same_hard_event", "canceled_exit"])
async def test_AX_29_completed_broker_cancel_and_repeated_event_keep_bounded_exit_work(
    harness: Harness, scenario: str
) -> None:
    from backend.execution.storage import exit_cycles
    from backend.tests.test_auto_safety import assert_paper_shares_protected

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        if scenario == "same_hard_event":
            built.realtime_exit = lambda symbol, first_fill: ("DELIST", "a" * 64)
            refresh_quotes(harness)
        else:
            refresh_quotes(harness, suspect=True)
        await built.monitor()
        previous = next(row for row in built._instructions() if row.role == "EXIT")
        broker = await built._read_bound(previous)
        assert broker is not None
        await built._cancel_confirmed(previous, broker)
        if scenario == "same_hard_event":
            await built._ensure_stop(entry, entry.qty)
            with Session(harness.state.engine) as session:
                cycle = exit_cycles(session)[-1]
            built._cycle_event(cycle, "FAILED")
            assert_paper_shares_protected(harness, client)
            for _ in range(2):
                await built.monitor()
            assert len(client.posts) == 3
            with Session(harness.state.engine) as session:
                assert len(exit_cycles(session)) == 2
            assert built._protection_repairs() == () and built.modes.entries_enabled
            assert_paper_shares_protected(harness, client)
        else:
            await built.monitor()
            assert len(client.posts) == 4
            current = client.orders[client.posts[-1]["client_order_id"]]
            assert current["type"] == "limit" and current["time_in_force"] == "day"
            assert current["status"] == "new" and current["qty"] == str(entry.qty)
            assert built._protection_repairs() and not built.modes.entries_enabled
            current["status"], current["filled_qty"] = "filled", current["qty"]
            client.positions.clear()
            built.observe_fill(
                ObservedFill(
                    account_id=entry.account_id,
                    broker_fill_id="completed-retry-after-cancel",
                    broker_order_id=UUID(current["id"]),
                    symbol=entry.symbol,
                    side=Side.SELL,
                    qty=entry.qty,
                    price=Decimal(current["limit_price"]),
                    filled_at=harness.clock.now(),
                )
            )
            await built.monitor()
            assert built._protection_repairs() == () and built.modes.entries_enabled
            assert len(client.posts) == 4
            assert_paper_shares_protected(harness, client)
        assert harness.state.current() == SystemState.RUNNING
        assert sum(row["side"] == "buy" for row in client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["quantity_changed", "terminal_id_collision"])
async def test_AX_29_late_exit_guard_refuses_sell_and_restores_exact_remaining_stop(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from typing import Any

    from backend.execution.alpaca_executor import parse_order
    from backend.tests.test_auto_safety import assert_paper_shares_protected

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        parent, _ = await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        assert entry.stop_price is not None
        refresh_quotes(harness, suspect=True)
        reasons: list[str] = []
        original_step = built._exit_step

        async def step(managed: ExecutionOrderRecord, qty: int) -> bool:
            try:
                return await original_step(managed, qty)
            except ReconciliationError as error:
                reasons.append(str(error))
                raise

        monkeypatch.setattr(built, "_exit_step", step)
        if fault == "quantity_changed":
            original_cancel = client._cancel_paper
            captured = False

            def cancel(identity: Any) -> None:
                nonlocal captured
                if not captured:
                    assert built._protection_repairs() and not built.modes.entries_enabled
                    captured = True
                    stop = next(row for row in parent["legs"] if row["type"] == "stop")
                    stop["filled_qty"], stop["status"] = "1", "partially_filled"
                    client.positions[0]["qty"] = str(entry.qty - 1)
                    assert entry.stop_price is not None
                    built.observe_fill(
                        ObservedFill(
                            account_id=entry.account_id,
                            broker_fill_id="fill-during-exit-cancel",
                            broker_order_id=UUID(stop["id"]),
                            symbol=entry.symbol,
                            side=Side.SELL,
                            qty=1,
                            price=entry.stop_price,
                            filled_at=harness.clock.now(),
                        )
                    )
                original_cancel(identity)

            monkeypatch.setattr(client, "_cancel_paper", cancel)
        else:
            identity = "vws-x-" + entry.client_order_id.removeprefix("vws-") + "-1"
            client.orders[identity] = {
                "id": str(uuid4()),
                "client_order_id": identity,
                "symbol": entry.symbol,
                "side": "sell",
                "type": "limit",
                "order_class": "simple",
                "time_in_force": "day",
                "qty": str(entry.qty),
                "filled_qty": "0",
                "status": "canceled",
                "limit_price": "100.00",
                "stop_price": None,
                "legs": None,
                "submitted_at": harness.clock.now().isoformat(),
            }

            def open_orders(filter: Any) -> list[dict[str, Any]]:
                assert filter.status.value == "open" and filter.nested
                return [
                    raw
                    for raw in client.orders.values()
                    if parse_order(raw).is_open or any(leg.is_open for leg in parse_order(raw).legs)
                ]

            monkeypatch.setattr(client, "get_orders", open_orders)
        with pytest.raises(ReconciliationError) as failed:
            await built.monitor()
        assert type(failed.value) is ReconciliationError
        assert str(failed.value) == "Automatic monitor failed closed"
        assert reasons == [
            "Exit would exceed verified held broker shares"
            if fault == "quantity_changed"
            else "Exit client ID already exists without a local instruction"
        ]
        assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
        assert client.posts[-1]["qty"] == str(entry.qty - int(fault == "quantity_changed"))
        assert client.posts[-1]["stop_price"] == format(entry.stop_price, ".2f")
        assert harness.state.current() == SystemState.HALTED and not built.modes.entries_enabled
        assert built._protection_repairs() == ()
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_03_close_above_ema_keeps_next_session_protection_without_an_exit(
    harness: Harness,
) -> None:
    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import HeldEntry, HeldExitObservation
    from backend.notifications.callbacks import FreshInputs
    from backend.tests.test_auto_safety import assert_paper_shares_protected
    from backend.tests.test_v_execution import variant

    variant(harness, "TRAIL_EMA20")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)

    async def observation(entry: HeldEntry, fresh: FreshInputs) -> HeldExitObservation:
        day = built.calendar.last_completed_session(harness.clock.now() - timedelta(minutes=30))
        return HeldExitObservation(
            entry=entry,
            session=day,
            known_at=built.calendar.session_close(day) + timedelta(minutes=30),
            history_sha256="a" * 64,
            close=Decimal(102),
            ema20=Decimal(101),
            atr14=Decimal(2),
            verified_peak=entry.entry_limit + (entry.entry_limit - entry.initial_stop),
        )

    built.held_exit_observation = observation
    try:
        await built.enter(alert.proposal_id)
        parent, _ = await fill_entry(harness, client, built)
        day = built.calendar.add_sessions(harness.clock.now().date(), 1)
        harness.clock.current = built.calendar.session_open(day) + timedelta(minutes=35)
        refresh_quotes(harness)
        await built.monitor()
        assert len(client.posts) == 1
        assert all(row["status"] == "new" for row in parent["legs"])
        with Session(harness.state.engine) as session:
            assert (
                session.scalar(
                    select(SecurityEvent).where(SecurityEvent.kind == "HELD_EXIT_SIGNAL")
                )
                is None
            )
        assert harness.state.current() == SystemState.RUNNING
        assert_paper_shares_protected(harness, client)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("state", ["unknown", "refused", "failed_cycle", "activity_lag"])
async def test_AX_29_restart_resolves_exit_journal_only_from_fresh_broker_proof(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    from backend.execution.storage import exit_cycles
    from backend.tests.test_auto_safety import assert_paper_shares_protected

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        entry = next(row for row in built._instructions() if row.role == "ENTRY")
        refresh_quotes(harness, suspect=True)
        if state in {"unknown", "refused"}:
            client.failure = "ambiguous-missing" if state == "unknown" else "reject"
            original_ensure = built._ensure_stop

            async def interrupted(entry: ExecutionOrderRecord, qty: int) -> None:
                with Session(harness.state.engine) as session:
                    intent = session.scalar(
                        select(ExecutionOrderRecord.id).where(
                            ExecutionOrderRecord.parent_execution_id == entry.id,
                            ExecutionOrderRecord.role == "EXIT",
                        )
                    )
                if intent is not None:
                    raise RuntimeError("offline interruption before stop recovery")
                await original_ensure(entry, qty)

            if state == "refused":
                monkeypatch.setattr(built, "_ensure_stop", interrupted)
            with pytest.raises(ReconciliationError) as caught:
                await built.monitor()
            assert type(caught.value) is ReconciliationError
            assert str(caught.value) == "Automatic monitor failed closed"
            monkeypatch.setattr(built, "_ensure_stop", original_ensure)
            assert harness.state.current() == SystemState.HALTED
            client.failure = None
        else:
            await built.monitor()
            pending = client.orders[client.posts[-1]["client_order_id"]]
            if state == "failed_cycle":
                intent = next(row for row in built._instructions() if row.role == "EXIT")
                broker = await built._read_bound(intent)
                assert broker is not None
                await built._cancel_confirmed(intent, broker)
                with Session(harness.state.engine) as session:
                    cycle = exit_cycles(session)[-1]
                built._cycle_event(cycle, "FAILED")
            else:
                pending["status"], pending["filled_qty"] = "partially_filled", "1"
                # Broker activity arrives before the position snapshot and its
                # canonical fill batch. Do not infer a replacement quantity.
                with pytest.raises(ReconciliationError) as failed:
                    await built.monitor()
                assert type(failed.value) is ReconciliationError
                assert str(failed.value) == "Automatic monitor failed closed"
                assert type(failed.value.__context__) is ReconciliationError
                assert (
                    str(failed.value.__context__)
                    == "Journaled exit does not cover the remaining held shares"
                )
                assert harness.state.current() == SystemState.HALTED
                client.positions[0]["qty"] = str(entry.qty - 1)
                built.observe_fill(
                    ObservedFill(
                        account_id=entry.account_id,
                        broker_fill_id="exit-activity-lag-first",
                        broker_order_id=UUID(pending["id"]),
                        symbol=entry.symbol,
                        side=Side.SELL,
                        qty=1,
                        price=Decimal(pending["limit_price"]),
                        filled_at=harness.clock.now(),
                    )
                )
                await built._resume_protection_repairs()
                assert len(client.posts) == 2 and built._protection_repairs()
                pending["status"], pending["filled_qty"] = "filled", pending["qty"]
                client.positions.clear()
                built.observe_fill(
                    ObservedFill(
                        account_id=entry.account_id,
                        broker_fill_id="exit-activity-lag-rest",
                        broker_order_id=UUID(pending["id"]),
                        symbol=entry.symbol,
                        side=Side.SELL,
                        qty=entry.qty - 1,
                        price=Decimal(pending["limit_price"]),
                        filled_at=harness.clock.now(),
                    )
                )
        if state == "unknown":
            with pytest.raises(ReconciliationError) as unresolved:
                await built._resume_protection_repairs()
            assert type(unresolved.value) is ReconciliationError
            assert str(unresolved.value) == "Journaled exit has an unresolved broker outcome"
            assert len(client.posts) == 2 and built._protection_repairs()
            assert not built.modes.entries_enabled
        else:
            await built._resume_protection_repairs()
            assert built._protection_repairs() == ()
            assert len(client.posts) == (2 if state == "activity_lag" else 3)
            assert built.modes.entries_enabled is (state == "failed_cycle")
            assert_paper_shares_protected(harness, client)
        assert sum(row["side"] == "buy" for row in client.posts) == 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_30_recovery_waits_for_canonical_child_fill_before_acting(
    harness: Harness,
) -> None:
    from backend.execution.storage import held_quantity

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    target = next(child for child in parent["legs"] if child["type"] == "limit")
    target["filled_qty"], target["status"] = "1", "partially_filled"
    harness.state.escalate(SystemState.HALTED, "Awaiting canonical paper child activity")
    await built._recover_verified_protection(protection_only=True)
    assert len(client.posts) == 1
    assert target["status"] == "partially_filled"
    built.observe_fill(
        ObservedFill(
            account_id="offline-paper",
            broker_fill_id="delayed-canonical-child-activity",
            broker_order_id=UUID(target["id"]),
            symbol=entry.symbol,
            side=Side.SELL,
            qty=1,
            price=Decimal(target["limit_price"]),
            filled_at=harness.clock.now(),
        )
    )
    client.positions[0]["qty"] = str(entry.qty - 1)
    stop = next(child for child in parent["legs"] if child["type"] == "stop")
    stop["qty"] = str(entry.qty - 1)
    await built._recover_verified_protection(protection_only=True)
    with Session(harness.state.engine) as session:
        assert (
            held_quantity(session, entry.id)
            == int(client.positions[0]["qty"])
            == int(stop["qty"])
            == entry.qty - 1
        )
    assert stop["status"] == "new" and len(client.posts) == 1
    assert harness.state.current() == SystemState.HALTED
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_fill_while_waiting_for_protective_submit_cannot_oversell(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    acquire = built.worker.bucket.acquire
    fired = False

    async def target_fills_before_request() -> None:
        nonlocal fired
        with Session(harness.state.engine) as session:
            replacement = session.scalar(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "REPAIR")
            )
        if replacement is not None and not fired:
            fired = True
            target = next(child for child in parent["legs"] if child["type"] == "limit")
            target["filled_qty"], target["status"] = "1", "partially_filled"
            client.positions[0]["qty"] = str(entry.qty - 1)
            built.observe_fill(
                ObservedFill(
                    account_id="offline-paper",
                    broker_fill_id="target-during-protection-admission",
                    broker_order_id=UUID(target["id"]),
                    symbol=entry.symbol,
                    side=Side.SELL,
                    qty=1,
                    price=Decimal(target["limit_price"]),
                    filled_at=harness.clock.now(),
                )
            )
            next(child for child in parent["legs"] if child["type"] == "stop")["qty"] = str(
                entry.qty - 1
            )
        await acquire()

    monkeypatch.setattr(built.worker.bucket, "acquire", target_fills_before_request)
    with pytest.raises(ReconciliationError) as caught:
        await built._repair_stop(entry, entry.qty)
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Protective stop could not be confirmed; HALTED"
    nested = caught.value.__context__
    assert isinstance(nested, ProviderError)
    assert type(nested.__context__) is ReconciliationError
    assert str(nested.__context__) == "Held shares changed before protective submit"
    assert fired and len(client.posts) == 1
    assert harness.state.current() == SystemState.HALTED
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_unknown_exit_is_never_retried_or_overlapped_by_a_stop(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    refresh_quotes(harness, suspect=True)
    client.failure = "ambiguous-missing"
    with pytest.raises(ReconciliationError) as first:
        await built._exit_step(entry, entry.qty)
    assert type(first.value) is ReconciliationError
    assert str(first.value) == "An unknown sell outcome prevents a conflicting stop or replacement"
    assert harness.state.current() == SystemState.HALTED
    assert len(client.posts) == 2
    with pytest.raises(ReconciliationError) as retry:
        await built._exit_step(entry, entry.qty)
    assert type(retry.value) is ReconciliationError
    assert str(retry.value) == "Pending exit outcome is unverifiable; no retry"
    with pytest.raises(ReconciliationError) as protection:
        await built._ensure_stop(entry, entry.qty)
    assert type(protection.value) is ReconciliationError
    assert str(protection.value) == "Unconfirmed sell outcome prevents overlapping stop coverage"
    assert len(client.posts) == 2
    assert sum(row["side"] == "buy" for row in client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["rejected", "quote_expired"])
async def test_AX_29_failed_exit_restores_broker_stop_without_another_entry(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from backend.core.database import SecurityEvent
    from backend.core.errors import EntryAdmissionRevoked
    from backend.execution.alpaca_executor import ExactLimit, ExactStop
    from backend.execution.storage import held_quantity

    class RejectExitOnce(FakeTradingClient):
        def _submit_paper(self, order_data: ExactLimit | ExactStop) -> dict[str, object]:
            assert order_data.side is not None
            if (
                fault == "rejected"
                and order_data.side.value == "sell"
                and order_data.type.value == "limit"
            ):
                self.failure = "reject"
            try:
                return super()._submit_paper(order_data)
            finally:
                self.failure = None

    alert = await deliver(harness)
    client = RejectExitOnce(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    refresh_quotes(harness, suspect=True)
    acquire = built.worker.bucket.acquire
    expired = False

    async def expire_after_intent() -> None:
        nonlocal expired
        with Session(harness.state.engine) as session:
            exit_intent = session.scalar(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "EXIT")
            )
        if exit_intent is not None and not expired:
            expired = True
            harness.clock.current += timedelta(seconds=61)
        await acquire()

    if fault == "quote_expired":
        monkeypatch.setattr(built.worker.bucket, "acquire", expire_after_intent)
    error_type = OrderRejectedError if fault == "rejected" else EntryAdmissionRevoked
    with pytest.raises(error_type) as caught:
        await built._exit_step(entry, entry.qty)
    assert type(caught.value) is error_type
    assert str(caught.value) == (
        "Broker rejected the order; client-ID lookup confirmed no order"
        if fault == "rejected"
        else "Exit quantity, session or quote changed before physical request"
    )
    assert len(client.posts) == (3 if fault == "rejected" else 2)
    assert sum(row["side"] == "buy" for row in client.posts) == 1
    repair = client.orders[client.posts[-1]["client_order_id"]]
    assert repair["status"] == "new" and repair["type"] == "stop"
    with Session(harness.state.engine) as session:
        assert (
            held_quantity(session, entry.id)
            == int(client.positions[0]["qty"])
            == int(repair["qty"])
            == entry.qty
        )
        cycles = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "AUTO_EXIT_CYCLE")
                .order_by(SecurityEvent.seq)
            )
        )
        assert [row.detail["state"] for row in cycles] == ["ACTIVE", "FAILED"]
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XA_01_excess_stop_history_refuses_an_incomplete_quote_inventory(
    harness: Harness,
) -> None:
    from backend.core.database import transaction
    from backend.core.errors import DataIntegrityError

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    # Valid immutable protection intents, not a fabricated query result. Together
    # with the original bracket stop these exceed the bounded quote inventory.
    with transaction(harness.state.engine) as session:
        for number in range(1000):
            harness.state.ledger.append_in_session(
                session,
                ExecutionOrderRecord,
                order_id=entry.order_id,
                parent_execution_id=entry.id,
                client_order_id=f"vws-history-stop-{number}",
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
                config_hash=entry.config_hash,
                valid_until=None,
            )
    with pytest.raises(DataIntegrityError) as caught:
        built._record_held_quote(built._held_entry(entry), harness.source.inputs)
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "XA-01: stop quote inventory exceeds its bound"
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_inactive_bracket_stops_are_cleared_before_one_exact_repair(
    harness: Harness,
) -> None:
    from backend.execution.storage import bindings, held_quantity

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    for child in parent["legs"]:
        if child["type"] == "stop":
            child["status"] = "held"
    await built._ensure_stop(entry, entry.qty)
    assert all(child["status"] == "canceled" for child in parent["legs"])
    assert len(client.posts) == 2
    assert client.posts[-1]["type"] == "stop"
    assert client.posts[-1]["qty"] == str(entry.qty)
    with Session(harness.state.engine) as session:
        assert held_quantity(session, entry.id) == int(client.positions[0]["qty"]) == entry.qty
        active = bindings(session)
        assert (
            sum(
                row.qty - row.filled_qty
                for row in active.values()
                if row.side == "sell" and row.order_type == "stop" and row.status == "new"
            )
            == entry.qty
        )
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["uncaptured_fill", "unbound_child"])
async def test_AX_31_reconciliation_refuses_uncaptured_activities_or_unbound_children(
    harness: Harness, fault: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(harness, client, built, partial=True)
    if fault == "uncaptured_fill":
        parent["filled_qty"] = "2"
    else:
        parent["legs"][0] = {
            **parent["legs"][0],
            "id": str(uuid4()),
            "client_order_id": "unbound-paper-child",
        }
    with pytest.raises(ReconciliationError) as caught:
        await built._reconcile()
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == (
        "Broker order fills differ from captured activities"
        if fault == "uncaptured_fill"
        else "Unbound bracket child is present in the account"
    )
    with pytest.raises(ReconciliationError) as public_error:
        await built.reconcile()
    assert type(public_error.value) is ReconciliationError
    assert str(public_error.value) == "Broker reconciliation failed closed"
    assert harness.state.current() == SystemState.HALTED
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["held_basis", "exit"])
async def test_AX_29_uncaptured_entry_cannot_authorize_a_held_exit(
    harness: Harness, operation: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    with pytest.raises(ReconciliationError) as caught:
        if operation == "held_basis":
            built._held_entry(entry)
        else:
            await built._exit_step(entry, 1)
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == (
        "EX: held entry lacks its original approval or captured fills"
        if operation == "held_basis"
        else "Exit has no captured entry fill"
    )
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_quote_before_acquisition_is_not_held_position_evidence(
    harness: Harness,
) -> None:
    from backend.core.database import SecurityEvent

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    held = built._held_entry(entry)
    stale = harness.source.inputs.model_copy(
        update={
            "market": harness.source.inputs.market.model_copy(
                update={"last_price_ts": held.first_fill - timedelta(seconds=1)}
            )
        }
    )
    built._record_held_quote(held, stale)
    with Session(harness.state.engine) as session:
        assert (
            tuple(
                session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "HELD_QUOTE_OBSERVED")
                )
            )
            == ()
        )
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO, {**AUTO, "auto_exits": False}], indirect=True)
async def test_AX_29_closed_session_or_disabled_exits_keep_existing_protection(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    raw, _ = await fill_entry(harness, client, built)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    if harness.settings.auto_exits:
        harness.clock.current += timedelta(hours=7)
    assert await built._exit_step(entry, entry.qty) is False
    assert len(client.posts) == 1
    assert (
        sum(
            int(child["qty"])
            for child in raw["legs"]
            if child["type"] == "stop" and child["status"] == "new"
        )
        == entry.qty
    )
    harness.state.ledger.verify_chain()
    await built.close()


def refresh_quotes(h: Harness, *, suspect: bool = False) -> None:
    h.source.inputs = h.source.inputs.model_copy(
        update={
            "market": h.source.inputs.market.model_copy(
                update={
                    "last_price_ts": h.clock.now(),
                    "status": MarketStatus.SUSPECT if suspect else MarketStatus.OK,
                }
            ),
            "portfolio": h.source.inputs.portfolio.model_copy(update={"as_of": h.clock.now()}),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("state", ["RUNNING", "HALTED", "REDUCE_ONLY", "PAUSE", "MANUAL"])
async def test_AX_29_30_SUSPECT_exit_is_limit_capped_and_unblocked(
    harness: Harness, state: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built)
    if state in {"HALTED", "REDUCE_ONLY"}:
        h.state.escalate(SystemState(state), "fixture state")
    elif state in {"PAUSE", "MANUAL"}:
        built.modes.downgrade("PAUSE" if state == "PAUSE" else "MANUAL", actor="fixture owner")
    refresh_quotes(h, suspect=True)
    await built.monitor()
    assert len(client.posts) == 2
    exit_order = client.posts[-1]
    assert exit_order["side"] == "sell" and exit_order["type"] == "limit"
    assert exit_order["time_in_force"] == "day" and exit_order["qty"] == parent["qty"]
    assert all(row["status"] == "canceled" for row in parent["legs"])
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("restart", [False, True])
async def test_AX_29_working_flatten_journal_blocks_entries_until_confirmed_flat(
    harness: Harness, restart: bool
) -> None:
    from backend.tests.test_auto_safety import assert_paper_shares_protected

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    original = built
    try:
        await built.enter(alert.proposal_id)
        await fill_entry(harness, client, built)
        assert_paper_shares_protected(harness, client)
        refresh_quotes(harness, suspect=True)
        await built.monitor()
        pending = client.orders[client.posts[-1]["client_order_id"]]
        assert pending["side"] == "sell" and pending["type"] == "limit"
        assert len(built._protection_repairs()) == 1
        assert built._protection_repairs()[0]["exit_cycle_id"]
        assert not built.modes.entries_enabled
        if restart:
            built = executor(harness, client)
        with pytest.raises(ExecutionDisabledError) as refused:
            await built.enter(uuid4())
        assert type(refused.value) is ExecutionDisabledError
        assert str(refused.value) == "Open protection repair blocks entry"
        await built.monitor()
        assert len(client.posts) == 2 and pending["status"] == "new"
        assert harness.state.current() == SystemState.RUNNING
        assert len(built._protection_repairs()) == 1
        pending["status"], pending["filled_qty"] = "filled", pending["qty"]
        client.positions.clear()
        built.observe_fill(
            ObservedFill(
                account_id="offline-paper",
                broker_fill_id="journaled-exit-" + uuid4().hex,
                broker_order_id=UUID(pending["id"]),
                symbol="NVDA",
                side=Side.SELL,
                qty=int(pending["qty"]),
                price=Decimal(pending["limit_price"]),
                filled_at=harness.clock.now(),
            )
        )
        await built.monitor()
        assert built._protection_repairs() == () and built.modes.entries_enabled
        assert_paper_shares_protected(harness, client)
        assert harness.state.current() == SystemState.RUNNING
        assert len(client.posts) == 2
        harness.state.ledger.verify_chain()
    finally:
        await built.close()
        if built is not original:
            await original.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_pending_exit_within_two_minutes_is_not_repriced(harness: Harness) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built)
    refresh_quotes(harness, suspect=True)
    await built.monitor()
    pending = dict(client.posts[-1])
    assert pending["side"] == "sell" and pending["time_in_force"] == "day"
    await built.monitor()
    assert len(client.posts) == 2
    assert client.posts[-1] == pending
    assert client.orders[pending["client_order_id"]]["status"] == "new"
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_completed_exit_closes_cycle_without_quotes_or_another_sell(
    harness: Harness,
) -> None:
    from backend.core.database import SecurityEvent

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built)
    refresh_quotes(harness, suspect=True)
    await built.monitor()
    raw = client.orders[client.posts[-1]["client_order_id"]]
    raw["filled_qty"], raw["status"] = raw["qty"], "filled"
    client.positions.clear()
    built.observe_fill(
        ObservedFill(
            account_id="offline-paper",
            broker_fill_id="completed-paper-exit",
            broker_order_id=UUID(raw["id"]),
            symbol="NVDA",
            side=Side.SELL,
            qty=int(raw["qty"]),
            price=Decimal(raw["limit_price"]),
            filled_at=harness.clock.now(),
        )
    )
    harness.source.error = ProviderError("Flat position needs no quote")
    await built.monitor()
    with Session(harness.state.engine) as session:
        cycles = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "AUTO_EXIT_CYCLE")
                .order_by(SecurityEvent.seq)
            )
        )
        assert [event.detail["state"] for event in cycles] == ["ACTIVE", "DONE"]
        assert cycles[0].detail["cycle_id"] == cycles[1].detail["cycle_id"]
        assert cycles[1].detail["reason"] == "SUSPECT"
    assert len(client.posts) == 2
    assert all(row["status"] == "canceled" for row in next(iter(client.orders.values()))["legs"])
    assert harness.state.current() == SystemState.RUNNING
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_unfilled_exit_has_three_reprices_then_one_stop_and_no_repeat_cycle(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built)
    refresh_quotes(h, suspect=True)
    await built.monitor()
    for _ in range(4):
        h.clock.current += timedelta(minutes=2)
        refresh_quotes(h, suspect=True)
        await built.monitor()
    assert len(client.posts) == 6
    assert (
        len([row for row in client.posts if row["side"] == "sell" and row["type"] == "limit"]) == 4
    )
    assert client.posts[-1]["type"] == "stop" and client.posts[-1]["time_in_force"] == "gtc"
    assert len({row["client_order_id"] for row in client.posts}) == 6
    await built.monitor()
    assert len(client.posts) == 6
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_partial_exit_reprices_only_remaining_broker_shares(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built)
    refresh_quotes(h, suspect=True)
    await built.monitor()
    raw = client.orders[client.posts[-1]["client_order_id"]]
    raw["filled_qty"], raw["status"] = "1", "partially_filled"
    client.positions[0]["qty"] = str(int(parent["qty"]) - 1)
    built.observe_fill(
        ObservedFill(
            account_id="offline-paper",
            broker_fill_id="partial-exit",
            broker_order_id=UUID(raw["id"]),
            symbol=raw["symbol"],
            side=Side.SELL,
            qty=1,
            price=Decimal(raw["limit_price"]),
            filled_at=h.clock.now(),
        )
    )
    h.clock.current += timedelta(minutes=2)
    refresh_quotes(h, suspect=True)
    await built.monitor()
    assert len(client.posts) == 3
    assert client.posts[-1]["qty"] == client.positions[0]["qty"]
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_30_restart_after_downgrade_repairs_stops_but_never_enters(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    journal_existing_partial_repair(built)
    built.modes.downgrade("MANUAL", actor="fixture owner")
    with pytest.raises(ExecutionDisabledError):
        executor(h, client)
    recovered = executor(h, client, constructor=ProtectionRecovery)
    await recovered.monitor()
    assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
    with pytest.raises(ExecutionDisabledError, match="cannot submit entries"):
        await recovered.enter(uuid4())
    recovered.modes.resume(operator="fixture owner", phrase="RESUME")
    with pytest.raises(ExecutionDisabledError):
        await recovered.enter(uuid4())
    assert len(client.posts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_30_missing_quote_never_prevents_valid_stop_repair(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    journal_existing_partial_repair(built)
    h.source.error = ProviderError("synthetic quote unavailable")
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
    assert h.state.current() == SystemState.HALTED
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_25_late_pause_is_a_no_send_and_not_a_broker_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    original = built.worker.bucket.acquire
    fired = False

    async def admission() -> None:
        nonlocal fired
        with Session(h.state.engine) as session:
            exists = session.scalar(select(ExecutionOrderRecord)) is not None
        if exists and not fired:
            fired = True
            built.modes.downgrade("PAUSE", actor="fixture owner")
        await original()

    monkeypatch.setattr(built.worker.bucket, "acquire", admission)
    with pytest.raises(ExecutionDisabledError, match="Final mode"):
        await built.enter(alert.proposal_id)
    assert fired and not client.posts
    assert h.state.current() == SystemState.RUNNING
    await built.monitor()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_third_confirmed_rejection_latches_and_survives_restart(
    harness: Harness,
) -> None:
    h = harness
    client = FakeTradingClient(h)
    client.failure = "reject"
    built = executor(h, client)
    with Session(h.state.engine) as session:
        source = session.get(DataSnapshot, h.request.data_snapshot_id)
        assert source is not None
        bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in source.bars)
    for number in range(3):
        if number:
            # Three independent session candidates, with freshly completed
            # synthetic bars. Reusing one research candidate is rightly refused.
            h.clock.current += timedelta(days=1)
            bars = (
                *bars,
                bars[-1].model_copy(
                    update={
                        "timestamp": bars[-1].timestamp + timedelta(days=1),
                        "open": bars[-1].open + Decimal(1),
                        "high": bars[-1].high + Decimal(1),
                        "low": bars[-1].low + Decimal(1),
                        "close": bars[-1].close + Decimal(1),
                    }
                ),
            )
            refresh_quotes(h)
            snapshot = h.state.ledger.append(
                DataSnapshot,
                symbol="NVDA",
                timeframe="1Day",
                feed="SIP",
                adjustment="SPLIT",
                fetched_at=h.clock.now(),
                range_start=bars[0].timestamp,
                range_end=bars[-1].timestamp,
                bar_count=len(bars),
                sha256=_bars_digest(bars)[0],
                bars=[row.model_dump(mode="json") for row in bars],
            )
            found = h.swarm.hunter.hunt(
                "NVDA", bars, h.source.inputs.portfolio, h.source.inputs.market, h.clock.now()
            )
            assert found.candidates
            h.request = h.request.model_copy(
                update={
                    "candidate": found.candidates[0],
                    "data_snapshot_id": snapshot.id,
                    "portfolio": h.source.inputs.portfolio,
                    "market": h.source.inputs.market,
                }
            )
        alert = await deliver(h)
        built = executor(
            h, client
        )  # Fresh synthetic backup/doctor proof each session; counter persists.
        with pytest.raises(OrderRejectedError):
            await built.enter(alert.proposal_id)
        assert h.state.current() == (SystemState.HALTED if number == 2 else SystemState.RUNNING)
    assert len(client.posts) == 3
    assert not ModeStore(h.settings, h.state, "offline-paper").entries_enabled
    h.state.ledger.verify_chain()
