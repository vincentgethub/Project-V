"""AX-50/EV-01: automatic decisions retain their exact hypothetical tracker scope."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.core.database import ExecutionOrderRecord
from backend.core.errors import DataIntegrityError
from backend.evaluation.ledger_inputs import collect_outcome_setups
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor
from backend.tests.test_ledger_evaluation import scope
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("projection", ["recorded", "reduced"])
async def test_AX_50_auto_approval_is_tracked_with_submitted_quantity(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, projection: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    h.state.ledger.verify_chain()
    if projection == "reduced":
        # Isolate reconstruction of a smaller approved intent. No stored rows
        # change, and this test never enables or simulates a live connection.
        monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
        monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda _: None)
        original = Session.scalars

        def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
            rows = original(session, statement, *args, **kwargs)
            if statement.column_descriptions[0]["entity"] is not ExecutionOrderRecord:
                return rows
            result = []
            for row in rows:
                cloned = SimpleNamespace(**row.__dict__)
                cloned.qty = 1
                result.append(cloned)
            return result

        monkeypatch.setattr(Session, "scalars", scalars)
    rows = collect_outcome_setups(h.state.ledger, h.settings, scope(h), built.calendar)
    primary = next(row for row in rows if row.disposition == "APPROVED")
    assert len(rows) == 2 and len({row.alert_id for row in rows}) == 2
    assert next(row for row in rows if row.disposition == "CRO_VETO").qty > primary.qty
    assert primary.qty == (1 if projection == "reduced" else h.request.candidate.qty)
    assert len(client.posts) == 1
    assert primary.limit == h.request.candidate.entry_price


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    ["account", "cohort", "config", "future", "qty", "bool", "levels", "inventory", "aggregate"],
)
async def test_EV_01_auto_tracker_refuses_unbound_intent_projection(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    h = harness
    alert = await deliver(h)
    built = executor(h, FakeTradingClient(h))
    await built.enter(alert.proposal_id)
    h.state.ledger.verify_chain()
    # The independently tested immutable verifier remains covered elsewhere;
    # detached results isolate the additional query-boundary checks here.
    monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
    monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda _: None)
    original = Session.scalars
    if fault == "aggregate":
        from backend.execution import storage

        monkeypatch.setattr(storage, "entry_quantity", lambda *a: None)

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        rows = original(session, statement, *args, **kwargs)
        if statement.column_descriptions[0]["entity"] is not ExecutionOrderRecord:
            return rows
        projected = [alter(row) for row in rows]
        return projected * 3 if fault == "inventory" else projected

    def alter(row: Any) -> Any:
        cloned = SimpleNamespace(**row.__dict__)
        if fault == "account":
            cloned.account_id = "other-paper-account"
        elif fault == "cohort":
            cloned.environment = "LIVE"
        elif fault == "config":
            cloned.config_hash = "0" * 64
        elif fault == "future":
            cloned.created_at = h.clock.now() + timedelta(seconds=1)
        elif fault == "qty":
            cloned.qty = h.request.candidate.qty + 1
        elif fault == "bool":
            cloned.qty = True
        elif fault == "levels":
            cloned.stop_price += Decimal("0.01")
        return cloned

    monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises(DataIntegrityError, match="tracker"):
        collect_outcome_setups(h.state.ledger, h.settings, scope(h), built.calendar)
