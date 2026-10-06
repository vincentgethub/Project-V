"""R-02/R-03/R-04/R-05, CMP-01/CMP-02: pure chronological wash-sale matching.

This is a pre-trade/reconciliation estimate, not a complete tax return. Supplied
history must include all acquisitions and dispositions relevant to matching.
Loss records attest any tax basis and holding-period adjustments from earlier
wash sales; tacked holding periods require an explicit acquisition trade ID.
Without that ID the holding start attests the actual untacked acquisition.
FIFO identifies non-loss dispositions without an acquisition ID;
ambiguous or insufficient supplied inventory fails closed. Sold shares cannot
replace themselves; retained shares of a partly sold acquisition can qualify.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.money import money_to_scaled, scaled_to_money
from backend.domain.compliance_models import (
    ExternalAccount,
    Form8949Row,
    TaxLot,
    TaxStatus,
    TradeRecord,
    WashAdjustment,
)
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import Side

_NEW_YORK = ZoneInfo("America/New_York")


def trade_day(value: datetime) -> date:
    """R-05/CMP-01/CMP-02: calendar-day windows use the US exchange date."""
    return ensure_utc(value).astimezone(_NEW_YORK).date()


class WashSaleMatcher:
    """CMP-01/CMP-02/R-03: detached metadata and no I/O or mutable tax ledger."""

    def __init__(self, registry: InstrumentRegistry) -> None:
        try:
            if not isinstance(registry, InstrumentRegistry):
                raise DataIntegrityError("Wash matcher requires an explicit instrument registry")
            self.registry = InstrumentRegistry.validated_copy(registry)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify wash-sale registry") from exc

    def marked_external_lots(
        self, sale: TradeRecord, lots: tuple[TaxLot, ...]
    ) -> tuple[TaxLot, ...]:
        """Owner-marked current lots prompt review; never infer tax treatment.

        This uses the same identity groups and inclusive exchange-date window
        as adjustments. It does not claim an estimated loss or a basis change.
        """
        try:
            checked = TradeRecord.model_validate(sale)
            if checked.side != Side.SELL or not isinstance(lots, tuple):
                raise DataIntegrityError(
                    "TX: sale awareness requires SELL and immutable marked lots"
                )
            checked_lots = tuple(TaxLot.model_validate(lot) for lot in lots)
            for lot in checked_lots:
                self.registry.get(lot.symbol)
            if len({lot.lot_id for lot in checked_lots}) != len(checked_lots):
                raise DataIntegrityError("TX: duplicate external marked lot")
            group = self.registry.identical_group(checked.symbol)
            return tuple(
                lot
                for lot in checked_lots
                if checked.realized_loss > 0
                and lot.account_id != checked.account_id
                and lot.symbol in group
                and abs((trade_day(lot.acquired_at) - trade_day(checked.ts)).days) <= 30
            )
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError(
                "TX: external marked lot awareness cannot be validated"
            ) from None

    def adjustments(
        self,
        history: tuple[TradeRecord, ...],
        accounts: tuple[ExternalAccount, ...],
    ) -> tuple[WashAdjustment, ...]:
        """CMP-01/CMP-02: inclusive 61-day matching and shared share capacity.

        Acquisitions match in chronological order. Before-sale shares must still
        be held after the loss disposition. A later sale does not erase an
        already valid replacement match. Each purchase share is assigned once
        across all losses. Proportional loss uses cumulative integer micro-unit
        allocation, so partial matches never absorb unmatched-share losses.
        """
        # VERIFY: https://www.irs.gov/publications/p550
        # VERIFY: https://www.irs.gov/pub/irs-drop/rr-08-05.pdf
        try:
            ordered, statuses = self._inputs(history, accounts)
            surviving = self._survivors(ordered)
            buys = tuple(row for row in ordered if row.side == Side.BUY)
            acquisitions = {row.trade_id: row.ts for row in buys}
            assigned: dict[UUID, list[tuple[int, int]]] = {row.trade_id: [] for row in buys}
            output: list[WashAdjustment] = []
            for loss in ordered:
                if loss.realized_loss <= 0 or statuses[loss.account_id] != TaxStatus.TAXABLE:
                    continue
                group = self.registry.identical_group(loss.symbol)
                used = 0
                allocated_micro = 0
                loss_micro = money_to_scaled(loss.realized_loss)
                for replacement in buys:
                    if used == loss.qty:
                        break
                    if (
                        replacement.symbol not in group
                        or abs((trade_day(replacement.ts) - trade_day(loss.ts)).days) > 30
                    ):
                        continue
                    first_held = 0
                    if replacement.trade_id in surviving[loss.trade_id]:
                        first_held = replacement.qty - surviving[loss.trade_id].get(
                            replacement.trade_id, 0
                        )
                    slices = self._available_slices(
                        first_held, replacement.qty, assigned[replacement.trade_id], loss.qty - used
                    )
                    matched = sum(end - start for start, end in slices)
                    if matched == 0:
                        continue
                    new_used = used + matched
                    new_allocated = loss_micro * new_used // loss.qty
                    disallowed = scaled_to_money(new_allocated - allocated_micro)
                    if disallowed <= 0:
                        raise DataIntegrityError(
                            "Wash loss allocation is below supported micro-unit precision"
                        )
                    output.append(
                        self._adjustment(
                            loss,
                            replacement,
                            matched,
                            disallowed,
                            statuses,
                            acquisitions[loss.acquisition_trade_id]
                            if loss.acquisition_trade_id is not None
                            else None,
                        )
                    )
                    assigned[replacement.trade_id].extend(slices)
                    assigned[replacement.trade_id].sort()
                    used = new_used
                    allocated_micro = new_allocated
            return tuple(output)
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify wash-sale matching evidence") from exc

    @staticmethod
    def _available_slices(
        first_held: int, total: int, assigned: list[tuple[int, int]], requested: int
    ) -> tuple[tuple[int, int], ...]:
        """CMP-02: FIFO share intervals prevent retained matched shares being reused."""
        cursor = first_held
        remaining = requested
        output: list[tuple[int, int]] = []
        for start, end in (*assigned, (total, total)):
            if end <= cursor:
                continue
            available = max(0, start - cursor)
            matched = min(available, remaining)
            if matched:
                output.append((cursor, cursor + matched))
                remaining -= matched
            cursor = max(cursor, end)
            if remaining == 0:
                break
        return tuple(output)

    def _inputs(
        self, history: tuple[TradeRecord, ...], accounts: tuple[ExternalAccount, ...]
    ) -> tuple[tuple[TradeRecord, ...], dict[str, TaxStatus]]:
        """R-02/CMP-01/CMP-02: revalidate forged models and every ownership link."""
        if not isinstance(history, tuple) or not isinstance(accounts, tuple):
            raise DataIntegrityError("Wash-sale evidence must be immutable tuples")
        checked_accounts = tuple(ExternalAccount.model_validate(row) for row in accounts)
        statuses = {row.account_id: row.tax_status for row in checked_accounts}
        if len(statuses) != len(checked_accounts):
            raise DataIntegrityError("Tax account identifiers must be unique")
        ordered = tuple(
            sorted(
                (TradeRecord.model_validate(row) for row in history),
                key=lambda row: (row.ts, 0 if row.side == Side.BUY else 1, str(row.trade_id)),
            )
        )
        if len({row.trade_id for row in ordered}) != len(ordered):
            raise DataIntegrityError("Executed trade identifiers must be unique")
        for trade in ordered:
            if trade.account_id not in statuses:
                raise DataIntegrityError("Executed trade ownership/tax status is unknown")
            self.registry.get(trade.symbol)
            if (
                trade.side == Side.SELL
                and trade.holding_period_start is None
                and trade.acquisition_trade_id is None
                and any(
                    row.side == Side.BUY
                    and row.account_id == trade.account_id
                    and row.symbol == trade.symbol
                    and row.ts == trade.ts
                    for row in ordered
                )
            ):
                raise DataIntegrityError("Tied BUY/SELL execution requires original-lot metadata")
        return ordered, statuses

    @staticmethod
    def _survivors(ordered: tuple[TradeRecord, ...]) -> dict[UUID, dict[UUID, int]]:
        """CMP-02: replay lot disposals before checking replacement availability."""
        inventory: dict[UUID, int] = {}
        purchases: dict[UUID, TradeRecord] = {}
        result: dict[UUID, dict[UUID, int]] = {}
        for trade in ordered:
            if trade.side == Side.BUY:
                purchases[trade.trade_id] = trade
                inventory[trade.trade_id] = trade.qty
                continue
            candidates = tuple(
                buy
                for buy in purchases.values()
                if buy.account_id == trade.account_id and buy.symbol == trade.symbol
            )
            selected: tuple[TradeRecord, ...]
            if trade.acquisition_trade_id is not None:
                origin = purchases.get(trade.acquisition_trade_id)
                if origin is None or origin not in candidates:
                    raise DataIntegrityError("SELL references an unavailable original purchase")
                if (
                    trade.holding_period_start is not None
                    and trade.holding_period_start > origin.ts
                ):
                    raise DataIntegrityError("SELL holding-period evidence disagrees with purchase")
                selected = (origin,)
            elif trade.holding_period_start is not None:
                selected = tuple(buy for buy in candidates if buy.ts == trade.holding_period_start)
                if len(selected) > 1:
                    raise DataIntegrityError("SELL original purchase is ambiguous; supply its ID")
            else:
                selected = candidates
            remaining = trade.qty
            for buy in selected:
                disposed = min(remaining, inventory[buy.trade_id])
                inventory[buy.trade_id] -= disposed
                remaining -= disposed
                if remaining == 0:
                    break
            if selected and remaining:
                raise DataIntegrityError("SELL exceeds verified original-purchase inventory")
            if trade.realized_loss > 0:
                result[trade.trade_id] = inventory.copy()
        return result

    @staticmethod
    def _adjustment(
        loss: TradeRecord,
        replacement: TradeRecord,
        matched: int,
        disallowed: Decimal,
        statuses: dict[str, TaxStatus],
        acquired_at: datetime | None = None,
    ) -> WashAdjustment:
        """CMP-01/CMP-02: preserve exact basis and tack the old holding duration."""
        if loss.holding_period_start is None:
            raise DataIntegrityError("Loss sale lacks holding-period metadata")
        permanent = statuses[replacement.account_id] in (TaxStatus.IRA, TaxStatus.ROTH)
        with localcontext() as context:
            context.prec = 80
            proceeds = loss.price * matched
            cost_basis = proceeds + disallowed
            adjusted = None if permanent else replacement.price * matched + disallowed
        held_days = (trade_day(loss.ts) - trade_day(loss.holding_period_start)).days
        tacked_start = (
            replacement.ts.astimezone(_NEW_YORK) - timedelta(days=held_days)
        ).astimezone(UTC)
        return WashAdjustment(
            loss_trade_id=loss.trade_id,
            replacement_trade_id=replacement.trade_id,
            loss_account_id=loss.account_id,
            replacement_account_id=replacement.account_id,
            symbol=loss.symbol,
            qty=matched,
            sale_date=trade_day(loss.ts),
            acquired_date=trade_day(
                loss.holding_period_start if acquired_at is None else acquired_at
            ),
            proceeds=proceeds,
            cost_basis=cost_basis,
            disallowed_loss=disallowed,
            adjusted_basis=adjusted,
            holding_period_start=tacked_start,
            permanent_loss=permanent,
        )

    @staticmethod
    def form_8949_rows(adjustments: tuple[WashAdjustment, ...]) -> tuple[Form8949Row, ...]:
        """CMP-02: export disjoint matched slices, never duplicate a whole sale.

        Unmatched loss shares require their separate broker-1099-B rows. These
        reconciliation estimates do not replace the broker filing record.
        """
        # VERIFY: https://www.irs.gov/instructions/i8949
        try:
            if not isinstance(adjustments, tuple):
                raise DataIntegrityError("Form 8949 evidence must be an immutable tuple")
            checked = tuple(WashAdjustment.model_validate(row) for row in adjustments)
            pairs = {(row.loss_trade_id, row.replacement_trade_id) for row in checked}
            if len(pairs) != len(checked):
                raise DataIntegrityError("Form 8949 evidence repeats a loss/replacement slice")
            with localcontext() as context:
                context.prec = 80
                return tuple(
                    Form8949Row(
                        account_id=row.loss_account_id,
                        loss_trade_id=row.loss_trade_id,
                        description=f"{row.qty} {row.symbol}",
                        date_acquired=row.acquired_date,
                        date_sold=row.sale_date,
                        proceeds=row.proceeds,
                        cost_basis=row.cost_basis,
                        adjustment=row.disallowed_loss,
                        gain_or_loss=row.proceeds - row.cost_basis + row.disallowed_loss,
                    )
                    for row in checked
                )
        except DataIntegrityError:
            raise
        except Exception as exc:
            raise DataIntegrityError("Cannot verify Form 8949 wash-sale evidence") from exc
