"""ER-01..05: immutable after-cost report cards, strict cohort separation.

Undefined denominators and missing daily equity stay unavailable. Grades never
pause a playbook; XK-05 alone owns that later host operation. Replay OOS cannot
be WORKING without supplied validation evidence for its deflated Sharpe.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import Field, model_validator

from backend.agents.fundamentals import FrameworkStatus
from backend.core.errors import DataIntegrityError
from backend.data.history import Digest
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, Money, Playbook, SessionDate
from backend.evaluation.costs import Exact
from backend.evaluation.outcomes import Cohort, Disposition, Outcome
from backend.indicators.statistics import (
    BootstrapEstimate,
    annualized_returns,
    circular_bootstrap,
    spearman,
)
from backend.ops.playbook_kill import playbook_kill_condition
from backend.realtime.models import ContextTag

ZERO = Decimal(0)
Grade = Literal["LOSING", "WORKING", "UNPROVEN"]


class EdgeKey(FrozenModel):
    playbook: Playbook
    variant: str = Field(strict=True, pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    cohort: Cohort
    disposition: Disposition
    fundamentals_status: FrameworkStatus | None = None
    context_tag: ContextTag | None = Field(default=None, exclude_if=lambda value: value is None)


class EquityPoint(FrozenModel):
    session: SessionDate
    equity: Money = Field(gt=0)


class EquityCurve(FrozenModel):
    key: EdgeKey
    manifest_sha256: Digest
    alert_ids: tuple[UUID, ...] = Field(max_length=100000)
    points: tuple[EquityPoint, ...] = Field(min_length=2, max_length=20000)
    exposed_sessions: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            len(set(self.alert_ids)) != len(self.alert_ids)
            or self.exposed_sessions > len(self.points) - 1
            or any(
                previous.session >= following.session
                for previous, following in zip(self.points, self.points[1:], strict=False)
            )
        ):
            raise ValueError("ER-01: equity sessions, alerts and exposure must agree")
        return self


class ScoreBand(FrozenModel):
    label: Literal["[7,8)", "[8,9)", "[9,10]"]
    n: int = Field(strict=True, ge=0)
    expectancy_r: Exact | None
    confidence: BootstrapEstimate | None

    @model_validator(mode="after")
    def available(self) -> Self:
        if (self.n == 0) != (self.expectancy_r is None) or (self.n == 0) != (
            self.confidence is None
        ):
            raise ValueError("ER-05: empty bands cannot invent an estimate")
        return self


def edge_grade(
    r_multiples: tuple[Decimal, ...],
    confidence: BootstrapEstimate | None,
    profit_factor: Decimal | None,
    cohort: Cohort,
    dsr: Decimal | None = None,
) -> Grade:
    """ER-02's fixed thresholds; no unavailable evidence can earn WORKING."""
    try:
        # Validate each sample even when it is below the count threshold.
        losing = playbook_kill_condition(r_multiples)
        if cohort not in {"PAPER", "LIVE", "REPLAY_IN_SAMPLE", "REPLAY_OOS"}:
            raise ValueError("unrecognized cohort")
        checked = BootstrapEstimate.model_validate(confidence) if confidence is not None else None
        if profit_factor is not None and (
            not isinstance(profit_factor, Decimal)
            or not profit_factor.is_finite()
            or profit_factor < 0
        ):
            raise ValueError("invalid profit factor")
        if dsr is not None and (
            not isinstance(dsr, Decimal) or not dsr.is_finite() or not 0 <= dsr <= 1
        ):
            raise ValueError("invalid DSR")
        count = len(r_multiples)
        if losing or (count >= 30 and checked is not None and checked.upper < 0):
            return "LOSING"
        # EV replay is in-sample. Only the future registered OOS proof can
        # qualify a replay cohort; an in-sample grade never claims readiness.
        if (
            count >= 50
            and checked is not None
            and checked.lower > 0
            and profit_factor is not None
            and profit_factor >= Decimal("1.2")
            and (
                cohort in {"PAPER", "LIVE"}
                or (cohort == "REPLAY_OOS" and dsr is not None and dsr >= Decimal("0.95"))
            )
        ):
            return "WORKING"
        return "UNPROVEN"
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("ER-02: malformed grading evidence") from None


