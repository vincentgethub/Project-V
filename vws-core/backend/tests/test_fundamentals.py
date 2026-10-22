"""FA-01..09: independent arithmetic on recorded SEC and synthetic evidence.

Expected values below are formulas transcribed from the raw USD facts, not
outputs of the framework. The default pytest socket prohibition remains on.
"""

import copy
import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.agents import fundamentals as fa
from backend.agents.fundamentals import (
    NAMES,
    THRESHOLDS,
    FrameworkStatus,
    FundamentalReport,
    MetricResult,
    MetricStatus,
    compute_fundamentals,
    framework_allows,
)
from backend.core.config import FundamentalsConfig
from backend.core.errors import DataIntegrityError
from backend.data.sec_edgar import SecPayload
from backend.domain.models import AssetClass, Instrument

AS_OF = datetime(2026, 10, 5, 23, 59, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "sec"
END = date(2026, 6, 30)


def test_FA_01_recorded_reports_round_trip_and_reject_malformed_provenance() -> None:
    report = compute_fundamentals(stock(), evidence(synthetic()), AS_OF, FundamentalsConfig())
    assert FundamentalReport.from_recorded(report.model_dump(mode="json")) == report
    for invalid in ({}, {**report.model_dump(mode="json"), "as_of": "unknown"}):
        with pytest.raises(DataIntegrityError, match="recorded fundamental"):
            FundamentalReport.from_recorded(invalid)


def stock(symbol: str = "MSFT", sector: str = "Information Technology") -> Instrument:
    return Instrument(
        symbol=symbol,
        asset_class=AssetClass.STOCK,
        gics_sector=sector,
        is_leveraged=False,
        is_inverse=False,
        tradable=True,
    )


def recorded(symbol: str) -> SecPayload:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    entry = next(row for row in manifest if row["symbol"] == symbol)
    raw = (FIXTURES / entry["file"]).read_bytes()
    assert len(raw) == entry["bytes"]
    assert hashlib.sha256(raw).hexdigest() == entry["data_sha256"]
    assert entry["source"] == (f"https://data.sec.gov/api/xbrl/companyfacts/CIK{entry['cik']}.json")
    return SecPayload(
        kind="COMPANYFACTS",
        cik=entry["cik"],
        fetched_at=datetime.fromisoformat(entry["fetched_at"]),
        raw=raw,
        data_sha256=entry["data_sha256"],
    )


def evidence(data: dict[str, Any]) -> SecPayload:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return SecPayload(
        kind="COMPANYFACTS",
        cik="0000789019",
        fetched_at=AS_OF,
        raw=raw,
        data_sha256=hashlib.sha256(raw).hexdigest(),
    )


def synthetic() -> dict[str, Any]:
    """FY all pass: revenue1000, GP500, op200, IC1000, tax20%, CFO300/capex100."""
    amounts = {
        "Revenues": 1000,
        "GrossProfit": 500,
        "OperatingIncomeLoss": 200,
        "NetCashProvidedByUsedInOperatingActivities": 300,
        "PaymentsToAcquirePropertyPlantAndEquipment": 100,
        "InterestExpense": 10,
        "IncomeTaxExpenseBenefit": 40,
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 200,
        "StockholdersEquity": 900,
        "LongTermDebt": 200,
        "CashAndCashEquivalentsAtCarryingValue": 100,
    }
    instants = {"StockholdersEquity", "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue"}
    tags: dict[str, Any] = {}
    for tag, value in amounts.items():
        row: dict[str, Any] = {
            "val": value,
            "end": "2026-06-30",
            "filed": "2026-08-01",
            "form": "10-K",
        }
        if tag not in instants:
            row["start"] = "2025-07-01"
        tags[tag] = {"units": {"USD": [row]}}
    return {"cik": 789019, "facts": {"us-gaap": tags}}


def rows(data: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    return data["facts"]["us-gaap"][tag]["units"]["USD"]  # type: ignore[no-any-return]


def set_value(data: dict[str, Any], tag: str, value: int | str) -> None:
    rows(data, tag)[0]["val"] = value


def metric(data: dict[str, Any], index: int) -> MetricResult:
    return compute_fundamentals(stock(), evidence(data), AS_OF).metrics[index]


def assert_values(report: FundamentalReport, expected: tuple[Decimal | None, ...]) -> None:
    assert tuple(item.value for item in report.metrics) == expected
    assert report.data_sha256 == recorded(report.symbol).data_sha256


def test_FA_real_MSFT_all_five_pass_with_hand_computed_FY() -> None:
    report = compute_fundamentals(stock(), recorded("MSFT"), AS_OF)
    with localcontext() as context:
        context.prec = 80
        # Millions USD. FY2026: GP225465, revenue331839, op155237,
        # tax32185/pretax165934; IC=(equity+total LT debt-cash), two June ends.
        invested = (Decimal(442387 + 40294 - 20935) + Decimal(343479 + 43151 - 30242)) / 2
        expected = (
            Decimal(225465) / 331839,
            Decimal(155237) / 331839,
            Decimal(155237) * (1 - Decimal(32185) / 165934) / invested,
            Decimal(182935 - 115948) * 1000000,
            Decimal(155237) / 3051,
        )
    assert_values(report, expected)
    assert report.basis == "FY" and report.latest_period_end == END
    assert report.framework_status == FrameworkStatus.PASS and report.passed_count == 5
    assert report.failure_reasons == ()
    assert report.metrics[4].source_tags[1] == "InterestExpenseNonoperating"


def test_FA_real_COST_low_margin_TTM_with_tag_change_and_52_week_year() -> None:
    report = compute_fundamentals(stock("COST", "Consumer Staples"), recorded("COST"), AS_OF)
    with localcontext() as context:
        context.prec = 80
        # Millions USD: FY ended Aug31 2025 + YTD May10 2026 - YTD May11 2025.
        revenue = Decimal(275235 + 207431 - 189079)
        cost = Decimal(239886 + 180748 - 164849)
        op = Decimal(10383 + 7884 - 7042)
        invested = (Decimal(33509 + 5670 - 18946) + Decimal(27125 + 5717 + 178 - 13836)) / 2
        expected = (
            (revenue - cost) / revenue,
            op / revenue,
            op * Decimal("0.79") / invested,  # period-matched pretax missing: specified fallback
            Decimal((13335 + 11133 - 9468) - (5498 + 4228 - 3532)) * 1000000,
            op / (154 + 100 - 108),
        )
    assert_values(report, expected)
    assert report.basis == "TTM" and report.latest_period_end == date(2026, 5, 10)
    assert report.framework_status == FrameworkStatus.FAIL and report.passed_count == 3
    assert report.failure_reasons[0] == "Gross margin 12.9% (needs >40%)"
    assert report.failure_reasons[1] == "Operating margin 3.8% (needs >15%)"
    assert "Revenues" in report.metrics[0].source_tags
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in report.metrics[0].source_tags


def test_FA_real_JPM_is_exempt_and_never_counted_as_pass() -> None:
    report = compute_fundamentals(stock("JPM", "Financials"), recorded("JPM"), AS_OF)
    assert report.framework_status == FrameworkStatus.NOT_APPLICABLE
    assert report.passed_count == 0 and report.failure_reasons == ()
    assert all(item.status == MetricStatus.NOT_MEANINGFUL for item in report.metrics)
    assert framework_allows(report, FundamentalsConfig(mode="require"))


def test_FA_real_AAPL_noncalendar_TTM_missing_interest_is_incomplete() -> None:
    report = compute_fundamentals(stock("AAPL"), recorded("AAPL"), AS_OF)
    with localcontext() as context:
        context.prec = 80
        # Millions USD: September27 FY + June27 YTD - June28 prior YTD.
        revenue = Decimal(416161 + 364357 - 313695)
        op = Decimal(133050 + 122432 - 100623)
        tax = Decimal(20719 + 21638 - 15381)
        pretax = Decimal(132729 + 123102 - 99925)
        invested = (
            Decimal(107520 + 82300 + 1997 - 39544) + Decimal(65830 + 91800 + 9923 - 36269)
        ) / 2
        expected = (
            Decimal(195201 + 178782 - 146860) / revenue,
            op / revenue,
            op * (1 - tax / pretax) / invested,
            Decimal((111482 + 116996 - 81754) - (12715 + 6799 - 9473)) * 1000000,
            None,
        )
    assert_values(report, expected)
    assert report.basis == "TTM" and report.latest_period_end == date(2026, 6, 27)
    assert report.framework_status == FrameworkStatus.INCOMPLETE and report.passed_count == 4
    assert report.metrics[4].status == MetricStatus.INSUFFICIENT_DATA
    assert not framework_allows(report, FundamentalsConfig(mode="require"))


def test_FA_real_SNAP_negative_operating_and_overlapping_debt() -> None:
    report = compute_fundamentals(stock("SNAP", "Communication Services"), recorded("SNAP"), AS_OF)
    with localcontext() as context:
        context.prec = 80
        revenue = Decimal(5931447000 + 3127784000 - 2708147000)
        cost = Decimal(2669575000 + 1333126000 - 1292912000)
        op = Decimal(-532167000 - 245170000 + 453522000)
        # LongTermDebt3534607000 already includes short153159000:
        # 3381448000 noncurrent + 153159000 short == 3534607000 total.
        invested = (
            Decimal(1927088000 + 3534607000 - 958848000)
            + Decimal(2069357000 + 3575972000 - 925973000)
        ) / 2
        expected = (
            (revenue - cost) / revenue,
            op / revenue,
            op * Decimal("0.79") / invested,
            Decimal((656170000 + 502993000 - 240104000) - (218981000 + 96448000 - 101915000)),
            op / (121998000 + 73697000 - 51006000),
        )
    assert_values(report, expected)
    assert report.framework_status == FrameworkStatus.FAIL and report.passed_count == 2
    assert report.metrics[4].note == "nonpositive operating income"


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize(
    "increment,status", [("0", MetricStatus.FAIL), ("0.0001", MetricStatus.PASS)]
)
def test_FA_exact_thresholds_are_strict(index: int, increment: str, status: MetricStatus) -> None:
    item = MetricResult(
        name=NAMES[index],
        value=THRESHOLDS[index] + Decimal(increment),
        threshold=THRESHOLDS[index],
        status=status,
        source_tags=("Revenues",),
        period_end=END,
        note="boundary evidence",
    )
    assert item.status == status
    with pytest.raises(ValidationError):
        MetricResult.model_validate(
            {
                **item.model_dump(),
                "status": MetricStatus.FAIL if status == MetricStatus.PASS else MetricStatus.PASS,
            }
        )


@pytest.mark.parametrize(
    "asset",
    [AssetClass.BROAD_ETF, AssetClass.SECTOR_ETF, AssetClass.COMMODITY_ETF, AssetClass.CASH_EQUIV],
)
def test_FA_nonstock_not_applicable(asset: AssetClass) -> None:
    instrument = Instrument.model_validate({**stock().model_dump(), "asset_class": asset})
    assert (
        compute_fundamentals(instrument, None, AS_OF).framework_status
        == FrameworkStatus.NOT_APPLICABLE
    )


def test_FA_no_debt_missing_or_zero_interest_passes_only_with_positive_op() -> None:
    for interest in (None, 0):
        data = synthetic()
        set_value(data, "LongTermDebt", 0)
        if interest is None:
            del data["facts"]["us-gaap"]["InterestExpense"]
        else:
            set_value(data, "InterestExpense", interest)
        item = metric(data, 4)
        assert item.status == MetricStatus.PASS and item.value is None and item.note == "no debt"
        set_value(data, "OperatingIncomeLoss", 0)
        item = metric(data, 4)
        assert item.status == MetricStatus.FAIL and item.note == "nonpositive operating income"


@pytest.mark.parametrize("equity", [0, -100])
def test_FA_nonpositive_invested_capital_is_not_meaningful(equity: int) -> None:
    data = synthetic()
    set_value(data, "StockholdersEquity", equity)
    set_value(data, "LongTermDebt", 0)
    set_value(data, "CashAndCashEquivalentsAtCarryingValue", 0)
    assert metric(data, 2).status == MetricStatus.NOT_MEANINGFUL


@pytest.mark.parametrize("revenue", [0, -10])
def test_FA_nonpositive_revenue_never_passes_margins(revenue: int) -> None:
    data = synthetic()
    set_value(data, "Revenues", revenue)
    report = compute_fundamentals(stock(), evidence(data), AS_OF)
    assert all(item.status == MetricStatus.NOT_MEANINGFUL for item in report.metrics[:2])


def test_FA_future_filing_ignored_latest_visible_amendment_wins() -> None:
    data = synthetic()
    rows(data, "Revenues").extend(
        [
            {**rows(data, "Revenues")[0], "val": 2000, "filed": "2026-10-04", "form": "10-K/A"},
            {**rows(data, "Revenues")[0], "val": 1, "filed": "2026-10-06", "form": "10-K/A"},
        ]
    )
    report = compute_fundamentals(stock(), evidence(data), AS_OF)
    assert report.metrics[0].value == Decimal("0.25")
    assert report.latest_filing_date == date(2026, 10, 4)
    # The SEC payload has date-only publication precision; NY date governs eligibility.
    midnight_utc = datetime(2026, 10, 4, 0, 1, tzinfo=UTC)
    assert compute_fundamentals(stock(), evidence(data), midnight_utc).metrics[0].value == Decimal(
        "0.5"
    )


def test_FA_stale_exact_age_boundary_and_disabled_missing_nonUSD() -> None:
    data = synthetic()
    payload = evidence(data)
    for day, stale in ((16, False), (17, True)):
        report = compute_fundamentals(stock(), payload, datetime(2027, 1, day, 18, tzinfo=UTC))
        assert (report.framework_status == FrameworkStatus.INCOMPLETE) == stale
    for tag in data["facts"]["us-gaap"].values():
        tag["units"]["EUR"] = tag["units"].pop("USD")
    for candidate, config in (
        (None, FundamentalsConfig()),
        (payload, FundamentalsConfig(enabled=False)),
        (evidence(data), FundamentalsConfig()),
    ):
        report = compute_fundamentals(stock(), candidate, AS_OF, config)
        assert report.passed_count == 0 and report.framework_status == FrameworkStatus.INCOMPLETE
        assert framework_allows(report, FundamentalsConfig())
        assert not framework_allows(report, FundamentalsConfig(mode="require"))


def test_FA_TTM_Q4_derived_from_FY_and_nine_month_YTD() -> None:
    data = synthetic()
    # For every duration, FY + current Q1 - prior Q1 = TTM. Prior FY can
    # include a derived Q4 without ever needing an explicit quarterly fact.
    for tag in data["facts"]["us-gaap"]:
        original = rows(data, tag)[0]
        if "start" not in original:
            rows(data, tag).append({**original, "end": "2026-09-30", "filed": "2026-10-04"})
            continue
        rows(data, tag).extend(
            [
                {
                    **original,
                    "start": "2026-07-01",
                    "end": "2026-09-30",
                    "val": original["val"] // 2,
                    "filed": "2026-10-04",
                    "form": "10-Q",
                },
                {
                    **original,
                    "end": "2025-09-30",
                    "val": original["val"] // 4,
                    "filed": "2026-10-04",
                    "form": "10-Q",
                },
            ]
        )
    report = compute_fundamentals(stock(), evidence(data), AS_OF)
    assert report.basis == "TTM" and report.latest_period_end == date(2026, 9, 30)
    assert report.metrics[3].value == Decimal(250)  # (300+150-75) - (100+50-25)
    assert report.metrics[2].value == Decimal("0.20")  # 250 * .8 / IC1000
    rows(data, "GrossProfit").pop()
    assert metric(data, 0).status == MetricStatus.INSUFFICIENT_DATA
    for tag in data["facts"]["us-gaap"]:
        rows(data, tag)[:] = [row for row in rows(data, tag) if row.get("end") != "2025-09-30"]
    assert compute_fundamentals(stock(), evidence(data), AS_OF).passed_count == 0


@pytest.mark.parametrize(
    "pretax,tax,expected",
    [
        (200, 100, "0.13"),
        (200, -20, "0.20"),
        (0, 40, "0.158"),
        (-1, 40, "0.158"),
        (None, 40, "0.158"),
        (200, None, None),
    ],
)
def test_FA_tax_clamp_and_fallback_scope(
    pretax: int | None, tax: int | None, expected: str | None
) -> None:
    data = synthetic()
    for tag, value in (
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            pretax,
        ),
        ("IncomeTaxExpenseBenefit", tax),
    ):
        if value is None:
            del data["facts"]["us-gaap"][tag]
        else:
            set_value(data, tag, value)
    item = metric(data, 2)
    assert item.value == (None if expected is None else Decimal(expected))


def test_FA_total_debt_precedence_short_overlap_and_separate_commercial_paper() -> None:
    data = synthetic()
    for tag, value in (
        ("LongTermDebtNoncurrent", 150),
        ("LongTermDebtCurrent", 50),
        ("ShortTermBorrowings", 70),
        ("CommercialPaper", 20),
    ):
        data["facts"]["us-gaap"][tag] = copy.deepcopy(data["facts"]["us-gaap"]["LongTermDebt"])
        set_value(data, tag, value)
    # LT200 + (short70 - included current50) =220. CP20 is inside short70.
    with localcontext() as context:
        context.prec = 80
        expected = Decimal(160) / 1020
    assert metric(data, 2).value == expected
    del data["facts"]["us-gaap"]["LongTermDebt"]
    assert metric(data, 2).value == expected  # noncurrent+current fallback
    del data["facts"]["us-gaap"]["ShortTermBorrowings"]
    assert metric(data, 2).value == expected  # separate CP20
    del data["facts"]["us-gaap"]["LongTermDebtCurrent"]
    assert metric(data, 2).status == MetricStatus.INSUFFICIENT_DATA


@pytest.mark.parametrize(
    "field,value",
    [
        ("value", float("nan")),
        ("value", float("inf")),
        ("value", 0.5),
        ("value", True),
        ("value", "1e129"),
        ("value", "NaN"),
        ("threshold", "0.39"),
        ("source_tags", ("Revenues", "Revenues")),
        ("period_end", None),
        ("source_tags", ()),
    ],
)
def test_FA_metric_contract_rejects_unverifiable_values(field: str, value: object) -> None:
    data: dict[str, Any] = dict(
        name="gross_margin",
        value=Decimal("0.5"),
        threshold=Decimal("0.4"),
        status=MetricStatus.PASS,
        source_tags=("Revenues",),
        period_end=END,
        note="synthetic",
    )
    data[field] = value
    with pytest.raises(ValidationError):
        MetricResult.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("passed_count", 4),
        ("framework_status", FrameworkStatus.FAIL),
        ("metrics", ()),
        ("failure_reasons", ("invented",)),
        ("latest_filing_date", date(2026, 10, 6)),
        ("latest_period_end", date(2026, 1, 1)),
    ],
)
def test_FA_report_revalidates_all_deterministic_claims(field: str, value: object) -> None:
    report = compute_fundamentals(stock(), evidence(synthetic()), AS_OF)
    corrupt = report.model_copy(update={field: value})
    with pytest.raises(ValidationError):
        FundamentalReport.model_validate(corrupt)


