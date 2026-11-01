"""Fix G-0: required HALT wiring at the last physical request boundary."""

from collections.abc import Callable
from contextlib import AsyncExitStack
from decimal import Decimal
from pathlib import Path
from shutil import copytree
from typing import Any
from uuid import UUID

import httpx
import pytest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AccountStatus
from requests import Response
from requests import Session as RequestsSession

from backend.core.clock import Clock, FrozenClock
from backend.core.config import Settings
from backend.core.errors import ConfigurationError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader, AsyncTokenBucket
from backend.execution import alpaca_executor
from backend.execution import worker as worker_module
from backend.execution.alpaca_executor import configure_execution_client
from backend.execution.models import AutoPrerequisites
from backend.execution.modes import ModeStore
from backend.execution.worker import SingleAttemptWorker, TransportRecord
from backend.funding.activities import AlpacaActivitiesSource
from backend.net.egress import EgressPolicy, build_allowlist
from backend.ops.anchors import LedgerAnchors
from backend.ops.doctor import DoctorResult
from backend.ops.read_checks import PaperAccountCheck, ReadChecksClient
from backend.ops.security import ConfigDriftGuard, SecurityOps
from backend.tests.test_attempt_timeout import CountingPaperBroker, prepared_submit
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_execution_transport import response
from backend.tests.test_host_runtime import doctor_result
from backend.tests.test_security_cli import MemorySecrets
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from vws import execution_cli, host_config, runtime_cli, security_cli

harness = make_research_harness


def test_G0_1_setter_without_halt_callback_is_refused(clock: FrozenClock) -> None:
    worker = SingleAttemptWorker(AsyncTokenBucket(clock))
    records: list[TransportRecord] = []
    options: dict[str, Any] = {}
    with pytest.raises(TypeError, match="on_refusal_error"):
        worker.set_transport_recorder(records.append, **options)


def test_G0_2_setter_refuses_none_with_typed_configuration_error(clock: FrozenClock) -> None:
    worker = SingleAttemptWorker(AsyncTokenBucket(clock))
    records: list[TransportRecord] = []
    options: dict[str, Any] = {"on_refusal_error": None}
    with pytest.raises(ConfigurationError, match="refusal-error HALT callback"):
        worker.set_transport_recorder(records.append, **options)
    assert worker._recorder is None and worker._refusal_error is None


