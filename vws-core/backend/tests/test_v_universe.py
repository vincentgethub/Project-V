"""QV-06: CSV interval boundaries are causal and part of the frozen run proof."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.data.frozen_filings import FrozenFilings
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.universe import PIT_NOTICE, HistoricalUniverse, load
from backend.tests.test_replay import calendar as source_calendar
from backend.tests.test_replay import inputs as source_inputs
from backend.tests.test_replay import request, run

calendar = source_calendar
inputs = source_inputs


def test_QV_PIT_addition_inclusive_removal_exclusive_and_registered_hash(tmp_path: Path) -> None:
    path = tmp_path / "universe.csv"
    assert load(path, ("NVDA", "MSFT")) is None
    path.write_text(
        "symbol,date_added,date_removed\nNVDA,2026-09-29,2026-10-01\nNVDA,2026-10-02,\nMSFT,2026-01-01,\n",
        encoding="utf-8",
    )
    first = load(path, ("NVDA", "MSFT"))
    assert first is not None
    assert not first.contains("NVDA", date(2026, 9, 28))
    assert first.contains("NVDA", date(2026, 9, 29))
    assert not first.contains("NVDA", date(2026, 10, 1))
    assert first.contains("NVDA", date(2026, 10, 2))
    assert HistoricalUniverse.recorded(first.model_dump(mode="json")) == first
    path.write_text(path.read_text().replace("2026-10-02", "2026-10-05"), encoding="utf-8")
    second = load(path, ("NVDA", "MSFT"))
    assert second is not None and first.file_sha256 != second.file_sha256


@pytest.mark.parametrize(
    "row",
    [
        "symbol,date_added\nNVDA,2026-01-01\n",
        "symbol,date_added,date_removed\nUNKNOWN,2026-01-01,\n",
        "symbol,date_added,date_removed\nNVDA,2026-01-01,2025-12-31\n",
        "symbol,date_added,date_removed\nNVDA,2026-01-01,\nNVDA,2026-02-01,\n",
        "symbol,date_added,date_removed\n",
        "symbol,date_added,date_removed\nNVDA,2026-01-01,,extra\n",
    ],
)
def test_QV_invalid_universe_never_falls_back_to_current_watchlist(
    tmp_path: Path, row: str
) -> None:
    path = tmp_path / "universe.csv"
    path.write_text(row, encoding="utf-8")
    with pytest.raises(DataIntegrityError, match="membership"):
        load(path, ("NVDA",))


def test_QV_replay_uses_membership_at_decision_and_preserves_bias_proof(
    tmp_path: Path,
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
) -> None:
    path = tmp_path / "universe.csv"
    path.write_text(
        "symbol,date_added,date_removed\nNVDA,2026-01-01,2026-09-29\nMSFT,2026-10-06,\n",
        encoding="utf-8",
    )
    universe = load(path, ("NVDA", "MSFT"))
    assert universe is not None
    baseline = run(request(), inputs, calendar)
    assert baseline.decisions
    result = run(request(universe=universe), inputs, calendar)
    assert result.decisions == () and result.filtered_outcomes == ()
    assert result.report.context.universe_sha256 == universe.file_sha256
    assert PIT_NOTICE in result.report.notes and PIT_NOTICE in result.notes
    assert "Historical membership SHA256: " + universe.file_sha256 in result.report.notes
    assert result.sha256 != baseline.sha256


@pytest.mark.parametrize("case", ["directory", "oversized", "duplicate", "unsorted"])
def test_QV_universe_file_and_detached_model_bounds(tmp_path: Path, case: str) -> None:
    path = tmp_path / "universe.csv"
    if case == "directory":
        path.mkdir()
    elif case == "oversized":
        path.write_bytes(b"x" * 256001)
    else:
        path.write_text(
            "symbol,date_added,date_removed\nMSFT,2026-01-01,\nNVDA,2026-01-01,\n", encoding="utf-8"
        )
        valid = load(path, ("MSFT", "NVDA"))
        assert valid is not None
        rows = (
            (valid.rows[0], valid.rows[0]) if case == "duplicate" else tuple(reversed(valid.rows))
        )
        with pytest.raises(ValidationError, match="unique membership"):
            HistoricalUniverse.model_validate({**valid.model_dump(), "rows": rows})
        return
    with pytest.raises(DataIntegrityError, match="membership"):
        load(path, ("NVDA",))