@pytest.mark.parametrize(
    "mutation",
    [
        "conflict",
        "bad_date",
        "bad_value",
        "nonobject",
        "bad_units",
        "bad_taxonomy",
        "future_period",
    ],
)
def test_FA_malformed_public_facts_have_typed_errors(mutation: str) -> None:
    data = synthetic()
    if mutation == "conflict":
        rows(data, "Revenues").append({**rows(data, "Revenues")[0], "val": 10})
    elif mutation == "bad_date":
        rows(data, "Revenues")[0]["filed"] = "yesterday"
    elif mutation == "bad_value":
        set_value(data, "Revenues", "NaN")
    elif mutation == "nonobject":
        rows(data, "Revenues").append(None)  # type: ignore[arg-type]
    elif mutation == "bad_units":
        data["facts"]["us-gaap"]["Revenues"]["units"] = []
    elif mutation == "bad_taxonomy":
        data["facts"]["us-gaap"] = []
    else:
        rows(data, "Revenues")[0]["end"] = "2027-01-01"
    with pytest.raises(DataIntegrityError):
        compute_fundamentals(stock(), evidence(data), AS_OF)


def test_FA_same_input_has_identical_output_under_small_ambient_context() -> None:
    data = evidence(synthetic())
    expected = compute_fundamentals(stock(), data, AS_OF)
    with localcontext() as context:
        context.prec = 2
        assert compute_fundamentals(stock(), data, AS_OF) == expected


