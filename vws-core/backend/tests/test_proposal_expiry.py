"""GD-06: calendar-bound validity across closes, holidays, DST and early close."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.agents.expiry import proposal_expiry
from backend.core.errors import ConfigurationError
from backend.data.market_calendar import MarketCalendar


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 1, 1), end=date(2027, 12, 31))


@pytest.mark.parametrize(
    "created, sessions, expected",
    [
        ("2026-09-30T15:00:00+00:00", 1, "2026-09-30T20:00:00+00:00"),
        ("2026-09-30T20:00:00+00:00", 1, "2026-10-01T20:00:00+00:00"),
        ("2026-11-26T15:00:00+00:00", 1, "2026-11-27T18:00:00+00:00"),
        ("2026-11-27T18:00:00+00:00", 1, "2026-11-30T21:00:00+00:00"),
        ("2026-03-06T21:00:00+00:00", 1, "2026-03-09T20:00:00+00:00"),
        ("2026-09-30T20:30:00+00:00", 3, "2026-10-05T20:00:00+00:00"),
    ],
)
def test_expiry_is_actual_Nth_close_strictly_after_creation(
    created: str, sessions: int, expected: str, calendar: MarketCalendar
) -> None:
    assert proposal_expiry(
        datetime.fromisoformat(created), sessions, calendar
    ) == datetime.fromisoformat(expected)


@pytest.mark.parametrize("value", [0, 4, True, 1.0])
def test_unknown_TTL_fails_closed(value: Any, calendar: MarketCalendar) -> None:
    with pytest.raises(ConfigurationError):
        proposal_expiry(datetime(2026, 9, 30, 15, tzinfo=UTC), value, calendar)
