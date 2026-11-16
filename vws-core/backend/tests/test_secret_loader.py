"""SEC-LOADER: one secret loader, strict order, refuse otherwise.

Order: systemd credentials ($CREDENTIALS_DIRECTORY), then a real Secret
Service (plaintext/file keyring backends refused by class), then an injected
in-memory source (VWS_SECRET_SOURCE=injected, off by default, paper only,
never written). Anything else is SECRETS_UNAVAILABLE. Tests never open the
owner's keyring; every value here is a synthetic TEST_ONLY string.
"""

import os
import re
from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.core.config import load_settings
from backend.core.errors import ConfigurationError
from backend.core.logging import redact
from backend.security.secret_loader import (
    INJECTED_PREFIX,
    SECRETS_UNAVAILABLE,
    SERVICE_CREDENTIALS,
    InjectedSecretStore,
    SecretsUnavailableError,
    SystemdCredentialStore,
    assert_trusted_keyring_backend,
    secret_source_line,
    select_secret_store,
)

PROJECT = Path(__file__).resolve().parents[2]
VALUE = "TEST_ONLY_PAPER_SECRET_VALUE_7f3a"


class FakeKeyring:
    source_name = "secret-service"

    def __init__(self) -> None:
        self.values: dict[str, SecretStr] = {}

    def probe(self) -> None:
        return None

    def get(self, name: str) -> SecretStr | None:
        return self.values.get(name)

    def set(self, name: str, value: SecretStr) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def available_keyring() -> FakeKeyring:
    return FakeKeyring()


def unavailable_keyring() -> FakeKeyring:
    raise ConfigurationError("trusted native keyring is unavailable; no fallback is permitted")


def credentials(tmp_path: Path, mode: int = 0o400, dir_mode: int = 0o500) -> Path:
    directory = tmp_path / "credentials"
    directory.mkdir()
    secret = directory / "vws.alpaca_paper_secret"
    secret.write_text(VALUE + "\n", encoding="utf-8")
    secret.chmod(mode)
    directory.chmod(dir_mode)
    return directory


def injected_env(**extra: str) -> dict[str, str]:
    return {
        "VWS_SECRET_SOURCE": "injected",
        INJECTED_PREFIX + "ALPACA_PAPER_SECRET": VALUE,
        **extra,
    }


# --- strict order ---------------------------------------------------------


def test_SEC_LOADER_systemd_credentials_win_over_every_other_source(tmp_path: Path) -> None:
    env = injected_env(CREDENTIALS_DIRECTORY=str(credentials(tmp_path)))
    store = select_secret_store(env, keyring=available_keyring)
    assert isinstance(store, SystemdCredentialStore)
    assert store.source_name == "systemd-creds"
    secret = store.get("ALPACA_PAPER_SECRET")
    assert secret is not None and secret.get_secret_value() == VALUE
    assert store.get("TELEGRAM_BOT_TOKEN") is None


def test_SEC_LOADER_secret_service_wins_over_injection_when_no_credentials() -> None:
    store = select_secret_store(injected_env(), keyring=available_keyring)
    assert isinstance(store, FakeKeyring)


def test_SEC_LOADER_injected_is_used_only_after_systemd_and_secret_service() -> None:
    env = injected_env()
    store = select_secret_store(env, keyring=unavailable_keyring)
    assert isinstance(store, InjectedSecretStore)
    assert store.source_name == "injected"
    secret = store.get("ALPACA_PAPER_SECRET")
    assert secret is not None and secret.get_secret_value() == VALUE


def test_SEC_LOADER_no_source_is_secrets_unavailable() -> None:
    with pytest.raises(SecretsUnavailableError) as caught:
        select_secret_store({}, keyring=unavailable_keyring)
    assert str(caught.value).startswith(SECRETS_UNAVAILABLE)
    assert isinstance(caught.value, ConfigurationError)


def test_SEC_LOADER_injection_is_off_by_default() -> None:
    env = {INJECTED_PREFIX + "ALPACA_PAPER_SECRET": VALUE}
    with pytest.raises(SecretsUnavailableError):
        select_secret_store(env, keyring=unavailable_keyring)


