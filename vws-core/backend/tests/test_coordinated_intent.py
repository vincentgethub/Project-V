"""S1 rev B: composition, caller-specific errors and production host wiring."""

import asyncio
import sys
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from backend.execution.coordinated_intent import CoordinatedResolver
from backend.execution.intent_resolution import IntentRefusal
from backend.execution.models import IntentDryRun
from backend.ops import quiescence
from backend.ops.process import ProcessLock
from backend.ops.quiescence import BrokerActor, BrokerCoordination, QuiescenceError
from backend.tests.broker_flag_fakes import FakeFlagAdapter
from backend.tests.test_broker_coordination import FakeLease, FakeSlots
from backend.tests.test_intent_resolution import HostInput, NoSecrets
from backend.tests.test_intent_resolution import case as ga_case

case = ga_case


def test_F1_slotless_panic_precreates_flag_before_resolver_and_current_call(tmp_path: Path) -> None:
    slots = FakeSlots()
    flag = FakeFlagAdapter()
    coordination = BrokerCoordination(tmp_path, slots, flag)
    coordination.initialize()
    blockers: list[BrokerActor] = []
    for _ in range(8):
        blocker = BrokerActor(coordination, "panic")
        blocker.start()
        blockers.append(blocker)
    actor = BrokerActor(UnpublishedPanic(tmp_path, slots, flag), "panic")
    actor.start()
    calls: list[str] = []
    refused: list[bool] = []

    def operation() -> None:
        for blocker in blockers:
            blocker.finish()
        try:
            with coordination.resolver():
                refused.append(False)
        except QuiescenceError:
            refused.append(True)
        calls.append("broker")

    try:
        actor.retain()
        actor.physical_call(operation)
        assert calls == ["broker"]
        assert refused == [True], (
            "new resolver must refuse at start before the panic's current call"
        )
        assert flag.signaled and flag.retained and flag.waits == 0
    finally:
        actor.finish()


@pytest.fixture(autouse=True)
def flag_backend(monkeypatch: pytest.MonkeyPatch) -> FakeFlagAdapter:
    """Inject the approved per-test adapter, without changing Q3's body/assertions."""
    shared = FakeFlagAdapter()
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: shared)
    return shared


class UnpublishedPanic(BrokerCoordination):
    def publish(self, identity: UUID, phase: str, kind: str, slot: bool) -> None:
        raise OSError("Offline publication unavailable")

    def publish_failure(self, identity: UUID, error_type: str) -> None:
        raise OSError("Offline publication unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("when", ["start", "middle", "before-commit"])
async def test_FE1_flag_signal_is_never_reset(
    tmp_path: Path, flag_backend: FakeFlagAdapter, strict: bool, when: str
) -> None:
    coordination = BrokerCoordination(tmp_path, FakeSlots())
    coordination.initialize()
    if when == "start":
        flag_backend.signaled = flag_backend.retained = True

    async def evidence() -> IntentDryRun:
        if when != "start":
            assert flag_backend.signal_if_present()
        return result()

    value = None
    refusal = None
    try:
        value = await CoordinatedResolver(coordination).run(evidence, strict=strict)
    except IntentRefusal as error:
        refusal = error.code
    if strict:
        assert refusal == "FIX_G_QUIESCENCE_UNVERIFIED"
    else:
        assert value is not None and not value.quiescence_verified
    assert flag_backend.signaled, "a signaled event is never reset"
    assert flag_backend.windows == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["open", "read-start", "read-end", "close"])
@pytest.mark.parametrize("strict", [False, True])
async def test_FE2_flag_adapter_error_is_no_proof(
    tmp_path: Path, flag_backend: FakeFlagAdapter, failure: str, strict: bool
) -> None:
    coordination = BrokerCoordination(tmp_path, FakeSlots())
    coordination.initialize()
    flag_backend.fail_at = failure

    async def evidence() -> IntentDryRun:
        return result()

    value = None
    refusal = None
    try:
        value = await CoordinatedResolver(coordination).run(evidence, strict=strict)
    except IntentRefusal as error:
        refusal = error.code
    if strict:
        assert refusal == "FIX_G_QUIESCENCE_UNVERIFIED"
    else:
        assert value is not None and not value.quiescence_verified
        assert not any(line.startswith("Quiescence: VERIFIED") for line in value.lines())