@pytest.mark.parametrize(
    "index,tag,at,above",
    [
        (0, "GrossProfit", "400", "400.1"),
        (1, "OperatingIncomeLoss", "150", "150.1"),
        (2, "OperatingIncomeLoss", "100", "100.1"),
        (3, "NetCashProvidedByUsedInOperatingActivities", "100", "100.0001"),
        (4, "OperatingIncomeLoss", "30", "30.001"),
    ],
)
def test_FA_computation_enforces_each_strict_threshold(
    index: int, tag: str, at: str, above: str
) -> None:
    data = synthetic()
    if index == 2:
        set_value(data, "IncomeTaxExpenseBenefit", 0)
    for value, expected in ((at, MetricStatus.FAIL), (above, MetricStatus.PASS)):
        set_value(data, tag, value)
        item = metric(data, index)
        assert item.status == expected
        assert item.value == THRESHOLDS[index] + (
            Decimal("0.0001") if expected == MetricStatus.PASS else 0
        )


@pytest.mark.parametrize("status", [MetricStatus.PASS, MetricStatus.FAIL])
def test_FA_absent_metric_cannot_claim_ordinary_pass_or_fail(status: MetricStatus) -> None:
    with pytest.raises(ValidationError):
        MetricResult(
            name="gross_margin",
            value=None,
            threshold=Decimal("0.4"),
            status=status,
            source_tags=(),
            period_end=None,
            note="missing evidence",
        )


