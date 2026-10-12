"""ER-04: rejected zero-size overlays remain costed, distinct and idempotent."""

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.agents.expiry import proposal_expiry
from backend.agents.indicators import atr
from backend.core.database import DataSnapshot, Signal
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.data_layer import AsyncAlpacaMarketData
from backend.domain.models import SizeEvidence
from backend.evaluation import ledger_inputs
from backend.evaluation.costs import CostContext
from backend.evaluation.filter_shadows import NAMESPACE, FilterShadow, filters, record
from backend.evaluation.ledger_inputs import collect_outcome_setups
from backend.evaluation.provenance import EvaluationProvenance
from backend.ops.trading_controls import ControlScope
from backend.tests.query_faults import selects_kind
from backend.tests.test_ledger_evaluation import scope
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_ER_full_CRO_veto_and_overlapping_filters_keep_unsized_quantity(
    harness: Harness,
    legacy: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = harness
    h.swarm.hunter.size_provider = lambda symbol, score, qty, portfolio, now: SizeEvidence(
        base_qty=qty, confidence=Decimal("0.5")
    )
    payload = json.loads((Path(__file__).parent / "fixtures/offline_nvda.json").read_text())
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in payload["bars"])
    candidate = h.swarm.hunter.hunt(
        "NVDA", bars, h.request.portfolio, h.request.market, h.clock.now()
    ).candidates[0]
    factors = candidate.size_evidence
    assert factors is not None
    request = type(h.request).model_validate({**h.request.model_dump(), "candidate": candidate})
    h.state.escalate(SystemState.HALTED, "offline test entry halt")
    result = await h.swarm.run(request)
    assert result.status == "VETOED" and result.alert_id is None
    h.state.ledger.verify_chain()
    if legacy:
        # Historical read projection only. Admission still requires the
        # current hunter evidence; no immutable signal is rewritten.
        get = Session.get

        def older_signal(session: Session, model: Any, *a: Any, **k: Any) -> Any:
            row = get(session, model, *a, **k)
            if model is Signal and row is not None:
                detached = SimpleNamespace(**vars(row))
                values = dict(row.structured_thesis)
                values["setup"] = {
                    name: value
                    for name, value in values["setup"].items()
                    if name != "size_evidence"
                }
                detached.structured_thesis = values
                return detached
            return row

        monkeypatch.setattr(Session, "get", older_signal)
        monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
        monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda *a: {})
    tracked = collect_outcome_setups(
        h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar
    )
    assert {row.disposition for row in tracked} == (
        {"CRO_VETO"} if legacy else {"CRO_VETO", "SZ_FILTER"}
    )
    assert all(row.qty == (candidate.qty if legacy else factors.base_qty) for row in tracked)
    h.state.ledger.verify_chain()


def test_ER_04_CRO_zero_cap_is_retained_without_an_order_or_LLM(harness: Harness) -> None:
    h = harness
    payload = json.loads((Path(__file__).parent / "fixtures/offline_nvda.json").read_text())
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in payload["bars"])
    portfolio = type(h.request.portfolio).model_validate(
        {
            **h.request.portfolio.model_dump(),
            "cash": Decimal(0),
            "settled_cash": Decimal(0),
        }
    )
    result = h.swarm.hunter.hunt("NVDA", bars, portfolio, h.request.market, h.clock.now())
    assert not result.candidates
    dropped = next(row for row in result.drops if row.filtered_candidate is not None)
    assert dropped.filtered_cro_cap == 0 and dropped.reductions is not None
    assert dropped.reductions.qty > 0 and dropped.filtered_candidate is not None
    assert dropped.filtered_candidate.qty == dropped.reductions.base_qty
    assert filters(dropped.reductions, accepted_qty=0) == ("CRO_VETO",)
    assert filters(dropped.reductions, accepted_qty=dropped.reductions.qty - 1) == ("CRO_VETO",)
    with pytest.raises(DataIntegrityError):
        filters(dropped.reductions, accepted_qty=dropped.reductions.qty + 1)


