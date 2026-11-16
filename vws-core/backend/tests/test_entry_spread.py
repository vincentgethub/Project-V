"""OPS-SPREAD: pre-entry quoted spread gate refuses wide, missing, bad or stale quotes."""

import ast
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import requests
from pydantic import ValidationError
from sqlalchemy import Engine

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError, ExecutionDisabledError
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.data.top_of_book import (
    DEFAULT_MAX_ENTRY_SPREAD,
    TopOfBook,
    spread_refusal,
)
from backend.execution.entry_spread import EntrySpreadGate
from backend.tests.test_async_reader import MovingClock
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor
from backend.tests.test_batch_data import _provider
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness
PROJECT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)


def top(bid: str, ask: str, *, age: int = 1, symbol: str = "SPY") -> TopOfBook:
    return TopOfBook(
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        quoted_at=NOW - timedelta(seconds=age),
    )


def refusal(quote: TopOfBook | None, limit: Decimal = DEFAULT_MAX_ENTRY_SPREAD) -> str | None:
    return spread_refusal(quote, NOW, max_spread=limit, max_age_seconds=60)


def test_OPS_SPREAD_default_is_ten_basis_points_and_settings_use_it() -> None:
    assert DEFAULT_MAX_ENTRY_SPREAD == Decimal("0.0010")
    assert Settings().max_entry_spread == DEFAULT_MAX_ENTRY_SPREAD
    assert Settings.DECIMAL_BOUNDS["max_entry_spread"] == (Decimal("0.0001"), Decimal("0.0050"))


@pytest.mark.parametrize("bad", ["0", "-0.001", "0.00009", "0.0051", "1", "NaN", "Infinity"])
def test_OPS_SPREAD_bound_cannot_be_disabled_or_nonsense(bad: str) -> None:
    with pytest.raises(ValidationError):
        Settings(max_entry_spread=Decimal(bad))


@pytest.mark.parametrize("bad", [0.001, True, None, "ten"])
def test_OPS_SPREAD_bound_rejects_inexact_values(bad: Any) -> None:
    with pytest.raises(ValidationError):
        Settings(max_entry_spread=bad)


@pytest.mark.parametrize("good", ["0.0001", "0.0005", "0.0050"])
def test_OPS_SPREAD_bound_accepts_its_inclusive_range(good: str) -> None:
    assert Settings(max_entry_spread=Decimal(good)).max_entry_spread == Decimal(good)


def test_OPS_SPREAD_liquid_quotes_pass() -> None:
    assert refusal(top("600.00", "600.01")) is None
    assert refusal(top("185.50", "185.52")) is None
    # Exactly at the bound passes: (ask - bid) / mid == 10 bps.
    assert refusal(top("99.95", "100.05")) is None


def test_OPS_SPREAD_spread_just_over_bound_refuses_with_basis_points() -> None:
    assert refusal(top("99.94", "100.05")) == (
        "quoted spread 11.0 bps exceeds the 10.0 bps entry bound"
    )
    assert refusal(top("20.00", "20.10")) == (
        "quoted spread 49.9 bps exceeds the 10.0 bps entry bound"
    )
    assert refusal(top("20.00", "20.10"), Decimal("0.0050")) is None


def test_OPS_SPREAD_missing_quote_refuses() -> None:
    assert refusal(None) == "bid/ask quote is missing"


@pytest.mark.parametrize(("bid", "ask"), [("0", "100.00"), ("100.00", "0"), ("0", "0")])
def test_OPS_SPREAD_zero_sided_quote_refuses(bid: str, ask: str) -> None:
    assert refusal(top(bid, ask)) == "bid/ask quote has a zero side"


def test_OPS_SPREAD_crossed_and_locked_quotes_refuse() -> None:
    assert refusal(top("100.02", "100.01")) == "bid/ask quote is crossed"
    assert refusal(top("100.01", "100.01")) == "bid/ask quote is locked"