@pytest.mark.parametrize("change", ["order", "not_applicable", "extra", "future_metric"])
def test_FA_report_rejects_structural_and_applicability_forgery(change: str) -> None:
    report = compute_fundamentals(stock(), evidence(synthetic()), AS_OF)
    values = report.model_dump()
    if change == "order":
        values["metrics"] = tuple(reversed(report.metrics))
    elif change == "not_applicable":
        values["framework_status"] = FrameworkStatus.NOT_APPLICABLE
    elif change == "future_metric":
        values["metrics"][0]["period_end"] = date(2026, 9, 30)
    else:
        values["approved"] = True
    with pytest.raises(ValidationError):
        FundamentalReport.model_validate(values)


@pytest.mark.parametrize(
    "change",
    [
        "negative_debt",
        "negative_cash",
        "ambiguous_short",
        "paper_exceeds_short",
        "missing_equity",
        "missing_op",
        "zero_interest",
        "negative_interest",
    ],
)
def test_FA_incomplete_or_nonmeaningful_evidence_never_becomes_a_pass(change: str) -> None:
    data = synthetic()
    index = 2
    if change == "negative_debt":
        set_value(data, "LongTermDebt", -1)
    elif change == "negative_cash":
        set_value(data, "CashAndCashEquivalentsAtCarryingValue", -1)
    elif change in {"ambiguous_short", "paper_exceeds_short"}:
        data["facts"]["us-gaap"]["ShortTermBorrowings"] = copy.deepcopy(
            data["facts"]["us-gaap"]["LongTermDebt"]
        )
        set_value(data, "ShortTermBorrowings", 20)
        if change == "paper_exceeds_short":
            for tag, value in (("LongTermDebtCurrent", 0), ("CommercialPaper", 30)):
                data["facts"]["us-gaap"][tag] = copy.deepcopy(
                    data["facts"]["us-gaap"]["LongTermDebt"]
                )
                set_value(data, tag, value)
    elif change == "missing_equity":
        del data["facts"]["us-gaap"]["StockholdersEquity"]
    elif change == "missing_op":
        del data["facts"]["us-gaap"]["OperatingIncomeLoss"]
        index = 4
    else:
        set_value(data, "InterestExpense", 0 if change == "zero_interest" else -1)
        index = 4
    assert metric(data, index).status in {
        MetricStatus.INSUFFICIENT_DATA,
        MetricStatus.NOT_MEANINGFUL,
    }


