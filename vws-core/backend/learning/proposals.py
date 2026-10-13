"""LP-01..07: fixed registered evidence produces suggestions, never settings."""

import hashlib
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import LearningJournalConfig, LessonProposalConfig, YamlConfig
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import Digest, canonical_bytes
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, Money
from backend.evaluation.registry import Registration, Variant
from backend.evaluation.walkforward import ValidationRun
from backend.indicators.statistics import BootstrapEstimate, circular_bootstrap
from backend.indicators.validation import holm
from backend.learning.journal import Cause, JournalRow
from backend.ops.anchors import controlled_path
from backend.ops.trading_controls import ControlScope


class LessonProposal(FrozenModel):
    id: Digest
    scope: ControlScope
    cause_tag: Cause
    playbook: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    variant: Variant
    validation_sha256: Digest
    registration_sha256: Digest
    n: int = Field(strict=True, ge=15, le=100000)
    cumulative_trials: int = Field(strict=True, ge=1, le=1000000)
    confidence: BootstrapEstimate
    expected_daily_return_lift: Money
    tag_breakdown: tuple[tuple[Cause, int], ...] = Field(min_length=1, max_length=14)
    what: str = Field(strict=True, min_length=1, max_length=500)
    risk: str = Field(strict=True, min_length=1, max_length=500)
    effort: str = Field(strict=True, min_length=1, max_length=280)
    status: Literal["OPEN"] = "OPEN"

    @model_validator(mode="after")
    def proposal_only(self) -> Self:
        if (
            self.cause_tag == Cause.NORMAL_VARIANCE
            or len(self.variant.overrides) != 1
            or self.confidence.lower <= 0
            or self.confidence.lower > self.expected_daily_return_lift
            or self.expected_daily_return_lift > self.confidence.upper
            or any(type(n) is not int or n < 0 for _, n in self.tag_breakdown)
        ):
            raise ValueError("LP: one review-only change needs positive corrected evidence")
        values = self.model_dump(mode="json", exclude={"id"})
        if self.id != proposal_id(values):
            raise ValueError("LP: immutable proposal identity differs")
        return self


def proposal_id(values: dict[str, Any]) -> str:
    import json

    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


class MiningResult(FrozenModel):
    proposals: tuple[LessonProposal, ...] = Field(max_length=10)
    insufficient: tuple[str, ...] = Field(max_length=1000)
    normal_variance_rows: int = Field(strict=True, ge=0)


def reducing_variant(variant: Variant, baseline: YamlConfig) -> bool:
    row, policy = Variant.model_validate(variant), YamlConfig.model_validate(baseline)
    if len(row.overrides) != 1:
        return False
    key, value = next(iter(row.overrides.items()))
    if key == "rs.use_breadth":
        return value is True
    if key == "rs.sector_filter":
        return value in {"half_size_outside", "top_n"} and policy.rs.sector_filter == "annotate"
    if key == "rs.min_stock_percentile":
        return (
            isinstance(value, (Decimal, int))
            and not isinstance(value, bool)
            and value >= policy.rs.min_stock_percentile
        )
    if key == "rs.top_n_sectors":
        return type(value) is int and value <= policy.rs.top_n_sectors
    return (
        key == "playbooks.enabled"
        and isinstance(value, tuple)
        and set(value).issubset(policy.enabled_playbooks)
    )


