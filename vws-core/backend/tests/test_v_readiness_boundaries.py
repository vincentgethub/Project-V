"""GV: query inventories, exact account PnL and publication fault boundaries."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.verdict import ReadinessVerdict, evaluate, latest_ready, record
from backend.evaluation.verdict_source import VerdictPublisher, update_progress
from backend.ops.trading_controls import ControlScope
from backend.pnl.storage import record_day
from backend.tests.query_faults import selects_kind
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_funding_and_pnl import day
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from backend.tests.test_v_verdict_quality import inputs
from backend.tests.test_v_verdict_source import SCOPE, close_split_trade, evidence

harness = make_research_harness
D = Decimal


@pytest.mark.parametrize("case", ["bound", "future"])
def test_GV_incident_query_boundaries_checked_independently(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    harness.state.ledger.verify_chain()
    monkeypatch.setattr(harness.state.ledger, "verify_chain", lambda: {})
    original = Session.scalars

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        entity = statement.column_descriptions[0]["entity"]
        if entity is SecurityEvent and statement.whereclause is None:
            event = SimpleNamespace(
                created_at=harness.clock.now() + timedelta(seconds=int(case == "future"))
            )
            return [event] * (100001 if case == "bound" else 1)
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises(DataIntegrityError, match="incident inventory"):
        evidence(harness)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_GV_actual_account_PnL_and_healthy_session_window_are_used(harness: Harness) -> None:
    h = harness
    await close_split_trade(h)
    calendar = MarketCalendar()
    tail = date(2026, 11, 10)
    h.clock.current = calendar.session_close(tail) + timedelta(minutes=31)
    sessions = (*calendar.previous_sessions(tail, 19), tail)
    equity = D(10000)
    for i, session in enumerate(sessions):
        following = equity + (D(10) if i % 2 == 0 else D(-5))
        record_day(
            h.state.ledger,
            day(
                FrozenClock(h.clock.now()),
                session,
                str(equity),
                str(following),
                owner=SCOPE.account_id,
            ),
        )
        equity = following
    h.state.ledger.append(
        SecurityEvent,
        kind="AUTO_RECONCILED",
        detail={"account_id": SCOPE.account_id, "environment": "PAPER"},
    )
    row = evidence(h)
    assert row.source == "AUTO_PAPER" and len(row.r_multiples) == 1
    assert row.sessions == sessions and row.drawdown is not None and row.sharpe is not None
    assert row.recent_fault_free_sessions == 20 and row.unresolved_reconciliation is False
    assert row.circuit_breaker_halts_this_month == 0
    assert row.spy_total_return_sharpe is None and evaluate(row, h.config.gv).status == "NOT_YET"


@pytest.mark.parametrize("case", ["hash", "ready", "stop"])
def test_GV_serialized_verdict_cannot_invent_a_status(harness: Harness, case: str) -> None:
    verdict = evaluate(inputs(FrozenClock(harness.clock.now())), harness.config.gv)
    changed = (
        {"inputs_sha256": "f" * 64}
        if case == "hash"
        else {"status": "NOT_YET"}
        if case == "ready"
        else {"status": "STOP", "unmet": ("unmet",)}
    )
    with pytest.raises(ValidationError):
        ReadinessVerdict.model_validate(verdict.model_copy(update=changed))


@pytest.mark.parametrize("value", [True, 0, 36])
def test_GV_ready_age_cannot_be_weakened_or_coerced(harness: Harness, value: Any) -> None:
    with pytest.raises(DataIntegrityError, match="stricter"):
        latest_ready(harness.state.ledger, SCOPE.account_id, "b" * 64, value)


def test_GV_future_verdict_cannot_be_recorded(harness: Harness) -> None:
    value = inputs(
        FrozenClock(harness.clock.now()), as_of=harness.clock.now() + timedelta(seconds=1)
    )
    with pytest.raises(DataIntegrityError, match="future verdict"):
        record(harness.state.ledger, value, harness.config.gv)


@pytest.mark.parametrize("case", ["bound", "future", "changed_result"])
def test_GV_stored_READY_query_has_independent_fault_controls(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    ledger = harness.state.ledger
    verdict = record(ledger, inputs(FrozenClock(harness.clock.now())), harness.config.gv)
    original = Session.scalars

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(session, statement, *args, **kwargs)
        if not selects_kind(statement, "VERDICT"):
            return result
        rows = [SimpleNamespace(**vars(event)) for event in result]
        if case == "bound":
            return rows * 1001
        if case == "future":
            rows[0].created_at = ledger.clock.now() + timedelta(seconds=1)
        else:
            forged = ReadinessVerdict.model_validate(
                verdict.model_copy(update={"status": "NOT_YET", "unmet": ("invented",)})
            )
            rows[0].detail = forged.model_dump(mode="json")
        return rows

    monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises(DataIntegrityError):
        latest_ready(ledger, SCOPE.account_id, "b" * 64)


@pytest.mark.parametrize("case", ["oversize", "misplaced", "drift"])
def test_GV_progress_edit_stays_bounded_and_in_its_one_sentence(
    harness: Harness, tmp_path: Path, case: str
) -> None:
    (tmp_path / "docs").mkdir()
    path = tmp_path / "docs/PROGRESS.md"
    content = "## Where things stand\nReadiness verdict: UNVERIFIED\n## What works now\n"
    if case == "oversize":
        content += "line\n" * 60
    elif case == "misplaced":
        content = "Readiness verdict: UNVERIFIED\n## Where things stand\n## What works now\n"
    path.write_text(content, encoding="utf-8")
    verdict = evaluate(
        inputs(FrozenClock(harness.clock.now()), edge_drift=case == "drift"), harness.config.gv
    )
    if case == "drift":
        update_progress(tmp_path, verdict)
        assert "EDGE DRIFT" in path.read_text(encoding="utf-8")
    else:
        with pytest.raises(DataIntegrityError):
            update_progress(tmp_path, verdict)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["scope", "bound", "other_account", "ordinary", "weekend", "same_account"]
)
async def test_GV_publication_scope_and_monthly_history_boundaries(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    h = harness
    calendar = MarketCalendar()
    h.clock.current = calendar.session_close(
        date(2026, 11, 2) if case == "weekend" else date(2026, 10, 1)
    ) + timedelta(minutes=31)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/PROGRESS.md").write_text(
        "## Where things stand\nReadiness verdict: UNVERIFIED\n## What works now\n",
        encoding="utf-8",
    )
    sent: list[str] = []

    async def notify(text: str, urgent: bool) -> None:
        sent.append(text)

    row = evidence(h)
    other = ControlScope(account_id="another-paper", environment="PAPER")
    if case == "scope":
        row = type(row).model_validate(row.model_copy(update={"scope": other}))
    else:
        record(
            h.state.ledger,
            type(row).model_validate(
                row.model_copy(update={"scope": SCOPE if case == "same_account" else other})
            ),
            h.config.gv,
        )
        if case == "bound":
            original = Session.scalars

            def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
                found = original(session, statement, *args, **kwargs)
                return list(found) * 1001 if selects_kind(statement, "VERDICT") else found

            monkeypatch.setattr(Session, "scalars", scalars)
    publisher = VerdictPublisher(
        h.state.ledger, h.config, SCOPE, calendar, tmp_path, lambda: row, notify
    )
    if case in {"other_account", "weekend"}:
        assert await publisher.publish(monthly=True) is not None
        assert len(sent) == 1
    elif case == "ordinary":
        assert await publisher.publish() is not None
        assert sent == []
    elif case == "same_account":
        assert await publisher.publish(monthly=True) is None
        assert sent == []
    else:
        with pytest.raises(DataIntegrityError):
            await publisher.publish(monthly=case == "bound")
