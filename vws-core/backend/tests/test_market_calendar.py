"""R-02/R-03/R-05, DAT-01/DAT-03 and CMP-03/CMP-05 calendar safety."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import cast

import pandas as pd
import pytest

from backend.core.errors import CalendarError
from backend.data.market_calendar import MarketCalendar


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2026, 12, 31))


@pytest.mark.parametrize(
    "day,open_hour,close_hour",
    [
        (date(2024, 3, 8), 14, 21),
        (date(2024, 3, 11), 13, 20),
        (date(2024, 11, 1), 13, 20),
        (date(2024, 11, 4), 14, 21),
        (date(2025, 3, 7), 14, 21),
        (date(2025, 3, 10), 13, 20),
        (date(2025, 10, 31), 13, 20),
        (date(2025, 11, 3), 14, 21),
        (date(2026, 3, 6), 14, 21),
        (date(2026, 3, 9), 13, 20),
        (date(2026, 10, 30), 13, 20),
        (date(2026, 11, 2), 14, 21),
    ],
)
def test_DAT_01_R_05_dst_changes_exact_utc_regular_hours(
    calendar: MarketCalendar, day: date, open_hour: int, close_hour: int
) -> None:
    """DAT-01/R-05: real spring/fall dates retain 09:30-16:00 New York hours."""
    opened = datetime(day.year, day.month, day.day, open_hour, 30, tzinfo=UTC)
    closed = datetime(day.year, day.month, day.day, close_hour, tzinfo=UTC)
    assert calendar.session_open(day) == opened
    assert calendar.session_close(day) == closed
    assert not calendar.is_open(opened - timedelta(microseconds=1))
    assert calendar.is_open(opened)
    assert calendar.is_open(closed - timedelta(microseconds=1))
    assert not calendar.is_open(closed)


@pytest.mark.parametrize(
    "holiday",
    [
        date(2024, 7, 4),
        date(2024, 11, 28),
        date(2024, 12, 25),
        date(2025, 1, 9),
        date(2025, 7, 4),
        date(2025, 11, 27),
        date(2025, 12, 25),
        date(2026, 7, 3),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2026, 10, 3),
        date(2026, 10, 4),
    ],
)
def test_DAT_01_holidays_weekends_and_2025_national_mourning_are_closed(
    calendar: MarketCalendar, holiday: date
) -> None:
    """DAT-01: closed days cannot produce a trading-session close."""
    assert not calendar.is_open(datetime.combine(holiday, datetime.min.time(), UTC))
    assert not calendar.is_open(datetime(holiday.year, holiday.month, holiday.day, 16, tzinfo=UTC))
    with pytest.raises(CalendarError, match="not an XNYS"):
        calendar.session_close(holiday)


@pytest.mark.parametrize(
    "day,hour",
    [
        (date(2024, 7, 3), 17),
        (date(2024, 11, 29), 18),
        (date(2024, 12, 24), 18),
        (date(2025, 7, 3), 17),
        (date(2025, 11, 28), 18),
        (date(2025, 12, 24), 18),
        (date(2026, 11, 27), 18),
        (date(2026, 12, 24), 18),
    ],
)
def test_DAT_01_DAT_03_early_close_is_completed_at_exact_close(
    calendar: MarketCalendar, day: date, hour: int
) -> None:
    """DAT-01/DAT-03: daily completion follows actual early-close time."""
    closed = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
    assert calendar.session_close(day) == closed
    assert calendar.is_open(closed - timedelta(microseconds=1))
    assert not calendar.is_open(closed)
    assert calendar.last_completed_session(closed) == day
    assert calendar.last_completed_session(closed - timedelta(microseconds=1)) < day


def test_DAT_01_2026_july_second_has_normal_close(calendar: MarketCalendar) -> None:
    """DAT-01: an observed Friday holiday does not invent a Thursday early close."""
    assert calendar.session_close(date(2026, 7, 2)) == utc("2026-07-02T20:00:00")
    assert calendar.is_open(utc("2026-07-02T19:59:59.999999"))


@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-10-02T13:29:59.999999", date(2026, 10, 1)),
        ("2026-10-02T13:30:00", date(2026, 10, 1)),
        ("2026-10-02T19:59:59.999999", date(2026, 10, 1)),
        ("2026-10-02T20:00:00", date(2026, 10, 2)),
        ("2026-10-02T23:00:00", date(2026, 10, 2)),
        ("2026-10-03T16:00:00", date(2026, 10, 2)),
        ("2026-10-04T16:00:00", date(2026, 10, 2)),
        ("2026-11-26T16:00:00", date(2026, 11, 25)),
        ("2026-11-27T17:59:59.999999", date(2026, 11, 25)),
        ("2026-11-27T18:00:00", date(2026, 11, 27)),
    ],
)
def test_DAT_03_last_completed_session_excludes_in_progress_daily_bar(
    calendar: MarketCalendar, now: str, expected: date
) -> None:
    """DAT-03: pre-open, nights, weekends and holidays use the last completed bar."""
    assert calendar.last_completed_session(utc(now)) == expected


@pytest.mark.parametrize(
    "trade,settlement",
    [
        (date(2024, 7, 3), date(2024, 7, 5)),
        (date(2025, 7, 3), date(2025, 7, 7)),
        (date(2026, 7, 2), date(2026, 7, 6)),
        (date(2024, 11, 27), date(2024, 11, 29)),
        (date(2025, 11, 26), date(2025, 11, 28)),
        (date(2026, 11, 25), date(2026, 11, 27)),
        (date(2024, 11, 29), date(2024, 12, 2)),
        (date(2025, 11, 28), date(2025, 12, 1)),
        (date(2026, 11, 27), date(2026, 11, 30)),
        (date(2024, 12, 24), date(2024, 12, 26)),
        (date(2025, 12, 24), date(2025, 12, 26)),
        (date(2026, 12, 24), date(2026, 12, 28)),
        (date(2025, 1, 8), date(2025, 1, 10)),
    ],
)
def test_CMP_03_T_plus_one_uses_real_exchange_sessions(
    calendar: MarketCalendar, trade: date, settlement: date
) -> None:
    """CMP-03: an early close is a session; holiday/weekend dates never settle."""
    assert calendar.add_sessions(trade, 0) == trade
    assert calendar.add_sessions(trade, 1) == settlement


@pytest.mark.parametrize("day", [date(2026, 10, 5), date(2026, 10, 3), date(2026, 10, 4)])
def test_CMP_05_previous_sessions_excludes_anchor_and_is_chronological(
    calendar: MarketCalendar, day: date
) -> None:
    """CMP-05: legacy count windows consistently exclude the anchor day."""
    assert calendar.previous_sessions(day, 5) == (
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
    )
    assert calendar.previous_sessions(day, 0) == ()


def test_R_02_calendar_limits_reject_stale_fallback(calendar: MarketCalendar) -> None:
    """R-02: out-of-range instants cannot silently reuse an arbitrarily old close."""
    assert calendar.first_session == date(2024, 1, 2)
    assert calendar.last_session == date(2026, 12, 31)
    for instant in (utc("2024-01-01T16:00:00"), utc("2027-01-01T16:00:00")):
        with pytest.raises(CalendarError, match="outside"):
            calendar.is_open(instant)
        with pytest.raises(CalendarError, match="outside"):
            calendar.last_completed_session(instant)
    with pytest.raises(CalendarError, match="No completed"):
        calendar.last_completed_session(calendar.session_open(calendar.first_session))
    with pytest.raises(CalendarError, match="exceeds"):
        calendar.add_sessions(calendar.last_session, 1)
    with pytest.raises(CalendarError, match="Insufficient"):
        calendar.previous_sessions(calendar.first_session, 1)


@pytest.mark.parametrize("count", [-1, True, "1", None])
def test_R_02_CMP_03_invalid_session_counts_fail_closed(
    calendar: MarketCalendar, count: object
) -> None:
    """R-02/CMP-03: negative, boolean, text and missing offsets are invalid."""
    with pytest.raises(CalendarError, match="nonnegative"):
        calendar.add_sessions(date(2026, 10, 2), cast(int, count))
    with pytest.raises(CalendarError, match="nonnegative"):
        calendar.previous_sessions(date(2026, 10, 2), cast(int, count))


@pytest.mark.parametrize("day", [None, "2026-10-02", utc("2026-10-02T00:00:00")])
def test_R_02_session_label_cannot_be_missing_text_or_datetime(
    calendar: MarketCalendar, day: object
) -> None:
    """R-02: conversion of ambiguous labels is prohibited."""
    with pytest.raises(CalendarError, match="must be dates"):
        calendar.add_sessions(cast(date, day), 1)


def test_R_02_CMP_03_trade_date_must_be_actual_session(
    calendar: MarketCalendar,
) -> None:
    """R-02/CMP-03: settlement cannot guess a trade date on a holiday."""
    with pytest.raises(CalendarError, match="not an XNYS"):
        calendar.add_sessions(date(2026, 7, 3), 1)


@pytest.mark.parametrize(
    "instant",
    [None, "2026-10-02T16:00:00", utc("2026-10-02T16:00:00").replace(tzinfo=None)],
)
def test_R_02_R_05_invalid_instants_raise_typed_calendar_error(
    calendar: MarketCalendar, instant: object
) -> None:
    """R-02/R-05: naive and missing instants never yield open/completed state."""
    with pytest.raises(CalendarError):
        calendar.is_open(cast(datetime, instant))
    with pytest.raises(CalendarError):
        calendar.last_completed_session(cast(datetime, instant))


@pytest.mark.parametrize("name", ["UNKNOWN", "XNAS", "NYSE", ""])
def test_R_02_unknown_or_unapproved_exchange_fails_typed(name: str) -> None:
    """R-02: only an exact XNYS exchange name is accepted."""
    with pytest.raises(CalendarError, match="Only the XNYS"):
        MarketCalendar(name=name)


@pytest.mark.parametrize(
    "failure", [RuntimeError("offline"), ValueError("corrupt"), KeyError("missing")]
)
def test_R_02_injected_calendar_exception_is_typed(failure: Exception) -> None:
    """R-02: unexpected provider failures are never interpreted as valid state."""

    def broken(name: str, start: date, end: date) -> object:
        del name, start, end
        raise failure

    with pytest.raises(CalendarError, match="construct") as result:
        MarketCalendar(calendar_factory=broken)
    assert result.value.__cause__ is failure


class BrokenSchedule:
    """R-02: controllable malformed provider for SDK-boundary fault injection."""

    def __init__(self, fault: str) -> None:
        self.name = "XNAS" if fault == "exchange" else "XNYS"
        self.fault = fault
        if fault == "empty":
            self.sessions = pd.DatetimeIndex([])
        elif fault == "duplicate":
            self.sessions = pd.DatetimeIndex(["2026-10-01", "2026-10-01"])
        elif fault == "reversed":
            self.sessions = pd.DatetimeIndex(["2026-10-02", "2026-10-01"])
        elif fault == "label_timezone":
            self.sessions = pd.DatetimeIndex(["2026-10-01"], tz="UTC")
        elif fault == "label_time":
            self.sessions = pd.DatetimeIndex(["2026-10-01T12:00:00"])
        elif fault == "label_missing":
            self.sessions = pd.DatetimeIndex([pd.NaT])
        elif fault == "escaped":
            self.sessions = pd.DatetimeIndex(["2023-12-29"])
        else:
            self.sessions = pd.DatetimeIndex(["2026-10-01", "2026-10-02"])

    def session_open(self, session: pd.Timestamp) -> pd.Timestamp:
        if self.fault == "missing_instant":
            return cast(pd.Timestamp, pd.NaT)
        if self.fault == "naive_instant":
            return session + pd.Timedelta(hours=13, minutes=30)
        if self.fault == "wrong_day":
            return (session - pd.Timedelta(days=1)).tz_localize("UTC")
        if self.fault == "overlap" and session.day == 2:
            return pd.Timestamp("2026-10-01T19:00:00", tz="UTC")
        return session.tz_localize("UTC") + pd.Timedelta(hours=13, minutes=30)

    def session_close(self, session: pd.Timestamp) -> pd.Timestamp:
        if self.fault == "reversed_interval":
            return session.tz_localize("UTC") + pd.Timedelta(hours=13)
        return session.tz_localize("UTC") + pd.Timedelta(hours=20)


@pytest.mark.parametrize(
    "fault",
    [
        "exchange",
        "empty",
        "duplicate",
        "reversed",
        "label_timezone",
        "label_time",
        "label_missing",
        "escaped",
        "missing_instant",
        "naive_instant",
        "wrong_day",
        "reversed_interval",
        "overlap",
    ],
)
def test_R_02_R_05_malformed_calendar_schedule_fails_closed(fault: str) -> None:
    """R-02/R-05: unknown, missing, ambiguous or nonmonotonic schedules fail."""

    def broken(name: str, start: date, end: date) -> object:
        del name, start, end
        return BrokenSchedule(fault)

    with pytest.raises(CalendarError):
        MarketCalendar(start=date(2024, 1, 2), end=date(2026, 12, 31), calendar_factory=broken)


@pytest.mark.parametrize(
    "start,end",
    [(date(2026, 10, 2), date(2026, 10, 2)), (date(2026, 10, 2), date(2026, 10, 1))],
)
def test_R_02_invalid_calendar_range_is_typed(start: date, end: date) -> None:
    """R-02: an empty or reversed configured horizon cannot pass startup."""
    with pytest.raises(CalendarError, match="start must precede"):
        MarketCalendar(start=start, end=end)


def test_R_03_R_05_calendar_queries_are_deterministic(calendar: MarketCalendar) -> None:
    """R-03/R-05: the same injected instant has the same regular-session result."""
    instant = utc("2026-10-02T16:00:00")
    assert calendar.is_open(instant) == calendar.is_open(instant)
    assert calendar.last_completed_session(instant) == date(2026, 10, 1)
    assert calendar.last_completed_session(instant) == calendar.last_completed_session(instant)
