"""LJ-01..08/AC-03: deterministic tagging and append-only, scoped journal."""

import hashlib
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from html import escape
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import canonical_bytes
from backend.domain.models import FrozenModel, Money, Price, Symbol, UTCDateTime
from backend.evaluation.costs import Exact
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import ContextTag


class Cause(StrEnum):
    GAP_THROUGH_STOP = "GAP_THROUGH_STOP"
    LATE_ENTRY = "LATE_ENTRY"
    NEWS_SHOCK = "NEWS_SHOCK"
    REGIME_SHIFT = "REGIME_SHIFT"
    SLIPPAGE_ABOVE_MODEL = "SLIPPAGE_ABOVE_MODEL"
    EARNINGS_SURPRISE = "EARNINGS_SURPRISE"
    SECTOR_WEAK = "SECTOR_WEAK"
    NORMAL_VARIANCE = "NORMAL_VARIANCE"
    RULE_BLOCKED_REGRET = "RULE_BLOCKED_REGRET"
    MISSED_FILL = "MISSED_FILL"
    DATA_OPS_INCIDENT = "DATA_OPS_INCIDENT"
    HALT_DURING_HOLD = "HALT_DURING_HOLD"
    DILUTION_EVENT = "DILUTION_EVENT"
    UNCLASSIFIED = "UNCLASSIFIED"


Trigger = Literal["LOSS", "STOP", "SLIPPAGE", "MISSED_FILL", "REGRETTED", "INCIDENT"]


