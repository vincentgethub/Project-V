"""Fix A: deterministic races at the last physical transport guard."""

import asyncio
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from alpaca.trading.client import TradingClient
from requests import Response
from requests import Session as RequestsSession
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionOrderRecord, Order, SecurityEvent
from backend.core.errors import (
    EntryAdmissionRevoked,
    ExecutionDisabledError,
    ProviderError,
    SafetyError,
)
from backend.core.system_state import SystemState
from backend.execution.alpaca_executor import (
    AlpacaExecutor,
    ExactLimit,
    ExactStop,
    configure_execution_client,
)
from backend.execution.models import SubmitOutcome, TransportAttemptEvidence
from backend.execution.storage import bindings, held_quantity
from backend.execution.worker import (
    SingleAttemptWorker,
    TransportAttempt,
    TransportRecord,
    TransportState,
)
from backend.net.egress import EgressPolicy, build_allowlist
from backend.tests.test_attempt_timeout import CountingPaperBroker, prepared_submit
from backend.tests.test_auto_execution import AUTO, executor, fill_entry
from backend.tests.test_execution_transport import response
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    ("state", "persisted"),
    [
        (TransportState.PENDING, "PENDING"),
        (TransportState.ENTERED, "ENTERED"),
        (TransportState.ABANDONED, "ABANDONED"),
    ],
)
async def test_transport_state_persisted_text_is_stable(
    harness: Harness, state: TransportState, persisted: str
) -> None:
    built = executor(harness, PhysicalPaperBroker(harness))
    try:
        built._record_transport(
            TransportRecord(
                uuid4(), "vws-state-text", state, "timeout", "EXECUTION_ATTEMPT_UNCERTAIN", False
            )
        )
        saved = evidence(harness, "EXECUTION_ATTEMPT_UNCERTAIN")[-1]
        assert saved["state"] == persisted
        parsed = {**saved, "timestamp": datetime.fromisoformat(saved["timestamp"])}
        assert TransportAttemptEvidence.model_validate(parsed).state == persisted
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_fenced_outcome_keeps_inner_type_and_static_reason_without_broker_text(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, intent, _, _ = await prepared_submit(harness, PhysicalPaperBroker(harness), monkeypatch)
    try:
        error = ProviderError("offline broker diagnostic canary")
        built._outcome(intent, "NOT_SENT", error, reason="fenced before transport")
        saved = evidence(harness, "EXECUTION_SUBMIT_OUTCOME")[-1]
        assert saved["error_type"] == "ProviderError"
        assert saved["reason"] == "fenced before transport"
        assert "offline broker diagnostic canary" not in json.dumps(saved)
        historical = {key: value for key, value in saved.items() if key != "reason"}
        assert SubmitOutcome.model_validate(historical).reason is None
    finally:
        await built.close()


class Gate:
    def __init__(self, *, after: bool = False) -> None:
        self.after = after
        self.loop = asyncio.get_running_loop()
        self.entered = asyncio.Event()
        self.exited = asyncio.Event()
        self.release = threading.Event()

    def pause(self) -> None:
        self.loop.call_soon_threadsafe(self.entered.set)
        self.release.wait()


class RequestCounts:
    """Count deliveries at the offline Session.request boundary explicitly."""

    def __init__(self) -> None:
        self.submit_calls = 0
        self.lookup_calls = 0

    def record_submit(self) -> None:
        self.submit_calls += 1

    def record_lookup(self) -> None:
        self.lookup_calls += 1


def test_refusal_audit_requires_actual_cas_veto_and_releases_lock_before_recording() -> None:
    records: list[TransportRecord] = []
    locks_held: list[bool] = []

    def record(saved: TransportRecord) -> None:
        locks_held.append(attempt._lock.locked())
        records.append(saved)

    attempt = TransportAttempt("vws-audit-veto", True, record)
    attempt.audit_refusal()
    assert records == []
    attempt.abandon("timeout")
    before_veto = tuple(records)
    attempt.audit_refusal()
    assert tuple(records) == before_veto, "ABANDONED without a hook veto is not a refusal"
    with pytest.raises(ProviderError, match="Abandoned attempt refused"):
        attempt.enter()
    attempt.audit_refusal()
    attempt.audit_refusal()
    assert [row.kind for row in records].count("EXECUTION_ATTEMPT_REFUSED") == 1
    assert records[-1].never_entered_transport is True
    assert locks_held and not any(locks_held), "recorder must run outside the attempt lock"

    entered_records: list[TransportRecord] = []
    entered = TransportAttempt("vws-audit-entered", True, entered_records.append)
    entered.enter()
    entered.audit_refusal()  # A network error after ENTERED cannot be a refusal.
    entered.abandon("timeout")
    entered.audit_refusal()
    assert [row.kind for row in entered_records] == ["EXECUTION_ATTEMPT_UNCERTAIN"]
    assert entered_records[0].never_entered_transport is False


class PhysicalPaperBroker(CountingPaperBroker):
    """The fake's last request boundary invokes the real worker guard."""

    def __init__(self, harness: Harness) -> None:
        super().__init__(harness)
        self.worker: SingleAttemptWorker | None = None
        self.built: AlpacaExecutor | None = None
        self.enabled = False
        self.gates: dict[tuple[str, str], Gate] = {}
        self.transport: list[tuple[str, str]] = []
        self.entry_flags: list[bool] = []
        self.requests: dict[str, ExactLimit | ExactStop] = {}
        self.contradiction: str | None = None
        self.submit_error: tuple[str, Exception] | None = None
        self.failed_states: list[TransportState] = []

    @contextmanager
    def physical(self, kind: str, identity: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        assert self.worker is not None and self.built is not None
        gate = self.gates.pop((kind, identity), None)
        guard: Callable[[], None] = self.worker._local.guard

        def paused_guard() -> None:
            guard()
            assert gate is not None
            gate.pause()

        if gate is not None and not gate.after:
            self.worker._local.guard = paused_guard
        try:
            self.worker.before_request()
            self.transport.append((kind, identity))
            if kind in {"submit", "cancel"}:
                self.entry_flags.append(self.built.modes.entries_enabled)
            if gate is not None and gate.after:
                gate.pause()
            yield
        finally:
            self.worker._local.guard = guard
            if gate is not None:
                gate.loop.call_soon_threadsafe(gate.exited.set)

    def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
        identity = str(order_data.client_order_id)
        self.requests[identity] = order_data
        with self.physical("submit", identity):
            self.submit_calls += 1
            if self.submit_error is not None and self.submit_error[0] == identity:
                assert self.worker is not None
                self.failed_states.append(self.worker._local.attempt._state)
                raise self.submit_error[1]
            return self._submit_paper(order_data)

    def cancel_order_by_id(self, order_id: UUID | str) -> None:
        with self.physical("cancel", str(order_id)):
            self._cancel_paper(order_id)

    def get_order_by_client_id(self, client_id: str) -> dict[str, Any]:
        with self.physical("lookup", client_id):
            if self.contradiction == client_id and client_id not in self.orders:
                self._submit_paper(self.requests[client_id])
            return super().get_order_by_client_id(client_id)

    def get_order_by_id(self, order_id: UUID | str, filter: object = None) -> dict[str, Any]:
        with self.physical("read", str(order_id)):
            return super().get_order_by_id(order_id, filter)

    def get_account(self) -> dict[str, Any]:
        with self.physical("account", ""):
            return super().get_account()

    def get_all_positions(self) -> list[dict[str, Any]]:
        with self.physical("positions", ""):
            return super().get_all_positions()

    def get_orders(self, filter: object = None) -> list[dict[str, Any]]:
        with self.physical("orders", ""):
            return super().get_orders(filter)


def enable(client: PhysicalPaperBroker, built: AlpacaExecutor) -> None:
    client.worker, client.built, client.enabled = built.worker, built, True


def evidence(h: Harness, kind: str) -> tuple[dict[str, Any], ...]:
    with Session(h.state.engine) as session:
        return tuple(
            row.detail
            for row in session.scalars(select(SecurityEvent).where(SecurityEvent.kind == kind))
        )


async def settle(task: asyncio.Task[Any]) -> tuple[Any, Exception | None]:
    try:
        return await task, None
    except (SafetyError, TimeoutError) as error:
        return None, error


async def held_position(
    h: Harness, *, partial: bool = False
) -> tuple[AlpacaExecutor, PhysicalPaperBroker, ExecutionOrderRecord, ExecutionOrderRecord]:
    alert = await deliver(h)
    client = PhysicalPaperBroker(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=partial)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    stop = next(row for row in built._instructions() if row.role == "STOP")
    if partial:
        await built._finalize_entry_cancellation(entry, reason="Offline partial fixture")
    else:
        await built._read_bound(stop)
    enable(client, built)
    return built, client, entry, stop


def active_stops(client: PhysicalPaperBroker) -> list[dict[str, Any]]:
    return [
        order
        for parent in client.orders.values()
        for order in (parent, *(parent["legs"] or ()))
        if order["type"] == "stop" and order["status"] == "new"
    ]


def coverage(h: Harness, client: PhysicalPaperBroker, entry: ExecutionOrderRecord) -> int:
    with Session(h.state.engine) as session:
        held = held_quantity(session, entry.id)
    assert held == int(client.positions[0]["qty"])
    return sum(int(row["qty"]) - int(row["filled_qty"]) for row in active_stops(client))


def confirmed_cancel_before_restore(h: Harness, stop: ExecutionOrderRecord, identity: str) -> None:
    with Session(h.state.engine) as session:
        assert bindings(session)[stop.id].status == "canceled"
        restored = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.client_order_id == identity)
        )
        canceled = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "EXECUTION_ORDER_OBSERVED",
                SecurityEvent.detail["execution_order_id"].as_string() == str(stop.id),
                SecurityEvent.detail["broker_order"]["status"].as_string() == "canceled",
            )
            .order_by(SecurityEvent.seq)
        )
        assert restored is not None and canceled is not None
        assert canceled.seq < restored.seq, "broker-confirmed cancel must precede restoration"


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("winner", ["abandon", "enter"])
async def test_A1_A6_entry_fence_forces_both_race_orders(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, winner: str
) -> None:
    client = PhysicalPaperBroker(harness)
    built, intent, request, guard = await prepared_submit(harness, client, monkeypatch)
    enable(client, built)
    gate = Gate(after=winner == "enter")
    client.gates["submit", intent.client_order_id] = gate
    task = asyncio.create_task(built._submit(intent, request, guard=guard))
    try:
        await gate.entered.wait()
        _, error = await settle(task)
        gate.release.set()
        await gate.exited.wait()
        await built.close()
        sent = client.transport.count(("submit", intent.client_order_id))
        proofs = [
            row
            for row in evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
            if row["client_order_id"] == intent.client_order_id
        ]
        assert sent == (1 if winner == "enter" else 0), (
            "an abandoned attempt must never enter transport"
        )
        assert bool(proofs) == (winner == "abandon")
        assert bool(proofs) != bool(sent), "exactly one CAS winner, never both or neither"
        assert error is not None and harness.state.current() == SystemState.HALTED
        outcomes = evidence(harness, "EXECUTION_SUBMIT_OUTCOME")
        assert outcomes[-1]["outcome"] == ("ERROR" if winner == "enter" else "NOT_SENT")
        if winner == "abandon":
            assert outcomes[-1]["reason"] == "fenced before transport"
            assert outcomes[-1]["error_type"] == "TimeoutError"
        assert client.lookups[-1] == intent.client_order_id
        if proofs:
            assert proofs[0]["never_entered_transport"] is True
            assert {"attempt_id", "timestamp"}.issubset(proofs[0])
            assert evidence(harness, "EXECUTION_ATTEMPT_REFUSED")
        harness.state.ledger.verify_chain()
    finally:
        gate.release.set()
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "case",
    ["abandoned", "entered", "write-failed", "write-missing", "foreign-proof", "contradiction"],
)
async def test_A2_protection_restores_only_on_durable_never_entered_proof(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    built, client, entry, old_stop = await held_position(harness)
    qty = int(client.positions[0]["qty"])
    assert entry.stop_price is not None
    journal = built._begin_protection_repair(entry, qty, entry.stop_price, entry.stop_price)
    identity, restoration = str(journal["new_client_id"]), str(journal["old_client_id"])
    notices: list[tuple[str, bool]] = []

    async def notice(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    monkeypatch.setattr(built, "notify", notice)
    writes: list[str] = []
    append = harness.state.ledger.append

    def fail_abandonment(model: type[Any], **fields: Any) -> Any:
        if fields.get("kind") == "EXECUTION_ATTEMPT_ABANDONED":
            if case == "write-failed":
                writes.append("failed")
                raise OSError("Offline abandonment journal write failed")
            if case == "write-missing":
                writes.append("missing")
                return None
            writes.append("foreign")
            fields["detail"] = {**fields["detail"], "account_id": "different-paper-account"}
        return append(model, **fields)

    if case in {"write-failed", "write-missing", "foreign-proof"}:
        monkeypatch.setattr(harness.state.ledger, "append", fail_abandonment)
    gate = Gate(after=case == "entered")
    client.gates["submit", identity] = gate
    task = asyncio.create_task(
        built._journaled_stop_repair(entry, qty, entry.stop_price, entry.stop_price)
    )
    try:
        await gate.entered.wait()
        if case == "contradiction":
            client.contradiction = identity
        result, error = await settle(task)
        gate.release.set()
        await gate.exited.wait()
        await asyncio.gather(*tuple(built.worker._workers), return_exceptions=True)
        assert client.transport.count(("submit", identity)) == (1 if case == "entered" else 0), (
            "late protective send escaped its fence"
        )
        assert harness.state.current() == SystemState.HALTED
        assert not built.modes.entries_enabled and not any(client.entry_flags)
        pause = built.modes._read()
        assert pause is not None and pause.paused
        assert identity in client.lookups
        with Session(harness.state.engine) as session:
            assert session.get(ExecutionOrderRecord, old_stop.id) is not None
            assert held_quantity(session, entry.id) == qty == int(client.positions[0]["qty"])
        if case == "abandoned":
            assert error is None and result is not None
            assert identity != restoration and restoration in client.orders
            assert client.orders[restoration]["stop_price"] == format(entry.stop_price, ".2f")
            assert coverage(harness, client, entry) == qty
            assert len(active_stops(client)) == 1
            confirmed_cancel_before_restore(harness, old_stop, restoration)
            assert evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
        else:
            assert restoration not in client.orders, (
                "possibly sent or contradictory attempts must never restore"
            )
            assert error is not None
            assert any(
                urgent and ("repair failed" in text or "contradict" in text.lower())
                for text, urgent in notices
            )
            if case == "write-failed":
                assert writes == ["failed"]
            if case == "write-missing":
                assert writes == ["missing"]
            if case == "foreign-proof":
                assert writes == ["foreign"]
            if case == "contradiction":
                assert evidence(harness, "EXECUTION_ATTEMPT_CONTRADICTION")
                contradicted = next(
                    row for row in built._instructions() if row.client_order_id == identity
                )
                assert await built._read_bound(contradicted) is not None
                before = len(client.transport)
                await settle(
                    asyncio.create_task(
                        built._journaled_stop_repair(entry, qty, entry.stop_price, entry.stop_price)
                    )
                )
                assert restoration not in client.orders, (
                    "contradiction must forbid restoration even after broker binding"
                )
                assert not any(
                    kind in {"submit", "cancel"} for kind, _ in client.transport[before:]
                )
        harness.state.ledger.verify_chain()
    finally:
        gate.release.set()
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("kind", ["lookup", "cancel"])
async def test_A3_abandoned_lookup_or_cancel_preserves_existing_stop(
    harness: Harness, kind: str
) -> None:
    built, client, entry, stop = await held_position(harness)
    broker = await built._read_bound(stop)
    assert broker is not None
    identity = "vws-offline-read" if kind == "lookup" else str(broker.order_id)
    gate = Gate()
    client.gates[kind, identity] = gate
    task = asyncio.create_task(
        built._lookup(identity) if kind == "lookup" else built._cancel_confirmed(stop, broker)
    )
    try:
        await gate.entered.wait()
        _, error = await settle(task)
        gate.release.set()
        await gate.exited.wait()
        await built.close()
        assert client.transport.count((kind, identity)) == 0, (
            "abandoned read/delete reached transport"
        )
        assert error is not None
        assert coverage(harness, client, entry) == int(client.positions[0]["qty"])
        assert evidence(harness, "EXECUTION_ATTEMPT_REFUSED")
    finally:
        gate.release.set()
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_A4_lookup_runs_while_durable_pause_blocks_fresh_entries(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = PhysicalPaperBroker(harness)
    built, intent, request, guard = await prepared_submit(harness, client, monkeypatch)
    enable(client, built)
    send_gate, lookup_gate = Gate(), Gate()
    client.gates["submit", intent.client_order_id] = send_gate
    client.gates["lookup", intent.client_order_id] = lookup_gate
    task = asyncio.create_task(built._submit(intent, request, guard=guard))
    try:
        await send_gate.entered.wait()
        original_worker = next(iter(built.worker._workers))
        await lookup_gate.entered.wait()
        assert harness.state.current() == SystemState.RUNNING
        send_gate.release.set()
        await send_gate.exited.wait()
        await asyncio.gather(original_worker, return_exceptions=True)
        assert client.transport.count(("submit", intent.client_order_id)) == 0
        assert not built.modes.entries_enabled, (
            "lookup window requires an existing durable entry block"
        )
        assert evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
        with Session(harness.state.engine) as session:
            order = session.get(Order, intent.order_id)
            assert order is not None
            proposal_id = order.proposal_id
        with pytest.raises(ExecutionDisabledError):
            await built.enter(proposal_id)
        assert harness.state.current() == SystemState.RUNNING
        lookup_gate.release.set()
        await settle(task)
        assert client.transport.count(("lookup", intent.client_order_id)) == 1
    finally:
        send_gate.release.set()
        lookup_gate.release.set()
        await settle(task)
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_A5_halt_refuses_cro_clear_entry_but_allows_fresh_protection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = PhysicalPaperBroker(harness)
    built, intent, request, guard = await prepared_submit(harness, client, monkeypatch)
    guard()
    harness.state.escalate(SystemState.HALTED, "Offline prior fault")
    enable(client, built)
    try:
        with pytest.raises(ExecutionDisabledError):
            await built._submit(intent, request, guard=guard)
        assert client.transport.count(("submit", intent.client_order_id)) == 0
        assert harness.state.current() == SystemState.HALTED
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_A5_fresh_protective_stop_under_halt_keeps_existing_policy(harness: Harness) -> None:
    built, client, entry, _ = await held_position(harness, partial=True)
    harness.state.escalate(SystemState.HALTED, "Offline prior fault")
    try:
        repaired = await built._repair_stop(entry, 1)
        assert repaired.is_open and repaired.side == "sell" and repaired.order_type == "stop"
        assert coverage(harness, client, entry) == 1
        assert harness.state.current() == SystemState.HALTED
        assert not built.modes.entries_enabled
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_A6_cancel_pending_worker_writes_proof_and_still_looks_up(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = PhysicalPaperBroker(harness)
    built, intent, request, guard = await prepared_submit(harness, client, monkeypatch)
    enable(client, built)
    gate = Gate()
    client.gates["submit", intent.client_order_id] = gate
    task = asyncio.create_task(built._submit(intent, request, guard=guard))
    try:
        await gate.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        gate.release.set()
        await gate.exited.wait()
        await built.close()
        assert client.transport.count(("submit", intent.client_order_id)) == 0
        assert client.lookups[-1] == intent.client_order_id
        assert evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")[-1]["reason"] == "cancelled"
        assert evidence(harness, "EXECUTION_SUBMIT_OUTCOME")[-1]["outcome"] == "NOT_SENT"
        assert harness.state.current() == SystemState.HALTED
    finally:
        gate.release.set()
        await built.close()


class OfflineCrash(BaseException):
    """Stop this test's coroutine at a durable checkpoint, without OS actions."""


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("recorded", [True, False])
async def test_A7_crash_recovery_restores_exactly_once_only_with_durable_no_send(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, recorded: bool
) -> None:
    built, client, entry, old_stop = await held_position(harness)
    assert entry.stop_price is not None
    qty = int(client.positions[0]["qty"])
    journal = built._begin_protection_repair(entry, qty, entry.stop_price, entry.stop_price)
    identity, restoration = str(journal["new_client_id"]), str(journal["old_client_id"])
    original_repair = built._repair_stop_attempt
    original_append = harness.state.ledger.append

    async def crash_before_restoration(
        entry: ExecutionOrderRecord, journal: dict[str, Any], *, restore: bool
    ) -> Any:
        if restore:
            assert evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
            assert evidence(harness, "EXECUTION_SUBMIT_OUTCOME")[-1]["outcome"] == "NOT_SENT"
            raise OfflineCrash("Durable no-send checkpoint before restoration")
        return await original_repair(entry, journal, restore=restore)

    def omit_proof(model: type[Any], **fields: Any) -> Any:
        if fields.get("kind") == "EXECUTION_ATTEMPT_ABANDONED":
            return None
        return original_append(model, **fields)

    monkeypatch.setattr(built, "_repair_stop_attempt", crash_before_restoration)
    if not recorded:
        monkeypatch.setattr(harness.state.ledger, "append", omit_proof)
    gate = Gate()
    client.gates["submit", identity] = gate
    task = asyncio.create_task(
        built._journaled_stop_repair(entry, qty, entry.stop_price, entry.stop_price)
    )
    try:
        await gate.entered.wait()
        if recorded:
            with pytest.raises(OfflineCrash):
                await task
        else:
            _, error = await settle(task)
            assert error is not None
            assert not evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
            assert evidence(harness, "EXECUTION_SUBMIT_OUTCOME")[-1]["outcome"] == "ERROR"
        assert client.transport.count(("submit", restoration)) == 0
    finally:
        gate.release.set()
        await gate.exited.wait()
        await built.close()

    recovered = executor(harness, client)
    enable(client, recovered)
    try:
        if recorded:
            await recovered._resume_protection_repairs()
            # Replaying the completed recovery is an idempotency assertion.
            await recovered._resume_protection_repairs()
            assert identity != restoration
            assert client.transport.count(("submit", restoration)) == 1
            assert coverage(harness, client, entry) == qty
            assert len(active_stops(client)) == 1
            confirmed_cancel_before_restore(harness, old_stop, restoration)
            assert recovered._protection_repairs() == ()
        else:
            with pytest.raises(SafetyError):
                await recovered._resume_protection_repairs()
            assert client.transport.count(("submit", restoration)) == 0
            assert len(active_stops(client)) == 0
        assert harness.state.current() == SystemState.HALTED
        assert not recovered.modes.entries_enabled
        pause = recovered.modes._read()
        assert pause is not None and pause.paused
        harness.state.ledger.verify_chain()
    finally:
        await recovered.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("winner", ["abandon", "enter"])
async def test_A8_real_session_boundary_has_one_winner_and_no_intervening_database_io(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, winner: str
) -> None:
    paper = CountingPaperBroker(harness)
    built, intent, request, original_guard = await prepared_submit(harness, paper, monkeypatch)
    client = TradingClient(
        api_key="TEST_ONLY_PAPER_ID", secret_key="TEST_ONLY_PAPER_SECRET", paper=True, raw_data=True
    )
    built.client = client
    gate = Gate()
    hook_active: set[int] = set()
    approved: set[int] = set()
    database_io: list[str] = []
    audits_inside_hook: list[bool] = []
    counts = RequestCounts()
    guard_calls = 0
    append = harness.state.ledger.append

    def hook() -> None:
        identity = threading.get_ident()
        hook_active.add(identity)
        try:
            built.worker.before_request()
        except Exception:
            approved.discard(identity)
            raise
        finally:
            hook_active.discard(identity)

    def guard() -> None:
        nonlocal guard_calls
        original_guard()
        guard_calls += 1
        if guard_calls == 2:
            approved.add(threading.get_ident())
            if winner == "abandon":
                gate.pause()

    def observe_io(*args: Any, **kwargs: Any) -> None:
        if threading.get_ident() in approved:
            database_io.append("database I/O after final approval")

    def audited_append(model: type[Any], **fields: Any) -> Any:
        if fields.get("kind") == "EXECUTION_ATTEMPT_REFUSED":
            audits_inside_hook.append(threading.get_ident() in hook_active)
        return append(model, **fields)

    def wire(session: RequestsSession, method: str, url: str, **kwargs: Any) -> Response:
        if "json" in kwargs:
            counts.record_submit()
            assert threading.get_ident() in approved
            approved.discard(threading.get_ident())
            assert kwargs["json"]["client_order_id"] == intent.client_order_id
            if winner == "enter":
                gate.pause()
            return response(url, 200, paper._submit_paper(request))
        assert kwargs["params"]["client_order_id"] == intent.client_order_id
        counts.record_lookup()
        return response(url, 404, {"code": 404, "message": "offline missing order"})

    configure_execution_client(
        client,
        harness.settings,
        EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger),
        before_request=hook,
    )
    monkeypatch.setattr(RequestsSession, "request", wire)
    monkeypatch.setattr(harness.state.ledger, "append", audited_append)
    event.listen(harness.state.engine, "before_cursor_execute", observe_io)
    task = asyncio.create_task(built._submit(intent, request, guard=guard))
    try:
        await gate.entered.wait()
        _, error = await settle(task)
        gate.release.set()
        await built.close()
        assert error is not None and harness.state.current() == SystemState.HALTED
        assert counts.lookup_calls == 1, "the client-ID lookup must still run"
        assert counts.submit_calls == (1 if winner == "enter" else 0)
        saved = evidence(harness, "EXECUTION_SUBMIT_OUTCOME")[-1]
        assert saved["outcome"] == ("ERROR" if winner == "enter" else "NOT_SENT")
        assert bool(evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")) == (winner == "abandon")
        assert database_io == [], "final approval must have no database I/O before transport"
        assert audits_inside_hook == ([] if winner == "enter" else [False]), (
            "refusal audit must happen only after the hook has raised"
        )
        assert not built.modes.entries_enabled
        harness.state.ledger.verify_chain()
    finally:
        gate.release.set()
        event.remove(harness.state.engine, "before_cursor_execute", observe_io)
        await built.close()


class HaltNotices:
    """Record the existing synchronous critical HALT notification boundary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def notify(self, state: str, reason: str) -> None:
        self.calls.append((state, reason))


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_A9_entered_transport_error_is_uncertain_and_never_restores(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, client, entry, _ = await held_position(harness)
    assert entry.stop_price is not None
    qty = int(client.positions[0]["qty"])
    journal = built._begin_protection_repair(entry, qty, entry.stop_price, entry.stop_price)
    identity, restoration = str(journal["new_client_id"]), str(journal["old_client_id"])
    client.submit_error = identity, ConnectionError("Offline transport failed after admission")
    notices: list[tuple[str, bool]] = []

    async def notice(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    monkeypatch.setattr(built, "notify", notice)
    try:
        with pytest.raises(SafetyError):
            await built._journaled_stop_repair(entry, qty, entry.stop_price, entry.stop_price)
        assert client.failed_states == [TransportState.ENTERED]
        assert client.transport.count(("submit", identity)) == 1
        assert client.transport.count(("submit", restoration)) == 0
        instruction = next(row for row in built._instructions() if row.client_order_id == identity)
        outcomes = [
            row
            for row in evidence(harness, "EXECUTION_SUBMIT_OUTCOME")
            if row["execution_order_id"] == str(instruction.id)
        ]
        assert [row["outcome"] for row in outcomes] == ["ERROR"]
        assert all(row.get("reason") != "fenced before transport" for row in outcomes)
        for kind in ("EXECUTION_ATTEMPT_ABANDONED", "EXECUTION_ATTEMPT_UNCERTAIN"):
            assert not any(
                row["client_order_id"] == identity and row["never_entered_transport"] is True
                for row in evidence(harness, kind)
            )
        assert harness.state.current() == SystemState.HALTED
        assert any(urgent and "repair failed" in text for text, urgent in notices)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("method_failure", [False, True])
async def test_A10_refusal_audit_failure_preserves_original_and_halts_with_critical_notice(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, method_failure: bool
) -> None:
    client = PhysicalPaperBroker(harness)
    built, intent, _, _ = await prepared_submit(harness, client, monkeypatch)
    notices = HaltNotices()
    harness.state.notifier.delegate = notices
    recorder = built.worker._recorder
    assert recorder is not None
    audit_error = OSError("Offline refusal write failed")
    originals: list[ProviderError] = []
    attempts: list[TransportAttempt] = []

    def failed_recorder(record: TransportRecord) -> None:
        if record.kind == "EXECUTION_ATTEMPT_REFUSED":
            raise audit_error
        recorder(record)

    def failed_audit(attempt: TransportAttempt) -> None:
        raise audit_error

    def operation() -> None:
        attempt = built.worker._local.attempt
        attempts.append(attempt)
        attempt.bind_boundary()
        attempt.abandon("timeout")
        try:
            built.worker.before_request()
        except ProviderError as original:
            originals.append(original)
            raise

    monkeypatch.setattr(built.worker, "_recorder", failed_recorder)
    if method_failure:
        monkeypatch.setattr(TransportAttempt, "audit_refusal", failed_audit)
    try:
        with built.worker.order_context(intent.client_order_id):
            with pytest.raises(ProviderError) as caught:
                await built.worker.attempt(operation)
        assert caught.value is originals[0], "the original transport veto must stay primary"
        assert harness.state.current() == SystemState.HALTED
        assert ("HALTED", "fault: OSError") in notices.calls
        assert any("OSError" in note for note in caught.value.__notes__)
        assert attempts[0].proof(intent.client_order_id) is not None
        assert evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
        assert not evidence(harness, "EXECUTION_ATTEMPT_REFUSED")
        assert client.posts == []
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("refusal_write_fails", [False, True])
async def test_A11_complete_abandoned_repair_has_exact_transport_counts(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, refusal_write_fails: bool
) -> None:
    built, client, entry, old_stop = await held_position(harness)
    assert entry.stop_price is not None
    qty = int(client.positions[0]["qty"])
    journal = built._begin_protection_repair(entry, qty, entry.stop_price, entry.stop_price)
    identity, restoration = str(journal["new_client_id"]), str(journal["old_client_id"])
    notices = HaltNotices()
    harness.state.notifier.delegate = notices
    append = harness.state.ledger.append

    def refuse_audit_write(model: type[Any], **fields: Any) -> Any:
        if fields.get("kind") == "EXECUTION_ATTEMPT_REFUSED":
            raise OSError("Offline refusal write failed after durable proof")
        return append(model, **fields)

    if refusal_write_fails:
        monkeypatch.setattr(harness.state.ledger, "append", refuse_audit_write)
    gate = Gate()
    client.gates["submit", identity] = gate
    task = asyncio.create_task(
        built._journaled_stop_repair(entry, qty, entry.stop_price, entry.stop_price)
    )
    try:
        await gate.entered.wait()
        result, error = await settle(task)
        late_workers = tuple(built.worker._workers)
        gate.release.set()
        await gate.exited.wait()
        await built.close()
        assert result is not None and error is None
        counts = {
            kind: sum(saved == kind for saved, _ in client.transport)
            for kind in ("lookup", "read", "cancel", "submit", "account", "positions", "orders")
        }
        print("A11 full repair transport counts:", counts)
        assert client.transport.count(("lookup", identity)) == 3
        assert client.transport.count(("lookup", restoration)) == 1
        assert client.transport.count(("submit", identity)) == 0
        assert client.transport.count(("submit", restoration)) == 1
        # The existing OCO cancel closes its sibling too: one cancel, not two.
        # Read-bound checks both children twice, polls the cancel once, then
        # confirms the restoration once. Three client-ID reads use the failed
        # new ID (preflight, ambiguity, cancel-new proof); one preflights restore.
        assert counts == {
            "lookup": 4,
            "read": 6,
            "cancel": 1,
            "submit": 1,
            "account": 5,
            "positions": 5,
            "orders": 5,
        }
        with Session(harness.state.engine) as session:
            proved = bindings(session)
            target = next(row for row in built._instructions() if row.role == "TARGET")
            restored = next(
                row for row in built._instructions() if row.client_order_id == restoration
            )
            canceled = [identity for kind, identity in client.transport if kind == "cancel"]
            old_ids = {str(proved[row.id].order_id) for row in (old_stop, target)}
            assert len(canceled) == 1 and canceled[0] in old_ids
            for broker_id in old_ids:
                expected = 3 if broker_id == canceled[0] else 2
                assert client.transport.count(("read", broker_id)) == expected
            assert client.transport.count(("read", str(proved[restored.id].order_id))) == 1
        assert coverage(harness, client, entry) == qty
        assert len(active_stops(client)) == 1
        confirmed_cancel_before_restore(harness, old_stop, restoration)
        assert harness.state.current() == SystemState.HALTED
        if refusal_write_fails:
            assert ("HALTED", "fault: OSError") in notices.calls
            assert not evidence(harness, "EXECUTION_ATTEMPT_REFUSED")
            assert evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
            assert len(late_workers) == 1
            late_error = late_workers[0].exception()
            assert isinstance(late_error, ProviderError)
            assert "Abandoned attempt refused" in str(late_error)
            assert any("OSError" in note for note in late_error.__notes__)
        harness.state.ledger.verify_chain()
    finally:
        gate.release.set()
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_A12_hook_guard_typed_veto_is_not_sent_without_uncertainty(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, intent, request, _ = await prepared_submit(
        harness, CountingPaperBroker(harness), monkeypatch
    )
    client = TradingClient(
        api_key="TEST_ONLY_PAPER_ID", secret_key="TEST_ONLY_PAPER_SECRET", paper=True, raw_data=True
    )
    built.client = client
    veto = EntryAdmissionRevoked("Offline host veto at physical hook")
    calls: list[str] = []
    guard_calls = 0

    def guard() -> None:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            raise veto

    def wire(session: RequestsSession, method: str, url: str, **kwargs: Any) -> Response:
        calls.append("physical request")
        raise AssertionError("Typed physical veto must precede Session.request")

    configure_execution_client(
        client,
        harness.settings,
        EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger),
        before_request=built.worker.before_request,
    )
    monkeypatch.setattr(RequestsSession, "request", wire)
    try:
        with pytest.raises(EntryAdmissionRevoked) as caught:
            await built._submit(intent, request, guard=guard)
        assert caught.value is veto
        assert guard_calls == 2 and calls == []
        saved = evidence(harness, "EXECUTION_SUBMIT_OUTCOME")[-1]
        assert saved["outcome"] == "NOT_SENT" and saved["error_type"] == "EntryAdmissionRevoked"
        assert not evidence(harness, "EXECUTION_ATTEMPT_UNCERTAIN")
        assert not evidence(harness, "EXECUTION_ATTEMPT_ABANDONED")
        assert harness.state.current() == SystemState.RUNNING
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("missing", ["admitted", "guard", "attempt"])
async def test_A13_missing_thread_local_cleanup_preserves_primary_exception(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    built, _, _, _ = await prepared_submit(harness, CountingPaperBroker(harness), monkeypatch)
    primary = ProviderError("Offline primary operation failure")

    def operation() -> None:
        delattr(built.worker._local, missing)
        raise primary

    try:
        with pytest.raises(ProviderError) as caught:
            await built.worker.attempt(operation)
        assert caught.value is primary, "cleanup must never replace the primary exception"
    finally:
        await built.close()