class EdgeCard(FrozenModel):
    key: EdgeKey
    manifest_sha256: Digest | None
    fee_schedule_sha256: Digest | None
    alerts: int = Field(strict=True, ge=0, le=100000)
    filled: int = Field(strict=True, ge=0)
    n: int = Field(strict=True, ge=0)
    fill_rate: Exact | None = Field(ge=0, le=1)
    win_rate: Exact | None = Field(ge=0, le=1)
    average_win_r: Exact | None = Field(gt=0)
    average_loss_r: Exact | None = Field(lt=0)
    payoff_ratio: Exact | None = Field(ge=0)
    expectancy_r: Exact | None
    expectancy_money: Money | None
    profit_factor: Exact | None = Field(ge=0)
    confidence: BootstrapEstimate | None
    average_hold: Exact | None = Field(ge=1, le=31)
    max_drawdown_pct: Exact | None = Field(ge=0, le=100)
    drawdown_duration_sessions: int | None = Field(default=None, strict=True, ge=0)
    sharpe: Exact | None
    sortino: Exact | None
    time_exposed_pct: Exact | None = Field(ge=0, le=100)
    equity_metrics_status: Literal["AVAILABLE", "UNAVAILABLE"]
    score_bands: tuple[ScoreBand, ScoreBand, ScoreBand]
    score_rho: Exact | None = Field(ge=-1, le=1)
    r_multiples: tuple[Exact, ...] = Field(max_length=100000)
    dsr: Exact | None = Field(default=None, ge=0, le=1)
    grade: Grade

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (
            not self.n <= self.filled <= self.alerts
            or self.n != len(self.r_multiples)
            or self.grade
            != edge_grade(
                self.r_multiples, self.confidence, self.profit_factor, self.key.cohort, self.dsr
            )
        ):
            raise ValueError("ER: grade and counts must follow the observed cohort")
        if (
            (self.alerts == 0) != (self.fill_rate is None)
            or (self.n == 0) != (self.win_rate is None)
            or (self.n == 0) != (self.expectancy_r is None)
            or (self.n == 0) != (self.expectancy_money is None)
            or (self.n == 0) != (self.confidence is None)
            or (self.n == 0) != (self.average_hold is None)
        ):
            raise ValueError("ER: unavailable samples cannot invent metrics")
        with localcontext() as precision:
            precision.prec = 80
            if self.fill_rate is not None and self.fill_rate != Decimal(self.filled) / self.alerts:
                raise ValueError("ER: fill rate differs from counts")
        if (
            tuple(band.label for band in self.score_bands) != ("[7,8)", "[8,9)", "[9,10]")
            or sum(band.n for band in self.score_bands) > self.n
        ):
            raise ValueError("ER-05: score bands must be fixed and disjoint")
        fields = (self.max_drawdown_pct, self.drawdown_duration_sessions, self.time_exposed_pct)
        if self.equity_metrics_status == "UNAVAILABLE" and any(
            value is not None for value in (*fields, self.sharpe, self.sortino)
        ):
            raise ValueError("ER-01: missing equity cannot carry portfolio statistics")
        if self.equity_metrics_status == "AVAILABLE" and any(value is None for value in fields):
            raise ValueError("ER-01: supplied equity needs complete drawdown and exposure")
        return self


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    return sum(values, ZERO) / len(values) if values else None


