"""SEC: real SQLite host commands with fake keyring and guarded HTTP transport."""

import asyncio
import getpass
import json
import sys
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import inspect, select, update
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import (
    NewsHeadlineRecord,
    SchemaMeta,
    SecurityEvent,
    SystemControl,
    create_schema,
    prepare_panic_schema,
    transaction,
)
from backend.core.errors import ConfigurationError, DatabaseError, LedgerIntegrityError, SafetyError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import GuardedAsyncClient, make_client
from backend.ops.anchors import LedgerAnchors
from backend.ops.security import ConfigDriftGuard, SecurityOps
from backend.security import secrets as secret_module
from backend.security.permissions import PermissionFinding
from backend.tests.conftest import pytest_asyncio_loop_factories
from vws import __main__ as cli
from vws import security_cli as module

ResultT = TypeVar("ResultT")


class MemorySecrets:
    """SEC-11: no native store, file secret or process fallback exists in tests."""

    def __init__(self) -> None:
        self.values: dict[str, SecretStr] = {}

    def get(self, name: str) -> SecretStr | None:
        return self.values.get(name)

    def set(self, name: str, value: SecretStr) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


@pytest.fixture(autouse=True)
def no_native_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-11: any accidental keyring construction gets an isolated fake."""
    monkeypatch.setattr(secret_module, "KeyringSecretStore", MemorySecrets)
    monkeypatch.setattr(module, "KeyringSecretStore", MemorySecrets, raising=False)
    offline_loop = pytest_asyncio_loop_factories()["offline"]

    def run(coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
        with asyncio.Runner(loop_factory=offline_loop) as runner:
            return runner.run(coroutine)

    monkeypatch.setattr(asyncio, "run", run)


@pytest.fixture(name="context")
def make_security_context(
    engine: Engine,
    clock: FrozenClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[module.SecurityContext]:
    """SEC-73: real durable controls, with only the owner project path detached."""
    monkeypatch.setattr(module, "PROJECT", tmp_path)
    for name in ("data", "logs", "backups"):
        (tmp_path / name).mkdir(mode=0o700)
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    ledger = state.ledger
    settings = Settings(
        _env_file=None, broker_account_type="CASH", db_url=SecretStr(str(engine.url))
    )
    yield module.SecurityContext(
        settings,
        engine,
        ledger,
        state,
        SecurityOps(ledger, state, clock),
        ConfigDriftGuard(ledger, clock),
        LedgerAnchors(ledger, clock),
        None,
    )


def install_http(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    """SEC-30: the real factory checks destinations over an in-memory transport."""
    requests: list[httpx.Request] = []
    policy = EgressPolicy(build_allowlist(mode=context.settings.execution_mode), context.ledger)

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def factory(purpose: str) -> GuardedAsyncClient:
        return make_client(purpose, policy=policy, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(module, "make_client", factory)
    monkeypatch.setattr(module, "configure_egress", lambda _context: None)
    return requests


def events(engine: Engine, kind: str) -> list[dict[str, Any]]:
    with transaction(engine) as session:
        return [
            dict(row.detail)
            for row in session.scalars(select(SecurityEvent).where(SecurityEvent.kind == kind))
        ]


def active_account() -> dict[str, object]:
    return {
        "id": "c73bc052-88d4-48bd-bf60-1728e2a5e759",
        "account_number": "synthetic-account-mask",
        "status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }


def test_AX_41_disable_live_is_local_despite_invalid_trading_config_and_keyring_outage(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class OfflineStore(MemorySecrets):
        def get(self, name: str) -> SecretStr | None:
            assert name == "DB_URL", "Emergency disable must never retrieve broker credentials"
            raise RuntimeError("synthetic keyring outage")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Emergency disable must never probe a service")

    env = tmp_path / "selected.env"
    env.write_text(
        "EXECUTION_MODE=AUTO_LIVE\nPAPER_TRADING=false\n"
        "LIVE_MAX_ORDER_NOTIONAL=invalid\nBROKER_STATE_SOURCE=MANUAL_CSV\n"
        f"DB_URL={context.engine.url}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EXECUTION_MODE", "AUTO_LIVE")
    monkeypatch.setattr(secret_module, "KeyringSecretStore", OfflineStore)
    monkeypatch.setattr(module, "configure_egress", forbidden)
    monkeypatch.setattr(module, "doctor_result", forbidden)
    monkeypatch.setattr(module, "check_permissions", lambda **kwargs: ())
    monkeypatch.setattr(module, "SystemClock", lambda: context.ledger.clock)
    assert cli.main(["--env-file", str(env), "ops", "disable-live", "--operator", "Owner"]) == 0
    assert events(context.engine, "LIVE_DISABLED") == [{"operator": "Owner"}]
    assert "disabled locally" in capsys.readouterr().out
    context.ledger.verify_chain()


def test_OPS_02_healthcheck_reads_no_configuration_or_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from backend.core.clock import SystemClock
    from backend.ops.process import Heartbeat, ProcessLock, write_heartbeat

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "vws/__main__.py"))

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("health must never read settings, secrets or owner database")

    monkeypatch.setattr(module, "open_context", forbidden)
    monkeypatch.setattr(secret_module, "KeyringSecretStore", forbidden)
    assert cli.main(["--healthcheck"]) == 1
    write_heartbeat(
        data / "runtime-heartbeat.json",
        Heartbeat(
            run_id=uuid4(),
            updated_at=SystemClock().now(),
            mode="MANUAL",
            paper=True,
            scheduler_running=True,
        ),
    )
    with ProcessLock(data / "runtime.lock"):
        assert cli.main(["--healthcheck"]) == 0
    assert cli.main(["--healthcheck"]) == 1
    with pytest.raises(SystemExit):
        cli.main(["--healthcheck", "doctor"])


@pytest.mark.asyncio
async def test_OPS_02_composition_builds_six_real_jobs_without_orders_or_network(
    context: module.SecurityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import AsyncExitStack
    from dataclasses import replace
    from shutil import copytree

    from backend.agents.orchestrator import JobName
    from backend.core.clock import Clock
    from backend.core.errors import DataIntegrityError, ProviderError
    from backend.data.async_reader import AsyncAlpacaReader
    from backend.funding.activities import AlpacaActivitiesSource
    from backend.ops.account_context import LedgerAccountContext
    from backend.ops.doctor import Check, DoctorResult
    from backend.ops.read_checks import PaperAccountCheck, ReadChecksClient
    from vws import runtime_cli
    from vws.runtime_cli import compose

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

    monkeypatch.setattr(runtime_cli, "AlpacaActivitiesSource", OfflineActivities)

    original = Path(__file__).resolve().parents[2]
    copytree(original / "config", module.PROJECT / "config")
    context = replace(
        context,
        settings=Settings(
            _env_file=None,
            broker_account_type="CASH",
            db_url=SecretStr(str(context.engine.url)),
            broker_api_key=SecretStr("TEST_ONLY_PAPER_KEY"),
            broker_secret_key=SecretStr("TEST_ONLY_PAPER_SECRET"),
            telegram_bot_token=SecretStr("123456:TEST_ONLY_FAKE_TOKEN"),
            telegram_callback_secret=SecretStr("TEST_ONLY_CALLBACK_KEY_WITH_32_BYTES_MINIMUM"),
            telegram_allowed_user_ids=(123456,),
            telegram_chat_id=123456,
        ),
    )

    async def paper(
        _self: ReadChecksClient, _key: SecretStr, _secret: SecretStr
    ) -> PaperAccountCheck:
        from decimal import Decimal
        from uuid import UUID

        from alpaca.trading.enums import AccountStatus

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

    monkeypatch.setattr(ReadChecksClient, "paper_account", paper)
    policy = EgressPolicy(build_allowlist(), context.ledger)
    monkeypatch.setattr(module, "_require_network_policy", lambda _context, _config: policy)
    checked = DoctorResult(
        checks=(
            Check(
                name="synthetic",
                status="PASS",
                required=True,
                message="Synthetic composition gate",
                fix="Fixture",
            ),
        )
    )
    executor_before = sys.modules.get("backend.execution.alpaca_executor")
    async with AsyncExitStack() as resources:
        runtime = await compose(context, MemorySecrets(), checked, resources=resources)
        assert set(runtime.orchestrator.jobs) == set(JobName)
        assert runtime.settings.execution_mode == "MANUAL" and runtime.settings.paper_trading
        assert not runtime.orchestrator.scheduler.running
        assert sys.modules.get("backend.execution.alpaca_executor") is executor_before
        with pytest.raises(ProviderError):
            LedgerAccountContext(
                context.state, "00000000-0000-0000-0000-000000000001", "PAPER"
            ).read()
        from types import MethodType

        from backend.agents.jobs import DeskJobs
        from backend.ops.desk_source import ConnectedDeskSource

        body = runtime.orchestrator.jobs[JobName.DAILY_SCAN]
        assert isinstance(body, MethodType)
        jobs = body.__self__
        assert isinstance(jobs, DeskJobs)
        assert isinstance(jobs.source, ConnectedDeskSource)
        with pytest.raises(DataIntegrityError):
            await jobs.source.scan()
        with pytest.raises(DataIntegrityError):
            await jobs.source.refresh("NVDA")
        assert context.state.current() == SystemState.HALTED
        from datetime import timedelta

        from backend.data.data_layer import BatchBars, SymbolBars, _bars_digest
        from backend.tests.test_peer_strength import inputs

        bars, observed, registry, calendar = inputs()
        batch = BatchBars(
            as_of=observed,
            through=bars[-1].session_date,
            entries=tuple(
                SymbolBars(
                    symbol=symbol, adjustment="ALL", bars=bars, data_sha256=_bars_digest(bars)[0]
                )
                for symbol in ("NVDA", "XLK", "SPY")
            ),
        )

        async def daily(_symbols: tuple[str, ...] = ()) -> BatchBars:
            return batch

        monkeypatch.setattr(jobs.source, "daily", daily)
        facts = await jobs.source.get("NVDA", observed + timedelta(seconds=5))
        assert facts.relative_spy_return == facts.relative_sector_return == 0
        assert facts.as_of == observed + timedelta(seconds=5)
        assert batch.as_of == observed  # stored fetch time is never rewritten
        await runtime.close_resources()
    context.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["", "doctor", "auto"])
async def test_OPS_02_start_cli_refuses_unverified_and_handles_signal_with_host_lock(
    context: module.SecurityContext, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import signal
    from shutil import copytree

    from backend.ops.doctor import Check, DoctorResult
    from backend.ops.process import ProcessBusyError, ProcessLock
    from vws import runtime_cli

    copytree(Path(__file__).resolve().parents[2] / "config", module.PROJECT / "config")
    calls: list[str] = []
    settings = (
        context.settings
        if fault != "auto"
        else Settings(_env_file=None, broker_account_type="CASH", execution_mode="AUTO_PAPER")
    )
    monkeypatch.setattr(runtime_cli, "KeyringSecretStore", MemorySecrets)
    monkeypatch.setattr(runtime_cli, "load_host_settings", lambda _project, _path, _store: settings)
    monkeypatch.setattr(module, "open_context", lambda _path, **_kwargs: context)
    monkeypatch.setattr(runtime_cli, "configure_logging", lambda **_kwargs: None)

    async def doctor(_context: object, _store: object) -> DoctorResult:
        calls.append("doctor")
        return DoctorResult(
            checks=(
                Check(
                    name="synthetic",
                    required=True,
                    status="UNVERIFIED" if fault == "doctor" else "PASS",
                    message="Synthetic startup gate",
                    fix="Fixture",
                ),
            )
        )

    class Runtime:
        async def run(self, stop: asyncio.Event) -> None:
            calls.append("run")
            with pytest.raises(ProcessBusyError):
                ProcessLock(module.PROJECT / "data/runtime.lock").__enter__()
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)
            await asyncio.sleep(0)
            assert stop.is_set()

    async def compose(*_args: object, **_kwargs: object) -> Runtime:
        calls.append("compose")
        return Runtime()

    monkeypatch.setattr(module, "doctor_result", doctor)
    monkeypatch.setattr(runtime_cli, "compose", compose)
    previous = signal.getsignal(signal.SIGTERM)
    if fault:
        with pytest.raises(ConfigurationError):
            await runtime_cli.execute(None)
        assert calls == (["doctor"] if fault == "doctor" else [])
    else:
        await runtime_cli.execute(None)
        assert calls == ["doctor", "compose", "run"]
    assert signal.getsignal(signal.SIGTERM) == previous
    with ProcessLock(module.PROJECT / "data/runtime.lock"):
        pass


def test_PG_05_progress_never_constructs_settings_or_keyring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refuse(*args: object, **kwargs: object) -> Any:
        raise AssertionError("Progress must not inspect configuration or native secrets")

    monkeypatch.setattr(module, "open_context", refuse)
    monkeypatch.setattr(secret_module, "KeyringSecretStore", refuse)
    monkeypatch.setattr(cli, "read_progress", lambda: "Owner progress\n")
    assert cli.main(["--env-file", "missing-private.env", "progress"]) == 0
    assert capsys.readouterr().out == "Owner progress\n"


def test_SEC_12_context_checks_database_permissions_before_connecting(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    def permissions(**kwargs: object) -> tuple[PermissionFinding, ...]:
        order.append("permissions")
        assert kwargs.get("db_path") is not None
        raise ConfigurationError("world-writable database is always refused")

    def connect(url: str) -> Engine:
        order.append("database")
        return context.engine

    monkeypatch.setenv("DB_URL", str(context.engine.url))
    monkeypatch.setattr(module, "check_permissions", permissions)
    monkeypatch.setattr(module, "create_database", connect)
    with pytest.raises(ConfigurationError):
        module.open_context()
    assert order == ["permissions"]


def test_SEC_context_uses_only_explicit_dotenv_and_defaults_manual_paper(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DB_URL", str(context.engine.url))
    monkeypatch.setattr(module, "check_permissions", lambda **kwargs: ())
    monkeypatch.setattr(module, "SystemClock", lambda: context.ledger.clock)
    # This unrelated fake dotenv must never be discovered implicitly.
    (tmp_path / ".env").write_text(
        "EXECUTION_MODE=AUTO_LIVE\nBROKER_ACCOUNT_TYPE=MARGIN\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    opened = module.open_context()
    try:
        assert opened.env_file is None
        assert opened.settings.execution_mode == "MANUAL"
        assert opened.settings.paper_trading is True
        assert opened.settings.broker_account_type == "CASH"
    finally:
        opened.engine.dispose()


def test_SEC_01_cli_attest_is_durable_and_does_not_claim_remote_verification(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(module, "open_context", lambda *_args, **_kwargs: context)
    assert cli.main(["ops", "attest", "1", "--operator", "Owner"]) == 0
    output = capsys.readouterr().out
    assert "ATTESTED: ALPACA_MFA" in output
    assert "verified remotely" not in output.casefold()
    assert events(context.engine, "ACCOUNT_ATTESTED") == [
        {"item": "ALPACA_MFA", "operator": "Owner"}
    ]


@pytest.mark.parametrize("item", ["unknown", "0", "11"])
def test_SEC_01_cli_invalid_attestation_is_rejected_without_evidence(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    item: str,
) -> None:
    monkeypatch.setattr(module, "open_context", lambda *_args, **_kwargs: context)
    assert cli.main(["ops", "attest", item, "--operator", "Owner"]) == 1
    assert events(context.engine, "ACCOUNT_ATTESTED") == []


def test_SEC_73_cli_panic_still_persists_halt_with_a_corrupted_ledger(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context.ledger.append(SecurityEvent, kind="SYNTHETIC_FIXTURE", detail={"text": "original"})
    with context.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_security_events_update")
        connection.exec_driver_sql("UPDATE security_events SET kind='TAMPERED_FIXTURE'")
    monkeypatch.setenv("DB_URL", str(context.engine.url))
    monkeypatch.setattr(module, "check_permissions", lambda **kwargs: ())
    monkeypatch.setattr(module, "SystemClock", lambda: context.ledger.clock)
    assert (
        cli.main(["ops", "panic", "--operator", "Owner", "--reason", "suspected compromise"]) == 0
    )
    with transaction(context.engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == SystemState.HALTED.value
    output = capsys.readouterr().out
    assert "Local state: HALTED" in output
    assert "Regenerate" in output and "/revoke" in output
    with pytest.raises(LedgerIntegrityError):
        context.ledger.verify_chain()


def test_SEC_73_native_keyring_constructor_failure_does_not_prevent_local_halt(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable() -> MemorySecrets:
        raise ConfigurationError("Synthetic unavailable native store")

    monkeypatch.setattr(secret_module, "KeyringSecretStore", unavailable)
    monkeypatch.setenv("DB_URL", str(context.engine.url))
    monkeypatch.setenv("EXECUTION_MODE", "AUTO_LIVE")
    monkeypatch.setenv("AUTO_MAX_DAILY_ORDERS", "malformed")
    monkeypatch.setattr(module, "check_permissions", lambda **kwargs: ())
    monkeypatch.setattr(module, "SystemClock", lambda: context.ledger.clock)
    assert cli.main(["ops", "panic", "--operator", "Owner"]) == 0
    assert context.state.current() == SystemState.HALTED
    assert "UNVERIFIED emergency step: cancel unfilled entries" in capsys.readouterr().out
    context.ledger.verify_chain()


def test_SEC_73_missing_explicit_database_with_keyring_failure_cannot_guess_a_ledger(
    context: module.SecurityContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vws.host_config import LocalLedgerLocator, load_downgrade_settings

    monkeypatch.delenv("DB_URL", raising=False)
    with pytest.raises(ConfigurationError, match="explicit local DB_URL"):
        load_downgrade_settings(module.PROJECT, None, LocalLedgerLocator())
    assert context.state.current() == SystemState.RUNNING


def make_pre_news_schema(engine: Engine) -> None:
    """SEC-73: synthetic prior schema, without changing an owner's database."""
    with engine.begin() as connection:
        from backend.core.database import (
            AutoJobRun,
            CashFlow,
            DailyPnL,
            ExecutionFillRecord,
            ExecutionOrderRecord,
            JobRun,
            SchemaVersion,
            TaxEvent,
            TicketEvent,
        )

        for model in (
            ExecutionFillRecord,
            ExecutionOrderRecord,
            AutoJobRun,
            CashFlow,
            DailyPnL,
            TaxEvent,
        ):
            model.metadata.tables[model.__tablename__].drop(connection)

        JobRun.metadata.tables[JobRun.__tablename__].drop(connection)
        TicketEvent.metadata.tables[TicketEvent.__tablename__].drop(connection)
        SchemaVersion.metadata.tables[SchemaVersion.__tablename__].drop(connection)
        NewsHeadlineRecord.metadata.tables[NewsHeadlineRecord.__tablename__].drop(connection)
        connection.execute(update(SchemaMeta).where(SchemaMeta.id == 1).values(version=2))