def mine(
    journal: tuple[JournalRow, ...],
    registration: Registration,
    runs: tuple[ValidationRun, ...],
    baseline: YamlConfig,
    lj: LearningJournalConfig,
    lp: LessonProposalConfig,
    *,
    seed: int = 20261006,
    open_count: int = 0,
    calendar: MarketCalendar,
) -> MiningResult:
    policy, limits = (
        LearningJournalConfig.model_validate(lj),
        LessonProposalConfig.model_validate(lp),
    )
    proof = Registration.model_validate(registration)
    if (
        not isinstance(journal, tuple)
        or len(journal) > 100000
        or not isinstance(runs, tuple)
        or len(runs) > 1000
        or type(open_count) is not int
        or not 0 <= open_count <= limits.max_open_proposals
    ):
        raise DataIntegrityError("LP: bounded frozen inventory required")
    rows = tuple(JournalRow.model_validate(row) for row in journal)
    if (
        len({row.key for row in rows}) != len(rows)
        or len({row.observation.scope for row in rows}) > 1
    ):
        raise DataIntegrityError("LP: duplicate or mixed-account journal evidence")
    scope = rows[0].observation.scope if rows else None
    cells: dict[tuple[Cause, str], set[str]] = defaultdict(set)
    for row in rows:
        if row.cause_tag != Cause.NORMAL_VARIANCE:
            # Split fills, stop and loss triggers from one proposed trade are
            # one independent episode, never extra statistical observations.
            cells[(row.cause_tag, row.observation.playbook)].add(str(row.observation.proposal_id))
    unavailable: list[str] = []
    proposed: list[LessonProposal] = []
    checked_runs = tuple(ValidationRun.model_validate(run) for run in runs)
    if any(
        run.registration_sha256 != proof.sha256
        or run.history_sha256 != proof.history_sha256
        or run.kind != "WALKFORWARD"
        for run in checked_runs
    ):
        raise DataIntegrityError(
            "LP-02: only the current preregistered full OOS evidence is admissible"
        )
    run_by_family = {run.family: run for run in checked_runs}
    if len(run_by_family) != len(checked_runs):
        raise DataIntegrityError("LP: duplicate validation family")
    for (cause, playbook), identities in sorted(cells.items()):
        n = len(identities)
        if n < policy.min_tag_n:
            unavailable.append(
                f"{cause} / {playbook}: INSUFFICIENT ({n} distinct trades; need {policy.min_tag_n})"
            )
            continue
        available = [
            (family, run_by_family[family.name])
            for family in proof.registry.families
            if family.name in run_by_family
        ]
        if not available or scope is None:
            unavailable.append(f"{cause} / {playbook}: INSUFFICIENT registered paired OOS evidence")
            continue
        made = False
        for family, run in available:
            results = {row.variant: row for row in run.results}
            reference = results.get("BASELINE")
            if reference is None or not reference.sample.daily:
                continue
            dates = tuple(
                reference.sample.start + timedelta(days=offset)
                for offset in range((reference.sample.end - reference.sample.start).days + 1)
                if calendar.is_session(reference.sample.start + timedelta(days=offset))
            )
            if tuple(day for day, _ in reference.sample.daily) != dates:
                raise DataIntegrityError("LP-02: incomplete baseline OOS daily cohort")
            candidates = []
            for variant in family.variants[1:]:
                result = results.get(variant.name)
                if result is None or not reducing_variant(variant, baseline):
                    continue
                if tuple(day for day, _ in result.sample.daily) != dates or (
                    result.sample.start,
                    result.sample.end,
                ) != (reference.sample.start, reference.sample.end):
                    raise DataIntegrityError("LP-02: candidate and baseline OOS sessions differ")
                differences = tuple(
                    candidate - original
                    for (_, candidate), (_, original) in zip(
                        result.sample.daily, reference.sample.daily, strict=True
                    )
                )
                estimate = circular_bootstrap(differences, seed=seed)
                if estimate is not None:
                    candidates.append(
                        (variant, estimate, sum(differences, Decimal(0)) / len(differences))
                    )
            trials = dict(proof.cumulative_trials)[family.name]
            if len(candidates) > trials:
                raise DataIntegrityError("LP-02: candidate count exceeds cumulative attempts")
            decisions = (
                holm(
                    tuple(estimate.p_nonpositive for _, estimate, _ in candidates),
                    unobserved_trials=trials - len(candidates),
                )
                if candidates
                else ()
            )
            for (variant, estimate, lift), significant in zip(candidates, decisions, strict=True):
                if (
                    not significant
                    or estimate.lower <= 0
                    or len(proposed) + open_count >= limits.max_open_proposals
                ):
                    continue
                values = {
                    "scope": scope,
                    "cause_tag": cause,
                    "playbook": playbook,
                    "variant": variant,
                    "validation_sha256": run.sha256,
                    "registration_sha256": proof.sha256,
                    "n": n,
                    "cumulative_trials": trials,
                    "confidence": estimate,
                    "expected_daily_return_lift": lift.quantize(Decimal("0.000001")),
                    "tag_breakdown": tuple(
                        (
                            tag,
                            sum(
                                row.cause_tag == tag and row.observation.playbook == playbook
                                for row in rows
                            ),
                        )
                        for tag in Cause
                    ),
                    "what": f"Review {variant.name}: {next(iter(variant.overrides))}. Approval, QV registration, walk-forward and paper evidence must precede a host setting change.",
                    "risk": "Lift uses the complete paired OOS portfolio window, not selected losses. This is not proof that the filter fixes this cause or predicts future edge. It may miss valid entries; NORMAL_VARIANCE is expected noise.",
                    "effort": "Owner review, one fixed registered override, validation and paper observation.",
                    "status": "OPEN",
                }
                from pydantic import TypeAdapter

                payload = TypeAdapter(dict[str, Any]).dump_python(values, mode="json")
                proposed.append(
                    LessonProposal.model_validate({"id": proposal_id(payload), **values})
                )
                made = True
        if not made:
            unavailable.append(
                f"{cause} / {playbook}: no positive corrected 90% CI; no change proposed"
            )
    return MiningResult(
        proposals=tuple(proposed),
        insufficient=tuple(unavailable),
        normal_variance_rows=sum(row.cause_tag == Cause.NORMAL_VARIANCE for row in rows),
    )