@pytest.mark.parametrize("value", ["INJECTED", "env", "dotenv", "file", "plaintext", " "])
def test_SEC_LOADER_unknown_source_selector_is_refused(value: str) -> None:
    with pytest.raises(SecretsUnavailableError):
        select_secret_store({"VWS_SECRET_SOURCE": value}, keyring=available_keyring)


def test_SEC_LOADER_invalid_systemd_directory_never_falls_through(tmp_path: Path) -> None:
    env = injected_env(CREDENTIALS_DIRECTORY=str(tmp_path / "missing"))
    with pytest.raises(SecretsUnavailableError):
        select_secret_store(env, keyring=available_keyring)


# --- systemd credentials --------------------------------------------------


@pytest.mark.parametrize("mode", [0o440, 0o404, 0o600, 0o644, 0o444])
def test_SEC_LOADER_credential_file_looser_than_0400_is_refused(tmp_path: Path, mode: int) -> None:
    store = SystemdCredentialStore(credentials(tmp_path, mode=mode))
    with pytest.raises(SecretsUnavailableError) as caught:
        store.get("ALPACA_PAPER_SECRET")
    assert VALUE not in str(caught.value)


@pytest.mark.parametrize("dir_mode", [0o750, 0o755, 0o705])
def test_SEC_LOADER_credentials_directory_open_to_others_is_refused(
    tmp_path: Path, dir_mode: int
) -> None:
    directory = credentials(tmp_path, dir_mode=dir_mode)
    with pytest.raises(SecretsUnavailableError):
        SystemdCredentialStore(directory)
    directory.chmod(0o700)


def test_SEC_LOADER_credential_symlinks_are_refused(tmp_path: Path) -> None:
    directory = credentials(tmp_path, dir_mode=0o700)
    target = directory / "vws.alpaca_paper_secret"
    (directory / "vws.telegram_bot_token").symlink_to(target)
    store = SystemdCredentialStore(directory)
    with pytest.raises(SecretsUnavailableError):
        store.get("TELEGRAM_BOT_TOKEN")
    linked = tmp_path / "linked"
    linked.symlink_to(directory)
    with pytest.raises(SecretsUnavailableError):
        SystemdCredentialStore(linked)


@pytest.mark.parametrize("content", ["", "\n", "two\nlines\n", "nul\x00byte"])
def test_SEC_LOADER_malformed_credential_is_refused_without_echoing_it(
    tmp_path: Path, content: str
) -> None:
    directory = credentials(tmp_path, dir_mode=0o700)
    path = directory / "vws.alpaca_paper_secret"
    path.chmod(0o600)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o400)
    with pytest.raises(SecretsUnavailableError) as caught:
        SystemdCredentialStore(directory).get("ALPACA_PAPER_SECRET")
    assert content.strip() == "" or content.strip() not in str(caught.value)


def test_SEC_LOADER_systemd_store_is_read_only(tmp_path: Path) -> None:
    store = SystemdCredentialStore(credentials(tmp_path))
    with pytest.raises(ConfigurationError, match="read-only"):
        store.set("ALPACA_PAPER_SECRET", SecretStr("TEST_ONLY_OTHER"))
    with pytest.raises(ConfigurationError, match="read-only"):
        store.delete("ALPACA_PAPER_SECRET")


# --- Secret Service backend class check -----------------------------------


@pytest.mark.parametrize(
    "module,name",
    [
        ("keyrings.alt.file", "PlaintextKeyring"),
        ("keyrings.alt.file", "EncryptedKeyring"),
        ("keyring.backends.chainer", "ChainerBackend"),
        ("keyring.backends.fail", "Keyring"),
        ("keyring.backends.null", "Keyring"),
        ("keyrings.alt.Gnome", "Keyring"),
        ("my_plugin", "PlaintextKeyring"),
        ("keyring.backends.SecretService", "PlaintextKeyring"),
    ],
)
def test_SEC_LOADER_plaintext_and_file_keyring_backends_are_refused_by_class(
    module: str, name: str
) -> None:
    backend = type(name, (), {"__module__": module})()
    with pytest.raises(SecretsUnavailableError):
        assert_trusted_keyring_backend(backend)


@pytest.mark.parametrize(
    "module,name",
    [
        ("keyring.backends.SecretService", "Keyring"),
        ("keyring.backends.Windows", "WinVaultKeyring"),
    ],
)
def test_SEC_LOADER_native_backends_pass_the_class_check(module: str, name: str) -> None:
    assert_trusted_keyring_backend(type(name, (), {"__module__": module})())