@pytest.mark.parametrize("version", [2, 4, 5, 6])
def test_SEC_73_old_schema_panic_halts_without_silent_migration(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    version: int,
) -> None:
    if version == 2:
        make_pre_news_schema(context.engine)
    else:
        from backend.core.database import (
            AutoJobRun,
            CashFlow,
            DailyPnL,
            ExecutionFillRecord,
            ExecutionOrderRecord,
            SchemaVersion,
            TaxEvent,
        )

        with context.engine.begin() as connection:
            for model in (ExecutionFillRecord, ExecutionOrderRecord, AutoJobRun):
                model.metadata.tables[model.__tablename__].drop(connection)
            if version < 6:
                for accounting_model in (CashFlow, DailyPnL, TaxEvent):
                    accounting_model.metadata.tables[accounting_model.__tablename__].drop(
                        connection
                    )
            if version == 4:
                SchemaVersion.metadata.tables[SchemaVersion.__tablename__].drop(connection)
            connection.execute(update(SchemaMeta).where(SchemaMeta.id == 1).values(version=version))
    with pytest.raises(DatabaseError, match="version"):
        create_schema(context.engine)
    monkeypatch.setenv("DB_URL", str(context.engine.url))
    monkeypatch.setattr(module, "check_permissions", lambda **kwargs: ())
    monkeypatch.setattr(module, "SystemClock", lambda: context.ledger.clock)
    assert cli.main(["ops", "panic", "--operator", "Owner", "--reason", "local emergency"]) == 0
    with transaction(context.engine) as session:
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == SystemState.HALTED.value
        assert session.scalar(select(SchemaMeta.version)) == version
    assert ("news_headlines" in inspect(context.engine).get_table_names()) == (version >= 4)
    assert events(context.engine, "PANIC")
    assert "Local state: HALTED" in capsys.readouterr().out
    with pytest.raises(ConfigurationError, match="verified ledger"):
        module.open_context()