def suggestion(proposal: LessonProposal) -> str:
    row = LessonProposal.model_validate(proposal)
    return f"- LP {row.id}: OPEN, awaiting owner's plain-words approval. Purpose: {row.what} Benefit: observed daily return lift {row.expected_daily_return_lift} (90% CI {row.confidence.lower} to {row.confidence.upper}; n={row.n}; cumulative trials={row.cumulative_trials}). Risk: {row.risk} Effort: {row.effort}"


class ProposalStore:
    def __init__(self, ledger: Ledger, scope: ControlScope) -> None:
        self.ledger, self.scope = ledger, ControlScope.model_validate(scope)

    def open(self) -> tuple[LessonProposal, ...]:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            return self._open_in_session(session)

    def _open_in_session(self, session: Session) -> tuple[LessonProposal, ...]:
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind.in_(("LESSON_PROPOSED", "LESSON_REVIEWED")),
                    SecurityEvent.detail["scope"]["account_id"].as_string()
                    == self.scope.account_id,
                    SecurityEvent.detail["scope"]["environment"].as_string()
                    == self.scope.environment,
                )
                .order_by(SecurityEvent.seq)
                .limit(1001)
            )
        )
        if len(rows) > 1000 or any(row.ts > self.ledger.clock.now() for row in rows):
            raise DataIntegrityError("LP: open proposal inventory exceeds its cap")
        proposed: dict[str, LessonProposal] = {}
        reviewed: set[str] = set()
        for row in rows:
            if row.kind == "LESSON_PROPOSED":
                value = LessonProposal.model_validate(row.detail["proposal"])
                if value.scope != self.scope or value.id in proposed:
                    raise DataIntegrityError("LP: proposal scope or immutable identity differs")
                proposed[value.id] = value
            else:
                if (
                    row.detail.get("status")
                    not in {"DECLINED", "ABANDONED", "ACCEPTED_FOR_TESTING"}
                    or row.detail.get("id") not in proposed
                    or row.detail["id"] in reviewed
                ):
                    raise DataIntegrityError("LP: invalid or duplicate host review")
                reviewed.add(row.detail["id"])
        values = tuple(value for key, value in proposed.items() if key not in reviewed)
        if len(values) > 10:
            raise DataIntegrityError("LP: open proposal inventory exceeds its cap")
        return values

    def resolve_review(
        self,
        identity: str,
        status: Literal["DECLINED", "ABANDONED", "ACCEPTED_FOR_TESTING"],
        operator: str,
        root: Path,
    ) -> None:
        """Host review API only. This neither registers nor applies a variant."""
        if (
            status not in {"DECLINED", "ABANDONED", "ACCEPTED_FOR_TESTING"}
            or not isinstance(operator, str)
            or not 1 <= len(operator.strip()) <= 128
            or not operator.isprintable()
        ):
            raise DataIntegrityError("LP-04: explicit bounded host review required")
        progress = controlled_path(root / "docs/PROGRESS.md")
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            value = next(
                (row for row in self._open_in_session(session) if row.id == identity), None
            )
            if value is None:
                raise DataIntegrityError("LP-04: open immutable proposal required")
            text = progress.read_text(encoding="utf-8")
            old = suggestion(value)
            if old not in text:
                raise DataIntegrityError("LP-04: proposal must remain in Suggestions")
            progress.write_text(
                text.replace(
                    old,
                    old.replace(
                        "OPEN, awaiting owner's plain-words approval",
                        status + ", owner review recorded",
                    ),
                ),
                encoding="utf-8",
            )
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="LESSON_REVIEWED",
                detail={
                    "scope": self.scope.model_dump(mode="json"),
                    "id": identity,
                    "status": status,
                    "operator": operator,
                },
            )

    def publish(self, proposal: LessonProposal, root: Path) -> bool:
        row = LessonProposal.model_validate(proposal)
        if row.scope != self.scope:
            raise DataIntegrityError("LP: proposal account binding differs")
        directory = controlled_path(root / "data/proposals")
        progress = controlled_path(root / "docs/PROGRESS.md")
        if not progress.is_file() or progress.stat().st_size > 65536:
            raise DataIntegrityError("LP: bounded progress page required")
        text = progress.read_text(encoding="utf-8")
        line = suggestion(row)
        if "## Suggestions" not in text or len(text.splitlines()) + int(line not in text) > 60:
            raise DataIntegrityError(
                "LP: Suggestions must exist with space within the 60-line progress bound"
            )
        directory.mkdir(parents=True, exist_ok=True)
        target = controlled_path(directory / f"{row.id}.json")
        raw = canonical_bytes(row)
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            prior = self._open_in_session(session)
            historical = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "LESSON_PROPOSED",
                    SecurityEvent.detail["proposal"]["id"].as_string() == row.id,
                )
                .limit(1)
            )
            if historical is not None and not any(old.id == row.id for old in prior):
                if (
                    LessonProposal.model_validate(historical.detail["proposal"]) != row
                    or not target.is_file()
                    or target.read_bytes() != raw
                ):
                    raise DataIntegrityError("LP: reviewed immutable proposal differs")
                return False  # Declined/accepted ideas cannot reopen themselves.
            if any(old.id == row.id for old in prior):
                if not target.is_file() or target.read_bytes() != raw or line not in text:
                    raise DataIntegrityError("LP: immutable proposal publication differs")
                return False
            if len(prior) >= 10:
                raise DataIntegrityError("LP-01: ten open review proposals already exist")
            directory.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != raw:
                    raise DataIntegrityError("LP: proposal file collision")
            else:
                with target.open("xb") as stream:
                    stream.write(raw)
            # This sole documentation output cannot apply a setting or register
            # a variant. The package/config/env write guard stays in force.
            if line not in text:
                progress.write_text(text.rstrip() + "\n" + line + "\n", encoding="utf-8")
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="LESSON_PROPOSED",
                detail={
                    "scope": self.scope.model_dump(mode="json"),
                    "proposal": row.model_dump(mode="json"),
                },
            )
        return True

    def masked(self) -> str:
        rows = self.open()
        return (
            "Lessons for owner review\n"
            + (
                "\n".join(
                    f"{row.cause_tag} / {row.playbook}: {row.variant.name}; positive 90% OOS CI; awaiting approval."
                    for row in rows
                )
                if rows
                else "No open proposals."
            )
            + "\nHypothetical/past results; not indicative of future returns."
        )
