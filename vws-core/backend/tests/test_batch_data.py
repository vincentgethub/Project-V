"""DAT-05..08: installed SDK batches, incremental ledger cache and SIP bounds."""

import json
import threading
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import requests
from alpaca.data.historical import StockHistoricalDataClient
from sqlalchemy import Engine, select

from backend.core.config import Settings
from backend.core.database import DataSnapshot, SystemEvent, transaction
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.corporate_actions import CorporateActionEvidence, CorporateActionsResult
from backend.data.data_layer import (
    AsyncAlpacaMarketData,
    DataLayer,
    FakeMarketData,
)
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import MarketContext, MarketStatus, ProviderStatus
from backend.net import http
from backend.net.egress import EgressPolicy, build_allowlist
from backend.tests.test_async_reader import MovingClock

NY = ZoneInfo("America/New_York")


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def _bar(day: date) -> dict[str, Any]:
    return {
        "t": datetime.combine(day, datetime.min.time(), tzinfo=NY).isoformat(),
        "o": "100.00",
        "h": "101.00",
        "l": "99.00",
        "c": "100.00",
        "v": 100000,
    }


def _provider(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, clock: MovingClock
) -> tuple[AsyncAlpacaMarketData, AsyncAlpacaReader, list[dict[str, Any]]]:
    ledger = Ledger(engine, clock)
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state, sleep=clock.sleep)
    monkeypatch.setattr(http, "_policy", EgressPolicy(build_allowlist(), ledger))
    calls: list[dict[str, Any]] = []

    def response(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        assert method == "GET" and kwargs["verify"] is True
        assert kwargs["timeout"] == (5, 20) and kwargs["allow_redirects"] is False
        params = dict(kwargs["params"])
        calls.append(params)
        start = datetime.fromisoformat(params["start"]).astimezone(NY).date()
        end_instant = datetime.fromisoformat(params["end"])
        end = end_instant.astimezone(NY).date()
        days: list[date] = []
        cursor = start
        while cursor <= end:
            if calendar.is_session(cursor):
                days.append(cursor)
            cursor += timedelta(days=1)
        payload = {symbol: [_bar(day) for day in days] for symbol in params["symbols"].split(",")}
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps({"bars": payload, "next_page_token": None}).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    client = StockHistoricalDataClient("offline-key", "offline-secret", raw_data=True)
    return AsyncAlpacaMarketData(Settings(), reader, calendar, ledger, client), reader, calls


@pytest.mark.asyncio
async def test_DAT_05_fifty_symbols_plus_benchmarks_warm_scan_is_batched_incrementally(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, calls = _provider(engine, calendar, monkeypatch, clock)
    symbols = tuple(f"S{index:03}" for index in range(50))
    benchmarks = ("SPY", "XLK", "XLF")
    first = await provider.completed_daily_bars(symbols, date(2026, 9, 25), benchmarks=benchmarks)
    assert len(first.entries) == 53 and len(calls) == 1
    assert first.through == date(2026, 9, 29) and len(first.for_symbol("S000")) == 3
    again = await provider.completed_daily_bars(symbols, date(2026, 9, 25), benchmarks=benchmarks)
    assert again == first and len(calls) == 1
    clock.current = datetime(2026, 9, 30, 21, tzinfo=UTC)
    warm_start = len(calls)
    latest = await provider.completed_daily_bars(symbols, date(2026, 9, 25), benchmarks=benchmarks)
    assert len(calls) - warm_start == 1 <= 10
    assert datetime.fromisoformat(calls[-1]["start"]).astimezone(NY).date() == date(2026, 9, 30)
    assert latest.through == date(2026, 9, 30) and len(latest.for_symbol("S000")) == 4
    assert reader.bucket.available <= 179
    with transaction(engine) as session:
        records = list(session.scalars(select(DataSnapshot)).all())
        assert (
            len(records) == 106
            and sorted(record.bar_count for record in records) == [1] * 53 + [3] * 53
        )
    provider.ledger.verify_chain()


@pytest.mark.asyncio
async def test_DAT_05_cache_survives_provider_restart(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, _, calls = _provider(engine, calendar, monkeypatch, clock)
    expected = await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
    restarted = AsyncAlpacaMarketData(
        Settings(), provider.reader, calendar, provider.ledger, provider.client
    )
    assert await restarted.completed_daily_bars(("AAPL",), date(2026, 9, 25)) == expected
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "now,through",
    [
        (datetime(2026, 9, 29, 20, 29, 59, tzinfo=UTC), date(2026, 9, 28)),
        (datetime(2026, 9, 29, 20, 30, tzinfo=UTC), date(2026, 9, 29)),
        (datetime(2026, 11, 27, 18, 29, tzinfo=UTC), date(2026, 11, 25)),
        (datetime(2026, 11, 27, 18, 30, tzinfo=UTC), date(2026, 11, 27)),
    ],
)
async def test_DAT_07_close_delay_sip_clamp_and_dst_mapping(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    through: date,
) -> None:
    clock = MovingClock(now)
    provider, _, calls = _provider(engine, calendar, monkeypatch, clock)
    start = calendar.previous_sessions(through, 1)[0]
    result = await provider.completed_daily_bars(("AAPL",), start)
    assert result.through == through
    end = datetime.fromisoformat(calls[0]["end"])
    assert end <= now - timedelta(minutes=16) and end <= calendar.session_close(through)
    for bar in result.for_symbol("AAPL"):
        assert bar.session_date <= through and bar.timestamp.astimezone(NY).hour == 0


@pytest.mark.asyncio
async def test_DAT_05_missing_symbol_is_not_a_cached_pass(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, _ = _provider(engine, calendar, monkeypatch, clock)
    monkeypatch.setattr(provider.client, "get_stock_bars", lambda request: {"AAPL": []})
    with pytest.raises(DataIntegrityError):
        await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
    assert reader.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_DAT_06_installed_sdk_pagination_charges_every_physical_get(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, _ = _provider(engine, calendar, monkeypatch, clock)
    calls: list[dict[str, Any]] = []

    def page(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        params = dict(kwargs["params"])
        calls.append(params)
        first = params.get("page_token") is None
        days = [date(2026, 9, 25)] if first else [date(2026, 9, 28), date(2026, 9, 29)]
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps(
            {
                "bars": {name: [_bar(day) for day in days] for name in ("AAPL", "SPY")},
                "next_page_token": "offline-page-two" if first else None,
            }
        ).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", page)
    result = await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
    assert len(calls) == 2 and calls[1]["page_token"] == "offline-page-two"
    assert reader.bucket.available == 178 and len(result.for_symbol("AAPL")) == 3


@pytest.mark.asyncio
async def test_DAT_08_cache_verification_and_snapshot_writes_leave_loop_thread(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, _, _ = _provider(engine, calendar, monkeypatch, clock)
    main_thread = threading.get_ident()
    checked: list[int] = []
    chain = provider.ledger.verify_chain
    append = provider.ledger.append_in_session

    def verify() -> None:
        checked.append(threading.get_ident())
        assert threading.get_ident() != main_thread
        chain()

    def write(*args: Any, **kwargs: Any) -> Any:
        checked.append(threading.get_ident())
        assert threading.get_ident() != main_thread
        return append(*args, **kwargs)

    monkeypatch.setattr(provider.ledger, "verify_chain", verify)
    monkeypatch.setattr(provider.ledger, "append_in_session", write)
    await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
    assert len(checked) >= 4


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_DAT_02_batch_known_action_or_unavailable_retains_durable_gap_rule(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    available: bool,
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, calls = _provider(engine, calendar, monkeypatch, clock)
    actions = CorporateActionsResult(
        provider="FAKE",
        status=ProviderStatus.OK if available else ProviderStatus.UNAVAILABLE,
        fetched_at=clock.now(),
        symbols=("AAPL", "SPY"),
        process_start=date(2026, 9, 25),
        process_end=date(2026, 9, 29),
        actions=(
            CorporateActionEvidence(
                provider_id=UUID(int=1),
                kind="forward_splits",
                symbol="AAPL",
                effective_date=date(2026, 9, 28),
                process_date=date(2026, 9, 28),
                effective_date_field="ex_date",
            ),
        )
        if available
        else (),
        reason="synthetic action evidence",
    )
    request = requests.Session.request

    def gap(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        result = request(session, method, url, *args, **kwargs)
        payload = json.loads(result.content)
        for value in payload["bars"]["AAPL"][1:]:
            value.update(o="150.00", h="151.00", l="149.00", c="150.00")
        result._content = json.dumps(payload).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", gap)
    batch = await provider.completed_daily_bars(
        ("AAPL",), date(2026, 9, 25), corporate_actions=actions
    )
    expected = MarketStatus.OK if available else MarketStatus.SUSPECT
    assert batch.status_for("AAPL") == expected and batch.status_for("SPY") == MarketStatus.OK
    restarted = AsyncAlpacaMarketData(
        Settings(), reader, calendar, provider.ledger, provider.client
    )
    again = await restarted.completed_daily_bars(
        ("AAPL",), date(2026, 9, 25), corporate_actions=actions
    )
    assert again.status_for("AAPL") == expected and len(calls) == 1
    assert reader.state.current() == SystemState.RUNNING
    if not available:
        await reader.run(
            partial(provider._status.acknowledge_gap, "AAPL", "operator", "verified gap")
        )
        cleared = await restarted.completed_daily_bars(("AAPL",), date(2026, 9, 25))
        assert cleared.status_for("AAPL") == MarketStatus.OK
        with transaction(engine) as session:
            events = list(session.scalars(select(SystemEvent)).all())
        assert any("SUSPECT" in event.reason for event in events)
        assert any("acknowledged_through" in event.reason for event in events)


@pytest.mark.asyncio
async def test_DAT_05_in_progress_raw_legacy_snapshot_is_refetched_after_close(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    provider, reader, calls = _provider(engine, calendar, monkeypatch, clock)
    raw = tuple(
        provider._cached_bar(
            {
                "timestamp": datetime.combine(day, datetime.min.time(), tzinfo=NY).isoformat(),
                "open": "100.00",
                "high": "101.00",
                "low": "99.00",
                "close": "100.00",
                "volume": 100000,
            }
        )
        for day in (date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29))
    )
    context = MarketContext(
        last_price=Decimal("100.00"),
        last_price_ts=clock.now(),
        adv20_usd=Decimal("10000000.00"),
        status=MarketStatus.OK,
    )
    legacy = DataLayer(
        Settings(),
        FakeMarketData(raw, context, "AAPL"),
        calendar,
        clock,
        reader.state,
        provider.ledger,
    )
    assert len(legacy.completed_daily_bars("AAPL", date(2026, 9, 25))) == 2
    clock.current = datetime(2026, 9, 29, 21, tzinfo=UTC)
    result = await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25), benchmarks=())
    assert len(calls) == 1
    assert datetime.fromisoformat(calls[0]["start"]).astimezone(NY).date() == date(2026, 9, 29)
    assert result.through == date(2026, 9, 29) and len(result.for_symbol("AAPL")) == 3
    with transaction(engine) as session:
        records = list(session.scalars(select(DataSnapshot)).all())
    assert sorted(record.bar_count for record in records) == [1, 3]


@pytest.mark.asyncio
async def test_DAT_06_real_sdk_429_response_preserves_retry_after_and_shared_budget(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, calls = _provider(engine, calendar, monkeypatch, clock)
    request = requests.Session.request
    attempts = 0

    def rate_limit(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "3"
            response._content = b'{"code":429,"message":"synthetic rate limit"}'
            return response
        return request(session, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "request", rate_limit)
    await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
    assert attempts == 2 and len(calls) == 1
    assert clock.now() >= datetime(2026, 9, 29, 21, 0, 3, tzinfo=UTC)
    assert reader.bucket.available == 0 and reader.state.current() == SystemState.RUNNING


@pytest.mark.asyncio
async def test_DAT_08_expired_real_sdk_pagination_cannot_publish_cache_or_start_next_page(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    old, _, _ = _provider(engine, calendar, monkeypatch, clock)
    reader = AsyncAlpacaReader(clock, old.reader.state, max_inflight=1, deadline_seconds=0.15)
    provider = AsyncAlpacaMarketData(Settings(), reader, calendar, old.ledger, old.client)
    started, release = threading.Event(), threading.Event()
    pages = 0

    def slow_page(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        nonlocal pages
        pages += 1
        started.set()
        release.wait(2)
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps(
            {
                "bars": {name: [_bar(date(2026, 9, 25))] for name in ("AAPL", "SPY")},
                "next_page_token": "must-not-be-followed",
            }
        ).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", slow_page)
    try:
        with pytest.raises(ProviderError, match="deadline"):
            await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
        assert started.is_set() and reader._semaphore._value == 0
        assert reader.state.current() == SystemState.HALTED
        with transaction(engine) as session:
            assert not list(session.scalars(select(DataSnapshot)).all())
    finally:
        release.set()
        for _ in range(100):
            if not reader._workers:
                break
            await asyncio.sleep(0.005)
    assert pages == 1 and reader._semaphore._value == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quote_kind", ["valid", "future", "stale", "suspect", "arriving", "backwards", "session_change"]
)
async def test_DAT_08_quote_uses_shared_iex_budget_cached_adv_and_durable_status(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    quote_kind: str,
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, bar_calls = _provider(engine, calendar, monkeypatch, clock)
    request = requests.Session.request
    quote_calls: list[str] = []
    timestamp = calendar.session_close(date(2026, 9, 29))
    if quote_kind == "future":
        timestamp = clock.now() + timedelta(seconds=1)
    elif quote_kind == "stale":
        timestamp -= timedelta(hours=1)
    elif quote_kind in {"arriving", "backwards"}:
        clock.current = datetime(2026, 9, 30, 15, tzinfo=UTC)
        timestamp = clock.now() + timedelta(seconds=1)
    elif quote_kind == "session_change":
        clock.current = datetime(2026, 9, 30, 20, 29, 59, tzinfo=UTC)

    def observed(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        if "/bars" in url:
            return request(session, method, url, *args, **kwargs)
        quote_calls.append(url)
        if "/trades/" in url:
            if quote_kind in {"arriving", "session_change"}:
                clock.current += timedelta(seconds=2)
            elif quote_kind == "backwards":
                clock.current -= timedelta(seconds=1)
        assert kwargs["params"]["feed"] == "iex"
        key = "quotes" if "/quotes/" in url else "trades"
        payload = (
            {"t": timestamp.isoformat(), "bp": "99.00", "ap": "101.00"}
            if key == "quotes"
            else {"t": timestamp.isoformat(), "p": "100.00"}
        )
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps({key: {"AAPL": payload}}).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", observed)
    batch = await provider.completed_daily_bars(("AAPL",), date(2026, 8, 20))
    if quote_kind == "suspect":
        await reader.run(
            partial(provider._status._record_symbol_status, "AAPL", "SUSPECT", None, "new gap")
        )
    if quote_kind in {"future", "stale", "backwards", "session_change"}:
        with pytest.raises((DataIntegrityError, ProviderError)):
            await provider.latest_market("AAPL", batch)
        assert reader.state.current() == SystemState.HALTED
    else:
        context = await provider.latest_market("AAPL", batch)
        assert context.last_price == Decimal("100.00")
        assert context.last_price_ts == timestamp
        assert context.adv20_usd == Decimal("10000000.000000")
        assert context.status == (
            MarketStatus.SUSPECT if quote_kind == "suspect" else MarketStatus.OK
        )
    assert len(bar_calls) == 1 and len(quote_calls) == 2
    assert reader.bucket.available == 177
