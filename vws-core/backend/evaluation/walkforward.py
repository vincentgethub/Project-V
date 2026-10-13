"""QV-03..07: fixed anchored folds and immutable OOS evidence, never a search."""

import csv
import hashlib
import io
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select

from backend.core.config import ValidationConfig
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import Digest, canonical_bytes
from backend.domain.models import FrozenModel, Money, Playbook, SessionDate
from backend.evaluation.edge import Grade, edge_grade
from backend.evaluation.registry import (
    Registration,
    Registrations,
    Variant,
    VariantFamily,
    add_months,
)
from backend.evaluation.universe import PIT_NOTICE
from backend.evaluation.weekly import DISCLAIMER, SURVIVORSHIP_NOTICE
from backend.indicators.statistics import BootstrapEstimate, circular_bootstrap
from backend.indicators.validation import deflated_sharpe, holm
from backend.ops.anchors import controlled_path


class ValidationTrade(FrozenModel):
    identity: UUID
    decision: SessionDate
    entry: SessionDate
    exit: SessionDate
    r_multiple: Money
    net_money: Money
    playbook: Playbook | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def causal(self) -> Self:
        if not self.decision < self.entry <= self.exit:
            raise ValueError("QV-06: fills follow the decision and precede the exit")
        return self


class Sample(FrozenModel):
    variant: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    start: SessionDate
    end: SessionDate
    history_sha256: Digest
    trades: tuple[ValidationTrade, ...] = Field(max_length=100000)
    daily: tuple[tuple[SessionDate, Money], ...] = Field(max_length=20000)

    @model_validator(mode="after")
    def scoped(self) -> Self:
        if (
            self.start >= self.end
            or len({row.identity for row in self.trades}) != len(self.trades)
            or any(
                not self.start <= row.decision < row.entry <= row.exit <= self.end
                for row in self.trades
            )
            or self.trades
            != tuple(sorted(self.trades, key=lambda row: (row.exit, row.identity.hex)))
            or any(not self.start <= day <= self.end for day, _ in self.daily)
            or any(a[0] >= b[0] for a, b in zip(self.daily, self.daily[1:], strict=False))
        ):
            raise ValueError(
                "QV-03/06: ordered, causal, unique samples must stay inside the window"
            )
        return self


class Fold(FrozenModel):
    train_start: SessionDate
    train_end: SessionDate
    test_start: SessionDate
    test_end: SessionDate

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.train_start < self.train_end < self.test_start < self.test_end:
            raise ValueError("QV-03: train precedes the test window")
        return self


def folds(
    sessions: tuple[date, ...], registration: Registration, policy: ValidationConfig
) -> tuple[Fold, ...]:
    proof, config = (
        Registration.model_validate(registration),
        ValidationConfig.model_validate(policy),
    )
    if (
        not isinstance(sessions, tuple)
        or len(sessions) > 20000
        or any(type(day) is not date for day in sessions)
        or sessions != tuple(sorted(set(sessions)))
    ):
        raise DataIntegrityError("QV-03: bounded increasing completed sessions required")
    available = tuple(day for day in sessions if day < proof.holdout_start)
    if len(available) <= 202:
        raise ConfigurationError("QV-03: warm-up leaves no anchored training window")
    train_start = available[200]
    boundary = add_months(train_start, config.test_months)
    result = []
    while boundary < proof.holdout_start:
        following = add_months(boundary, config.test_months)
        if following > proof.holdout_start:
            break
        training = [day for day in available if train_start <= day < boundary]
        testing = [day for day in available if boundary <= day < following]
        if len(training) >= 2 and len(testing) >= 2:
            result.append(
                Fold(
                    train_start=train_start,
                    train_end=training[-1],
                    test_start=testing[0],
                    test_end=testing[-1],
                )
            )
        boundary = following
    if not result:
        raise ConfigurationError("QV-03: no complete six-month test fold before the holdout")
    return tuple(result)


