"""GV/XA: bounded evidence collection and informative paper readiness publication."""

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import Settings, YamlConfig
from backend.core.database import SecurityEvent, SystemEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.data_layer import _eligible_session
from backend.data.history import FrozenHistory, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.availability import GradeStore
from backend.evaluation.calibrated_costs import snapshot as cost_snapshot
from backend.evaluation.costs import FeeSchedule
from backend.evaluation.edge import EdgeKey, Grade, edge_grade
from backend.evaluation.equity import build_equity_curve
from backend.evaluation.evidence import OutcomeEvidence, recorded_publication
from backend.evaluation.fill_quality import edge_drift
from backend.evaluation.physical import resolved_trades
from backend.evaluation.verdict import ReadinessVerdict, VerdictInputs, record
from backend.indicators.statistics import annualized_returns, circular_bootstrap
from backend.ops.anchors import LedgerAnchors, controlled_path
from backend.ops.trading_controls import ControlScope
from backend.pnl.stats import statistics
from backend.pnl.storage import read_days

_NY = ZoneInfo("America/New_York")


def _grade(values: tuple[Decimal, ...], seed: int) -> Grade:
    with localcontext() as precision:
        precision.prec = 80
        wins = sum((value for value in values if value > 0), Decimal(0))
        losses = -sum((value for value in values if value < 0), Decimal(0))
        return edge_grade(
            values,
            circular_bootstrap(values, seed=seed),
            wins / losses if losses else None,
            "PAPER",
        )


