"""G-q command-level panic evidence with explicit offline adapters."""

import asyncio
import threading
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from shutil import copytree
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent, SystemEvent, create_database, create_schema
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.async_reader import AsyncTokenBucket
from backend.execution import alpaca_executor
from backend.execution.worker import SingleAttemptWorker
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import make_client
from backend.ops import quiescence
from backend.ops.anchors import LedgerAnchors
from backend.ops.panic_flag import PanicFlagError
from backend.ops.quiescence import BrokerCoordination, current_actor
from backend.ops.security import ConfigDriftGuard, SecurityOps
from backend.security import secrets
from backend.tests.broker_flag_fakes import FakeFlagAdapter
from backend.tests.test_auto_execution import AUTO, executor, fill_entry
from backend.tests.test_broker_coordination import CountedBroker, FakeSlots
from backend.tests.test_security_cli import MemorySecrets, make_security_context
from backend.tests.test_security_cli import no_native_keyring as no_native_keyring
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from vws import __main__ as cli
from vws import execution_cli, host_config, runtime_cli, security_cli

context = make_security_context
harness = make_research_harness


@pytest.fixture
def adapters(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeSlots, FakeFlagAdapter]:
    slots, flag = FakeSlots(), FakeFlagAdapter()
    monkeypatch.setattr(quiescence, "OSSlots", lambda _directory: slots)
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: flag)
    return slots, flag


def test_B1_flag_and_both_record_writes_fail_nonzero_after_emergency_ops(
    context: security_cli.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    adapters: tuple[FakeSlots, FakeFlagAdapter],
    capsys: pytest.CaptureFixture[str],
) -> None:
    slots, flag = adapters
    slots.held.update(f"slot-{index}" for index in range(8))
    flag.fail_at = "signal"
    bound = replace(context, emergency_mode="AUTO_PAPER")
    monkeypatch.setattr(security_cli, "open_context", lambda *_args, **_kwargs: bound)
    monkeypatch.setattr(secrets, "KeyringSecretStore", MemorySecrets)

    def record_unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("offline record unavailable")

    monkeypatch.setattr(BrokerCoordination, "publish", record_unavailable)
    monkeypatch.setattr(BrokerCoordination, "publish_failure", record_unavailable)
    calls: list[str] = []

    async def cancel(*_args: object) -> None:
        assert context.state.current() == SystemState.HALTED
        actor = current_actor()
        assert actor is not None
        for kind in ("cancel", "protective-submit"):
            actor.retain()

            def record_call(kind: str = kind) -> None:
                calls.append(kind)

            actor.physical_call(record_call)

    async def notify(*_args: object) -> None:
        calls.append("notify")

    async def activity(*_args: object) -> tuple[str, ...]:
        calls.append("activity")
        return ("Verified offline activity",)

    monkeypatch.setattr(execution_cli, "panic_cancel", cancel)
    monkeypatch.setattr(security_cli, "panic_notify", notify)
    monkeypatch.setattr(security_cli, "panic_activities", activity)
    code = cli.main(["ops", "panic", "--operator", "Owner", "--reason", "offline emergency"])
    captured = capsys.readouterr()
    assert calls == ["cancel", "protective-submit", "notify", "activity"]
    lines = [line for line in captured.err.splitlines() if "PANIC_NOT_RECORDED" in line]
    assert len(lines) == 1
    assert "clear-intent --apply must not run until vws doctor is clean" in lines[0]
    assert code != 0, "unrecorded panic must not report command success"


def file_ops(tmp_path: Path, clock: FrozenClock) -> SecurityOps:
    engine = create_database("sqlite:///" + str(tmp_path / "ledger.sqlite3"))
    create_schema(engine)
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    return SecurityOps(state.ledger, state, clock)


def test_Q8_direct_panic_already_halted_keeps_original_reason_and_new_invocation(
    tmp_path: Path, clock: FrozenClock, adapters: tuple[FakeSlots, FakeFlagAdapter]
) -> None:
    ops = file_ops(tmp_path, clock)
    identities: list[object] = []

    def cancel() -> None:
        actor = current_actor()
        assert actor is not None
        identities.append(actor.identity)
        actor.retain()
        actor.physical_call(lambda: None)

    try:
        ops.state.escalate(SystemState.HALTED, "earlier retained fault")
        for _ in range(2):
            result = ops.panic("Owner", "offline panic", mode="AUTO_PAPER", cancel_unfilled=cancel)
            assert result.state == SystemState.HALTED
        assert len(identities) == 2 and identities[0] != identities[1]
        with Session(ops.ledger.engine) as session:
            reasons = tuple(
                session.scalars(select(SystemEvent.reason).where(SystemEvent.state == "HALTED"))
            )
        assert reasons == ("earlier retained fault",)
        assert len(list((tmp_path / "data/broker-coordination").glob("*.BEGIN"))) == 2
    finally:
        ops.ledger.engine.dispose()