def test_SEC_LOADER_subclassing_a_native_backend_does_not_pass() -> None:
    native = type("Keyring", (), {"__module__": "keyring.backends.SecretService"})
    sneaky = type("Keyring", (native,), {"__module__": "keyrings.alt.file"})
    with pytest.raises(SecretsUnavailableError):
        assert_trusted_keyring_backend(sneaky())


# --- injected (paper only, memory only) -----------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"EXECUTION_MODE": "AUTO_LIVE"},
        {"EXECUTION_MODE": "auto_live"},
        {"PAPER_TRADING": "false"},
        {"PAPER_TRADING": "0"},
        {INJECTED_PREFIX + "ALPACA_LIVE_KEY_ID": "TEST_ONLY_LIVE"},
        {"LIVE_TRADING_ENABLED": "true"},
    ],
)
def test_SEC_LOADER_injected_source_is_paper_only(extra: dict[str, str]) -> None:
    with pytest.raises(SecretsUnavailableError):
        InjectedSecretStore.from_environment(injected_env(**extra))


def test_SEC_LOADER_injected_values_leave_the_environment_and_are_never_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    env = injected_env()
    store = InjectedSecretStore.from_environment(env)
    assert not any(name.startswith(INJECTED_PREFIX) for name in env)
    assert env["VWS_SECRET_SOURCE"] == "injected"
    with pytest.raises(ConfigurationError, match="never written"):
        store.set("ALPACA_PAPER_SECRET", SecretStr("TEST_ONLY_OTHER"))
    with pytest.raises(ConfigurationError, match="never written"):
        store.delete("ALPACA_PAPER_SECRET")
    assert list(tmp_path.iterdir()) == []


def test_SEC_LOADER_injected_source_needs_at_least_one_valid_value() -> None:
    with pytest.raises(SecretsUnavailableError):
        InjectedSecretStore.from_environment({"VWS_SECRET_SOURCE": "injected"})
    with pytest.raises(SecretsUnavailableError):
        InjectedSecretStore.from_environment(
            {"VWS_SECRET_SOURCE": "injected", INJECTED_PREFIX + "bad-name": VALUE}
        )


# --- redaction and doctor -------------------------------------------------


def test_SEC_LOADER_loaded_values_are_redacted_everywhere(tmp_path: Path) -> None:
    for store in (
        SystemdCredentialStore(credentials(tmp_path)),
        InjectedSecretStore.from_environment(injected_env()),
    ):
        secret = store.get("ALPACA_PAPER_SECRET")
        assert secret is not None
        assert VALUE not in repr(store) and VALUE not in str(store)
        assert VALUE not in repr(secret)
        assert redact(f"broker said {VALUE}") == "broker said [REDACTED]"
        assert VALUE not in secret_source_line(store)


@pytest.mark.parametrize(
    "factory,name",
    [
        (lambda tmp: SystemdCredentialStore(credentials(tmp)), "systemd-creds"),
        (lambda tmp: InjectedSecretStore.from_environment(injected_env()), "injected"),
        (lambda tmp: FakeKeyring(), "secret-service"),
    ],
)
def test_SEC_LOADER_doctor_line_shows_the_source_name_only(
    tmp_path: Path, factory: object, name: str
) -> None:
    assert callable(factory)
    assert secret_source_line(factory(tmp_path)) == f"Secret source: {name}"


def test_SEC_LOADER_doctor_and_start_print_the_source_line() -> None:
    main = (PROJECT / "vws/__main__.py").read_text(encoding="utf-8")
    runtime = (PROJECT / "vws/runtime_cli.py").read_text(encoding="utf-8")
    assert "select_secret_store()" in main and "select_secret_store()" in runtime
    assert "KeyringSecretStore()" not in main and "KeyringSecretStore()" not in runtime
    assert main.count("print(secret_source_line(store))") == 1
    assert runtime.count("print(secret_source_line(store))") == 1


# --- deployment files and dotenv ------------------------------------------


