"""EV-01/02: preserve each alert's result alongside its aggregate report."""

from __future__ import annotations

import hashlib
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Self

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.data.history import canonical_bytes
from backend.domain.models import FrozenModel
from backend.evaluation.equity import _selected
from backend.evaluation.outcomes import Outcome
from backend.evaluation.weekly import WeeklyReport
from backend.ops.anchors import controlled_path


class OutcomeEvidence(FrozenModel):
    report: WeeklyReport
    outcomes: tuple[Outcome, ...] = Field(max_length=100000)

    @model_validator(mode="after")
    def bound(self) -> Self:
        identities = tuple(item.setup.alert_id.hex for item in self.outcomes)
        context = self.report.context
        expected_keys = {
            (
                item.setup.playbook,
                item.setup.variant,
                item.setup.cohort,
                item.setup.disposition,
                status,
            )
            for item in self.outcomes
            for status in (None, item.setup.fundamentals_status)
        }
        actual_keys = {
            (
                card.key.playbook,
                card.key.variant,
                card.key.cohort,
                card.key.disposition,
                card.key.fundamentals_status,
            )
            for card in self.report.cards
        }
        if actual_keys != expected_keys:
            raise ValueError("EV-02: report cards do not cover exactly the recorded outcomes")
        if identities != tuple(sorted(set(identities))) or any(
            item.setup.cohort != context.cohort
            or item.manifest_sha256 != self.report.manifest_sha256
            or item.fee_schedule_sha256 != self.report.fee_schedule_sha256
            or item.cost_policy_sha256 != self.report.cost_policy_sha256
            or not context.start <= item.setup.decision_session <= context.end
            or (item.exit_session is not None and item.exit_session > context.end)
            for item in self.outcomes
        ):
            raise ValueError("EV-01: outcome proof differs from report identity/hash/window")
        for card in self.report.cards:
            rows = tuple(item for item in self.outcomes if _selected(card.key, item))
            if (card.alerts, card.filled, card.n) != (
                len(rows),
                sum(item.entry_session is not None for item in rows),
                sum(item.status == "RESOLVED" for item in rows),
            ):
                raise ValueError("EV-02: report counts differ from its per-alert evidence")
            with localcontext() as precision:
                precision.prec = 256
                years: dict[int, Decimal] = {}
                for item in rows:
                    if item.exit_session is not None and item.net_money is not None:
                        year = item.exit_session.year
                        years[year] = years.get(year, Decimal(0)) + item.net_money
                recorded = {
                    item.year: item.net_gains
                    for item in self.report.tax_years
                    if item.key == card.key
                }
                if recorded != years:
                    raise ValueError("CM-05: yearly net differs from per-alert evidence")
        return self

    @classmethod
    def from_recorded(cls, payload: dict[str, Any]) -> OutcomeEvidence:
        try:
            return cls.model_validate(
                {
                    **payload,
                    "report": WeeklyReport.from_recorded(payload["report"]),
                    "outcomes": tuple(Outcome.from_recorded(item) for item in payload["outcomes"]),
                }
            )
        except Exception:
            raise DataIntegrityError("EV-01: recorded outcome evidence is unverifiable") from None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def recorded_publication(payload: dict[str, Any]) -> WeeklyReport:
    try:
        report = WeeklyReport.from_recorded(payload["report"])
        evidence = OutcomeEvidence.from_recorded(payload["outcome_evidence"])
        if (
            evidence.report != report
            or report.sha256 != payload["report_sha256"]
            or report.manifest_sha256 != payload["manifest_sha256"]
            or evidence.sha256 != payload["outcomes_sha256"]
            or payload["outcomes_filename"] != f"outcomes_{evidence.sha256}.json"
        ):
            raise ValueError("report or outcome proof differs")
        return report
    except Exception:
        raise DataIntegrityError("EV-02: stored publication proof is unverifiable") from None


def save_outcomes(root: Path, evidence: OutcomeEvidence) -> Path:
    try:
        bound = OutcomeEvidence.model_validate(evidence)
        payload = canonical_bytes(bound)
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError("outcome evidence exceeds its file bound")
        target = controlled_path(root / f"outcomes_{bound.sha256}.json")
        if target.exists():
            with target.open("rb") as stream:
                if stream.read(len(payload) + 1) != payload:
                    raise ValueError("existing outcome proof differs")
        else:
            with target.open("xb") as stream:
                stream.write(payload)
        return target
    except Exception:
        raise DataIntegrityError("EV-01: per-alert outcome publication failed") from None
