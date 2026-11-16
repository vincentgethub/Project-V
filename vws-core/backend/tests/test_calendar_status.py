"""Calendar status: the shipped calendar marks only unpublished release times provisional."""

from datetime import date
from pathlib import Path

from backend.ops.macro_events import MacroCalendar

CONFIG = Path(__file__).resolve().parents[2] / "config"
PROVISIONAL = {(date(2027, 1, 27), "FOMC"), (date(2027, 3, 17), "FOMC")}


def test_CAL_STATUS_shipped_calendar_uses_the_time_status_column() -> None:
    header = (CONFIG / "macro_events.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "date,et_time,event,source,time_status"


def test_CAL_STATUS_exactly_the_two_2027_fomc_rows_are_provisional() -> None:
    events = MacroCalendar(CONFIG / "macro_events.csv").read()
    assert len(events) == 15
    assert {(e.date, e.event) for e in events if not e.time_confirmed} == PROVISIONAL
    assert all(e.time_confirmed for e in events if e.date.year == 2026)