@pytest.mark.asyncio
async def test_FE3_absent_then_resolver_then_next_call_sets_flag_after_slot_probe(
    tmp_path: Path, flag_backend: FakeFlagAdapter
) -> None:
    class TracedSlots(FakeSlots):
        def acquire(self, name: str) -> Any:
            if name.startswith("slot-"):
                flag_backend.trace.append("slot")
            return super().acquire(name)

    slots = TracedSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    coordination.initialize()
    slots.held.update(f"slot-{index}" for index in range(8))
    actor = BrokerActor(UnpublishedPanic(tmp_path, slots), "panic")
    actor.start()
    actor.retain()
    actor.physical_call(lambda: None)
    assert flag_backend.signaled and flag_backend.retained
    slots.held.difference_update(f"slot-{index}" for index in range(8))

    async def evidence() -> IntentDryRun:
        flag_backend.trace.clear()
        actor.retain()
        actor.physical_call(lambda: flag_backend.trace.append("broker"))
        actor.finish()
        return result()

    value = await CoordinatedResolver(coordination).run(evidence)
    assert flag_backend.trace == ["slot", "flag", "broker"]
    assert not value.quiescence_verified
    assert flag_backend.waits == 0


@pytest.mark.asyncio
async def test_FE4_handle_lives_after_panic_scope_until_process_exit(
    tmp_path: Path, flag_backend: FakeFlagAdapter
) -> None:
    slots = FakeSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    coordination.initialize()

    async def evidence() -> IntentDryRun:
        actor = BrokerActor(UnpublishedPanic(tmp_path, slots), "panic")
        actor.start()
        actor.retain()
        actor.physical_call(lambda: None)
        actor.finish()
        return result()

    await CoordinatedResolver(coordination).run(evidence)
    assert flag_backend.retained and flag_backend.signaled
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        await CoordinatedResolver(coordination).run(evidence, strict=True)


def test_FE5_no_resolver_panic_proceeds_without_wait(
    tmp_path: Path, flag_backend: FakeFlagAdapter
) -> None:
    slots = FakeSlots()
    slots.held.update(f"slot-{index}" for index in range(8))
    actor = BrokerActor(BrokerCoordination(tmp_path, slots), "panic")
    actor.start()
    calls: list[str] = []
    actor.retain()
    actor.physical_call(lambda: calls.append("cancel"))
    actor.finish()
    assert calls == ["cancel"]
    assert flag_backend.signals == 1 and flag_backend.signaled and flag_backend.retained
    assert flag_backend.waits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "corrupt",
        "rollback",
        "truncated",
        "denied",
        "disappeared",
        "slot-error",
        "abandoned",
        "release-error",
    ],
)
async def test_Q11_full_coordination_fault_matrix(
    tmp_path: Path,
    flag_backend: FakeFlagAdapter,
    strict: bool,
    fault: str,
) -> None:
    class BadRelease(FakeLease):
        def release(self) -> None:
            super().release()
            raise OSError("offline release unavailable")

    class FaultSlots(FakeSlots):
        def acquire(self, name: str) -> Any:
            if name == "slot-4" and fault == "slot-error":
                raise OSError("offline slot unavailable")
            if name == "slot-4" and fault == "abandoned":
                raise QuiescenceError("Abandoned broker mutex is unverified")
            lease = super().acquire(name)
            if name == "slot-4" and fault == "release-error" and lease is not None:
                return BadRelease(self, name)
            return lease

    class FaultInventory(BrokerCoordination):
        reads = 0

        def _inventory(self) -> tuple[tuple[str, str], ...]:
            self.reads += 1
            if fault == "denied":
                raise PermissionError("offline inventory denied")
            if fault == "disappeared" and self.reads > 1:
                raise FileNotFoundError("offline inventory disappeared")
            return super()._inventory()

    coordination = FaultInventory(tmp_path, FaultSlots(), flag_backend)
    if fault != "missing":
        coordination.initialize()
    if fault == "corrupt":
        (coordination.directory / "generation").write_bytes(b"corrupt")
    if fault == "truncated":
        (coordination.directory / (UUID(int=90).hex + ".BEGIN")).write_bytes(b"{")

    async def evidence() -> IntentDryRun:
        if fault == "rollback":
            (coordination.directory / "generation").write_text("0" * 32)
        return result()

    value, refusal = None, None
    try:
        value = await CoordinatedResolver(coordination).run(evidence, strict=strict)
    except IntentRefusal as error:
        refusal = error.code
    if strict:
        assert refusal == "FIX_G_QUIESCENCE_UNVERIFIED"
    else:
        assert value is not None and not value.quiescence_verified


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_Q1_Q7_Q12_panic_after_final_get_before_proof_barrier(
    case: Any,
    flag_backend: FakeFlagAdapter,
    strict: bool,
) -> None:
    from backend.tests.test_intent_resolution import Reads, run

    reader, _, clock, settings = case
    slots = FakeSlots()
    coordination = BrokerCoordination(reader.project, slots, flag_backend)
    coordination.initialize()
    calls: list[str] = []

    class BoundaryReads(Reads):
        async def open_orders(self) -> Any:
            value = await super().open_orders()
            if self.open_calls == 2:
                actor = BrokerActor(UnpublishedPanic(reader.project, slots, flag_backend), "panic")
                actor.start()
                actor.retain()
                actor.physical_call(lambda: calls.append("cancel"))
                actor.finish()
            return value

    refusal, value = None, None
    try:
        value = await CoordinatedResolver(coordination).run(
            lambda: run((reader, BoundaryReads(clock), clock, settings)),
            strict=strict,
        )
    except IntentRefusal as error:
        refusal = error.code
    assert calls == ["cancel"]
    if strict:
        assert refusal == "FIX_G_QUIESCENCE_UNVERIFIED"
    else:
        assert value is not None and not value.quiescence_verified


