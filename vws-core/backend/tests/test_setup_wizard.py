"""WZ acceptance: disposable files, fake providers/keyring, socket blocking."""

import os
import shutil
from collections import defaultdict, deque
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from alpaca.trading.enums import AccountStatus
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import load_settings, load_yaml_config
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.domain.instruments import InstrumentRegistry
from backend.ops.apply_config import apply_setup
from backend.ops.doctor import Check, DoctorResult
from backend.ops.read_checks import PaperAccountCheck
from backend.tests.test_security_cli import MemorySecrets
from vws.setup import SetupWizard, read_environment

PROJECT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("save", [True, False])
async def test_WZ_01_cli_composition_delays_db_until_confirmation_and_audits_only_names(
    project: Path, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, save: bool
) -> None:
    from backend.core.database import create_database
    from vws import security_cli, setup_cli

    store, reads = MemorySecrets(), Reads()
    answers = {"SEC filing contact": ["Test Owner owner@example.invalid"]}
    if not save:
        answers["Save these settings"] = ["no"]
    script = Script(answers)
    monkeypatch.setattr(security_cli, "PROJECT", project)
    monkeypatch.setattr(setup_cli, "KeyringSecretStore", lambda: store)
    monkeypatch.setattr(setup_cli, "SystemClock", lambda: clock)
    monkeypatch.setattr(security_cli, "SystemClock", lambda: clock)
    monkeypatch.setattr(setup_cli, "ReadChecksClient", lambda _policy, _clock: reads)
    monkeypatch.setattr(setup_cli, "TerminalPrompts", lambda: script)
    monkeypatch.setattr(security_cli, "check_permissions", lambda **_kwargs: ())

    async def doctor(_context: object, _store: object) -> DoctorResult:
        return DoctorResult(
            checks=(
                Check(
                    name="fred",
                    status="UNVERIFIED",
                    required=False,
                    message="Synthetic feed is unverified",
                    fix="Fixture",
                ),
            )
        )

    monkeypatch.setattr(security_cli, "doctor_result", doctor)
    result = await setup_cli.execute(None)
    assert result.applied == save
    if not save:
        assert not (project / "data").exists() and not (project / ".env").exists()
        assert not store.values
        return
    assert result.doctor is not None and not result.doctor.fully_green
    for value in store.values.values():
        assert value.get_secret_value() not in (project / ".env").read_text()
    engine = create_database("sqlite:///" + str(project / "data/vws-core.sqlite3"))
    try:
        ledger = Ledger(engine, clock)
        ledger.verify_chain()
        with transaction(engine) as session:
            rows = tuple(session.scalars(select(SecurityEvent)).all())
        applied = next(row for row in rows if row.kind == "CONFIG_APPLIED")
        assert set(applied.detail) == {"changed_keys", "config_hash"}
        assert "FRED_API_KEY" in applied.detail["changed_keys"]
        for value in store.values.values():
            assert value.get_secret_value() not in str([row.detail for row in rows])
    finally:
        engine.dispose()


class Script:
    def __init__(self, answers: dict[str, list[str]] | None = None) -> None:
        self.answers = {name: deque(values) for name, values in (answers or {}).items()}
        self.output: list[str] = []
        self.questions: list[str] = []
        self.hidden_questions: list[str] = []
        self.interrupt = ""

    def ask(self, question: str, default: str = "") -> str:
        self.questions.append(question)
        if self.interrupt and self.interrupt in question:
            raise KeyboardInterrupt
        for fragment, values in self.answers.items():
            if fragment in question and values:
                return values.popleft() or default
        if "Is this your account" in question or "Save these settings" in question:
            return "yes"
        return default

    def hidden(self, question: str, saved: bool) -> str:
        self.hidden_questions.append(question)
        if self.interrupt and self.interrupt in question:
            raise KeyboardInterrupt
        for fragment, values in self.answers.items():
            if fragment in question and values:
                return values.popleft()
        return "" if saved else "TEST_ONLY_NOT_A_CREDENTIAL_" + str(len(self.hidden_questions))

    def show(self, message: str) -> None:
        self.output.append(message)


def update(kind: str = "private", identity: int = 123, text: str = "/start") -> dict[str, object]:
    return {
        "message": {
            "text": text,
            "chat": {"id": identity, "type": kind},
            "from": {"id": identity, "first_name": "Test Owner", "is_bot": False},
        }
    }


