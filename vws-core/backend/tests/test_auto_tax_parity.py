"""AX-26 acceptance 13: identical physical activities through both ledger paths."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import (
    DataSnapshot,
    ExecutionFillRecord,
    Fill,
    Order,
    OrderEvent,
    Signal,
    create_database,
    create_schema,
)
from backend.core.system_state import SystemStateStore
from backend.data.fill_polling import ObservedFill
from backend.domain.models import PortfolioSnapshot, Position, Side
from backend.domain.tax_profile import TaxProfile
from backend.evaluation.costs import FeeSchedule
from backend.funding.activities import ActivityBatch, parse_activity
from backend.tax.reports import render_report
from backend.tax.service import TaxService
from backend.tests.test_accounting_service import fee_schedule
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_26_manual_auto_lots_washes_and_8949_are_identical_goldens(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, purchase = await fill_entry(h, client, built)
    h.clock.current += timedelta(minutes=1)
    child = next(row for row in parent["legs"] if row["type"] == "stop")
    sale = ObservedFill(
        account_id=purchase.account_id,
        broker_fill_id="parity-stop-sale",
        broker_order_id=UUID(child["id"]),
        symbol=purchase.symbol,
        side=Side.SELL,
        qty=1,
        price=Decimal(child["stop_price"]) - Decimal(10),
        filled_at=h.clock.now(),
    )
    child["filled_qty"], child["status"] = "1", "partially_filled"
    built.observe_fill(sale)
    client.positions[0]["qty"] = str(purchase.qty - 1)
    schedule = fee_schedule()
    tape = tuple(
        parse_activity(
            {
                "activity_type": "FILL",
                "id": row.broker_fill_id,
                "symbol": row.symbol,
                "side": row.side.value.lower(),
                "qty": str(row.qty),
                "price": str(row.price),
                "transaction_time": row.filled_at.isoformat(),
                "order_id": str(row.broker_order_id),
            },
            purchase.account_id,
            "PAPER",
            h.clock.now(),
            schedule,
        )
        for row in (purchase, sale)
    )

    class PhysicalTape:
        async def read_activities(
            self, after: datetime | None, until: datetime, fees: FeeSchedule
        ) -> ActivityBatch:
            return ActivityBatch(
                account_id=purchase.account_id,
                env="PAPER",
                as_of=until,
                complete_history=True,
                activities=tape,
            )

    async def snapshot() -> PortfolioSnapshot:
        return h.request.portfolio.model_copy(
            update={
                "as_of": h.clock.now(),
                "cash": Decimal("9000"),
                "settled_cash": Decimal("9000"),
                "positions": {
                    "NVDA": Position(
                        qty=purchase.qty - 1, avg_cost=purchase.price, last_price=purchase.price
                    )
                },
            }
        )

    async def notify(text: str, urgent: bool) -> None:
        assert "estimate" in text.lower() or text.startswith("SIMULATED")

    manual_engine = create_database("sqlite:///" + str(tmp_path / "manual.sqlite3"))
    try:
        create_schema(manual_engine)
        manual_state = SystemStateStore(manual_engine, h.clock, h.state.notifier)
        with Session(h.state.engine) as session:
            data = session.get(DataSnapshot, h.request.data_snapshot_id)
            assert data is not None
            snapshot_record = manual_state.ledger.append(
                DataSnapshot,
                symbol=data.symbol,
                timeframe=data.timeframe,
                range_start=data.range_start,
                range_end=data.range_end,
                feed=data.feed,
                adjustment=data.adjustment,
                fetched_at=data.fetched_at,
                bar_count=data.bar_count,
                sha256=data.sha256,
                bars=data.bars,
            )
        manual_orders = {}
        for observed in (purchase, sale):
            signal = manual_state.ledger.append(
                Signal,
                agent_name="owner_manual_fixture",
                symbol="NVDA",
                direction=observed.side.value,
                signal_type="MANUAL",
                confidence=Decimal(1),
                structured_thesis={"reason": "observed owner trade"},
                invalidation="owner review",
                data_snapshot_id=snapshot_record.id,
                prompt_hash=None,
            )
            manual_orders[observed.side] = manual_state.ledger.append(
                Order,
                proposal_id=signal.id,
                signal_id=signal.id,
                client_order_id="manual-" + signal.id.hex,
                account_id=purchase.account_id,
                symbol="NVDA",
                side=observed.side.value,
                intent="ENTRY" if observed.side == Side.BUY else "EXIT",
                source="MANUAL",
                qty=observed.qty,
                limit_price=observed.price,
                stop_price=Decimal(1) if observed.side == Side.BUY else None,
            )
            for lifecycle in ("APPROVED", "SUBMITTED"):
                manual_state.ledger.append(
                    OrderEvent,
                    order_id=manual_orders[observed.side].id,
                    state=lifecycle,
                    reason="owner manually placed fixture trade",
                    broker_order_id=str(observed.broker_order_id),
                )

        def manual_capture(row: ObservedFill) -> object:
            # Manual polling deduplicates physical activity IDs before the
            # legacy record_fill API, as TicketFillMatcher does in MANUAL.
            with Session(manual_engine) as session:
                previous = session.scalar(
                    select(Fill).where(Fill.broker_fill_id == row.broker_fill_id)
                )
                if previous is not None:
                    assert (previous.qty, previous.price, previous.filled_at) == (
                        row.qty,
                        row.price,
                        row.filled_at,
                    )
                    return previous
            return manual_state.ledger.record_fill(
                manual_orders[row.side].id,
                broker_fill_id=row.broker_fill_id,
                qty=row.qty,
                price=row.price,
                filled_at=row.filled_at,
            )

        outputs = []
        for name, state, observer in (
            ("auto", h.state, built.observe_fill),
            ("manual", manual_state, manual_capture),
        ):
            project = tmp_path / name
            (project / "config").mkdir(parents=True)
            (project / "config/accounts.yaml").write_text("accounts: []\n", encoding="utf-8")
            tax = TaxService(
                project,
                state,
                h.settings,
                purchase.account_id,
                h.swarm.risk.cro.registry,
                PhysicalTape(),
                snapshot,
                notify,
                schedule,
                observe_fill=observer,
            )
            await tax.sync(force=True)
            await tax.sync(force=True)
            book = tax.book()
            totals, files = render_report(
                book,
                (),
                TaxProfile(),
                h.swarm.risk.cro.registry,
                2026,
                h.clock.now().date(),
                simulate=True,
            )
            outputs.append((book, totals, files))
            with Session(state.engine) as session:
                model = ExecutionFillRecord if name == "auto" else Fill
                assert len(tuple(session.scalars(select(model)))) == 2
            state.ledger.verify_chain()
        assert outputs[0] == outputs[1]
        book, _, files = outputs[0]
        assert len(book.sales) == 1 and len(book.lots) == 2
        assert sum(lot.qty for lot in book.lots) == purchase.qty - 1 == 8
        # 9 shares bought at 101.75 plus .01 modeled fees; one sells at
        # 89.10 minus .01 fees. Basis allocates to six decimal places.
        assert book.sales[0].basis == Decimal("101.751111")
        assert book.sales[0].proceeds == Decimal("89.09")
        assert book.sales[0].economic_gain == Decimal("-12.661111")
        assert book.sales[0].wash_disallowed == Decimal("12.661111")
        assert book.sales[0].taxable_gain == Decimal(0)
        assert book.adjustments, (
            "Retained shares bought within 30 days must be reviewed by the same wash engine"
        )
        assert any("8949" in name for name in files)
    finally:
        manual_engine.dispose()
