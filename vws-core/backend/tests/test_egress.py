"""SEC-30/31/32: offline destination, redirect, deadline and SDK backstop proofs."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, EgressDeniedError, ProviderError
from backend.core.ledger import Ledger
from backend.net import http
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist, normalize_host
from backend.net.http import TimeoutSession, configure_network, make_client


@pytest.fixture
def policy(engine: Engine, clock: FrozenClock) -> EgressPolicy:
    return EgressPolicy(build_allowlist(), Ledger(engine, clock))


def _events(policy: EgressPolicy) -> list[SecurityEvent]:
    with transaction(policy.ledger.engine) as session:
        return list(session.scalars(select(SecurityEvent)).all())


def test_SEC_31_allowlist_exact_configuration() -> None:
    hosts = build_allowlist(
        mode="AUTO_LIVE",
        plaid_env="production",
        llm_enabled=True,
        llm_base_url="https://llm.example.com/v1",
        healthcheck_url="https://health.example.com/token",
        rss_urls=["https://news.example.com/feed"],
        extra_hosts={"extra.example.com": "approved feed"},
    )
    assert {
        "api.alpaca.markets",
        "production.plaid.com",
        "llm.example.com",
        "health.example.com",
        "news.example.com",
        "extra.example.com",
    } <= hosts
    default = build_allowlist(llm_base_url="https://disabled.example.com")
    assert "api.alpaca.markets" not in default and "disabled.example.com" not in default
    assert "stream.data.alpaca.markets" in default


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "UNKNOWN"},
        {"plaid_env": "unknown"},
        {"llm_enabled": 1},
        {"llm_enabled": True},
        {"extra_hosts": {"extra.example.com": ""}},
        {"extra_hosts": {"api.alpaca.markets": "attempted mode bypass"}},
        {"rss_urls": ["https://user:password@news.example.com/feed"]},
        {"rss_urls": ["https://news.example.com:444/feed"]},
        {"rss_urls": ["https://api.alpaca.markets/feed"]},
        {"healthcheck_url": "https://api.alpaca.markets/health"},
        {"llm_enabled": True, "llm_base_url": "https://api.alpaca.markets/v1"},
    ],
)
def test_SEC_31_invalid_allowlist_fails_closed(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ConfigurationError):
        build_allowlist(**kwargs)


@pytest.mark.parametrize(
    "host",
    [
        "",
        "*.example.com",
        "example.com.",
        " example.com",
        "https://example.com",
        "8.8.8.8",
        "[::1]",
        "a..example.com",
        "localhost",
    ],
)
def test_SEC_31_allowlist_rejects_non_dns_entries(host: str) -> None:
    with pytest.raises(ConfigurationError):
        normalize_host(host)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "https://8.8.8.8",
        "https://[::1]",
        "https://user:secret@data.alpaca.markets",
        "https://data.alpaca.markets:444",
        "https://data.alpaca.markets.evil.example.com",
        "https://data.alpaca.markets\\evil.example.com",
        "https://data.alpaca.markets\n",
        "https://data.alpaca.markets.",
        "https://data.alpaca.markets:bad",
    ],
)
def test_SEC_31_each_url_denial_has_sanitized_ledger_event(policy: EgressPolicy, url: str) -> None:
    with pytest.raises(EgressDeniedError):
        policy.check_url(url, purpose="research")
    events = _events(policy)
    assert len(events) == 1 and events[0].kind == "EGRESS_DENIED"
    assert set(events[0].detail) == {"purpose", "reason", "host"}
    assert "secret" not in str(events[0].detail) and url not in str(events[0].detail)
    policy.ledger.verify_chain()


def test_SEC_30_http_and_loopback_refused_at_http_boundary(policy: EgressPolicy) -> None:
    for url in [f"{'http'}://data.alpaca.markets", f"{'http'}://localhost"]:
        with pytest.raises(EgressDeniedError):
            policy.check_url(url, purpose="research")
    assert len(_events(policy)) == 2


@pytest.mark.asyncio
async def test_SEC_30_factory_requires_runtime_policy(
    monkeypatch: pytest.MonkeyPatch, policy: EgressPolicy
) -> None:
    monkeypatch.setattr(http, "_policy", None)
    with pytest.raises(ConfigurationError):
        make_client("research")
    configure_network(policy)
    async with make_client(
        "research",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})),
    ) as client:
        response = await client.get("https://data.alpaca.markets/value")
        assert response.json() == {"ok": True}
        assert client._client.timeout.connect == 5 and client._client.timeout.read == 20
        assert not client._client.trust_env
    assert not _events(policy)


@pytest.mark.asyncio
async def test_SEC_30_redirects_are_checked_before_second_request(policy: EgressPolicy) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com/untrusted"})

    async with make_client(
        "research", policy=policy, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(EgressDeniedError):
            await client.get("https://data.alpaca.markets/start")
    assert len(requests) == 1 and len(_events(policy)) == 1


@pytest.mark.asyncio
async def test_SEC_30_approved_cross_host_redirect_drops_credentials(policy: EgressPolicy) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://data.sec.gov/public"})
        return httpx.Response(200, content=b"public")

    async with make_client(
        "research", policy=policy, transport=httpx.MockTransport(handler)
    ) as client:
        response = await client.get(
            "https://data.alpaca.markets/start",
            headers={"Authorization": "secret", "APCA-API-KEY-ID": "secret", "Cookie": "secret"},
        )
    assert response.content == b"public" and len(requests) == 2
    assert not {"authorization", "apca-api-key-id", "cookie"} & set(requests[1].headers)


@pytest.mark.asyncio
async def test_SEC_30_cross_host_redirect_never_forwards_secret_body(policy: EgressPolicy) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"location": "https://data.sec.gov/public"})

    async with make_client(
        "plaid", policy=policy, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(EgressDeniedError, match="request bodies"):
            await client.post("https://sandbox.plaid.com/item/get", json={"access_token": "secret"})
    assert len(requests) == 1 and len(_events(policy)) == 1


class _SlowBody(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.005)
            yield b"chunk"


class _SlowClose(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"complete"

    async def aclose(self) -> None:
        await asyncio.sleep(5)


@pytest.mark.asyncio
async def test_SEC_30_whole_deadline_includes_response_cleanup(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http, "_WHOLE_REQUEST_SECONDS", 0.025)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=_SlowClose()))
    async with make_client("research", policy=policy, transport=transport) as client:
        with pytest.raises(ProviderError, match="whole-request deadline"):
            async with asyncio.timeout(0.5):
                await client.get("https://data.alpaca.markets/value")


@pytest.mark.asyncio
async def test_SEC_30_whole_deadline_includes_streamed_body(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http, "_WHOLE_REQUEST_SECONDS", 0.025)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=_SlowBody()))
    async with make_client("research", policy=policy, transport=transport) as client:
        with pytest.raises(ProviderError, match="whole-request deadline"):
            await client.get("https://data.alpaca.markets/value")


@pytest.mark.asyncio
async def test_SEC_30_whole_deadline_includes_redirect_chain(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http, "_WHOLE_REQUEST_SECONDS", 0.025)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.010)
        return httpx.Response(302, headers={"location": "/another"})

    async with make_client(
        "research", policy=policy, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ProviderError, match="whole-request deadline"):
            await client.get("https://data.alpaca.markets/value")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["timeout", "verify", "follow_redirects", "stream"])
async def test_SEC_30_caller_cannot_weaken_controls(policy: EgressPolicy, key: str) -> None:
    async with make_client(
        "research",
        policy=policy,
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    ) as client:
        with pytest.raises(ConfigurationError):
            await client.get("https://data.alpaca.markets", **{key: True})


def test_SEC_32_socket_guard_requires_controlled_dns_before_connect(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = SDKSocketGuard(policy)
    monkeypatch.setattr(
        guard,
        "_resolver",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    with pytest.raises(EgressDeniedError):
        guard.audit("socket.connect", (None, ("8.8.8.8", 443)))
    guard.resolve("data.alpaca.markets", 443)
    guard.audit("socket.connect", (None, ("8.8.8.8", 443)))
    for endpoint in [("8.8.8.8", 80), ("1.1.1.1", 443), ("data.alpaca.markets", 443), "unix.sock"]:
        with pytest.raises(EgressDeniedError):
            guard.audit("socket.connect", (None, endpoint))
    assert len(_events(policy)) == 5
    assert not guard.installed


@pytest.mark.parametrize(
    "host", ["example.com", "8.8.8.8", None, bytes((255,)), "bad_host.example.com"]
)
def test_SEC_32_dns_refusal_is_audited(policy: EgressPolicy, host: object) -> None:
    guard = SDKSocketGuard(policy)
    with pytest.raises(EgressDeniedError):
        guard.audit("socket.getaddrinfo", (host, 443, 0, 0, 0))
    assert len(_events(policy)) == 1


def test_SEC_32_loopback_hook_exception_and_SEC_34_no_bind(policy: EgressPolicy) -> None:
    guard = SDKSocketGuard(policy)
    for host in ["localhost", "127.0.0.1", "::1", b"data.alpaca.markets"]:
        guard.audit("socket.getaddrinfo", (host, 443, 0, 0, 0))
    guard.audit("socket.connect", (None, ("127.0.0.1", 80)))
    guard.audit("socket.connect", (None, ("::1", 80, 0, 0)))
    guard.audit("unrelated.event", ())
    with pytest.raises(EgressDeniedError):
        guard.audit("socket.bind", (None, ("127.0.0.1", 0)))
    assert len(_events(policy)) == 1


@pytest.mark.parametrize(
    "results", [[], [(0, 0, 0, "", ("192.168.1.1", 443))], [(0, 0, 0, "", ("bad", 443))], [()]]
)
def test_SEC_32_dns_answers_fail_closed(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch, results: list[Any]
) -> None:
    guard = SDKSocketGuard(policy)
    monkeypatch.setattr(guard, "_resolver", lambda *args, **kwargs: results)
    with pytest.raises(EgressDeniedError):
        guard.resolve("data.alpaca.markets", 443)
    assert len(_events(policy)) == 1


def test_SEC_30_sdk_request_requires_policy_before_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http, "_policy", None)
    with pytest.raises(ConfigurationError, match="configured before HTTP"):
        TimeoutSession(30).request("GET", "https://data.alpaca.markets")


def test_SEC_31_failed_ledger_never_permits_io(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_append(*args: Any, **kwargs: Any) -> None:
        raise ProviderError("ledger unavailable")

    monkeypatch.setattr(policy.ledger, "append", failed_append)
    with pytest.raises(ProviderError, match="ledger unavailable"):
        policy.check_url("https://example.com", purpose="research")


def test_SEC_32_installed_hook_checks_real_audit_events_without_network(tmp_path: Path) -> None:
    """SEC-32: irreversible audit hooks remain confined to a child process."""
    script = """
