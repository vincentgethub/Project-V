"""FN/TX/H: complete activity capture produces fresh, account-bound research history."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.orchestrator import JobCounts
from backend.core.config import MANUAL_CSV_DISABLED_MESSAGE, Settings
from backend.core.database import CashFlow, PortfolioState, SecurityEvent, TaxEvent
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.fill_polling import ObservedFill
from backend.domain.compliance_models import TaxLot, TaxStatus
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import PortfolioSnapshot
from backend.evaluation.costs import FeeSchedule
from backend.funding.activities import ActivityBatch
from backend.funding.models import CORPORATE_TYPES, EXTERNAL_TYPES, Activity
from backend.funding.tracker import FundingTracker
from backend.ops.account_context import AccountContext
from backend.tax.accounting import TaxBook, build_tax_book
from backend.tax.imports import import_fills, load_accounts
from backend.tax.models import NOTICE, Environment, TaxAccount, TaxFill, TaxIncome
from backend.tax.storage import append_evidence, read_fills
from backend.tax.tax_tracker import TaxTracker


class ActivitiesSource(Protocol):
    async def read_activities(
        self, after: datetime | None, until: datetime, schedule: FeeSchedule
    ) -> ActivityBatch: ...


def managed_accounts(
    project: Path, account_id: str, broker_source: str = "ALPACA"
) -> tuple[TaxAccount, ...]:
    if broker_source != "ALPACA":
        raise DataIntegrityError(MANUAL_CSV_DISABLED_MESSAGE)
    owners = load_accounts(project / "config/accounts.yaml").accounts
    managed = tuple(row for row in owners if row.source == "ALPACA")
    if managed and (len(managed) != 1 or managed[0].id != account_id):
        raise DataIntegrityError("TX-01: managed account differs from the verified broker account")
    if not managed:
        owners = (
            TaxAccount(
                id=account_id,
                name="Managed Alpaca brokerage",
                tax_status=TaxStatus.TAXABLE,
                source="ALPACA",
            ),
            *owners,
        )
    return owners


class TaxService:
    def __init__(
        self,
        project: Path,
        state: SystemStateStore,
        settings: Settings,
        account_id: str,
        registry: InstrumentRegistry,
        activities: ActivitiesSource,
        snapshot: Callable[[], Awaitable[PortfolioSnapshot]],
        notify: Callable[[str, bool], Awaitable[None]],
        schedule: FeeSchedule,
        *,
        buying_power: Callable[[], Decimal | None] | None = None,
        observe_fill: Callable[[ObservedFill], object] | None = None,
        prepare_fills: Callable[[tuple[str, ...]], Awaitable[None]] | None = None,
    ) -> None:
        self.project, self.state, self.account_id = project, state, account_id
        self.settings, self.registry = (
            Settings.validated_copy(settings),
            InstrumentRegistry.validated_copy(registry),
        )
        if self.settings.broker_state_source != "ALPACA":
            raise DataIntegrityError(MANUAL_CSV_DISABLED_MESSAGE)
        self.env: Environment = "PAPER" if settings.paper_trading else "LIVE"
        self.activities, self.snapshot, self.notify = activities, snapshot, notify
        self.schedule = FeeSchedule.model_validate(schedule)
        self.buying_power = buying_power or (lambda: None)
        self.observe_fill = observe_fill
        self.prepare_fills = prepare_fills
        self.funding = FundingTracker(state, account_id, self.env)
        self._lock = asyncio.Lock()
        self._fresh: datetime | None = None

    def _checkpoint(self) -> tuple[datetime | None, bool]:
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            rows = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind.in_(
                            ("ACCOUNT_ACTIVITIES_CAPTURED", "TAX_FULL_HISTORY_CAPTURED")
                        ),
                        SecurityEvent.detail["account_id"].as_string() == self.account_id,
                        SecurityEvent.detail["cohort"].as_string() == self.env,
                    )
                    .order_by(SecurityEvent.seq)
                )
            )
        full = any(row.kind == "TAX_FULL_HISTORY_CAPTURED" for row in rows)
        ends = tuple(datetime.fromisoformat(row.detail["until"]) for row in rows)
        if any(end > row.ts for end, row in zip(ends, rows, strict=True)):
            raise DataIntegrityError("FN-02: activity checkpoint is in the future")
        return (max(ends) if ends and full else None), full

    def _opening_baseline(self, batch: ActivityBatch) -> None:
        """Do not silently reset baselines inherited from an older host stage.

        A flow posted while prior managed marks existed must have an explicit
        scaled mark. Date-only ambiguous legacy postings require audited review.
        Older flows precede the host's declared opening snapshot and are included.
        """
        with Session(self.state.engine) as session:
            marks = tuple(
                session.scalars(
                    select(PortfolioState)
                    .where(
                        PortfolioState.account_id == self.account_id,
                    )
                    .order_by(PortfolioState.seq)
                )
            )
        if not marks:
            return
        for row in batch.activities:
            if row.type not in EXTERNAL_TYPES:
                continue
            if (
                row.date < marks[0].as_of.date()
                or row.occurred_at is not None
                and row.occurred_at < marks[0].as_of
            ):
                continue
            if not any(
                mark.cash_flow_amount == row.amount
                and mark.cash_flow_at == row.occurred_at
                and row.occurred_at is not None
                for mark in marks
            ):
                raise DataIntegrityError(
                    "FN-03: legacy baselines lack proof of scaling this external flow; audited reconciliation required"
                )

    def _record(self, batch: ActivityBatch, initial: bool) -> JobCounts:
        if self.settings.broker_state_source != "ALPACA":
            raise DataIntegrityError(MANUAL_CSV_DISABLED_MESSAGE)
        checked = ActivityBatch.model_validate(batch)
        if (checked.account_id, checked.env) != (self.account_id, self.env):
            raise DataIntegrityError("FN-02: activity batch belongs to another account")
        recorded = 0
        for row in checked.activities:
            if row.fill is not None:
                fill = row.fill
                append_evidence(
                    self.state.ledger,
                    fill.account_id,
                    fill.env,
                    "FILL",
                    fill.activity_id,
                    fill.payload_sha256,
                    fill.model_dump(mode="json"),
                )
                if self.observe_fill is not None:
                    self.observe_fill(
                        ObservedFill(
                            account_id=fill.account_id,
                            broker_fill_id=fill.activity_id,
                            broker_order_id=cast(UUID, row.broker_order_id),
                            symbol=fill.symbol,
                            side=fill.side,
                            qty=fill.qty,
                            price=fill.price,
                            filled_at=fill.ts,
                        )
                    )
            else:
                _record, fresh = self.funding.record(row, historical_inclusion=initial)
                recorded += int(fresh)
                if row.type.startswith(("DIV", "INT")) or row.type == "FEE":
                    income = TaxIncome(
                        activity_id=row.activity_id,
                        account_id=row.account_id,
                        env=row.env,
                        type=row.type,
                        date=row.date,
                        amount=row.amount,
                    )
                    append_evidence(
                        self.state.ledger,
                        income.account_id,
                        income.env,
                        "INCOME",
                        income.activity_id,
                        row.payload_sha256,
                        income.model_dump(mode="json"),
                    )
                if row.type in CORPORATE_TYPES:
                    append_evidence(
                        self.state.ledger,
                        row.account_id,
                        row.env,
                        "CORPORATE_ACTION",
                        row.activity_id,
                        row.payload_sha256,
                        row.model_dump(mode="json"),
                    )
        if checked.complete_history:
            self.state.ledger.append(
                SecurityEvent,
                kind="TAX_FULL_HISTORY_CAPTURED",
                detail={
                    "account_id": self.account_id,
                    "cohort": self.env,
                    "until": checked.as_of.isoformat(),
                    "activities": len(checked.activities),
                    "source": "ALL_PAGINATED_BROKER_ACTIVITIES",
                },
            )
        self.state.ledger.append(
            SecurityEvent,
            kind="ACCOUNT_ACTIVITIES_CAPTURED",
            detail={
                "account_id": self.account_id,
                "cohort": self.env,
                "until": checked.as_of.isoformat(),
                "activities": len(checked.activities),
            },
        )
        return JobCounts(
            counts={
                "activities_observed": len(checked.activities),
                "cash_activities_recorded": recorded,
                "fills_observed": sum(row.fill is not None for row in checked.activities),
            }
        )

    def book(self) -> TaxBook:
        owners = managed_accounts(self.project, self.account_id, self.settings.broker_state_source)
        fills: list[TaxFill] = []
        for owner in owners:
            if owner.source == "CSV":
                if owner.fills_csv is None:
                    raise DataIntegrityError("TX-01: external fills path unavailable")
                path = Path(owner.fills_csv)
                source = path if path.is_absolute() else self.project / path
                import_fills(self.state.ledger, owner, source, self.env)
            fills.extend(
                read_fills(self.state.ledger, owner.id, self.env, csv=owner.source == "CSV")
            )
        return build_tax_book(tuple(fills), owners, self.registry, self.env)

    def incomes(self) -> tuple[TaxIncome, ...]:
        self.state.ledger.verify_chain()
        owners = {
            row.id
            for row in managed_accounts(
                self.project, self.account_id, self.settings.broker_state_source
            )
        }
        with Session(self.state.engine) as session:
            records = tuple(
                session.scalars(
                    select(TaxEvent)
                    .where(
                        TaxEvent.kind == "INCOME",
                        TaxEvent.env == self.env,
                        TaxEvent.account_id.in_(owners),
                    )
                    .order_by(TaxEvent.seq)
                )
            )
        current = {
            (row.account_id, row.source_id): TaxIncome.from_payload(row.payload) for row in records
        }
        return tuple(
            sorted(current.values(), key=lambda row: (row.date, row.account_id, row.activity_id))
        )

    def _publish(
        self, book: TaxBook, snapshot: PortfolioSnapshot, until: datetime
    ) -> AccountContext:
        book = TaxBook.model_validate(book)
        if (
            book.env != self.env
            or self.env != ("PAPER" if self.settings.paper_trading else "LIVE")
            or self.account_id not in {row.id for row in book.accounts}
        ):
            raise DataIntegrityError("TX/H: accounting environment or account differs")
        verified = PortfolioSnapshot.model_validate(snapshot)
        as_of = min(verified.as_of, until)
        if verified.account_id != self.account_id or not timedelta(
            0
        ) <= self.state.clock.now() - as_of <= timedelta(seconds=30):
            raise DataIntegrityError("TX/H: current broker/history evidence is stale or unbound")
        quantities: dict[str, int] = defaultdict(int)
        for row in book.lots:
            if row.account_id == self.account_id:
                quantities[row.symbol] += row.qty
        if dict(quantities) != {
            symbol: position.qty for symbol, position in verified.positions.items() if position.qty
        }:
            raise DataIntegrityError(
                "TX-02: tax lots differ from broker shares; missing history or corporate action requires review"
            )
        context = AccountContext(
            account_id=self.account_id,
            cohort=self.env,
            as_of=as_of,
            lots=book.compliance_lots(),
            history=book.history,
            accounts=tuple(row.ownership for row in book.accounts),
        )
        self.state.ledger.append(
            SecurityEvent, kind="ACCOUNT_RESEARCH_CONTEXT", detail=context.model_dump(mode="json")
        )
        self.state.ledger.append(
            SecurityEvent,
            kind="J_ACCOUNTING_VERIFIED",
            detail={
                "account_id": self.account_id,
                "cohort": self.env,
                "as_of": as_of.isoformat(),
                "book_sha256": book.sha256,
                "fills": len(book.fills),
                "lots": len(book.lots),
            },
        )
        return context

    async def _pending_notices(self, buying_power: Decimal | None) -> None:
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            recorded = tuple(
                session.scalars(
                    select(CashFlow)
                    .where(CashFlow.account_id == self.account_id, CashFlow.env == self.env)
                    .order_by(CashFlow.seq)
                )
            )
            delivered = {
                row.detail["activity_id"]
                for row in session.scalars(
                    select(SecurityEvent).where(
                        SecurityEvent.kind == "FN_ACTIVITY_NOTIFIED",
                        SecurityEvent.detail["account_id"].as_string() == self.account_id,
                        SecurityEvent.detail["cohort"].as_string() == self.env,
                    )
                )
            }
        pending = tuple(row for row in recorded if row.activity_id not in delivered)
        for row in pending:
            activity = Activity.from_payload(row.payload)
            text, urgent = self.funding.message(
                activity, buying_power, mask=self.settings.telegram_mask_amounts
            )
            await self.notify(text, urgent)
            self.state.ledger.append(
                SecurityEvent,
                kind="FN_ACTIVITY_NOTIFIED",
                detail={
                    "account_id": self.account_id,
                    "cohort": self.env,
                    "cash_flow_id": str(row.id),
                    "activity_id": row.activity_id,
                },
            )

    async def sync(self, *, force: bool = False) -> JobCounts:
        async with self._lock:
            try:
                if self.settings.broker_state_source != "ALPACA":
                    raise DataIntegrityError(MANUAL_CSV_DISABLED_MESSAGE)
                now = self.state.clock.now()
                if (
                    not force
                    and self._fresh is not None
                    and timedelta(0) <= now - self._fresh < timedelta(seconds=10)
                ):
                    return JobCounts(counts={"account_context_cached": 1})
                after, complete = await asyncio.to_thread(self._checkpoint)
                batch = ActivityBatch.model_validate(
                    await self.activities.read_activities(
                        None if after is None else after - timedelta(seconds=1), now, self.schedule
                    )
                )
                if not complete and not batch.complete_history:
                    raise DataIntegrityError("TX-02: complete opening history is required")
                await self._withdrawal_notices(batch)
                if not complete:
                    await asyncio.to_thread(self._opening_baseline, batch)
                    # Activity list has already proved which postings precede
                    # the first bound broker snapshot; current equity is explicit.
                    await self.snapshot()
                if self.prepare_fills is not None:
                    symbols = tuple(
                        sorted(
                            {row.fill.symbol for row in batch.activities if row.fill is not None}
                        )
                    )
                    if symbols:
                        await self.prepare_fills(symbols)
                counts = await asyncio.to_thread(self._record, batch, not complete)
                snapshot = PortfolioSnapshot.model_validate(await self.snapshot())
                await self._pending_notices(self.buying_power())
                book = await asyncio.to_thread(self.book)
                context = await asyncio.to_thread(self._publish, book, snapshot, batch.as_of)
                # TX owner profile: every new recorded sale prompts/checks marked
                # external lots, including 401(k), without inferring its treatment.
                await self._sale_reviews(book)
                self._fresh = context.as_of
                return counts
            except Exception:
                self.state.escalate(
                    SystemState.HALTED,
                    "Stage J account/tax history is UNVERIFIED; reconcile before entries",
                )
                raise DataIntegrityError("FN/TX: accounting unavailable; entries halted") from None

    async def _withdrawal_notices(self, batch: ActivityBatch) -> None:
        """Urgent source-verified withdrawals still alert if baseline/tax math fails."""
        checked = ActivityBatch.model_validate(batch)
        if (checked.account_id, checked.env) != (self.account_id, self.env):
            raise DataIntegrityError("FN-04: withdrawal source is not bound")
        with Session(self.state.engine) as session:
            delivered = {
                row.detail["activity_id"]
                for row in session.scalars(
                    select(SecurityEvent).where(
                        SecurityEvent.kind == "FN_ACTIVITY_NOTIFIED",
                        SecurityEvent.detail["account_id"].as_string() == self.account_id,
                        SecurityEvent.detail["cohort"].as_string() == self.env,
                    )
                )
            }
        for row in checked.activities:
            if (
                row.type == "CSW" or row.type == "JNLC" and row.amount < 0
            ) and row.activity_id not in delivered:
                text, urgent = self.funding.message(
                    row, None, mask=self.settings.telegram_mask_amounts
                )
                await self.notify(text, urgent)
                self.state.ledger.append(
                    SecurityEvent,
                    kind="FN_ACTIVITY_NOTIFIED",
                    detail={
                        "account_id": self.account_id,
                        "cohort": self.env,
                        "activity_id": row.activity_id,
                        "payload_sha256": row.payload_sha256,
                        "source_verified_before_baseline_reconciliation": True,
                    },
                )

    async def _sale_reviews(self, book: TaxBook) -> None:
        with Session(self.state.engine) as session:
            reviewed = {
                row.detail["sale_id"]
                for row in session.scalars(
                    select(SecurityEvent).where(
                        SecurityEvent.kind == "TX_SALE_REVIEW",
                        SecurityEvent.detail["account_id"].as_string() == self.account_id,
                        SecurityEvent.detail["cohort"].as_string() == self.env,
                    )
                )
            }
            marked_records = tuple(
                session.scalars(
                    select(TaxEvent)
                    .where(TaxEvent.kind == "MARKED_LOT", TaxEvent.env == self.env)
                    .order_by(TaxEvent.seq)
                )
            )
        marked: dict[tuple[str, str], TaxLot] = {}
        for row in marked_records:
            # Typed decoder is shared with ledger verification.
            raw = dict(row.payload)
            from datetime import date

            raw["acquired_at"] = datetime.fromisoformat(raw["acquired_at"])
            raw["holding_period_start"] = (
                None
                if raw["holding_period_start"] is None
                else datetime.fromisoformat(raw["holding_period_start"])
            )
            raw["funding_settlement_date"] = (
                None
                if raw["funding_settlement_date"] is None
                else date.fromisoformat(raw["funding_settlement_date"])
            )
            marked[(row.account_id, row.source_id)] = TaxLot.model_validate(raw)
        tracker = TaxTracker(self.settings, self.registry)
        for execution in book.fills:
            if (
                execution.account_id == self.account_id
                and execution.side.value == "SELL"
                and str(execution.fill_id) not in reviewed
            ):
                reviews = tuple(
                    tracker.review_sale(sale, tuple(marked.values()))
                    for sale in book.history
                    if sale.execution_id == execution.fill_id
                )
                prompts = tuple(
                    dict.fromkeys(prompt for review in reviews for prompt in review.prompts)
                )
                await self.notify(
                    f"{self.env} · Sale recorded for {execution.symbol}. "
                    + " · ".join(prompts)
                    + "\n"
                    + NOTICE,
                    False,
                )
                self.state.ledger.append(
                    SecurityEvent,
                    kind="TX_SALE_REVIEW",
                    detail={
                        "account_id": self.account_id,
                        "cohort": self.env,
                        "sale_id": str(execution.fill_id),
                        "reviews": [review.model_dump(mode="json") for review in reviews],
                    },
                )
