"""EV-03: frozen issuer provenance, filing visibility and stale-period expiry."""

import copy
from datetime import date
from pathlib import Path

import pytest

from backend.agents.fundamentals import FrameworkStatus, compute_fundamentals
from backend.core.config import FundamentalsConfig
from backend.core.errors import DataIntegrityError
from backend.data.frozen_filings import FilingEvidence, load_filings, seal_filings
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.fundamental_timeline import precompute_fundamentals
from backend.tests.test_fundamentals import evidence, stock, synthetic


def test_EV_03_frozen_issuer_roundtrip_empty_evidence_and_changed_files(tmp_path: Path) -> None:
    original = seal_filings(
        tmp_path, (FilingEvidence(symbol="MSFT", payload=evidence(synthetic())),)
    )
    assert load_filings(tmp_path) == original
    assert original.for_symbol("MSFT") is not None and original.for_symbol("AAPL") is None
    with pytest.raises(DataIntegrityError):
        seal_filings(tmp_path, ())
    path = tmp_path / "MSFT_companyfacts.json"
    path.write_bytes(path.read_bytes().replace(b"1000", b"1001"))
    with pytest.raises(DataIntegrityError):
        load_filings(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DataIntegrityError):
        load_filings(empty)
    sealed = seal_filings(empty, ())
    assert load_filings(empty) == sealed and sealed.evidence == ()


def test_EV_03_future_amendment_is_invisible_until_its_filed_date() -> None:
    calendar = MarketCalendar(start=date(2026, 1, 1), end=date(2027, 6, 30))
    days = (
        date(2026, 7, 31),
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        date(2027, 1, 19),
    )
    original = synthetic()
    poisoned = copy.deepcopy(original)
    amended = {
        **poisoned["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"][0],
        "val": 1,
        "form": "10-K/A",
        "filed": "2026-08-05",
    }
    poisoned["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"].append(amended)
    table = precompute_fundamentals(
        stock(), evidence(poisoned), FundamentalsConfig(), days, calendar
    )
    assert table.at(days[0]).framework_status == FrameworkStatus.INCOMPLETE
    assert table.at(days[1]).framework_status == FrameworkStatus.PASS
    assert (
        table.at(days[2]).metrics
        == compute_fundamentals(
            stock(), evidence(original), calendar.session_close(days[2])
        ).metrics
    )
    assert table.at(days[3]).framework_status == FrameworkStatus.FAIL
    assert table.at(days[4]).framework_status == FrameworkStatus.INCOMPLETE
    assert len(table.points) == 4
    with pytest.raises(DataIntegrityError):
        table.at(date(2027, 1, 20))


def test_EV_03_unavailable_evidence_never_becomes_a_framework_pass() -> None:
    calendar = MarketCalendar(start=date(2026, 1, 1), end=date(2026, 12, 31))
    table = precompute_fundamentals(
        stock(), None, FundamentalsConfig(), (date(2026, 8, 3), date(2026, 8, 4)), calendar
    )
    assert (
        len(table.points) == 1
        and table.at(date(2026, 8, 4)).framework_status == FrameworkStatus.INCOMPLETE
    )
