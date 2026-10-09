"""OPS-01: each required fault gives a red line and a concrete fix."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from alpaca.trading.enums import AccountStatus
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from backend.core.config import Settings, load_yaml_config
from backend.core.errors import DataIntegrityError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.ops.doctor import Doctor
from backend.ops.host import HostFinding
from backend.ops.read_checks import PaperAccountCheck
from backend.tests.test_broker_clock import MovingClock, Reads

PROJECT = Path(__file__).resolve().parents[2]


class Store:
    def __init__(self, missing: str = "") -> None:
        names = (
            "ALPACA_PAPER_KEY_ID",
            "ALPACA_PAPER_SECRET",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CALLBACK_SECRET",
        )
        self.values = {
            name: SecretStr("TEST_ONLY_" + name + "_NOT_A_CREDENTIAL")
            for name in names
            if name != missing
        }

    def get(self, name: str) -> SecretStr | None:
        return self.values.get(name)

    def set(self, name: str, value: SecretStr) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class ProbeReads:
    def __init__(self, clock: MovingClock, calendar: MarketCalendar, fault: str = "") -> None:
        self.time = Reads(calendar, clock, "future" if fault == "clock" else "")
        self.fault = fault

    async def paper_account(self, key: SecretStr, secret: SecretStr) -> PaperAccountCheck:
        if self.fault == "broker_unavailable":
            raise OSError("injected read unavailable")
        return PaperAccountCheck(
            account_id=UUID(int=1),
            status=AccountStatus.ACTIVE,
            buying_power=Decimal(10000),
            equity=Decimal(10000),
            currency="USD",
            trading_blocked=self.fault == "broker_blocked",
            account_blocked=False,
            trade_suspended_by_user=False,
        )

    async def account(
        self, settings: Settings, key: SecretStr, secret: SecretStr
    ) -> PaperAccountCheck:
        raise AssertionError("This doctor fixture is paper only")

    async def telegram(
        self,
        token: SecretStr,
        method: Literal["getMe", "getWebhookInfo", "getUpdates", "getChat"],
        *,
        chat_id: int | None = None,
    ) -> object:
        if self.fault == "telegram_unavailable":
            raise OSError("injected read unavailable")
        if method == "getMe":
            return {
                "is_bot": True,
                "can_join_groups": self.fault == "groups",
                "can_read_all_group_messages": False,
            }
        if method == "getWebhookInfo":
            return {"url": "https://example.invalid" if self.fault == "webhook" else ""}
        if method == "getChat":
            return {
                "id": 123 if self.fault != "chat_id" else 456,
                "type": "group" if self.fault == "private" else "private",
            }
        raise AssertionError("Doctor must not consume setup updates")

    async def broker_clock(self, settings: Settings, key: SecretStr, secret: SecretStr) -> object:
        return await self.time.time()

    async def broker_calendar(
        self, settings: Settings, key: SecretStr, secret: SecretStr, start: date, end: date
    ) -> object:
        return await self.time.sessions(start, end)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 1, 1), end=date(2027, 1, 1))


def make(engine: Engine, calendar: MarketCalendar, project: Path, fault: str = "") -> Doctor:
    from datetime import UTC, datetime

    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    settings = Settings(
        _env_file=None,
        broker_account_type="CASH",
        telegram_chat_id=123,
        telegram_allowed_user_ids=(123,),
        sec_user_agent=None if fault == "sec" else "Project V Test operator@example.invalid",
        execution_mode="AUTO_PAPER" if fault == "mode" else "MANUAL",
    )
    config = load_yaml_config(
        PROJECT / "config/config.yaml",
        allowed_symbols=set(InstrumentRegistry.from_csv(PROJECT / "config").symbols),
        settings=settings,
    )
    source = ProbeReads(clock, calendar, fault)
    host = (
        HostFinding(
            name="firewall",
            status="UNKNOWN" if fault == "host_unknown" else "PASS",
            reason="Mocked host check.",
            fix="Review the actual firewall.",
        ),
    )
    return Doctor(
        settings,
        config,
        state,
        calendar,
        clock,
        Store(
            "ALPACA_PAPER_KEY_ID"
            if fault == "key"
            else "TELEGRAM_CALLBACK_SECRET"
            if fault == "callback"
            else ""
        ),
        source,
        project=project,
        host_findings=host,
        disk_free=lambda _: 0 if fault == "disk" else 1_000_000_000,
        python_version=(3, 10) if fault == "python" else (3, 12),
    )


@pytest.mark.asyncio
async def test_OPS_01_all_required_mocked_checks_and_unverified_feed_are_distinct(
    engine: Engine, calendar: MarketCalendar, tmp_path: Path
) -> None:
    service = make(engine, calendar, tmp_path)
    result = await service.run()
    assert result.exit_code == 0
    assert all(row.status == "PASS" for row in result.checks if row.required)
    assert not result.fully_green
    assert next(row for row in result.checks if row.name == "fred").status == "UNVERIFIED"
    assert (
        next(row for row in result.checks if row.name == "last_dependency_audit").status
        == "UNVERIFIED"
    )
    assert all("Fix:" in line for line in result.lines())
    assert not any("TEST_ONLY_" in line for line in result.lines())
    service.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,name",
    [
        ("python", "python"),
        ("mode", "mode_endpoint"),
        ("disk", "disk_space"),
        ("key", "paper_account"),
        ("broker_blocked", "paper_account"),
        ("broker_unavailable", "paper_account"),
        ("clock", "clock_skew"),
        ("groups", "telegram_private"),
        ("webhook", "telegram_private"),
        ("private", "telegram_private"),
        ("chat_id", "telegram_private"),
        ("callback", "telegram_private"),
        ("telegram_unavailable", "telegram_private"),
        ("sec", "sec_identification"),
    ],
)
async def test_OPS_01_required_failure_is_red_and_nonzero(
    engine: Engine, calendar: MarketCalendar, tmp_path: Path, fault: str, name: str
) -> None:
    service = make(engine, calendar, tmp_path, fault)
    result = await service.run()
    assert result.exit_code == 1 and not result.fully_green
    check = next(row for row in result.checks if row.name == name)
    assert check.status == "RED" and check.fix and check.required
    if fault == "clock":
        assert service.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_SEC_71_unknown_host_is_never_pass(
    engine: Engine, calendar: MarketCalendar, tmp_path: Path
) -> None:
    result = await make(engine, calendar, tmp_path, "host_unknown").run()
    assert next(row for row in result.checks if row.name == "host_firewall").status == "UNVERIFIED"
    assert not result.fully_green


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["ledger", "database_writable", "calendar", "configuration"])
async def test_OPS_01_local_failures_are_red(
    engine: Engine,
    calendar: MarketCalendar,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    service = make(engine, calendar, tmp_path)

    def unavailable(*args: object, **kwargs: object) -> None:
        raise DataIntegrityError("injected local check unavailable")

    if name == "ledger":
        monkeypatch.setattr(service.state.ledger, "verify_chain", unavailable)
    elif name == "database_writable":
        monkeypatch.setattr(service.state.ledger, "append_in_session", unavailable)
    elif name == "calendar":
        monkeypatch.setattr(service.calendar, "is_session", unavailable)
    else:
        monkeypatch.setattr(type(service.config), "assert_settings_consistent", unavailable)
    result = await service.run()
    assert result.exit_code == 1
    assert next(row for row in result.checks if row.name == name).status == "RED"


@pytest.mark.asyncio
async def test_DAT_12_native_manual_csv_never_uses_an_alpaca_account_instead(
    engine: Engine, calendar: MarketCalendar, tmp_path: Path
) -> None:
    service = make(engine, calendar, tmp_path)
    service.settings = Settings.validated_copy(
        service.settings.model_copy(update={"broker_state_source": "MANUAL_CSV"})
    )
    result = await service.run()
    check = next(row for row in result.checks if row.name == "mode_endpoint")
    assert result.exit_code == 1 and check.status == "RED"
    assert "MANUAL_CSV is disabled by owner decision (Oct 8 2026)" in check.fix
    assert "BROKER_STATE_SOURCE=ALPACA" in check.fix
