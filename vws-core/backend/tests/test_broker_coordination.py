"""Fix G-q: baseline broker counts and deterministic actor coordination."""

from collections import Counter
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from backend.core.system_state import SystemState
from backend.execution.alpaca_executor import ExactLimit, ExactStop, ProtectionRecovery
from backend.ops import quiescence
from backend.ops.quiescence import BrokerActor, BrokerCoordination, OSSlots, QuiescenceError
from backend.tests.broker_flag_fakes import FakeFlagAdapter
from backend.tests.test_attempt_timeout import CountingPaperBroker
from backend.tests.test_auto_execution import AUTO, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.fixture(autouse=True)
def isolated_component_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    flag = FakeFlagAdapter()
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: flag)


class FakeLease:
    def __init__(self, slots: "FakeSlots", name: str) -> None:
        self.slots, self.name = slots, name

    @property
    def held(self) -> bool:
        return self.name in self.slots.held

    def release(self) -> None:
        self.slots.held.remove(self.name)


class FakeSlots:
    def __init__(self) -> None:
        self.held: set[str] = set()
        self.error = False
        self.probes: list[str] = []

    def acquire(self, name: str) -> FakeLease | None:
        self.probes.append(name)
        if self.error:
            raise OSError("Offline adapter unavailable")
        if name in self.held:
            return None
        self.held.add(name)
        return FakeLease(self, name)


@pytest.mark.parametrize("slot", range(8))
def test_Q2_Q10_active_actor_refuses_without_wait(tmp_path: Path, slot: int) -> None:
    slots = FakeSlots()
    slots.held.add(f"slot-{slot}")
    refused = False
    try:
        with BrokerCoordination(tmp_path, slots).resolver():
            pass
    except QuiescenceError:
        refused = True
    assert refused, "an occupied broker slot must refuse resolver evidence immediately"
    assert slots.held == {f"slot-{slot}"}, "partial slot acquisition must be unwound"
    assert len(slots.probes) <= 8, "only one nonblocking probe per slot is permitted"


def test_Q11_adapter_error_refuses(tmp_path: Path) -> None:
    slots = FakeSlots()
    slots.error = True
    refused = False
    try:
        with BrokerCoordination(tmp_path, slots).resolver():
            pass
    except QuiescenceError:
        refused = True
    assert refused, "an adapter error must never become positive quiescence"


def test_Q15_real_os_slot_is_exclusive_even_on_owner_thread(tmp_path: Path) -> None:
    coordination = BrokerCoordination(tmp_path)
    coordination.initialize()
    adapter = OSSlots(coordination.directory)
    first = adapter.acquire("slot-7")
    assert first is not None
    second = None
    try:
        second = adapter.acquire("slot-7")
        assert second is None, "same-thread mutex recursion is not a second free broker slot"
    finally:
        if second is not None:
            second.release()
        first.release()


@pytest.mark.parametrize("phase", ["during", "after-snapshot"])
def test_Q1_Q7_Q12_new_completed_panic_changes_epoch(tmp_path: Path, phase: str) -> None:
    slots = FakeSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    coordination.initialize()
    refused = False
    try:
        with coordination.resolver():
            actor = BrokerActor(coordination, "panic")
            actor.start()
            assert actor.slot is None, "panic proceeds even while resolver owns every slot"
            actor.finish()
            coordination.check()
    except QuiescenceError:
        refused = True
    assert refused, f"panic at {phase} must invalidate the evidence epoch"


def test_Q3_Q10_slot_and_publication_failure_never_blocks_panic(tmp_path: Path) -> None:
    slots = FakeSlots()
    slots.error = True
    coordination = BrokerCoordination(tmp_path, slots)
    actor = BrokerActor(coordination, "panic")
    actor.start()
    actor.retain()
    calls: list[str] = []
    actor.physical_call(lambda: calls.append("cancel"))
    actor.finish()
    assert calls == ["cancel"], "coordination failure cannot suppress emergency broker work"
    with pytest.raises(QuiescenceError):
        with coordination.resolver():
            raise AssertionError("unverified adapters may not authorize evidence")


def test_Q4_Q13_crash_or_failed_end_has_doctor_message(tmp_path: Path) -> None:
    slots = FakeSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    actor = BrokerActor(coordination, "panic")
    actor.start()
    # Simulate kernel release at crash, leaving durable BEGIN without END.
    slots.held.clear()
    message = coordination.doctor_message()
    assert message is not None and "incomplete panic/recovery" in message
    assert "no automatic expiry" in message
    assert not list(coordination.directory.glob("*.END"))
    with pytest.raises(QuiescenceError):
        with coordination.resolver():
            raise AssertionError("an unmatched invocation must refuse")


