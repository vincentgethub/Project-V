"""WZ/SEC: real guarded HTTP factory with in-memory transport only."""

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EgressDeniedError,
    ProviderError,
)
from backend.core.ledger import Ledger
from backend.core.logging import redact
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import GuardedAsyncClient, make_client
from backend.ops import read_checks as module
from backend.ops.read_checks import ReadChecksClient
from backend.tests.test_broker_clock import MovingClock


def client(
    engine: Engine,
    clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> ReadChecksClient:
    policy = EgressPolicy(build_allowlist(), Ledger(engine, clock))

    def factory(purpose: str, **kwargs: Any) -> GuardedAsyncClient:
        return make_client(purpose, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module, "make_client", factory)
    return ReadChecksClient(policy, clock)


def account() -> dict[str, object]:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "status": "ACTIVE",
        "buying_power": "1234.56",
        "equity": "1234.56",
        "currency": "USD",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }


@pytest.mark.asyncio
async def test_DAT_06_read_checks_charge_only_physical_alpaca_requests(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    charges: list[str] = []

    async def charge() -> None:
        charges.append("alpaca")

    source = client(
        engine,
        clock,
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={"ok": True, "result": {"is_bot": True}}
            if request.url.host == "api.telegram.org"
            else account(),
        ),
    )
    source._alpaca_request_hook = charge
    await source.paper_account(SecretStr("TEST_ONLY_KEY"), SecretStr("TEST_ONLY_SECRET"))
    await source.telegram(SecretStr("123:TEST_ONLY_FAKE_TOKEN"), "getMe")
    assert charges == ["alpaca"]