@pytest.mark.parametrize(
    "change",
    ["USD_not_list", "no_annual", "unsupported_form", "bad_facts", "wrong_kind", "naive_asof"],
)
def test_FA_input_provenance_and_period_availability(change: str) -> None:
    data = synthetic()
    if change == "USD_not_list":
        data["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = {}
    elif change == "no_annual":
        for tag in data["facts"]["us-gaap"]:
            for row in rows(data, tag):
                if "start" in row:
                    row["start"] = "2026-04-01"
    elif change == "unsupported_form":
        for tag in data["facts"]["us-gaap"]:
            rows(data, tag)[0]["form"] = "8-K"
    elif change == "bad_facts":
        data["facts"] = []
    payload = evidence(data)
    if change == "wrong_kind":
        payload = SecPayload.model_validate({**payload.model_dump(), "kind": "SUBMISSIONS"})
    instant = AS_OF.replace(tzinfo=None) if change == "naive_asof" else AS_OF
    if change in {"no_annual", "unsupported_form"}:
        assert (
            compute_fundamentals(stock(), payload, instant).framework_status
            == FrameworkStatus.INCOMPLETE
        )
    else:
        with pytest.raises(DataIntegrityError):
            compute_fundamentals(stock(), payload, instant)


@pytest.mark.parametrize("value", [True, 1.25])
def test_FA_exact_rejection_of_inexact_financial_number(value: object) -> None:
    with pytest.raises(
        ValueError, match=re.escape("fundamental numbers require exact Decimal/text/integer")
    ) as caught:
        fa._number(value)
    assert type(caught.value) is ValueError
    assert str(caught.value) == "fundamental numbers require exact Decimal/text/integer"


def test_FA_129_significant_digits_exceeds_fact_precision_bound() -> None:
    with pytest.raises(
        ValueError, match=re.escape("fundamental number is nonfinite or unbounded")
    ) as caught:
        fa._number("0." + "1" * 129)
    assert type(caught.value) is ValueError
    assert str(caught.value) == "fundamental number is nonfinite or unbounded"


def test_FA_recorded_report_rejection_keeps_exact_audit_message() -> None:
    with pytest.raises(
        DataIntegrityError, match=re.escape("FA-01: recorded fundamental facts are invalid")
    ) as caught:
        fa.FundamentalReport.from_recorded({})
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "FA-01: recorded fundamental facts are invalid"


@pytest.mark.parametrize(
    "fault,message",
    [
        ("taxonomy", "FA-02: SEC financial taxonomy is malformed"),
        ("usd", "FA-02: SEC USD facts are malformed or unbounded"),
        ("row", "FA-02: SEC fact is malformed"),
        ("date", "FA-02: SEC fact date/value is unverifiable"),
    ],
)
def test_FA_sec_fact_rejections_are_exact(fault: str, message: str) -> None:
    data = synthetic()
    if fault == "taxonomy":
        data["facts"]["us-gaap"] = []
    elif fault == "usd":
        data["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = ()
    elif fault == "row":
        data["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [[]]
    else:
        data["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["end"] = "2026-99-99"
    with pytest.raises(DataIntegrityError, match=re.escape(message)) as caught:
        fa._facts(data, AS_OF.date())
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == message


def test_FA_thirty_thousand_equal_sec_facts_are_within_the_ingress_bound() -> None:
    data = synthetic()
    rows = data["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    data["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = rows * 30000
    report = fa.compute_fundamentals(stock(), evidence(data), AS_OF)
    assert report.framework_status == fa.FrameworkStatus.PASS
    assert tuple(x.value for x in report.metrics) == (
        Decimal("0.5"),
        Decimal("0.2"),
        Decimal("0.16"),
        Decimal("200"),
        Decimal("20"),
    )
    assert report.passed_count == 5


def test_FA_failed_financial_metrics_have_exact_human_audit_reasons() -> None:
    values = [Decimal("0.20"), Decimal("0.10"), Decimal("0.05"), Decimal("0"), Decimal("2")]
    metrics = tuple(
        (
            fa.MetricResult(
                name=name,
                value=value,
                threshold=threshold,
                status=fa.MetricStatus.FAIL,
                source_tags=("Revenues",),
                period_end=END,
                note="recorded annual USD facts",
            )
            for name, value, threshold in zip(fa.NAMES, values, fa.THRESHOLDS, strict=True)
        )
    )
    assert fa.failure_reasons(metrics) == (
        "Gross margin 20.0% (needs >40%)",
        "Operating margin 10.0% (needs >15%)",
        "ROIC 5.0% (needs >10%)",
        "Free cash flow $0.00 (needs >$0)",
        "Interest coverage 2.0x (needs >3x)",
    )


@pytest.mark.parametrize(
    "enabled,expected", [(True, "filing evidence unavailable"), (False, "fundamentals disabled")]
)
def test_FA_unavailable_filing_explains_each_missing_metric(enabled: bool, expected: str) -> None:
    report = fa.compute_fundamentals(stock(), None, AS_OF, FundamentalsConfig(enabled=enabled))
    assert tuple(x.note for x in report.metrics) == (expected,) * 5
    assert all(x.value is None for x in report.metrics)
    assert report.passed_count == 0


@pytest.mark.parametrize(
    "tag,index,note",
    [
        ("GrossProfit", 0, "missing period-matched revenue or gross profit"),
        ("OperatingIncomeLoss", 1, "missing period-matched revenue or operating income"),
        ("PaymentsToAcquirePropertyPlantAndEquipment", 3, "missing period-matched CFO or CapEx"),
        ("NetCashProvidedByUsedInOperatingActivities", 3, "missing period-matched CFO or CapEx"),
    ],
)
def test_FA_missing_inputs_keep_the_exact_metric_reason(tag: str, index: int, note: str) -> None:
    data = synthetic()
    del data["facts"]["us-gaap"][tag]
    report = fa.compute_fundamentals(stock(), evidence(data), AS_OF)
    assert report.metrics[index].value is None
    assert report.metrics[index].note == note
    assert report.metrics[index].status == fa.MetricStatus.INSUFFICIENT_DATA


def test_FA_zero_revenue_is_not_meaningful_with_the_exact_reason() -> None:
    data = synthetic()
    set_value(data, "Revenues", 0)
    report = fa.compute_fundamentals(stock(), evidence(data), AS_OF)
    assert tuple(x.note for x in report.metrics[:2]) == ("nonpositive revenue",) * 2
    assert all(
        x.value is None and x.status == fa.MetricStatus.NOT_MEANINGFUL for x in report.metrics[:2]
    )


def test_FA_zero_invested_capital_is_not_meaningful_with_the_exact_reason() -> None:
    data = synthetic()
    set_value(data, "CashAndCashEquivalentsAtCarryingValue", 1100)
    report = fa.compute_fundamentals(stock(), evidence(data), AS_OF)
    assert report.metrics[2].value is None
    assert report.metrics[2].status == fa.MetricStatus.NOT_MEANINGFUL
    assert report.metrics[2].note == "nonpositive invested capital"
    assert report.failure_reasons == ("ROIC: not meaningful (nonpositive invested capital)",)


def test_FA_complete_financial_evidence_has_exact_notes_without_false_missing_flags() -> None:
    report = fa.compute_fundamentals(stock(), evidence(synthetic()), AS_OF)
    assert tuple(x.note for x in report.metrics) == ("period-matched USD filing evidence",) * 5
    assert report.framework_status == fa.FrameworkStatus.PASS


def test_FA_current_balances_without_an_annual_duration_are_unavailable_not_stale() -> None:
    data = synthetic()
    for concept in data["facts"]["us-gaap"].values():
        for row in concept["units"]["USD"]:
            if "start" in row:
                row["start"] = "2026-04-01"
    report = fa.compute_fundamentals(stock(), evidence(data), AS_OF)
    assert all(x.value is None for x in report.metrics)
    assert tuple(x.note for x in report.metrics) == ("non-USD or unavailable annual USD facts",) * 5
    assert report.framework_status == fa.FrameworkStatus.INCOMPLETE


@pytest.mark.parametrize(
    "interest,note,status",
    [
        (
            None,
            "missing period-matched operating income or interest",
            fa.MetricStatus.INSUFFICIENT_DATA,
        ),
        (
            0,
            "nonpositive interest with reported or unavailable debt",
            fa.MetricStatus.NOT_MEANINGFUL,
        ),
    ],
)
def test_FA_unknown_or_zero_interest_does_not_pass_with_reported_debt(
    interest: int | None, note: str, status: fa.MetricStatus
) -> None:
    data = synthetic()
    if interest is None:
        del data["facts"]["us-gaap"]["InterestExpense"]
    else:
        set_value(data, "InterestExpense", interest)
    report = fa.compute_fundamentals(stock(), evidence(data), AS_OF)
    assert report.metrics[4].value is None
    assert report.metrics[4].note == note
    assert report.metrics[4].status == status


def test_FA_unvalidated_issuer_is_rejected_with_the_exact_public_audit_message() -> None:
    invalid = stock().model_copy(update={"symbol": "bad ticker!"})
    message = "FA-01..09: public fundamentals cannot be computed from verified evidence"
    with pytest.raises(DataIntegrityError, match=re.escape(message)) as caught:
        fa.compute_fundamentals(invalid, evidence(synthetic()), AS_OF)
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == message