class Observation(FrozenModel):
    trade_id: UUID
    proposal_id: UUID
    scope: ControlScope
    symbol: Symbol
    playbook: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    variant_id: str = Field(default="BASELINE", strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    at: UTCDateTime
    entry_at: UTCDateTime | None = None
    exit_at: UTCDateTime | None = None
    entry_price: Price | None = None
    exit_price: Price | None = None
    r_after_costs: Exact | None = None
    mfe_r: Exact | None = Field(default=None, ge=0)
    mae_r: Exact | None = Field(default=None, le=0)
    stop: Price
    target: Price
    multiplier_product: Exact = Field(default=Decimal(1), ge=0, le=1)
    context_tags: tuple[ContextTag, ...] = Field(default=(), max_length=21)
    cause_context_tags: tuple[ContextTag, ...] | None = Field(default=None, max_length=21)
    blocked_rules: tuple[str, ...] = Field(default=(), max_length=30)
    fill_vs_model_bps: Money | None = None
    bucket_p90_bps: Money | None = None
    gap_open: Price | None = None
    stopped: bool = Field(default=False, strict=True)
    never_traded_through: bool = Field(default=False, strict=True)
    regretted: bool = Field(default=False, strict=True)
    incident: str | None = Field(default=None, strict=True, min_length=1, max_length=160)
    oos_abs_mean: Exact | None = Field(default=None, ge=0)
    oos_stddev: Exact | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def evidence(self) -> Self:
        if (
            (self.entry_at is None) != (self.entry_price is None)
            or (self.exit_at is None) != (self.exit_price is None)
            or self.exit_at is not None
            and (self.entry_at is None or self.exit_at < self.entry_at)
            or any(time is not None and time > self.at for time in (self.entry_at, self.exit_at))
            or self.r_after_costs is not None
            and self.exit_at is None
            or (self.oos_abs_mean is None) != (self.oos_stddev is None)
            or len(set(self.context_tags)) != len(self.context_tags)
            or self.cause_context_tags is not None
            and len(set(self.cause_context_tags)) != len(self.cause_context_tags)
            or len(set(self.blocked_rules)) != len(self.blocked_rules)
            or any(
                not isinstance(rule, str) or not 1 <= len(rule) <= 120
                for rule in self.blocked_rules
            )
            or self.regretted
            and not self.blocked_rules
        ):
            raise ValueError(
                "LJ-02: causal structured evidence required; unknown excursions stay unset"
            )
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "Observation":
        try:
            values = dict(payload)
            for name in ("at", "entry_at", "exit_at"):
                if values[name] is not None:
                    values[name] = datetime.fromisoformat(values[name])
            for name in ("entry_price", "exit_price", "stop", "target", "gap_open"):
                if values[name] is not None:
                    if not isinstance(values[name], str):
                        raise ValueError("stored prices require exact strings")
                    values[name] = Decimal(values[name])
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("LJ: stored observation is malformed") from None


def cause_for(observation: Observation, trigger: Trigger) -> Cause:
    row = Observation.model_validate(observation)
    if trigger == "REGRETTED":
        return Cause.RULE_BLOCKED_REGRET
    if trigger == "INCIDENT":
        return Cause.DATA_OPS_INCIDENT
    if trigger == "MISSED_FILL":
        return Cause.MISSED_FILL
    if row.gap_open is not None and row.gap_open < row.stop:
        return Cause.GAP_THROUGH_STOP
    if (
        row.fill_vs_model_bps is not None
        and row.bucket_p90_bps is not None
        and row.fill_vs_model_bps > row.bucket_p90_bps
    ):
        return Cause.SLIPPAGE_ABOVE_MODEL
    tags = row.context_tags if row.cause_context_tags is None else row.cause_context_tags
    if ContextTag.NEWS_NEG in tags:
        return Cause.NEWS_SHOCK
    if ContextTag.DILUTION in tags:
        return Cause.DILUTION_EVENT
    if ContextTag.HALT in tags:
        return Cause.HALT_DURING_HOLD
    if (
        row.r_after_costs is not None
        and row.oos_abs_mean is not None
        and row.oos_stddev is not None
        and abs(row.r_after_costs) <= row.oos_abs_mean + row.oos_stddev
    ):
        return Cause.NORMAL_VARIANCE
    return Cause.UNCLASSIFIED


def triggers(observation: Observation) -> tuple[Trigger, ...]:
    row = Observation.model_validate(observation)
    result: list[Trigger] = []
    if row.r_after_costs is not None and row.r_after_costs < 0:
        result.append("LOSS")
    if row.stopped:
        result.append("STOP")
    if (
        row.fill_vs_model_bps is not None
        and row.bucket_p90_bps is not None
        and row.fill_vs_model_bps > row.bucket_p90_bps
    ):
        result.append("SLIPPAGE")
    if row.never_traded_through:
        result.append("MISSED_FILL")
    if row.regretted:
        result.append("REGRETTED")
    if row.incident is not None:
        result.append("INCIDENT")
    return tuple(result)


class JournalRow(FrozenModel):
    trigger: Trigger
    cause_tag: Cause
    observation: Observation
    narrative: str | None = Field(default=None, strict=True, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def code_authority(self) -> Self:
        if self.trigger not in triggers(self.observation) or self.cause_tag != cause_for(
            self.observation, self.trigger
        ):
            raise ValueError("LJ-04: code alone decides triggers and primary causes")
        return self

    @property
    def key(self) -> str:
        return hashlib.sha256(
            f"{self.trigger}:{self.observation.trade_id}:{self.cause_tag}".encode("ascii")
        ).hexdigest()

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "JournalRow":
        try:
            values = dict(payload)
            values["observation"] = Observation.recorded(values["observation"])
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("LJ: stored journal row is malformed") from None


class MistakeJournal:
    def __init__(self, ledger: Ledger, scope: ControlScope) -> None:
        self.ledger, self.scope = ledger, ControlScope.model_validate(scope)

    def _rows(self, session: Session) -> tuple[SecurityEvent, ...]:
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "LEARNING_JOURNAL",
                    SecurityEvent.detail["scope"]["account_id"].as_string()
                    == self.scope.account_id,
                    SecurityEvent.detail["scope"]["environment"].as_string()
                    == self.scope.environment,
                )
                .order_by(SecurityEvent.seq)
                .limit(100001)
            )
        )
        if len(rows) > 100000 or any(row.ts > self.ledger.clock.now() for row in rows):
            raise DataIntegrityError("LJ: journal requires bounded causal history")
        return rows

    def record(self, observation: Observation) -> int:
        checked = Observation.model_validate(observation)
        if checked.scope != self.scope or checked.at > self.ledger.clock.now():
            raise DataIntegrityError("LJ: observation scope or time differs")
        added = 0
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            prior = {row.detail["key"]: row for row in self._rows(session)}
            for trigger in triggers(checked):
                value = JournalRow(
                    trigger=trigger, cause_tag=cause_for(checked, trigger), observation=checked
                )
                old = prior.get(value.key)
                if old is not None:
                    if canonical_bytes(JournalRow.recorded(old.detail["row"])) != canonical_bytes(
                        value
                    ):
                        raise DataIntegrityError(
                            "LJ-06: repeated trigger changed immutable evidence"
                        )
                    continue
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="LEARNING_JOURNAL",
                    detail={
                        "scope": self.scope.model_dump(mode="json"),
                        "key": value.key,
                        "row": value.model_dump(mode="json"),
                    },
                )
                added += 1
        return added

    def rows(self) -> tuple[JournalRow, ...]:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            stored = self._rows(session)
            drafts = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "LEARNING_NARRATIVE",
                        SecurityEvent.detail["scope"]["account_id"].as_string()
                        == self.scope.account_id,
                        SecurityEvent.detail["scope"]["environment"].as_string()
                        == self.scope.environment,
                    )
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
        result = tuple(JournalRow.recorded(row.detail["row"]) for row in stored)
        if len({row.key for row in result}) != len(result) or any(
            value.key != row.detail["key"]
            or value.observation.scope != self.scope
            or value.observation.at > row.ts
            for value, row in zip(result, stored, strict=True)
        ):
            raise DataIntegrityError("LJ: journal receipt or identity differs")
        if len(drafts) > 100000 or len({row.detail["key"] for row in drafts}) != len(drafts):
            raise DataIntegrityError("LJ: bounded unique narrative inventory required")
        summaries = {row.detail["key"]: row.detail["summary"] for row in drafts}
        if any(
            row.ts > self.ledger.clock.now()
            or row.detail["key"] not in {value.key for value in result}
            for row in drafts
        ):
            raise DataIntegrityError("LJ: narrative receipt lacks causal structured evidence")
        return tuple(
            JournalRow.model_validate(
                row.model_copy(update={"narrative": summaries.get(row.key, row.narrative)})
            )
            for row in result
        )

    def replay(self) -> bytes:
        return b"".join(canonical_bytes(row) for row in self.rows())

    def recent(self, count: int = 10) -> str:
        if type(count) is not int or not 1 <= count <= 50:
            raise DataIntegrityError("LJ-07: recent count must be 1 to 50")
        rows = self.rows()[-count:]
        lines = ["Learning journal (masked)"]
        for row in rows:
            obs = row.observation
            result = (
                "unresolved" if obs.r_after_costs is None else f"{obs.r_after_costs}R after costs"
            )
            lines.append(
                escape(
                    f"{obs.symbol} {obs.playbook} {row.trigger}: {row.cause_tag}; {result}. Proposal {obs.proposal_id}"
                )
            )
            if row.narrative is not None:
                lines.append(escape(row.narrative))
        return "\n".join(lines if rows else [*lines, "No recorded lessons."])

    def summary(self, open_proposals: int) -> str:
        if type(open_proposals) is not int or not 0 <= open_proposals <= 10:
            raise DataIntegrityError("LJ-08: bounded open proposal count required")
        rows = self.rows()
        counts = {tag: sum(row.cause_tag == tag for row in rows) for tag in Cause}
        noise = counts[Cause.NORMAL_VARIANCE]
        share = Decimal(0) if not rows else Decimal(noise) / len(rows)
        return (
            "Lessons\n"
            + "\n".join(f"{tag}: {count}" for tag, count in counts.items() if count)
            + f"\nExpected noise: {noise}/{len(rows)} ({share:.1%}). Open review proposals: {open_proposals}.\nHypothetical/past results; not indicative of future returns."
        )
