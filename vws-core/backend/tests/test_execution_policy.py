"""AX-02/14/15/22/42: planted controls, durable downgrades and exact boundaries."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import transaction
from backend.core.errors import ConfigurationError, ExecutionDisabledError
from backend.core.execution_policy import ALLOWED_EXECUTOR_NAMES, EXECUTOR_RELATIVE_PATH
from backend.core.source_guard import scan_file, scan_project
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.execution.modes import ModeStore, assert_auto_binding
from backend.execution.policy import entry_window, require_live_limits
from backend.ops.security import ConfigDriftGuard
from backend.tests.test_security_cli import MemorySecrets
from backend.tests.test_system_state import RecordingNotifier


def auto_settings(**values: Any) -> Settings:
    return Settings(
        _env_file=None, broker_account_type="CASH", execution_mode="AUTO_PAPER", **values
    )


def test_SEC_43_drift_blocks_both_entry_gates_until_host_ack(
    engine: Engine, clock: FrozenClock
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    modes = ModeStore(auto_settings(), state, "paper-owner")
    drift = ConfigDriftGuard(state.ledger, clock)
    drift.apply("a" * 64, "Owner")
    assert modes.entries_enabled
    assert drift.check("b" * 64, mode="AUTO_PAPER").entries_paused
    assert not modes.entries_enabled and modes.effective == "AUTO_PAPER"
    with transaction(engine) as session:
        assert modes.in_session(session) == ("AUTO_PAPER", True)
    modes.resume(operator="Owner", phrase="RESUME")
    assert not modes.entries_enabled, "RESUME cannot bypass host configuration acknowledgement"
    restarted = ModeStore(auto_settings(), state, "paper-owner")
    assert not restarted.entries_enabled
    drift.ack("b" * 64, "Owner")
    assert restarted.entries_enabled
    with transaction(engine) as session:
        assert restarted.in_session(session) == ("AUTO_PAPER", False)
    state.ledger.verify_chain()


@pytest.mark.parametrize("name", sorted(ALLOWED_EXECUTOR_NAMES))
def test_AX_14_exact_executor_whitelist_retains_outside_positive_controls(
    tmp_path: Path, name: str
) -> None:
    isolated = tmp_path / EXECUTOR_RELATIVE_PATH
    isolated.parent.mkdir(parents=True)
    isolated.write_text(f"client.{name}\n", encoding="utf-8")
    assert not scan_project(tmp_path)
    assert scan_file(isolated), "An untrusted standalone path must not grant an exemption"
    outside = tmp_path / "backend" / "outside.py"
    outside.write_text(f"client.{name}\n", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert findings and all(row.path == outside for row in findings)


@pytest.mark.parametrize(
    "source",
    [
        "client." + "MarketOrder" + "Request()",
        "client." + "close_" + "position()",
        "client." + "create_" + "transfer()",
        "client." + "ReplaceOrder" + "Request()",
        "client." + "cancel_" + "orders()",
        "getattr(client, name)()",
    ],
)
def test_AX_13_14_executor_still_rejects_banned_members(tmp_path: Path, source: str) -> None:
    path = tmp_path / EXECUTOR_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert scan_project(tmp_path)


@pytest.mark.parametrize("action", ["MANUAL", "PAUSE", "HALT", "DISABLE_LIVE"])
def test_AX_02_downgrade_survives_restart_and_never_upgrades(
    engine: Engine,
    clock: FrozenClock,
    action: Any,
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    modes = ModeStore(auto_settings(), state, "paper-owner")
    assert modes.effective == "AUTO_PAPER" and modes.entries_enabled
    modes.downgrade(action, actor="telegram:123")
    restarted = ModeStore(
        auto_settings(), SystemStateStore(engine, clock, RecordingNotifier()), "paper-owner"
    )
    assert not restarted.entries_enabled
    assert restarted.effective == ("AUTO_PAPER" if action == "PAUSE" else "MANUAL")
    with pytest.raises(ConfigurationError):
        restarted.resume(operator="Owner", phrase="resume")
    if action != "HALT":
        restarted.resume(operator="Owner", phrase="RESUME")
        assert restarted.entries_enabled
    else:
        assert state.current() == SystemState.HALTED
        with pytest.raises(ExecutionDisabledError, match="reset"):
            restarted.resume(operator="Owner", phrase="RESUME")
    manual = ModeStore(Settings(_env_file=None, broker_account_type="CASH"), state, "paper-owner")
    assert manual.effective == "MANUAL"
    with pytest.raises(ExecutionDisabledError):
        manual.resume(operator="Owner", phrase="RESUME")


@pytest.mark.parametrize("bad_name", ["ALPACA_LIVE_KEY_ID", "ALPACA_LIVE_SECRET"])
def test_AX_15_even_one_opposite_key_refuses_paper(bad_name: str) -> None:
    store = MemorySecrets()
    key, secret = SecretStr("TEST_ONLY_PAPER_ID"), SecretStr("TEST_ONLY_PAPER_SECRET")
    store.set("ALPACA_PAPER_KEY_ID", key)
    store.set("ALPACA_PAPER_SECRET", secret)
    settings = auto_settings(broker_api_key=key, broker_secret_key=secret)
    assert_auto_binding(settings, store)
    store.set(bad_name, SecretStr("TEST_ONLY_OPPOSITE"))
    with pytest.raises(ConfigurationError, match="opposite"):
        assert_auto_binding(settings, store)


@pytest.mark.parametrize("case", ["endpoint", "source", "missing", "wrong_pair"])
def test_AX_15_other_binding_faults_refuse(case: str) -> None:
    store = MemorySecrets()
    values: dict[str, Any] = {}
    if case == "endpoint":
        values.update(
            paper_trading=False,
            live_trading_enabled=True,
            live_trading_confirm="I_ACCEPT_REAL_MONEY_RISK",
            broker_api_key=SecretStr("TEST_ONLY"),
            broker_secret_key=SecretStr("TEST_ONLY_SECRET"),
        )
    if case == "source":
        values["broker_state_source"] = "MANUAL_CSV"
    if case == "wrong_pair":
        store.set("ALPACA_PAPER_KEY_ID", SecretStr("TEST_ONLY_OTHER"))
        store.set("ALPACA_PAPER_SECRET", SecretStr("TEST_ONLY_OTHER_SECRET"))
    with pytest.raises(ConfigurationError):
        assert_auto_binding(auto_settings(**values), store)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


@pytest.mark.parametrize("day", [date(2026, 3, 6), date(2026, 3, 9), date(2026, 11, 27)])
def test_AX_22_open_close_DST_and_early_close_exact_boundaries(
    calendar: MarketCalendar, day: date
) -> None:
    settings = auto_settings()
    opening, closing = calendar.session_open(day), calendar.session_close(day)
    cutoff = closing - timedelta(minutes=60 if day.month == 11 else 15)
    assert not entry_window(
        settings, calendar, opening + timedelta(minutes=15) - timedelta(microseconds=1)
    )
    assert entry_window(settings, calendar, opening + timedelta(minutes=15))
    assert entry_window(settings, calendar, cutoff - timedelta(microseconds=1))
    assert not entry_window(settings, calendar, cutoff)
    assert not entry_window(settings, calendar, closing)


@pytest.mark.parametrize(
    "now", [datetime(2026, 7, 3, 16, tzinfo=UTC), datetime(2026, 9, 27, 16, tzinfo=UTC)]
)
def test_AX_22_non_sessions_refuse(calendar: MarketCalendar, now: datetime) -> None:
    assert not entry_window(auto_settings(), calendar, now)


def test_AX_21_42_no_silent_live_limits_or_relaxed_CRO() -> None:
    with pytest.raises(ConfigurationError, match="six"):
        require_live_limits(auto_settings())
    with pytest.raises(ValidationError, match="AUTO_MIN_SCORE"):
        auto_settings(auto_min_score=Decimal("6.99"))
    for name, value in (
        ("live_max_daily_orders", 6),
        ("live_max_open_positions", 31),
        ("live_max_gross_exposure_pct", Decimal("1.000001")),
        ("live_max_risk_per_trade", Decimal("0.010001")),
        ("live_daily_loss_limit", Decimal("0.020001")),
        ("live_max_order_notional", 1.0),
    ):
        with pytest.raises(ValidationError):
            auto_settings(**{name: value})