@pytest.mark.parametrize("damage", ["table", "column", "version"])
def test_SEC_73_old_schema_panic_refuses_incompatible_controls(engine: Engine, damage: str) -> None:
    make_pre_news_schema(engine)
    with engine.begin() as connection:
        if damage == "table":
            connection.exec_driver_sql("CREATE TABLE unexpected_fixture (id INTEGER)")
        elif damage == "column":
            connection.exec_driver_sql(
                "ALTER TABLE system_control ADD COLUMN unexpected_fixture INTEGER"
            )
        else:
            connection.execute(update(SchemaMeta).where(SchemaMeta.id == 1).values(version=1))
    with pytest.raises(DatabaseError):
        prepare_panic_schema(engine)


@pytest.mark.parametrize(
    "group_bad,webhook", [(False, ""), (True, ""), (False, "https://example.com/hijacked")]
)
def test_SEC_34_SEC_50_doctor_reads_keyring_token_and_never_false_passes_warnings(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    group_bad: bool,
    webhook: str,
) -> None:
    store = MemorySecrets()
    token = "123456:" + "T" * 36
    store.set("TELEGRAM_BOT_TOKEN", SecretStr(token))
    monkeypatch.setattr(module, "check_permissions", lambda **kwargs: ())

    def handler(request: httpx.Request) -> httpx.Response:
        assert token in str(request.url)
        if request.url.path.endswith("/getMe"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "is_bot": True,
                        "can_join_groups": group_bad,
                        "can_read_all_group_messages": False,
                    },
                },
            )
        assert request.url.path.endswith("/getWebhookInfo")
        return httpx.Response(200, json={"ok": True, "result": {"url": webhook}})

    requests = install_http(context, monkeypatch, handler)
    result = module.doctor(context, store)
    assert len(requests) == 2
    assert token not in "\n".join(result)
    if group_bad or webhook:
        assert any("WARN" in line or "Urgent" in line or "URGENT" in line for line in result)
        assert not any(line.startswith("PASS: Telegram") for line in result)
    else:
        assert any(line.startswith("PASS: Telegram") for line in result)


