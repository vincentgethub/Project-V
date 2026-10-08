"""H/EV: disclosures, cohort comparisons and report publication boundaries."""

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.historical_spread import _result
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.evaluation import weekly as module
from backend.evaluation.costs import CostContext
from backend.evaluation.outcomes import REPLAY_NOTES, Outcome
from backend.evaluation.provenance import EvaluationProvenance
from backend.evaluation.security_summary import weekly_security
from backend.evaluation.weekly import (
    SURVIVORSHIP_NOTICE,
    SYNTHETIC_NOTICE,
    ReportContext,
    WeeklyReport,
    report_csv,
    save_report,
)
from backend.tests import test_edge as edge_golden
from backend.tests import test_weekly_equity as golden
from backend.tests.test_weekly_publication import composition

calendar, history, results = golden.calendar, golden.history, golden.results
edge_outcomes = edge_golden.outcomes


@pytest.mark.parametrize("fault", ["tax_order", "estimate", "synthetic", "disclosure"])
def test_EV_report_cannot_remove_disclosures_or_forge_tax_estimates(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar, fault: str
) -> None:
    value = golden.weekly(results, history, calendar)
    changes: dict[str, Any]
    if fault == "tax_order":
        changes = {"tax_years": (*value.tax_years, value.tax_years[0])}
    elif fault == "estimate":
        first = value.tax_years[0].model_copy(update={"rough_after_tax": Decimal(1)})
        changes = {"tax_years": (first, *value.tax_years[1:])}
    elif fault == "synthetic":
        changes = {"notes": (*value.notes, SYNTHETIC_NOTICE)}
    else:
        changes = {"notes": ("profits expected", *value.notes[1:])}
    with pytest.raises(ValidationError):
        WeeklyReport.model_validate(value.model_copy(update=changes))
    with pytest.raises(ValidationError):
        ReportContext.model_validate(golden.context().model_copy(update={"synthetic": True}))


def test_EV_replay_cannot_lose_survivorship_notice(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    rows = tuple(
        row.model_copy(
            update={
                "setup": row.setup.model_copy(update={"cohort": "REPLAY_IN_SAMPLE"}),
                "notes": REPLAY_NOTES,
            }
        )
        for row in results
    )
    value = golden.weekly(rows, history, calendar, ctx=golden.context(cohort="REPLAY_IN_SAMPLE"))
    with pytest.raises(ValidationError):
        WeeklyReport.model_validate(
            value.model_copy(
                update={"notes": tuple(item for item in value.notes if item != SURVIVORSHIP_NOTICE)}
            )
        )


def test_EV_filter_comparison_csv_and_schema_bind_to_actual_cohorts(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    first = results[0]
    rows = (
        first.model_copy(
            update={"setup": first.setup.model_copy(update={"disposition": "CRO_VETO"})}
        ),
        *results[1:],
    )
    value = golden.weekly(rows, history, calendar)
    assert value.filters and b"filter" in report_csv(value)
    with pytest.raises(ValidationError):
        WeeklyReport.model_validate(
            value.model_copy(update={"filters": (*value.filters, value.filters[0])})
        )
    bad = value.filters[0].model_copy(update={"filtered_n": value.filters[0].filtered_n + 1})
    with pytest.raises(ValidationError):
        WeeklyReport.model_validate(value.model_copy(update={"filters": (bad,)}))


def test_EV_report_publication_failure_and_size_limit_are_typed(
    tmp_path: Path,
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = golden.weekly(results, history, calendar)
    with monkeypatch.context() as local:
        local.setattr(module, "canonical_bytes", lambda _: b"x" * (32 * 1024 * 1024 + 1))
        with pytest.raises(DataIntegrityError, match="file bound"):
            save_report(tmp_path, value)

    def deny(*args: object, **kwargs: object) -> object:
        raise OSError("fixture full disk")

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(DataIntegrityError, match="publication failed"):
        save_report(tmp_path, value)


def test_EV_measured_spread_proof_rehydrates_and_rejects_metric_mismatch() -> None:
    instant = datetime(2026, 9, 30, 21, tzinfo=UTC)
    measurement = _result("AAPL", instant.date(), instant, (Decimal(1),), "offline observed")
    value = EvaluationProvenance(
        cohort="PAPER",
        expires_at=instant + timedelta(days=1),
        yaml_hash="a" * 64,
        settings_hash="b" * 64,
        evidence_session=instant.date(),
        initial_equity=Decimal(100),
        cost_context=CostContext(atr14=Decimal(1), measured_half_spread_bps=Decimal(1)),
        spread_measurement=measurement,
    )
    assert EvaluationProvenance.from_recorded(value.model_dump(mode="json")) == value
    with pytest.raises(ValidationError):
        EvaluationProvenance.model_validate(
            value.model_copy(update={"cost_context": CostContext(atr14=Decimal(1))})
        )


def test_SEC_publication_refuses_future_security_evidence(
    engine: Engine,
    tmp_path: Path,
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    publisher, source, _ = composition(engine, tmp_path, calendar, history, results)
    instant = publisher.state.clock.now() + timedelta(days=1)
    summary = weekly_security(Ledger(engine, FrozenClock(instant)), Settings(), instant)
    with pytest.raises(DataIntegrityError, match="future"):
        publisher._publish(
            source.values.model_copy(update={"security": summary}), threading.Event()
        )
