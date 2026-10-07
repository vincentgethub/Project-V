"""UX: read-only activity paging, partial fills and immutable manual observations."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import Fill, OrderEvent, Signal
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.fill_polling import AlpacaFillSource, ObservedFill, TicketFillMatcher
from backend.net.egress import EgressPolicy, build_allowlist
from backend.tests.test_swarm_and_callbacks import (  # noqa: F401
    Harness,
    ack,
    click,
    count,
    deliver,
    make_research_harness,
)


def observed(h: Harness, **changes: Any) -> ObservedFill:
    return ObservedFill.model_validate(
        {
            "account_id": h.request.portfolio.account_id,
            "broker_fill_id": "observed-1",
            "broker_order_id": uuid4(),
            "symbol": "NVDA",
            "side": "BUY",
            "qty": 3,
            "price": Decimal(100),
            "filled_at": h.clock.now(),
            **changes,
        }
    )


def matcher(h: Harness) -> TicketFillMatcher:
    return TicketFillMatcher(
        h.settings, h.request.portfolio.account_id, h.state, h.swarm.risk.cro.registry
    )


@pytest.mark.asyncio
async def test_UX_partial_ticket_fills_bind_one_broker_order_and_deduplicate(
    harness: Harness,
) -> None:
    h = harness
    await deliver(h)
    assert (await h.gate.handle(click(h, "A"), acknowledge=ack)).status == "TICKET"
    match, row = matcher(h), observed(h)
    first = match.record(row)
    assert first.status == "MATCHED" and first.ticket_id is not None
    assert match.record(row).status == "DUPLICATE" and count(h, Fill) == 1
    second = row.model_copy(update={"broker_fill_id": "observed-2", "qty": 6})
    assert match.record(second).ticket_id == first.ticket_id and count(h, Fill) == 2
    with Session(h.state.engine) as session:
        latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()).limit(1))
        assert latest is not None and latest.state == "FILLED"
    assert h.state.current() == SystemState.RUNNING
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "why", ["no_ticket", "price", "oversized", "skipped", "expired", "before_ticket"]
)
async def test_UX_unmatched_fills_are_manual_signals_without_fictitious_orders(
    harness: Harness, why: str
) -> None:
    h = harness
    if why != "no_ticket":
        alert = await deliver(h)
        assert (await h.gate.handle(click(h, "A"), acknowledge=ack)).status == "TICKET"
        if why == "skipped":
            await h.gate.handle(click(h, "S"), acknowledge=ack)
        elif why == "expired":
            h.clock.current = alert.expires_at + timedelta(seconds=1)
    row = observed(
        h,
        price=Decimal(110) if why == "price" else Decimal(100),
        qty=10 if why == "oversized" else 3,
        filled_at=h.clock.now() - timedelta(seconds=1) if why == "before_ticket" else h.clock.now(),
    )
    match = matcher(h)
    assert match.record(row).status == "MANUAL"
    assert match.record(row).status == "DUPLICATE" and count(h, Fill) == 0
    with Session(h.state.engine) as session:
        signal = session.scalar(select(Signal).where(Signal.signal_type == "MANUAL"))
        assert signal is not None and signal.structured_thesis == {
            "observed_fill": row.model_dump(mode="json")
        }
        assert signal.confidence == 0 and "stop inferred" in signal.invalidation
    assert h.state.current() == SystemState.RUNNING
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["changed_id", "account", "future", "bound_oversized"])
async def test_UX_unverifiable_or_changed_observation_halts_without_duplicate_write(
    harness: Harness, bad: str
) -> None:
    h = harness
    await deliver(h)
    await h.gate.handle(click(h, "A"), acknowledge=ack)
    match, row = matcher(h), observed(h)
    if bad in {"changed_id", "bound_oversized"}:
        assert match.record(row).status == "MATCHED"
        row = (
            row.model_copy(update={"price": Decimal(99)})
            if bad == "changed_id"
            else row.model_copy(update={"broker_fill_id": "excess", "qty": 7})
        )
    elif bad == "account":
        row = row.model_copy(update={"account_id": "other-paper"})
    else:
        row = row.model_copy(update={"filled_at": h.clock.now() + timedelta(seconds=1)})
    with pytest.raises(DataIntegrityError):
        match.record(row)
    assert h.state.current() == SystemState.HALTED
    assert count(h, Fill) == (1 if bad in {"changed_id", "bound_oversized"} else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", [None, "account", "fraction", "price", "activity", "duplicate", "status", "redirect"]
)
async def test_UX_account_bound_read_only_activity_contract(
    harness: Harness, fault: str | None
) -> None:
    h = harness
    settings = h.settings.model_copy(
        update={
            "broker_api_key": SecretStr("test-read-key"),
            "broker_secret_key": SecretStr("test-read-secret"),
        }
    )
    calls: list[httpx.Request] = []
    raw = {
        "id": "activity-1",
        "order_id": str(uuid4()),
        "symbol": "NVDA",
        "side": "buy",
        "qty": "3.0",
        "price": "100.00",
        "transaction_time": h.clock.now().isoformat(),
        "activity_type": "FILL",
    }
    if fault == "fraction":
        raw["qty"] = "0.5"
    elif fault == "price":
        raw["price"] = "100.001"
    elif fault == "activity":
        raw["activity_type"] = "OTHER"

    async def http(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET" and request.url.host == "paper-api.alpaca.markets"
        if request.url.path == "/v2/account":
            return httpx.Response(
                200, json={"id": "wrong" if fault == "account" else h.request.portfolio.account_id}
            )
        assert (
            request.url.path == "/v2/account/activities"
            and request.url.params["activity_types"] == "FILL"
        )
        if fault == "status":
            return httpx.Response(429, headers={"Retry-After": "1"})
        if fault == "redirect":
            return httpx.Response(
                302, headers={"Location": "https://api.alpaca.markets/v2/account"}
            )
        return httpx.Response(200, json=[raw, raw] if fault == "duplicate" else [raw])

    reader = AsyncAlpacaReader(h.clock, h.state)
    source = AlpacaFillSource(
        settings,
        h.request.portfolio.account_id,
        h.state,
        h.clock,
        reader,
        EgressPolicy(build_allowlist(), h.state.ledger),
        transport=httpx.MockTransport(http),
    )
    try:
        if fault is None:
            batch = await source.read(h.clock.now() - timedelta(days=1), h.clock.now())
            assert len(batch.fills) == 1 and batch.fills[0].qty == 3
            assert reader.bucket.available == reader.bucket.capacity - 2
            assert h.state.current() == SystemState.RUNNING
        else:
            with pytest.raises(DataIntegrityError):
                await source.read(h.clock.now() - timedelta(days=1), h.clock.now())
            assert h.state.current() == SystemState.HALTED and reader.tripped
        assert len(calls) == (1 if fault == "account" else 2)
    finally:
        await source.close()


def test_UX_stage_f_matcher_rejects_auto_mode_and_polling_without_credentials(
    harness: Harness,
) -> None:
    h = harness
    with pytest.raises(ConfigurationError):
        matcher(
            Harness(
                **{
                    **h.__dict__,
                    "settings": h.settings.model_copy(update={"execution_mode": "AUTO_PAPER"}),
                }
            )
        )
    with pytest.raises(ConfigurationError):
        AlpacaFillSource(
            h.settings,
            h.request.portfolio.account_id,
            h.state,
            h.clock,
            AsyncAlpacaReader(h.clock, h.state),
            EgressPolicy(build_allowlist(), h.state.ledger),
        )