class WireRecorder:
    def __init__(self) -> None:
        self.calls = 0

    def record(self) -> None:
        self.calls += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_G0_3_unwired_worker_never_reaches_session_request(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = SingleAttemptWorker(AsyncTokenBucket(harness.clock))
    client = TradingClient(
        api_key="TEST_ONLY_PAPER_ID", secret_key="TEST_ONLY_PAPER_SECRET", paper=True, raw_data=True
    )
    recorder = WireRecorder()

    def wire(session: RequestsSession, method: str, url: str, **kwargs: Any) -> Response:
        recorder.record()
        return response(url, 200, {})

    configure_execution_client(
        client,
        harness.settings,
        EgressPolicy(build_allowlist(), harness.state.ledger),
        before_request=worker.before_request,
    )
    monkeypatch.setattr(RequestsSession, "request", wire)
    caught: Exception | None = None
    try:
        await worker.attempt(lambda: client.get_order_by_client_id("vws-g0-unwired"))
    except Exception as error:
        caught = error
    finally:
        await worker.aclose()
        client._session.close()
    assert recorder.calls == 0, "an unwired worker must refuse before Session.request"
    assert isinstance(caught, ConfigurationError)


class WiringObserved(Exception):
    """Stop composition after its final executor-constructor wiring statement."""


class OfflineActivities(AlpacaActivitiesSource):
    def __init__(
        self,
        settings: Settings,
        account_id: str,
        state: SystemStateStore,
        clock: Clock,
        reader: AsyncAlpacaReader,
        policy: EgressPolicy,
    ) -> None:
        super().__init__(
            settings,
            account_id,
            state,
            clock,
            reader,
            policy,
            transport=httpx.MockTransport(lambda request: httpx.Response(503)),
        )


class OfflinePrerequisites:
    def __init__(self, modes: ModeStore, doctor: DoctorResult, backups: object) -> None:
        self.modes = modes

    def __call__(self) -> AutoPrerequisites:
        now = self.modes.state.clock.now()
        return AutoPrerequisites(
            account_id=self.modes.account_id,
            environment=self.modes.environment,
            config_hash=self.modes.settings.config_hash,
            doctor_fully_green=True,
            watchdog_enabled=True,
            backup_chain_verified=True,
            backup_verified_at=now,
            telegram_verified_at=now,
            clock_verified_at=now,
        )


class OfflineTicketMatcher:
    """Isolate the legacy MANUAL matcher from the AUTO construction wiring test."""

    def __init__(
        self, settings: Settings, account_id: str, state: SystemStateStore, registry: object
    ) -> None:
        self.settings, self.account_id, self.state = settings, account_id, state


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("path", ["runtime", "panic"])
async def test_G0_4_production_constructions_wire_the_bound_state_halt_method(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    settings = Settings.validated_copy(
        harness.settings.model_copy(update={"telegram_chat_id": 123})
    )
    client = CountingPaperBroker(harness)
    if path == "panic":
        prepared, _, _, _ = await prepared_submit(harness, client, monkeypatch)
        await prepared.close()
        harness.state.escalate(SystemState.HALTED, "Offline panic construction fixture")
    copytree(Path(__file__).resolve().parents[2] / "config", tmp_path / "config")
    for name in ("data", "logs", "backups"):
        (tmp_path / name).mkdir()
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
    store = MemorySecrets()
    store.set("ALPACA_PAPER_KEY_ID", settings.broker_api_key)
    store.set("ALPACA_PAPER_SECRET", settings.broker_secret_key)
    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger)
    made: list[SingleAttemptWorker] = []

    class ObservedWorker(SingleAttemptWorker):
        def set_transport_recorder(
            self,
            recorder: Callable[[TransportRecord], None],
            *,
            on_refusal_error: Callable[[Exception], object],
        ) -> None:
            super().set_transport_recorder(recorder, on_refusal_error=on_refusal_error)
            made.append(self)
            raise WiringObserved("Observed the real executor's final wiring statement")

    async def account(
        reads: ReadChecksClient, selected: Settings, key: object, secret: object
    ) -> PaperAccountCheck:
        return PaperAccountCheck(
            account_id=UUID("00000000-0000-0000-0000-000000000001"),
            equity=Decimal("10000.00"),
            buying_power=Decimal("10000.00"),
            status=AccountStatus.ACTIVE,
            currency="USD",
            trading_blocked=False,
            account_blocked=False,
            trade_suspended_by_user=False,
        )

    monkeypatch.setattr(security_cli, "PROJECT", tmp_path)
    monkeypatch.setattr(security_cli, "_require_network_policy", lambda *_args: policy)
    monkeypatch.setattr(security_cli, "configure_egress", lambda *_args: None)
    monkeypatch.setattr(security_cli, "backups", lambda *_args: object())
    monkeypatch.setattr(context.drift, "check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_cli, "HostPrerequisites", OfflinePrerequisites)
    monkeypatch.setattr(runtime_cli, "TicketFillMatcher", OfflineTicketMatcher)
    monkeypatch.setattr(runtime_cli, "AlpacaActivitiesSource", OfflineActivities)
    monkeypatch.setattr(ReadChecksClient, "account", account)
    monkeypatch.setattr(alpaca_executor, "make_execution_client", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(host_config, "load_host_settings", lambda *_args: settings)
    monkeypatch.setattr(runtime_cli, "SingleAttemptWorker", ObservedWorker)
    monkeypatch.setattr(worker_module, "SingleAttemptWorker", ObservedWorker)
    try:
        with pytest.raises(WiringObserved):
            if path == "runtime":
                async with AsyncExitStack() as resources:
                    await runtime_cli.compose(context, store, doctor_result(), resources=resources)
            else:
                await execution_cli.panic_cancel(context, store)
        assert len(made) == 1
        assert made[0]._refusal_error == harness.state.halt_for_error
        assert made[0]._recorder is not None
        assert not made[0].has_pending_attempts
    finally:
        for worker in made:
            await worker.aclose()
