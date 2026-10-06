"""FA-02/09: exact public evidence, rate/cache boundaries and provider failures."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import Engine

from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState
from backend.data.sec_edgar import (
    RequestHook,
    SecEdgarProvider,
    SecPayload,
    SecRequestPacer,
    exact_json,
)
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import GuardedAsyncClient, make_client
from backend.tests.test_async_reader import MovingClock


def provider(
    engine: Engine, replies: list[tuple[int, object, dict[str, str]]]
) -> tuple[SecEdgarProvider, MovingClock, list[httpx.Request]]:
    clock = MovingClock(datetime(2026, 10, 5, 20, tzinfo=UTC))
    ledger = Ledger(engine, clock)
    policy = EgressPolicy(build_allowlist(), ledger)
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["User-Agent"] == "Project V Test Owner owner@example.com"
        status, body, headers = replies.pop(0)
        return httpx.Response(status, json=body, headers=headers)

    def factory(hook: RequestHook) -> GuardedAsyncClient:
        return make_client(
            "sec-edgar", policy=policy, transport=httpx.MockTransport(handle), request_hook=hook
        )

    result = SecEdgarProvider(
        Settings(sec_user_agent="Project V Test Owner owner@example.com"),
        ledger,
        client_factory=factory,
        sleep=clock.sleep,
    )
    return result, clock, calls


def tickers() -> dict[str, object]:
    return {"0": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft"}}


@pytest.mark.asyncio
async def test_FA_02_cache_TTL_boundaries_and_detached_exact_payload(engine: Engine) -> None:
    replies: list[tuple[int, object, dict[str, str]]] = [
        (200, tickers(), {}),
        (200, {"cik": 789019, "facts": {}}, {}),
        (200, {"cik": 789019, "facts": {"new": "evidence"}}, {}),
        (200, tickers(), {}),
    ]
    source, clock, calls = provider(engine, replies)
    first = await source.companyfacts("MSFT")
    assert len(calls) == 2
    first.parsed()["cik"] = 1
    assert first.parsed()["cik"] == 789019
    assert await source.companyfacts("MSFT") == first and len(calls) == 2
    clock.current = first.fetched_at + timedelta(hours=24)
    refreshed = await source.companyfacts("MSFT")
    assert len(calls) == 3 and refreshed.data_sha256 != first.data_sha256
    clock.current = source._cache[("TICKERS", None)].fetched_at + timedelta(days=7)
    assert await source.cik_for("MSFT") == "0000789019" and len(calls) == 4
    source.ledger.verify_chain()


@pytest.mark.asyncio
async def test_FA_02_pacer_serializes_twenty_concurrent_physical_requests() -> None:
    import asyncio

    clock = MovingClock(datetime(2026, 10, 5, 20, tzinfo=UTC))
    gate = SecRequestPacer(clock, sleep=clock.sleep)
    instants: list[datetime] = []

    async def request() -> None:
        await gate.acquire()
        instants.append(clock.now())

    await asyncio.gather(*(request() for _ in range(20)))
    assert all(
        right - left >= timedelta(microseconds=125000)
        for left, right in zip(instants, instants[1:], strict=False)
    )
    assert instants[-1] - instants[0] == timedelta(microseconds=19 * 125000)


@pytest.mark.asyncio
async def test_FA_02_every_redirect_is_rate_charged(engine: Engine) -> None:
    source, clock, calls = provider(
        engine,
        [
            (302, {}, {"Location": "https://www.sec.gov/files/verified-tickers.json"}),
            (200, tickers(), {}),
        ],
    )
    start = clock.now()
    assert await source.cik_for("MSFT") == "0000789019"
    assert len(calls) == 2 and clock.now() - start == timedelta(microseconds=125000)


@pytest.mark.asyncio
async def test_FA_02_429_retry_after_preserves_cached_identity(engine: Engine) -> None:
    source, clock, calls = provider(engine, [(429, {}, {"Retry-After": "2"}), (200, tickers(), {})])
    start = clock.now()
    assert await source.cik_for("MSFT") == "0000789019"
    assert clock.now() - start == timedelta(seconds=2) and len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", ["-1", "31", "invalid", "1.5"])
async def test_FA_02_unbounded_retry_after_is_unavailable(engine: Engine, delay: str) -> None:
    source, _, calls = provider(engine, [(429, {}, {"Retry-After": delay})])
    with pytest.raises(ProviderError):
        await source.cik_for("MSFT")
    assert len(calls) == 1 and not source._cache


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 401])
async def test_FA_02_expected_service_denial_never_supplies_evidence(
    engine: Engine, status: int
) -> None:
    source, _, calls = provider(engine, [(status, {}, {})])
    with pytest.raises(ProviderError):
        await source.companyfacts("MSFT")
    assert len(calls) == 1 and not source._cache


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"0": "bad"},
        {"0": {"ticker": "MSFT", "cik_str": True}},
        {"0": {"ticker": "MSFT", "cik_str": 0}},
    ],
)
async def test_FA_02_invalid_ticker_identity_durably_halts(engine: Engine, body: Any) -> None:
    source, _, _ = provider(engine, [(200, body, {})])
    with pytest.raises(DataIntegrityError):
        await source.cik_for("MSFT")
    assert source.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_FA_02_forged_future_cache_durably_halts(engine: Engine) -> None:
    source, clock, _ = provider(engine, [(200, tickers(), {})])
    await source.cik_for("MSFT")
    cached = source._cache[("TICKERS", None)]
    source._cache[("TICKERS", None)] = cached.model_copy(
        update={"fetched_at": clock.now() + timedelta(seconds=1)}
    )
    with pytest.raises(DataIntegrityError):
        await source.cik_for("MSFT")
    assert source.state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "raw", [b"", b"[]", b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1,"x":2}', b"invalid"]
)
def test_FA_02_exact_json_refuses_ambiguous_or_nonfinite_data(raw: bytes) -> None:
    with pytest.raises(DataIntegrityError):
        exact_json(raw)


def test_FA_02_raw_hash_and_CIK_are_revalidated() -> None:
    raw = json.dumps({"cik": 789019, "amount": "100"}).encode()
    fields: dict[str, Any] = {
        "kind": "COMPANYFACTS",
        "cik": "0000789019",
        "fetched_at": datetime(2026, 10, 5, tzinfo=UTC),
        "raw": raw,
        "data_sha256": hashlib.sha256(raw).hexdigest(),
    }
    good = SecPayload(**fields)
    with pytest.raises(ValidationError):
        SecPayload.model_validate(good.model_copy(update={"data_sha256": "a" * 64}))
    with pytest.raises(ValidationError):
        SecPayload(**{**fields, "cik": "0000000001"})
    assert exact_json(b'{"amount":0.1}')["amount"].as_tuple().digits == (1,)


def test_FA_02_missing_contact_refuses_provider(engine: Engine) -> None:
    with pytest.raises(ConfigurationError):
        SecEdgarProvider(Settings(), Ledger(engine, MovingClock(datetime(2026, 10, 5, tzinfo=UTC))))