@pytest.mark.parametrize(
    "response",
    [{"ok": False}, {"ok": True, "result": []}, {"ok": True, "result": {"can_join_groups": False}}],
)
def test_SEC_34_doctor_malformed_telegram_evidence_is_never_pass(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, object],
) -> None:
    store = MemorySecrets()
    store.set("TELEGRAM_BOT_TOKEN", SecretStr("123456:" + "M" * 36))
    monkeypatch.setattr(module, "check_permissions", lambda **kwargs: ())
    install_http(context, monkeypatch, lambda _request: httpx.Response(200, json=response))
    with pytest.raises(SafetyError):
        module.doctor(context, store)


@pytest.mark.parametrize("name", ["BROKER_API_KEY", "ALPACA_PAPER_KEY_ID"])
def test_SEC_13_paper_rotation_validates_read_only_then_records_only_hmac(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    store = MemorySecrets()
    secret_name = "BROKER_SECRET_KEY" if name.startswith("BROKER") else "ALPACA_PAPER_SECRET"
    store.set(name, SecretStr("PK-old-isolated"))
    store.set(secret_name, SecretStr("matching-paper-secret"))
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "PK-new-isolated")

    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            request.method == "GET"
            and str(request.url) == "https://paper-api.alpaca.markets/v2/account"
        )
        assert request.headers["APCA-API-KEY-ID"] == "PK-new-isolated"
        assert request.headers["APCA-API-SECRET-KEY"] == "matching-paper-secret"
        assert store.get(name) == SecretStr("PK-old-isolated")
        return httpx.Response(200, json=active_account())

    requests = install_http(context, monkeypatch, handler)
    output = module.rotate_secret(context, name, store)
    assert len(requests) == 1
    assert store.get(name) == SecretStr("PK-new-isolated")
    records = events(context.engine, "SECRET_ROTATED")
    assert len(records) == 1 and records[0]["name"] == name and len(records[0]["fingerprint"]) == 64
    assert "PK-new-isolated" not in json.dumps(records) + output
    assert "matching-paper-secret" not in json.dumps(records) + output


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "ACTIVE"},
        {**active_account(), "trading_blocked": True},
        {**active_account(), "account_blocked": None},
    ],
)
def test_SEC_13_bad_account_validation_preserves_existing_key(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, object],
) -> None:
    store = MemorySecrets()
    store.set("BROKER_API_KEY", SecretStr("PK-old-isolated"))
    store.set("BROKER_SECRET_KEY", SecretStr("matching-paper-secret"))
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "PK-new-isolated")
    install_http(context, monkeypatch, lambda _request: httpx.Response(200, json=response))
    with pytest.raises(ConfigurationError):
        module.rotate_secret(context, "BROKER_API_KEY", store)
    assert store.get("BROKER_API_KEY") == SecretStr("PK-old-isolated")
    assert events(context.engine, "SECRET_ROTATED") == []


