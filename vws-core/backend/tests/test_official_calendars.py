"""DATA-16: shipped calendars hold only rows fetched from official .gov schedules.

Each macro row's source is the official schedule page; docs/MACRO_SOURCES.md
records the retrieval time and lists every row. Earnings, ETF weights and
substantially-identical groups were not fetched from a provider/issuer, so they
stay header-only (UNAVAILABLE; consumers fail safe). Macro blackout windows are
derived at runtime from macro_events.csv (MacroEvent.window), so
blackout_windows.csv stays header-only too.
"""

from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from backend.ops.macro_events import OFFICIAL_HOSTS, MacroCalendar

PROJECT = Path(__file__).resolve().parents[2]
CONFIG = PROJECT / "config"
HOST_BY_EVENT = {
    "FOMC": "www.federalreserve.gov",
    "CPI": "www.bls.gov",
    "NFP": "www.bls.gov",
    "GDP": "www.bea.gov",
    "PCE": "www.bea.gov",
}


def test_DATA_16_shipped_macro_calendar_parses_with_official_sources_only() -> None:
    events = MacroCalendar(CONFIG / "macro_events.csv").read()
    assert len(events) == 15
    for event in events:
        host = urlsplit(event.source).hostname
        assert host in OFFICIAL_HOSTS and host == HOST_BY_EVENT[event.event]


def test_DATA_16_current_quarter_covers_all_five_official_event_types() -> None:
    events = MacroCalendar(CONFIG / "macro_events.csv").read()
    current = {e.event for e in events if date(2026, 10, 1) <= e.date <= date(2026, 12, 31)}
    assert current == set(HOST_BY_EVENT)
    following = Counter(e.event for e in events if date(2027, 1, 1) <= e.date <= date(2027, 3, 31))
    # BEA had not published its 2027 schedule at retrieval: GDP/PCE UNAVAILABLE.
    assert following == Counter({"FOMC": 2, "CPI": 3, "NFP": 3})


def test_DATA_16_every_row_is_recorded_with_its_retrieval_evidence() -> None:
    notes = (PROJECT / "docs/MACRO_SOURCES.md").read_text(encoding="utf-8")
    assert "Retrieved: 2026-11-16" in notes
    rows = (CONFIG / "macro_events.csv").read_text(encoding="utf-8").splitlines()[1:]
    for row in rows:
        day, clock, event, source, status = row.split(",")
        assert f"| {day} | {clock} | {event} | {source} | {status} |" in notes
    for unavailable in ("Earnings", "ETF sector weights", "substantially_identical.csv"):
        assert unavailable in notes


def test_DATA_16_unfetched_tables_stay_header_only() -> None:
    headers = {
        "earnings_calendar.csv": "symbol,date",
        "etf_sector_weights.csv": "symbol,gics_sector,weight",
        "substantially_identical.csv": "group_id,symbol",
        "blackout_windows.csv": "symbol,start,end,reason",
    }
    for name, header in headers.items():
        assert (CONFIG / name).read_text(encoding="utf-8").splitlines() == [header]