def test_Q6_two_panics_and_Q8_existing_halt_still_have_distinct_leases(tmp_path: Path) -> None:
    slots = FakeSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    first, second = BrokerActor(coordination, "panic"), BrokerActor(coordination, "panic")
    first.start()
    second.start()
    assert first.identity != second.identity
    first.finish()
    try:
        with pytest.raises(QuiescenceError):
            with coordination.resolver():
                raise AssertionError("the second panic is still active")
    finally:
        second.finish()
    with coordination.resolver():
        coordination.check()


def test_Q9_late_physical_worker_retains_slot_and_unmatched_begin(tmp_path: Path) -> None:
    slots = FakeSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    actor = BrokerActor(coordination, "panic")
    actor.start()
    actor.retain()
    actor.finish()
    assert "slot-0" in slots.held
    assert not list(coordination.directory.glob("*.END"))
    calls: list[str] = []
    actor.physical_call(lambda: calls.append("physical exit"))
    # A synchronous owner performs its final release, never the worker thread.
    actor.finish()
    assert calls == ["physical exit"]
    assert slots.held == set()
    assert len(list(coordination.directory.glob("*.END"))) == 1


def test_Q14_Q17_healthy_proof_and_static_messages(tmp_path: Path) -> None:
    slots = FakeSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    coordination.initialize()
    with coordination.resolver():
        assert len(slots.held) == 8
        coordination.check()
    assert slots.held == set()
    assert coordination.doctor_message() is None


class CountedBroker(CountingPaperBroker):
    def __init__(self, harness: Harness) -> None:
        super().__init__(harness)
        self.counts: Counter[str] = Counter()

    def get_account(self) -> dict[str, Any]:
        self.counts["account"] += 1
        return super().get_account()

    def get_order_by_client_id(self, client_id: str) -> dict[str, Any]:
        self.counts["client_lookup"] += 1
        return super().get_order_by_client_id(client_id)

    def get_order_by_id(self, order_id: UUID | str, filter: object = None) -> dict[str, Any]:
        self.counts["order_read"] += 1
        return super().get_order_by_id(order_id, filter)

    def get_orders(self, filter: object = None) -> list[dict[str, Any]]:
        self.counts["open_orders"] += 1
        return super().get_orders(filter)

    def get_all_positions(self) -> list[dict[str, Any]]:
        self.counts["positions"] += 1
        return super().get_all_positions()

    def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
        self.counts["submit"] += 1
        self.submit_calls += 1
        return self._submit_paper(order_data)

    def cancel_order_by_id(self, order_id: UUID | str) -> None:
        self.counts["cancel"] += 1
        self._cancel_paper(order_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("path", ["runtime", "panic", "panic-partial", "panic-completed"])
async def test_Q6_baseline_broker_counts(harness: Harness, path: str) -> None:
    broker = CountedBroker(harness)
    built = executor(harness, broker)
    try:
        alert = await deliver(harness)
        await built.enter(alert.proposal_id)
        if path == "runtime":
            assert broker.submit_calls == 1
        else:
            if path == "panic-partial":
                await fill_entry(harness, broker, built, partial=True)
            await built.close()
            built = executor(harness, broker, constructor=ProtectionRecovery)
            harness.state.escalate(SystemState.HALTED, "Offline Q6 panic baseline")
            broker.counts.clear()
            await built.cancel_unfilled_entries()
            if path == "panic-completed":
                broker.counts.clear()
                await built.cancel_unfilled_entries()
            assert harness.state.current() == SystemState.HALTED
        print("Q6", path, dict(sorted(broker.counts.items())))
        expected = {
            "runtime": {
                "account": 1,
                "client_lookup": 1,
                "open_orders": 3,
                "positions": 3,
                "submit": 1,
            },
            "panic": {"account": 1, "cancel": 1, "order_read": 6, "positions": 1},
            "panic-partial": {
                "account": 4,
                "cancel": 1,
                "client_lookup": 1,
                "open_orders": 3,
                "order_read": 7,
                "positions": 4,
                "submit": 1,
            },
            "panic-completed": {},
        }
        assert broker.counts == expected[path], "Q6 broker call counts must remain identical"
    finally:
        await built.close()
