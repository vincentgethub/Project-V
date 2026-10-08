"""SEC-31/32/34: explicit destinations and an SDK socket audit backstop.

Python audit hooks are a defense against accidental SDK bypasses, not a
sandbox for malicious Python code. DNS results authorize numeric socket
destinations; the HTTP boundary still checks the hostname and verifies TLS.
Importing this module neither resolves DNS nor installs process-wide hooks.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Never
from urllib.parse import urlsplit

from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, EgressDeniedError
from backend.core.ledger import Ledger

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_BASE_HOSTS = frozenset(
    {
        "paper-api.alpaca.markets",
        "data.alpaca.markets",
        "stream.data.alpaca.markets",
        "api.telegram.org",
        "www.sec.gov",
        "data.sec.gov",
        "api.stlouisfed.org",
    }
)
_PLAID_HOSTS = {
    "sandbox": "sandbox.plaid.com",
    "development": "development.plaid.com",
    "production": "production.plaid.com",
}


def normalize_host(host: str) -> str:
    """SEC-31: accept exact DNS names, never IPs, globs, or URL fragments."""
    if not isinstance(host, str) or not host or host != host.strip() or host.endswith("."):
        raise ConfigurationError("egress host must be an exact DNS hostname")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise ConfigurationError("IP literals cannot appear in the egress allowlist")
    try:
        normalized = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ConfigurationError("egress hostname cannot be normalized") from None
    if (
        len(normalized) > 253
        or "." not in normalized
        or not all(_HOST_LABEL.fullmatch(label) for label in normalized.split("."))
    ):
        raise ConfigurationError("egress host must be an exact DNS hostname")
    return normalized


def _configured_url_host(url: str) -> str:
    if not isinstance(url, str):
        raise ConfigurationError("configured outbound URL must be a string")
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme.lower() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname is None
            or parsed.port not in {None, 443}
            or any(ord(character) < 33 for character in url)
            or "\\" in url
        ):
            raise ConfigurationError("configured outbound URL must use ordinary verified HTTPS")
        return normalize_host(parsed.hostname)
    except ValueError:
        raise ConfigurationError("configured outbound URL is malformed") from None


def build_allowlist(
    *,
    mode: str = "MANUAL",
    plaid_env: str = "sandbox",
    llm_enabled: bool = False,
    llm_base_url: str | None = None,
    healthcheck_url: str | None = None,
    rss_urls: Iterable[str] = (),
    news_provider: str = "ALPACA",
    extra_hosts: Mapping[str, str] | Iterable[tuple[str, str]] = (),
) -> frozenset[str]:
    """SEC-31: derive a startup allowlist from verified, explicit configuration."""
    if mode not in {"MANUAL", "AUTO_PAPER", "AUTO_LIVE"}:
        raise ConfigurationError("unknown execution mode cannot expand egress")
    if (
        plaid_env not in _PLAID_HOSTS
        or type(llm_enabled) is not bool
        or news_provider not in {"ALPACA", "RSS", "NEWSAPI"}
    ):
        raise ConfigurationError("egress environment or LLM enablement is invalid")
    hosts = set(_BASE_HOSTS)
    hosts.add(_PLAID_HOSTS[plaid_env])
    if mode == "AUTO_LIVE":
        hosts.add("api.alpaca.markets")
    if llm_enabled:
        if not llm_base_url:
            raise ConfigurationError("enabled LLM requires an explicit HTTPS base URL")
        hosts.add(_configured_url_host(llm_base_url))
    if healthcheck_url:
        hosts.add(_configured_url_host(healthcheck_url))
    hosts.update(_configured_url_host(url) for url in rss_urls)
    if news_provider == "NEWSAPI":
        hosts.add("newsapi.org")
    entries = extra_hosts.items() if isinstance(extra_hosts, Mapping) else extra_hosts
    for host, comment in entries:
        if not isinstance(comment, str) or not comment.strip():
            raise ConfigurationError("every extra egress host requires a reason comment")
        normalized = normalize_host(host)
        if normalized == "api.alpaca.markets" and mode != "AUTO_LIVE":
            raise ConfigurationError("extra hosts cannot enable live Alpaca outside AUTO_LIVE")
        hosts.add(normalized)
    if mode != "AUTO_LIVE" and "api.alpaca.markets" in hosts:
        raise ConfigurationError("configured URLs cannot enable live Alpaca outside AUTO_LIVE")
    return frozenset(hosts)


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """SEC-31: refuse unknown destinations with a durable, sanitized audit row."""

    hosts: frozenset[str]
    ledger: Ledger

    def __post_init__(self) -> None:
        if not self.hosts or any(normalize_host(host) != host for host in self.hosts):
            raise ConfigurationError("egress allowlist must contain normalized DNS hostnames")
        object.__setattr__(self, "hosts", frozenset(self.hosts))

    def deny(self, *, purpose: str, reason: str, host: str = "unknown") -> Never:
        """SEC-31/R-02: persist the refusal before raising; persistence also fails closed."""
        safe_host = host if re.fullmatch(r"[a-z0-9.:-]{1,253}", host) else "unknown"
        self.ledger.append(
            SecurityEvent,
            kind="EGRESS_DENIED",
            detail={"purpose": purpose, "reason": reason, "host": safe_host},
        )
        raise EgressDeniedError(f"outbound request denied: {reason} ({safe_host})")

    def check_url(self, url: str, *, purpose: str) -> str:
        """SEC-30: HTTPS, ordinary port, no credentials, and an exact approved host."""
        try:
            host = _configured_url_host(url)
        except ConfigurationError:
            self.deny(purpose=purpose, reason="invalid HTTPS destination")
        if host not in self.hosts:
            self.deny(purpose=purpose, reason="hostname is not allowlisted", host=host)
        return host


class SDKSocketGuard:
    """SEC-32/34: explicit process-wide DNS/connect audit backstop for SDKs.

    Numeric addresses are authorized only by successful controlled lookups of
    allowlisted names. Shared hosting means a numeric address is not proof of
    application identity, so hostname checks and TLS remain mandatory. Hooks
    cannot be removed; activate only once, during validated application startup.
    """

    def __init__(self, policy: EgressPolicy) -> None:
        self.policy = policy
        self._addresses: set[str] = set()
        self._lock = threading.RLock()
        self._installed = False
        self._resolver: Callable[..., Any] = socket.getaddrinfo

    @property
    def installed(self) -> bool:
        return self._installed and socket.getaddrinfo == self.resolve

    def _check_host(self, host: object) -> str:
        if isinstance(host, bytes):
            try:
                host = host.decode("ascii")
            except UnicodeError:
                self.policy.deny(purpose="sdk", reason="invalid DNS host")
        if not isinstance(host, str):
            self.policy.deny(purpose="sdk", reason="missing DNS host")
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            if host.lower() == "localhost":
                return host
            try:
                normalized = normalize_host(host)
            except ConfigurationError:
                self.policy.deny(purpose="sdk", reason="invalid DNS host")
            if normalized not in self.policy.hosts:
                self.policy.deny(
                    purpose="sdk", reason="DNS host is not allowlisted", host=normalized
                )
            return normalized
        if address.is_loopback:
            return host
        self.policy.deny(purpose="sdk", reason="literal IP lookup is prohibited", host=str(address))

    def resolve(self, host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        """SEC-32: inspect both the name before DNS and all resulting addresses."""
        self._check_host(host)
        results = self._resolver(host, port, *args, **kwargs)
        addresses: set[str] = set()
        for result in results:
            try:
                address = ipaddress.ip_address(result[4][0])
            except (ValueError, TypeError, IndexError):
                self.policy.deny(purpose="sdk", reason="malformed DNS result")
            if not address.is_global and not address.is_loopback:
                self.policy.deny(
                    purpose="sdk", reason="DNS resolved to a nonpublic address", host=str(address)
                )
            addresses.add(str(address))
        if not addresses:
            self.policy.deny(purpose="sdk", reason="DNS returned no addresses")
        with self._lock:
            self._addresses.update(addresses)
        return results

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        """SEC-32: connect_ex emits the same socket.connect event as connect."""
        if event == "socket.getaddrinfo":
            self._check_host(args[0] if args else None)
        elif event == "socket.bind":
            self.policy.deny(purpose="sdk", reason="inbound socket binds are prohibited")
        elif event == "socket.connect":
            endpoint = args[1] if len(args) > 1 else None
            from backend.security.native_ipc import native_connection_allowed

            if len(args) > 1 and native_connection_allowed(args[0], endpoint):
                return
            if not isinstance(endpoint, tuple) or len(endpoint) < 2:
                self.policy.deny(purpose="sdk", reason="unverifiable socket address")
            host, port = endpoint[:2]
            try:
                address = ipaddress.ip_address(host)
            except (ValueError, TypeError):
                self.policy.deny(purpose="sdk", reason="connect requires controlled DNS resolution")
            if address.is_loopback:
                return
            with self._lock:
                known = str(address) in self._addresses
            if not known or port != 443:
                self.policy.deny(
                    purpose="sdk", reason="socket destination is not authorized", host=str(address)
                )

    def install(self) -> None:
        """SEC-32: activate only after configuration and ledger validation."""
        if self._installed:
            if not self.installed:
                raise ConfigurationError("installed DNS guard has been replaced")
            return
        sys.addaudithook(self.audit)
        socket.getaddrinfo = self.resolve
        self._installed = True
