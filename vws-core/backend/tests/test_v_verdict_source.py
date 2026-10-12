"""GV/XA: real ledger paths, no cohort top-ups, bounded publication and no orders."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionOrderRecord, SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.data.fee_schedule import load_fee_schedule
from backend.data.fill_polling import ObservedFill
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import Side
from backend.evaluation.physical import resolved_trades
from backend.evaluation.tca_store import record_arrival
from backend.evaluation.verdict import VerdictInputs, evaluate
from backend.evaluation.verdict_source import VerdictPublisher, collect, update_progress
from backend.notifications.callbacks import FreshInputs
from backend.ops.doctor import stop_slippage_check
from backend.ops.trading_controls import ControlScope
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from backend.tests.test_v_stop_raises import entered

harness = make_research_harness
D = Decimal
SCOPE = ControlScope(account_id="offline-paper", environment="PAPER")
ROOT = Path(__file__).resolve().parents[2]


def evidence(h: Harness) -> VerdictInputs:
    return collect(
        h.state.ledger,
        h.settings,
        h.config,
        SCOPE,
        MarketCalendar(),
        load_fee_schedule(ROOT / "config/fees.yaml"),
        history=None,
        effective_hash=h.config.config_hash,
    )


def test_GV_missing_ledger_evidence_stays_NOT_YET(harness: Harness) -> None:
    row = evidence(harness)
    assert row.source == "UNAVAILABLE" and row.drawdown is None and row.sessions == ()
    assert row.edge_drift is None and row.unresolved_reconciliation is None
    assert not row.security_green and row.drill_at is None
    assert row.unavailable_playbooks == harness.config.enabled_playbooks
    assert evaluate(row, harness.config.gv).status == "NOT_YET"
    with pytest.raises(DataIntegrityError, match="paper scope"):
        collect(
            harness.state.ledger,
            harness.settings,
            harness.config,
            ControlScope(account_id="offline-paper", environment="LIVE"),
            MarketCalendar(),
            load_fee_schedule(ROOT / "config/fees.yaml"),
            history=None,
            effective_hash=harness.config.config_hash,
        )


async def close_split_trade(
    harness: Harness,
) -> None:
    h = harness
    ex, client, _ = await entered(h)
    before_posts = len(client.posts)
    assert not resolved_trades(h.state.ledger, SCOPE, load_fee_schedule(ROOT / "config/fees.yaml"))
    roots = tuple(client.orders.values())
    for index, raw in enumerate(roots):
        stop = next(child for child in raw["legs"] if child["type"] == "stop")
        with Session(h.state.engine) as session:
            instruction = session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.client_order_id == stop["client_order_id"]
                )
            )
            assert instruction is not None
        quote = FreshInputs.model_validate(
            {
                **h.source.inputs.model_dump(),
                "market": {
                    **h.source.inputs.market.model_dump(),
                    "last_price": D(stop["stop_price"]) + D(1),
                    "last_price_ts": h.clock.now(),
                },
            }
        )
        record_arrival(h.state.ledger, instruction, quote.market, h.settings.stale_quote_seconds)
        stop["status"], stop["filled_qty"] = "filled", stop["qty"]
        for child in raw["legs"]:
            if child["type"] == "limit":
                child["status"] = "canceled"
        await ex._read_bound(instruction)
        fill = ObservedFill(
            account_id=SCOPE.account_id,
            broker_fill_id=f"readiness-stop-{index}",
            broker_order_id=UUID(stop["id"]),
            symbol=raw["symbol"],
            side=Side.SELL,
            qty=int(stop["qty"]),
            price=D(stop["stop_price"]),
            filled_at=h.clock.now(),
        )
        ex.observe_fill(fill)
        ex.observe_fill(fill)
        if index == 0:
            assert not resolved_trades(
                h.state.ledger, SCOPE, load_fee_schedule(ROOT / "config/fees.yaml")
            )
    client.positions = []
    await ex.reconcile()
    trades = resolved_trades(h.state.ledger, SCOPE, load_fee_schedule(ROOT / "config/fees.yaml"))
    assert len(trades) == 1 and len(trades[0].fill_ids) == 4 and trades[0].modeled_fees
    assert trades[0].net_money < -trades[0].initial_risk
    assert not resolved_trades(
        h.state.ledger,
        ControlScope(account_id=SCOPE.account_id, environment="LIVE"),
        load_fee_schedule(ROOT / "config/fees.yaml"),
    )
    inputs = evidence(h)
    assert inputs.source == "AUTO_PAPER" and len(inputs.r_multiples) == 1
    assert inputs.unresolved_reconciliation is False
    assert evaluate(inputs, h.config.gv).status == "NOT_YET"
    assert stop_slippage_check(h.state.ledger, h.settings, SCOPE.account_id).status == "WARN"
    assert stop_slippage_check(h.state.ledger, h.settings, None).status == "UNVERIFIED"
    assert len(client.posts) == before_posts
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_GV_split_roots_are_one_physical_trade_and_never_hypothetical(
    harness: Harness,
) -> None:
    await close_split_trade(harness)


@pytest.mark.asyncio
async def test_GV_monthly_after_close_publication_is_once_and_never_unlocks(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    progress = project / "docs/PROGRESS.md"
    progress.write_text(
        "# Project V progress\n## Where things stand\nReadiness verdict: UNVERIFIED\n"
        "## What works now\nOffline fixtures.\n",
        encoding="utf-8",
    )
    sent: list[str] = []

    async def notify(text: str, urgent: bool) -> None:
        assert not urgent
        sent.append(text)

    publisher = VerdictPublisher(
        h.state.ledger, h.config, SCOPE, MarketCalendar(), project, lambda: evidence(h), notify
    )
    first = h.clock.now().date().replace(day=1)
    # The fake clock only moves forward: next month's first XNYS session.
    first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    calendar = MarketCalendar()
    while not calendar.is_session(first):
        first += timedelta(days=1)
    h.clock.current = calendar.session_close(first) - timedelta(seconds=1)
    assert await publisher.publish(monthly=True) is None
    h.clock.current += timedelta(minutes=31)
    result = await publisher.publish(monthly=True)
    assert result is not None and result.status == "NOT_YET"
    assert await publisher.publish(monthly=True) is None
    assert len(sent) == 1 and "Readiness verdict: NOT YET" in progress.read_text(encoding="utf-8")
    with Session(h.state.engine) as session:
        kinds = tuple(session.scalars(select(SecurityEvent.kind)))
    assert (
        kinds.count("VERDICT") == 1 and "LIVE_ENABLED" not in kinds and "MODE_OVERRIDE" not in kinds
    )
    progress.write_text("# wrong placeholder\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        update_progress(project, result)
