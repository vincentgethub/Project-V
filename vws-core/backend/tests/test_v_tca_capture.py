"""XA-01: canonical fills, missing evidence, frozen costs and no cost decreases."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionOrderRecord, SecurityEvent
from backend.data.fill_polling import ObservedFill
from backend.domain.models import Side
from backend.evaluation.calibrated_costs import snapshot
from backend.evaluation.costs import (
    CostContext,
    CostOrder,
    arrival_reference,
    estimate_fill,
    half_spread,
)
from backend.evaluation.tca_store import calibration, inventory
from backend.notifications.callbacks import FreshInputs
from backend.ops.trading_controls import ControlScope
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_costs import bar
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness
D = Decimal


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("available", [True, False])
async def test_XA_physical_fill_quality_is_idempotent_and_missing_arrival_never_passes(
    harness: Harness,
    available: bool,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    ex = executor(h, client)
    await ex.enter(alert.proposal_id)
    raw, bought = await fill_entry(h, client, ex)
    if not available:
        # Generated stops have no invented trigger-time arrival quote.
        stop = next(leg for leg in raw["legs"] if leg["type"] == "stop")
        stop["status"], stop["filled_qty"] = "filled", stop["qty"]
        for child in raw["legs"]:
            if child["type"] == "limit":
                child["status"] = "canceled"
        with Session(h.state.engine) as session:
            intent = session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.client_order_id == stop["client_order_id"]
                )
            )
            assert intent is not None
        await ex._read_bound(intent)
        sold = ObservedFill(
            account_id=bought.account_id,
            broker_fill_id="quality-stop",
            broker_order_id=UUID(stop["id"]),
            symbol=bought.symbol,
            side=Side.SELL,
            qty=bought.qty,
            price=D(stop["stop_price"]),
            filled_at=h.clock.now(),
        )
        ex.observe_fill(sold)
        ex.observe_fill(sold)
    scope = ControlScope(account_id="offline-paper", environment="PAPER")
    rows = inventory(h.state.ledger, scope)
    assert len(rows) == (1 if available else 2)
    assert (rows[-1].unavailable_reason is None) is available
    assert (rows[-1].arrival_slippage_bps is not None) is available
    assert not inventory(
        h.state.ledger, ControlScope(account_id="offline-paper", environment="LIVE")
    )
    result = calibration(h.state.ledger, scope, "2026-09", rows[0].bucket, D(2))
    assert result.n == 1 and result.unavailable == int(not available)
    again = calibration(h.state.ledger, scope, "2026-09", rows[0].bucket, D(2))
    assert again == result
    with Session(h.state.engine) as session:
        assert (
            len(
                tuple(
                    session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "COST_CALIBRATION")
                    )
                )
            )
            == 1
        )
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XA_twenty_real_identity_fills_calibrate_and_later_empty_month_cannot_lower(
    harness: Harness,
) -> None:
    h = harness
    import json
    from pathlib import Path

    from backend.data.data_layer import AsyncAlpacaMarketData

    assert h.request.capital is not None

    payload = json.loads((Path(__file__).parent / "fixtures/offline_nvda.json").read_text())
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in payload["bars"])
    portfolio = type(h.request.portfolio).model_validate(
        {
            **h.request.portfolio.model_dump(),
            "equity": D(100000),
            "cash": D(100000),
            "settled_cash": D(100000),
            "high_water_mark": D(100000),
            "day_start_equity": D(100000),
        }
    )
    capital = type(h.request.capital).model_validate(
        {**h.request.capital.model_dump(), "checking_used": D(101500), "deployable": D(100000)}
    )
    candidate = h.swarm.hunter.hunt(
        "NVDA", bars, portfolio, h.request.market, h.clock.now()
    ).candidates[0]
    h.request = type(h.request).model_validate(
        {
            **h.request.model_dump(),
            "candidate": candidate,
            "portfolio": portfolio,
            "capital": capital,
        }
    )
    h.source.inputs = FreshInputs.model_validate(
        {**h.source.inputs.model_dump(), "portfolio": portfolio, "capital": capital}
    )
    alert = await deliver(h)
    client = FakeTradingClient(h)
    ex = executor(h, client)
    limit = h.request.candidate.entry_price
    h.source.inputs = FreshInputs.model_validate(
        {
            **h.source.inputs.model_dump(),
            "market": {
                **h.source.inputs.market.model_dump(),
                "last_price": (limit * D("0.995")).quantize(D("0.01")),
            },
        }
    )
    await ex.enter(alert.proposal_id)
    raw = next(iter(client.orders.values()))
    assert int(raw["qty"]) >= 20
    with Session(h.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
        assert entry is not None
    for index in range(20):
        raw["filled_qty"], raw["status"] = str(index + 1), "partially_filled"
        await ex._read_bound(entry)
        fill = ObservedFill(
            account_id="offline-paper",
            broker_fill_id=f"quality-{index}",
            broker_order_id=UUID(raw["id"]),
            symbol=entry.symbol,
            side=Side.BUY,
            qty=1,
            price=limit,
            filled_at=h.clock.now(),
        )
        ex.observe_fill(fill)
        ex.observe_fill(fill)
    scope = ControlScope(account_id="offline-paper", environment="PAPER")
    rows = inventory(h.state.ledger, scope)
    assert len(rows) == 20
    report = calibration(h.state.ledger, scope, "2026-09", rows[0].bucket, D(2))
    assert report.n == 20 and report.p50_bps is not None and report.p50_bps > 4
    assert report.calibrated_half_spread_bps == report.p50_bps
    later = calibration(h.state.ledger, scope, "2026-10", rows[0].bucket, D(2))
    assert later.n == 0 and later.calibrated_half_spread_bps == report.calibrated_half_spread_bps
    proof = snapshot(h.state.ledger, "PAPER", scope=scope)
    ctx = proof.context(CostContext(atr14=D(2), median_dollar_volume_20=D(100000000)))
    assert (
        ctx.calibration_sha256 == proof.sha256
        and half_spread(ctx)[0] >= report.calibrated_half_spread_bps
    )
    assert snapshot(h.state.ledger, "LIVE").scope is None
    h.state.ledger.verify_chain()


@pytest.mark.parametrize(
    "kind,level,opening",
    [
        ("ENTRY", "101", "100"),
        ("STOP", "100", "99"),
        ("STOP", "100", "101"),
        ("TARGET", "100", "100"),
    ],
)
def test_XA_quote_reference_uses_exactly_the_CM_fill_price(
    kind: str, level: str, opening: str
) -> None:
    from typing import Literal, cast

    order = CostOrder(
        kind=cast(Literal["ENTRY", "STOP", "TARGET"], kind),
        side=Side.BUY if kind == "ENTRY" else Side.SELL,
        level=D(level),
        qty=100,
        decision_session=bar().session_date - timedelta(days=1),
    )
    observed = bar(open=D(opening), high=D(102), low=D(98))
    ctx = CostContext(atr14=D(2), median_dollar_volume_20=D(500000000))
    result = estimate_fill(order, observed, ctx)
    assert result.price == arrival_reference(order, observed.open, ctx)
