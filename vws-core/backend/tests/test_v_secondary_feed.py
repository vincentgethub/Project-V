"""DQ-02: pinned SDK request, separate immutable feeds and unchanged SIP cache."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import requests
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.core.config import Settings, YamlConfig, load_yaml_config
from backend.core.database import DataSnapshot
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import MarketStatus
from backend.ops.desk_source import ConnectedDeskSource
from backend.tests.test_async_reader import MovingClock
from backend.tests.test_batch_data import _provider
from backend.tests.test_batch_data import calendar as source_calendar

calendar = source_calendar


@pytest.mark.asyncio
async def test_DQ_02_connected_source_third_consecutive_flag_marks_SUSPECT(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, _ = _provider(engine, calendar, monkeypatch, clock)
    request = requests.Session.request

    def secondary_warning(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        response = request(session, method, url, *args, **kwargs)
        if kwargs["params"]["feed"] == "iex":
            data = json.loads(response.content)
            for row in data["bars"]["NVDA"]:
                row["v"] = 100001  # Same prices; IEX volume exceeding SIP still flags.
            response._content = json.dumps(data).encode()
        return response

    monkeypatch.setattr(requests.Session, "request", secondary_warning)
    project = Path(__file__).resolve().parents[2]
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    config = YamlConfig.model_validate({**config.model_dump(), "watchlist": ("NVDA",)})
    settings = Settings()
    boundary, hunter, unused = Mock(), Mock(), Mock()
    boundary.state, hunter.cro.config = reader.state, settings
    actions = Mock()
    actions.fetch = AsyncMock(return_value=None)  # No action can explain this volume anomaly.
    source = ConnectedDeskSource(
        project,
        settings,
        config,
        reader.state,
        clock,
        calendar,
        registry,
        provider,
        boundary,
        reader,
        hunter,
        unused,
        actions,
        unused,
        unused,
        unused,
        None,
    )
    try:
        for index, day in enumerate((29, 30, 1)):
            clock.current = datetime(2026, 9 if day != 1 else 10, day, 21, tzinfo=UTC)
            result = await source.daily()
            nvda = next(
                row for row in result.entries if row.symbol == "NVDA" and row.adjustment == "SPLIT"
            )
            assert nvda.status == (MarketStatus.SUSPECT if index == 2 else MarketStatus.OK)
            assert await source.daily() == result  # Cached reads do not advance the streak.
        reader.state.ledger.verify_chain()
    finally:
        await reader.aclose()


@pytest.mark.asyncio
async def test_DQ_02_secondary_IEX_is_explicit_cached_and_never_replaces_SIP(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, reader, calls = _provider(engine, calendar, monkeypatch, clock)
    try:
        first = await provider.completed_daily_bars(("NVDA",), date(2026, 9, 28))
        secondary = await provider.secondary_completed_bars(("NVDA", "SPY"), first.through)
        assert len(calls) == 2 and calls[0]["feed"] == "sip" and calls[1]["feed"] == "iex"
        assert calls[1]["adjustment"] == "split" and len(secondary[0].bars) == 1
        assert await provider.secondary_completed_bars(("NVDA", "SPY"), first.through) == secondary
        assert await provider.completed_daily_bars(("NVDA",), date(2026, 9, 28)) == first
        assert len(calls) == 2
        with Session(engine) as session:
            rows = tuple(session.scalars(select(DataSnapshot)))
            assert len(rows) == 4 and {row.feed for row in rows} == {"SIP", "IEX"}
        provider.ledger.verify_chain()
    finally:
        await reader.aclose()


@pytest.mark.asyncio
async def test_DQ_02_secondary_incomplete_and_duplicate_symbols_fail_before_request(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 18, tzinfo=UTC))
    provider, reader, calls = _provider(engine, calendar, monkeypatch, clock)
    try:
        for symbols, day in ((("NVDA",), date(2026, 9, 29)), (("NVDA", "NVDA"), date(2026, 9, 28))):
            with pytest.raises(DataIntegrityError):
                await provider.secondary_completed_bars(symbols, day)
        assert not calls
    finally:
        await reader.aclose()
