"""EV-01: inconsistent query projections cannot become tracked outcomes.

The separately tested hash verifier is stubbed after making a real valid
research row, to isolate projection validation from immutable-chain validation.
No stored row is modified; each injected query result is a detached namespace.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.core.database import Alert, AlertEvent, Order, ResearchReport, RiskDecision, Signal
from backend.core.errors import DataIntegrityError
from backend.data.historical_spread import _result
from backend.evaluation.ledger_inputs import collect_tracked_setups
from backend.tests import test_ledger_evaluation as golden
from backend.tests.test_swarm_and_callbacks import Harness, deliver
from backend.tests.test_swarm_and_callbacks import make_research_harness as make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "future_signal",
        "future_candidate",
        "future_cost",
        "future_quote",
        "alert_binding",
        "lifecycle",
        "future_lifecycle",
        "issuer",
        "validity",
        "veto_binding",
        "proposal_bound",
    ],
)
async def test_EV_projection_mismatches_remain_typed_failures(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    h = harness
    await deliver(h)
    h.state.ledger.verify_chain()
    monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
    monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda _: None)
    original_get, original_scalar, original_scalars = Session.get, Session.scalar, Session.scalars
    expiry = h.clock.now() + timedelta(days=5)
    while expiry.weekday() != 6:
        expiry += timedelta(days=1)

    def get(session: Session, model: Any, identity: Any, *args: Any, **kwargs: Any) -> Any:
        row = original_get(session, model, identity, *args, **kwargs)
        if model is not Signal or row is None:
            return row
        cloned = SimpleNamespace(**row.__dict__)
        data = {
            **row.structured_thesis,
            "setup": dict(row.structured_thesis["setup"]),
            "evaluation_provenance": dict(row.structured_thesis["evaluation_provenance"]),
        }
        cloned.structured_thesis = data
        provenance = data["evaluation_provenance"]
        if fault == "future_signal":
            cloned.created_at = h.clock.now() + timedelta(seconds=1)
        elif fault == "future_candidate":
            cloned.created_at = h.clock.now() - timedelta(seconds=1)
        elif fault == "future_cost":
            provenance["evidence_session"] = golden.scope(h).end.isoformat()
        elif fault == "future_quote":
            from datetime import date

            measurement = _result(
                row.symbol,
                date.fromisoformat(provenance["evidence_session"]),
                h.clock.now() + timedelta(seconds=1),
                (Decimal(1),),
                "offline future quote",
            )
            provenance["spread_measurement"] = measurement.model_dump(mode="json")
            provenance["cost_context"] = {
                **provenance["cost_context"],
                "measured_half_spread_bps": "1",
            }
        elif fault == "validity":
            provenance["expires_at"] = expiry.isoformat()
        return cloned

    def scalar(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        row = original_scalar(session, statement, *args, **kwargs)
        entity = statement.column_descriptions[0]["entity"]
        if entity is Alert:
            if fault == "veto_binding":
                return None
            cloned = SimpleNamespace(**row.__dict__)
            if fault == "alert_binding":
                cloned.expires_at += timedelta(seconds=1)
            elif fault == "validity":
                cloned.expires_at = expiry
            return cloned
        if entity is AlertEvent:
            if fault == "lifecycle":
                return None
            cloned = SimpleNamespace(**row.__dict__)
            if fault == "future_lifecycle":
                cloned.created_at = h.clock.now() + timedelta(seconds=1)
            return cloned
        if entity is ResearchReport and fault == "issuer":
            return SimpleNamespace(payload={**row.payload, "symbol": "AAPL"})
        if entity is RiskDecision and fault == "veto_binding":
            return SimpleNamespace(evaluated_at=h.clock.now(), config_hash="unbound")
        return row

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        rows = original_scalars(session, statement, *args, **kwargs)
        if fault == "proposal_bound" and statement.column_descriptions[0]["entity"] is Order:
            first = next(iter(rows))
            return (first,) * 100001
        return rows

    monkeypatch.setattr(Session, "get", get)
    monkeypatch.setattr(Session, "scalar", scalar)
    monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises(DataIntegrityError):
        collect_tracked_setups(
            h.state.ledger, h.settings, golden.scope(h), h.swarm.risk.cro.calendar
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing_signal", "other_agent", "missing_fact", "no_veto"])
async def test_EV_absent_evidence_never_creates_a_cro_veto_or_framework_pass(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    h = harness
    await deliver(h)
    h.state.ledger.verify_chain()
    monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
    monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda _: None)
    original_get, original_scalar = Session.get, Session.scalar

    def get(session: Session, model: Any, identity: Any, *args: Any, **kwargs: Any) -> Any:
        row = original_get(session, model, identity, *args, **kwargs)
        if model is Signal and fault == "missing_signal":
            return None
        if model is Signal and fault == "other_agent":
            return SimpleNamespace(agent_name="Manual")
        return row

    def scalar(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        entity = statement.column_descriptions[0]["entity"]
        if (entity is ResearchReport and fault == "missing_fact") or (
            entity in {Alert, RiskDecision} and fault == "no_veto"
        ):
            return None
        return original_scalar(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "get", get)
    monkeypatch.setattr(Session, "scalar", scalar)
    rows = collect_tracked_setups(
        h.state.ledger, h.settings, golden.scope(h), h.swarm.risk.cro.calendar
    )
    if fault == "missing_fact":
        assert len(rows) == 2 and all(
            row.setup.fundamentals_status.value == "INCOMPLETE" for row in rows
        )
        assert {row.setup.disposition for row in rows} == {"PENDING", "CRO_VETO"}
    else:
        assert rows == ()
