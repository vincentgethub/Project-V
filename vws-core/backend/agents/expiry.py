"""GD-06: the Nth XNYS close strictly after proposal creation."""

from datetime import datetime

from backend.core.clock import ensure_utc
from backend.core.errors import ConfigurationError
from backend.data.market_calendar import MarketCalendar


def proposal_expiry(created_at: datetime, sessions: int, calendar: MarketCalendar) -> datetime:
    if type(sessions) is not int or not 1 <= sessions <= 3:
        raise ConfigurationError("GD-06: proposal TTL requires one through three sessions")
    instant = ensure_utc(created_at)
    previous_close = calendar.last_completed_session(instant)
    return calendar.session_close(calendar.add_sessions(previous_close, sessions))