class Reads:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.updates: deque[object] = deque([[update()]])
        self.faults: dict[str, deque[Exception]] = defaultdict(deque)

    def check(self, name: str) -> None:
        self.calls.append(name)
        if self.faults[name]:
            raise self.faults[name].popleft()

    async def telegram(
        self,
        token: SecretStr,
        method: Literal["getMe", "getWebhookInfo", "getUpdates", "getChat"],
        *,
        chat_id: int | None = None,
    ) -> object:
        self.check(method)
        if method == "getMe":
            return {"is_bot": True, "can_join_groups": False, "can_read_all_group_messages": False}
        if method == "getUpdates":
            return self.updates.popleft() if len(self.updates) > 1 else self.updates[0]
        raise AssertionError("Unexpected wizard Telegram route")

    async def paper_account(self, key: SecretStr, secret: SecretStr) -> PaperAccountCheck:
        self.check("account")
        return PaperAccountCheck(
            account_id=UUID(int=7),
            status=AccountStatus.ACTIVE,
            buying_power=Decimal(10000),
            equity=Decimal(10000),
            currency="USD",
            trading_blocked=False,
            account_blocked=False,
            trade_suspended_by_user=False,
        )

    async def asset(self, symbol: str, key: SecretStr, secret: SecretStr) -> None:
        self.check("asset:" + symbol)

    async def fred(self, key: SecretStr) -> None:
        self.check("fred")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    for source in (PROJECT / "config").iterdir():
        if source.is_file():
            shutil.copyfile(source, tmp_path / "config" / source.name)
    return tmp_path


def wizard(
    project: Path,
    engine: Engine,
    clock: FrozenClock,
    *,
    script: Script | None = None,
    reads: Reads | None = None,
    store: MemorySecrets | None = None,
    section: Literal["telegram", "alpaca", "watchlist", "risk"] | None = None,
) -> SetupWizard:
    ledger = Ledger(engine, clock)

    def record(names: tuple[str, ...], fingerprints: dict[str, str]) -> None:
        with transaction(engine) as session:
            for name, fingerprint in fingerprints.items():
                ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="SECRET_ROTATED",
                    detail={"name": name, "fingerprint": fingerprint},
                    telegram_user_id=None,
                    ts=clock.now(),
                )
            ledger.append_in_session(
                session,
                SecurityEvent,
                kind="CONFIG_APPLIED",
                detail={"changed_keys": list(names)},
                telegram_user_id=None,
                ts=clock.now(),
            )

    async def doctor() -> DoctorResult:
        return DoctorResult(
            checks=(
                Check(
                    name="fred",
                    status="UNVERIFIED",
                    required=False,
                    message="Feed health is unverified.",
                    fix="Run required realtime feed checks.",
                ),
            )
        )

    return SetupWizard(
        project,
        store or MemorySecrets(),
        reads or Reads(),
        script or Script(),
        clock,
        record=record,
        doctor=doctor,
        section=section,
    )


@pytest.mark.asyncio
async def test_WZ_01_03_full_setup_has_valid_files_only_keyring_credentials_and_order(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    store = MemorySecrets()
    script = Script({"SEC filing contact": ["Test Owner owner@example.invalid"]})
    reads = Reads()
    service = wizard(project, engine, clock, store=store, script=script, reads=reads)
    original_yaml = (project / "config/config.yaml").read_bytes()
    result = await service.run()
    assert result.applied and result.doctor is not None and not result.doctor.fully_green
    settings = load_settings(env_file=project / ".env")
    assert settings.execution_mode == "MANUAL" and settings.paper_trading
    assert not settings.live_trading_enabled and not settings.llm_enabled
    assert settings.telegram_allowed_user_ids == (123,) and settings.telegram_chat_id == 123
    assert settings.tax_filing_status == "single" and settings.tax_state == "Texas"
    assert settings.tax_state_rate == settings.tax_niit_rate == Decimal(0)
    assert settings.tax_fed_st_rate is None and settings.tax_fed_lt_rate is None
    config = load_yaml_config(
        project / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(project / "config").symbols,
        settings=settings,
    )
    assert config.watchlist == service.config.watchlist
    assert (project / "config/config.yaml").read_bytes() == original_yaml
    assert {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CALLBACK_SECRET",
        "ALPACA_PAPER_KEY_ID",
        "ALPACA_PAPER_SECRET",
        "FRED_API_KEY",
    } <= store.values.keys()
    assert reads.calls[:3] == ["getMe", "getUpdates", "account"]
    assert "fred" == reads.calls[-1]
    with transaction(engine) as session:
        events = tuple(session.scalars(select(SecurityEvent)).all())
    applied = next(event for event in events if event.kind == "CONFIG_APPLIED")
    assert set(applied.detail) == {"changed_keys"}
    for value in store.values.values():
        raw = value.get_secret_value()
        assert raw not in "\n".join(script.output)
        assert all(
            raw.encode() not in file.read_bytes() for file in project.rglob("*") if file.is_file()
        )
        assert raw not in str([event.detail for event in events])
    assert "FRED_API_KEY" not in read_environment(project / ".env")[1]
    Ledger(engine, clock).verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["AUTO_PAPER", "AUTO_LIVE"])
