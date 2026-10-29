"""Fix F: distinguish token-wait timeouts from created physical workers."""

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import (
    ExecutionOrderRecord,
    OrderEvent,
    SecurityEvent,
    SystemControl,
    SystemEvent,
)
from backend.core.errors import (
    EntryAdmissionRevoked,
    ExecutionDisabledError,
    ProviderError,
    ReconciliationError,
)
from backend.core.system_state import SystemState
from backend.execution.alpaca_executor import AlpacaExecutor, ExactLimit, ExactStop
from backend.execution.models import BrokerOrder, SubmitOutcome
from backend.execution.worker import AttemptNotStartedError
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


class CountingPaperBroker(FakeTradingClient):
    """Count calls through an explicit pinned fake-client method."""

    def __init__(self, harness: Harness) -> None:
        super().__init__(harness)
        self.submit_calls = 0

    def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
        self.submit_calls += 1
        return self._submit_paper(order_data)


async def prepared_submit(
    harness: Harness, client: FakeTradingClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    AlpacaExecutor,
    ExecutionOrderRecord,
    ExactLimit | ExactStop,
    Callable[[], None],
]:
    """Let real admission journal the intent, stopping before its physical attempt."""
    alert = await deliver(harness)
    built = executor(harness, client)
    captured: list[tuple[ExecutionOrderRecord, ExactLimit | ExactStop, Callable[[], None]]] = []

    async def capture(
        instruction: ExecutionOrderRecord,
        request: ExactLimit | ExactStop,
        *,
        guard: Callable[[], None],
    ) -> tuple[BrokerOrder, bool]:
        captured.append((instruction, request, guard))
        raise ExecutionDisabledError("Offline fixture captured the durable submit boundary")

    with monkeypatch.context() as patch:
        patch.setattr(built, "_submit", capture)
        with pytest.raises(
            ExecutionDisabledError, match="Offline fixture captured the durable submit boundary"
        ):
            await built.enter(alert.proposal_id)
    assert len(captured) == 1 and client.posts == []
    instruction, request, guard = captured[0]
    return built, instruction, request, guard


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_timeout_before_worker_creation_records_certain_not_sent(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = CountingPaperBroker(harness)
    built, instruction, request, guard = await prepared_submit(harness, client, monkeypatch)
    workers_created = 0
    create_task = asyncio.create_task

    async def unavailable_token() -> None:
        await asyncio.get_running_loop().create_future()

    def observed_create_task(coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        nonlocal workers_created
        workers_created += 1
        return create_task(coroutine)

    monkeypatch.setattr(built.worker.bucket, "acquire", unavailable_token)
    monkeypatch.setattr(asyncio, "create_task", observed_create_task)
    try:
        with pytest.raises((ExecutionDisabledError, ProviderError)):
            await built._submit(instruction, request, guard=guard)
        assert workers_created == 0
        assert not built.worker.has_pending_attempts
        assert client.submit_calls == 0 and client.posts == []
        with Session(harness.state.engine) as session:
            assert session.get(ExecutionOrderRecord, instruction.id) is not None
            outcomes = tuple(
                row.detail["outcome"]
                for row in session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
                )
                if row.detail["execution_order_id"] == str(instruction.id)
            )
        assert outcomes == ("NOT_SENT",)
        assert built._confirmed_absence(instruction)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_timeout_after_worker_creation_keeps_halt_and_uncertain_reconciliation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockedPaperBroker(FakeTradingClient):
        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            entered.set()
            release.wait()
            raise TimeoutError("Offline physical worker completed without a broker response")

    client = BlockedPaperBroker(harness)
    built, instruction, request, guard = await prepared_submit(harness, client, monkeypatch)
    previous_lookups = len(client.lookups)
    try:
        with pytest.raises(
            ProviderError, match="Order was refused or remains unconfirmed; no retry"
        ):
            await built._submit(instruction, request, guard=guard)
        assert entered.is_set() and built.worker.has_pending_attempts
        assert client.posts == []
        assert client.lookups[previous_lookups:] == [instruction.client_order_id]
        assert harness.state.current() == SystemState.HALTED
        with Session(harness.state.engine) as session:
            outcomes = tuple(
                row.detail["outcome"]
                for row in session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
                )
                if row.detail["execution_order_id"] == str(instruction.id)
            )
        assert outcomes == ("ERROR",) and "NOT_SENT" not in outcomes
        assert not built._confirmed_absence(instruction)
        release.set()
        await asyncio.gather(*tuple(built.worker._workers), return_exceptions=True)
        with pytest.raises(
            ReconciliationError, match="Durable order outcome remains unverifiable; no retry"
        ):
            await built._reconcile()
        assert harness.state.current() == SystemState.HALTED
        assert client.posts == []
        harness.state.ledger.verify_chain()
    finally:
        release.set()
        await built.close()