import socket
import sys
from datetime import UTC, datetime
from backend.core.clock import FrozenClock
from backend.core.database import create_database, create_schema
from backend.core.errors import EgressDeniedError
from backend.core.ledger import Ledger
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist
engine = create_database('sqlite:///' + sys.argv[1])
create_schema(engine)
clock = FrozenClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
ledger = Ledger(engine, clock)
guard = SDKSocketGuard(EgressPolicy(build_allowlist(), ledger))
guard._resolver = lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
guard.install()
assert guard.installed
guard.install()
for host in ['example.com', '8.8.8.8']:
    try:
        socket.getaddrinfo(host, 443)
    except EgressDeniedError:
        pass
    else:
        raise AssertionError('denied lookup was allowed')
socket.getaddrinfo('data.alpaca.markets', 443)
sys.audit('socket.getaddrinfo', 'data.alpaca.markets', 443, 0, 0, 0)
sys.audit('socket.connect', None, ('8.8.8.8', 443))
try:
    sys.audit('socket.bind', None, ('127.0.0.1', 0))
except EgressDeniedError:
    pass
else:
    raise AssertionError('inbound bind was allowed')
ledger.verify_chain()
engine.dispose()
print('isolated SDK audit guard passed')
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, (tmp_path / "audit.sqlite3").as_posix()],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "isolated SDK audit guard passed"
