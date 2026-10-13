"""RT-12/ER-04: real ledger bindings, counterfactuals and receipt refusals."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.data.fee_schedule import load_fee_schedule
from backend.evaluation.filter_shadows import FilterShadow
from backend.evaluation.ledger_inputs import collect_outcome_setups
from backend.learning.service import LearningService
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import ContextTag, RealtimeContext
from backend.realtime.storage import RealtimeStore
from backend.tests.query_faults import selects_kind
from backend.tests.test_ledger_evaluation import scope
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from backend.tests.test_v_filter_shadows import (
    test_ER_04_zero_RS_filter_does_not_make_a_ticket_or_call_the_LLM as seed_filtered,
)

harness = make_research_harness


def context(h: Harness, multiplier: Decimal = Decimal(1)) -> RealtimeContext:
    return RealtimeContext(
        scope=ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER"),
        symbol="NVDA",
        as_of=h.clock.now(),
        policy_sha256=h.config.config_hash,
        tags=(ContextTag.FOMC,),
        entry_multiplier=multiplier,
        warnings=(),
        blocked=multiplier == 0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "scope", "future_receipt", "cap", "past_context"])
async def test_RT_proposal_context_is_bound_and_never_uses_unverified_receipts(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    h = harness
    alert = await deliver(h)
    value = context(h)
    store = RealtimeStore(h.state.ledger, value.scope, h.config.config_hash)
    store.record_context(alert.proposal_id, value.model_dump(mode="python"))
    scalars = Session.scalars

    def projected(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        rows = scalars(session, statement, *args, **kwargs)
        if not selects_kind(statement, "REALTIME_CONTEXT"):
            return rows
        actual = list(rows)
        if not actual:
            return actual
        row = SimpleNamespace(**vars(actual[0]))
        payload = dict(row.detail)
        public = dict(payload["context"])
        if fault == "scope":
            public["scope"] = {"account_id": "different-paper", "environment": "PAPER"}
        elif fault == "future_receipt":
            row.ts = h.clock.now() + timedelta(seconds=1)
        elif fault == "past_context":
            public["as_of"] = (h.request.candidate.as_of - timedelta(seconds=1)).isoformat()
        payload["context"] = public
        row.detail = payload
        return [row] * 1001 if fault == "cap" else [row]

    monkeypatch.setattr(Session, "scalars", projected)
    monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda *args: {})
    if fault in {"scope", "future_receipt", "cap"}:
        with pytest.raises(DataIntegrityError):
            collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)
    else:
        rows = collect_outcome_setups(
            h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar
        )
        assert rows and all(
            row.context_tags == (() if fault == "past_context" else ("fomc_day",)) for row in rows
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "cap", "future_context", "other_multiplier"])
async def test_RT_zero_filter_context_and_owner_regret_are_scoped(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    h = harness
    with monkeypatch.context() as seeding:
        await seed_filtered(h, seeding)
    value = context(h)
    store = RealtimeStore(h.state.ledger, value.scope, h.config.config_hash)
    store.record_size_context(value.model_dump(mode="python"))
    store.record_size_context(value.model_dump(mode="python"))
    with Session(h.state.engine) as session:
        stored = session.scalar(select(SecurityEvent).where(SecurityEvent.kind == "FILTER_SHADOW"))
        assert stored is not None
        shadow = FilterShadow.recorded(stored.detail)
    service = LearningService(
        h.state.ledger,
        value.scope,
        h.config,
        h.swarm.risk.cro.calendar,
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
        Path(__file__).resolve().parents[2],
    )
    assert "REGRETTED" in service.regret(shadow.identity)
    assert service.journal.rows()[0].trigger == "REGRETTED"
    scalars = Session.scalars

    def projected(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        rows = scalars(session, statement, *args, **kwargs)
        if not selects_kind(statement, "REALTIME_SIZE_CONTEXT"):
            return rows
        actual = list(rows)
        if not actual:
            return actual
        row = SimpleNamespace(**vars(actual[0]))
        payload = dict(row.detail)
        public = dict(payload["context"])
        if fault == "future_context":
            public["as_of"] = (h.clock.now() + timedelta(seconds=1)).isoformat()
        elif fault == "other_multiplier":
            public["entry_multiplier"] = "0.5"
        payload["context"] = public
        row.detail = payload
        return [row] * 1001 if fault == "cap" else [row]

    monkeypatch.setattr(Session, "scalars", projected)
    monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda *args: {})
    if fault in {"cap", "future_context"}:
        with pytest.raises(DataIntegrityError):
            collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)
    else:
        rows = collect_outcome_setups(
            h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar
        )
        assert rows and all(row.context_tags == (() if fault else ("fomc_day",)) for row in rows)
