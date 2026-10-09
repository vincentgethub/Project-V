"""AX-25/31/42: actual admission and monitor boundary faults, no network."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.core.config import Settings
from backend.core.errors import ExecutionDisabledError
from backend.core.system_state import SystemState
from backend.domain.compliance_models import TradeRecord
from backend.domain.models import PortfolioSnapshot, Position, Side
from backend.execution.policy import live_ceiling_reasons
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_domain import proposal as make_proposal
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "harness", [AUTO, {**AUTO, "day_trade_regime": "LEGACY_PDT"}], indirect=True
)
async def test_AX_25_actual_submit_refuses_settled_cash_or_two_legacy_day_trades(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    if h.settings.day_trade_regime == "LEGACY_PDT":
        history = tuple(
            TradeRecord(
                trade_id=uuid4(),
                account_id="offline-paper",
                symbol="NVDA",
                side=side,
                qty=1,
                price=Decimal(100),
                ts=h.clock.now() - timedelta(days=1, minutes=minute),
            )
            for minute, side in ((4, Side.BUY), (3, Side.SELL), (2, Side.BUY), (1, Side.SELL))
        )
        h.source.inputs = h.source.inputs.model_copy(update={"history": history})
    else:
        h.source.inputs = h.source.inputs.model_copy(
            update={
                "portfolio": h.source.inputs.portfolio.model_copy(
                    update={"settled_cash": Decimal(0)}
                )
            }
        )
    with pytest.raises(ExecutionDisabledError):
        await built.enter(alert.proposal_id)
    assert not client.posts
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "equity,state",
    [
        ("9800", SystemState.RUNNING),
        ("9000", SystemState.REDUCE_ONLY),
        ("8500", SystemState.HALTED),
    ],
)
async def test_AX_30_daily_loss_and_drawdown_cancel_remainder_but_preserve_stop(
    harness: Harness, equity: str, state: SystemState
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)

    async def portfolio() -> PortfolioSnapshot:
        return h.source.inputs.portfolio.model_copy(
            update={
                "equity": Decimal(equity),
                "cash": Decimal(equity) - Decimal(100),
                "settled_cash": Decimal(equity) - Decimal(100),
                "positions": {
                    "NVDA": Position(qty=1, avg_cost=Decimal(100), last_price=Decimal(100))
                },
            }
        )

    built.portfolio = portfolio
    await built.monitor()
    assert h.state.current() == state
    assert parent["status"] == "canceled" and len(client.posts) == 2
    assert client.posts[-1]["type"] == "stop" and client.posts[-1]["qty"] == "1"
    if state == SystemState.RUNNING:
        assert built.risk.marks is not None and built.risk.marks.daily_loss_blocked(h.clock.now())
    with pytest.raises(ExecutionDisabledError):
        await built.enter(uuid4())
    assert len(client.posts) == 2
    h.state.ledger.verify_chain()


@pytest.mark.parametrize("boundary", ["notional", "daily", "positions", "gross", "risk", "loss"])
def test_AX_42_exact_live_ceiling_boundary_and_first_excess(
    harness: Harness, boundary: str
) -> None:
    h = harness
    proposal = make_proposal(
        stop_price=Decimal(99), target_price=Decimal(103), account_id="offline-paper"
    )
    portfolio = h.request.portfolio
    values = {
        "live_max_order_notional": Decimal(1000),
        "live_max_daily_orders": 5,
        "live_max_open_positions": 3,
        "live_max_gross_exposure_pct": Decimal(1),
        "live_max_risk_per_trade": Decimal("0.01"),
        "live_daily_loss_limit": Decimal("0.02"),
    }
    daily = 0
    if boundary == "notional":
        values["live_max_order_notional"] = Decimal(100)
    elif boundary == "daily":
        daily = 4
    elif boundary == "positions":
        values["live_max_open_positions"] = 1
    elif boundary == "gross":
        values["live_max_gross_exposure_pct"] = Decimal("0.01")
    elif boundary == "risk":
        values["live_max_risk_per_trade"] = (
            Decimal(1) + Decimal(100) * h.settings.stop_slippage_buffer
        ) / portfolio.equity
    elif boundary == "loss":
        # The daily loss cutoff itself blocks; the nearest cent above permits entry.
        portfolio = portfolio.model_copy(update={"equity": Decimal("9800.01")})
    settings = Settings.validated_copy(h.settings.model_copy(update=values))
    assert not live_ceiling_reasons(settings, proposal, portfolio, daily)
    if boundary in {"notional", "gross"}:
        proposal = proposal.model_copy(update={"limit_price": Decimal("100.01")})
    elif boundary == "daily":
        daily += 1
    elif boundary == "positions":
        portfolio = portfolio.model_copy(
            update={
                "positions": {"NVDA": Position(qty=1, avg_cost=Decimal(1), last_price=Decimal(1))}
            }
        )
    elif boundary == "risk":
        proposal = proposal.model_copy(update={"stop_price": Decimal("98.99")})
    else:
        portfolio = portfolio.model_copy(update={"equity": Decimal(9800)})
    reasons = live_ceiling_reasons(settings, proposal, portfolio, daily)
    expected = {
        "notional": "notional",
        "daily": "daily entry",
        "positions": "open-position",
        "gross": "gross-exposure",
        "risk": "per-trade risk",
        "loss": "daily loss",
    }[boundary]
    assert len(reasons) == 1 and expected in reasons[0]
