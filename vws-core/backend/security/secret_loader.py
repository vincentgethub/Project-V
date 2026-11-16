"""SEC-LOADER: the single secret loader. Strict order, refuse otherwise.

1. systemd credentials: ``$CREDENTIALS_DIRECTORY/vws.<name>`` from
   ``LoadCredentialEncrypted=`` (deploy/vws.service). Read-only.
2. A real Secret Service (or Windows Credential Manager) through the pinned
   native keyring backend. Plaintext, file, chainer, fail and null backends are
   refused by class.
3. Injected in memory: only with ``VWS_SECRET_SOURCE=injected``, paper only.
   Values arrive as ``VWS_INJECTED_<NAME>`` process variables at launch, are
   removed from the environment mapping when read and are never written.

Anything else raises ``SECRETS_UNAVAILABLE``. A configured but invalid
higher-priority source never falls through to a lower one. Messages name the
source and the problem only, never a value.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from pydantic import SecretStr

from backend.core.errors import ConfigurationError
from backend.core.logging import register_secrets
from backend.security.secrets import SecretStore

LOADER_REFUSAL = "SECRETS_UNAVAILABLE"
CREDENTIAL_PREFIX = "vws."
INJECTED_PREFIX = "VWS_INJECTED_"
SOURCE_SELECTOR = "VWS_SECRET_SOURCE"
# One LoadCredentialEncrypted= line per name in deploy/vws.service (paper host).
SERVICE_CREDENTIALS = (
    "ALPACA_PAPER_KEY_ID",
    "ALPACA_PAPER_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CALLBACK_SECRET",
    "VWS_FINGERPRINT_SALT",
)
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_MAX_BYTES = 16384
_TRUSTED_BACKENDS = frozenset(
    {
        ("keyring.backends.SecretService", "Keyring"),
        ("keyring.backends.Windows", "WinVaultKeyring"),
    }
)
_REFUSED_CLASS_NAMES = frozenset(
    {"PlaintextKeyring", "EncryptedKeyring", "ChainerBackend", "UncryptedFileKeyring"}
)


class SecretsUnavailableError(ConfigurationError):
    """SEC-LOADER: no approved secret source; the process must not start."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"{LOADER_REFUSAL}: {reason}")


class ProbedSecretStore(SecretStore, Protocol):
    source_name: str

    def probe(self) -> None:
        """Raise when the backing service is not usable right now."""
        raise NotImplementedError("secret store must implement probe")


def _name(name: str) -> str:
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ConfigurationError("secret name must be a bounded uppercase identifier")
    return name


def _checked_value(raw: str, source: str) -> SecretStr:
    if not raw or not raw.strip() or "\x00" in raw or "\n" in raw or "\r" in raw:
        raise SecretsUnavailableError(f"{source} value is empty or malformed")
    value = SecretStr(raw)
    register_secrets(value)
    return value


def assert_trusted_keyring_backend(backend: object) -> None:
    """Refuse plaintext/file/chainer/fail/null keyrings by exact class identity."""
    kind = type(backend)
    module = kind.__module__
    if (
        kind.__name__ in _REFUSED_CLASS_NAMES
        or module.startswith("keyrings.")
        or module in {"keyring.backends.chainer", "keyring.backends.fail", "keyring.backends.null"}
        or (module, kind.__name__) not in _TRUSTED_BACKENDS
    ):
        raise SecretsUnavailableError(
            f"keyring backend {module}.{kind.__name__} is not a trusted native store"
        )


