"""XA/ER: cost tables cannot cross accounts or change during publication."""

import threading
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import Playbook
from backend.evaluation import publication, tca_store
from backend.evaluation.calibrated_costs import CostCalibration
from backend.evaluation.fill_quality import DriftCheck, QualityBucket, monthly
from backend.evaluation.outcomes import Outcome
from backend.evaluation.publication import WeeklyInputs, WeeklyPublisher
from backend.evaluation.weekly import WeeklyReport, render_weekly, report_csv
from backend.ops.trading_controls import ControlScope
from backend.tests import test_weekly_publication as golden
from backend.tests.test_v_verdict_quality import quality

calendar, history, results = golden.calendar, golden.history, golden.results
edge_outcomes = golden.edge_outcomes
D = Decimal


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "decode",
        "drift_account",
        "drift_live",
        "drift_duplicate",
        "cost_account",
        "cost_live",
        "quality_account",
        "quality_live",
    ],
)
def test_XA_weekly_tables_are_scoped_and_visible(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    case: str,
) -> None:
    publisher, source, _ = golden.composition(engine, tmp_path, calendar, history, results)
    report = publisher._publish(source.values, threading.Event())
    scope = ControlScope(account_id="paper-test", environment="PAPER")
    other = ControlScope(account_id="other", environment="PAPER")
    live = ControlScope(account_id="paper-test", environment="LIVE")
    quality = monthly(
        other if case == "quality_account" else live if case == "quality_live" else scope,
        "2026-10",
        "HIGH",
        (),
        D(2),
    )
    calibration = CostCalibration(
        scope=other if case == "cost_account" else live if case == "cost_live" else scope,
        source_ids=(UUID(int=1),),
        high=D(2),
        observed_at=publisher.state.clock.now(),
    )
    drift = DriftCheck(
        scope=other if case == "drift_account" else scope,
        playbook=Playbook.TREND_50EMA,
        paper=(),
        oos=(),
        seed=1,
    )
    context = (
        report.context.model_copy(update={"cohort": "LIVE"})
        if case == "drift_live"
        else report.context
    )
    values = {
        **report.model_dump(),
        "context": context,
        "fill_quality": (quality,),
        "calibration": calibration,
        "drift": (drift, drift) if case == "drift_duplicate" else (drift,),
    }
    if case == "decode":
        payload = report.model_dump(mode="json")
        payload["calibration"] = {"scope": "corrupt"}
        with pytest.raises(DataIntegrityError, match="unverifiable"):
            WeeklyReport.from_recorded(payload)
    elif case == "valid":
        changed = WeeklyReport.model_validate(values)
        assert WeeklyReport.from_recorded(changed.model_dump(mode="json")) == changed
        text, csv = render_weekly(changed), report_csv(changed).decode()
        assert "Fill quality 2026-10 HIGH" in text and calibration.sha256 in text
        assert "fill_quality" in csv and "UNVERIFIED" in text
    else:
        with pytest.raises(ValidationError, match="XA"):
            WeeklyReport.model_validate(values)


@pytest.mark.parametrize("changed", [False, True])
def test_XA_publication_records_monthly_quality_and_refuses_midrun_cost_change(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    monkeypatch: pytest.MonkeyPatch,
    changed: bool,
) -> None:
    publisher, source, _ = golden.composition(engine, tmp_path, calendar, history, results)
    scope = ControlScope(account_id="paper-test", environment="PAPER")
    table = (monthly(scope, "2026-10", "HIGH", (), D(2)),)

    def quality() -> tuple[QualityBucket, ...]:
        if changed:
            calibration = CostCalibration(
                scope=scope,
                source_ids=(UUID(int=1),),
                high=D(2),
                observed_at=publisher.state.clock.now(),
            )
            monkeypatch.setattr(publication, "cost_snapshot", lambda *a, **k: calibration)
        return table

    monkeypatch.setattr(publisher, "_quality_table", quality)
    if changed:
        with pytest.raises(DataIntegrityError, match="costs changed"):
            publisher._publish(source.values, threading.Event())
        assert not tuple(tmp_path.glob("*.json"))
    else:
        report = publisher._publish(source.values, threading.Event())
        assert report.fill_quality == table
        publisher.state.ledger.verify_chain()


def test_XA_publisher_builds_all_three_buckets_for_observed_months(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, _, _ = golden.composition(engine, tmp_path, calendar, history, results)
    row = quality(
        FrozenClock(publisher.state.clock.now()),
        1,
        scope=ControlScope(account_id="paper-test", environment="PAPER"),
    )
    monkeypatch.setattr(tca_store, "inventory", lambda *a: (row,))
    table = publisher._quality_table()
    assert tuple(item.bucket for item in table) == ("HIGH", "MID", "LOW")
    assert all(item.month == "2026-10" and item.scope == row.scope for item in table)
    publisher.state.ledger.verify_chain()


def test_XA_live_report_never_includes_paper_drift(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
) -> None:
    original, source, notices = golden.composition(engine, tmp_path, calendar, history, results)
    inputs = WeeklyInputs.model_validate(
        source.values.model_copy(
            update={
                "context": source.values.context.model_copy(update={"cohort": "LIVE"}),
                "outcomes": tuple(
                    Outcome.model_validate(
                        row.model_copy(
                            update={"setup": row.setup.model_copy(update={"cohort": "LIVE"})}
                        )
                    )
                    for row in source.values.outcomes
                ),
            }
        )
    )
    publisher = WeeklyPublisher(
        original.state,
        Settings(
            paper_trading=False,
            live_trading_enabled=True,
            live_trading_confirm="I_ACCEPT_REAL_MONEY_RISK",
            broker_api_key=SecretStr("TEST_ONLY"),
            broker_secret_key=SecretStr("TEST_ONLY_SECRET"),
        ),
        original.config,
        original.account_id,
        calendar,
        tmp_path,
        source,
        notices.notify,
    )
    result = publisher._publish(inputs, threading.Event())
    assert result.context.cohort == "LIVE" and result.drift == ()
    publisher.state.ledger.verify_chain()