def test_SEC_LOADER_service_unit_uses_encrypted_credentials_not_a_dotenv() -> None:
    unit = (PROJECT / "deploy/vws.service").read_text(encoding="utf-8")
    assert "EnvironmentFile" not in unit
    loaded = re.findall(r"(?m)^LoadCredentialEncrypted=([^:\s]+):?\S*$", unit)
    assert loaded == ["vws." + name.lower() for name in SERVICE_CREDENTIALS]
    assert "ALPACA_PAPER_KEY_ID" in SERVICE_CREDENTIALS
    assert "ALPACA_PAPER_SECRET" in SERVICE_CREDENTIALS
    assert not any(name.startswith("ALPACA_LIVE_") for name in SERVICE_CREDENTIALS)


def test_SEC_LOADER_compose_has_no_env_file() -> None:
    compose = (PROJECT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "env_file" not in compose
    assert ".env" not in compose


@pytest.mark.parametrize(
    "line",
    [
        "BROKER_API_KEY=TEST_ONLY_ID",
        "BROKER_SECRET_KEY=TEST_ONLY_SECRET",
        "TELEGRAM_BOT_TOKEN=123:TEST_ONLY",
        "LLM_API_KEY=TEST_ONLY",
        "DB_URL=postgresql://vws:TEST_ONLY@localhost/vws",
    ],
)
def test_SEC_LOADER_dotenv_cannot_be_a_secret_source(tmp_path: Path, line: str) -> None:
    env = tmp_path / ".env"
    env.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_settings(env_file=env)
    assert SECRETS_UNAVAILABLE in str(caught.value)
    assert "TEST_ONLY" not in str(caught.value)


def test_SEC_LOADER_dotenv_keeps_non_secret_settings(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "MAX_SINGLE_STOCK_WEIGHT=0.09\nDB_URL=sqlite:///vws.sqlite3\nBROKER_API_KEY=\n",
        encoding="utf-8",
    )
    settings = load_settings(env_file=env)
    assert str(settings.max_single_stock_weight) == "0.09"


def test_SEC_LOADER_systemd_credentials_need_a_posix_host(tmp_path: Path) -> None:
    directory = credentials(tmp_path)
    if os.name == "posix":
        assert SystemdCredentialStore(directory).source_name == "systemd-creds"
    else:
        with pytest.raises(SecretsUnavailableError):
            SystemdCredentialStore(directory)


# --- the real KeyringSecretStore probe ------------------------------------


def native_store(
    monkeypatch: pytest.MonkeyPatch, module: str, name: str, priority: object
) -> object:
    import contextlib

    import backend.security.secrets as secrets_module

    def read_priority(cls: type) -> object:
        if isinstance(priority, Exception):
            raise priority
        return priority

    backend = type(name, (), {"__module__": module, "priority": property(read_priority)})()
    monkeypatch.setattr(secrets_module, "_native_backend", lambda: backend)
    monkeypatch.setattr(secrets_module, "native_keyring_call", contextlib.nullcontext)
    return secrets_module.KeyringSecretStore()


def test_SEC_LOADER_keyring_probe_accepts_only_a_live_native_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.security.secrets import KeyringSecretStore

    store = native_store(monkeypatch, "keyring.backends.SecretService", "Keyring", 5)
    assert isinstance(store, KeyringSecretStore)
    store.probe()
    assert select_secret_store({}, keyring=lambda: store) is store
    assert secret_source_line(store) in {
        "Secret source: secret-service",
        "Secret source: windows-credential-manager",
    }


@pytest.mark.parametrize(
    "module,name,priority",
    [
        ("keyrings.alt.file", "PlaintextKeyring", 5),
        ("keyring.backends.chainer", "ChainerBackend", 10),
        ("keyring.backends.SecretService", "Keyring", RuntimeError("no D-Bus service")),
        ("keyring.backends.SecretService", "Keyring", 0),
        ("keyring.backends.SecretService", "Keyring", "5"),
    ],
)
def test_SEC_LOADER_keyring_probe_refuses_untrusted_or_dead_backends(
    monkeypatch: pytest.MonkeyPatch, module: str, name: str, priority: object
) -> None:
    from backend.security.secrets import KeyringSecretStore

    store = native_store(monkeypatch, module, name, priority)
    assert isinstance(store, KeyringSecretStore)
    with pytest.raises(ConfigurationError):
        store.probe()
    with pytest.raises(SecretsUnavailableError):
        select_secret_store({}, keyring=lambda: store)
