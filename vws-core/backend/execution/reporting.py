"""AX-50/51: actual fills and cohort-bound summaries, computed without an LLM."""

from datetime import timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import Alert, ExecutionFillRecord, ExecutionOrderRecord, Order
from backend.core.errors import DataIntegrityError
from backend.domain.models import PortfolioSnapshot
from backend.execution.modes import ModeStore
from backend.notifications.card_formatter import display_time
from backend.tax.accounting import TaxBook
from backend.tax.lots import trade_day

_NY = ZoneInfo("America/New_York")


def fill_fyi(
    settings: Settings,
    instruction: ExecutionOrderRecord,
    entry: ExecutionOrderRecord,
    fill: ExecutionFillRecord,
    held: int,
    *,
    unit_cost: Decimal | None = None,
    exit_reason: str | None = None,
) -> str:
    if (
        fill.execution_order_id != instruction.id
        or instruction.account_id != entry.account_id
        or instruction.environment != entry.environment
        or entry.environment != ("PAPER" if settings.paper_trading else "LIVE")
        or entry.role != "ENTRY"
        or entry.stop_price is None
        or entry.target_price is None
        or type(held) is not int
        or held < 0
    ):
        raise DataIntegrityError("AX-50: fill notice account, order or held evidence differs")
    label = (
        ("Partial buy" if fill.qty < entry.qty else "Bought")
        if instruction.side == "BUY"
        else {
            "STOP": "Stop hit",
            "REPAIR": "Stop hit",
            "TARGET": "Target hit",
            "EXIT": "Exit fill",
        }.get(instruction.role)
    )
    if label is None:
        raise DataIntegrityError("AX-50: fill notice role is unknown")
    if exit_reason is not None:
        label = {
            "TIME": "Time-stop exit",
            "EARNINGS": "Earnings exit",
            "SUSPECT": "Suspect-data exit",
        }.get(exit_reason)
        if instruction.role != "EXIT" or label is None:
            raise DataIntegrityError("AX-50: exit notice reason is not authorized")
    cost = (
        unit_cost
        if unit_cost is not None
        else (fill.price if instruction.side == "BUY" else entry.limit_price)
    )
    if not isinstance(cost, Decimal) or not cost.is_finite() or cost <= 0:
        raise DataIntegrityError("AX-50: fill notice lacks an exact acquisition cost")
    with localcontext() as precision:
        precision.prec = 80
        risk = max(Decimal(0), cost - entry.stop_price) * held
    qty = "$•••" if settings.telegram_mask_amounts else str(fill.qty)
    risk_text = "$•••" if settings.telegram_mask_amounts else f"${risk:,.2f}"
    protection = "at broker" if held else "recorded level; position closed"
    return (
        f"{entry.environment} · 🤖 {label} {qty} {entry.symbol} @ ${fill.price:.2f} · "
        f"stop ${entry.stop_price:.2f} ({protection}) · target ${entry.target_price:.2f} · "
        f"risk ≈ {risk_text} · {display_time(fill.filled_at, settings)}"
    )


def daily_summary(
    settings: Settings, modes: ModeStore, snapshot: PortfolioSnapshot, book: TaxBook
) -> str:
    portfolio, tax = PortfolioSnapshot.model_validate(snapshot), TaxBook.model_validate(book)
    now = ensure_utc(modes.state.clock.now())
    if (
        portfolio.account_id != modes.account_id
        or tax.env != modes.environment
        or modes.account_id not in {row.id for row in tax.accounts}
        or not timedelta(0)
        <= now - portfolio.as_of
        <= timedelta(seconds=settings.stale_quote_seconds)
    ):
        raise DataIntegrityError(
            "AX-51: summary requires fresh bound broker and shared tax evidence"
        )
    modes.state.ledger.verify_chain()
    day = now.astimezone(_NY).date()
    with Session(modes.state.engine) as session:
        instructions = {
            row.id: row
            for row in session.scalars(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.account_id == modes.account_id,
                    ExecutionOrderRecord.environment == modes.environment,
                )
            )
        }
        fills = tuple(
            row
            for row in session.scalars(select(ExecutionFillRecord))
            if row.execution_order_id in instructions and trade_day(row.filled_at) == day
        )
        alerts = tuple(
            session.scalars(
                select(Alert)
                .join(Order, Alert.proposal_id == Order.proposal_id)
                .where(
                    Order.account_id == modes.account_id,
                    Alert.config_hash == settings.config_hash,
                    Alert.expires_at > now,
                )
                .order_by(Alert.score.desc(), Alert.seq.desc())
            )
        )
    entries = {
        row.execution_order_id
        for row in fills
        if instructions[row.execution_order_id].side == "BUY"
    }
    exits = {
        instructions[row.execution_order_id].parent_execution_id
        for row in fills
        if instructions[row.execution_order_id].side == "SELL"
    }
    candidates = tuple(
        dict.fromkeys(
            row.symbol
            for row in alerts
            if modes.state.ledger.current_alert_status(row.id) in {"PENDING", "SENT"}
        )
    )[:5]
    with localcontext() as precision:
        precision.prec = 80
        realized = sum(
            (
                row.realized_before_wash
                for row in tax.sales
                if row.account_id == modes.account_id and trade_day(row.sold_at) == day
            ),
            Decimal(0),
        )
        unrealized = sum(
            ((row.last_price - row.avg_cost) * row.qty for row in portfolio.positions.values()),
            Decimal(0),
        )
        risk = Decimal(0)
        coverage = True
        for symbol, held in portfolio.positions.items():
            stops = tuple(row for row in portfolio.protective_stops if row.symbol == symbol)
            coverage = coverage and sum(row.qty for row in stops) == held.qty
            risk += sum(
                (max(Decimal(0), held.last_price - row.stop_price) * row.qty for row in stops),
                Decimal(0),
            )

    def money(value: Decimal) -> str:
        return "$•••" if settings.telegram_mask_amounts else f"${value:+,.2f}"

    risk_text = money(risk) if coverage else "UNVERIFIED: broker stop coverage differs"
    return (
        f"{modes.environment} · Daily summary · {display_time(now, settings)}\n"
        f"Entries {len(entries)} · Exits {len(exits)} · Realized {money(realized)} · Open P&L {money(unrealized)}\n"
        f"Open risk {risk_text} · Cash {money(portfolio.cash)} · State {modes.state.current().value} · Mode {modes.effective}\n"
        f"Tomorrow's candidates: {', '.join(candidates) if candidates else 'none recorded'}. Fresh checks decide."
    )