@pytest.mark.asyncio
async def test_Q2_Q12_resolver_creation_after_absent_probe_before_current_broker_call(
    tmp_path: Path,
) -> None:
    """Fixture correction: the ABSENT state was removed by design.

    AMENDMENT_panic_flag_rev2.md SHA256:
    65136464eb773e97a6a54c78298d416299c32df8c09664afac0a9ca3bc51999e.
    """
    slots = FakeSlots()
    blockers: list[BrokerActor] = []
    proof_context: Any = None
    proof: Any = None
    refusals: list[str] = []
    reported_verified: list[bool] = []
    apply_reachable = False
    runtime_guard: ProcessLock | None = None

    class GapFlag(FakeFlagAdapter):
        def signal_if_present(self) -> bool:
            nonlocal proof_context, proof, apply_reachable, runtime_guard
            for blocker in blockers:
                blocker.finish()
            present = super().signal_if_present()
            assert present and self.signaled, "panic signals before the resolver starts"
            # Interleaving after CreateEvent/SetEvent, before the current broker call.
            proof_context = CoordinatedResolver(coordination).window(strict=True)
            with pytest.raises(IntentRefusal) as refusal:
                proof = proof_context.__enter__()
                reported_verified.append(proof.verified)
                apply_reachable = True
            refusals.append(refusal.value.code)
            assert not coordination._leases, "refusing resolver must release every broker slot"
            assert not any(name.startswith("slot-") for name in slots.held)
            assert self.windows == 0, "refusing resolver must close its flag handle"
            assert calls == [], "resolver refusal must precede every broker call"
            runtime_guard = ProcessLock(tmp_path / "data/runtime.lock")
            runtime_guard.__enter__()
            assert runtime_guard.fd is not None, "runtime.lock must be available after refusal"
            return present

    flag = GapFlag()
    coordination = BrokerCoordination(tmp_path, slots, flag)
    coordination.initialize()
    (tmp_path / "data/runtime.lock").write_bytes(b"0")
    for _ in range(8):
        blocker = BrokerActor(coordination, "panic")
        blocker.start()
        blockers.append(blocker)
    actor = BrokerActor(UnpublishedPanic(tmp_path, slots, flag), "panic")
    actor.start()
    assert actor.slot is None
    calls: list[str] = []
    try:
        actor.retain()
        actor.physical_call(lambda: calls.append("cancel"))
        assert calls == ["cancel"] and flag.signals == 1
        assert not actor._flag_failed, "no SetEvent operation failed in this interleaving"
        assert refusals == ["FIX_G_QUIESCENCE_UNVERIFIED"] and proof is None
        assert flag.signaled and flag.retained, "resolver must never reset the panic signal"
        assert not coordination._leases and flag.waits == 0
        assert not any(name.startswith("slot-") for name in slots.held)
        assert not reported_verified and not apply_reachable, (
            "a current-call panic cannot be invisible to a newly created resolver"
        )
    finally:
        if runtime_guard is not None:
            runtime_guard.__exit__(None, None, None)
        if proof_context is not None:
            proof_context.__exit__(None, None, None)
        actor.finish()