def collect(
    ledger: Ledger,
    settings: Settings,
    config: YamlConfig,
    scope: ControlScope,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
    *,
    history: FrozenHistory | None,
    effective_hash: str,
    security_green: bool = False,
    drill_at: datetime | None = None,
) -> VerdictInputs:
    policy, limits, bound = (
        YamlConfig.model_validate(config),
        Settings.validated_copy(settings),
        ControlScope.model_validate(scope),
    )
    if bound.environment != "PAPER" or type(security_green) is not bool:
        raise DataIntegrityError("GV: explicit paper scope and typed security evidence required")
    now = ensure_utc(ledger.clock.now())
    tail = _eligible_session(calendar, now, policy.schedule.daily_scan_delay_minutes)
    ledger.verify_chain()
    if history is not None:
        history = FrozenHistory.model_validate(history)
        validate_history(history.bundle, calendar)
        if any(row.sessions[-1] > tail for row in history.bundle.series):
            raise DataIntegrityError("GV: future or uncompleted history is refused")
    with Session(ledger.engine) as session:
        events = tuple(
            session.scalars(select(SecurityEvent).order_by(SecurityEvent.seq).limit(100001))
        )
        states = tuple(session.scalars(select(SystemEvent).order_by(SystemEvent.seq).limit(100001)))
    if (
        len(events) > 100000
        or len(states) > 100000
        or any(row.created_at > now for row in (*events, *states))
    ):
        raise DataIntegrityError("GV: bounded past incident inventory required")
    physical = resolved_trades(ledger, bound, schedule, config=policy)
    source: Literal["AUTO_PAPER", "EV_01_HYPOTHETICAL", "UNAVAILABLE"] = "UNAVAILABLE"
    samples: dict[str, tuple[Decimal, ...]] = {}
    r_values: tuple[Decimal, ...] = ()
    sessions: tuple[date, ...] = ()
    returns: tuple[Decimal, ...] = ()
    drawdown = None
    if physical:
        source = "AUTO_PAPER"
        r_values = tuple(row.r_multiple for row in physical)
        samples = {
            name: tuple(row.r_multiple for row in physical if row.playbook.value == name)
            for name in policy.enabled_playbooks
        }
        days = read_days(ledger, bound.account_id, "PAPER")
        if days and days[-1].observation.session == tail:
            stats = statistics(days, "inception", calendar)
            sessions = tuple(row.observation.session for row in days)
            returns = tuple(row.day_ret for row in days)
            drawdown = stats.max_drawdown
    else:
        # Explicitly labeled EV-01 fallback. A physical sample, however small,
        # always wins; hypothetical results never top up its trade count.
        for event in reversed(events):
            if (
                event.kind != "WEEKLY_REPORT"
                or event.detail.get("account_id") != bound.account_id
                or event.detail.get("cohort") != "PAPER"
            ):
                continue
            report = recorded_publication(event.detail)
            if (
                report.context.config_sha256 != policy.config_hash
                or report.context.end != tail
                or report.calibration != cost_snapshot(ledger, "PAPER", scope=bound)
            ):
                break
            proof = OutcomeEvidence.from_recorded(event.detail["outcome_evidence"])
            outcomes = tuple(
                row
                for row in proof.outcomes
                if row.setup.disposition == "APPROVED"
                and row.setup.variant
                == ("baseline" if policy.exits.variant == "BASELINE" else policy.exits.variant)
            )
            resolved = tuple(
                row for row in outcomes if row.status == "RESOLVED" and row.r_multiple is not None
            )
            if not resolved:
                break
            source = "EV_01_HYPOTHETICAL"
            r_values = tuple(row.r_multiple for row in resolved if row.r_multiple is not None)
            samples = {
                name: tuple(
                    row.r_multiple
                    for row in resolved
                    if row.setup.playbook.value == name and row.r_multiple is not None
                )
                for name in policy.enabled_playbooks
            }
            if (
                history is not None
                and history.manifest.sha256 == report.manifest_sha256
                and report.context.initial_equity is not None
            ):
                key = EdgeKey(
                    playbook=resolved[0].setup.playbook,
                    variant="baseline"
                    if policy.exits.variant == "BASELINE"
                    else policy.exits.variant,
                    cohort="PAPER",
                    disposition="APPROVED",
                )
                built = build_equity_curve(
                    key,
                    outcomes,
                    history,
                    calendar,
                    initial_equity=report.context.initial_equity,
                    start=report.context.start,
                    end=report.context.end,
                    portfolio=True,
                )
                if built.curve is not None:
                    points = built.curve.points
                    sessions = tuple(row.session for row in points[1:])
                    with localcontext() as precision:
                        precision.prec = 80
                        returns = tuple(
                            b.equity / a.equity - 1
                            for a, b in zip(points, points[1:], strict=False)
                        )
                        peak = points[0].equity
                        drawdown = Decimal(0)
                        for point in points[1:]:
                            peak = max(peak, point.equity)
                            drawdown = max(drawdown, (peak - point.equity) / peak)
            break
    spy_sharpe = None
    if (
        history is not None
        and sessions
        and any(row.symbol == "SPY" and row.adjustment == "ALL" for row in history.manifest.entries)
    ):
        spy = history.bundle.for_symbol("SPY", "ALL")
        closes = {bar.session_date: bar.close for bar in spy.bars}
        preceding = calendar.previous_sessions(sessions[0], 1)[0]
        dates = (preceding, *sessions)
        if all(day in closes for day in dates):
            with localcontext() as precision:
                precision.prec = 80
                spy_returns = tuple(
                    closes[b] / closes[a] - 1 for a, b in zip(dates, dates[1:], strict=False)
                )
            spy_sharpe = annualized_returns(spy_returns).sharpe
    grades = tuple(
        (name, _grade(samples[name], policy.qv.seed))
        for name in policy.enabled_playbooks
        if samples.get(name)
    )
    oos = GradeStore(ledger, limits, policy).oos_by_playbook()
    flags = tuple(
        edge_drift(
            tuple(row.r_multiple for row in physical if row.playbook == name),
            oos.get(name, ()),
            seed=policy.qv.seed,
        )
        for name in oos
        if name.value in policy.enabled_playbooks
    )
    drift = (
        True
        if any(flag is True for flag in flags)
        else False
        if len(flags) == len(policy.enabled_playbooks) and all(flag is False for flag in flags)
        else None
    )
    month_start = now.astimezone(_NY).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    halts = tuple(row for row in states if row.state == "HALTED")
    # All local halts count against the fault-free window. This is conservative
    # when an older incident lacks account attribution; nothing is hidden.
    matches = tuple(
        row
        for row in events
        if row.kind == "AUTO_RECONCILED"
        and row.detail.get("account_id") == bound.account_id
        and row.detail.get("environment") == "PAPER"
    )
    telemetry_start = matches[0].created_at if matches else None
    recent = 0
    for day in reversed(sessions):
        if (
            telemetry_start is None
            or calendar.session_open(day) < telemetry_start
            or any(calendar.session_open(day) <= row.created_at <= now for row in halts)
        ):
            break
        recent += 1
    latest_match = matches[-1] if matches else None
    reconciliation_faults = tuple(row for row in halts if "reconcil" in row.reason.lower())
    unresolved = (
        True
        if any(latest_match is None or row.seq > latest_match.seq for row in reconciliation_faults)
        else None
        if latest_match is None or now - latest_match.created_at > timedelta(hours=24)
        else False
    )
    return VerdictInputs(
        scope=bound,
        as_of=now,
        source=source,
        evidence_sha256=hashlib.sha256(
            (
                LedgerAnchors(ledger, ledger.clock).create().digest
                + "/"
                + ("UNAVAILABLE" if history is None else history.manifest.sha256)
                + "/"
                + schedule.sha256
            ).encode("ascii")
        ).hexdigest(),
        config_sha256=effective_hash,
        r_multiples=r_values,
        sessions=sessions,
        drawdown=drawdown,
        # Any reducing halt remains conservative evidence of the drawdown tier.
        reduce_only_hit=any(row.state == "REDUCE_ONLY" for row in states),
        sharpe=annualized_returns(returns).sharpe,
        spy_total_return_sharpe=spy_sharpe,
        recent_fault_free_sessions=recent if sessions else None,
        drill_at=drill_at,
        security_green=security_green,
        playbook_grades=grades,
        unavailable_playbooks=tuple(
            name for name in policy.enabled_playbooks if not samples.get(name)
        ),
        edge_drift=drift,
        unresolved_reconciliation=unresolved,
        panic_this_month=any(
            row.kind == "PANIC" and row.created_at >= month_start for row in events
        ),
        circuit_breaker_halts_this_month=(
            sum(
                row.kind == "CIRCUIT_BREAKER_HALTED" and row.created_at >= month_start
                for row in events
            )
            if telemetry_start is not None
            and telemetry_start <= month_start
            or sum(
                row.kind == "CIRCUIT_BREAKER_HALTED" and row.created_at >= month_start
                for row in events
            )
            >= 2
            else None
        ),
    )