@pytest.mark.parametrize("name", ["ALPACA_LIVE_KEY_ID", "ALPACA_LIVE_SECRET"])
def test_AX_15_live_rotation_cannot_read_live_endpoint_in_paper_context(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    store = MemorySecrets()
    store.set("ALPACA_LIVE_KEY_ID", SecretStr("AK-prior-isolated"))
    store.set("ALPACA_LIVE_SECRET", SecretStr("prior-live-secret"))
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "AK-new-isolated")
    requests = install_http(
        context, monkeypatch, lambda _request: httpx.Response(200, json=active_account())
    )
    with pytest.raises(ConfigurationError):
        module.rotate_secret(context, name, store)
    assert requests == []
    assert store.get("ALPACA_LIVE_KEY_ID") == SecretStr("AK-prior-isolated")
    assert store.get("ALPACA_LIVE_SECRET") == SecretStr("prior-live-secret")
    assert events(context.engine, "SECRET_ROTATED") == []


def test_SEC_13_plaid_rotation_is_item_get_only_and_keeps_old_value_until_response(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = replace(
        context,
        settings=Settings(
            _env_file=None,
            broker_account_type="CASH",
            plaid_client_id=SecretStr("isolated-client-id"),
        ),
    )
    store = MemorySecrets()
    store.set("PLAID_SECRET", SecretStr("isolated-plaid-secret"))
    store.set("PLAID_ACCESS_TOKEN", SecretStr("access-sandbox-old-isolated"))
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "access-sandbox-new-isolated")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and str(request.url) == "https://sandbox.plaid.com/item/get"
        assert json.loads(request.content) == {
            "client_id": "isolated-client-id",
            "secret": "isolated-plaid-secret",
            "access_token": "access-sandbox-new-isolated",
        }
        assert store.get("PLAID_ACCESS_TOKEN") == SecretStr("access-sandbox-old-isolated")
        return httpx.Response(200, json={"item": {"item_id": "synthetic-item"}})

    requests = install_http(context, monkeypatch, handler)
    module.rotate_secret(context, "PLAID_ACCESS_TOKEN", store)
    assert len(requests) == 1
    assert store.get("PLAID_ACCESS_TOKEN") == SecretStr("access-sandbox-new-isolated")
    assert "access-sandbox-" not in json.dumps(events(context.engine, "SECRET_ROTATED"))