async def test_WZ_04_existing_auto_value_and_related_flags_preserved(
    project: Path, engine: Engine, clock: FrozenClock, mode: str
) -> None:
    flags = (
        'EXECUTION_MODE="'
        + mode
        + '"\nPAPER_TRADING=false\nLIVE_TRADING_ENABLED=true\nLIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY_RISK\n'
    )
    (project / ".env").write_text(flags, encoding="utf-8")
    script = Script()
    service = wizard(project, engine, clock, script=script)
    await service.run()
    assert (project / ".env").read_text(encoding="utf-8").startswith(flags)
    assert any("resume-auto" in line and mode in line for line in script.output)
    assert all(
        "LIVE key" not in line and "LIVE secret" not in line for line in script.hidden_questions
    )


@pytest.mark.asyncio
async def test_WZ_05_bad_token_ticker_budget_reasked_without_bad_save(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    reads = Reads()
    reads.faults["getMe"].append(ConfigurationError("injected invalid token"))
    script = Script(
        {
            "Watchlist tickers": ["UNKNOWN", "AAPL"],
            "Daily AI summary budget": ["999", "1"],
            "Maximum risk per trade": ["nan", "0.01"],
        }
    )
    service = wizard(project, engine, clock, script=script, reads=reads)
    await service.run()
    assert reads.calls.count("getMe") == 2
    assert reads.calls.count("asset:AAPL") == 1
    settings = load_settings(env_file=project / ".env")
    assert settings.llm_daily_budget_usd == Decimal(1)
    assert settings.max_risk_per_trade == Decimal("0.01")
    assert "UNKNOWN" not in (project / "config/config.yaml").read_text(encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "point",
    [
        "Telegram bot token",
        "Press Enter",
        "Alpaca PAPER secret",
        "Watchlist tickers",
        "Daily AI summary budget",
        "SEC filing contact",
        "FRED API key",
        "Use Central Time",
        "Save these settings",
    ],
)
async def test_WZ_06_interrupt_during_collection_changes_nothing(
    project: Path, engine: Engine, clock: FrozenClock, point: str
) -> None:
    (project / ".env").write_text("BROKER_ACCOUNT_TYPE=CASH\n", encoding="utf-8")
    before = {
        str(path.relative_to(project)): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    script, store = Script(), MemorySecrets()
    script.interrupt = point
    service = wizard(project, engine, clock, script=script, store=store)
    with pytest.raises(KeyboardInterrupt):
        await service.run()
    assert {
        str(path.relative_to(project)): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before
    assert not store.values


@pytest.mark.asyncio
async def test_WZ_07_watchlist_section_changes_only_watchlist_and_backs_up_yaml(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    (project / ".env").write_text(
        "BROKER_ACCOUNT_TYPE=CASH\nEXECUTION_MODE=AUTO_PAPER\n", encoding="utf-8"
    )
    original_env = (project / ".env").read_bytes()
    original_yaml = (project / "config/config.yaml").read_bytes()
    store = MemorySecrets()
    for name in ("ALPACA_PAPER_KEY_ID", "ALPACA_PAPER_SECRET"):
        store.set(name, SecretStr("TEST_ONLY_" + name))
    prior_secrets = dict(store.values)
    script, reads = Script({"Watchlist tickers": ["AAPL,MSFT"]}), Reads()
    result = await wizard(
        project, engine, clock, section="watchlist", store=store, script=script, reads=reads
    ).run()
    assert result.changed_names == ("WATCHLIST",)
    assert len(result.backups) == 1 and result.backups[0].read_bytes() == original_yaml
    assert (project / ".env").read_bytes() == original_env
    assert store.values == prior_secrets
    assert not script.hidden_questions
    changed = (project / "config/config.yaml").read_bytes()
    assert changed.split(b"schedule:", 1)[1] == original_yaml.split(b"schedule:", 1)[1]
    assert reads.calls == ["asset:AAPL", "asset:MSFT"]


@pytest.mark.asyncio
async def test_WZ_05_network_skip_removes_unverified_credential_and_does_not_claim_pass(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    store, reads = MemorySecrets(), Reads()
    store.set("TELEGRAM_BOT_TOKEN", SecretStr("TEST_ONLY_OLD_TOKEN"))
    (project / ".env").write_text(
        "BROKER_ACCOUNT_TYPE=CASH\nTELEGRAM_CHAT_ID=123\nTELEGRAM_ALLOWED_USER_IDS=[123]\n",
        encoding="utf-8",
    )
    reads.faults["getMe"].append(ProviderError("injected network failure"))
    script = Script({"Retry this check": ["skip"]})
    result = await wizard(
        project, engine, clock, section="telegram", store=store, reads=reads, script=script
    ).run()
    assert result.applied and result.waiting
    assert store.get("TELEGRAM_BOT_TOKEN") is None
    values = read_environment(project / ".env")[1]
    assert "TELEGRAM_CHAT_ID" not in values and "TELEGRAM_ALLOWED_USER_IDS" not in values
    assert any("UNVERIFIED" in line for line in script.output)


@pytest.mark.asyncio
async def test_WZ_05_watchlist_skip_does_not_write_unverified_list(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    store, reads = MemorySecrets(), Reads()
    for name in ("ALPACA_PAPER_KEY_ID", "ALPACA_PAPER_SECRET"):
        store.set(name, SecretStr("TEST_ONLY_" + name))
    old = (project / "config/config.yaml").read_bytes()
    reads.faults["asset:AAPL"].append(ProviderError("injected network failure"))
    script = Script({"Watchlist tickers": ["AAPL"], "Retry this check": ["skip"]})
    result = await wizard(
        project, engine, clock, section="watchlist", store=store, reads=reads, script=script
    ).run()
    assert result.applied and result.waiting
    assert (project / "config/config.yaml").read_bytes() == old


@pytest.mark.asyncio
async def test_WZ_07_group_ignored_private_confirmation_required(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    reads, script = Reads(), Script({"Is this your account": ["no", "yes"]})
    reads.updates = deque(
        [[update("group", -123), update("private", 456)], [update("group", -123), update()]]
    )
    result = await wizard(
        project, engine, clock, section="telegram", reads=reads, script=script
    ).run()
    assert result.applied
    values = read_environment(project / ".env")[1]
    assert values["TELEGRAM_CHAT_ID"] == "123" and values["TELEGRAM_ALLOWED_USER_IDS"] == "[123]"
    assert reads.calls == ["getMe", "getUpdates", "getUpdates"]
    assert script.questions.count("Is this your account? (yes/no)") == 2


@pytest.mark.asyncio
async def test_WZ_07_ambiguous_private_accounts_are_not_selected(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    reads, script = Reads(), Script({"Retry or skip private chat": ["skip"]})
    reads.updates = deque([[update(), update("private", 456)]])
    result = await wizard(
        project, engine, clock, section="telegram", reads=reads, script=script
    ).run()
    assert result.applied and any("confirm" in item for item in result.waiting)
    assert "TELEGRAM_CHAT_ID" not in read_environment(project / ".env")[1]


@pytest.mark.asyncio
async def test_WZ_final_no_and_concurrent_edit_are_safe(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    before = (project / "config/config.yaml").read_bytes()
    store = MemorySecrets()
    script = Script({"Save these settings": ["no"]})
    result = await wizard(project, engine, clock, script=script, store=store).run()
    assert not result.applied and not (project / ".env").exists() and not store.values
    assert (project / "config/config.yaml").read_bytes() == before


@pytest.mark.parametrize(
    "text",
    [
        "EXECUTION_MODE=MANUAL\nEXECUTION_MODE=AUTO_PAPER\n",
        "FRED_API_KEY=TEST_ONLY_NOT_A_CREDENTIAL\n",
        "TELEGRAM_BOT_TOKEN=TEST_ONLY_NOT_A_CREDENTIAL\n",
        "BROKEN LINE\n",
    ],
)
def test_WZ_03_plaintext_duplicate_and_unpreservable_format_refused(
    project: Path, text: str
) -> None:
    path = project / ".env"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        read_environment(path)


@pytest.mark.parametrize("failure", ["second_rename", "keyring", "audit", "interrupt"])
def test_WZ_06_apply_rollback_restores_files_keyring_and_inventory(
    project: Path, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    env, yaml = project / ".env", project / "config/config.yaml"
    env.write_bytes(b"EXECUTION_MODE=MANUAL\n")
    prior = {
        str(path.relative_to(project)): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    store = MemorySecrets()
    store.set("TELEGRAM_BOT_TOKEN", SecretStr("TEST_ONLY_OLD_TOKEN"))
    initial = dict(store.values)
    original_replace, original_set = os.replace, store.set
    renamed = 0

    def replace(source: str | Path, destination: str | Path) -> None:
        nonlocal renamed
        if Path(destination) in (env, yaml):
            renamed += 1
            if renamed == 2 and failure in {"second_rename", "interrupt"}:
                if failure == "interrupt":
                    original_replace(source, destination)
                    raise KeyboardInterrupt
                raise OSError("injected rename failure")
        original_replace(source, destination)

    def save(name: str, value: SecretStr) -> None:
        if failure == "keyring" and value.get_secret_value() == "TEST_ONLY_NEW_TOKEN":
            raise OSError("injected keyring failure")
        original_set(name, value)

    def record(names: tuple[str, ...]) -> None:
        if failure == "audit":
            raise DataIntegrityError("injected audit failure")

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(store, "set", save)
    with pytest.raises((OSError, DataIntegrityError, KeyboardInterrupt)):
        apply_setup(
            project,
            {".env": b"BROKER_ACCOUNT_TYPE=CASH\n", "config/config.yaml": b"watchlist: [AAPL]\n"},
            {"TELEGRAM_BOT_TOKEN": SecretStr("TEST_ONLY_NEW_TOKEN")},
            store,
            clock,
            ("TELEGRAM_BOT_TOKEN",),
            record,
        )
    assert store.values == initial
    assert {
        str(path.relative_to(project)): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == prior


def test_WZ_06_restoration_failure_is_never_claimed_success(
    project: Path, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = project / ".env"
    env.write_bytes(b"EXECUTION_MODE=MANUAL\n")
    original = os.replace

    def replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == env:
            raise OSError("injected apply and rollback failure")
        original(source, destination)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(DataIntegrityError, match="UNVERIFIED"):
        apply_setup(
            project,
            {".env": b"BROKER_ACCOUNT_TYPE=CASH\n"},
            {},
            MemorySecrets(),
            clock,
            (),
            lambda _: None,
        )


@pytest.mark.asyncio
async def test_WZ_06_interrupt_in_post_save_doctor_restores_configuration_and_entries(
    project: Path, engine: Engine, clock: FrozenClock
) -> None:
    (project / ".env").write_bytes(b"BROKER_ACCOUNT_TYPE=CASH\r\n")
    # Runtime ledger evidence is append-only even on cancellation. WZ file
    # rollback covers the setup configuration, never erases audit rows.
    before = {
        str(path.relative_to(project)): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and path.name != "ledger.db"
    }
    store = MemorySecrets()
    service = wizard(project, engine, clock, store=store)
    cancelled: list[tuple[str, ...]] = []

    def record_cancel(names: tuple[str, ...]) -> None:
        cancelled.append(names)
        Ledger(engine, clock).append(
            SecurityEvent, kind="CONFIG_APPLY_ROLLED_BACK", detail={"changed_keys": list(names)}
        )

    service.rolled_back = record_cancel

    async def interrupted() -> DoctorResult:
        raise KeyboardInterrupt

    service.doctor = interrupted
    with pytest.raises(KeyboardInterrupt):
        await service.run()
    assert cancelled and not store.values
    assert {
        str(path.relative_to(project)): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and path.name != "ledger.db"
    } == before
    with transaction(engine) as session:
        assert tuple(
            session.scalars(
                select(SecurityEvent.kind)
                .where(SecurityEvent.kind.in_(("CONFIG_APPLIED", "CONFIG_APPLY_ROLLED_BACK")))
                .order_by(SecurityEvent.seq)
            )
        ) == ("CONFIG_APPLIED", "CONFIG_APPLY_ROLLED_BACK")
    Ledger(engine, clock).verify_chain()


@pytest.mark.parametrize(
    "relative", ["../.env", "backend/core/config.py", "config/fees.yaml", ".env.other"]
)
def test_WZ_06_only_specified_paths_can_be_written(
    project: Path, clock: FrozenClock, relative: str
) -> None:
    with pytest.raises(ConfigurationError):
        apply_setup(project, {relative: b"bad"}, {}, MemorySecrets(), clock, (), lambda _: None)
