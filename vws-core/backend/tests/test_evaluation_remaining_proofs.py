"""EV/SEC: unavailable outcomes, expired fee review and mismatched anchors."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import CostModelConfig, EvaluationConfig, Settings
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.fee_schedule import load_fee_schedule
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries
from backend.data.market_calendar import MarketCalendar
from backend.domain.tax_profile import TaxProfile
from backend.evaluation import fixtures as fixture_module
from backend.evaluation.costs import CostContext
from backend.evaluation.dividends import DistributionCredit
from backend.evaluation.evidence import OutcomeEvidence
from backend.evaluation.fixtures import seal_offline_fixtures
from backend.evaluation.outcomes import Outcome, _simulate
from backend.evaluation.provenance import EvaluationProvenance
from backend.evaluation.security_summary import weekly_security
from backend.evaluation.weekly import WeeklyReport, build_weekly_report, render_weekly
from backend.ops.anchors import LedgerAnchors
from backend.tests import test_edge as edge_golden
from backend.tests import test_replay as replay_golden
from backend.tests import test_weekly_equity as golden
from backend.tests.test_outcomes_history import frozen

calendar, history, results = golden.calendar, golden.history, golden.results
edge_outcomes = edge_golden.outcomes
D = Decimal
PROJECT = Path(__file__).resolve().parents[2]


def unresolved(item: Outcome) -> Outcome:
    return Outcome.model_validate(
        item.model_copy(
            update={
                "status": "OPEN",
                "reason": "HISTORY_PENDING",
                "exit_session": None,
                "exit_fill": None,
                "exit_fees": None,
                "net_money": None,
                "r_multiple": None,
            }
        )
    )


def test_EV_open_and_empty_fill_results_survive_exact_recorded_roundtrip(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    item = unresolved(results[0])
    proof = OutcomeEvidence(report=golden.weekly((item,), history, calendar), outcomes=(item,))
    assert OutcomeEvidence.from_recorded(proof.model_dump(mode="json")) == proof
    assert item.entry_fill
    unfilled = item.entry_fill.model_copy(
        update={"status": "NOT_FILLED", "qty": 0, "price": None, "reason": "NOT_TOUCHED"}
    )
    with pytest.raises(ValidationError, match="show a fill"):
        Outcome.model_validate(item.model_copy(update={"entry_fill": unfilled}))
    empty = Outcome.model_validate(
        item.model_copy(
            update={
                "status": "NOT_FILLED",
                "reason": "ALERT_UNFILLED",
                "entry_session": None,
                "entry_fill": None,
                "entry_fees": None,
                "entry_basis_ratio": None,
                "sessions_held": 0,
            }
        )
    )
    assert Outcome.from_recorded(empty.model_dump(mode="json")) == empty
    with pytest.raises(DataIntegrityError):
        EvaluationProvenance.from_recorded({})
    assert item.entry_session
    credit = DistributionCredit(session=item.entry_session, qty=1, per_share=D(1), amount=D(1))
    with pytest.raises(ValidationError, match="preceding held replay shares"):
        Outcome.model_validate(item.model_copy(update={"distributions": (credit,)}))


def test_EV_cutoff_and_halt_without_a_fill_remain_unavailable(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
) -> None:
    table = load_fee_schedule(PROJECT / "config/fees.yaml")
    seed = results[0].setup
    value = _simulate(
        seed,
        history,
        CostContext(atr14=D(1)),
        table,
        EvaluationConfig(),
        None,
        seed.decision_session,
        cancel_entry_at=seed.decision_session,
    )
    assert value.status == "NOT_FILLED" and value.reason == "ENTRY_HALTED"


def test_EV_weekly_unavailable_benchmark_overdue_fees_and_losing_cohort(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    engine: Engine,
) -> None:
    table = load_fee_schedule(PROJECT / "config/fees.yaml")
    overdue = table.model_copy(update={"review_due": table.verified_on})
    spy_bar = history.bundle.for_symbol("AAPL", "RAW").bars[-1]
    observed = frozen(
        HistoryBundle(
            series=(
                *history.bundle.series,
                *(
                    HistorySeries(symbol="SPY", adjustment=adj, bars=(spy_bar,))
                    for adj in ("ALL", "RAW", "SPLIT")
                ),
            )
        )
    )
    instant = datetime(2026, 10, 8, 22, tzinfo=UTC)
    summary = weekly_security(Ledger(engine, FrozenClock(instant)), Settings(), instant)
    report = build_weekly_report(
        golden.context(),
        (),
        observed,
        calendar,
        overdue,
        CostModelConfig(),
        TaxProfile(),
        security=summary,
    )
    assert report.spy_buy_hold_pct is None and any(
        "review overdue" in note for note in report.notes
    )
    assert WeeklyReport.from_recorded(report.model_dump(mode="json")) == report
    bad: Any = list(results)
    with pytest.raises(DataIntegrityError):
        build_weekly_report(
            golden.context(), bad, history, calendar, table, CostModelConfig(), TaxProfile()
        )
    with pytest.raises(DataIntegrityError):
        golden.weekly(
            results,
            history,
            calendar,
            ctx=golden.context(start=calendar.previous_sessions(golden.START, 1)[0]),
        )
    losing = tuple(
        results[1].model_copy(
            update={"setup": results[1].setup.model_copy(update={"alert_id": UUID(int=100 + i)})}
        )
        for i in range(30)
    )
    report = golden.weekly(losing, history, calendar, ctx=golden.context(initial_equity=D(10000)))
    assert all(card.grade == "LOSING" for card in report.cards)
    assert "too few trades" not in render_weekly(report)


@pytest.mark.parametrize("fault", ["digest", "chain"])
def test_SEC_saved_anchor_must_match_verified_prefix(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    instant = datetime(2026, 10, 8, 22, tzinfo=UTC)
    ledger = Ledger(engine, FrozenClock(instant))
    anchors = LedgerAnchors(ledger, ledger.clock)
    anchor = anchors.record()
    if fault == "digest":
        monkeypatch.setattr(
            LedgerAnchors, "create", lambda *args: anchor.model_copy(update={"digest": "f" * 64})
        )
    else:

        def corrupt() -> Any:
            raise DataIntegrityError("fixture chain verification failed")

        monkeypatch.setattr(ledger, "verify_chain", corrupt)
    with pytest.raises(DataIntegrityError):
        weekly_security(ledger, Settings(), instant - timedelta(days=1))


@pytest.mark.parametrize("failure", [OSError, DataIntegrityError])
def test_EV_fixture_os_failure_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise failure("fixture disk unavailable")

    monkeypatch.setattr(fixture_module, "seal_history", denied)
    calendar = MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))
    with pytest.raises(DataIntegrityError):
        seal_offline_fixtures(tmp_path, replay_golden.request(), calendar)
