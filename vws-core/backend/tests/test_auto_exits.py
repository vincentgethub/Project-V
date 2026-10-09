"""AX-24..31: protected recovery, fixed exits, capped shares and bounded attempts."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import DataSnapshot, ExecutionOrderRecord
from backend.core.errors import (
    ExecutionDisabledError,
    OrderRejectedError,
    ProviderError,
    ReconciliationError,
)
from backend.core.system_state import SystemState
from backend.data.data_layer import AsyncAlpacaMarketData, _bars_digest
from backend.data.fill_polling import ObservedFill
from backend.domain.models import MarketStatus, Side
from backend.execution.alpaca_executor import ProtectionRecovery
from backend.execution.modes import ModeStore
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


def refresh_quotes(h: Harness, *, suspect: bool = False) -> None:
    h.source.inputs = h.source.inputs.model_copy(
        update={
            "market": h.source.inputs.market.model_copy(
                update={
                    "last_price_ts": h.clock.now(),
                    "status": MarketStatus.SUSPECT if suspect else MarketStatus.OK,
                }
            ),
            "portfolio": h.source.inputs.portfolio.model_copy(update={"as_of": h.clock.now()}),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("state", ["RUNNING", "HALTED", "REDUCE_ONLY", "PAUSE", "MANUAL"])
async def test_AX_29_30_SUSPECT_exit_is_limit_capped_and_unblocked(
    harness: Harness, state: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built)
    if state in {"HALTED", "REDUCE_ONLY"}:
        h.state.escalate(SystemState(state), "fixture state")
    elif state in {"PAUSE", "MANUAL"}:
        built.modes.downgrade("PAUSE" if state == "PAUSE" else "MANUAL", actor="fixture owner")
    refresh_quotes(h, suspect=True)
    await built.monitor()
    assert len(client.posts) == 2
    exit_order = client.posts[-1]
    assert exit_order["side"] == "sell" and exit_order["type"] == "limit"
    assert exit_order["time_in_force"] == "day" and exit_order["qty"] == parent["qty"]
    assert all(row["status"] == "canceled" for row in parent["legs"])
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_unfilled_exit_has_three_reprices_then_one_stop_and_no_repeat_cycle(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built)
    refresh_quotes(h, suspect=True)
    await built.monitor()
    for _ in range(4):
        h.clock.current += timedelta(minutes=2)
        refresh_quotes(h, suspect=True)
        await built.monitor()
    assert len(client.posts) == 6
    assert (
        len([row for row in client.posts if row["side"] == "sell" and row["type"] == "limit"]) == 4
    )
    assert client.posts[-1]["type"] == "stop" and client.posts[-1]["time_in_force"] == "gtc"
    assert len({row["client_order_id"] for row in client.posts}) == 6
    await built.monitor()
    assert len(client.posts) == 6
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_29_partial_exit_reprices_only_remaining_broker_shares(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built)
    refresh_quotes(h, suspect=True)
    await built.monitor()
    raw = client.orders[client.posts[-1]["client_order_id"]]
    raw["filled_qty"], raw["status"] = "1", "partially_filled"
    client.positions[0]["qty"] = str(int(parent["qty"]) - 1)
    built.observe_fill(
        ObservedFill(
            account_id="offline-paper",
            broker_fill_id="partial-exit",
            broker_order_id=UUID(raw["id"]),
            symbol=raw["symbol"],
            side=Side.SELL,
            qty=1,
            price=Decimal(raw["limit_price"]),
            filled_at=h.clock.now(),
        )
    )
    h.clock.current += timedelta(minutes=2)
    refresh_quotes(h, suspect=True)
    await built.monitor()
    assert len(client.posts) == 3
    assert client.posts[-1]["qty"] == client.positions[0]["qty"]
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_30_restart_after_downgrade_repairs_stops_but_never_enters(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    built.modes.downgrade("MANUAL", actor="fixture owner")
    with pytest.raises(ExecutionDisabledError):
        executor(h, client)
    recovered = executor(h, client, constructor=ProtectionRecovery)
    await recovered.monitor()
    assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
    with pytest.raises(ExecutionDisabledError, match="cannot submit entries"):
        await recovered.enter(uuid4())
    recovered.modes.resume(operator="fixture owner", phrase="RESUME")
    with pytest.raises(ExecutionDisabledError):
        await recovered.enter(uuid4())
    assert len(client.posts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_30_missing_quote_never_prevents_valid_stop_repair(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    h.source.error = ProviderError("synthetic quote unavailable")
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
    assert h.state.current() == SystemState.HALTED
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_25_late_pause_is_a_no_send_and_not_a_broker_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    original = built.worker.bucket.acquire
    fired = False

    async def admission() -> None:
        nonlocal fired
        with Session(h.state.engine) as session:
            exists = session.scalar(select(ExecutionOrderRecord)) is not None
        if exists and not fired:
            fired = True
            built.modes.downgrade("PAUSE", actor="fixture owner")
        await original()

    monkeypatch.setattr(built.worker.bucket, "acquire", admission)
    with pytest.raises(ExecutionDisabledError, match="Final mode"):
        await built.enter(alert.proposal_id)
    assert fired and not client.posts
    assert h.state.current() == SystemState.RUNNING
    await built.monitor()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_third_confirmed_rejection_latches_and_survives_restart(
    harness: Harness,
) -> None:
    h = harness
    client = FakeTradingClient(h)
    client.failure = "reject"
    built = executor(h, client)
    with Session(h.state.engine) as session:
        source = session.get(DataSnapshot, h.request.data_snapshot_id)
        assert source is not None
        bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in source.bars)
    for number in range(3):
        if number:
            # Three independent session candidates, with freshly completed
            # synthetic bars. Reusing one research candidate is rightly refused.
            h.clock.current += timedelta(days=1)
            bars = (
                *bars,
                bars[-1].model_copy(
                    update={
                        "timestamp": bars[-1].timestamp + timedelta(days=1),
                        "open": bars[-1].open + Decimal(1),
                        "high": bars[-1].high + Decimal(1),
                        "low": bars[-1].low + Decimal(1),
                        "close": bars[-1].close + Decimal(1),
                    }
                ),
            )
            refresh_quotes(h)
            snapshot = h.state.ledger.append(
                DataSnapshot,
                symbol="NVDA",
                timeframe="1Day",
                feed="SIP",
                adjustment="SPLIT",
                fetched_at=h.clock.now(),
                range_start=bars[0].timestamp,
                range_end=bars[-1].timestamp,
                bar_count=len(bars),
                sha256=_bars_digest(bars)[0],
                bars=[row.model_dump(mode="json") for row in bars],
            )
            found = h.swarm.hunter.hunt(
                "NVDA", bars, h.source.inputs.portfolio, h.source.inputs.market, h.clock.now()
            )
            assert found.candidates
            h.request = h.request.model_copy(
                update={
                    "candidate": found.candidates[0],
                    "data_snapshot_id": snapshot.id,
                    "portfolio": h.source.inputs.portfolio,
                    "market": h.source.inputs.market,
                }
            )
        alert = await deliver(h)
        built = executor(
            h, client
        )  # Fresh synthetic backup/doctor proof each session; counter persists.
        with pytest.raises(OrderRejectedError):
            await built.enter(alert.proposal_id)
        assert h.state.current() == (SystemState.HALTED if number == 2 else SystemState.RUNNING)
    assert len(client.posts) == 3
    assert not ModeStore(h.settings, h.state, "offline-paper").entries_enabled
    h.state.ledger.verify_chain()