@pytest.mark.asyncio
async def test_ER_04_zero_RS_filter_does_not_make_a_ticket_or_call_the_LLM(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = harness
    h.swarm.hunter.size_provider = lambda symbol, score, qty, portfolio, now: SizeEvidence(
        base_qty=qty,
        relative_strength=Decimal(0),
        confidence=Decimal("0.5"),
        minimum=h.config.sizing.min_multiplier,
    )
    payload = json.loads((Path(__file__).parent / "fixtures/offline_nvda.json").read_text())
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in payload["bars"])
    found = h.swarm.hunter.hunt("NVDA", bars, h.request.portfolio, h.request.market, h.clock.now())
    assert not found.candidates
    drop = next(row for row in found.drops if row.filtered_candidate is not None)
    assert drop.reductions is not None and drop.filtered_candidate is not None
    candidate = drop.filtered_candidate
    value = atr(bars)[-1]
    assert value is not None
    provenance = EvaluationProvenance(
        cohort="PAPER",
        expires_at=proposal_expiry(
            h.clock.now(), h.settings.proposal_ttl_sessions, h.swarm.risk.cro.calendar
        ),
        yaml_hash=h.config.config_hash,
        settings_hash=h.settings.config_hash,
        evidence_session=bars[-1].session_date,
        initial_equity=h.request.portfolio.equity,
        cost_context=CostContext(atr14=value, policy=h.config.cm),
    )
    bound = ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER")
    identity = uuid5(
        NAMESPACE,
        f"{bound.account_id}/{bound.environment}/{h.request.data_snapshot_id}/{candidate.playbook}/{candidate.as_of}/{provenance.yaml_hash}",
    )
    proof = FilterShadow(
        identity=identity,
        scope=bound,
        data_snapshot_id=h.request.data_snapshot_id,
        candidate=candidate,
        factors=drop.reductions,
        provenance=provenance,
    )
    assert FilterShadow.recorded(proof.model_dump(mode="json")) == proof
    with pytest.raises(ValidationError, match="zero-sized"):
        FilterShadow.model_validate(
            proof.model_copy(update={"factors": SizeEvidence(base_qty=proof.factors.base_qty)})
        )
    with pytest.raises(ValidationError, match="identity"):
        FilterShadow.model_validate(
            proof.model_copy(update={"identity": h.request.data_snapshot_id})
        )
    malformed = proof.model_dump(mode="json")
    malformed["candidate"]["entry_price"] = "not-money"
    with pytest.raises(DataIntegrityError, match="unverifiable"):
        FilterShadow.recorded(malformed)
    future_candidate = type(candidate).model_validate(
        candidate.model_copy(update={"as_of": h.clock.now() + timedelta(seconds=1)})
    )
    future_identity = uuid5(
        NAMESPACE,
        f"{bound.account_id}/{bound.environment}/{h.request.data_snapshot_id}/{candidate.playbook}/{future_candidate.as_of}/{provenance.yaml_hash}",
    )
    future = FilterShadow.model_validate(
        proof.model_copy(update={"identity": future_identity, "candidate": future_candidate})
    )
    with pytest.raises(DataIntegrityError, match="future"):
        record(h.state.ledger, future)
    record(h.state.ledger, proof)
    record(h.state.ledger, proof)
    tracked = collect_outcome_setups(
        h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar
    )
    assert len(tracked) == 2 and {row.disposition for row in tracked} == {"RS_FILTER", "SZ_FILTER"}
    assert tracked[0].qty == proof.factors.base_qty > 0
    assert (
        collect_outcome_setups(
            h.state.ledger,
            h.settings,
            scope(h).model_copy(update={"account_id": "other-paper"}),
            h.swarm.risk.cro.calendar,
        )
        == ()
    )
    changed = proof.model_copy(
        update={
            "provenance": provenance.model_copy(
                update={"initial_equity": provenance.initial_equity + 1}
            )
        }
    )
    with pytest.raises(DataIntegrityError, match="changed"):
        record(h.state.ledger, changed)
    h.state.ledger.verify_chain()
    day = h.swarm.risk.cro.calendar.previous_sessions(scope(h).start, 1)[0]
    earlier = scope(h).model_copy(
        update={"start": h.swarm.risk.cro.calendar.previous_sessions(day, 1)[0], "end": day}
    )
    assert (
        collect_outcome_setups(h.state.ledger, h.settings, earlier, h.swarm.risk.cro.calendar) == ()
    )
    original = Session.scalars
    monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
    monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda *a: {})
    get = Session.get
    monkeypatch.setattr(
        Session,
        "get",
        lambda s, model, *a, **k: None if model is DataSnapshot else get(s, model, *a, **k),
    )
    with pytest.raises(DataIntegrityError, match="source/configuration"):
        collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)
    monkeypatch.setattr(Session, "get", get)
    monkeypatch.setattr(ledger_inputs, "MAX_TRACKED_SETUPS", 1)
    with pytest.raises(DataIntegrityError, match="alert plus counterfactual"):
        collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)
    monkeypatch.setattr(ledger_inputs, "MAX_TRACKED_SETUPS", 100000)

    def bounded(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        rows = original(session, statement, *args, **kwargs)
        if selects_kind(statement, "FILTER_SHADOW"):
            return [SimpleNamespace(**vars(row)) for row in rows] * 100001
        return rows

    monkeypatch.setattr(Session, "scalars", bounded)
    with pytest.raises(DataIntegrityError, match="inventory exceeds"):
        collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)
