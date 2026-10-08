"""OPS-01/RT-01: read-only clock and bounded broker-calendar verification.

The early RT-01 work is already required by doctor and AX-22. It adds no feed
policy or execution. UTC evidence is revalidated; disagreement durably halts.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, UTCDateTime

_NY = ZoneInfo("America/New_York")
ClockRead = Callable[[], Awaitable[object]]
CalendarRead = Callable[[date, date], Awaitable[object]]


class BrokerSession(FrozenModel):
    session: date
    opened: UTCDateTime
    closed: UTCDateTime

    @model_validator(mode="after")
    def interval(self) -> Self:
        if (
            isinstance(self.session, datetime)
            or self.opened >= self.closed
            or self.opened.astimezone(_NY).date() != self.session
            or self.closed.astimezone(_NY).date() != self.session
        ):
            raise ValueError("broker calendar interval is invalid")
        return self


class BrokerTime(FrozenModel):
    timestamp: UTCDateTime
    is_open: bool = Field(strict=True)
    next_open: UTCDateTime
    next_close: UTCDateTime
    sampled_start: UTCDateTime
    sampled_end: UTCDateTime
    calendar_fetched_at: UTCDateTime
    sessions: tuple[BrokerSession, ...] = Field(min_length=1, max_length=32)
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if (
            self.sampled_end < self.sampled_start
            or self.sampled_end - self.sampled_start > timedelta(seconds=30)
            or self.calendar_fetched_at > self.sampled_end
            or self.next_open < self.timestamp
            or self.next_close < self.timestamp
            or tuple(row.session for row in self.sessions)
            != tuple(sorted({row.session for row in self.sessions}))
        ):
            raise ValueError("broker time evidence is malformed or unordered")
        return self


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("broker clock requires a bounded timestamp")
    return ensure_utc(datetime.fromisoformat(value))


def _session(value: object) -> BrokerSession:
    if not isinstance(value, dict) or not {"date", "open", "close"} <= value.keys():
        raise ValueError("broker calendar row is incomplete")
    label = value["date"]
    if not isinstance(label, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", label) is None:
        raise ValueError("broker calendar date is invalid")
    day = date.fromisoformat(label)
    instants: list[datetime] = []
    for name in ("open", "close"):
        text = value[name]
        if not isinstance(text, str) or re.fullmatch(r"\d{2}:\d{2}", text) is None:
            raise ValueError("broker calendar time is invalid")
        instants.append(ensure_utc(datetime.combine(day, time.fromisoformat(text), _NY)))
    return BrokerSession(session=day, opened=instants[0], closed=instants[1])


class BrokerTimeVerifier:
    def __init__(
        self,
        settings: Settings,
        calendar: MarketCalendar,
        clock: Clock,
        state: SystemStateStore,
        read_clock: ClockRead,
        read_calendar: CalendarRead,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        if state.clock is not clock:
            raise DataIntegrityError("broker clock must share the durable state clock")
        self.calendar, self.clock, self.state = calendar, clock, state
        self.read_clock, self.read_calendar = read_clock, read_calendar
        self._cache: tuple[date, datetime, tuple[BrokerSession, ...]] | None = None
        self._lock = asyncio.Lock()

    async def verify(self) -> BrokerTime:
        async with self._lock:
            try:
                start = ensure_utc(self.clock.now())
                today = start.astimezone(_NY).date()
                if (
                    self._cache is None
                    or self._cache[0] != today
                    or not timedelta(0) <= start - self._cache[1] <= timedelta(hours=24)
                ):
                    end = today + timedelta(days=14)
                    async with asyncio.timeout(30):
                        raw_calendar = await self.read_calendar(today, end)
                    if not isinstance(raw_calendar, list) or len(raw_calendar) > 32:
                        raise ValueError("broker calendar list is unavailable or oversized")
                    sessions = tuple(_session(row) for row in raw_calendar)
                    expected = tuple(
                        today + timedelta(days=offset)
                        for offset in range(15)
                        if self.calendar.is_session(today + timedelta(days=offset))
                    )
                    if tuple(row.session for row in sessions) != expected:
                        raise ValueError("broker calendar inventory differs from XNYS")
                    if any(
                        row.opened != self.calendar.session_open(row.session)
                        or row.closed != self.calendar.session_close(row.session)
                        for row in sessions
                    ):
                        raise ValueError("broker hours differ from verified XNYS hours")
                    fetched = ensure_utc(self.clock.now())
                    if fetched < start or fetched - start > timedelta(seconds=30):
                        raise ValueError("broker calendar read exceeded its deadline")
                    self.state.ledger.append(
                        SecurityEvent,
                        kind="BROKER_CALENDAR_VERIFIED",
                        telegram_user_id=None,
                        detail={
                            "config_hash": self.settings.config_hash,
                            "endpoint": self.settings.broker_endpoint,
                            "sessions": [row.model_dump(mode="json") for row in sessions],
                        },
                        ts=fetched,
                    )
                    self._cache = (today, fetched, sessions)
                fetched, sessions = self._cache[1], self._cache[2]
                sampled_start = ensure_utc(self.clock.now())
                async with asyncio.timeout(30):
                    raw_clock = await self.read_clock()
                sampled_end = ensure_utc(self.clock.now())
                if not isinstance(raw_clock, dict):
                    raise ValueError("broker clock payload is unavailable")
                is_open = raw_clock.get("is_open")
                if type(is_open) is not bool:
                    raise ValueError("broker market-open flag must be an exact boolean")
                timestamp = _instant(raw_clock.get("timestamp"))
                evidence = BrokerTime(
                    timestamp=timestamp,
                    is_open=is_open,
                    next_open=_instant(raw_clock.get("next_open")),
                    next_close=_instant(raw_clock.get("next_close")),
                    sampled_start=sampled_start,
                    sampled_end=sampled_end,
                    calendar_fetched_at=fetched,
                    sessions=sessions,
                    config_hash=self.settings.config_hash,
                )
                # Worst-case bound across the read interval, rather than a
                # guessed midpoint that hides network uncertainty or skew.
                if max(abs(timestamp - sampled_start), abs(timestamp - sampled_end)) > timedelta(
                    seconds=self.settings.max_clock_skew_seconds
                ):
                    raise ValueError("clock skew or network uncertainty exceeds its ceiling")
                if evidence.is_open != self.calendar.is_open(timestamp):
                    raise ValueError("broker market-open flag disagrees with XNYS")
                next_open = next((row.opened for row in sessions if row.opened > timestamp), None)
                next_close = next((row.closed for row in sessions if row.closed > timestamp), None)
                if evidence.next_open != next_open or evidence.next_close != next_close:
                    raise ValueError("next broker open/close disagrees with XNYS")
                return BrokerTime.model_validate(evidence)
            except Exception as error:
                self._cache = None
                self.state.escalate(SystemState.HALTED, "RT-01: broker clock/calendar unavailable")
                if isinstance(error, ProviderError):
                    raise ProviderError("RT-01: broker clock/calendar read failed") from None
                raise DataIntegrityError(
                    "RT-01: broker clock/calendar could not be verified"
                ) from None