def test_OPS_SPREAD_stale_and_future_quotes_refuse() -> None:
    assert refusal(top("100.00", "100.01", age=60)) is None
    assert refusal(top("100.00", "100.01", age=61)) == "bid/ask quote is stale"
    assert refusal(top("100.00", "100.01", age=-1)) == "bid/ask quote is timestamped in the future"


@pytest.mark.parametrize(
    "fields",
    [
        {"bid": Decimal("-0.01")},
        {"ask": Decimal("-0.01")},
        {"bid": Decimal("NaN")},
        {"symbol": "spy"},
        {"quoted_at": datetime(2026, 11, 16, 15)},
        {"extra": 1},
    ],
)
def test_OPS_SPREAD_top_of_book_model_rejects_invalid_evidence(fields: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "symbol": "SPY",
        "bid": Decimal("1.00"),
        "ask": Decimal("1.01"),
        "quoted_at": NOW,
    }
    values.update(fields)
    with pytest.raises(ValidationError):
        TopOfBook(**values)


@pytest.mark.parametrize("bad", ["-0.001", "0", "0.0051"])
def test_OPS_SPREAD_refusal_rejects_an_out_of_range_bound(bad: str) -> None:
    with pytest.raises(DataIntegrityError, match="entry spread bound"):
        spread_refusal(top("1.00", "1.01"), NOW, max_spread=Decimal(bad), max_age_seconds=60)


@pytest.mark.parametrize("bad", [0, 301, True])
def test_OPS_SPREAD_refusal_rejects_an_out_of_range_age(bad: Any) -> None:
    with pytest.raises(DataIntegrityError, match="quote age bound"):
        spread_refusal(top("1.00", "1.01"), NOW, max_spread=Decimal("0.001"), max_age_seconds=bad)


class Quotes:
    def __init__(self, quote: TopOfBook) -> None:
        self.quote = quote
        self.symbols: list[str] = []

    async def __call__(self, symbol: str) -> TopOfBook:
        self.symbols.append(symbol)
        return self.quote


def quote_for(h: Harness, bid: str, ask: str, symbol: str = "NVDA") -> TopOfBook:
    return TopOfBook(symbol=symbol, bid=Decimal(bid), ask=Decimal(ask), quoted_at=h.clock.now())


def gate(h: Harness, quotes: Quotes, calls: list[UUID]) -> EntrySpreadGate:
    async def realtime(proposal_id: UUID) -> None:
        calls.append(proposal_id)

    return EntrySpreadGate(h.settings, h.state.engine, h.clock, quotes, realtime)


