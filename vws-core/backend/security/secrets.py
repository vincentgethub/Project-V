"""SEC-10..15: native keyring storage, validated rotation and immutable evidence.

No keyring plugin discovery is used. Only Windows Credential Manager with local
machine persistence or Linux Secret Service is selected. Tests inject SecretStore
implementations and never open the owner's real keyring.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import platform
import re
import secrets
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from types import MappingProxyType
from typing import Literal, Protocol, cast

from pydantic import SecretStr
from sqlalchemy import select

from backend.core.clock import Clock, ensure_utc
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.logging import register_secrets
from backend.security.native_ipc import native_keyring_call

_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_ROTATION_LOCK = RLock()
_LEGACY_PLAID_NAMES = frozenset(
    {"PLAID_ACCESS_TOKEN", "PLAID_TOKEN_PATH", "FERNET_KEY", "FRED_API_KEY"}
)
_LIVE_ENV_ALIASES = frozenset(
    {"BROKER_API_KEY", "BROKER_SECRET_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"}
)


class SecretStore(Protocol):
    """SEC-11/SEC-40: secret access is an explicit injectable boundary."""

    def get(self, name: str) -> SecretStr | None:
        """SEC-14: return a masked value, with None only for a missing entry."""
        raise NotImplementedError("secret store must implement get")

    def set(self, name: str, value: SecretStr) -> None:
        """SEC-11: atomically replace one native keyring entry."""
        raise NotImplementedError("secret store must implement set")

    def delete(self, name: str) -> None:
        """SEC-13: restore an absent prior entry after a failed operation."""
        raise NotImplementedError("secret store must implement delete")


class _KeyringBackend(Protocol):
    """SEC-11: minimal native backend contract, without plugin discovery."""

    def get_password(self, service: str, username: str) -> str | None:
        """SEC-11: read one operating-system credential."""
        raise NotImplementedError("native backend must implement get_password")

    def set_password(self, service: str, username: str, password: str) -> None:
        """SEC-11: replace one operating-system credential."""
        raise NotImplementedError("native backend must implement set_password")

    def delete_password(self, service: str, username: str) -> None:
        """SEC-13: remove one operating-system credential."""
        raise NotImplementedError("native backend must implement delete_password")


class _WindowsBackend(_KeyringBackend, Protocol):
    """SEC-11: Windows persistence must be local to this machine."""

    persist: str


def _native_backend() -> _KeyringBackend:
    """SEC-11: refuse unsupported hosts and unavailable/locked native storage."""
    try:
        system = platform.system()
        if system == "Windows":
            # VERIFY: https://github.com/jaraco/keyring/blob/v25.7.0/keyring/backends/Windows.py
            from keyring.backends.Windows import WinVaultKeyring

            backend = cast(Callable[[], _WindowsBackend], WinVaultKeyring)()
            backend.persist = "local machine"
            return cast(_KeyringBackend, backend)
        if system == "Linux":
            # VERIFY: https://github.com/jaraco/keyring/blob/v25.7.0/keyring/backends/SecretService.py
            from keyring.backends.SecretService import Keyring

            return cast(Callable[[], _KeyringBackend], Keyring)()
        raise ConfigurationError("native keyring supports Windows or Linux only")
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError(
            "trusted native keyring is unavailable; no fallback is permitted"
        ) from None


def _name(name: str) -> str:
    """SEC-14: validate static credential identifiers without exposing values."""
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ConfigurationError("secret name must be a bounded uppercase identifier")
    return name


def _secret(value: SecretStr) -> str:
    """SEC-14: reject invalid hidden input before calling any native backend."""
    if not isinstance(value, SecretStr):
        raise ConfigurationError("secret value must be supplied as masked input")
    raw = value.get_secret_value()
    if not raw or not raw.strip() or len(raw) > 16384 or "\x00" in raw:
        raise ConfigurationError("secret value is empty, oversized or malformed")
    register_secrets(value)
    return raw


class KeyringSecretStore:
    """SEC-11/SEC-14: explicit native backend; no env/file/plaintext fallback."""

    def __init__(self) -> None:
        """SEC-11: construct only the approved host-specific native backend."""
        self._backend = _native_backend()
        self._lock = RLock()

    def get(self, name: str) -> SecretStr | None:
        """SEC-11: a backend failure is unavailable evidence, never a fallback."""
        _name(name)
        try:
            with self._lock, native_keyring_call():
                raw = self._backend.get_password(f"vws-core:{name}", "vws")
            if raw is None:
                return None
            if not isinstance(raw, str):
                raise ConfigurationError("native keyring returned an invalid value")
            result = SecretStr(raw)
            _secret(result)
            return result
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError("native keyring read failed") from None

    def set(self, name: str, value: SecretStr) -> None:
        """SEC-13: native single-entry replacement followed by read verification."""
        _name(name)
        raw = _secret(value)
        try:
            with self._lock, native_keyring_call():
                self._backend.set_password(f"vws-core:{name}", "vws", raw)
                observed = self._backend.get_password(f"vws-core:{name}", "vws")
                if not isinstance(observed, str) or not hmac.compare_digest(observed, raw):
                    raise ConfigurationError("native keyring write could not be verified")
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError("native keyring write failed") from None

    def delete(self, name: str) -> None:
        """SEC-13: idempotently restore a previously missing native entry."""
        _name(name)
        try:
            with self._lock, native_keyring_call():
                if self._backend.get_password(f"vws-core:{name}", "vws") is not None:
                    self._backend.delete_password(f"vws-core:{name}", "vws")
                if self._backend.get_password(f"vws-core:{name}", "vws") is not None:
                    raise ConfigurationError("native keyring deletion could not be verified")
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError("native keyring deletion failed") from None


def assert_secret_sources(
    mode: str,
    *,
    environment: Mapping[str, str] | None = None,
    dotenv_keys: Collection[str] = (),
) -> None:
    """SEC-10/SEC-11: reject forbidden env sources, even if values are empty."""
    if mode not in {"MANUAL", "AUTO_PAPER", "AUTO_LIVE"}:
        raise ConfigurationError("secret-source validation requires a known execution mode")
    source = os.environ if environment is None else environment
    names = {name.upper() for name in (*source, *dotenv_keys)}
    if names.intersection(_LEGACY_PLAID_NAMES):
        raise ConfigurationError("Keyring-only credentials must exist only in the native keyring")
    if mode == "AUTO_LIVE" and any(
        name.startswith("ALPACA_LIVE_")
        or name in {"TELEGRAM_BOT_TOKEN", "PLAID_SECRET"}
        or name in _LIVE_ENV_ALIASES
        for name in names
    ):
        raise ConfigurationError("AUTO_LIVE secrets must come only from the native keyring")


def plaid_access_token(store: SecretStore | None = None) -> SecretStr:
    """SEC-11: require keyring storage in every execution mode."""
    assert_secret_sources("MANUAL")
    source = KeyringSecretStore() if store is None else store
    try:
        token = source.get("PLAID_ACCESS_TOKEN")
        if token is None:
            raise ConfigurationError("Plaid access token is missing from the native keyring")
        _secret(token)
        return token
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("Plaid native keyring token cannot be read") from None


@dataclass(frozen=True, slots=True)
class RotationRecord:
    """SEC-13: only non-secret HMAC evidence is returned or persisted."""

    name: str
    fingerprint: str
    rotated_at: datetime


@dataclass(frozen=True, slots=True)
class SecretAge:
    """SEC-13: an unknown rotation date is never presented as a pass."""

    name: str
    last_rotated: datetime | None
    age_days: int | None
    status: Literal["PASS", "WARN", "UNKNOWN"]


class RotationService:
    """SEC-13: injected named live validators run before any credential swap."""

    def __init__(
        self,
        store: SecretStore,
        clock: Clock,
        ledger: Ledger,
        validators: Mapping[str, Callable[[SecretStr], None]],
    ) -> None:
        """SEC-13: detach validators; no client is constructed or probed here."""
        self.store, self.clock, self.ledger = store, clock, ledger
        self.validators = MappingProxyType(dict(validators))

    def fingerprint(self, name: str, value: SecretStr) -> str:
        """SEC-13: HMAC uses a random local salt held only in the native keyring."""
        _name(name)
        raw = _secret(value)
        with _ROTATION_LOCK:
            salt = self.store.get("VWS_FINGERPRINT_SALT")
            if salt is None:
                salt = SecretStr(base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
                self.store.set("VWS_FINGERPRINT_SALT", salt)
            try:
                salt_bytes = base64.b64decode(_secret(salt), validate=True)
                if len(salt_bytes) != 32:
                    raise ValueError("invalid local salt")
            except (ValueError, UnicodeError):
                raise ConfigurationError("keyring fingerprint salt cannot be verified") from None
            return hmac.new(salt_bytes, f"{name}\0{raw}".encode(), hashlib.sha256).hexdigest()

    def rotate(self, name: str, value: SecretStr) -> RotationRecord:
        """SEC-13: restore the old value on validation, swap or audit failure."""
        _name(name)
        _secret(value)
        validator = self.validators.get(name)
        if validator is None:
            raise ConfigurationError("secret rotation needs a named live validator")
        with _ROTATION_LOCK:
            try:
                self.ledger.verify_chain()
                if validator(value) is not None:
                    raise ConfigurationError("secret validation did not return a verified result")
                at = ensure_utc(self.clock.now())
                fingerprint = self.fingerprint(name, value)
                old = self.store.get(name)
            except Exception:
                raise ConfigurationError(
                    "secret validation failed; existing value is unchanged"
                ) from None
            try:
                self.store.set(name, value)
                observed = self.store.get(name)
                if observed is None or not hmac.compare_digest(_secret(observed), _secret(value)):
                    raise ConfigurationError("secret swap could not be verified")
                self.ledger.append(
                    SecurityEvent,
                    kind="SECRET_ROTATED",
                    detail={"name": name, "fingerprint": fingerprint},
                    ts=at,
                )
            except Exception:
                try:
                    if old is None:
                        self.store.delete(name)
                    else:
                        self.store.set(name, old)
                except Exception:
                    raise DataIntegrityError(
                        "secret rotation failed and restoration is unverified"
                    ) from None
                raise ConfigurationError(
                    "secret rotation failed; prior value was restored"
                ) from None
            return RotationRecord(name, fingerprint, at)

    def age(self, name: str, max_age_days: int = 90) -> SecretAge:
        """SEC-13: WARN starts at the configured full-day boundary."""
        _name(name)
        if (
            isinstance(max_age_days, bool)
            or not isinstance(max_age_days, int)
            or not 30 <= max_age_days <= 365
        ):
            raise ConfigurationError("secret maximum age must be between 30 and 365 days")
        try:
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                rows = session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "SECRET_ROTATED")
                    .order_by(SecurityEvent.seq.desc())
                ).all()
                latest = next((row.ts for row in rows if row.detail.get("name") == name), None)
            if latest is None:
                return SecretAge(name, None, None, "UNKNOWN")
            elapsed = ensure_utc(self.clock.now()) - ensure_utc(latest)
            if elapsed.total_seconds() < 0:
                raise DataIntegrityError("secret rotation evidence has a future timestamp")
            days = elapsed.days
            return SecretAge(name, latest, days, "WARN" if days >= max_age_days else "PASS")
        except (ConfigurationError, DataIntegrityError):
            raise
        except Exception:
            raise DataIntegrityError("secret age evidence cannot be verified") from None