def result() -> IntentDryRun:
    return IntentDryRun(
        intent_id=UUID(int=1),
        account="offline-paper",
        outcome="TERMINAL",
        status="canceled",
        pause_owner=None,
    )


@pytest.mark.asyncio
async def test_B1_healthy_wrapper_marks_verified(tmp_path: Path) -> None:
    coordination = BrokerCoordination(tmp_path, FakeSlots())
    coordination.initialize()

    async def evidence() -> IntentDryRun:
        return result()

    value = await CoordinatedResolver(coordination).run(evidence)
    assert any(line.startswith("Quiescence: VERIFIED") for line in value.lines())


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("offline"), QuiescenceError("offline")])
async def test_B2_expected_adapter_error_reports_inner_outcome(
    tmp_path: Path, error: Exception
) -> None:
    class FailedAdapter(FakeSlots):
        def acquire(self, name: str) -> None:
            self.probes.append(name)
            raise error

    slots = FailedAdapter()

    async def evidence() -> IntentDryRun:
        return result()

    value = await CoordinatedResolver(BrokerCoordination(tmp_path, slots)).run(evidence)
    assert slots.probes, "the wrapper must actually probe the real coordination dependency"
    assert value.outcome == "TERMINAL"
    assert any(line.startswith("Quiescence: UNVERIFIED") for line in value.lines())


@pytest.mark.asyncio
async def test_B3_apply_refuses_expected_proof_error(tmp_path: Path) -> None:
    slots = FakeSlots()
    slots.error = True
    called = False

    async def evidence() -> IntentDryRun:
        nonlocal called
        called = True
        return result()

    refused = False
    try:
        await CoordinatedResolver(BrokerCoordination(tmp_path, slots)).run(evidence, strict=True)
    except IntentRefusal as error:
        refused = error.code == "FIX_G_QUIESCENCE_UNVERIFIED"
    assert refused and not called, "apply must refuse before its evidence/apply body"


@pytest.mark.parametrize("site", ["acquire", "body"])
def test_B4_unexpected_resolver_error_propagates_unchanged(tmp_path: Path, site: str) -> None:
    original = ValueError("offline unexpected sentinel")

    class Unexpected(FakeSlots):
        def acquire(self, name: str) -> Any:
            if site == "acquire":
                raise original
            return super().acquire(name)

    coordination = BrokerCoordination(tmp_path, Unexpected())
    coordination.initialize()
    caught = None
    try:
        with coordination.resolver():
            raise original
    except Exception as error:
        caught = error
    assert caught is original, "unexpected errors must not be reclassified as missing proof"


def test_B5_panic_records_known_adapter_failure_and_still_calls_broker(tmp_path: Path) -> None:
    slots = FakeSlots()
    slots.error = True
    coordination = BrokerCoordination(tmp_path, slots)
    actor = BrokerActor(coordination, "panic")
    actor.start()
    actor.retain()
    calls: list[str] = []
    actor.physical_call(lambda: calls.append("protect"))
    actor.finish()
    assert calls == ["protect"]
    assert list(coordination.directory.glob("*.FAIL")), "adapter failure must be durable evidence"


