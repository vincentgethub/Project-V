"""FA-01..09: pure point-in-time Decimal computation; no network or LLM."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator, Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.config import FundamentalsConfig
from backend.core.errors import DataIntegrityError
from backend.core.money import decimal_money
from backend.data.sec_edgar import SecPayload
from backend.domain.models import (
    AssetClass,
    FrozenModel,
    Instrument,
    SessionDate,
    Symbol,
    UTCDateTime,
)

MetricName = Literal[
    "gross_margin", "operating_margin", "roic", "free_cash_flow", "interest_coverage"
]
NAMES: tuple[MetricName, ...] = (
    "gross_margin",
    "operating_margin",
    "roic",
    "free_cash_flow",
    "interest_coverage",
)
THRESHOLDS = (Decimal("0.40"), Decimal("0.15"), Decimal("0.10"), Decimal("0"), Decimal("3.0"))
TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "gross": ("GrossProfit",),
    "cost": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "operating": ("OperatingIncomeLoss",),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "interest": (
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
    ),
    "tax": ("IncomeTaxExpenseBenefit",),
    "pretax": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "debt_total": ("LongTermDebt",),
    "debt_noncurrent": ("LongTermDebtNoncurrent",),
    "debt_current": ("LongTermDebtCurrent",),
    "short_debt": ("ShortTermBorrowings",),
    "paper": ("CommercialPaper",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
}


class MetricStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_MEANINGFUL = "NOT_MEANINGFUL"


class FrameworkStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValueError("fundamental numbers require exact Decimal/text/integer")
    result = value if isinstance(value, Decimal) else Decimal(value)
    if (
        not result.is_finite()
        or len(result.as_tuple().digits) > 128
        or abs(result.adjusted()) > 128
    ):
        raise ValueError("fundamental number is nonfinite or unbounded")
    return result


Number = Annotated[Decimal, BeforeValidator(_number)]
SourceTag = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9]{0,199}$")]


class MetricResult(FrozenModel):
    name: MetricName
    value: Number | None
    threshold: Number
    status: MetricStatus
    source_tags: tuple[SourceTag, ...] = Field(max_length=32)
    period_end: SessionDate | None
    note: str = Field(strict=True, max_length=280)

    @model_validator(mode="after")
    def exact_status(self) -> Self:
        if self.threshold != THRESHOLDS[NAMES.index(self.name)] or len(
            set(self.source_tags)
        ) != len(self.source_tags):
            raise ValueError("metric has a wrong threshold or duplicated source tag")
        if self.value is None:
            permitted_pass = self.name == "interest_coverage" and self.note == "no debt"
            permitted_fail = (
                self.name == "interest_coverage" and self.note == "nonpositive operating income"
            )
            if self.status == MetricStatus.PASS and not permitted_pass:
                raise ValueError("unavailable metric cannot pass")
            if self.status == MetricStatus.FAIL and not permitted_fail:
                raise ValueError("unavailable metric lacks known failure evidence")
        elif self.status not in {MetricStatus.PASS, MetricStatus.FAIL} or self.status != (
            MetricStatus.PASS if self.value > self.threshold else MetricStatus.FAIL
        ):
            raise ValueError("metric status must follow its strict numerical comparison")
        if self.status in {MetricStatus.PASS, MetricStatus.FAIL} and (
            not self.source_tags or self.period_end is None
        ):
            raise ValueError("pass/fail requires period-bound source evidence")
        return self


def failure_reasons(metrics: tuple[MetricResult, ...]) -> tuple[str, ...]:
    names = ("Gross margin", "Operating margin", "ROIC", "Free cash flow", "Interest coverage")
    result: list[str] = []
    with localcontext() as context:
        context.prec = 80
        for index, metric in enumerate(metrics):
            if metric.status == MetricStatus.PASS:
                continue
            if metric.value is None:
                result.append(
                    f"{names[index]}: {metric.status.value.lower().replace('_', ' ')} ({metric.note})"
                )
            elif index < 3:
                result.append(
                    f"{names[index]} {(metric.value * 100).quantize(Decimal('0.1'))}% (needs >{(metric.threshold * 100).normalize()}%)"
                )
            elif index == 3:
                result.append(f"Free cash flow ${metric.value:,.2f} (needs >$0)")
            else:
                result.append(
                    f"Interest coverage {metric.value.quantize(Decimal('0.1'))}x (needs >3x)"
                )
    return tuple(result)


def rollup(metrics: tuple[MetricResult, ...]) -> FrameworkStatus:
    if any(item.status == MetricStatus.FAIL for item in metrics):
        return FrameworkStatus.FAIL
    if all(item.status == MetricStatus.PASS for item in metrics):
        return FrameworkStatus.PASS
    return FrameworkStatus.INCOMPLETE


class FundamentalReport(FrozenModel):
    symbol: Symbol
    cik: str | None = Field(pattern=r"^[0-9]{10}$")
    as_of: UTCDateTime
    latest_filing_date: SessionDate | None
    latest_period_end: SessionDate | None
    basis: Literal["TTM", "FY"]
    metrics: tuple[MetricResult, ...] = Field(min_length=5, max_length=5)
    framework_status: FrameworkStatus
    passed_count: int = Field(strict=True, ge=0, le=5)
    failure_reasons: tuple[str, ...] = Field(max_length=5)
    data_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def consistent_report(self) -> Self:
        if tuple(item.name for item in self.metrics) != NAMES:
            raise ValueError("framework requires exactly five metrics in fixed order")
        if self.passed_count != sum(item.status == MetricStatus.PASS for item in self.metrics):
            raise ValueError("framework count must equal proven metric passes")
        today = self.as_of.astimezone(ZoneInfo("America/New_York")).date()
        if any(
            day is not None and day > today
            for day in (self.latest_filing_date, self.latest_period_end)
        ):
            raise ValueError("framework dates cannot follow its as-of date")
        if any(
            metric.period_end is not None
            and (self.latest_period_end is None or metric.period_end > self.latest_period_end)
            for metric in self.metrics
        ):
            raise ValueError("metric period cannot follow report provenance")
        if self.framework_status == FrameworkStatus.NOT_APPLICABLE:
            if (
                self.passed_count
                or self.failure_reasons
                or any(
                    item.status != MetricStatus.NOT_MEANINGFUL
                    or item.value is not None
                    or item.note != "framework not applicable"
                    for item in self.metrics
                )
            ):
                raise ValueError("not-applicable framework cannot claim passes or failures")
        elif self.framework_status != rollup(
            self.metrics
        ) or self.failure_reasons != failure_reasons(self.metrics):
            raise ValueError(
                "framework roll-up and reasons must match deterministic metric evidence"
            )
        return self


@dataclass(frozen=True)
class Fact:
    tag: str
    start: date | None
    end: date
    filed: date
    value: Decimal


def _facts(payload: dict[str, Any], as_of: date) -> dict[str, tuple[Fact, ...]]:
    taxonomy = payload.get("facts", {}).get("us-gaap", {})
    if not isinstance(taxonomy, Mapping):
        raise DataIntegrityError("FA-02: SEC financial taxonomy is malformed")
    result: dict[str, tuple[Fact, ...]] = {}
    for tag in (name for names in TAGS.values() for name in names):
        concept = taxonomy.get(tag, {})
        if not isinstance(concept, Mapping) or not isinstance(concept.get("units", {}), Mapping):
            raise DataIntegrityError("FA-02: SEC concept units are malformed")
        rows = concept.get("units", {}).get("USD", [])
        if not isinstance(rows, list) or len(rows) > 30000:
            raise DataIntegrityError("FA-02: SEC USD facts are malformed or unbounded")
        selected: dict[tuple[date | None, date], Fact] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise DataIntegrityError("FA-02: SEC fact is malformed")
            if row.get("form") not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
                continue
            try:
                filed = date.fromisoformat(row["filed"])
                if filed > as_of:
                    continue
                end = date.fromisoformat(row["end"])
                start = date.fromisoformat(row["start"]) if "start" in row else None
                if end > filed or (start is not None and start > end):
                    raise ValueError("unverifiable financial period")
                value = decimal_money(row["val"])
                current = Fact(tag, start, end, filed, value)
                key = (start, end)
                prior = selected.get(key)
                if prior is None or filed > prior.filed:
                    selected[key] = current
                elif filed == prior.filed and value != prior.value:
                    raise ValueError("conflicting facts filed on the same date")
            except Exception:
                raise DataIntegrityError("FA-02: SEC fact date/value is unverifiable") from None
        result[tag] = tuple(selected.values())
    return result


def _period(
    facts: dict[str, tuple[Fact, ...]], names: tuple[str, ...], start: date | None, end: date
) -> Fact | None:
    for tag in names:
        matches = [fact for fact in facts[tag] if fact.start == start and fact.end == end]
        if matches:
            return max(matches, key=lambda fact: fact.filed)
    return None


def _value(
    facts: dict[str, tuple[Fact, ...]],
    names: tuple[str, ...],
    periods: tuple[tuple[date, date], ...],
) -> tuple[Decimal | None, tuple[str, ...]]:
    chosen = [_period(facts, names, start, end) for start, end in periods]
    tags = tuple(dict.fromkeys(fact.tag for fact in chosen if fact is not None))
    if any(fact is None for fact in chosen):
        return None, tags
    amounts = tuple(fact.value for fact in chosen if fact is not None)
    return (amounts[0] if len(amounts) == 1 else amounts[0] + amounts[1] - amounts[2]), tags


def _balance(
    facts: dict[str, tuple[Fact, ...]], key: str, end: date
) -> tuple[Decimal | None, tuple[str, ...]]:
    fact = _period(facts, TAGS[key], None, end)
    return (None, ()) if fact is None else (fact.value, (fact.tag,))


def _debt(facts: dict[str, tuple[Fact, ...]], end: date) -> tuple[Decimal | None, tuple[str, ...]]:
    total, tags = _balance(facts, "debt_total", end)
    if total is None:
        noncurrent, a = _balance(facts, "debt_noncurrent", end)
        current, b = _balance(facts, "debt_current", end)
        tags = (*a, *b)
        if noncurrent is None or current is None:
            return None, tags
        total = noncurrent + current
    short, a = _balance(facts, "short_debt", end)
    paper, b = _balance(facts, "paper", end)
    # A reported aggregate short-term balance can already include commercial
    # paper. Its sum is used conservatively once; never add two overlapping
    # totals. A separate commercial-paper balance is added only without that
    # aggregate. LongTermDebt similarly supersedes its current/noncurrent parts.
    addition = short if short is not None else paper if paper is not None else Decimal(0)
    return total + addition, (*tags, *(a if short is not None else b))


def _capital(
    facts: dict[str, tuple[Fact, ...]], end: date
) -> tuple[Decimal | None, tuple[str, ...]]:
    equity, a = _balance(facts, "equity", end)
    debt, b = _debt(facts, end)
    cash, c = _balance(facts, "cash", end)
    tags = tuple(dict.fromkeys((*a, *b, *c)))
    if equity is None or debt is None or cash is None or debt < 0 or cash < 0:
        return None, tags
    return equity + debt - cash, tags


def compute_fundamentals(
    instrument: Instrument,
    payload: SecPayload | None,
    as_of: datetime,
    config: FundamentalsConfig | None = None,
) -> FundamentalReport:
    """FA-01..09: metrics/status/roll-up derive only from public filing facts."""
    try:
        instrument = Instrument.model_validate(instrument)
        config = FundamentalsConfig.model_validate(config or FundamentalsConfig())
        instant = ensure_utc(as_of)
        today = instant.astimezone(ZoneInfo("America/New_York")).date()
        evidence = SecPayload.model_validate(payload) if payload is not None else None
        if evidence is not None and evidence.kind != "COMPANYFACTS":
            raise DataIntegrityError("FA-02: framework needs issuer companyfacts evidence")
        metrics: list[MetricResult] = []
        latest: date | None = None
        filed: date | None = None
        basis: Literal["TTM", "FY"] = "FY"

        def metric(
            index: int,
            value: Decimal | None,
            tags: tuple[str, ...],
            note: str = "",
            status: MetricStatus | None = None,
        ) -> None:
            resolved = status or (
                MetricStatus.INSUFFICIENT_DATA
                if value is None
                else MetricStatus.PASS
                if value > THRESHOLDS[index]
                else MetricStatus.FAIL
            )
            metrics.append(
                MetricResult(
                    name=NAMES[index],
                    value=value,
                    threshold=THRESHOLDS[index],
                    status=resolved,
                    source_tags=tuple(dict.fromkeys(tags)),
                    period_end=latest,
                    note=note,
                )
            )

        applicable = (
            instrument.asset_class == AssetClass.STOCK
            and instrument.gics_sector not in config.exempt_sectors
        )
        if not applicable:
            for index in range(5):
                metric(index, None, (), "framework not applicable", MetricStatus.NOT_MEANINGFUL)
        elif evidence is None or not config.enabled:
            for index in range(5):
                metric(
                    index,
                    None,
                    (),
                    "filing evidence unavailable" if config.enabled else "fundamentals disabled",
                )
        else:
            with localcontext() as context:
                context.prec = 80
                facts = _facts(evidence.parsed(), today)
                available = tuple(fact for values in facts.values() for fact in values)
                latest = max((fact.end for fact in available), default=None)
                filed = max((fact.filed for fact in available), default=None)
                annuals = [
                    fact
                    for key in ("revenue", "operating", "cfo")
                    for tag in TAGS[key]
                    for fact in facts[tag]
                    if fact.start is not None and 335 <= (fact.end - fact.start).days <= 395
                ]
                if (
                    latest is None
                    or (today - latest).days > config.max_filing_age_days
                    or not annuals
                ):
                    note = (
                        "non-USD or unavailable annual USD facts"
                        if latest is None or not annuals
                        else "financial period older than the allowed filing age"
                    )
                    for index in range(5):
                        metric(index, None, (), note)
                else:
                    annual = max(annuals, key=lambda fact: (fact.end, fact.filed))
                    assert annual.start is not None
                    periods = ((annual.start, annual.end),)
                    newer = [
                        fact
                        for key in ("revenue", "operating", "cfo")
                        for tag in TAGS[key]
                        for fact in facts[tag]
                        if fact.start is not None
                        and fact.end > annual.end
                        and 1 <= (fact.start - annual.end).days <= 11
                    ]
                    if newer:
                        current = max(
                            newer,
                            key=lambda fact: (
                                fact.end,
                                -(fact.start - annual.end).days if fact.start is not None else 0,
                            ),
                        )
                        assert current.start is not None
                        prior_year = [
                            fact
                            for key in ("revenue", "operating", "cfo")
                            for tag in TAGS[key]
                            for fact in facts[tag]
                            if fact.start is not None
                            and abs((current.end - fact.end).days - 365) <= 10
                            and abs(
                                (current.end - current.start).days - (fact.end - fact.start).days
                            )
                            <= 10
                        ]
                        basis = "TTM"
                        if prior_year:
                            prior = max(prior_year, key=lambda fact: (fact.end, fact.filed))
                            assert prior.start is not None
                            periods = (
                                *periods,
                                (current.start, current.end),
                                (prior.start, prior.end),
                            )
                        else:
                            periods = ()
                    values = {
                        key: _value(facts, TAGS[key], periods) if periods else (None, ())
                        for key in (
                            "revenue",
                            "gross",
                            "cost",
                            "operating",
                            "cfo",
                            "capex",
                            "interest",
                            "tax",
                            "pretax",
                        )
                    }
                    revenue, rev_tags = values["revenue"]
                    gross, gross_tags = values["gross"]
                    cost, cost_tags = values["cost"]
                    op, op_tags = values["operating"]
                    if revenue is not None and revenue <= 0:
                        metric(
                            0, None, rev_tags, "nonpositive revenue", MetricStatus.NOT_MEANINGFUL
                        )
                        metric(
                            1, None, rev_tags, "nonpositive revenue", MetricStatus.NOT_MEANINGFUL
                        )
                    else:
                        if gross is None and revenue is not None and cost is not None:
                            gross, gross_tags = revenue - cost, (*rev_tags, *cost_tags)
                        metric(
                            0,
                            None if gross is None or revenue is None else gross / revenue,
                            (*gross_tags, *rev_tags),
                            "missing period-matched revenue or gross profit"
                            if gross is None or revenue is None
                            else "",
                        )
                        metric(
                            1,
                            None if op is None or revenue is None else op / revenue,
                            (*op_tags, *rev_tags),
                            "missing period-matched revenue or operating income"
                            if op is None or revenue is None
                            else "",
                        )
                    current_capital, capital_tags = _capital(facts, latest)
                    debt, debt_tags = _debt(facts, latest)
                    prior_instants = [
                        fact.end
                        for tag in TAGS["equity"]
                        for fact in facts[tag]
                        if fact.start is None and abs((latest - fact.end).days - 365) <= 20
                    ]
                    previous_capital, previous_tags = (
                        _capital(facts, max(prior_instants)) if prior_instants else (None, ())
                    )
                    average = (
                        current_capital
                        if previous_capital is None
                        else None
                        if current_capital is None
                        else (current_capital + previous_capital) / 2
                    )
                    tax, tax_tags = values["tax"]
                    pretax, pretax_tags = values["pretax"]
                    tax_rate = (
                        Decimal("0.21")
                        if pretax is None or pretax <= 0 or tax is None
                        else max(Decimal(0), min(Decimal("0.35"), tax / pretax))
                    )
                    roic_tags = (*op_tags, *capital_tags, *previous_tags, *tax_tags, *pretax_tags)
                    if current_capital is not None and (
                        current_capital <= 0
                        or (previous_capital is not None and previous_capital <= 0)
                    ):
                        metric(
                            2,
                            None,
                            roic_tags,
                            "nonpositive invested capital",
                            MetricStatus.NOT_MEANINGFUL,
                        )
                    else:
                        metric(
                            2,
                            None
                            if op is None or average is None
                            else op * (1 - tax_rate) / average,
                            roic_tags,
                            "missing operating income or invested capital"
                            if op is None or average is None
                            else "tax rate fallback 0.21"
                            if pretax is None or pretax <= 0 or tax is None
                            else "",
                        )
                    cfo, cfo_tags = values["cfo"]
                    capex, capex_tags = values["capex"]
                    metric(
                        3,
                        None if cfo is None or capex is None else cfo - capex,
                        (*cfo_tags, *capex_tags),
                        "missing period-matched CFO or CapEx"
                        if cfo is None or capex is None
                        else "",
                    )
                    interest, interest_tags = values["interest"]
                    coverage_tags = (*op_tags, *interest_tags, *debt_tags)
                    if op is not None and op <= 0:
                        metric(
                            4,
                            None if interest is None or interest <= 0 else op / interest,
                            coverage_tags,
                            "nonpositive operating income",
                            MetricStatus.FAIL,
                        )
                    elif op is not None and (interest is None or interest == 0) and debt == 0:
                        metric(4, None, coverage_tags, "no debt", MetricStatus.PASS)
                    elif interest is not None and interest <= 0:
                        metric(
                            4,
                            None,
                            coverage_tags,
                            "nonpositive interest with reported or unavailable debt",
                            MetricStatus.NOT_MEANINGFUL,
                        )
                    else:
                        metric(
                            4,
                            None if op is None or interest is None else op / interest,
                            coverage_tags,
                            "missing period-matched operating income or interest"
                            if op is None or interest is None
                            else "",
                        )
        result = tuple(metrics)
        return FundamentalReport(
            symbol=instrument.symbol,
            cik=None if evidence is None else evidence.cik,
            as_of=instant,
            latest_filing_date=filed,
            latest_period_end=latest,
            basis=basis,
            metrics=result,
            framework_status=rollup(result) if applicable else FrameworkStatus.NOT_APPLICABLE,
            passed_count=sum(item.status == MetricStatus.PASS for item in result),
            failure_reasons=failure_reasons(result) if applicable else (),
            data_sha256=evidence.data_sha256
            if evidence is not None
            else "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError(
            "FA-01..09: public fundamentals cannot be computed from verified evidence"
        ) from None


def framework_allows(report: FundamentalReport, config: FundamentalsConfig) -> bool:
    """FA-08: this never adjusts a setup's score, levels or size."""
    report = FundamentalReport.model_validate(report)
    config = FundamentalsConfig.model_validate(config)
    return config.mode == "annotate" or report.framework_status in {
        FrameworkStatus.PASS,
        FrameworkStatus.NOT_APPLICABLE,
    }
