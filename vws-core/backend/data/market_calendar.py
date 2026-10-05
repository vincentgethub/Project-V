"""R-02/R-03/R-05, DAT-01 and CMP-03: deterministic, bounded XNYS sessions.

The official exchange_calendars schedule is compiled once to immutable Python
values. Queries perform no I/O and never consult the wall clock. A regular
session includes its open and excludes its close; at its exact close it is a
completed session. Session labels are dates, whereas all instants are UTC.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol, cast

import exchange_calendars
import pandas as pd
import structlog

from backend.core.clock import ensure_utc
from backend.core.errors import CalendarError

CalendarFactory = Callable[[str, date, date], object]


class _CalendarSource(Protocol):
    """R-02: narrow boundary for the verified, otherwise untyped SDK."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def sessions(self) -> pd.DatetimeIndex:
        raise NotImplementedError

    def session_open(self, session: pd.Timestamp) -> pd.Timestamp:
        raise NotImplementedError

    def session_close(self, session: pd.Timestamp) -> pd.Timestamp:
        raise NotImplementedError


def _official_calendar(name: str, start: date, end: date) -> object:
    # VERIFY: https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/calendar_utils.py
    return cast(
        object,
        exchange_calendars.get_calendar(
            name, start=start.isoformat(), end=end.isoformat(), side="left"
        ),
    )


def _calendar_instant(value: object) -> datetime:
    """R-02/R-05: reject missing, NaT or naive times at the SDK boundary."""
    if not isinstance(value, pd.Timestamp) or pd.isna(value):
        raise CalendarError("Calendar returned a missing or invalid session instant")
    return ensure_utc(value.to_pydatetime())


def _date_argument(value: date) -> date:
    """R-02: do not silently truncate an instant into a session label."""
    if not isinstance(value, date) or isinstance(value, datetime):
        raise CalendarError("Session arguments must be dates, not timestamps")
    return value


