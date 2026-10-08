"""H gate: forged report, curve and security evidence must never appear verified."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.evaluation import evidence as evidence_module
from backend.evaluation.equity import build_equity_curve
from backend.evaluation.evidence import OutcomeEvidence, recorded_publication, save_outcomes
from backend.evaluation.outcomes import Outcome
from backend.evaluation.security_summary import (
    CheckEvidence,
    CredentialAge,
    WeeklySecurity,
    weekly_security,
)
from backend.tests import test_edge as edge_golden
from backend.tests import test_weekly_equity as golden

calendar, history, results = golden.calendar, golden.history, golden.results
edge_outcomes = edge_golden.outcomes


def proof(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> OutcomeEvidence:
    return OutcomeEvidence(
        report=golden.weekly(results, history, calendar),
        outcomes=tuple(sorted(results, key=lambda row: row.setup.alert_id.hex)),
    )


@pytest.mark.parametrize("fault", ["cards", "order", "duplicate", "hash", "counts", "years"])
def test_EV_report_proof_rejects_forged_membership_counts_and_years(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar, fault: str
) -> None:
    value = proof(results, history, calendar)
    report, rows = value.report, value.outcomes
    if fault == "cards":
        report = report.model_copy(update={"cards": (), "equity_notes": (), "tax_years": ()})
    elif fault == "order":
        rows = tuple(reversed(rows))
    elif fault == "duplicate":
        rows = (rows[0], *rows)
    elif fault == "hash":
        rows = (rows[0].model_copy(update={"manifest_sha256": "b" * 64}), *rows[1:])
    elif fault == "counts":
        first = report.cards[0]
        with localcontext() as precision:
            precision.prec = 80
            altered = first.model_copy(
                update={
                    "alerts": first.alerts + 1,
                    "fill_rate": Decimal(first.filled) / (first.alerts + 1),
                }
            )
        report = report.model_copy(update={"cards": (altered, *report.cards[1:])})
    else:
        report = report.model_copy(update={"tax_years": ()})
    with pytest.raises(ValidationError):
        OutcomeEvidence(report=report, outcomes=rows)


@pytest.mark.parametrize(
    "fault", ["report_sha256", "manifest_sha256", "outcomes_sha256", "outcomes_filename"]
)
def test_EV_saved_publication_rejects_each_broken_proof_binding(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar, fault: str
) -> None:
    value = proof(results, history, calendar)
    payload = {
        "report": value.report.model_dump(mode="json"),
        "outcome_evidence": value.model_dump(mode="json"),
        "report_sha256": value.report.sha256,
        "manifest_sha256": value.report.manifest_sha256,
        "outcomes_sha256": value.sha256,
        "outcomes_filename": f"outcomes_{value.sha256}.json",
    }
    assert recorded_publication(payload) == value.report
    payload[fault] = "incorrect"
    with pytest.raises(DataIntegrityError):
        recorded_publication(payload)


def test_EV_canonical_outcome_proof_is_write_once_and_bounded(
    tmp_path: Path,
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = proof(results, history, calendar)
    path = save_outcomes(tmp_path, value)
    assert save_outcomes(tmp_path, value) == path
    path.write_bytes(b"altered proof")
    with pytest.raises(DataIntegrityError):
        save_outcomes(tmp_path, value)
    monkeypatch.setattr(evidence_module, "canonical_bytes", lambda _: b"x" * (32 * 1024 * 1024 + 1))
    with pytest.raises(DataIntegrityError):
        save_outcomes(tmp_path, value)
    with pytest.raises(DataIntegrityError):
        OutcomeEvidence.from_recorded({})


@pytest.mark.parametrize("fault", ["list", "duplicate", "cohort", "outside_window", "marks"])
def test_EV_equity_rejects_unbound_or_incomplete_curve_inputs(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar, fault: str
) -> None:
    rows: Any = results
    start, end = golden.START, golden.END
    if fault == "list":
        rows = list(rows)
    elif fault == "duplicate":
        rows = (rows[0], *rows)
    elif fault == "cohort":
        first = rows[0]
        rows = (
            first.model_copy(update={"setup": first.setup.model_copy(update={"cohort": "LIVE"})}),
            *rows[1:],
        )
    elif fault == "outside_window":
        end = calendar.previous_sessions(end, 1)[0]
    else:
        start = calendar.previous_sessions(start, 1)[0]
    with pytest.raises(DataIntegrityError):
        build_equity_curve(
            edge_golden.KEY,
            rows,
            history,
            calendar,
            initial_equity=Decimal(100),
            start=start,
            end=end,
        )


@pytest.mark.parametrize("fault", ["ids", "checks", "future", "age"])
def test_SEC_weekly_security_never_verifies_inconsistent_dates_or_ages(
    engine: Engine, fault: str
) -> None:
    instant = datetime(2026, 10, 8, 21, tzinfo=UTC)
    value = weekly_security(Ledger(engine, FrozenClock(instant)), Settings(), instant)
    changes: dict[str, Any]
    if fault == "ids":
        changes = {"new_ids": (123, 123)}
    elif fault == "checks":
        changes = {"checks": tuple(reversed(value.checks))}
    else:
        rotated = instant + timedelta(days=1) if fault == "future" else instant
        age = CredentialAge(name="TEST_KEY", last_rotated=rotated, age_days=1, status="PASS")
        changes = {"credentials": (age,)}
    with pytest.raises(ValidationError):
        WeeklySecurity.model_validate(value.model_copy(update=changes))


def test_SEC_unknown_secret_age_and_unverified_check_cannot_claim_pass() -> None:
    with pytest.raises(ValidationError):
        CredentialAge(name="TEST_KEY", last_rotated=None, age_days=None, status="PASS")
    with pytest.raises(ValidationError):
        CheckEvidence(check="drill", at=None, status="PASS")
