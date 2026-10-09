"""AX-30/31: entry faults preserve only independently provable held protection."""

from decimal import Decimal
from uuid import uuid4

import pytest

from backend.core.errors import ExecutionDisabledError, ReconciliationError
from backend.core.system_state import SystemState
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("symbol", ["AMD", "UNLISTED"])
async def test_AX_30_unrelated_position_halts_but_repairs_verified_held_stop(
    harness: Harness, symbol: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    client.positions.append(
        {"symbol": symbol, "qty": "1", "side": "long", "asset_class": "us_equity"}
    )
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == 2
    assert client.posts[-1]["type"] == "stop" and client.posts[-1]["qty"] == "1"
    assert client.posts[-1]["stop_price"] == f"{h.request.candidate.stop_price:.2f}"
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("partial", [False, True])
async def test_SEC_73_panic_cancels_remainders_without_exit_analysis(
    harness: Harness, partial: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    if partial:
        await fill_entry(h, client, built, partial=True)
    with pytest.raises(ExecutionDisabledError, match="HALT first"):
        await built.cancel_unfilled_entries()
    h.state.escalate(SystemState.HALTED, "local panic fixture")

    async def forbidden(symbol: str) -> object:
        raise AssertionError("Panic must not request entry or time/earnings exit analysis")

    monkeypatch.setattr(h.source, "refresh", forbidden)
    await built.cancel_unfilled_entries()
    assert (
        next(row for row in client.orders.values() if row["side"] == "buy")["status"] == "canceled"
    )
    assert len(client.posts) == (2 if partial else 1)
    assert all(row["type"] == "stop" and row["qty"] == "1" for row in client.posts[1:])
    assert h.state.current() == SystemState.HALTED
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["held_quantity", "foreign_sell", "repair_rejection"])
async def test_AX_30_recovery_never_guesses_holdings_or_overlaps_unknown_sell(
    harness: Harness, fault: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)
    if fault == "held_quantity":
        client.positions[0]["qty"] = "2"
    elif fault == "foreign_sell":
        client.orders["foreign-manual"] = {
            "id": str(uuid4()),
            "client_order_id": "foreign-manual",
            "symbol": "NVDA",
            "side": "sell",
            "type": "limit",
            "order_class": "simple",
            "time_in_force": "day",
            "qty": "1",
            "filled_qty": "0",
            "status": "new",
            "limit_price": "150.00",
            "submitted_at": h.clock.now().isoformat(),
            "legs": None,
        }
    else:
        client.positions.append(
            {"symbol": "AMD", "qty": "1", "side": "long", "asset_class": "us_equity"}
        )
        client.failure = "reject"
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == (2 if fault == "repair_rejection" else 1)
    assert all(Decimal(row["qty"]) <= 1 for row in client.posts[1:])
    if fault != "repair_rejection":
        assert parent["status"] == "partially_filled"
    h.state.ledger.verify_chain()