def _count_argument(value: int) -> int:
    """R-02/CMP-03: offsets are nonnegative whole session counts."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CalendarError("Session count must be a nonnegative integer")
    return value


class MarketCalendar:
    """R-02/R-03/R-05/DAT-01/CMP-03: bounded NYSE regular trading schedule.

    The default requested range is fixed at 1990-01-01 through 2030-12-31,
    rather than the SDK's wall-clock-dependent default. Only the resolved
    first through last session dates are supported. Beyond those dates every
    query raises CalendarError, including queries that would otherwise return
    an old close. Supply an explicit range for replay or a calendar update.

    add_sessions requires a genuine session date; it never guesses a trade
    date on a holiday. previous_sessions accepts holidays and weekends and
    returns strictly preceding session dates in chronological order.
    """

    def __init__(
        self,
        *,
        name: str = "XNYS",
        start: date = date(1990, 1, 1),
        end: date = date(2030, 12, 31),
        calendar_factory: CalendarFactory | None = None,
    ) -> None:
        try:
            if name != "XNYS":
                raise CalendarError("Only the XNYS calendar is supported")
            start = _date_argument(start)
            end = _date_argument(end)
            if start >= end:
                raise CalendarError("Calendar start must precede end")
            factory = calendar_factory or _official_calendar
            source = cast(_CalendarSource, factory(name, start, end))
            if source.name != "XNYS":
                raise CalendarError("Calendar provider resolved to an unexpected exchange")
            # VERIFY: https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py
            labels = source.sessions
            if not isinstance(labels, pd.DatetimeIndex) or labels.empty:
                raise CalendarError("Calendar returned no valid sessions")
            dates: list[date] = []
            opens: list[datetime] = []
            closes: list[datetime] = []
            for label in labels:
                if not isinstance(label, pd.Timestamp) or pd.isna(label):
                    raise CalendarError("Calendar returned an invalid session label")
                if label.tzinfo is not None or label != label.normalize():
                    raise CalendarError("Session labels must be naive midnight dates")
                session = label.date()
                if not start <= session <= end:
                    raise CalendarError("Calendar session escaped the requested bounds")
                if dates and session <= dates[-1]:
                    raise CalendarError("Calendar sessions must increase strictly")
                # VERIFY: https://github.com/gerrymanoim/exchange_calendars/blob/master/exchange_calendars/exchange_calendar.py
                opened = _calendar_instant(source.session_open(label))
                closed = _calendar_instant(source.session_close(label))
                if opened >= closed or opened.date() != session or closed.date() != session:
                    raise CalendarError("XNYS session open/close interval is invalid")
                if closes and opened <= closes[-1]:
                    raise CalendarError("Calendar session intervals overlap")
                dates.append(session)
                opens.append(opened)
                closes.append(closed)
            self._sessions = tuple(dates)
            self._opens = tuple(opens)
            self._closes = tuple(closes)
        except CalendarError:
            raise
        except Exception as exc:
            structlog.get_logger(__name__).error(
                "calendar_build_failed", error_type=type(exc).__name__
            )
            raise CalendarError("Failed to construct a verified XNYS calendar") from exc

    @property
    def first_session(self) -> date:
        """R-02: first supported session label, inclusive."""
        return self._sessions[0]

    @property
    def last_session(self) -> date:
        """R-02: last supported session label, inclusive."""
        return self._sessions[-1]

    def _bounded_date(self, value: date) -> date:
        result = _date_argument(value)
        if not self.first_session <= result <= self.last_session:
            raise CalendarError("Date is outside the verified calendar range")
        return result

    def _session_index(self, value: date) -> int:
        result = self._bounded_date(value)
        index = bisect_left(self._sessions, result)
        if index == len(self._sessions) or self._sessions[index] != result:
            raise CalendarError("Date is not an XNYS trading session")
        return index

    def _instant(self, value: datetime) -> datetime:
        try:
            result = ensure_utc(value)
            self._bounded_date(result.date())
            return result
        except CalendarError:
            raise
        except Exception as exc:
            raise CalendarError("Calendar query requires a valid aware UTC instant") from exc

    def is_open(self, ts: datetime) -> bool:
        """DAT-01/R-05: regular hours are [open, close), including early closes."""
        instant = self._instant(ts)
        index = bisect_right(self._opens, instant) - 1
        return index >= 0 and instant < self._closes[index]

    def last_completed_session(self, now: datetime) -> date:
        """DAT-01/DAT-03: never expose today's in-progress daily session."""
        instant = self._instant(now)
        index = bisect_right(self._closes, instant) - 1
        if index < 0:
            raise CalendarError("No completed session exists in the verified range")
        return self._sessions[index]

    def add_sessions(self, day: date, n: int) -> date:
        """CMP-03: T+n from an actual trade date; holidays never count."""
        index = self._session_index(day) + _count_argument(n)
        if index >= len(self._sessions):
            raise CalendarError("Session offset exceeds the verified calendar range")
        return self._sessions[index]

    def previous_sessions(self, day: date, n: int) -> tuple[date, ...]:
        """CMP-05: n strictly preceding sessions, earliest first; d is excluded."""
        bounded = self._bounded_date(day)
        count = _count_argument(n)
        index = bisect_left(self._sessions, bounded)
        if count > index:
            raise CalendarError("Insufficient preceding sessions in verified range")
        return self._sessions[index - count : index]

    def session_open(self, day: date) -> datetime:
        """DAT-01/R-05: UTC regular-session open, with DST respected."""
        return self._opens[self._session_index(day)]

    def is_session(self, day: date) -> bool:
        """DAT-01/CMP-05: bounded session membership without assuming a holiday."""
        bounded = self._bounded_date(day)
        index = bisect_left(self._sessions, bounded)
        return index < len(self._sessions) and self._sessions[index] == bounded

    def session_close(self, day: date) -> datetime:
        """DAT-01/R-05: UTC regular-session close, with early close/DST respected."""
        return self._closes[self._session_index(day)]


XNYSCalendar = MarketCalendar
