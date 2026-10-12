"""XA/GV: resolved managed broker trades, separate from EV hypothetical results."""

from decimal import Decimal, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import YamlConfig
from backend.core.database import ExecutionFillRecord, ExecutionOrderRecord, Order, Signal
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, Money, Playbook, Side, UTCDateTime
from backend.evaluation.costs import Exact, FeeSchedule, fees
from backend.execution.storage import approval_evidence, bindings
from backend.ops.trading_controls import ControlScope
from backend.tax.models import TaxFill
from backend.tax.storage import read_fills


class PhysicalTrade(FrozenModel):
    proposal_id: UUID
    scope: ControlScope
    playbook: Playbook
    entry_at: UTCDateTime
    exit_at: UTCDateTime
    fill_ids: tuple[UUID, ...] = Field(min_length=2, max_length=10000)
    net_money: Money
    initial_risk: Money = Field(gt=0)
    r_multiple: Exact
    modeled_fees: bool = Field(strict=True)


def resolved_trades(
    ledger: Ledger, scope: ControlScope, schedule: FeeSchedule, *, config: YamlConfig | None = None
) -> tuple[PhysicalTrade, ...]:
    """One proposal is one trade, including A/B partial fills and stop children.

    A still-open entry cannot qualify as a resolved round trip. Actual attributed
    fee evidence wins; absent attribution uses the same dated CM schedule and is
    labeled as an estimate. Tax wash adjustments never change economic returns.
    """
    checked = ControlScope.model_validate(scope)
    ledger.verify_chain()
    now = ledger.clock.now()
    attributed = {
        row.activity_id: row
        for row in read_fills(ledger, checked.account_id, checked.environment, csv=False)
    }
    with Session(ledger.engine) as session:
        instructions = tuple(
            session.scalars(
                select(ExecutionOrderRecord)
                .where(
                    ExecutionOrderRecord.account_id == checked.account_id,
                    ExecutionOrderRecord.environment == checked.environment,
                )
                .order_by(ExecutionOrderRecord.seq)
                .limit(100001)
            )
        )
        if len(instructions) > 100000:
            raise DataIntegrityError("GV: physical order inventory exceeds its bound")
        by_id = {row.id: row for row in instructions}
        fills = tuple(
            session.scalars(
                select(ExecutionFillRecord)
                .where(ExecutionFillRecord.execution_order_id.in_(tuple(by_id)))
                .order_by(ExecutionFillRecord.filled_at, ExecutionFillRecord.seq)
                .limit(100001)
            )
        )
        if len(fills) > 100000 or any(row.filled_at > now for row in fills):
            raise DataIntegrityError("GV: physical fill inventory is unbounded or future")
        proved = bindings(session)
        orders = {row.order_id: session.get(Order, row.order_id) for row in instructions}
        groups: dict[UUID, list[ExecutionOrderRecord]] = {}
        for row in instructions:
            groups.setdefault(row.order_id, []).append(row)
        result: list[PhysicalTrade] = []
        for identity, members in groups.items():
            original = orders[identity]
            entries = tuple(row for row in members if row.role == "ENTRY")
            if not entries:
                continue
            if original is None or original.account_id != checked.account_id:
                raise DataIntegrityError("GV: physical proposal binding differs")
            proof = approval_evidence(session, original.proposal_id, entries[0].seq)
            if proof is None:
                raise DataIntegrityError("GV: physical trade lacks its immutable approval")
            if config is not None and proof.yaml_hash != config.config_hash:
                continue  # Other policies never certify the current policy's edge.
            signal = session.get(Signal, original.signal_id)
            if signal is None:
                raise DataIntegrityError("GV: physical trade lacks its recorded signal")
            proposal_fills = tuple(
                row for row in fills if by_id[row.execution_order_id].order_id == identity
            )
            bought = tuple(
                row for row in proposal_fills if by_id[row.execution_order_id].side == "BUY"
            )
            sold = tuple(
                row for row in proposal_fills if by_id[row.execution_order_id].side == "SELL"
            )
            bought_qty, sold_qty = sum(row.qty for row in bought), sum(row.qty for row in sold)
            if sold_qty > bought_qty:
                raise DataIntegrityError("GV: physical trade oversold")
            if not bought_qty or sold_qty != bought_qty:
                continue
            if any(row.id not in proved or proved[row.id].is_open for row in entries):
                continue
            if sold[0].filled_at < bought[0].filled_at:
                raise DataIntegrityError("GV: physical sale precedes acquisition")
            total_fees, risk = Decimal(0), Decimal(0)
            modeled = False
            with localcontext() as precision:
                precision.prec = 80
                for fill in proposal_fills:
                    instruction = by_id[fill.execution_order_id]
                    tax: TaxFill | None = attributed.get(fill.broker_fill_id)
                    if tax is not None:
                        if (tax.symbol, tax.side.value, tax.qty, tax.price, tax.ts) != (
                            instruction.symbol,
                            instruction.side,
                            fill.qty,
                            fill.price,
                            fill.filled_at,
                        ):
                            raise DataIntegrityError(
                                "GV: attributed broker fee/fill identity differs"
                            )
                        total_fees += tax.fees
                        modeled |= tax.fee_source == "MODELED"
                    else:
                        total_fees += fees(
                            Side(instruction.side),
                            fill.qty,
                            fill.price,
                            fill.filled_at.astimezone(ZoneInfo("America/New_York")).date(),
                            schedule=schedule,
                        ).total
                        modeled = True
                    if instruction.side == "BUY":
                        if instruction.stop_price is None or fill.price <= instruction.stop_price:
                            raise DataIntegrityError(
                                "GV: physical initial stop risk is unavailable"
                            )
                        risk += (fill.price - instruction.stop_price) * fill.qty
                net = (
                    sum((row.price * row.qty for row in sold), Decimal(0))
                    - sum((row.price * row.qty for row in bought), Decimal(0))
                    - total_fees
                )
                result.append(
                    PhysicalTrade(
                        proposal_id=original.proposal_id,
                        scope=checked,
                        playbook=Playbook(signal.structured_thesis["setup"]["playbook"]),
                        entry_at=bought[0].filled_at,
                        exit_at=sold[-1].filled_at,
                        fill_ids=tuple(row.id for row in proposal_fills),
                        net_money=net,
                        initial_risk=risk,
                        r_multiple=net / risk,
                        modeled_fees=modeled,
                    )
                )
        return tuple(sorted(result, key=lambda row: (row.exit_at, row.proposal_id.hex)))