def update_progress(project: Path, verdict: ReadinessVerdict) -> None:
    """GV-01's one permitted progress sentence; never edits settings or source."""
    path = controlled_path(project / "docs/PROGRESS.md")
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    indices = [i for i, line in enumerate(lines) if line.startswith("Readiness verdict:")]
    if (
        len(indices) != 1
        or lines.index("## Where things stand") > indices[0]
        or lines.index("## What works now") <= indices[0]
    ):
        raise DataIntegrityError("GV-01: progress verdict placeholder is missing or misplaced")
    drift = (
        "UNVERIFIED"
        if verdict.inputs.edge_drift is None
        else "EDGE DRIFT"
        if verdict.inputs.edge_drift
        else "clear"
    )
    lines[indices[0]] = (
        f"Readiness verdict: {verdict.status.replace('_', ' ')}; {len(verdict.inputs.r_multiples)} resolved trades over {len(verdict.inputs.sessions)} sessions. Edge drift: {drift}. Live stays locked."
    )
    if len(lines) > 60:
        raise DataIntegrityError("GV-01: progress page exceeds 60 lines")
    temporary = controlled_path(path.with_suffix(".verdict.tmp"))
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class VerdictPublisher:
    def __init__(
        self,
        ledger: Ledger,
        config: YamlConfig,
        scope: ControlScope,
        calendar: MarketCalendar,
        project: Path,
        inputs: Callable[[], VerdictInputs],
        notify: Callable[[str, bool], Awaitable[None]],
    ) -> None:
        self.ledger, self.config, self.scope, self.calendar = ledger, config, scope, calendar
        self.project, self.inputs, self.notify = project, inputs, notify
        self._lock = asyncio.Lock()

    async def publish(self, *, monthly: bool = False) -> ReadinessVerdict | None:
        async with self._lock:
            now = ensure_utc(self.ledger.clock.now())
            if monthly:
                today = now.astimezone(_NY).date()
                first = today.replace(day=1)
                while not self.calendar.is_session(first):
                    first += timedelta(days=1)
                if today < first or now < self.calendar.session_close(first) + timedelta(
                    minutes=self.config.schedule.daily_scan_delay_minutes
                ):
                    return None
                with Session(self.ledger.engine) as session:
                    rows = tuple(
                        session.scalars(
                            select(SecurityEvent)
                            .where(
                                SecurityEvent.kind == "VERDICT",
                                SecurityEvent.created_at >= self.calendar.session_close(first),
                            )
                            .limit(1001)
                        )
                    )
                if len(rows) > 1000:
                    raise DataIntegrityError("GV-01: monthly publication bound exceeded")
                if any(
                    ReadinessVerdict.recorded(row.detail).inputs.scope == self.scope for row in rows
                ):
                    return None

            def build() -> ReadinessVerdict:
                inputs = VerdictInputs.model_validate(self.inputs())
                if inputs.scope != self.scope:
                    raise DataIntegrityError("GV-01: publisher scope differs from evidence")
                result = record(self.ledger, inputs, self.config.gv, seed=self.config.qv.seed)
                update_progress(self.project, result)
                return result

            verdict = await asyncio.to_thread(build)
            if monthly:
                await self.notify(verdict.text(), False)
            return verdict