@pytest.mark.asyncio
async def test_WZ_paper_only_get_paths_and_exact_money(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    routes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "paper-api.alpaca.markets"
        assert request.headers["APCA-API-KEY-ID"] == "TEST_ONLY_PAPER_KEY"
        assert request.headers["APCA-API-SECRET-KEY"] == "TEST_ONLY_PAPER_SECRET"
        routes.append(request.url.path)
        data: object = (
            account()
            if request.url.path.endswith("account")
            else {"symbol": "AAPL", "class": "us_equity", "status": "active", "tradable": True}
            if "assets" in request.url.path
            else []
        )
        return httpx.Response(200, json=data)

    source = client(engine, clock, monkeypatch, handler)
    key, secret = SecretStr("TEST_ONLY_PAPER_KEY"), SecretStr("TEST_ONLY_PAPER_SECRET")
    checked = await source.paper_account(key, secret)
    assert checked.buying_power == Decimal("1234.56") and checked.equity == Decimal("1234.56")
    await source.asset("AAPL", key, secret)
    settings = Settings(_env_file=None, broker_account_type="CASH")
    await source.broker_clock(settings, key, secret)
    await source.broker_calendar(settings, key, secret, date(2026, 10, 7), date(2026, 10, 20))
    assert routes == ["/v2/account", "/v2/assets/AAPL", "/v2/clock", "/v2/calendar"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [b'{"id":1,"id":2}', b'{"value":NaN}', b'{"value":Infinity}', b"not json", b"[]"]
)
async def test_WZ_malformed_json_never_validates_account(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    source = client(engine, clock, monkeypatch, lambda _: httpx.Response(200, content=body))
    with pytest.raises(DataIntegrityError):
        await source.paper_account(SecretStr("TEST_ONLY_KEY"), SecretStr("TEST_ONLY_SECRET"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("trading_blocked", "false"),
        ("buying_power", "nan"),
        ("equity", "0"),
        ("currency", "EUR"),
        ("id", "bad"),
        ("status", "unknown"),
    ],
)
async def test_WZ_strict_account_boundaries(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    data = account()
    data[field] = value
    source = client(engine, clock, monkeypatch, lambda _: httpx.Response(200, json=data))
    with pytest.raises(DataIntegrityError):
        await source.paper_account(SecretStr("TEST_ONLY_KEY"), SecretStr("TEST_ONLY_SECRET"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("tradable", "true"),
        ("tradable", False),
        ("class", "crypto"),
        ("status", "inactive"),
        ("symbol", "MSFT"),
    ],
)
async def test_WZ_asset_must_be_matching_active_tradable_us_equity(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    data: dict[str, object] = {
        "symbol": "AAPL",
        "class": "us_equity",
        "status": "active",
        "tradable": True,
    }
    data[field] = value
    source = client(engine, clock, monkeypatch, lambda _: httpx.Response(200, json=data))
    with pytest.raises(DataIntegrityError):
        await source.asset("AAPL", SecretStr("TEST_ONLY_KEY"), SecretStr("TEST_ONLY_SECRET"))


@pytest.mark.asyncio
async def test_WZ_telegram_routes_are_read_only_and_updates_are_not_acknowledged(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = SecretStr("123:" + "TEST_ONLY_NOT_A_CREDENTIAL_" * 2)
    routes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "api.telegram.org"
        routes.append(request.url.path.rsplit("/", 1)[-1])
        assert "offset" not in request.url.params
        if routes[-1] == "getUpdates":
            assert request.url.params["limit"] == "100" and request.url.params["timeout"] == "0"
        return httpx.Response(200, json={"ok": True, "result": {}})

    source = client(engine, clock, monkeypatch, handler)
    await source.telegram(token, "getMe")
    await source.telegram(token, "getUpdates")
    await source.telegram(token, "getWebhookInfo")
    await source.telegram(token, "getChat", chat_id=123)
    assert routes == ["getMe", "getUpdates", "getWebhookInfo", "getChat"]
    assert token.get_secret_value() not in str(
        redact({"url": "https://api.telegram.org/bot" + token.get_secret_value() + "/getMe"})
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_WZ_provider_rejection_stays_unverified_no_retry(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(status)
        return httpx.Response(status, text="untrusted provider error")

    source = client(engine, clock, monkeypatch, handler)
    with pytest.raises(ProviderError) as failure:
        await source.paper_account(SecretStr("TEST_ONLY_KEY"), SecretStr("TEST_ONLY_SECRET"))
    assert calls == [status] and "untrusted" not in str(failure.value)


@pytest.mark.asyncio
async def test_SEC_authenticated_redirect_refused_before_another_request(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://api.alpaca.markets/v2/account"})

    source = client(engine, clock, monkeypatch, handler)
    with pytest.raises(EgressDeniedError):
        await source.paper_account(SecretStr("TEST_ONLY_KEY"), SecretStr("TEST_ONLY_SECRET"))
    assert calls == ["paper-api.alpaca.markets"]


@pytest.mark.asyncio
async def test_WZ_clock_does_not_contact_live_or_unbounded_calendar(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid binding must fail before any request")

    source = client(engine, clock, monkeypatch, handler)
    key, secret = SecretStr("TEST_ONLY_KEY"), SecretStr("TEST_ONLY_SECRET")
    live = Settings(
        _env_file=None,
        broker_account_type="CASH",
        paper_trading=False,
        live_trading_enabled=True,
        live_trading_confirm="I_ACCEPT_REAL_MONEY_RISK",
        broker_api_key=key,
        broker_secret_key=secret,
    )
    with pytest.raises(ConfigurationError):
        await source.broker_clock(live, key, secret)
    with pytest.raises(ConfigurationError):
        await source.broker_calendar(live, key, secret, date(2026, 10, 7), date(2026, 10, 20))
    paper = Settings(_env_file=None, broker_account_type="CASH")
    with pytest.raises(ConfigurationError):
        await source.broker_calendar(paper, key, secret, date(2026, 10, 7), date(2027, 10, 20))


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [".", "NaN", "-1", "Infinity"])
async def test_RT_07_fred_unavailable_or_invalid_observation_is_not_verified(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    source = client(
        engine,
        clock,
        monkeypatch,
        lambda _: httpx.Response(
            200, json={"observations": [{"date": "2026-10-06", "value": value}]}
        ),
    )
    with pytest.raises(DataIntegrityError):
        await source.fred(SecretStr("TEST_ONLY_NOT_A_CREDENTIAL"))


@pytest.mark.asyncio
async def test_RT_07_fred_rate_reservations_are_atomic_failures_consume_and_reset(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.stlouisfed.org" and request.method == "GET"
        assert request.url.params["series_id"] == "VIXCLS"
        calls.append(1)
        return httpx.Response(500)

    source = client(engine, clock, monkeypatch, handler)
    moving = MovingClock(clock.now())
    source.clock = moving
    key = SecretStr("TEST_ONLY_NOT_A_CREDENTIAL")
    outcomes = await asyncio.gather(*(source.fred(key) for _ in range(125)), return_exceptions=True)
    assert len(calls) == 120 and all(isinstance(item, ProviderError) for item in outcomes)
    moving.current += timedelta(seconds=60)
    with pytest.raises(ProviderError):
        await source.fred(key)
    assert len(calls) == 121
    moving.current -= timedelta(seconds=1)
    with pytest.raises(DataIntegrityError, match="backward"):
        await source.fred(key)


@pytest.mark.asyncio
async def test_SEC_73_open_order_report_uses_bound_read_only_finite_request(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "paper-api.alpaca.markets"
        assert request.url.path.endswith("/orders")
        assert dict(request.url.params) == {"status": "open", "limit": "500", "nested": "true"}
        return httpx.Response(200, json=[])

    source = client(engine, clock, monkeypatch, handler)
    settings = Settings(
        _env_file=None,
        broker_account_type="CASH",
        broker_api_key=SecretStr("TEST_ONLY_PAPER"),
        broker_secret_key=SecretStr("TEST_ONLY_SECRET"),
    )
    assert await source.open_orders(settings) == []
    with pytest.raises(ConfigurationError, match="Live order reads"):
        await source.open_orders(
            settings.model_copy(
                update={
                    "paper_trading": False,
                    "live_trading_enabled": True,
                    "live_trading_confirm": "I_ACCEPT_REAL_MONEY_RISK",
                }
            )
        )
