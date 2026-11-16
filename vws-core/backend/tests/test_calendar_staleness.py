"""Item 4: macro calendar staleness alerts and fail-closed blackouts."""

import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.core.clock import FrozenClock
from backend.core.config import EventsPolicy, RealtimeConfig
from backend.core.errors import DataIntegrityError
from backend.ops.macro_events import MacroCalendar, MacroEvent
from backend.realtime.models import ContextTag
from backend.realtime.policy import context
from backend.tests.test_w_core import CAL, HASH, SCOPE, health

NY = ZoneInfo("America/New_York")
FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS = "https://www.bls.gov/schedule/news_release/cpi.htm"
HEADER = "date,et_time,event,source,time_status\n"


def calendar(tmp_path: Path, text: str, now: datetime) -> MacroCalendar:
    path = tmp_path / "macro_events.csv"
    path.write_text(text, encoding="utf-8")
    os.utime(path, (now.timestamp(), now.timestamp()))
    return MacroCalendar(path)


def decide(
    clock: FrozenClock, macros: tuple[MacroEvent, ...], *, auto: bool, fomc: str = "half_size"
) -> tuple[bool, object, tuple[str, ...], tuple[ContextTag, ...]]:
    row = context(
        SCOPE,
        "NVDA",
        clock.now(),
        HASH,
        RealtimeConfig(),
        EventsPolicy.model_validate({"fomc": fomc}),
        health(clock.now()),
        (),
        macros,
        CAL,
        auto=auto,
        schedules_verified=True,
    )
    return row.blocked, row.entry_multiplier, row.warnings, row.tags


def test_EVT_STALE_provisional_marker_parses_and_widens_window(
    tmp_path: Path, clock: FrozenClock
) -> None:
    rows = calendar(
        tmp_path,
        HEADER
        + f"2026-09-29,14:00,FOMC,{FED},provisional\n"
        + f"2026-10-15,08:30,CPI,{BLS},confirmed\n",
        clock.now(),
    ).read()
    provisional, confirmed = rows
    assert provisional.time_confirmed is False and confirmed.time_confirmed is True
    day = date(2026, 9, 29)
    assert provisional.window().start == datetime.combine(day, time(), NY).astimezone(UTC)
    assert provisional.window().end == datetime.combine(
        day + timedelta(days=1), time(), NY
    ).astimezone(UTC) + timedelta(minutes=30)
    assert confirmed.window().end == confirmed.release_at + timedelta(minutes=30)


def test_EVT_STALE_legacy_header_rows_stay_confirmed(tmp_path: Path, clock: FrozenClock) -> None:
    (row,) = calendar(
        tmp_path, f"date,et_time,event,source\n2026-10-15,08:30,CPI,{BLS}\n", clock.now()
    ).read()
    assert row.time_confirmed is True


@pytest.mark.parametrize("status", ["", "PROVISIONAL", "tbd", "confirmed "])
def test_EVT_STALE_unknown_time_status_fails_closed(
    tmp_path: Path, clock: FrozenClock, status: str
) -> None:
    with pytest.raises(DataIntegrityError):
        calendar(tmp_path, HEADER + f"2026-10-15,08:30,CPI,{BLS},{status}\n", clock.now()).read()


def test_EVT_STALE_provisional_row_raises_alert_until_it_passes(
    tmp_path: Path, clock: FrozenClock
) -> None:
    macro = calendar(
        tmp_path,
        HEADER
        + f"2026-09-28,14:00,FOMC,{FED},provisional\n"
        + f"2026-10-28,14:00,FOMC,{FED},provisional\n"
        + f"2026-10-15,08:30,CPI,{BLS},confirmed\n",
        clock.now(),
    )
    (alert,) = macro.warnings(clock.now())
    assert "FOMC 2026-10-28" in alert and "no confirmed official release time" in alert
    assert "2026-09-28" not in alert


def test_EVT_STALE_calendar_past_horizon_raises_alert(tmp_path: Path, clock: FrozenClock) -> None:
    macro = calendar(tmp_path, HEADER + f"2026-09-28,08:30,CPI,{BLS},confirmed\n", clock.now())
    (alert,) = macro.warnings(clock.now())
    assert "past its horizon" in alert and "2026-09-28" in alert
    current = calendar(tmp_path, HEADER + f"2026-09-29,08:30,CPI,{BLS},confirmed\n", clock.now())
    assert current.warnings(clock.now()) == ()


def test_EVT_STALE_empty_calendar_alerts_are_unchanged(tmp_path: Path, clock: FrozenClock) -> None:
    # RT-08/EVT-01 already fail an empty calendar closed: it can never be confirmed.
    assert calendar(tmp_path, HEADER, clock.now()).warnings(clock.now()) == ()


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("fomc", ["annotate", "half_size"])
def test_EVT_STALE_provisional_event_day_is_a_full_blackout(
    clock: FrozenClock, auto: bool, fomc: str
) -> None:
    provisional = MacroEvent(
        date=clock.now().date(),
        release_at=clock.now() + timedelta(hours=3),
        event="FOMC",
        source=FED,
        time_confirmed=False,
    )
    blocked, multiplier, warnings, tags = decide(clock, (provisional,), auto=auto, fomc=fomc)
    assert blocked and multiplier == 0
    assert any(line.startswith("EVT-03:") for line in warnings)
    assert ContextTag.UNAVAILABLE in tags and ContextTag.FOMC in tags
    confirmed = provisional.model_copy(update={"time_confirmed": True})
    blocked, multiplier, warnings, _ = decide(clock, (confirmed,), auto=auto, fomc=fomc)
    assert not blocked and not warnings


@pytest.mark.parametrize("auto", [False, True])
def test_EVT_STALE_calendar_past_horizon_is_a_blackout(clock: FrozenClock, auto: bool) -> None:
    yesterday = clock.now() - timedelta(days=1)
    stale = MacroEvent(
        date=yesterday.astimezone(NY).date(), release_at=yesterday, event="CPI", source=BLS
    )
    blocked, multiplier, warnings, tags = decide(clock, (stale,), auto=auto)
    assert blocked and multiplier == 0
    assert any(line.startswith("EVT-04:") for line in warnings)
    assert ContextTag.UNAVAILABLE in tags
    blocked, _, warnings, _ = decide(clock, (), auto=auto)
    assert not blocked and not warnings