def summarize_edge(
    key: EdgeKey,
    outcomes: tuple[Outcome, ...],
    *,
    calendar: MarketCalendar,
    curve: EquityCurve | None = None,
    dsr: Decimal | None = None,
) -> EdgeCard:
    """ER/EV: exact money metrics, sorted statistics and explicit evidence gaps."""
    try:
        bound = EdgeKey.model_validate(key)
        if not isinstance(outcomes, tuple) or len(outcomes) > 100000:
            raise ValueError("bounded immutable outcomes required")
        checked = tuple(Outcome.model_validate(item) for item in outcomes)
        if len({item.setup.alert_id for item in checked}) != len(checked):
            raise ValueError("duplicate alert")
        for item in checked:
            intent = item.setup
            if (
                (intent.playbook, intent.variant, intent.cohort, intent.disposition)
                != (
                    bound.playbook,
                    bound.variant,
                    bound.cohort,
                    bound.disposition,
                )
                or (
                    bound.fundamentals_status is not None
                    and intent.fundamentals_status != bound.fundamentals_status
                )
                or (bound.context_tag is not None and bound.context_tag not in intent.context_tags)
            ):
                raise ValueError("mixed playbook, variant, cohort, filter or fundamental status")
        manifests = {item.manifest_sha256 for item in checked}
        fees = {item.fee_schedule_sha256 for item in checked}
        policies = {item.cost_policy_sha256 for item in checked}
        if len(manifests) > 1 or len(fees) > 1 or len(policies) > 1:
            raise ValueError("different frozen history or fee versions")
        manifest = next(iter(manifests), None)
        fee_hash = next(iter(fees), None)
        resolved = tuple(
            sorted(
                (item for item in checked if item.status == "RESOLVED"),
                key=lambda item: (cast(date, item.exit_session), item.setup.alert_id.hex),
            )
        )
        rs = tuple(cast(Decimal, item.r_multiple) for item in resolved)
        wins = tuple(value for value in rs if value > 0)
        losses = tuple(value for value in rs if value < 0)
        filled = sum(item.entry_fill is not None for item in checked)
        equity = EquityCurve.model_validate(curve) if curve is not None else None
        drawdown = None
        duration = None
        exposure = None
        sharpe = None
        sortino = None
        with localcontext() as precision:
            precision.prec = 80
            if equity is not None:
                if (
                    equity.key != bound
                    or equity.manifest_sha256 != manifest
                    or set(equity.alert_ids) != {item.setup.alert_id for item in checked}
                ):
                    raise ValueError("equity is bound to different outcomes")
                days = tuple(point.session for point in equity.points)
                if not calendar.is_session(days[-1]) or days != (
                    *calendar.previous_sessions(days[-1], len(days) - 1),
                    days[-1],
                ):
                    raise ValueError("equity curve has a missing/non-XNYS session")
                if any(
                    item.setup.decision_session < days[0]
                    or (item.exit_session is not None and item.exit_session > days[-1])
                    for item in checked
                ):
                    raise ValueError("equity curve does not cover the outcome period")
                daily = tuple(
                    following.equity / previous.equity - 1
                    for previous, following in zip(equity.points, equity.points[1:], strict=False)
                )
                stats = annualized_returns(daily)
                sharpe, sortino = stats.sharpe, stats.sortino
                peak = equity.points[0].equity
                drawdown, duration, underwater = ZERO, 0, 0
                for point in equity.points[1:]:
                    peak = max(peak, point.equity)
                    current = (peak - point.equity) / peak * 100
                    underwater = underwater + 1 if point.equity < peak else 0
                    drawdown = max(drawdown, current)
                    duration = max(duration, underwater)
                exposure = Decimal(equity.exposed_sessions) / (len(equity.points) - 1) * 100
            average_win, average_loss = _average(wins), _average(losses)
            money = tuple(cast(Decimal, item.net_money) for item in resolved)
            positive = sum((value for value in money if value > 0), ZERO)
            negative = -sum((value for value in money if value < 0), ZERO)
            factor = positive / negative if negative else None
            average_money = _average(money)
            confidence = circular_bootstrap(rs)
            bands: list[ScoreBand] = []
            for label, lower, upper in (("[7,8)", 7, 8), ("[8,9)", 8, 9), ("[9,10]", 9, 10)):
                sample = tuple(
                    cast(Decimal, item.r_multiple)
                    for item in resolved
                    if lower <= item.setup.score
                    and (item.setup.score < upper or (upper == 10 and item.setup.score == 10))
                )
                bands.append(
                    ScoreBand(
                        label=cast(Literal["[7,8)", "[8,9)", "[9,10]"], label),
                        n=len(sample),
                        expectancy_r=_average(sample),
                        confidence=circular_bootstrap(sample),
                    )
                )
            return EdgeCard(
                key=bound,
                manifest_sha256=manifest,
                fee_schedule_sha256=fee_hash,
                alerts=len(checked),
                filled=filled,
                n=len(resolved),
                fill_rate=Decimal(filled) / len(checked) if checked else None,
                win_rate=Decimal(len(wins)) / len(rs) if rs else None,
                average_win_r=average_win,
                average_loss_r=average_loss,
                payoff_ratio=average_win / -average_loss
                if average_win is not None and average_loss is not None
                else None,
                expectancy_r=_average(rs),
                expectancy_money=average_money.quantize(Decimal("0.000001"))
                if average_money is not None
                else None,
                profit_factor=factor,
                confidence=confidence,
                average_hold=_average(tuple(Decimal(item.sessions_held) for item in resolved)),
                max_drawdown_pct=drawdown,
                drawdown_duration_sessions=duration,
                sharpe=sharpe,
                sortino=sortino,
                time_exposed_pct=exposure,
                equity_metrics_status="AVAILABLE" if equity is not None else "UNAVAILABLE",
                score_bands=(bands[0], bands[1], bands[2]),
                score_rho=spearman(tuple(item.setup.score for item in resolved), rs),
                r_multiples=rs,
                dsr=dsr,
                grade=edge_grade(rs, confidence, factor, bound.cohort, dsr),
            )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("ER: invalid report evidence; no metrics inferred") from None
