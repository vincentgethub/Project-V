"""LIVE-BAN: AUTO_LIVE is hard-banned; this build is paper-only.

Re-allowing live trading later requires a code change plus Vincent's explicit
approval. The live guard and enable-live code stay in the tree, inert.
"""

from pathlib import Path
from typing import get_args

import pytest
from pydantic import SecretStr, ValidationError

import backend.core.config as config_module
from backend.core.config import AUTO_LIVE_BANNED, Settings, load_settings
from backend.core.errors import ConfigurationError
from vws.__main__ import main

PROJECT = Path(__file__).resolve().parents[2]

LIVE_VALUES = {
    "broker_account_type": "CASH",
    "paper_trading": False,
    "live_trading_enabled": True,
    "live_trading_confirm": "I_ACCEPT_REAL_MONEY_RISK",
    "broker_api_key": SecretStr("TEST_ONLY_LIVE_ID"),
    "broker_secret_key": SecretStr("TEST_ONLY_LIVE_SECRET"),
}


def test_LIVE_BAN_message_names_the_ban_and_the_approval_requirement() -> None:
    assert "AUTO_LIVE is banned" in AUTO_LIVE_BANNED
    assert "paper-only" in AUTO_LIVE_BANNED
    assert "explicit approval" in AUTO_LIVE_BANNED


@pytest.mark.parametrize("spelling", ["AUTO_LIVE", "auto_live", " AUTO_LIVE "])
def test_LIVE_BAN_settings_with_auto_live_fail_with_a_clear_error(spelling: str) -> None:
    with pytest.raises(ValidationError, match="AUTO_LIVE is banned"):
        Settings(_env_file=None, execution_mode=spelling)


def test_LIVE_BAN_fully_unlocked_live_values_still_fail() -> None:
    with pytest.raises(ValidationError, match="AUTO_LIVE is banned"):
        Settings(_env_file=None, execution_mode="AUTO_LIVE", **LIVE_VALUES)


def test_LIVE_BAN_environment_auto_live_fails_config_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXECUTION_MODE", "AUTO_LIVE")
    with pytest.raises(ConfigurationError) as caught:
        load_settings()
    assert "AUTO_LIVE is banned" in str(caught.value.__cause__)


def test_LIVE_BAN_dotenv_auto_live_fails_config_load(tmp_path: Path) -> None:
    env = tmp_path / "live.env"
    env.write_text("EXECUTION_MODE=AUTO_LIVE\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_settings(env)
    assert "AUTO_LIVE is banned" in str(caught.value.__cause__)


def test_LIVE_BAN_manual_default_unchanged() -> None:
    assert Settings(_env_file=None).execution_mode == "MANUAL"


@pytest.mark.parametrize("value", ["", "LIVE", "AUTO", "AUTO-LIVE", 7, None])
def test_LIVE_BAN_unknown_modes_still_fail_closed_to_manual(value: object) -> None:
    assert Settings(_env_file=None, execution_mode=value).execution_mode == "MANUAL"


def test_LIVE_BAN_auto_paper_unaffected() -> None:
    settings = Settings(_env_file=None, execution_mode="AUTO_PAPER")
    assert settings.execution_mode == "AUTO_PAPER"
    assert settings.paper_trading is True


def test_LIVE_BAN_enable_live_exits_nonzero_before_any_context(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import vws.security_cli as security_cli

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("enable-live opened a host context")

    monkeypatch.setattr(security_cli, "open_context", forbidden)
    assert main(["ops", "enable-live", "--operator", "night1"]) == 1
    assert "AUTO_LIVE is banned" in capsys.readouterr().err


def test_LIVE_BAN_live_guard_and_enable_live_code_remain_present_and_inert() -> None:
    assert (PROJECT / "backend/execution/live_guard.py").is_file()
    assert "enable-live" in (PROJECT / "vws/__main__.py").read_text(encoding="utf-8")
    # The Literal keeps AUTO_LIVE so inert live code still type-checks; the
    # mode="before" validator above is what rejects it at every load.
    assert "AUTO_LIVE" in get_args(config_module.Settings.model_fields["execution_mode"].annotation)