def select_variant(
    training: tuple[Sample, ...], family: VariantFamily, policy: ValidationConfig
) -> str:
    fixed, config = VariantFamily.model_validate(family), ValidationConfig.model_validate(policy)
    if tuple(row.variant for row in training) != tuple(row.name for row in fixed.variants):
        raise DataIntegrityError("QV-03: training samples differ from the registered order")
    windows = {(row.start, row.end, row.history_sha256) for row in training}
    if len(windows) != 1:
        raise DataIntegrityError("QV-03: all train samples share one frozen window")
    candidates = {}
    for sample in training:
        checked = Sample.model_validate(sample)
        if len(checked.trades) >= config.min_train_trades:
            estimate = circular_bootstrap(
                tuple(row.r_multiple for row in checked.trades), seed=config.seed
            )
            if estimate is not None:
                candidates[sample.variant] = estimate.lower
    if not candidates:
        return "BASELINE"
    best = max(candidates.values())
    winners = [name for name, lower in candidates.items() if lower == best]
    return winners[0] if len(winners) == 1 else "BASELINE"


class FoldSelection(FrozenModel):
    fold: Fold
    selected: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    training_sha256: tuple[Digest, ...] = Field(min_length=1, max_length=8)
    test_sha256: tuple[Digest, ...] = Field(min_length=1, max_length=8)


class OOSResult(FrozenModel):
    variant: str = Field(strict=True, pattern=r"^(SELECTED|[A-Z][A-Z0-9_]{0,63})$")
    n: int = Field(strict=True, ge=0)
    expectancy: Money | None
    confidence: BootstrapEstimate | None
    profit_factor: Money | None = Field(ge=0)
    dsr: Money | None = Field(ge=0, le=1)
    holm_rejects_zero: bool | None
    status: Literal["SUFFICIENT", "INSUFFICIENT"]
    grade: Grade
    sample: Sample

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (
            self.variant != self.sample.variant
            or self.n != len(self.sample.trades)
            or (self.n == 0) != (self.confidence is None)
            or (self.n == 0) != (self.expectancy is None)
            or (self.n >= 30) != (self.status == "SUFFICIENT")
            or self.n < 30
            and self.grade != "UNPROVEN"
        ):
            raise ValueError("QV-04: OOS count, availability and grade differ from the sample")
        return self


class ValidationRun(FrozenModel):
    registration_sha256: Digest
    history_sha256: Digest
    family: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    kind: Literal["WALKFORWARD", "HOLDOUT"]
    selections: tuple[FoldSelection, ...] = Field(max_length=100)
    results: tuple[OOSResult, ...] = Field(min_length=2, max_length=9)
    notices: tuple[str, ...] = (DISCLAIMER, SURVIVORSHIP_NOTICE)
    universe_sha256: Digest | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (
            self.results[0].variant != "SELECTED"
            or len({row.variant for row in self.results}) != len(self.results)
            or any(row.sample.history_sha256 != self.history_sha256 for row in self.results)
            or self.notices
            != (DISCLAIMER, PIT_NOTICE if self.universe_sha256 is not None else SURVIVORSHIP_NOTICE)
            or (self.kind == "WALKFORWARD") != bool(self.selections)
        ):
            raise ValueError("QV-07: result identity, notices or fold evidence differs")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "ValidationRun":
        values = dict(payload)
        selections = []
        for selection in values["selections"]:
            row = dict(selection)
            row["fold"] = {name: date.fromisoformat(value) for name, value in row["fold"].items()}
            selections.append(row)
        values["selections"] = selections
        results = []
        for result in values["results"]:
            row = dict(result)
            sample = dict(row["sample"])
            sample["start"], sample["end"] = (
                date.fromisoformat(sample["start"]),
                date.fromisoformat(sample["end"]),
            )
            sample["daily"] = [(date.fromisoformat(day), value) for day, value in sample["daily"]]
            sample["trades"] = [
                {
                    **trade,
                    **{
                        name: date.fromisoformat(trade[name])
                        for name in ("decision", "entry", "exit")
                    },
                }
                for trade in sample["trades"]
            ]
            row["sample"] = sample
            results.append(row)
        values["results"] = results
        return cls.model_validate(values)