@pytest.mark.asyncio
async def test_OPS_SPREAD_gate_runs_realtime_first_then_reads_its_own_quote(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    quotes = Quotes(quote_for(harness, "100.00", "100.05"))
    calls: list[UUID] = []
    await gate(harness, quotes, calls)(alert.proposal_id)
    assert calls == [alert.proposal_id] and quotes.symbols == ["NVDA"]


@pytest.mark.asyncio
async def test_OPS_SPREAD_gate_refuses_wide_spread_without_halting(harness: Harness) -> None:
    alert = await deliver(harness)
    quotes = Quotes(quote_for(harness, "100.00", "100.50"))
    with pytest.raises(ExecutionDisabledError) as caught:
        await gate(harness, quotes, [])(alert.proposal_id)
    assert str(caught.value) == (
        "Spread gate blocks entry: quoted spread 49.9 bps exceeds the 10.0 bps entry bound"
    )
    assert harness.state.current() == SystemState.RUNNING


@pytest.mark.asyncio
async def test_OPS_SPREAD_gate_refuses_realtime_failure_before_quote(harness: Harness) -> None:
    alert = await deliver(harness)
    quotes = Quotes(quote_for(harness, "100.00", "100.01"))

    async def blocked(_proposal_id: UUID) -> None:
        raise ExecutionDisabledError("RT blocked")

    built = EntrySpreadGate(harness.settings, harness.state.engine, harness.clock, quotes, blocked)
    with pytest.raises(ExecutionDisabledError, match="RT blocked"):
        await built(alert.proposal_id)
    assert quotes.symbols == []


@pytest.mark.asyncio
async def test_OPS_SPREAD_gate_requires_a_bound_opening_proposal_and_matching_quote(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    with pytest.raises(DataIntegrityError, match="bound opening proposal"):
        await gate(harness, Quotes(quote_for(harness, "1.00", "1.01")), [])(uuid4())
    with pytest.raises(DataIntegrityError, match="quote symbol differs"):
        await gate(harness, Quotes(quote_for(harness, "1.00", "1.01", "AMD")), [])(
            alert.proposal_id
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(("ask", "admitted"), [("100.05", True), ("100.50", False)])
async def test_OPS_SPREAD_executor_entry_is_refused_on_wide_spread_before_any_order(
    harness: Harness, ask: str, admitted: bool
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    quotes = Quotes(quote_for(harness, "100.00", ask))
    built.realtime_entry = gate(harness, quotes, [])
    if admitted:
        await built.enter(alert.proposal_id)
        assert client.posts and client.posts[0]["side"] == "buy"
    else:
        with pytest.raises(ExecutionDisabledError, match="Spread gate blocks entry"):
            await built.enter(alert.proposal_id)
        assert client.posts == []
    await built.close()


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"SPY": {"t": "2026-11-16T14:59:59Z", "bp": "600.00", "ap": "600.01"}}, "600.01"),
        ({"SPY": {"t": "2026-11-16T14:59:59Z", "bp": 0, "ap": "600.01"}}, "600.01"),
    ],
)
async def test_OPS_SPREAD_data_layer_reads_one_iex_latest_quote(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    expected: str,
) -> None:
    clock = MovingClock(NOW)
    provider, reader, _ = _provider(engine, calendar, monkeypatch, clock)
    urls: list[str] = []

    def response(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        assert method == "GET" and "/quotes/latest" in url
        assert kwargs["params"]["feed"] == "iex" and kwargs["params"]["symbols"] == "SPY"
        urls.append(url)
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps({"quotes": payload}).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    quote = await provider.top_of_book("SPY")
    assert len(urls) == 1
    assert quote.symbol == "SPY" and quote.ask == Decimal(expected)
    assert quote.quoted_at == datetime(2026, 11, 16, 14, 59, 59, tzinfo=UTC)
    assert reader.state.current() == SystemState.RUNNING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"AMD": {"t": "2026-11-16T14:59:59Z", "bp": "1.00", "ap": "1.01"}},
        {"SPY": {"t": "2026-11-16T14:59:59Z", "bp": "-1.00", "ap": "1.01"}},
        {"SPY": {"t": "2026-11-16T14:59:59Z", "bp": 1.5, "ap": "1.01"}},
        {"SPY": {"t": "2026-11-16T14:59:59", "bp": "1.00", "ap": "1.01"}},
        {"SPY": ["not", "a", "quote"]},
    ],
)
async def test_OPS_SPREAD_data_layer_malformed_quote_fails_closed_and_halts(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    clock = MovingClock(NOW)
    provider, reader, _ = _provider(engine, calendar, monkeypatch, clock)

    def response(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps({"quotes": payload}).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    with pytest.raises(DataIntegrityError):
        await provider.top_of_book("SPY")
    assert reader.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_OPS_SPREAD_data_layer_rejects_invalid_symbol_before_any_read(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, reader, calls = _provider(engine, calendar, monkeypatch, MovingClock(NOW))
    with pytest.raises(DataIntegrityError):
        await provider.top_of_book("spy")
    assert calls == []


def test_OPS_SPREAD_host_runtime_wraps_the_realtime_entry_hook() -> None:
    tree = ast.parse((PROJECT / "vws/runtime_cli.py").read_text(encoding="utf-8"))
    hooks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "realtime_entry"
    ]
    assert len(hooks) == 1
    assert ast.unparse(hooks[0].value) == (
        "EntrySpreadGate(settings, state.engine, clock, market.top_of_book, realtime.require_entry)"
    )
