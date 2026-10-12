"""EX-01/02: isolated fake requests, conserved shares, protected restarts."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import YamlConfig
from backend.core.database import ExecutionOrderRecord
from backend.core.errors import ExecutionDisabledError
from backend.execution.exit_variants import HeldEntry, HeldExitObservation
from backend.execution.storage import entry_quantity
from backend.notifications.callbacks import FreshInputs
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


def variant(h: Harness, name: str) -> None:
    values = h.config.model_dump(mode="python")
    values["exits"]["variant"] = name
    h.config = YamlConfig.model_validate(values)
    h.swarm.config = h.config


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("name", ["SPLIT_1R", "SPLIT_1R_TRAIL"])
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_EX_split_has_two_durable_ids_and_duplicate_trigger_recovers_both(
    harness: Harness,
    name: str,
    ambiguous: bool,
) -> None:
    h = harness
    variant(h, name)
    alert = await deliver(h)
    client = FakeTradingClient(h)
    client.failure = "accepted-timeout" if ambiguous else None
    first, second = executor(h, client), executor(h, client)
    first.entry_variant_allowed = second.entry_variant_allowed = lambda: True

    async def observation(held: HeldEntry, fresh: FreshInputs) -> HeldExitObservation:
        raise AssertionError("An entry test must not consume held-exit observations")

    first.held_exit_observation = second.held_exit_observation = observation
    observed = await asyncio.gather(first.enter(alert.proposal_id), second.enter(alert.proposal_id))
    assert len(client.posts) == 2
    a, b = client.posts
    total = h.request.candidate.qty
    assert a["client_order_id"] == "vws-" + alert.proposal_id.hex + "-a"
    assert b["client_order_id"] == "vws-" + alert.proposal_id.hex + "-b"
    assert int(a["qty"]) == total // 2 and int(b["qty"]) == total - total // 2
    assert a["stop_loss"] == b["stop_loss"]
    assert Decimal(a["take_profit"]["limit_price"]) == h.request.candidate.entry_price + (
        h.request.candidate.entry_price - h.request.candidate.stop_price
    )
    assert b["order_class"] == ("oto" if name == "SPLIT_1R_TRAIL" else "bracket")
    assert ("take_profit" not in b) is (name == "SPLIT_1R_TRAIL")
    assert len(observed[0].broker_orders) == len(observed[1].broker_orders) == 2
    assert tuple(row.order_id for row in observed[0].broker_orders) == tuple(
        row.order_id for row in observed[1].broker_orders
    )
    assert first._daily_count() == 1
    with Session(h.state.engine) as session:
        parents = tuple(
            session.scalars(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
            )
        )
        assert len(parents) == 2 and entry_quantity(session, parents[0].order_id) == total
        for parent in parents:
            children = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.parent_execution_id == parent.id
                    )
                )
            )
            assert sum(row.qty for row in children if row.role == "STOP") == parent.qty
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("available", [None, False])
async def test_EX_nonbaseline_missing_working_evidence_never_submits(
    harness: Harness,
    available: bool | None,
) -> None:
    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    ex = executor(harness, client)
    ex.entry_variant_allowed = None if available is None else lambda: available
    with pytest.raises(ExecutionDisabledError, match="WORKING"):
        await ex.enter(alert.proposal_id)
    assert not client.posts
    harness.state.ledger.verify_chain()