class SystemdCredentialStore:
    """Read-only view of a systemd credentials directory (0400 files, private dir)."""

    source_name = "systemd-creds"

    def __init__(self, directory: Path) -> None:
        if os.name != "posix":
            raise SecretsUnavailableError("systemd credentials need a POSIX host")
        try:
            info = directory.lstat()
        except OSError:
            raise SecretsUnavailableError("credentials directory is missing") from None
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise SecretsUnavailableError(
                "credentials directory must be a private directory owned by this service"
            )
        self._directory = directory

    def __repr__(self) -> str:
        return "SystemdCredentialStore(<credentials directory>)"

    def get(self, name: str) -> SecretStr | None:
        path = self._directory / (CREDENTIAL_PREFIX + _name(name).lower())
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            raise SecretsUnavailableError(f"credential {name} cannot be inspected") from None
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & ~0o400
            or info.st_size > _MAX_BYTES
        ):
            raise SecretsUnavailableError(
                f"credential {name} must be a regular 0400 file owned by this service"
            )
        try:
            raw = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError):
            raise SecretsUnavailableError(f"credential {name} cannot be read") from None
        return _checked_value(raw.removesuffix("\n"), f"credential {name}")

    def set(self, name: str, value: SecretStr) -> None:
        raise ConfigurationError("systemd credentials are read-only; use systemd-creds encrypt")

    def delete(self, name: str) -> None:
        raise ConfigurationError("systemd credentials are read-only; use systemd-creds encrypt")

    def probe(self) -> None:
        return None


class InjectedSecretStore:
    """Paper-only, memory-only values handed to this process at launch."""

    source_name = "injected"

    def __init__(self, values: Mapping[str, SecretStr]) -> None:
        if not values:
            raise SecretsUnavailableError("injected source holds no values")
        self._values = MappingProxyType(dict(values))

    def __repr__(self) -> str:
        return f"InjectedSecretStore(<{len(self._values)} masked values>)"

    @classmethod
    def from_environment(cls, environ: MutableMapping[str, str]) -> InjectedSecretStore:
        if environ.get(SOURCE_SELECTOR) != "injected":
            raise SecretsUnavailableError("injected source is off unless explicitly selected")
        mode = environ.get("EXECUTION_MODE", "MANUAL").strip().upper()
        paper = environ.get("PAPER_TRADING", "true").strip().casefold()
        live = environ.get("LIVE_TRADING_ENABLED", "false").strip().casefold()
        names = [key for key in environ if key.startswith(INJECTED_PREFIX)]
        if mode == "AUTO_LIVE" or paper != "true" or live != "false":
            raise SecretsUnavailableError("injected secrets are paper only")
        values: dict[str, SecretStr] = {}
        for key in names:
            raw = environ.pop(key)
            name = key.removeprefix(INJECTED_PREFIX)
            if _NAME.fullmatch(name) is None or name.startswith("ALPACA_LIVE_"):
                raise SecretsUnavailableError("injected names must be paper secret identifiers")
            values[name] = _checked_value(raw, f"injected {name}")
        return cls(values)

    def get(self, name: str) -> SecretStr | None:
        return self._values.get(_name(name))

    def set(self, name: str, value: SecretStr) -> None:
        raise ConfigurationError("injected secrets live in memory only and are never written")

    def delete(self, name: str) -> None:
        raise ConfigurationError("injected secrets live in memory only and are never written")

    def probe(self) -> None:
        return None


def _default_keyring() -> ProbedSecretStore:
    from backend.security.secrets import KeyringSecretStore

    return KeyringSecretStore()


def select_secret_store(
    environ: MutableMapping[str, str] | None = None,
    *,
    keyring: Callable[[], ProbedSecretStore] | None = None,
) -> SecretStore:
    """Return the first approved source in strict order, or refuse."""
    env = os.environ if environ is None else environ
    selector = env.get(SOURCE_SELECTOR, "")
    if selector not in {"", "injected"}:
        raise SecretsUnavailableError(f"{SOURCE_SELECTOR} accepts only 'injected'")
    directory = env.get("CREDENTIALS_DIRECTORY")
    if directory is not None:
        return SystemdCredentialStore(Path(directory))
    try:
        store = (keyring or _default_keyring)()
        store.probe()
        return store
    except Exception:
        if selector != "injected":
            raise SecretsUnavailableError(
                "no systemd credentials, no trusted Secret Service and no paper injection"
            ) from None
    return InjectedSecretStore.from_environment(env)


def secret_source_line(store: object) -> str:
    """Doctor/start line: the source name only, never a value or a path."""
    name = getattr(store, "source_name", None)
    return f"Secret source: {name if isinstance(name, str) else 'unknown'}"