class BlockedAdmission:
    """Release token admission only after its real deadline has canceled the wait."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.canceled = False

    async def acquire(self) -> None:
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.canceled = True
            raise


async def release_admission(gate: BlockedAdmission) -> None:
    assert gate.canceled and not gate.release.is_set()
    gate.release.set()
    loop = asyncio.get_running_loop()
    barrier: asyncio.Future[None] = loop.create_future()
    loop.call_soon(barrier.set_result, None)
    await barrier


def observed_workers(monkeypatch: pytest.MonkeyPatch) -> list[asyncio.Task[Any]]:
    created: list[asyncio.Task[Any]] = []
    original = asyncio.create_task

    def create(coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        worker = original(coroutine)
        created.append(worker)
        return worker

    monkeypatch.setattr(asyncio, "create_task", create)
    return created


def submit_outcomes(
    harness: Harness, instruction: ExecutionOrderRecord
) -> tuple[SubmitOutcome, ...]:
    with Session(harness.state.engine) as session:
        return tuple(
            evidence
            for evidence in (
                SubmitOutcome.model_validate(row.detail)
                for row in session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
                )
            )
            if evidence.execution_order_id == instruction.id
        )


async def unprotected_position(
    harness: Harness,
) -> tuple[AlpacaExecutor, CountingPaperBroker, ExecutionOrderRecord]:
    alert = await deliver(harness)
    client = CountingPaperBroker(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built, partial=True)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    await built._finalize_entry_cancellation(
        entry, reason="Offline fixture canceled the unfilled remainder"
    )
    assert client.positions[0]["qty"] == "1"
    assert all(
        child["status"] == "canceled"
        for parent in client.orders.values()
        for child in parent["legs"] or ()
    )
    return built, client, entry


async def prepared_stop(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    AlpacaExecutor,
    CountingPaperBroker,
    ExecutionOrderRecord,
    ExactLimit | ExactStop,
    Callable[[], None],
]:
    built, client, entry = await unprotected_position(harness)
    captured: list[tuple[ExecutionOrderRecord, ExactLimit | ExactStop, Callable[[], None]]] = []

    async def capture(
        instruction: ExecutionOrderRecord,
        request: ExactLimit | ExactStop,
        *,
        guard: Callable[[], None],
    ) -> tuple[BrokerOrder, bool]:
        captured.append((instruction, request, guard))
        raise ExecutionDisabledError("Offline fixture captured the protective submit boundary")

    with monkeypatch.context() as patch:
        patch.setattr(built, "_submit", capture)
        with pytest.raises(
            ReconciliationError, match="Protective stop could not be confirmed; HALTED"
        ):
            await built._repair_stop(entry, 1)
    assert len(captured) == 1
    instruction, request, guard = captured[0]
    assert instruction.role == "REPAIR" and instruction.order_type == "STOP"
    assert isinstance(request, ExactStop)
    return built, client, instruction, request, guard


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("operation", ["entry", "stop"])
async def test_deadline_release_never_creates_entry_or_stop_worker(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    if operation == "entry":
        client = CountingPaperBroker(harness)
        built, instruction, request, guard = await prepared_submit(harness, client, monkeypatch)
    else:
        built, client, instruction, request, guard = await prepared_stop(harness, monkeypatch)
    previous_posts = len(client.posts)
    previous_submit_calls = client.submit_calls

    gate = BlockedAdmission()
    monkeypatch.setattr(built.worker.bucket, "acquire", gate.acquire)
    created = observed_workers(monkeypatch)
    try:
        with pytest.raises(ExecutionDisabledError):
            await built._submit(instruction, request, guard=guard)
        await release_admission(gate)
        assert created == [] and not built.worker.has_pending_attempts
        assert client.submit_calls == previous_submit_calls and len(client.posts) == previous_posts
        assert tuple(row.outcome for row in submit_outcomes(harness, instruction)) == ("NOT_SENT",)
        assert built._confirmed_absence(instruction)
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_deadline_at_admission_return_keeps_created_worker_uncertain(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = CountingPaperBroker(harness)
    client.failure = "ambiguous-missing"
    built, instruction, request, guard = await prepared_submit(harness, client, monkeypatch)
    contexts: list[asyncio.Timeout] = []
    timeout = asyncio.timeout

    def active_timeout(delay: float | None) -> asyncio.Timeout:
        context = timeout(delay)
        contexts.append(context)
        return context

    class BoundaryAdmission:
        def __init__(self) -> None:
            self.expired = False

        async def acquire(self) -> None:
            if not self.expired:
                self.expired = True
                contexts[-1].reschedule(asyncio.get_running_loop().time())

    gate = BoundaryAdmission()
    previous_lookups = len(client.lookups)
    monkeypatch.setattr(asyncio, "timeout", active_timeout)
    monkeypatch.setattr(built.worker.bucket, "acquire", gate.acquire)
    created = observed_workers(monkeypatch)
    try:
        with pytest.raises(
            ProviderError, match="Order was refused or remains unconfirmed; no retry"
        ):
            await built._submit(instruction, request, guard=guard)
        await asyncio.gather(*tuple(built.worker._workers), return_exceptions=True)
        assert gate.expired and contexts[0].expired()
        assert len(created) == 2  # The physical attempt, followed by the client-ID lookup.
        assert client.lookups[previous_lookups:] == [instruction.client_order_id]
        outcomes = tuple(row.outcome for row in submit_outcomes(harness, instruction))
        assert outcomes == ("ERROR",) and "NOT_SENT" not in outcomes
        assert not built._confirmed_absence(instruction)
        assert harness.state.current() == SystemState.HALTED
        assert client.submit_calls <= 1 and len(client.posts) <= 1
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_certain_not_sent_retains_intent_for_manual_decision_without_resubmit(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert = await deliver(harness)
    client = CountingPaperBroker(harness)
    built = executor(harness, client)
    submit = built._submit
    gate = BlockedAdmission()
    submit_workers: list[asyncio.Task[Any]] = []

    async def blocked_submit(
        instruction: ExecutionOrderRecord,
        request: ExactLimit | ExactStop,
        *,
        guard: Callable[[], None],
    ) -> tuple[BrokerOrder, bool]:
        nonlocal submit_workers
        with monkeypatch.context() as patch:
            patch.setattr(built.worker.bucket, "acquire", gate.acquire)
            submit_workers = observed_workers(patch)
            return await submit(instruction, request, guard=guard)

    monkeypatch.setattr(built, "_submit", blocked_submit)
    try:
        with pytest.raises(EntryAdmissionRevoked):
            await built.enter(alert.proposal_id)
        await release_admission(gate)
        instructions = built._instructions()
        assert len(instructions) == 1
        instruction = instructions[0]
        assert tuple(row.outcome for row in submit_outcomes(harness, instruction)) == ("NOT_SENT",)
        assert submit_workers == [] and client.submit_calls == 0 and client.posts == []
        with Session(harness.state.engine) as session:
            latest = session.scalar(
                select(OrderEvent)
                .where(OrderEvent.order_id == instruction.order_id)
                .order_by(OrderEvent.seq.desc())
                .limit(1)
            )
            assert latest is not None and latest.state == "CANCELED"
        await built.reconcile()
        assert client.submit_calls == 0 and client.posts == []
        with pytest.raises(
            ExecutionDisabledError, match="Prior durable intent is retained; never resubmit"
        ):
            await built.enter(alert.proposal_id)
        assert tuple(row.id for row in built._instructions()) == (instruction.id,)
        assert tuple(row.outcome for row in submit_outcomes(harness, instruction)) == ("NOT_SENT",)
        assert client.submit_calls == 0 and client.posts == []
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_outer_cancellation_before_worker_keeps_halt_and_reconciliation_lookup(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = CountingPaperBroker(harness)
    built, instruction, request, guard = await prepared_submit(harness, client, monkeypatch)
    gate = BlockedAdmission()
    previous_lookups = len(client.lookups)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(built.worker.bucket, "acquire", gate.acquire)
            submission = asyncio.create_task(built._submit(instruction, request, guard=guard))
            created = observed_workers(patch)
            await gate.entered.wait()
            submission.cancel()
            with pytest.raises(asyncio.CancelledError):
                await submission
            assert gate.canceled and created == [] and not built.worker.has_pending_attempts
        assert client.submit_calls == 0 and client.posts == []
        assert submit_outcomes(harness, instruction) == ()
        assert not built._confirmed_absence(instruction)
        assert harness.state.current() == SystemState.HALTED
        assert halt_evidence(harness)[1][-1][1] == (
            "Order attempt canceled; look up the client ID before any recovery"
        )
        with pytest.raises(
            ReconciliationError, match="Durable order outcome remains unverifiable; no retry"
        ):
            await built._reconcile()
        assert client.lookups[previous_lookups:] == [instruction.client_order_id]
        assert submit_outcomes(harness, instruction) == ()
        assert client.submit_calls == 0 and client.posts == []
        assert harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_cancel_deadline_release_never_creates_worker(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    await fill_entry(harness, client, built)
    stop = next(row for row in built._instructions() if row.role == "STOP")
    broker = await built._read_bound(stop)
    assert broker is not None and broker.is_open
    broker_id = broker.order_id
    previous_posts = len(client.posts)
    previous_outcomes = submit_outcomes(harness, stop)
    cancel_calls: list[str] = []

    def cancel() -> None:
        cancel_calls.append(str(broker_id))
        client._cancel_paper(broker_id)

    gate = BlockedAdmission()
    monkeypatch.setattr(built.worker.bucket, "acquire", gate.acquire)
    created = observed_workers(monkeypatch)
    try:
        with pytest.raises(AttemptNotStartedError):
            await built.worker.attempt(cancel)
        await release_admission(gate)
        assert created == [] and not built.worker.has_pending_attempts
        assert cancel_calls == [] and len(client.posts) == previous_posts
        assert submit_outcomes(harness, stop) == previous_outcomes
        assert client.get_order_by_id(broker_id)["status"] == "new"
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


def halt_evidence(harness: Harness) -> tuple[int, tuple[tuple[int, str, str], ...]]:
    with Session(harness.state.engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
        return control.version, tuple(
            (row.seq, row.reason, row.row_hash)
            for row in session.scalars(
                select(SystemEvent).where(SystemEvent.state == "HALTED").order_by(SystemEvent.seq)
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_pre_worker_not_sent_preserves_earlier_halt_and_original_reason(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeTradingClient(harness)
    built, instruction, request, guard = await prepared_submit(harness, client, monkeypatch)
    reason = "Offline earlier integrity fault; operator reset required"
    harness.state.escalate(SystemState.HALTED, reason)
    before = halt_evidence(harness)
    assert len(before[1]) == 1 and before[1][0][1] == reason
    gate = BlockedAdmission()
    monkeypatch.setattr(built.worker.bucket, "acquire", gate.acquire)
    created = observed_workers(monkeypatch)
    try:
        with pytest.raises(EntryAdmissionRevoked):
            await built._submit(instruction, request, guard=guard)
        await release_admission(gate)
        assert harness.state.current() == SystemState.HALTED
        assert halt_evidence(harness) == before
        assert tuple(row.outcome for row in submit_outcomes(harness, instruction)) == ("NOT_SENT",)
        assert built._confirmed_absence(instruction)
        assert created == [] and not built.worker.has_pending_attempts
        assert client.posts == []
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_pre_worker_stop_not_sent_still_halts_and_alerts_unprotected_position(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, client, entry = await unprotected_position(harness)
    assert harness.state.current() == SystemState.RUNNING
    previous_posts = len(client.posts)
    notices: list[tuple[str, bool]] = []
    previous_submit_calls = client.submit_calls
    gate = BlockedAdmission()
    acquire = built.worker.bucket.acquire
    created = observed_workers(monkeypatch)
    workers_at_submit: int | None = None

    async def block_protective_submit() -> None:
        nonlocal workers_at_submit
        if any(row.role == "REPAIR" for row in built._instructions()):
            workers_at_submit = len(created)
            await gate.acquire()
        else:
            await acquire()

    async def notify(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    monkeypatch.setattr(built.worker.bucket, "acquire", block_protective_submit)
    monkeypatch.setattr(built, "notify", notify)
    try:
        with pytest.raises(
            ReconciliationError, match="Protective stop could not be confirmed; HALTED"
        ):
            await built._repair_stop(entry, 1)
        await release_admission(gate)
        repair = next(row for row in built._instructions() if row.role == "REPAIR")
        assert repair.side == "SELL" and repair.order_type == "STOP" and repair.qty == 1
        assert tuple(row.outcome for row in submit_outcomes(harness, repair)) == ("NOT_SENT",)
        assert built._confirmed_absence(repair)
        assert workers_at_submit is not None and len(created) == workers_at_submit
        assert not built.worker.has_pending_attempts
        assert client.submit_calls == previous_submit_calls and len(client.posts) == previous_posts
        assert harness.state.current() == SystemState.HALTED
        assert halt_evidence(harness)[1][-1][1] == "fault: EntryAdmissionRevoked"
        assert any(urgent and "HALTED: stop repair failed" in text for text, urgent in notices)
        assert client.positions[0]["qty"] == "1"
        harness.state.ledger.verify_chain()
    finally:
        await built.close()