def test_B6_panic_does_not_swallow_unexpected_error(tmp_path: Path) -> None:
    original = ValueError("offline unexpected sentinel")

    class Unexpected(FakeSlots):
        def acquire(self, name: str) -> None:
            raise original

    actor = BrokerActor(BrokerCoordination(tmp_path, Unexpected()), "panic")
    caught = None
    try:
        actor.start()
    except Exception as error:
        caught = error
    assert caught is original, "only the adapter's documented failure types may be contained"


@pytest.mark.parametrize("site", ["acquire", "body"])
def test_B7_keyboard_interrupt_is_never_contained(tmp_path: Path, site: str) -> None:
    original = KeyboardInterrupt()

    class Interrupted(FakeSlots):
        def acquire(self, name: str) -> Any:
            if site == "acquire":
                raise original
            return super().acquire(name)

    coordination = BrokerCoordination(tmp_path, Interrupted())
    coordination.initialize()
    with pytest.raises(KeyboardInterrupt) as caught:
        with coordination.resolver():
            raise original
    assert caught.value is original


def test_B8_production_cli_uses_wrapper_with_real_adapter(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.ops.quiescence import OSSlots
    from vws import intent_cli

    seen: list[object] = []

    async def capture_run(
        self: CoordinatedResolver,
        operation: Callable[[], Awaitable[IntentDryRun]],
        *,
        strict: bool = False,
    ) -> IntentDryRun:
        assert isinstance(self.coordination.adapter, OSSlots)
        seen.append(self.coordination.adapter)
        return await operation()

    async def evidence(*args: object, **kwargs: object) -> IntentDryRun:
        return result()

    def inline(operation: Coroutine[object, object, IntentDryRun]) -> IntentDryRun:
        try:
            operation.send(None)
        except StopIteration as finished:
            return IntentDryRun.model_validate(finished.value)
        raise AssertionError("the explicit wiring fake must not suspend")

    monkeypatch.setattr(CoordinatedResolver, "run", capture_run)
    monkeypatch.setattr(intent_cli, "dry_run", evidence)
    monkeypatch.setattr(intent_cli, "KeyringSecretStore", NoSecrets)
    monkeypatch.setattr(intent_cli, "load_host_settings", lambda *_args: case[3])
    monkeypatch.setattr(asyncio, "run", inline)
    monkeypatch.setattr(sys, "stdin", HostInput())
    for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("SESSIONNAME", "Console")
    code = intent_cli.execute(
        intent=str(UUID(int=1)),
        account="offline-paper",
        environment="PAPER",
        operator="Owner",
        reason="offline wiring evidence",
    )
    assert code == 0
    assert len(seen) == 1, "production must never call the bare resolver directly"


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_Q3_all_slots_owned_and_publication_unavailable_cannot_certify(
    tmp_path: Path, strict: bool
) -> None:
    """Exercise the design's invisible-panic counterexample, not a collection failure."""
    slots = FakeSlots()
    coordination = BrokerCoordination(tmp_path, slots)
    coordination.initialize()

    class UnpublishedPanic(BrokerCoordination):
        def publish(self, identity: UUID, phase: str, kind: str, slot: bool) -> None:
            raise OSError("Offline publication unavailable")

        def publish_failure(self, identity: UUID, error_type: str) -> None:
            raise OSError("Offline publication unavailable")

    calls: list[str] = []

    async def evidence() -> IntentDryRun:
        assert all(f"slot-{index}" in slots.held for index in range(8))
        actor = BrokerActor(UnpublishedPanic(tmp_path, slots), "panic")
        actor.start()
        assert actor.slot is None
        actor.retain()
        actor.physical_call(lambda: calls.append("cancel"))
        actor.retain()
        actor.physical_call(lambda: calls.append("protective-submit"))
        actor.finish()
        return result()

    refusal = None
    value = None
    try:
        value = await CoordinatedResolver(coordination).run(evidence, strict=strict)
    except IntentRefusal as error:
        refusal = error.code
    assert calls == ["cancel", "protective-submit"], "panic must continue both emergency operations"
    if strict:
        assert refusal == "FIX_G_QUIESCENCE_UNVERIFIED", "apply must not certify an invisible panic"
    else:
        assert value is not None
        assert not value.quiescence_verified, "dry-run must report this unproven quiescence"
