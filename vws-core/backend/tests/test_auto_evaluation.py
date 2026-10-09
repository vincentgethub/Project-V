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
        original = Session.scalar

        def scalar(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
            row = original(session, statement, *args, **kwargs)
            if (
                statement.column_descriptions[0]["entity"] is ExecutionOrderRecord
                and row is not None
            ):
                cloned = SimpleNamespace(**row.__dict__)
                cloned.qty = 1
                return cloned
            return row

        monkeypatch.setattr(Session, "scalar", scalar)
    rows = collect_outcome_setups(h.state.ledger, h.settings, scope(h), built.calendar)
    assert len(rows) == 1 and rows[0].disposition == "APPROVED"
    assert rows[0].qty == (1 if projection == "reduced" else h.request.candidate.qty)
    assert len(client.posts) == 1
    assert rows[0].limit == h.request.candidate.entry_price


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault", ["account", "cohort", "config", "future", "qty", "bool", "levels"]
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
    original = Session.scalar

    def scalar(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        row = original(session, statement, *args, **kwargs)
        if statement.column_descriptions[0]["entity"] is not ExecutionOrderRecord or row is None:
            return row
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

    monkeypatch.setattr(Session, "scalar", scalar)
    with pytest.raises(DataIntegrityError, match="tracker"):
        collect_outcome_setups(h.state.ledger, h.settings, scope(h), built.calendar)
