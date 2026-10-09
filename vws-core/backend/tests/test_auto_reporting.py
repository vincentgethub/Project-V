"""AX-50/51: recomputed fill/summary goldens and cohort/stop evidence faults."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import ExecutionFillRecord
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemStateStore
from backend.domain.compliance_models import TaxStatus
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AccountType, PortfolioSnapshot, Position, ProtectiveStop, Side
from backend.execution.modes import ModeStore
from backend.execution.reporting import daily_summary, fill_fyi
from backend.tax.accounting import build_tax_book
from backend.tax.models import TaxAccount, TaxFill
from backend.tests.test_execution_storage import append_execution_fixture
from backend.tests.test_system_state import RecordingNotifier


@pytest.mark.parametrize("masked", [False, True])
def test_AX_50_51_actual_fill_and_daily_summary_goldens(
    engine: Engine, clock: FrozenClock, masked: bool
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    _, entry, stop = append_execution_fixture(state.ledger, clock)
    with Session(engine) as session:
        fills = tuple(
            session.scalars(select(ExecutionFillRecord).order_by(ExecutionFillRecord.seq))
        )
    settings = Settings(
        _env_file=None,
        broker_account_type="CASH",
        execution_mode="AUTO_PAPER",
        telegram_mask_amounts=masked,
    )
    modes = ModeStore(settings, state, entry.account_id)
    text = fill_fyi(settings, entry, entry, fills[0], 1)
    expected = (
        "PAPER · 🤖 Bought $••• AAPL @ $99.00 · stop $95.00 (at broker) · target $105.00 · risk ≈ $••• · Tue Sep 29, 10:00 AM CT"
        if masked
        else "PAPER · 🤖 Bought 2 AAPL @ $99.00 · stop $95.00 (at broker) · target $105.00 · risk ≈ $4.00 · Tue Sep 29, 10:00 AM CT"
    )
    assert text == expected
    sale = fill_fyi(settings, stop, entry, fills[1], 1)
    assert "Stop hit" in sale and "@ $80.00" in sale and "stop $95.00" in sale
    registry = InstrumentRegistry.from_csv(Path(__file__).resolve().parents[2] / "config")
    account = TaxAccount(
        id=entry.account_id, name="Scratch", tax_status=TaxStatus.TAXABLE, source="ALPACA"
    )
    observations = tuple(
        TaxFill(
            fill_id=row.id,
            activity_id=row.broker_fill_id,
            account_id=entry.account_id,
            env="PAPER",
            symbol="AAPL",
            side=Side.BUY if row.execution_order_id == entry.id else Side.SELL,
            qty=row.qty,
            price=row.price,
            fees=Decimal(0),
            # The storage fixture ties its two fills; the tax tape must prove
            # their sequence rather than guess tied BUY/SELL chronology.
            ts=row.filled_at
            - (timedelta(microseconds=1) if row.execution_order_id == entry.id else timedelta(0)),
            fee_source="BROKER",
            payload_sha256="a" * 64,
        )
        for row in fills
    )
    book = build_tax_book(observations, (account,), registry, "PAPER")
    snapshot = PortfolioSnapshot(
        account_id=entry.account_id,
        account_type=AccountType.CASH,
        as_of=clock.now(),
        equity=Decimal("1101"),
        cash=Decimal("1000"),
        settled_cash=Decimal("1000"),
        positions={"AAPL": Position(qty=1, avg_cost=Decimal("99"), last_price=Decimal("101"))},
        open_orders=(),
        protective_stops=(ProtectiveStop(symbol="AAPL", qty=1, stop_price=Decimal("95")),),
        high_water_mark=Decimal("1101"),
        day_start_equity=Decimal("1101"),
    )
    summary = daily_summary(settings, modes, snapshot, book)
    money_line = (
        "Entries 1 · Exits 1 · Realized $••• · Open P&L $•••"
        if masked
        else "Entries 1 · Exits 1 · Realized $-19.00 · Open P&L $+2.00"
    )
    risk_line = "Open risk $••• · Cash $•••" if masked else "Open risk $+6.00 · Cash $+1,000.00"
    assert summary == (
        "PAPER · Daily summary · Tue Sep 29, 10:00 AM CT\n"
        + money_line
        + "\n"
        + risk_line
        + " · State RUNNING · Mode AUTO_PAPER\n"
        "Tomorrow's candidates: none recorded. Fresh checks decide."
    )
    uncovered = snapshot.model_copy(update={"protective_stops": ()})
    assert "Open risk UNVERIFIED: broker stop coverage differs" in daily_summary(
        settings, modes, uncovered, book
    )
    for change in (
        {"account_id": "foreign-account"},
        {"as_of": clock.now() - timedelta(seconds=settings.stale_quote_seconds, microseconds=1)},
        {"as_of": clock.now() + timedelta(microseconds=1)},
    ):
        with pytest.raises(DataIntegrityError):
            daily_summary(settings, modes, snapshot.model_copy(update=change), book)
    state.ledger.verify_chain()


@pytest.mark.parametrize("fault", ["environment", "order", "held", "levels", "role"])
def test_AX_50_fill_notice_never_guesses_foreign_or_invalid_evidence(
    engine: Engine, clock: FrozenClock, fault: str
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    _, entry, stop = append_execution_fixture(state.ledger, clock)
    with Session(engine) as session:
        fill = session.scalar(select(ExecutionFillRecord).order_by(ExecutionFillRecord.seq))
        assert fill is not None
    settings = Settings(_env_file=None, broker_account_type="CASH")
    held = 1
    instruction = entry
    if fault == "environment":
        entry.environment = "LIVE"
    elif fault == "order":
        instruction = stop
    elif fault == "held":
        held = -1
    elif fault == "levels":
        entry.stop_price = None
    else:
        instruction = stop
        fill.execution_order_id = stop.id
        instruction.role = "UNKNOWN"
    with pytest.raises(DataIntegrityError):
        fill_fyi(settings, instruction, entry, fill, held)