Evaluator = Callable[[Variant, date, date], Sample]


def _join(name: str, samples: tuple[Sample, ...]) -> Sample:
    if not samples:
        raise ConfigurationError("QV-04: no out-of-sample windows")
    if len({row.history_sha256 for row in samples}) != 1 or any(
        a.end >= b.start for a, b in zip(samples, samples[1:], strict=False)
    ):
        raise DataIntegrityError("QV-03: OOS windows overlap or use different histories")
    return Sample(
        variant=name,
        start=samples[0].start,
        end=samples[-1].end,
        history_sha256=samples[0].history_sha256,
        trades=tuple(
            sorted(
                (trade for row in samples for trade in row.trades),
                key=lambda row: (row.exit, row.identity.hex),
            )
        ),
        daily=tuple(item for row in samples for item in row.daily),
    )


def _results(
    samples: tuple[Sample, ...], trials: int, config: ValidationConfig
) -> tuple[OOSResult, ...]:
    # The selected stream is not another independent trial in the family correction.
    estimates = tuple(
        circular_bootstrap(tuple(trade.r_multiple for trade in row.trades), seed=config.seed)
        for row in samples
    )
    reject = holm(
        tuple(
            Decimal(1) if estimate is None else estimate.p_nonpositive for estimate in estimates[1:]
        ),
        unobserved_trials=max(0, trials - len(samples) + 1),
    )
    dates = tuple(day for day, _ in samples[0].daily)
    if any(tuple(day for day, _ in row.daily) != dates for row in samples):
        raise DataIntegrityError("QV-05: variants must share the same OOS daily sessions")
    daily = tuple(tuple(value for _, value in row.daily) for row in samples[1:])
    results = []
    for index, (sample, estimate) in enumerate(zip(samples, estimates, strict=True)):
        r_values = tuple(row.r_multiple for row in sample.trades)
        gains = sum((row.net_money for row in sample.trades if row.net_money > 0), Decimal(0))
        losses = -sum((row.net_money for row in sample.trades if row.net_money < 0), Decimal(0))
        pf = None if losses == 0 else (gains / losses).quantize(Decimal("0.000001"))
        expectation = (
            None
            if not r_values
            else (sum(r_values, Decimal(0)) / len(r_values)).quantize(Decimal("0.000001"))
        )
        dsr = deflated_sharpe(tuple(value for _, value in sample.daily), daily, trials)
        sufficient = len(r_values) >= 30
        significant = None if index == 0 else reject[index - 1]
        grade = edge_grade(r_values, estimate, pf, "REPLAY_OOS", dsr)
        if not sufficient or (index > 0 and significant is not True and grade == "WORKING"):
            grade = "UNPROVEN"
        results.append(
            OOSResult(
                variant=sample.variant,
                n=len(r_values),
                expectancy=expectation,
                confidence=estimate,
                profit_factor=pf,
                dsr=dsr,
                holm_rejects_zero=significant,
                status="SUFFICIENT" if sufficient else "INSUFFICIENT",
                grade=grade,
                sample=sample,
            )
        )
    return tuple(results)