@pytest.mark.parametrize("fault", ["end", "notify", "audit"])
def test_Q13_optional_failures_preserve_panic_order_and_counts(
    tmp_path: Path,
    clock: FrozenClock,
    adapters: tuple[FakeSlots, FakeFlagAdapter],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    ops = file_ops(tmp_path, clock)
    calls: list[str] = []
    original_publish = BrokerCoordination.publish
    original_append = ops.ledger.append

    def publish(self: BrokerCoordination, *args: Any, **kwargs: Any) -> None:
        if fault == "end" and args[1] == "END":
            raise OSError("offline end unavailable")
        original_publish(self, *args, **kwargs)

    def append(table: Any, **kwargs: Any) -> Any:
        if fault == "audit" and table is SecurityEvent and kwargs.get("kind") == "PANIC":
            raise OSError("offline audit unavailable")
        return original_append(table, **kwargs)

    def cancel() -> None:
        calls.append("cancel")

    def notify(_text: str) -> None:
        calls.append("notify")
        if fault == "notify":
            raise OSError("offline notice unavailable")

    def activity(_since: object) -> tuple[str, ...]:
        calls.append("activity")
        return ("offline",)

    monkeypatch.setattr(BrokerCoordination, "publish", publish)
    monkeypatch.setattr(ops.ledger, "append", append)
    try:
        result = ops.panic(
            "Owner",
            "offline",
            mode="AUTO_PAPER",
            cancel_unfilled=cancel,
            notify=notify,
            read_activities=activity,
        )
        assert calls == ["cancel", "notify", "activity"]
        assert result.state == SystemState.HALTED
        expected = {"end": (), "notify": ("notify Telegram",), "audit": ("write panic audit",)}
        assert result.failed_steps == expected[fault]
        if fault == "end":
            assert BrokerCoordination(tmp_path).doctor_message() is not None
    finally:
        ops.ledger.engine.dispose()


def test_Q14_flag_failure_records_types_not_diagnostic_text(
    tmp_path: Path,
    adapters: tuple[FakeSlots, FakeFlagAdapter],
    caplog: pytest.LogCaptureFixture,
) -> None:
    slots, _ = adapters
    canary = "private-diagnostic-canary-never-record"

    class CanaryFlag(FakeFlagAdapter):
        def signal_if_present(self) -> bool:
            raise PanicFlagError(canary)

    flag = CanaryFlag()
    slots.held.update(f"slot-{index}" for index in range(8))
    flag.fail_at = "signal"
    actor = quiescence.BrokerActor(BrokerCoordination(tmp_path, slots, flag), "panic")
    actor.start()
    actor.retain()
    actor.physical_call(lambda: None)
    actor.finish()
    records = list((tmp_path / "data/broker-coordination").glob("*.FAIL"))
    assert len(records) == 1
    assert '"error_type": "PanicFlagError"' in records[0].read_text()
    assert canary not in records[0].read_text() + caplog.text


def test_Q1_runtime_cannot_overflow_broker_slots(
    tmp_path: Path, adapters: tuple[FakeSlots, FakeFlagAdapter]
) -> None:
    slots, _ = adapters
    slots.held.update(f"slot-{index}" for index in range(8))
    calls: list[str] = []
    refused = False
    try:
        with quiescence.actor_scope(tmp_path, "runtime"):
            calls.append("runtime broker read")
    except quiescence.QuiescenceError:
        refused = True
    assert refused and not calls, "only panic may proceed without an actor slot"


@pytest.mark.asyncio
async def test_Q1_Q16_panic_activity_account_read_signals_before_transport(
    context: security_cli.SecurityContext,
    tmp_path: Path,
    adapters: tuple[FakeSlots, FakeFlagAdapter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.funding import activities
    from backend.ops import read_checks
    from backend.tests.test_panic_callbacks import bound

    bound(context, monkeypatch)
    context.state.escalate(SystemState.HALTED, "offline activity-read coordination")
    slots, flag = adapters
    slots.held.update(f"slot-{index}" for index in range(8))
    handle = flag.open_window()
    seen: list[bool] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(flag.signaled)
        return httpx.Response(
            200,
            json={
                "id": str(UUID(int=1)),
                "status": "ACTIVE",
                "currency": "USD",
                "buying_power": "10000.00",
                "equity": "10000.00",
                "trading_blocked": False,
                "account_blocked": False,
                "trade_suspended_by_user": False,
            },
        )

    original_factory = make_client

    def offline_factory(purpose: str, **kwargs: Any) -> Any:
        return original_factory(purpose, transport=httpx.MockTransport(respond), **kwargs)

    class AccountObserved(Exception):
        pass

    class StopAfterAccount:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise AccountObserved("offline account read completed")

    monkeypatch.setattr(read_checks, "make_client", offline_factory)
    monkeypatch.setattr(activities, "AlpacaActivitiesSource", StopAfterAccount)
    try:
        with quiescence.actor_scope(tmp_path, "panic"):
            with pytest.raises(AccountObserved):
                await security_cli.panic_activities(
                    context, MemorySecrets(), context.ledger.clock.now()
                )
        assert seen == [True], "standalone panic account GET must signal before the real HTTP hook"
    finally:
        handle.close()


@pytest.mark.asyncio
async def test_Q9_event_blocked_real_worker_holds_lifetime_until_actual_exit(
    tmp_path: Path, clock: FrozenClock, adapters: tuple[FakeSlots, FakeFlagAdapter]
) -> None:
    entered, exited = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    records: list[object] = []
    worker = SingleAttemptWorker(AsyncTokenBucket(clock))
    worker.set_transport_recorder(records.append, on_refusal_error=records.append)

    def physical() -> None:
        worker.before_request()
        loop.call_soon_threadsafe(entered.set)
        try:
            release.wait()
        finally:
            loop.call_soon_threadsafe(exited.set)

    with quiescence.actor_scope(tmp_path, "panic") as actor:
        task = asyncio.create_task(worker.attempt(physical))
        try:
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            actor.finish()
            assert actor._pending == 1
            assert not list(actor.coordination.directory.glob("*.END"))
            with pytest.raises(quiescence.QuiescenceError):
                with BrokerCoordination(tmp_path).resolver():
                    raise AssertionError("a still-running physical worker is not quiescent")
        finally:
            release.set()
            await exited.wait()
            await worker.aclose()
    assert actor._pending == 0
    assert len(list(actor.coordination.directory.glob("*.END"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("with_flag", [False, True])
@pytest.mark.parametrize("path", ["panic", "panic-partial", "panic-completed", "manual"])
async def test_Q1_Q5_Q6_Q16_real_panic_roots_preserve_baseline_counts(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapters: tuple[FakeSlots, FakeFlagAdapter],
    path: str,
    with_flag: bool,
) -> None:
    slots, flag = adapters
    broker = CountedBroker(harness)
    built = executor(harness, broker)
    alert = await deliver(harness)
    await built.enter(alert.proposal_id)
    if path == "panic-partial":
        await fill_entry(harness, broker, built, partial=True)
    await built.close()
    harness.state.escalate(SystemState.HALTED, "offline real panic root")
    settings = harness.settings
    if path == "manual":
        settings = type(settings).validated_copy(
            settings.model_copy(update={"execution_mode": "MANUAL"})
        )
    copytree(Path(__file__).resolve().parents[2] / "config", tmp_path / "config")
    for name in ("data", "logs", "backups"):
        (tmp_path / name).mkdir(mode=0o700, exist_ok=True)
    context = security_cli.SecurityContext(
        settings,
        harness.state.engine,
        harness.state.ledger,
        harness.state,
        SecurityOps(harness.state.ledger, harness.state, harness.clock),
        ConfigDriftGuard(harness.state.ledger, harness.clock),
        LedgerAnchors(harness.state.ledger, harness.clock),
        None,
    )
    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger)
    monkeypatch.setattr(security_cli, "PROJECT", tmp_path)
    monkeypatch.setattr(host_config, "load_host_settings", lambda *_args: settings)
    monkeypatch.setattr(security_cli, "configure_egress", lambda *_args: None)
    monkeypatch.setattr(security_cli, "_require_network_policy", lambda *_args: policy)
    monkeypatch.setattr(alpaca_executor, "make_execution_client", lambda *_args, **_kwargs: broker)
    made: list[alpaca_executor.ProtectionRecovery] = []
    actors: list[quiescence.BrokerActor] = []

    class ObservedRecovery(alpaca_executor.ProtectionRecovery):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            owner = current_actor()
            assert owner is not None, "root coordination precedes recovery/worker construction"
            actors.append(owner)
            super().__init__(*args, **kwargs)
            assert self.worker._recorder == self._record_transport
            assert self.worker._refusal_error == harness.state.halt_for_error
            made.append(self)

    monkeypatch.setattr(alpaca_executor, "ProtectionRecovery", ObservedRecovery)
    store = MemorySecrets()
    store.set("ALPACA_PAPER_KEY_ID", settings.broker_api_key)
    store.set("ALPACA_PAPER_SECRET", settings.broker_secret_key)
    handle = None
    if with_flag:
        slots.held.update(f"slot-{index}" for index in range(8))
        handle = flag.open_window()
    try:
        if path == "panic-completed":
            await execution_cli.panic_cancel(context, store)
        broker.counts.clear()
        flag.signals = 0
        await execution_cli.panic_cancel(context, store)
        expected = {
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
            "manual": {},
        }
        assert broker.counts == expected[path]
        if with_flag:
            assert flag.signals == sum(broker.counts.values()), (
                "every physical call rechecks the flag"
            )
        else:
            assert flag.signals == 0, "a held actor slot already excludes resolver proof"
        assert all(not recovery.worker.has_pending_attempts for recovery in made)
        assert all(actor._pending == 0 for actor in actors)
        assert harness.state.current() == SystemState.HALTED
    finally:
        if handle is not None:
            handle.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_Q1_Q16_Q17_runtime_entry_uses_real_wiring_under_host_slot(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapters: tuple[FakeSlots, FakeFlagAdapter],
) -> None:
    from alpaca.trading.enums import AccountStatus

    from backend.ops.read_checks import PaperAccountCheck, ReadChecksClient
    from backend.tests.test_host_runtime import doctor_result
    from backend.tests.test_refusal_error_wiring import (
        OfflineActivities,
        OfflinePrerequisites,
        OfflineTicketMatcher,
    )

    copytree(Path(__file__).resolve().parents[2] / "config", tmp_path / "config")
    for name in ("data", "logs", "backups"):
        (tmp_path / name).mkdir(mode=0o700, exist_ok=True)
    context = security_cli.SecurityContext(
        harness.settings,
        harness.state.engine,
        harness.state.ledger,
        harness.state,
        SecurityOps(harness.state.ledger, harness.state, harness.clock),
        ConfigDriftGuard(harness.state.ledger, harness.clock),
        LedgerAnchors(harness.state.ledger, harness.clock),
        None,
    )
    seen: list[SingleAttemptWorker] = []
    calls: list[str] = []

    class WiringObserved(Exception):
        pass

    class ObservedWorker(SingleAttemptWorker):
        def set_transport_recorder(self, recorder: Any, *, on_refusal_error: Any) -> None:
            assert current_actor() is not None
            super().set_transport_recorder(recorder, on_refusal_error=on_refusal_error)
            assert on_refusal_error == harness.state.halt_for_error
            seen.append(self)
            raise WiringObserved("offline final runtime wiring observed")

    async def account(*_args: Any, **_kwargs: Any) -> PaperAccountCheck:
        actor = current_actor()
        assert actor is not None and actor.slot is not None
        assert list(actor.coordination.directory.glob("*.BEGIN"))
        calls.append("account")
        return PaperAccountCheck(
            account_id=UUID(int=1),
            equity=Decimal("10000.00"),
            buying_power=Decimal("10000.00"),
            status=AccountStatus.ACTIVE,
            currency="USD",
            trading_blocked=False,
            account_blocked=False,
            trade_suspended_by_user=False,
        )

    async def doctor(*_args: Any) -> Any:
        return doctor_result()

    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger)
    monkeypatch.setattr(security_cli, "PROJECT", tmp_path)
    monkeypatch.setattr(security_cli, "open_context", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(security_cli, "doctor_result", doctor)
    monkeypatch.setattr(security_cli, "configure_egress", lambda *_args: None)
    monkeypatch.setattr(security_cli, "_require_network_policy", lambda *_args: policy)
    monkeypatch.setattr(security_cli, "backups", lambda *_args: object())
    monkeypatch.setattr(context.drift, "check", lambda *_args, **_kwargs: None)
    store = MemorySecrets()
    store.set("ALPACA_PAPER_KEY_ID", harness.settings.broker_api_key)
    store.set("ALPACA_PAPER_SECRET", harness.settings.broker_secret_key)
    monkeypatch.setattr(runtime_cli, "KeyringSecretStore", lambda: store)
    monkeypatch.setattr(runtime_cli, "load_host_settings", lambda *_args: harness.settings)
    monkeypatch.setattr(runtime_cli, "configure_logging", lambda **_kwargs: None)
    monkeypatch.setattr(runtime_cli, "HostPrerequisites", OfflinePrerequisites)
    monkeypatch.setattr(runtime_cli, "TicketFillMatcher", OfflineTicketMatcher)
    monkeypatch.setattr(runtime_cli, "AlpacaActivitiesSource", OfflineActivities)
    monkeypatch.setattr(runtime_cli, "SingleAttemptWorker", ObservedWorker)
    monkeypatch.setattr(ReadChecksClient, "account", account)
    broker = CountedBroker(harness)
    monkeypatch.setattr(alpaca_executor, "make_execution_client", lambda *_args, **_kwargs: broker)
    try:
        with pytest.raises(WiringObserved):
            await runtime_cli.execute(None)
        assert calls == ["account"] and broker.counts == {}
        assert len(seen) == 1 and seen[0]._recorder is not None
    finally:
        for worker in seen:
            await worker.aclose()
