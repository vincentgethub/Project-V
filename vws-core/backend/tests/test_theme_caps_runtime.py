"""Item 17: paper THEME_CAPS reach the deployed runtime.

The deployed process is `vws start` under deploy/vws.service: systemd sets the
unit's Environment= lines, the item 9 loader selects systemd credentials from
$CREDENTIALS_DIRECTORY, and load_host_settings reads the host's own .env for
non-secret settings. These tests load settings exactly that way, from a host
.env that does NOT carry THEME_CAPS, so the caps must come from the unit.
Every value is synthetic (TEST_ONLY); nothing opens a broker or keyring.
"""

import shlex
from decimal import Decimal
from pathlib import Path

import pytest

from backend.core.config import Settings, load_settings
from backend.security.secret_loader import SystemdCredentialStore, select_secret_store
from backend.tests.test_secret_loader import credentials, unavailable_keyring
from vws.host_config import load_host_settings

PROJECT = Path(__file__).resolve().parents[2]
SEED_THEMES = {"AI_SEMIS", "CLOUD", "CONSUMER_TECH"}
PAPER_CAP = Decimal("0.25")


def unit_environment() -> dict[str, str]:
    """Environment= assignments of deploy/vws.service, systemd-quoted."""
    values: dict[str, str] = {}
    for line in (PROJECT / "deploy/vws.service").read_text(encoding="utf-8").splitlines():
        if line.startswith("Environment="):
            for assignment in shlex.split(line.removeprefix("Environment=")):
                name, _, value = assignment.partition("=")
                values[name] = value
    return values


def deployed_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host_env: str) -> Settings:
    for name, value in unit_environment().items():
        monkeypatch.setenv(name, value)
    environ = {"CREDENTIALS_DIRECTORY": str(credentials(tmp_path))}
    store = select_secret_store(environ, keyring=unavailable_keyring)
    assert isinstance(store, SystemdCredentialStore)
    selected = tmp_path / ".env"
    selected.write_text(host_env, encoding="utf-8")
    return load_host_settings(tmp_path, selected, store)


@pytest.fixture(autouse=True)
def clean_theme_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("THEME_CAPS", "EXECUTION_MODE", "PAPER_TRADING"):
        monkeypatch.delenv(name, raising=False)


def test_THEME_RT_deployed_settings_carry_every_seed_theme_at_the_paper_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = deployed_settings(tmp_path, monkeypatch, "BROKER_ACCOUNT_TYPE=CASH\n")
    assert settings.paper_trading and settings.execution_mode == "MANUAL"
    assert {name: settings.theme_caps.get(name) for name in SEED_THEMES} == {
        name: PAPER_CAP for name in SEED_THEMES
    }


def test_THEME_RT_unit_caps_are_paper_only_non_secret_and_match_the_template() -> None:
    environment = unit_environment()
    assert set(environment) == {"PYTHONDONTWRITEBYTECODE", "THEME_CAPS"}
    unit_caps = load_settings(broker_account_type="CASH", theme_caps=environment["THEME_CAPS"])
    template = {
        line.partition("=")[0]: line.partition("=")[2]
        for line in (PROJECT / ".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    }
    example_caps = load_settings(broker_account_type="CASH", theme_caps=template["THEME_CAPS"])
    assert dict(unit_caps.theme_caps) == dict(example_caps.theme_caps)
    assert set(unit_caps.theme_caps) == SEED_THEMES
    assert all(value == PAPER_CAP for value in unit_caps.theme_caps.values())
