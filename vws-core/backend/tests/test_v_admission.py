"""PR: the same private manual gate checks fresh reductions without changing tickets."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from backend.core.database import TradeTicket
from backend.core.system_state import SystemState
from backend.data.data_layer import AsyncAlpacaMarketData
from backend.domain.models import SizeEvidence
from backend.evaluation.ledger_inputs import collect_outcome_setups
from backend.tests.test_ledger_evaluation import scope
from backend.tests.test_swarm_and_callbacks import (
    Harness,
    ack,
    click,
    count,
    deliver,
    make_research_harness,
)

harness = make_research_harness
D = Decimal


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", ["same", "less", "zero", "invalid", "boolean"])
async def test_PR_fresh_manual_size_never_alters_an_approved_ticket(
    harness: Harness, allowed: str
) -> None:
    h = harness
    await deliver(h)

    async def fresh_size(*args: object) -> int:
        return {
            "same": h.request.candidate.qty,
            "less": h.request.candidate.qty - 1,
            "zero": 0,
            "invalid": h.request.candidate.qty + 1,
            "boolean": True,
        }[allowed]

    h.gate.size_entry = fresh_size
    if allowed in {"invalid", "boolean"}:
        result = await h.gate.handle(click(h, "A"), acknowledge=ack)
        assert result.status == "FAILED"
        assert h.state.current() == SystemState.HALTED
    else:
        result = await h.gate.handle(click(h, "A"), acknowledge=ack)
        assert result.status == ("TICKET" if allowed == "same" else "FAILED")
    assert count(h, TradeTicket) == int(allowed == "same")
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_ER_04_downsized_candidate_has_a_distinct_costed_shadow(harness: Harness) -> None:
    h = harness
    h.swarm.hunter.size_provider = lambda symbol, score, qty, portfolio, now: SizeEvidence(
        base_qty=qty, confidence=D("0.5"), minimum=h.config.sizing.min_multiplier
    )
    payload = json.loads(
        (Path(__file__).resolve().parent / "fixtures/offline_nvda.json").read_text()
    )
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in payload["bars"])
    candidate = h.swarm.hunter.hunt(
        "NVDA", bars, h.request.portfolio, h.request.market, h.clock.now()
    ).candidates[0]
    h.request = h.request.model_copy(update={"candidate": candidate})
    await deliver(h)
    await h.gate.handle(click(h, "A"), acknowledge=ack)
    tracked = collect_outcome_setups(
        h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar
    )
    taken = next(row for row in tracked if row.disposition == "APPROVED")
    shadow = next(row for row in tracked if row.disposition == "SZ_FILTER")
    assert candidate.size_evidence is not None
    assert shadow.qty == candidate.size_evidence.base_qty > taken.qty
    assert shadow.alert_id != taken.alert_id
    assert shadow.limit == taken.limit and shadow.stop == taken.stop
