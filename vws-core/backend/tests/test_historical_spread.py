"""CM-01: real pinned SDK requests/pagination with fake offline HTTP quotes."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import requests
from pydantic import ValidationError
from sqlalchemy import Engine

from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.historical_spread import (
    HistoricalSpreadSampler,
    SpreadMeasurement,
    _measure,
    _window,
)
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import ProviderStatus
from backend.evaluation.costs import CostContext, half_spread
from backend.tests.test_async_reader import MovingClock
from backend.tests.test_batch_data import _provider

DAY = date(2026, 9, 29)
NOW = datetime(2026, 9, 29, 21, tzinfo=UTC)
D = Decimal


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 1, 1), end=date(2027, 1, 31))


def quote(minute: int = 45, **values: Any) -> dict[str, Any]:
    return {"t": f"2026-09-29T19:{minute}:00Z", "bp": "99.99", "ap": "100.01", **values}


@pytest.mark.asyncio
async def test_CM_01_sdk_multi_symbol_sip_window_pagination_budget_and_exact_median(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, reader, _ = _provider(engine, calendar, monkeypatch, MovingClock(NOW))
    calls: list[dict[str, Any]] = []

    def response(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        assert method == "GET" and url == "https://data.alpaca.markets/v2/stocks/quotes"
        assert kwargs["verify"] is True and kwargs["timeout"] == (5, 20)
        assert kwargs["allow_redirects"] is False
        params = dict(kwargs["params"])
        calls.append(params)
        assert params["feed"] == "sip" and params["symbols"] == "AAPL,SPY"
        assert datetime.fromisoformat(params["start"]) == _window(DAY)[0]
        assert datetime.fromisoformat(params["end"]) == _window(DAY)[1]
        first = params.get("page_token") is None
        data = (
            {"AAPL": [quote(), quote(46, bp="99.98", ap="100.02")], "SPY": []}
            if first
            else {
                "AAPL": [quote(47, bp="99.97", ap="100.03")],
                "SPY": [quote(48), quote(49, bp="99.98", ap="100.02")],
            }
        )
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps(
            {"quotes": data, "next_page_token": "next" if first else None}
        ).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    observed = await HistoricalSpreadSampler(provider).sample(("AAPL", "SPY"), DAY)
    assert len(calls) == 2 and calls[1]["page_token"] == "next" and reader.bucket.available == 178
    assert observed[0].samples == 3 and observed[0].half_spread_bps == D("2.000000")
    assert observed[1].samples == 2 and observed[1].half_spread_bps == D("1.500000")
    assert half_spread(
        CostContext(
            median_dollar_volume_20=D(500_000_000),
            atr14=D(1),
            measured_half_spread_bps=observed[1].half_spread_bps,
        )
    ) == (D(2), ())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "now,session",
    [
        (datetime(2026, 9, 29, 20, 5, 59, tzinfo=UTC), DAY),
        (datetime(2026, 11, 27, 22, tzinfo=UTC), date(2026, 11, 27)),
    ],
)
async def test_CM_01_incomplete_delay_or_early_close_uses_floor_without_get(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    session: date,
) -> None:
    provider, _, calls = _provider(engine, calendar, monkeypatch, MovingClock(now))
    result = await HistoricalSpreadSampler(provider).sample(("AAPL",), session)
    assert result[0].status == ProviderStatus.UNAVAILABLE and result[0].half_spread_bps is None
    assert not calls and provider.reader.state.current() == SystemState.RUNNING


@pytest.mark.parametrize("raw", [{}, {"AAPL": []}])
def test_CM_01_missing_samples_are_unavailable_not_zero_spread(raw: dict[str, Any]) -> None:
    result = _measure(raw, ("AAPL",), DAY, NOW)[0]
    assert result.status == ProviderStatus.UNAVAILABLE and result.samples == 0
    assert result.half_spread_bps is None


@pytest.mark.parametrize(
    "raw",
    [
        [],
        {"WRONG": []},
        {"AAPL": None},
        {"AAPL": [None]},
        {"AAPL": [quote(bp=99.99)]},
        {"AAPL": [quote(bp="100.02")]},
        {"AAPL": [quote(bp="0")]},
        {"AAPL": [quote(bp="99.999")]},
        {"AAPL": [quote(t="2026-09-29T19:44:59Z")]},
        {"AAPL": [quote(t="2026-09-29T19:50:01Z")]},
        {"AAPL": [quote(46), quote(45)]},
        {"AAPL": [quote(t="bad")]},
        {"AAPL": [quote()] * 10001},
    ],
)
def test_CM_01_bad_quote_evidence_is_typed(raw: object) -> None:
    with pytest.raises(DataIntegrityError):
        _measure(raw, ("AAPL",), DAY, NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "symbols,session",
    [
        ((), DAY),
        (("AAPL", "AAPL"), DAY),
        (("aapl",), DAY),
        (("AAPL",), date(2026, 10, 1)),
        (("AAPL",), date(2026, 9, 27)),
        (["AAPL"], DAY),
    ],
)
async def test_CM_01_invalid_requests_halt_before_network(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    symbols: Any,
    session: date,
) -> None:
    provider, _, calls = _provider(engine, calendar, monkeypatch, MovingClock(NOW))
    with pytest.raises(DataIntegrityError):
        await HistoricalSpreadSampler(provider).sample(symbols, session)
    assert not calls and provider.reader.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_CM_01_bad_sdk_response_halts_durably(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, _, _ = _provider(engine, calendar, monkeypatch, MovingClock(NOW))
    monkeypatch.setattr(
        provider.client, "get_stock_quotes", lambda request: {"AAPL": [quote(bp="101")]}
    )
    with pytest.raises(DataIntegrityError):
        await HistoricalSpreadSampler(provider).sample(("AAPL",), DAY)
    assert provider.reader.state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "change",
    [
        {"samples": 0},
        {"half_spread_bps": None},
        {"half_spread_bps": 1.0},
        {"window_start": datetime(2026, 9, 29, 19, 44, tzinfo=UTC)},
        {"fetched_at": datetime(2026, 9, 29, 20, 5, 59, tzinfo=UTC)},
        {"status": ProviderStatus.UNAVAILABLE},
    ],
)
def test_CM_01_measurement_schema_cannot_forge_available_evidence(change: dict[str, Any]) -> None:
    valid = _measure({"AAPL": [quote()]}, ("AAPL",), DAY, NOW)[0]
    with pytest.raises(ValidationError):
        SpreadMeasurement.model_validate(valid.model_copy(update=change))


def test_CM_01_window_dst_and_conservative_median_rounding() -> None:
    assert _window(date(2026, 11, 30))[0] == datetime(2026, 11, 30, 20, 45, tzinfo=UTC)
    result = _measure({"AAPL": [quote(bp="99.99", ap="100.00")]}, ("AAPL",), DAY, NOW)[0]
    with pytest.raises(DataIntegrityError):
        HistoricalSpreadSampler(None)  # type: ignore[arg-type]
    assert result.half_spread_bps == D("0.500026")
    at_delay = NOW - timedelta(minutes=54)
    valid = result.model_copy(update={"fetched_at": at_delay})
    assert SpreadMeasurement.model_validate(valid).status == ProviderStatus.OK
