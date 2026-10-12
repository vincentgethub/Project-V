"""EV-02/ER-03..05: after-cost weekly text and CSV, with explicit evidence gaps."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from backend.core.config import CostModelConfig
from backend.core.errors import DataIntegrityError
from backend.data.history import Digest, FrozenHistory, canonical_bytes, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, Identifier, Money, Playbook, SessionDate
from backend.domain.tax_profile import TAX_ESTIMATE_NOTICE, TaxProfile
from backend.evaluation.calibrated_costs import CostCalibration
from backend.evaluation.costs import Exact, FeeSchedule, Note, after_tax_year, cost_policy_sha256
from backend.evaluation.dividends import NOTICE as DISTRIBUTION_NOTICE
from backend.evaluation.edge import EdgeCard, EdgeKey, summarize_edge
from backend.evaluation.equity import _selected, build_equity_curve
from backend.evaluation.fill_quality import DriftCheck, QualityBucket
from backend.evaluation.outcomes import Cohort, Outcome
from backend.evaluation.security_summary import WeeklySecurity, render_security
from backend.evaluation.universe import PIT_NOTICE
from backend.indicators.statistics import BootstrapEstimate
from backend.ops.anchors import controlled_path

DISCLAIMER = "Hypothetical/past results; not indicative of future returns."
SOURCE_NOTICE = "EV-01 hypothetical tracker; paper/live labels identify the account, not actual broker performance."
DIVIDEND_NOTICE = "Strategy dividends ignored; SPY comparison uses ALL-adjusted closes including vendor dividend adjustments."
SURVIVORSHIP_NOTICE = (
    "Survivorship-bias warning: the watchlist is today's; historical delisted names may be absent."
)
TAX_NOTICE = "Rough; every trade treated as short-term; wash sales and carryovers ignored."
SYNTHETIC_NOTICE = (
    "SYNTHETIC OFFLINE FIXTURES: generated prices and filings, not observed market/account results."
)


def _key(key: EdgeKey) -> tuple[str, str, str, str, str]:
    return (
        key.playbook.value,
        key.variant,
        key.cohort,
        key.disposition,
        "" if key.fundamentals_status is None else key.fundamentals_status.value,
    )


class ReportContext(FrozenModel):
    account_id: Identifier = Field(max_length=128)
    cohort: Cohort
    start: SessionDate
    end: SessionDate
    config_sha256: Digest
    initial_equity: Money | None = Field(default=None, gt=0)
    synthetic: bool = Field(default=False, strict=True)
    universe_sha256: Digest | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("EV-02: report needs an ordered multi-session period")
        if self.synthetic and not self.cohort.startswith("REPLAY"):
            raise ValueError("EV-02: synthetic evidence cannot represent a managed account")
        return self


class TaxYearEstimate(FrozenModel):
    key: EdgeKey
    year: int = Field(strict=True, ge=1900, le=9999)
    net_gains: Money
    rough_after_tax: Money | None


class FilterComparison(FrozenModel):
    playbook: Playbook
    variant: str = Field(strict=True, pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    cohort: Cohort
    filter: Literal["CRO_VETO", "RS_FILTER", "PR_FILTER", "SZ_FILTER"]
    taken_n: int = Field(strict=True, ge=0)
    filtered_n: int = Field(strict=True, ge=0)
    taken_expectancy_r: Exact | None
    filtered_expectancy_r: Exact | None


class WeeklyReport(FrozenModel):
    context: ReportContext
    manifest_sha256: Digest
    fee_schedule_sha256: Digest
    cost_policy_sha256: Digest
    tax_profile: TaxProfile
    cards: tuple[EdgeCard, ...] = Field(max_length=1024)
    equity_notes: tuple[Note, ...] = Field(max_length=1024)
    spy_buy_hold_pct: Exact | None
    tax_years: tuple[TaxYearEstimate, ...] = Field(max_length=10000)
    filters: tuple[FilterComparison, ...] = Field(max_length=1024)
    notes: tuple[Note, ...] = Field(min_length=4, max_length=30)
    security: WeeklySecurity | None = None
    fill_quality: tuple[QualityBucket, ...] = Field(
        default=(), max_length=36, exclude_if=lambda v: not v
    )
    calibration: CostCalibration = Field(
        default_factory=CostCalibration, exclude_if=lambda v: v.scope is None
    )
    drift: tuple[DriftCheck, ...] = Field(default=(), max_length=4, exclude_if=lambda v: not v)

    @classmethod
    def from_recorded(cls, payload: dict[str, Any]) -> WeeklyReport:
        try:
            values = dict(payload)
            context = dict(values["context"])
            for name in ("start", "end"):
                context[name] = date.fromisoformat(context[name])
            values["context"] = context
            if "calibration" in values:
                values["calibration"] = CostCalibration.recorded(values["calibration"])
            if values.get("security") is not None:
                security = dict(values["security"])
                for name in ("start", "as_of"):
                    security[name] = (
                        None if security[name] is None else datetime.fromisoformat(security[name])
                    )
                security["credentials"] = tuple(
                    {
                        **item,
                        "last_rotated": None
                        if item["last_rotated"] is None
                        else datetime.fromisoformat(item["last_rotated"]),
                    }
                    for item in security["credentials"]
                )
                if security["latest_anchor"] is not None:
                    anchor = dict(security["latest_anchor"])
                    anchor["created_at"] = datetime.fromisoformat(anchor["created_at"])
                    security["latest_anchor"] = anchor
                security["checks"] = tuple(
                    {
                        **item,
                        "at": None if item["at"] is None else datetime.fromisoformat(item["at"]),
                    }
                    for item in security["checks"]
                )
                values["security"] = security
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("EV-02: recorded report is unverifiable") from None

    @model_validator(mode="after")
    def bound_cards(self) -> Self:
        if self.drift and (
            self.context.cohort != "PAPER"
            or any(row.scope.account_id != self.context.account_id for row in self.drift)
            or len({row.playbook for row in self.drift}) != len(self.drift)
        ):
            raise ValueError(
                "XA-02: paper drift must bind to unique playbooks and one paper account"
            )
        if (
            self.calibration.scope is not None
            and self.context.cohort in {"PAPER", "LIVE"}
            and (
                self.calibration.scope.account_id != self.context.account_id
                or self.calibration.scope.environment != self.context.cohort
            )
        ):
            raise ValueError(
                "XA-01: report calibration cannot mix physical accounts or environments"
            )
        if any(
            row.scope.account_id != self.context.account_id
            or row.scope.environment != self.context.cohort
            for row in self.fill_quality
        ):
            raise ValueError("XA-01: monthly quality table cannot mix physical account cohorts")
        keys = tuple(_key(card.key) for card in self.cards)
        if keys != tuple(sorted(set(keys))) or len(self.equity_notes) != len(self.cards):
            raise ValueError("ER: report cards must be unique, ordered and have equity notes")
        if any(
            card.key.cohort != self.context.cohort
            or card.manifest_sha256 != self.manifest_sha256
            or card.fee_schedule_sha256 != self.fee_schedule_sha256
            for card in self.cards
        ):
            raise ValueError("ER: report cannot mix account cohorts, histories or fee versions")
        if (
            self.notes[:3]
            != (
                DISCLAIMER,
                SOURCE_NOTICE,
                DISTRIBUTION_NOTICE
                if self.context.cohort.startswith("REPLAY")
                else DIVIDEND_NOTICE,
            )
            or TAX_ESTIMATE_NOTICE not in self.notes
        ):
            raise ValueError("EV-02: fixed result, source, dividend and tax disclosures required")
        if (
            self.context.cohort.startswith("REPLAY")
            and (PIT_NOTICE if self.context.universe_sha256 is not None else SURVIVORSHIP_NOTICE)
            not in self.notes
        ):
            raise ValueError("EV-03: replay reports require the survivorship warning")
        if (SYNTHETIC_NOTICE in self.notes) != self.context.synthetic:
            raise ValueError("EV-03: synthetic evidence must keep its source label")
        tax_keys = tuple((_key(item.key), item.year) for item in self.tax_years)
        if tax_keys != tuple(sorted(set(tax_keys))) or any(
            _key(item.key) not in keys
            or not self.context.start.year <= item.year <= self.context.end.year
            for item in self.tax_years
        ):
            raise ValueError("EV-02: tax rows must bind to unique report cards and years")
        if any(
            item.rough_after_tax != after_tax_year(item.net_gains, self.tax_profile)
            for item in self.tax_years
        ):
            raise ValueError("CM-05: tax estimate differs from the recorded profile")
        overall = {
            (card.key.playbook, card.key.variant, card.key.disposition): card
            for card in self.cards
            if card.key.fundamentals_status is None
        }
        comparisons = tuple(
            (item.playbook.value, item.variant, item.filter) for item in self.filters
        )
        if comparisons != tuple(sorted(set(comparisons))):
            raise ValueError("ER-04: filter comparisons must be unique and ordered")
        for item in self.filters:
            taken = overall.get((item.playbook, item.variant, "APPROVED"))
            filtered = overall.get((item.playbook, item.variant, item.filter))
            if (
                item.cohort != self.context.cohort
                or filtered is None
                or item.filtered_n != filtered.n
                or item.filtered_expectancy_r != filtered.expectancy_r
                or item.taken_n != (0 if taken is None else taken.n)
                or item.taken_expectancy_r != (None if taken is None else taken.expectancy_r)
            ):
                raise ValueError("ER-04: filter comparison differs from its report cards")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def build_weekly_report(
    context: ReportContext,
    outcomes: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
    policy: CostModelConfig,
    tax_profile: TaxProfile,
    *,
    security: WeeklySecurity | None = None,
    calibration: CostCalibration | None = None,
) -> WeeklyReport:
    """One card per playbook/variant/status, plus explicit fundamental subgroups.

    Subgroup rows overlap the overall rows and are never added together. Empty,
    incomplete, or unfunded equity is shown as unavailable. No DSR is invented.
    """
    try:
        bound = ReportContext.model_validate(context)
        frozen = FrozenHistory.model_validate(history)
        validate_history(frozen.bundle, calendar)
        fees = FeeSchedule.model_validate(schedule)
        costs = CostModelConfig.model_validate(policy)
        taxes = TaxProfile.model_validate(tax_profile)
        if not isinstance(outcomes, tuple) or len(outcomes) > 100000:
            raise ValueError("bounded immutable outcomes required")
        checked = tuple(Outcome.model_validate(item) for item in outcomes)
        if len({item.setup.alert_id for item in checked}) != len(checked) or any(
            item.setup.cohort != bound.cohort
            or item.manifest_sha256 != frozen.manifest.sha256
            or item.fee_schedule_sha256 != fees.sha256
            or item.cost_policy_sha256 != cost_policy_sha256(costs)
            or not bound.start <= item.setup.decision_session <= bound.end
            or (item.exit_session is not None and item.exit_session > bound.end)
            for item in checked
        ):
            raise ValueError("report outcome account/cohort/hash/date binding differs")
        if not calendar.is_session(bound.start) or not calendar.is_session(bound.end):
            raise ValueError("report endpoints require XNYS sessions")
        grouped: dict[tuple[str, str, str, str, str], EdgeKey] = {}
        for item in checked:
            for status in (None, item.setup.fundamentals_status):
                key = EdgeKey(
                    playbook=item.setup.playbook,
                    variant=item.setup.variant,
                    cohort=item.setup.cohort,
                    disposition=item.setup.disposition,
                    fundamentals_status=status,
                )
                grouped[_key(key)] = key
        cards: list[EdgeCard] = []
        equity_notes: list[str] = []
        estimates: list[TaxYearEstimate] = []
        for identity in sorted(grouped):
            key = grouped[identity]
            rows = tuple(item for item in checked if _selected(key, item))
            curve = None
            note = "Initial equity unavailable; no simulated portfolio statistics"
            if bound.initial_equity is not None:
                built = build_equity_curve(
                    key,
                    rows,
                    frozen,
                    calendar,
                    initial_equity=bound.initial_equity,
                    start=bound.start,
                    end=bound.end,
                )
                curve, note = built.curve, built.reason
            cards.append(summarize_edge(key, rows, calendar=calendar, curve=curve))
            equity_notes.append(note)
            years: dict[int, Decimal] = {}
            with localcontext() as precision:
                precision.prec = 256
                for item in rows:
                    if item.exit_session is not None and item.net_money is not None:
                        years[item.exit_session.year] = (
                            years.get(item.exit_session.year, Decimal(0)) + item.net_money
                        )
                estimates.extend(
                    TaxYearEstimate(
                        key=key,
                        year=year,
                        net_gains=net,
                        rough_after_tax=after_tax_year(net, taxes),
                    )
                    for year, net in sorted(years.items())
                )
        overall = {
            (card.key.playbook, card.key.variant, card.key.disposition): card
            for card in cards
            if card.key.fundamentals_status is None
        }
        comparisons: list[FilterComparison] = []
        for (playbook, variant, disposition), filtered in sorted(
            overall.items(), key=lambda row: tuple(str(v) for v in row[0])
        ):
            if disposition not in {"CRO_VETO", "RS_FILTER", "PR_FILTER", "SZ_FILTER"}:
                continue
            taken = overall.get((playbook, variant, "APPROVED"))
            comparisons.append(
                FilterComparison(
                    playbook=playbook,
                    variant=variant,
                    cohort=bound.cohort,
                    filter=disposition,
                    taken_n=0 if taken is None else taken.n,
                    filtered_n=filtered.n,
                    taken_expectancy_r=None if taken is None else taken.expectancy_r,
                    filtered_expectancy_r=filtered.expectancy_r,
                )
            )
        spy_return = None
        symbols = {item.symbol for item in frozen.bundle.series}
        if "SPY" in symbols:
            spy = {
                bar.session_date: bar.close for bar in frozen.bundle.for_symbol("SPY", "ALL").bars
            }
            if bound.start in spy and bound.end in spy:
                with localcontext() as precision:
                    precision.prec = 256
                    spy_return = ((spy[bound.end] / spy[bound.start] - 1) * 100).quantize(
                        Decimal("0.000001")
                    )
        notes = [
            DISCLAIMER,
            SOURCE_NOTICE,
            DISTRIBUTION_NOTICE if bound.cohort.startswith("REPLAY") else DIVIDEND_NOTICE,
            TAX_ESTIMATE_NOTICE,
            TAX_NOTICE,
            "Fundamental subgroups overlap the overall rows; never sum the two views.",
            "Commission plan unverified; modeled fees round each component up per trade.",
            "No spread measurement uses the liquidity floor; fees before the first dated row use its rates.",
            "SIP/IEX cross-check uses the same vendor; IEX is partial volume, not independent confirmation.",
        ]
        if bound.end > fees.review_due:
            notes.append("Fee schedule review overdue; rates remain estimates")
        if bound.cohort.startswith("REPLAY"):
            notes.append(PIT_NOTICE if bound.universe_sha256 is not None else SURVIVORSHIP_NOTICE)
            if bound.universe_sha256 is not None:
                notes.append("Historical membership SHA256: " + bound.universe_sha256)
        if bound.synthetic:
            notes.append(SYNTHETIC_NOTICE)
        return WeeklyReport(
            context=bound,
            manifest_sha256=frozen.manifest.sha256,
            fee_schedule_sha256=fees.sha256,
            cost_policy_sha256=cost_policy_sha256(costs),
            tax_profile=taxes,
            calibration=calibration or CostCalibration(),
            cards=tuple(cards),
            equity_notes=tuple(equity_notes),
            spy_buy_hold_pct=spy_return,
            tax_years=tuple(estimates),
            filters=tuple(comparisons),
            notes=tuple(notes),
            security=security,
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-02: weekly report evidence is unverifiable") from None


def _number(value: Decimal | None, *, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    with localcontext() as precision:
        precision.prec = 256
        return format(value * (100 if percent else 1), ".2f") + ("%" if percent else "")


def _range(value: BootstrapEstimate | None) -> str:
    return "n/a" if value is None else f"{_number(value.lower)} to {_number(value.upper)}"


def render_weekly(report: WeeklyReport, *, mask_amounts: bool = False) -> str:
    """Plain text; Telegram escapes/pages it at its already-private boundary."""
    bound = WeeklyReport.model_validate(report)
    if type(mask_amounts) is not bool:
        raise DataIntegrityError("EV-02: amount masking requires a strict boolean")
    lines = [
        f"Weekly outcomes · {bound.context.cohort} · {bound.context.start} to {bound.context.end}",
        f"Manifest: {bound.manifest_sha256}",
        f"Report: {bound.sha256}",
        "SPY ALL buy-and-hold: "
        + _number(bound.spy_buy_hold_pct)
        + ("%" if bound.spy_buy_hold_pct is not None else ""),
        DISCLAIMER,
    ]
    if not bound.cards:
        lines.append("No eligible recorded outcomes in this period.")
    for card, equity_note in zip(bound.cards, bound.equity_notes, strict=True):
        status = (
            "all fundamentals"
            if card.key.fundamentals_status is None
            else card.key.fundamentals_status.value
        )
        money = "$•••" if mask_amounts else "$" + _number(card.expectancy_money)
        ci = _range(card.confidence)
        lines.extend(
            [
                f"{card.key.playbook.value}/{card.key.variant} · {card.key.disposition} · {status}: {card.grade}",
                f"Alerts {card.alerts}; filled {card.filled}; resolved {card.n}; fill {_number(card.fill_rate, percent=True)}; win {_number(card.win_rate, percent=True)}",
                f"Avg/expectancy {_number(card.expectancy_r)}R ({money}); 90% range {ci}R; PF {_number(card.profit_factor)}",
                f"Avg win {_number(card.average_win_r)}R; avg loss {_number(card.average_loss_r)}R; payoff {_number(card.payoff_ratio)}; hold {_number(card.average_hold)} sessions",
                f"Drawdown {_number(card.max_drawdown_pct)}%; duration {card.drawdown_duration_sessions if card.drawdown_duration_sessions is not None else 'n/a'} sessions; Sharpe {_number(card.sharpe)}; Sortino {_number(card.sortino)}; exposure {_number(card.time_exposed_pct)}%",
                "Equity: " + equity_note,
                "Scores: "
                + "; ".join(
                    f"{band.label} n={band.n} avg={_number(band.expectancy_r)}R (90% {_range(band.confidence)}R)"
                    for band in card.score_bands
                )
                + "; Spearman="
                + _number(card.score_rho),
            ]
        )
        if card.n < 30:
            lines.append("too few trades to judge")
        if card.grade == "UNPROVEN":
            lines.append(
                "Needs ≥ 50 trades, positive 90% lower bound and PF ≥ 1.2; replay OOS also needs validated DSR ≥ 0.95."
            )
    for comparison in bound.filters:
        lines.append(
            f"Filter {comparison.filter} · {comparison.playbook.value}/{comparison.variant}: taken n={comparison.taken_n} {_number(comparison.taken_expectancy_r)}R; filtered n={comparison.filtered_n} {_number(comparison.filtered_expectancy_r)}R"
        )
    for estimate in bound.tax_years:
        amount = "$•••" if mask_amounts else "$" + _number(estimate.rough_after_tax)
        lines.append(
            f"Rough ST year {estimate.year} · {estimate.key.playbook.value}/{estimate.key.variant}/{estimate.key.disposition}: {amount}"
        )
    lines.extend(bound.notes[1:])
    for row in bound.fill_quality:
        lines.append(
            f"Fill quality {row.month} {row.bucket}: n={row.n}; UNAVAILABLE={row.unavailable}; arrival p50={_number(row.p50_bps)} bps; p90={_number(row.p90_bps)} bps; stop p90={_number(row.stop_p90_bps)} bps; cost floor={_number(row.calibrated_half_spread_bps)} bps"
        )
    if bound.calibration.scope is not None:
        lines.append("Actual fill cost calibration SHA-256: " + bound.calibration.sha256)
    for drift_check in bound.drift:
        label = (
            "EDGE DRIFT"
            if drift_check.flag is True
            else "clear"
            if drift_check.flag is False
            else "UNVERIFIED"
        )
        lines.append(
            f"{drift_check.playbook.value}: {label} · {len(drift_check.paper)} actual paper trades vs {len(drift_check.oos)} current registered OOS trades. No settings change automatically."
        )
    lines.extend(render_security(bound.security, masked=mask_amounts))
    return "\n".join(lines)


_COLUMNS = (
    "record_type",
    "account_id",
    "cohort",
    "start",
    "end",
    "manifest_sha256",
    "report_sha256",
    "fee_schedule_sha256",
    "cost_policy_sha256",
    "config_sha256",
    "playbook",
    "variant",
    "disposition",
    "fundamentals_status",
    "grade",
    "alerts",
    "filled",
    "n",
    "fill_rate",
    "win_rate",
    "average_win_r",
    "average_loss_r",
    "payoff_ratio",
    "expectancy_r",
    "expectancy_money",
    "profit_factor",
    "ci_lower",
    "ci_upper",
    "max_drawdown_pct",
    "drawdown_duration_sessions",
    "sharpe",
    "sortino",
    "average_hold",
    "time_exposed_pct",
    "score_rho",
    "score_band",
    "year",
    "net_gains",
    "rough_after_tax",
    "notes",
)


def _safe_cell(value: object) -> str:
    text = "n/a" if value is None else str(value)
    # CSV viewers must not evaluate text as formulas. Exact negative numeric
    # values remain numeric; untrusted identifiers starting with '-' do not.
    if not isinstance(value, (Decimal, int)) and text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def report_csv(report: WeeklyReport) -> bytes:
    bound = WeeklyReport.model_validate(report)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    base = dict(
        account_id=bound.context.account_id,
        cohort=bound.context.cohort,
        start=bound.context.start,
        end=bound.context.end,
        manifest_sha256=bound.manifest_sha256,
        report_sha256=bound.sha256,
        fee_schedule_sha256=bound.fee_schedule_sha256,
        cost_policy_sha256=bound.cost_policy_sha256,
        config_sha256=bound.context.config_sha256,
    )

    def row(values: dict[str, object]) -> None:
        writer.writerow({key: _safe_cell(value) for key, value in {**base, **values}.items()})

    row(
        {
            "record_type": "benchmark",
            "expectancy_r": bound.spy_buy_hold_pct,
            "notes": "; ".join((*bound.notes, *render_security(bound.security, masked=False))),
        }
    )
    for card, note in zip(bound.cards, bound.equity_notes, strict=True):
        key_fields = dict(
            playbook=card.key.playbook.value,
            variant=card.key.variant,
            disposition=card.key.disposition,
            fundamentals_status=card.key.fundamentals_status,
        )
        metrics = {
            key: value for key, value in card.model_dump(mode="python").items() if key in _COLUMNS
        }
        row(
            {
                **metrics,
                **key_fields,
                "record_type": "edge",
                "ci_lower": None if card.confidence is None else card.confidence.lower,
                "ci_upper": None if card.confidence is None else card.confidence.upper,
                "notes": note + ("; too few trades to judge" if card.n < 30 else ""),
            }
        )
        for band in card.score_bands:
            row(
                {
                    **key_fields,
                    "record_type": "score_band",
                    "score_band": band.label,
                    "n": band.n,
                    "expectancy_r": band.expectancy_r,
                    "ci_lower": None if band.confidence is None else band.confidence.lower,
                    "ci_upper": None if band.confidence is None else band.confidence.upper,
                }
            )
    for estimate in bound.tax_years:
        row(
            {
                "record_type": "tax",
                "playbook": estimate.key.playbook.value,
                "variant": estimate.key.variant,
                "disposition": estimate.key.disposition,
                "fundamentals_status": estimate.key.fundamentals_status,
                "year": estimate.year,
                "net_gains": estimate.net_gains,
                "rough_after_tax": estimate.rough_after_tax,
                "notes": TAX_NOTICE + " " + TAX_ESTIMATE_NOTICE,
            }
        )
    for comparison in bound.filters:
        row(
            {
                "record_type": "filter",
                "playbook": comparison.playbook.value,
                "variant": comparison.variant,
                "disposition": comparison.filter,
                "n": comparison.filtered_n,
                "expectancy_r": comparison.filtered_expectancy_r,
                "notes": f"Taken n={comparison.taken_n}; expectancy_R={comparison.taken_expectancy_r}",
            }
        )
    for quality in bound.fill_quality:
        row(
            {
                "record_type": "fill_quality",
                "variant": quality.bucket,
                "n": quality.n,
                "notes": (
                    f"month={quality.month}; unavailable={quality.unavailable}; "
                    f"p50_bps={quality.p50_bps}; p90_bps={quality.p90_bps}; "
                    f"stop_p90_bps={quality.stop_p90_bps}; "
                    f"calibrated_half_spread_bps={quality.calibrated_half_spread_bps}"
                ),
            }
        )
    for drift in bound.drift:
        row(
            {
                "record_type": "edge_drift",
                "playbook": drift.playbook.value,
                "n": len(drift.paper),
                "notes": f"flag={drift.flag}; current OOS n={len(drift.oos)}; physical paper only; no automatic changes",
            }
        )
    return output.getvalue().encode("utf-8")


def save_report(root: Path, report: WeeklyReport) -> tuple[Path, Path]:
    """Explicit existing report directory; content-addressed files are write-once."""
    try:
        bound = WeeklyReport.model_validate(report)
        account = hashlib.sha256(bound.context.account_id.encode("utf-8")).hexdigest()[:16]
        name = f"weekly_{bound.context.start}_{bound.context.end}_{bound.context.cohort}_{account}_{bound.sha256}"
        json_path, csv_path = (
            controlled_path(root / (name + suffix)) for suffix in (".json", ".csv")
        )
        payloads = (canonical_bytes(bound), report_csv(bound))
        if any(len(payload) > 32 * 1024 * 1024 for payload in payloads):
            raise DataIntegrityError("EV-02: generated report exceeds its file bound")
        for path, payload in zip((json_path, csv_path), payloads, strict=True):
            if path.exists():
                with path.open("rb") as stream:
                    existing = stream.read(len(payload) + 1)
                if existing != payload:
                    raise DataIntegrityError("EV-02: existing content-addressed report differs")
            else:
                with path.open("xb") as stream:
                    stream.write(payload)
        return json_path, csv_path
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-02: report publication failed") from None
