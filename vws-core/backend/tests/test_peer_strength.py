"""GD-03: informational returns cannot infer unavailable peers or regime."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.agents.peer_strength import calculate_peer_strength
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import AsyncAlpacaMarketData, Bar
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import ProviderStatus


def inputs() -> tuple[tuple[Bar, ...], datetime, InstrumentRegistry, MarketCalendar]:
    project = Path(__file__).resolve().parents[2]
    fixture = json.loads((project / "backend/tests/fixtures/offline_nvda.json").read_text())
    return (
        tuple(AsyncAlpacaMarketData._cached_bar(row) for row in fixture["bars"]),
        datetime.fromisoformat(fixture["as_of"]),
        InstrumentRegistry.from_csv(project / "config"),
        MarketCalendar(),
    )


def test_GD_03_known_aligned_peers_zero_relative_return_and_spy_trend() -> None:
    bars, now, registry, calendar = inputs()
    result = calculate_peer_strength(
        "NVDA", bars, bars, bars, registry=registry, calendar=calendar, as_of=now
    )
    assert result.status == ProviderStatus.OK and result.sector_etf == "XLK"
    assert result.relative_sector_return == result.relative_spy_return == Decimal(0)
    assert result.spy_above_ema200 is True


def test_GD_03_short_or_unknown_sector_stays_unavailable() -> None:
    bars, now, registry, calendar = inputs()
    for symbol, rows in (("NVDA", bars[-199:]), ("SPY", bars)):
        result = calculate_peer_strength(
            symbol, rows, bars, bars, registry=registry, calendar=calendar, as_of=now
        )
        assert result.status == ProviderStatus.UNAVAILABLE
        assert result.relative_sector_return is None and result.spy_above_ema200 is None


@pytest.mark.parametrize("kind", ["stale", "unordered", "symbol"])
def test_GD_03_malformed_peer_evidence_typed(kind: str) -> None:
    bars, now, registry, calendar = inputs()
    symbol = "NVDA"
    if kind == "stale":
        now += timedelta(days=1)
    elif kind == "unordered":
        bars = (*bars[:-2], bars[-1], bars[-2])
    else:
        symbol = "unknown"
    with pytest.raises(DataIntegrityError):
        calculate_peer_strength(
            symbol, bars, bars, bars, registry=registry, calendar=calendar, as_of=now
        )
