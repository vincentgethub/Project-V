"""SEC-10..14: fake native backends, source refusal and rollback-safe rotation."""

import json
import platform
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.security import secrets as module
from backend.security.secrets import (
    KeyringSecretStore,
    RotationService,
    assert_secret_sources,
    plaid_access_token,
)

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)


class FakeStore:
    """SEC-11: isolated masked storage with deterministic failure injection."""

    def __init__(self) -> None:
        self.values: dict[str, SecretStr] = {}
        self.fail_new = False

    def get(self, name: str) -> SecretStr | None:
        return self.values.get(name)

    def set(self, name: str, value: SecretStr) -> None:
        self.values[name] = value
        if self.fail_new and value.get_secret_value() == "new-isolated-secret":
            raise RuntimeError("injected partial store failure")

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class FakeNative:
    """SEC-11: native-shaped fake, with no OS service or credential read."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.persist: str = ""
        self.fail = False

    def get_password(self, service: str, username: str) -> str | None:
        if self.fail:
            raise RuntimeError("access-sandbox-unregistered-error-token")
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.fail:
            raise RuntimeError(password)
        self.values[service, username] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.fail:
            raise RuntimeError("native denied")
        self.values.pop((service, username), None)


def test_SEC_11_native_backend_selection_is_explicit_and_local_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from keyring.backends import SecretService, Windows

    fake = FakeNative()
    monkeypatch.setattr(Windows, "WinVaultKeyring", lambda: fake)
    monkeypatch.setattr(SecretService, "Keyring", lambda: fake)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    assert module._native_backend() is fake
    assert fake.persist == "local machine"
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert module._native_backend() is fake
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    with pytest.raises(ConfigurationError, match="Windows or Linux"):
        module._native_backend()


def test_SEC_11_keyring_has_no_plaintext_or_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    native = FakeNative()
    monkeypatch.setattr(module, "_native_backend", lambda: native)
    store = KeyringSecretStore()
    assert store.get("PLAID_ACCESS_TOKEN") is None
    store.set("PLAID_ACCESS_TOKEN", SecretStr("isolated-native-token"))
    token = store.get("PLAID_ACCESS_TOKEN")
    assert token is not None and token.get_secret_value() == "isolated-native-token"
    assert "isolated-native-token" not in repr(token)
    store.delete("PLAID_ACCESS_TOKEN")
    store.delete("PLAID_ACCESS_TOKEN")
    assert store.get("PLAID_ACCESS_TOKEN") is None
    native.fail = True
    operations: tuple[Callable[[], object], ...] = (
        lambda: store.get("PLAID_ACCESS_TOKEN"),
        lambda: store.set("PLAID_ACCESS_TOKEN", SecretStr("new-value")),
        lambda: store.delete("PLAID_ACCESS_TOKEN"),
    )
    for operation in operations:
        with pytest.raises(ConfigurationError) as caught:
            operation()
        assert "access-sandbox-unregistered-error-token" not in str(caught.value)


@pytest.mark.parametrize("name", ["lower", "", "BAD-NAME", "A" * 129])
def test_SEC_14_secret_names_are_bounded_before_backend_access(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(module, "_native_backend", FakeNative)
    with pytest.raises(ConfigurationError):
        KeyringSecretStore().get(name)


@pytest.mark.parametrize(
    "value", [SecretStr(""), SecretStr(" "), SecretStr("\x00"), SecretStr("x" * 16385), "plaintext"]
)
def test_SEC_14_invalid_hidden_input_never_reaches_backend(
    monkeypatch: pytest.MonkeyPatch, value: Any
) -> None:
    native = FakeNative()
    monkeypatch.setattr(module, "_native_backend", lambda: native)
    with pytest.raises(ConfigurationError):
        KeyringSecretStore().set("TELEGRAM_BOT_TOKEN", value)
    assert not native.values


@pytest.mark.parametrize("mode", ["MANUAL", "AUTO_PAPER", "AUTO_LIVE"])
@pytest.mark.parametrize("name", ["PLAID_ACCESS_TOKEN", "PLAID_TOKEN_PATH", "FERNET_KEY"])
def test_SEC_11_plaid_legacy_sources_are_refused_even_if_empty(mode: str, name: str) -> None:
    with pytest.raises(ConfigurationError, match="keyring"):
        assert_secret_sources(mode, environment={name: ""})
    with pytest.raises(ConfigurationError, match="keyring"):
        assert_secret_sources(mode, environment={}, dotenv_keys=(name.lower(),))


@pytest.mark.parametrize(
    "name",
    [
        "ALPACA_LIVE_API_KEY",
        "ALPACA_LIVE_SECRET_KEY",
        "TELEGRAM_BOT_TOKEN",
        "PLAID_SECRET",
        "BROKER_API_KEY",
        "BROKER_SECRET_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
    ],
)
def test_SEC_10_auto_live_refuses_env_and_dotenv_secret_sources(name: str) -> None:
    with pytest.raises(ConfigurationError, match="AUTO_LIVE"):
        assert_secret_sources("AUTO_LIVE", environment={name: ""})
    with pytest.raises(ConfigurationError, match="AUTO_LIVE"):
        assert_secret_sources("AUTO_LIVE", environment={}, dotenv_keys=(name,))
    assert_secret_sources("MANUAL", environment={name: ""})
    assert_secret_sources("AUTO_LIVE", environment={}, dotenv_keys=())


def test_SEC_11_plaid_only_reads_the_injected_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    with pytest.raises(ConfigurationError, match="missing"):
        plaid_access_token(store)
    store.set("PLAID_ACCESS_TOKEN", SecretStr("isolated-plaid-token"))
    assert plaid_access_token(store).get_secret_value() == "isolated-plaid-token"
    monkeypatch.setenv("PLAID_ACCESS_TOKEN", "")
    with pytest.raises(ConfigurationError):
        plaid_access_token(store)


def service(engine: Engine, store: FakeStore, clock: FrozenClock) -> RotationService:
    """SEC-13: every validator is a named fake; sockets are prohibited."""
    return RotationService(
        store, clock, Ledger(engine, clock), {"TELEGRAM_BOT_TOKEN": lambda _value: None}
    )


def test_SEC_13_rotation_hmac_evidence_and_age_boundary(engine: Engine) -> None:
    store, clock = FakeStore(), FrozenClock(NOW)
    rotation = service(engine, store, clock)
    assert rotation.age("TELEGRAM_BOT_TOKEN").status == "UNKNOWN"
    result = rotation.rotate("TELEGRAM_BOT_TOKEN", SecretStr("new-isolated-secret"))
    assert result.rotated_at == NOW
    assert len(result.fingerprint) == 64
    assert (
        rotation.fingerprint("TELEGRAM_BOT_TOKEN", SecretStr("new-isolated-secret"))
        == result.fingerprint
    )
    assert (
        rotation.fingerprint("TELEGRAM_BOT_TOKEN", SecretStr("other-value")) != result.fingerprint
    )
    with transaction(engine) as session:
        event = session.scalars(select(SecurityEvent)).one()
        assert event.kind == "SECRET_ROTATED"
        assert event.detail == {"name": result.name, "fingerprint": result.fingerprint}
        assert "new-isolated-secret" not in json.dumps(event.detail)
    assert (
        service(engine, store, FrozenClock(NOW + timedelta(days=89))).age(result.name).status
        == "PASS"
    )
    assert (
        service(engine, store, FrozenClock(NOW + timedelta(days=90))).age(result.name).status
        == "WARN"
    )
    with pytest.raises(DataIntegrityError, match="verified"):
        service(engine, store, FrozenClock(NOW - timedelta(seconds=1))).age(result.name)


def test_SEC_13_failed_validation_keeps_prior_secret_and_creates_no_evidence(
    engine: Engine,
) -> None:
    store = FakeStore()
    old = SecretStr("old-isolated-secret")
    store.set("TELEGRAM_BOT_TOKEN", old)

    def refuse(_value: SecretStr) -> None:
        raise RuntimeError("new-isolated-secret")

    clock = FrozenClock(NOW)
    rotation = RotationService(store, clock, Ledger(engine, clock), {"TELEGRAM_BOT_TOKEN": refuse})
    with pytest.raises(ConfigurationError, match="unchanged"):
        rotation.rotate("TELEGRAM_BOT_TOKEN", SecretStr("new-isolated-secret"))
    assert store.get("TELEGRAM_BOT_TOKEN") == old
    assert "VWS_FINGERPRINT_SALT" not in store.values
    with transaction(engine) as session:
        assert not session.scalars(select(SecurityEvent)).all()


@pytest.mark.parametrize("had_prior", [False, True])
def test_SEC_13_partial_swap_restores_prior_or_absence(engine: Engine, had_prior: bool) -> None:
    store = FakeStore()
    if had_prior:
        store.set("TELEGRAM_BOT_TOKEN", SecretStr("old-isolated-secret"))
    old = store.get("TELEGRAM_BOT_TOKEN")
    store.fail_new = True
    with pytest.raises(ConfigurationError, match="restored"):
        service(engine, store, FrozenClock(NOW)).rotate(
            "TELEGRAM_BOT_TOKEN", SecretStr("new-isolated-secret")
        )
    assert store.get("TELEGRAM_BOT_TOKEN") == old


def test_SEC_13_audit_failure_restores_prior_secret(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeStore()
    old = SecretStr("old-isolated-secret")
    store.set("TELEGRAM_BOT_TOKEN", old)
    rotation = service(engine, store, FrozenClock(NOW))

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(rotation.ledger, "append", refuse)
    with pytest.raises(ConfigurationError, match="restored"):
        rotation.rotate("TELEGRAM_BOT_TOKEN", SecretStr("new-isolated-secret"))
    assert store.get("TELEGRAM_BOT_TOKEN") == old


def test_SEC_13_unknown_validator_and_invalid_salt_cannot_rotate(engine: Engine) -> None:
    store = FakeStore()
    rotation = service(engine, store, FrozenClock(NOW))
    with pytest.raises(ConfigurationError, match="validator"):
        rotation.rotate("UNVALIDATED_SECRET", SecretStr("new-value"))
    store.set("VWS_FINGERPRINT_SALT", SecretStr("invalid-base64"))
    with pytest.raises(ConfigurationError, match="salt"):
        rotation.fingerprint("TELEGRAM_BOT_TOKEN", SecretStr("new-value"))