def test_SEC_14_cli_failure_stderr_never_renders_untrusted_secret_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: object, **kwargs: object) -> module.SecurityContext:
        raise RuntimeError("access-sandbox-private-unregistered-token")

    monkeypatch.setattr(module, "open_context", fail)
    assert cli.main(["doctor"]) == 1
    rendered = capsys.readouterr()
    assert "access-sandbox-private-unregistered-token" not in rendered.out + rendered.err
    assert "no secret details printed" in rendered.err


def test_SEC_43_host_apply_and_ack_dispatch_bind_exact_effective_files(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "config"
    directory.mkdir()
    config_file = directory / "config.yaml"
    config_file.write_text("policy: original\n", encoding="utf-8")
    (directory / "instruments.csv").write_text("symbol\nSPY\n", encoding="utf-8")
    monkeypatch.setattr(module, "open_context", lambda *_args, **_kwargs: context)
    before = context.config_hash()
    assert cli.main(["ops", "apply-config", "--operator", "Owner"]) == 0
    assert not context.drift.check(before, mode="AUTO_PAPER").changed
    config_file.write_text("policy: changed\n", encoding="utf-8")
    after = context.config_hash()
    assert before != after
    assert context.drift.check(after, mode="AUTO_PAPER").entries_paused
    assert cli.main(["ops", "ack-config", "--operator", "Owner"]) == 0
    assert not context.drift.entries_paused()
    assert events(context.engine, "CONFIG_APPLIED") == [
        {"config_hash": before, "operator": "Owner"}
    ]
    assert events(context.engine, "CONFIG_ACKNOWLEDGED") == [
        {"config_hash": after, "operator": "Owner"}
    ]


def test_SEC_40_host_backup_and_restore_test_use_the_same_fake_keyring_only(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = MemorySecrets()
    monkeypatch.setattr(secret_module, "KeyringSecretStore", lambda: store)
    monkeypatch.setattr(module, "open_context", lambda *_args, **_kwargs: context)
    context.ledger.append(SecurityEvent, kind="BACKUP_SYNTHETIC_FIXTURE", detail={"text": "source"})
    assert cli.main(["ops", "backup"]) == 0
    saved = tuple((tmp_path / "data/backups").iterdir())
    assert len(saved) == 1 and saved[0].suffix == ".vwsbak"
    assert b"SQLite format 3" not in saved[0].read_bytes()
    assert cli.main(["ops", "restore-test", "--file", str(saved[0])]) == 0
    output = capsys.readouterr().out
    assert "PASS: encrypted restore" in output
    key = store.get("VWS_BACKUP_KEY")
    assert key is not None and key.get_secret_value() not in output
    assert len(events(context.engine, "RESTORE_TEST_PASSED")) == 1


def test_SEC_15_host_backup_key_export_is_explicit_and_once_only(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = MemorySecrets()
    monkeypatch.setattr(secret_module, "KeyringSecretStore", lambda: store)
    monkeypatch.setattr(module, "open_context", lambda *_args, **_kwargs: context)
    assert cli.main(["ops", "show-backup-key"]) == 0
    key = store.get("VWS_BACKUP_KEY")
    assert key is not None
    first = capsys.readouterr().out
    assert "Losing it prevents restores" in first
    assert key.get_secret_value() in first
    assert cli.main(["ops", "show-backup-key"]) == 1
    second = capsys.readouterr()
    assert key.get_secret_value() not in second.out + second.err


def test_SEC_42_host_anchor_dispatch_verifies_and_refuses_mixed_options(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(module, "open_context", lambda *_args, **_kwargs: context)
    context.ledger.append(SecurityEvent, kind="ANCHOR_SYNTHETIC_FIXTURE", detail={"text": "source"})
    anchor = context.anchors.create()
    args = ["ledger", "verify-anchor", "--seq", str(anchor.seq), "--hash", anchor.digest]
    assert cli.main(args) == 0
    assert len(events(context.engine, "ANCHOR_VERIFIED")) == 1
    assert cli.main(["ledger", "verify-anchor", "--seq", str(anchor.seq), "--hash", "f" * 64]) == 1
    assert len(events(context.engine, "ANCHOR_VERIFIED")) == 1
    assert cli.main(args + ["--file", str(tmp_path / "never-read.anchor")]) == 1
    assert cli.main(["ledger", "verify-anchor", "--seq", str(anchor.seq)]) == 1
    assert len(events(context.engine, "ANCHOR_VERIFIED")) == 1


@pytest.mark.parametrize("status,payload", [(401, {}), (200, []), (200, None)])
def test_SEC_13_rejected_or_nonobject_rotation_response_preserves_the_secret(
    context: module.SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    payload: object,
) -> None:
    store = MemorySecrets()
    store.set("BROKER_API_KEY", SecretStr("PK-old-isolated"))
    store.set("BROKER_SECRET_KEY", SecretStr("matching-paper-secret"))
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "PK-new-isolated")
    install_http(context, monkeypatch, lambda _request: httpx.Response(status, json=payload))
    with pytest.raises(ConfigurationError):
        module.rotate_secret(context, "BROKER_API_KEY", store)
    assert store.get("BROKER_API_KEY") == SecretStr("PK-old-isolated")
    assert events(context.engine, "SECRET_ROTATED") == []
