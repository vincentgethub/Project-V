"""WZ/SEC: separate paper/live pairs and no implicit dotenv discovery."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.core.errors import ConfigurationError
from backend.tests.test_security_cli import MemorySecrets
from vws.host_config import load_host_settings


class Store(MemorySecrets):
    def __init__(self) -> None:
        super().__init__()
        self.reads: list[str] = []

    def get(self, name: str) -> SecretStr | None:
        self.reads.append(name)
        return super().get(name)


@pytest.mark.parametrize("paper", [True, False])
def test_SEC_host_configuration_selects_only_matching_pair(tmp_path: Path, paper: bool) -> None:
    store = Store()
    for kind in ("PAPER", "LIVE"):
        for field in ("KEY_ID", "SECRET"):
            store.set("ALPACA_" + kind + "_" + field, SecretStr("TEST_ONLY_" + kind + "_" + field))
    env = tmp_path / "selected.env"
    env.write_text(
        "BROKER_ACCOUNT_TYPE=CASH\nPAPER_TRADING="
        + ("true" if paper else "false")
        + "\nLIVE_TRADING_ENABLED="
        + ("false" if paper else "true")
        + "\nLIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY_RISK\nDB_URL=sqlite:///data/ledger.db\n",
        encoding="utf-8",
    )
    settings = load_host_settings(tmp_path, env, store)
    kind, other = ("PAPER", "LIVE") if paper else ("LIVE", "PAPER")
    assert settings.broker_api_key == store.values["ALPACA_" + kind + "_KEY_ID"]
    assert settings.broker_secret_key == store.values["ALPACA_" + kind + "_SECRET"]
    assert not any("ALPACA_" + other + "_" in name for name in store.reads)
    assert (
        Path(settings.db_url.get_secret_value().removeprefix("sqlite:///"))
        == tmp_path / "data/ledger.db"
    )


def test_SEC_host_configuration_does_not_discover_unselected_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "EXECUTION_MODE=AUTO_LIVE\nPAPER_TRADING=false\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = load_host_settings(tmp_path, None, Store())
    assert result.execution_mode == "MANUAL" and result.paper_trading


def test_SEC_host_live_pair_missing_never_borrows_paper(tmp_path: Path) -> None:
    env = tmp_path / "selected.env"
    env.write_text(
        "BROKER_ACCOUNT_TYPE=CASH\nPAPER_TRADING=false\nLIVE_TRADING_ENABLED=true\nLIVE_TRADING_CONFIRM=I_ACCEPT_REAL_MONEY_RISK\n",
        encoding="utf-8",
    )
    store = Store()
    store.set("ALPACA_PAPER_KEY_ID", SecretStr("TEST_ONLY_PAPER"))
    store.set("ALPACA_PAPER_SECRET", SecretStr("TEST_ONLY_PAPER_SECRET"))
    with pytest.raises(ConfigurationError):
        load_host_settings(tmp_path, env, store)


def test_SEC_host_pair_rotation_during_read_fails_closed(tmp_path: Path) -> None:
    class RacingStore(Store):
        def get(self, name: str) -> SecretStr | None:
            if name == "ALPACA_PAPER_KEY_ID" and name in self.reads:
                return SecretStr("TEST_ONLY_CHANGED_PAIR")
            return super().get(name)

    store = RacingStore()
    store.set("ALPACA_PAPER_KEY_ID", SecretStr("TEST_ONLY_PAPER_KEY"))
    with pytest.raises(ConfigurationError, match="changed"):
        load_host_settings(tmp_path, None, store)


@pytest.mark.parametrize("name", ["FRED_API_KEY", "FERNET_KEY", "PLAID_ACCESS_TOKEN"])
def test_SEC_keyring_only_credentials_cannot_appear_even_empty_in_selected_file(
    tmp_path: Path, name: str
) -> None:
    env = tmp_path / "selected.env"
    env.write_text("BROKER_ACCOUNT_TYPE=CASH\n" + name + "=\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_host_settings(tmp_path, env, Store())


def test_SEC_enabled_llm_credential_loaded_before_settings_validation(tmp_path: Path) -> None:
    env = tmp_path / "selected.env"
    env.write_text(
        "BROKER_ACCOUNT_TYPE=CASH\nLLM_ENABLED=true\nLLM_BASE_URL=https://api.openai.com/v1\nLLM_MODEL_NAME=TEST_ONLY_MODEL\nLLM_PRICE_INPUT_PER_MTOK=1\nLLM_PRICE_OUTPUT_PER_MTOK=1\n",
        encoding="utf-8",
    )
    store = Store()
    store.set("LLM_API_KEY", SecretStr("TEST_ONLY_LLM_KEY"))
    settings = load_host_settings(tmp_path, env, store)
    assert settings.llm_enabled and settings.llm_api_key == store.values["LLM_API_KEY"]
    assert "TEST_ONLY_LLM_KEY" not in str(settings)