def walkforward(
    registration: Registration,
    family_name: str,
    sessions: tuple[date, ...],
    policy: ValidationConfig,
    evaluator: Evaluator,
) -> ValidationRun:
    proof, config = (
        Registration.model_validate(registration),
        ValidationConfig.model_validate(policy),
    )
    family = proof.registry.family(family_name)
    selected_samples = []
    own: dict[str, list[Sample]] = {row.name: [] for row in family.variants}
    selections = []
    for fold in folds(sessions, proof, config):

        def evaluate(variant: Variant, start: date, end: date) -> Sample:
            if end >= proof.holdout_start:
                raise ConfigurationError("QV-02: ordinary validation refuses holdout dates")
            sample = Sample.model_validate(evaluator(variant, start, end))
            if (sample.variant, sample.start, sample.end, sample.history_sha256) != (
                variant.name,
                start,
                end,
                proof.history_sha256,
            ):
                raise DataIntegrityError("QV-03: evaluator sample identity/window differs")
            return sample

        training = tuple(
            evaluate(variant, fold.train_start, fold.train_end) for variant in family.variants
        )
        winner = select_variant(training, family, config)
        testing = tuple(
            evaluate(variant, fold.test_start, fold.test_end) for variant in family.variants
        )
        selections.append(
            FoldSelection(
                fold=fold,
                selected=winner,
                training_sha256=tuple(
                    hashlib.sha256(canonical_bytes(row)).hexdigest() for row in training
                ),
                test_sha256=tuple(
                    hashlib.sha256(canonical_bytes(row)).hexdigest() for row in testing
                ),
            )
        )
        selected_samples.append(next(row for row in testing if row.variant == winner))
        for row in testing:
            own[row.variant].append(row)
    combined = (
        _join("SELECTED", tuple(selected_samples)),
        *(_join(row.name, tuple(own[row.name])) for row in family.variants),
    )
    return ValidationRun(
        registration_sha256=proof.sha256,
        history_sha256=proof.history_sha256,
        family=family_name,
        kind="WALKFORWARD",
        selections=tuple(selections),
        results=_results(combined, dict(proof.cumulative_trials)[family_name], config),
        universe_sha256=getattr(evaluator, "universe_sha256", None),
        notices=(
            DISCLAIMER,
            PIT_NOTICE
            if getattr(evaluator, "universe_sha256", None) is not None
            else SURVIVORSHIP_NOTICE,
        ),
    )


def publish(run: ValidationRun, root: Path) -> tuple[Path, Path]:
    checked = ValidationRun.model_validate(run)
    directory = controlled_path(root / checked.registration_sha256)
    directory.mkdir(exist_ok=True)
    prefix = checked.family + "_" + checked.kind.lower()
    rows = io.StringIO(newline="")
    writer = csv.writer(rows, lineterminator="\n")
    writer.writerow(
        ("variant", "n", "expectancy_R", "ci_low", "ci_high", "dsr", "holm", "status", "grade")
    )
    for row in checked.results:
        writer.writerow(
            (
                row.variant,
                row.n,
                row.expectancy,
                None if row.confidence is None else row.confidence.lower,
                None if row.confidence is None else row.confidence.upper,
                row.dsr,
                row.holm_rejects_zero,
                row.status,
                row.grade,
            )
        )
    summary = (
        "\n".join(
            (
                *checked.notices,
                f"Family {checked.family}: {checked.kind}. Fixed registered comparisons; no parameter search.",
                f"Frozen history {checked.history_sha256}. Registration {checked.registration_sha256}.",
                *(
                    f"{row.variant}: {row.grade}, {row.n} resolved trades after costs, {row.status}."
                    for row in checked.results
                ),
            )
        )
        + "\n"
    )
    csv_path = controlled_path(directory / (prefix + ".csv"))
    summary_path = controlled_path(directory / (prefix + ".md"))
    for path, payload in (
        (csv_path, rows.getvalue().encode()),
        (summary_path, summary.encode()),
        (controlled_path(directory / (prefix + ".json")), canonical_bytes(checked)),
    ):
        if path.exists() and path.read_bytes() != payload:
            raise DataIntegrityError("QV-07: immutable validation artifact differs on rerun")
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(payload)
    return csv_path, summary_path


