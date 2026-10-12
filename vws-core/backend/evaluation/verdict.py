"""GV-01..05: informative readiness verdict; it never changes a mode."""

import hashlib
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import VerdictConfig
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import Digest, canonical_bytes
from backend.domain.models import FrozenModel, Playbook, SessionDate, UTCDateTime
from backend.evaluation.costs import Exact
from backend.evaluation.edge import Grade
from backend.indicators.statistics import BootstrapEstimate, circular_bootstrap
from backend.ops.trading_controls import ControlScope


class VerdictInputs(FrozenModel):
    scope: ControlScope
    as_of: UTCDateTime
    source: Literal["AUTO_PAPER", "EV_01_HYPOTHETICAL", "UNAVAILABLE"]
    evidence_sha256: Digest
    config_sha256: Digest
    r_multiples: tuple[Exact, ...] = Field(max_length=100000)
    sessions: tuple[SessionDate, ...] = Field(max_length=20000)
    drawdown: Exact | None = Field(ge=0, le=1)
    reduce_only_hit: StrictBool | None
    sharpe: Exact | None
    spy_total_return_sharpe: Exact | None
    recent_fault_free_sessions: int | None = Field(strict=True, ge=0, le=20000)
    drill_at: UTCDateTime | None
    security_green: bool = Field(default=False, strict=True)
    playbook_grades: tuple[tuple[str, Grade], ...] = Field(max_length=24)
    unavailable_playbooks: tuple[str, ...] = Field(
        default=(), max_length=24, exclude_if=lambda values: not values
    )
    edge_drift: StrictBool | None
    unresolved_reconciliation: StrictBool | None
    panic_this_month: StrictBool | None
    circuit_breaker_halts_this_month: int | None = Field(strict=True, ge=0, le=100000)

    @model_validator(mode="after")
    def verified_context(self) -> Self:
        if (
            self.scope.environment != "PAPER"
            or any(day > self.as_of.date() for day in self.sessions)
            or any(a >= b for a, b in zip(self.sessions, self.sessions[1:], strict=False))
            or self.drill_at is not None
            and self.drill_at > self.as_of
            or len({name for name, _ in self.playbook_grades}) != len(self.playbook_grades)
            or len(set(self.unavailable_playbooks)) != len(self.unavailable_playbooks)
            or any(
                name not in {item.value for item in Playbook} for name in self.unavailable_playbooks
            )
            or any(
                name not in {item.value for item in Playbook} for name, _ in self.playbook_grades
            )
        ):
            raise ValueError("GV: paper cohort, past evidence and unique playbooks required")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class ReadinessVerdict(FrozenModel):
    inputs: VerdictInputs
    inputs_sha256: Digest
    policy: VerdictConfig
    status: Literal["READY", "NOT_YET", "STOP"]
    confidence: BootstrapEstimate | None
    unmet: tuple[str, ...] = Field(max_length=30)
    stop_reasons: tuple[str, ...] = Field(max_length=5)
    disclaimer: Literal["Hypothetical/past results; not indicative of future returns."] = (
        "Hypothetical/past results; not indicative of future returns."
    )
    seed: int = Field(default=20261006, strict=True, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.inputs_sha256 != self.inputs.sha256:
            raise ValueError("GV-01: verdict input hash differs")
        if (self.status == "READY") != (not self.unmet and not self.stop_reasons):
            raise ValueError("GV-02: READY requires every prerequisite")
        if (self.status == "STOP") != bool(self.stop_reasons):
            raise ValueError("GV-03: STOP reasons must match the status")
        return self

    def text(self) -> str:
        label = self.status.replace("_", " ")
        source = (
            "Actual AUTO_PAPER"
            if self.inputs.source == "AUTO_PAPER"
            else "Hypothetical alert tracker"
            if self.inputs.source == "EV_01_HYPOTHETICAL"
            else "Evidence unavailable"
        )
        interval = (
            "range unavailable"
            if self.confidence is None
            else f"after-cost range {self.confidence.lower}R to {self.confidence.upper}R"
        )
        reason = (
            "; ".join(self.stop_reasons or self.unmet) or "all specified readiness checks passed"
        )
        return f"{label} · {source} · {len(self.inputs.r_multiples)} of {self.policy.min_paper_trades} resolved trades · {interval} · {reason}.\n{self.disclaimer}"

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "ReadinessVerdict":
        from datetime import datetime

        values = dict(payload)
        source = dict(values["inputs"])
        source["as_of"] = datetime.fromisoformat(source["as_of"])
        source["drill_at"] = (
            None if source["drill_at"] is None else datetime.fromisoformat(source["drill_at"])
        )
        source["sessions"] = [date.fromisoformat(day) for day in source["sessions"]]
        values["inputs"] = source
        return cls.model_validate(values)


def evaluate(
    inputs: VerdictInputs, policy: VerdictConfig, *, seed: int = 20261006
) -> ReadinessVerdict:
    source, config = VerdictInputs.model_validate(inputs), VerdictConfig.model_validate(policy)
    estimate = circular_bootstrap(source.r_multiples, seed=seed)
    count = len(source.r_multiples)
    stop = []
    if count >= 30 and estimate is not None and estimate.upper < 0:
        stop.append("after-cost expectancy range is below zero")
    if source.drawdown is not None and source.drawdown >= Decimal("0.12"):
        stop.append("drawdown reached 12%")
    if source.unresolved_reconciliation is True:
        stop.append("an unresolved reconciliation mismatch remains")
    if source.panic_this_month is True:
        stop.append("a PANIC occurred this month")
    if (
        source.circuit_breaker_halts_this_month is not None
        and source.circuit_breaker_halts_this_month >= 2
    ):
        stop.append("two circuit-breaker halts occurred this month")
    unmet = []
    if source.source == "UNAVAILABLE":
        unmet.append("paper or hypothetical evidence is unavailable")
    if count < config.min_paper_trades:
        unmet.append(f"need {config.min_paper_trades} resolved paper trades")
    if len(source.sessions) < config.min_sessions:
        unmet.append(f"need {config.min_sessions} completed sessions")
    if estimate is None or estimate.lower <= 0:
        unmet.append("after-cost expectancy range must be strictly above zero")
    if source.drawdown is None or source.drawdown > config.max_drawdown:
        unmet.append(f"drawdown must be at most {config.max_drawdown * 100}%")
    if source.reduce_only_hit is not False:
        unmet.append("CRO-09 must never have reached reduce only")
    if (
        source.sharpe is None
        or source.spy_total_return_sharpe is None
        or source.sharpe < source.spy_total_return_sharpe - config.benchmark_sharpe_tolerance
    ):
        unmet.append("Sharpe must meet the matching SPY total-return comparison")
    if (
        source.recent_fault_free_sessions is None
        or source.recent_fault_free_sessions < config.no_halt_sessions
    ):
        unmet.append(
            f"need {config.no_halt_sessions} sessions without circuit-breaker or reconciliation HALT"
        )
    if source.drill_at is None or source.as_of - source.drill_at > timedelta(
        days=config.drill_max_age_days
    ):
        unmet.append(f"need a verified emergency drill within {config.drill_max_age_days} days")
    if not source.security_green:
        unmet.append("Amendment 03 section 10 protections are unverified")
    if not source.playbook_grades or any(grade == "LOSING" for _, grade in source.playbook_grades):
        unmet.append("each playbook in use needs verified, non-losing evidence")
    if source.unavailable_playbooks:
        unmet.append("playbook evidence unavailable: " + ", ".join(source.unavailable_playbooks))
    if source.edge_drift is not False:
        unmet.append("the execution edge-drift check must be clear")
    if source.unresolved_reconciliation is not False:
        unmet.append("reconciliation must be verified and clear")
    if source.panic_this_month is None or source.circuit_breaker_halts_this_month is None:
        unmet.append("this month's incident history must be verified")
    return ReadinessVerdict(
        inputs=source,
        inputs_sha256=source.sha256,
        policy=config,
        status="STOP" if stop else "NOT_YET" if unmet else "READY",
        confidence=estimate,
        unmet=tuple(unmet),
        stop_reasons=tuple(stop),
        seed=seed,
    )


def record(
    ledger: Ledger, inputs: VerdictInputs, policy: VerdictConfig, *, seed: int = 20261006
) -> ReadinessVerdict:
    verdict = evaluate(inputs, policy, seed=seed)
    if verdict.inputs.as_of > ensure_utc(ledger.clock.now()):
        raise DataIntegrityError("GV-01: cannot record a future verdict")
    ledger.verify_chain()
    ledger.append(SecurityEvent, kind="VERDICT", detail=verdict.model_dump(mode="json"))
    return verdict


def latest_ready(ledger: Ledger, account_id: str, config_hash: str, max_age_days: int = 35) -> bool:
    if type(max_age_days) is not int or not 1 <= max_age_days <= 35:
        raise DataIntegrityError("GV-05: READY evidence age may only be stricter")
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "VERDICT")
                .order_by(SecurityEvent.seq.desc())
                .limit(1001)
            )
        )
    if len(rows) > 1000:
        raise DataIntegrityError("GV-05: verdict history exceeds the bounded window")
    now = ensure_utc(ledger.clock.now())
    for row in rows:
        verdict = ReadinessVerdict.recorded(row.detail)
        if verdict != evaluate(verdict.inputs, verdict.policy, seed=verdict.seed):
            raise DataIntegrityError("GV-05: verdict result differs from its immutable inputs")
        if row.created_at > now or verdict.inputs.as_of > row.created_at:
            raise DataIntegrityError("GV-05: verdict time provenance differs")
        if verdict.inputs.scope.account_id == account_id:
            # Amendment 05 explicitly permits labeled EV-01 fallback data.
            # AX-40's separate actual paper history/report checks still apply.
            return (
                verdict.status == "READY"
                and verdict.inputs.source in {"AUTO_PAPER", "EV_01_HYPOTHETICAL"}
                and verdict.inputs.config_sha256 == config_hash
                and now - verdict.inputs.as_of <= timedelta(days=max_age_days)
            )
    return False
