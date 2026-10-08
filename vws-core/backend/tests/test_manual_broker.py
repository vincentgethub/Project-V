"""Owner Oct 8 deferral: manual broker/funding must never access input files."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import MANUAL_CSV_DISABLED_MESSAGE, Settings
from backend.core.errors import ConfigurationError
from backend.data.manual_broker import ManualCSVBrokerState
from backend.data.market_calendar import MarketCalendar
from backend.funding.csv_source import ManualActivitiesSource
from backend.tests.test_accounting_service import fee_schedule, state

NOW = datetime(2026, 10, 8, 15, tzinfo=UTC)


@pytest.fixture
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 1, 1))


def forbidden(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("Disabled manual source must not probe files or providers")


@pytest.mark.parametrize("mode", ["MANUAL", "AUTO_PAPER", "AUTO_LIVE"])
@pytest.mark.parametrize("account_type", ["CASH", "MARGIN"])
def test_DAT_12_disabled_even_with_complete_injected_providers(
    tmp_path: Path,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    account_type: str,
) -> None:
    settings = Settings(_env_file=None, broker_account_type="CASH").model_copy(
        update={
            "execution_mode": mode,
            "broker_account_type": account_type,
            "broker_state_source": "MANUAL_CSV",
        }
    )
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    with pytest.raises(ConfigurationError, match="disabled by owner decision") as caught:
        ManualCSVBrokerState(
            settings,
            FrozenClock(NOW),
            calendar,
            forbidden,
            tmp_path / "data/manual_positions.csv",
            tmp_path / "data/manual_cash.csv",
            account_id="owner",
            known_symbols=frozenset({"AAPL"}),
            market_context_provider=forbidden,
            flags_provider=forbidden,
            pending_orders_provider=forbidden,
        )
    assert str(caught.value) == MANUAL_CSV_DISABLED_MESSAGE


def test_DAT_12_constructor_bypass_still_cannot_read_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = object.__new__(ManualCSVBrokerState)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    with pytest.raises(ConfigurationError, match="BROKER_STATE_SOURCE=ALPACA"):
        source.snapshot(NOW)
    assert source.last_flags is None


def test_FN_02_disabled_funding_constructor_cannot_read_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    engine: Engine,
    clock: FrozenClock,
) -> None:
    state_store = state(engine, clock)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    with pytest.raises(ConfigurationError, match="disabled by owner decision"):
        ManualActivitiesSource(
            state_store, tmp_path / "data/manual_cash_flows.csv", "owner", "PAPER"
        )


@pytest.mark.asyncio
async def test_FN_02_constructor_bypass_cannot_read_cash_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule = fee_schedule()
    source = object.__new__(ManualActivitiesSource)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    with pytest.raises(ConfigurationError, match="BROKER_STATE_SOURCE=ALPACA"):
        await source.read_activities(None, NOW, schedule)
