"""H/EV-03: malformed filing timelines must not become point-in-time passes."""

from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.config import FundamentalsConfig
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.evaluation import fundamental_timeline as module
from backend.evaluation.fundamental_timeline import FundamentalTimeline, precompute_fundamentals
from backend.tests.test_fundamentals import evidence, stock, synthetic

DAYS = (date(2026, 9, 30), date(2026, 10, 1))


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "list",
        "reverse",
        "kind",
        "taxonomy",
        "concept",
        "units",
        "rows",
        "row",
        "period",
        "bounded_rows",
    ],
)
def test_EV_03_invalid_timeline_inputs_raise_typed_error(
    calendar: MarketCalendar, fault: str
) -> None:
    raw = synthetic()
    days: Any = DAYS
    if fault == "empty":
        days = ()
    elif fault == "list":
        days = list(DAYS)
    elif fault == "reverse":
        days = tuple(reversed(DAYS))
    elif fault == "taxonomy":
        raw["facts"]["us-gaap"] = []
    elif fault == "concept":
        raw["facts"]["us-gaap"]["Revenues"] = []
    elif fault == "units":
        raw["facts"]["us-gaap"]["Revenues"]["units"] = []
    elif fault == "rows":
        raw["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = {}
    elif fault == "row":
        raw["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [1]
    elif fault == "bounded_rows":
        raw["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [{}] * 30001
    elif fault == "period":
        row = raw["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]
        row["filed"], row["end"] = "2026-09-30", "2026-10-01"
    payload = evidence(raw)
    if fault == "kind":
        payload = payload.model_copy(update={"kind": "SUBMISSIONS"})
    with pytest.raises(DataIntegrityError):
        precompute_fundamentals(stock(), payload, FundamentalsConfig(), days, calendar)


@pytest.mark.parametrize("fault", ["window", "points", "issuer", "date"])
def test_EV_03_forged_timeline_cannot_mix_issuer_or_observation_dates(
    calendar: MarketCalendar, fault: str
) -> None:
    table = precompute_fundamentals(
        stock(), evidence(synthetic()), FundamentalsConfig(), DAYS, calendar
    )
    point = table.points[0]
    changes: dict[str, Any]
    if fault == "window":
        changes = {"first": DAYS[-1] + timedelta(days=1)}
    elif fault == "points":
        changes = {"points": (point, point)}
    elif fault == "issuer":
        report = point.report.model_copy(update={"symbol": "AAPL"})
        later = point.model_copy(update={"session": DAYS[-1], "report": report})
        changes = {"points": (point, later)}
    else:
        report = point.report.model_copy(update={"as_of": point.report.as_of + timedelta(days=1)})
        changes = {"points": (point.model_copy(update={"report": report}),)}
    with pytest.raises(ValidationError):
        FundamentalTimeline.model_validate(table.model_copy(update=changes))


def test_EV_03_unexpected_and_typed_filing_failures_remain_closed(
    calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise DataIntegrityError("fixture financial evidence fault")

    monkeypatch.setattr(module, "compute_fundamentals", broken)
    with pytest.raises(DataIntegrityError, match="fixture financial evidence"):
        precompute_fundamentals(stock(), None, FundamentalsConfig(), DAYS, calendar)


def test_EV_03_nonfinancial_forms_are_ignored_without_inventing_metrics(
    calendar: MarketCalendar,
) -> None:
    raw = synthetic()
    for concept in raw["facts"]["us-gaap"].values():
        for row in concept["units"]["USD"]:
            row["form"] = "8-K"
    table = precompute_fundamentals(stock(), evidence(raw), FundamentalsConfig(), DAYS, calendar)
    assert table.at(DAYS[-1]).framework_status.value == "INCOMPLETE"
