"""TX-02..05: exact FIFO/compressed FIFO with the shared wash matcher.

Each physical acquisition is an interval of whole shares. Matching returns its
actual replacement intervals; refinement only splits those accounting intervals,
never generates trading parameters. Rebuilding propagates basis through dated
wash chains until the finite ledger is stable. No writes, I/O or account login.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.core.money import money_to_scaled, scaled_to_money
from backend.data.history import canonical_bytes
from backend.domain.compliance_models import TaxLot, TradeRecord, WashAdjustment
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import FrozenModel, Side
from backend.tax.lots import WashSaleMatcher, trade_day
from backend.tax.models import Environment, OpenTaxLot, TaxAccount, TaxFill, TaxSale

IDENTITY = UUID("e7fc5a78-98bf-42ca-9d62-cc03cd279e81")
MAX_ACCOUNTING_ROWS = 100000
MAX_WASH_PASSES = 1024
Allocation = tuple[WashAdjustment, tuple[tuple[int, int], ...]]


def anniversary(acquired: date) -> date:
    """TX-04: leap-day acquisition uses February 28 in the following year."""
    if type(acquired) is not date or acquired.year == 9999:
        raise DataIntegrityError("TX-04: acquisition date cannot establish an anniversary")
    return (
        date(
            acquired.year + 1, 2, 28 if (acquired.month, acquired.day) == (2, 29) else acquired.day
        )
        if acquired.month == 2
        else date(acquired.year + 1, acquired.month, acquired.day)
    )


@dataclass
class _Pool:
    qty: int
    basis: int


@dataclass
class _Part:
    fill: TaxFill
    start: int
    end: int
    pool: tuple[str, str, str]
    extra: int
    holding: datetime

    @property
    def qty(self) -> int:
        return self.end - self.start


class TaxBook(FrozenModel):
    env: Environment
    accounts: tuple[TaxAccount, ...] = Field(min_length=1, max_length=1000)
    fills: tuple[TaxFill, ...] = Field(max_length=MAX_ACCOUNTING_ROWS)
    sales: tuple[TaxSale, ...] = Field(max_length=MAX_ACCOUNTING_ROWS)
    lots: tuple[OpenTaxLot, ...] = Field(max_length=MAX_ACCOUNTING_ROWS)
    history: tuple[TradeRecord, ...] = Field(max_length=MAX_ACCOUNTING_ROWS)
    adjustments: tuple[WashAdjustment, ...] = Field(max_length=MAX_ACCOUNTING_ROWS)

    @model_validator(mode="after")
    def bound(self) -> Self:
        owners = {row.id for row in self.accounts}
        fills = {row.fill_id: row for row in self.fills}
        if (
            len(owners) != len(self.accounts)
            or len(fills) != len(self.fills)
            or any(
                row.account_id not in owners or row.env != self.env
                for row in tuple[TaxFill | TaxSale | OpenTaxLot, ...](
                    (*self.fills, *self.sales, *self.lots)
                )
            )
            or len({row.sale_id for row in self.sales}) != len(self.sales)
            or len({row.lot_id for row in self.lots}) != len(self.lots)
        ):
            raise ValueError("TX-01/04: account, environment or accounting identity differs")
        sold: dict[UUID, int] = defaultdict(int)
        for sale in self.sales:
            sold[sale.fill_id] += sale.qty
        for fill in self.fills:
            if fill.side == Side.SELL and sold[fill.fill_id] != fill.qty:
                raise ValueError("TX-03: disposal slices differ from actual filled shares")
        if any(
            row.fill_id not in fills
            or fills[row.fill_id].side != Side.SELL
            or row.acquisition_id not in fills
            or fills[row.acquisition_id].side != Side.BUY
            for row in self.sales
        ) or any(
            row.acquisition_id not in fills or fills[row.acquisition_id].side != Side.BUY
            for row in self.lots
        ):
            raise ValueError("TX-02: accounting lineage lacks actual acquisition/disposal fills")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    def compliance_lots(self) -> tuple[TaxLot, ...]:
        """Preserve exact total basis as at most two per-share micro-unit buckets."""
        output: list[TaxLot] = []
        for lot in self.lots:
            units, remainder = divmod(money_to_scaled(lot.basis), lot.qty)
            for suffix, qty, per_share in (
                ("base", lot.qty - remainder, units),
                ("residual", remainder, units + 1),
            ):
                if qty:
                    output.append(
                        TaxLot(
                            lot_id=uuid5(lot.lot_id, suffix),
                            account_id=lot.account_id,
                            symbol=lot.symbol,
                            qty=qty,
                            acquired_at=lot.acquired_at,
                            cost_basis=scaled_to_money(per_share),
                            acquisition_trade_id=lot.acquisition_id,
                            holding_period_start=lot.holding_period_start,
                        )
                    )
        return tuple(output)


def _rebuild(
    fills: tuple[TaxFill, ...],
    accounts: dict[str, TaxAccount],
    allocations: tuple[Allocation, ...],
    prior_history: tuple[TradeRecord, ...],
    boundaries: dict[UUID, set[int]],
) -> tuple[tuple[TaxSale, ...], tuple[OpenTaxLot, ...], tuple[TradeRecord, ...]]:
    pools: dict[tuple[str, str, str], _Pool] = {}
    parts: list[_Part] = []
    sales: list[TaxSale] = []
    history: list[TradeRecord] = []
    prior = {row.trade_id: row for row in prior_history}
    by_fill: dict[UUID, list[Allocation]] = {}
    buys = {row.fill_id: row for row in fills if row.side == Side.BUY}
    for allocation in allocations:
        adjustment, _ranges = allocation
        loss = prior[adjustment.loss_trade_id]
        replacement = buys[adjustment.replacement_trade_id]
        identity = replacement.fill_id if replacement.ts > loss.ts else loss.execution_id
        if identity is None:
            raise DataIntegrityError("TX-05: wash allocation lacks an actual disposition")
        by_fill.setdefault(identity, []).append(allocation)

    def apply(identity: UUID) -> None:
        for adjustment, ranges in by_fill.get(identity, ()):
            selected = [
                part
                for part in parts
                if part.fill.fill_id == adjustment.replacement_trade_id
                and any(start <= part.start < part.end <= end for start, end in ranges)
            ]
            if sum(part.qty for part in selected) != adjustment.qty:
                raise DataIntegrityError("TX-05: replacement share intervals are unavailable")
            used = allocated = 0
            total = money_to_scaled(adjustment.disallowed_loss)
            for part in selected:
                used += part.qty
                next_amount = total * used // adjustment.qty
                if not adjustment.permanent_loss:
                    part.extra += next_amount - allocated
                    part.holding = adjustment.holding_period_start
                allocated = next_amount

    with localcontext() as precision:
        precision.prec = 80
        for fill in fills:
            if fill.side == Side.BUY:
                account = accounts[fill.account_id]
                pool_id = (
                    fill.account_id,
                    fill.symbol,
                    str(trade_day(fill.ts))
                    if account.method == "ALPACA_COMPRESSED_FIFO"
                    else fill.fill_id.hex,
                )
                cost = money_to_scaled(fill.qty * fill.price + fill.fees)
                pool = pools.setdefault(pool_id, _Pool(0, 0))
                pool.qty += fill.qty
                pool.basis += cost
                marks = sorted(boundaries[fill.fill_id])
                parts.extend(
                    _Part(fill, start, end, pool_id, 0, fill.ts)
                    for start, end in zip(marks, marks[1:], strict=False)
                )
                history.append(
                    TradeRecord(
                        trade_id=fill.fill_id,
                        account_id=fill.account_id,
                        symbol=fill.symbol,
                        side=Side.BUY,
                        qty=fill.qty,
                        price=fill.price,
                        ts=fill.ts,
                        is_drip=fill.is_drip,
                    )
                )
            else:
                remaining = fill.qty
                candidates = sorted(
                    (
                        part
                        for part in parts
                        if part.fill.account_id == fill.account_id
                        and part.fill.symbol == fill.symbol
                    ),
                    key=lambda part: (part.fill.ts, part.fill.fill_id.hex, part.start),
                )
                fee_units = money_to_scaled(fill.fees)
                disposed = allocated_fee = 0
                for part in candidates:
                    if not remaining:
                        break
                    quantity = min(remaining, part.qty)
                    pool = pools[part.pool]
                    basis = pool.basis * quantity // pool.qty
                    extra = part.extra * quantity // part.qty
                    disposed += quantity
                    next_fee = fee_units * disposed // fill.qty
                    proceeds = fill.price * quantity - scaled_to_money(next_fee - allocated_fee)
                    total_basis = scaled_to_money(basis + extra)
                    net = proceeds - total_basis
                    identity = uuid5(IDENTITY, f"{fill.fill_id}/{part.fill.fill_id}/{part.start}")
                    held_date = trade_day(part.holding)
                    sales.append(
                        TaxSale(
                            sale_id=identity,
                            fill_id=fill.fill_id,
                            acquisition_id=part.fill.fill_id,
                            account_id=fill.account_id,
                            env=fill.env,
                            symbol=fill.symbol,
                            qty=quantity,
                            acquired_at=part.fill.ts,
                            sold_at=fill.ts,
                            holding_period_start=part.holding,
                            proceeds=proceeds,
                            basis=total_basis,
                            economic_gain=net,
                            wash_basis=scaled_to_money(extra),
                            wash_disallowed=Decimal(0),
                            permanent_disallowed=Decimal(0),
                            taxable_gain=net,
                            term="LT" if trade_day(fill.ts) > anniversary(held_date) else "ST",
                        )
                    )
                    history.append(
                        TradeRecord(
                            trade_id=identity,
                            account_id=fill.account_id,
                            symbol=fill.symbol,
                            side=Side.SELL,
                            qty=quantity,
                            price=fill.price,
                            ts=fill.ts,
                            realized_loss=max(-net, Decimal(0)),
                            holding_period_start=part.holding,
                            acquisition_trade_id=part.fill.fill_id,
                            execution_id=fill.fill_id,
                        )
                    )
                    boundaries[part.fill.fill_id].add(part.start + quantity)
                    pool.qty -= quantity
                    pool.basis -= basis
                    part.extra -= extra
                    part.start += quantity
                    if not part.qty:
                        parts.remove(part)
                    remaining -= quantity
                    allocated_fee = next_fee
                if remaining:
                    raise DataIntegrityError("TX-02: sale exceeds verified long inventory")
            apply(fill.fill_id)
            if len(parts) + len(history) > MAX_ACCOUNTING_ROWS:
                raise DataIntegrityError("TX-02: bounded accounting intervals exceeded")
        lots: list[OpenTaxLot] = []
        allocated_pool: dict[tuple[str, str, str], tuple[int, int]] = {}
        for part in sorted(parts, key=lambda row: (row.fill.ts, row.fill.fill_id.hex, row.start)):
            pool = pools[part.pool]
            used, allocated = allocated_pool.get(part.pool, (0, 0))
            new_used = used + part.qty
            new_allocated = pool.basis * new_used // pool.qty
            basis = new_allocated - allocated + part.extra
            lots.append(
                OpenTaxLot(
                    lot_id=uuid5(IDENTITY, f"lot/{part.fill.fill_id}/{part.start}"),
                    acquisition_id=part.fill.fill_id,
                    account_id=part.fill.account_id,
                    env=part.fill.env,
                    symbol=part.fill.symbol,
                    qty=part.qty,
                    acquired_at=part.fill.ts,
                    holding_period_start=part.holding,
                    basis=scaled_to_money(basis),
                    wash_basis=scaled_to_money(part.extra),
                )
            )
            allocated_pool[part.pool] = (new_used, new_allocated)
    return tuple(sales), tuple(lots), tuple(history)


def build_tax_book(
    fills: tuple[TaxFill, ...],
    accounts: tuple[TaxAccount, ...],
    registry: InstrumentRegistry,
    env: Environment,
) -> TaxBook:
    """Revalidate all public inputs; mixed environments or unavailable evidence refuse."""
    try:
        if (
            not isinstance(fills, tuple)
            or not isinstance(accounts, tuple)
            or len(fills) > MAX_ACCOUNTING_ROWS
            or env not in {"PAPER", "LIVE"}
        ):
            raise ValueError("TX-01: bounded immutable evidence and explicit environment required")
        owned = tuple(TaxAccount.model_validate(row) for row in accounts)
        owners = {row.id: row for row in owned}
        checked = tuple(
            sorted(
                (TaxFill.model_validate(row) for row in fills),
                key=lambda row: (row.ts, 0 if row.side == Side.BUY else 1, row.fill_id.hex),
            )
        )
        if (
            not owners
            or len(owners) != len(owned)
            or len({row.fill_id for row in checked}) != len(checked)
            or len({(row.account_id, row.activity_id) for row in checked}) != len(checked)
        ):
            raise ValueError("TX-01: account/fill identities must be unique")
        for row in checked:
            if row.env != env or row.account_id not in owners:
                raise ValueError("TX-01: fill ownership/environment differs")
            registry.get(row.symbol)
        tied: dict[tuple[str, str, datetime], set[Side]] = {}
        for row in checked:
            tied.setdefault((row.account_id, row.symbol, row.ts), set()).add(row.side)
        if any(len(sides) > 1 for sides in tied.values()):
            raise ValueError("TX-02: tied BUY/SELL fills cannot establish an intraday sequence")
        boundaries = {row.fill_id: {0, row.qty} for row in checked if row.side == Side.BUY}
        matcher = WashSaleMatcher(registry)
        allocations: tuple[Allocation, ...] = ()
        previous_history: tuple[TradeRecord, ...] = ()
        for _pass in range(min(len(checked) + 2, MAX_WASH_PASSES)):
            before = {key: frozenset(value) for key, value in boundaries.items()}
            sales, lots, history = _rebuild(
                checked, owners, allocations, previous_history, boundaries
            )
            candidate = matcher.allocations(history, tuple(row.ownership for row in owned))
            for adjustment, ranges in candidate:
                for start, end in ranges:
                    boundaries[adjustment.replacement_trade_id].update((start, end))
            if candidate == allocations and before == {
                key: frozenset(value) for key, value in boundaries.items()
            }:
                with localcontext() as precision:
                    precision.prec = 80
                    final_sales = tuple(
                        TaxSale.model_validate(
                            row.model_copy(
                                update={
                                    "wash_disallowed": sum(
                                        (
                                            item.disallowed_loss
                                            for item, _ranges in candidate
                                            if item.loss_trade_id == row.sale_id
                                        ),
                                        Decimal(0),
                                    ),
                                    "permanent_disallowed": sum(
                                        (
                                            item.disallowed_loss
                                            for item, _ranges in candidate
                                            if item.loss_trade_id == row.sale_id
                                            and item.permanent_loss
                                        ),
                                        Decimal(0),
                                    ),
                                    "taxable_gain": row.economic_gain
                                    + sum(
                                        (
                                            item.disallowed_loss
                                            for item, _ranges in candidate
                                            if item.loss_trade_id == row.sale_id
                                        ),
                                        Decimal(0),
                                    ),
                                }
                            )
                        )
                        for row in sales
                    )
                return TaxBook(
                    env=env,
                    accounts=owned,
                    fills=checked,
                    sales=final_sales,
                    lots=lots,
                    history=history,
                    adjustments=tuple(row for row, _ranges in candidate),
                )
            allocations, previous_history = candidate, history
        raise DataIntegrityError("TX-05: wash basis/tacking did not converge within its bound")
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("TX-01..05: tax accounting evidence is unverifiable") from None