def final_holdout(
    ledger: Ledger,
    registration: Registration,
    family_name: str,
    policy: ValidationConfig,
    evaluator: Evaluator,
    phrase: str,
) -> ValidationRun:
    proof, config = (
        Registration.model_validate(registration),
        ValidationConfig.model_validate(policy),
    )
    family = proof.registry.family(family_name)
    ledger.verify_chain()
    if Registrations(ledger).latest() != proof:
        raise ConfigurationError("QV-01: final test needs the latest registered fixed set")
    binding = {"registration_sha256": proof.sha256, "family": family_name}
    with transaction(ledger.engine) as session:
        ledger._verify_in_session(session)
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind.in_(("VALIDATION_FINAL_STARTED", "VALIDATION_FINAL_RESULT"))
                )
                .order_by(SecurityEvent.seq)
                .limit(2001)
            )
        )
        if len(rows) > 2000 or any(row.created_at > ledger.clock.now() for row in rows):
            raise DataIntegrityError("QV-02: final-test history unavailable")
        results = [
            row
            for row in rows
            if row.kind == "VALIDATION_FINAL_RESULT"
            and all(row.detail.get(key) == value for key, value in binding.items())
        ]
        if results:
            if len(results) != 1:
                raise DataIntegrityError("QV-02: duplicate final result")
            # JSON decoding is explicit; dates are restored only inside the validated schema.
            restored = ValidationRun.recorded(results[0].detail["result"])
            if (
                restored.sha256 != results[0].detail.get("result_sha256")
                or restored.registration_sha256 != proof.sha256
                or restored.family != family_name
                or restored.kind != "HOLDOUT"
            ):
                raise DataIntegrityError("QV-02: stored final proof differs")
            return restored
        if any(row.kind == "VALIDATION_FINAL_STARTED" and row.detail == binding for row in rows):
            raise ConfigurationError(
                "QV-02: holdout was consumed but no result committed; owner audit required"
            )
        if phrase != "RUN HOLDOUT " + family_name:
            raise ConfigurationError("QV-02: exact host holdout confirmation is required")
        ledger.append_in_session(
            session, SecurityEvent, kind="VALIDATION_FINAL_STARTED", detail=binding
        )
    training = tuple(
        Sample.model_validate(evaluator(variant, proof.training_start, proof.training_end))
        for variant in family.variants
    )
    if any(
        (row.variant, row.start, row.end, row.history_sha256)
        != (variant.name, proof.training_start, proof.training_end, proof.history_sha256)
        for variant, row in zip(family.variants, training, strict=True)
    ):
        raise DataIntegrityError(
            "QV-02: final training evaluator differs from registered non-holdout history"
        )
    winner = select_variant(training, family, config)
    testing = []
    for variant in family.variants:
        sample = Sample.model_validate(evaluator(variant, proof.holdout_start, proof.holdout_end))
        if (sample.variant, sample.start, sample.end, sample.history_sha256) != (
            variant.name,
            proof.holdout_start,
            proof.holdout_end,
            proof.history_sha256,
        ):
            raise DataIntegrityError("QV-02: final evaluator differs from the frozen holdout")
        testing.append(sample)
    # Selection used only registered training, before observing any holdout.
    run = ValidationRun(
        registration_sha256=proof.sha256,
        history_sha256=proof.history_sha256,
        family=family_name,
        kind="HOLDOUT",
        selections=(),
        results=_results(
            (_join("SELECTED", (next(row for row in testing if row.variant == winner),)), *testing),
            dict(proof.cumulative_trials)[family_name],
            config,
        ),
        universe_sha256=getattr(evaluator, "universe_sha256", None),
        notices=(
            DISCLAIMER,
            PIT_NOTICE
            if getattr(evaluator, "universe_sha256", None) is not None
            else SURVIVORSHIP_NOTICE,
        ),
    )
    ledger.append(
        SecurityEvent,
        kind="VALIDATION_FINAL_RESULT",
        detail={**binding, "result": run.model_dump(mode="json"), "result_sha256": run.sha256},
    )
    return run
