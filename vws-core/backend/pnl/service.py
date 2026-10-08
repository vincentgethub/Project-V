"""PL-01..06: host EOD producer, backfill and account-bound private reports."""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import pages
from backend.agents.orchestrator import JobCounts
from backend.core.database import CashFlow, SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import PortfolioSnapshot
from backend.funding.models import EXTERNAL_TYPES, Activity
from backend.pnl.history import EquityHistory
from backend.pnl.models import MAX_PNL_SESSIONS, DayInput, build_day
from backend.pnl.stats import Window, statistics
from backend.pnl.storage import read_days, record_day
from backend.tax.lots import trade_day
from backend.tax.models import NOTICE, SIMULATED
from backend.tax.reports import annual
from backend.tax.service import TaxService


class HistorySource(Protocol):
    async def __call__(self, start: date, end: date) -> EquityHistory: ...


class AccountingReports:
    def __init__(
        self,
        tax: TaxService,
        calendar: MarketCalendar,
        delay_minutes: int,
        history: HistorySource,
        spy: Callable[[date, date], Awaitable[tuple[tuple[date, Decimal], ...]]],
    ) -> None:
        if type(delay_minutes) is not int or not 0 <= delay_minutes <= 120:
            raise DataIntegrityError("PL-01: close delay differs from the registered schedule")
        self.tax, self.state, self.calendar = tax, tax.state, calendar
        self.delay, self.history, self.spy = delay_minutes, history, spy
        self._lock = asyncio.Lock()

    def _session(self, day: date, instant: datetime | None = None) -> date:
        if self.calendar.is_session(day):
            if instant is None or instant < self.calendar.session_close(day):
                return day
            return self.calendar.add_sessions(day, 1)
        for _ in range(31):
            day += timedelta(days=1)
            if self.calendar.is_session(day):
                return day
        raise DataIntegrityError("PL-01: no verified session follows the posting")

    def _cash_events(self) -> tuple[Activity, ...]:
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            rows = tuple(
                session.scalars(
                    select(CashFlow)
                    .where(
                        CashFlow.account_id == self.tax.account_id,
                        CashFlow.env == self.tax.env,
                    )
                    .order_by(CashFlow.seq)
                )
            )
        return tuple(Activity.from_payload(row.payload) for row in rows)

    async def capture(self) -> JobCounts:
        """Backfill every missing completed session; a missing price stays unknown.

        Historical cash is reconstructed backwards from the verified current cash
        and captured flows/fills. Those rows are COMPUTED, with modeled fees made
        explicit. Never label inferred cash/position values as broker observations.
        """
        async with self._lock:
            try:
                await self.tax.sync(force=True)
                now = self.state.clock.now()
                end = self.calendar.last_completed_session(now - timedelta(minutes=self.delay))
                book = await asyncio.to_thread(self.tax.book)
                incomes = await asyncio.to_thread(self.tax.incomes)
                flows = await asyncio.to_thread(self._cash_events)
                snapshot = PortfolioSnapshot.model_validate(await self.tax.snapshot())
                now = self.state.clock.now()
                if snapshot.account_id != self.tax.account_id or not timedelta(
                    0
                ) <= now - snapshot.as_of <= timedelta(seconds=30):
                    raise DataIntegrityError("PL-04: current equity/cash is stale or unbound")
                dates = [
                    trade_day(fill.ts)
                    for fill in book.fills
                    if fill.account_id == self.tax.account_id
                ]
                dates.extend(row.date for row in flows)
                current = await asyncio.to_thread(
                    read_days, self.state.ledger, self.tax.account_id, self.tax.env
                )
                start = min(dates) if dates else end
                if current:
                    start = min(
                        start, self.calendar.previous_sessions(current[0].observation.session, 1)[0]
                    )
                start = self._session(start)
                if start > end:
                    return JobCounts(counts={"pnl_completed_sessions": 0})
                now = self.state.clock.now()
                try:
                    evidence = EquityHistory.model_validate(await self.history(start, end))
                    now = self.state.clock.now()
                    if (evidence.account_id, evidence.env) != (
                        self.tax.account_id,
                        self.tax.env,
                    ) or not timedelta(0) <= now - evidence.as_of <= timedelta(seconds=30):
                        raise DataIntegrityError("PL-04: historical equity account/time differs")
                    equity = {row.session: row.equity for row in evidence.closes}
                    provenance = evidence.sha256
                except Exception:
                    # Exact current and stored observations are a bounded fallback,
                    # never invented intervening closes or a flat-price assumption.
                    now = self.state.clock.now()
                    equity = {row.observation.session: row.observation.equity for row in current}
                    if end == self.calendar.last_completed_session(
                        now
                    ) and not self.calendar.is_open(now):
                        equity[end] = snapshot.equity
                    provenance = hashlib.sha256(
                        str(snapshot.model_dump(mode="json")).encode()
                    ).hexdigest()
                changes: dict[date, Decimal] = defaultdict(Decimal)
                external: dict[date, Decimal] = defaultdict(Decimal)
                realized: dict[date, Decimal] = defaultdict(Decimal)
                dividends: dict[date, Decimal] = defaultdict(Decimal)
                interest: dict[date, Decimal] = defaultdict(Decimal)
                charged: dict[date, Decimal] = defaultdict(Decimal)
                fill_fees: dict[date, Decimal] = defaultdict(Decimal)
                actual_fees: dict[date, Decimal] = defaultdict(Decimal)
                with localcontext() as precision:
                    precision.prec = 80
                    for fill in book.fills:
                        if fill.account_id != self.tax.account_id:
                            continue
                        day = self._session(trade_day(fill.ts), fill.ts)
                        changes[day] += (
                            -fill.qty * fill.price - fill.fees
                            if fill.side.value == "BUY"
                            else fill.qty * fill.price - fill.fees
                        )
                        charged[day] += fill.fees
                        fill_fees[day] += fill.fees
                    for row in flows:
                        day = self._session(row.date, row.occurred_at)
                        changes[day] += row.amount
                        if row.type in EXTERNAL_TYPES:
                            external[day] += row.amount
                    for sale in book.sales:
                        if sale.account_id == self.tax.account_id:
                            realized[self._session(trade_day(sale.sold_at), sale.sold_at)] += (
                                sale.realized_before_wash
                            )
                    for income in incomes:
                        if income.account_id != self.tax.account_id:
                            continue
                        day = self._session(income.date)
                        if income.type.startswith("DIV"):
                            dividends[day] += income.amount
                        elif income.type.startswith("INT"):
                            interest[day] += income.amount
                        elif income.type == "FEE":
                            if income.amount > 0:
                                raise DataIntegrityError(
                                    "CM-04: positive fee adjustment attribution is UNVERIFIED"
                                )
                            actual_fees[day] += abs(income.amount)
                    for day, amount in actual_fees.items():
                        relevant = tuple(
                            fill
                            for fill in book.fills
                            if fill.account_id == self.tax.account_id
                            and self._session(trade_day(fill.ts), fill.ts) == day
                        )
                        if any(fill.fee_source == "MODELED" for fill in relevant):
                            raise DataIntegrityError(
                                "CM-04/TX-03: actual fee attribution is UNVERIFIED; model and broker charges cannot be combined"
                            )
                        if fill_fees[day] > amount:
                            raise DataIntegrityError(
                                "CM-04: attributed fill fees exceed actual fee charges"
                            )
                        # FEE activities already changed cash. Undo fees embedded
                        # in gross trade projections; count the broker total once.
                        changes[day] += fill_fees[day]
                        charged[day] = amount
                    if (end - start).days > MAX_PNL_SESSIONS * 2:
                        raise DataIntegrityError("PL-01: requested backfill exceeds its bound")
                    sessions = tuple(
                        start + timedelta(days=offset)
                        for offset in range((end - start).days + 1)
                        if self.calendar.is_session(start + timedelta(days=offset))
                    )
                    # Every intervening session is required; UNVERIFIED is not a
                    # zero return. Zero-equity pre-funding points supply a baseline.
                    if any(day not in equity for day in sessions):
                        raise DataIntegrityError("PL-01: missing closes cannot be backfilled")
                    cash = {
                        day: snapshot.cash
                        - sum(
                            (amount for stamp, amount in changes.items() if stamp > day), Decimal(0)
                        )
                        for day in sessions
                    }
                    created = 0
                    previous: Decimal | None = None
                    for day in sessions:
                        end_equity = equity[day]
                        if previous is None:
                            known = next(
                                (
                                    row.observation.equity_start
                                    for row in current
                                    if row.observation.session == day
                                ),
                                None,
                            )
                            if known is not None:
                                previous = known
                            elif (
                                end_equity > 0 and external[day] > 0 and external[day] == end_equity
                            ):
                                previous = Decimal(0)
                        if end_equity <= 0 or previous is None:
                            previous = end_equity
                            continue
                        if cash[day] < 0 or end_equity - cash[day] < 0:
                            raise DataIntegrityError(
                                "PL-01: reconstructed cash/long holdings contradict"
                            )
                        daily = build_day(
                            DayInput(
                                account_id=self.tax.account_id,
                                env=self.tax.env,
                                session=day,
                                as_of=now,
                                equity_start=previous,
                                equity=end_equity,
                                cash=cash[day],
                                long_market_value=end_equity - cash[day],
                                external_flows=external[day],
                                realized=realized[day],
                                dividends=dividends[day],
                                interest=interest[day],
                                fees=charged[day],
                                source="COMPUTED",
                                provenance_sha256=provenance,
                            )
                        )
                        await asyncio.to_thread(record_day, self.state.ledger, daily)
                        previous = end_equity
                        created += 1
                self.state.ledger.append(
                    SecurityEvent,
                    kind="PNL_CAPTURED",
                    detail={
                        "account_id": self.tax.account_id,
                        "cohort": self.tax.env,
                        "through": end.isoformat(),
                        "days": created,
                        "source": "COMPUTED",
                        "modeled_fees": any(row.fee_source == "MODELED" for row in book.fills),
                        "opening_baseline": sessions[0].isoformat(),
                    },
                )
                return JobCounts(counts={"pnl_sessions_recorded": created})
            except Exception:
                self.state.escalate(SystemState.HALTED, "PL-01: account P&L backfill is UNVERIFIED")
                raise DataIntegrityError("PL-01: P&L capture failed; entries halted") from None

    def _money(self, amount: Decimal) -> str:
        return "$•••" if self.tax.settings.telegram_mask_amounts else f"${amount:+,.2f}"

    async def pnl(self, argument: str) -> tuple[str, ...]:
        if argument.strip() not in {"", "today", "week", "month", "ytd"}:
            return ("Use /pnl today|week|month|ytd.",)
        window = cast(Window, argument.strip() or "today")
        days = await asyncio.to_thread(
            read_days, self.state.ledger, self.tax.account_id, self.tax.env
        )
        if not days:
            return (
                f"{self.tax.env} · P&L UNVERIFIED: no completed account series. These are not tax numbers.",
            )
        first = self.calendar.previous_sessions(days[0].observation.session, 1)[0]
        try:
            spy = await self.spy(first, days[-1].observation.session)
        except Exception:
            spy = None
        result = statistics(days, window, self.calendar, spy_closes=spy)
        benchmark = (
            "UNVERIFIED" if result.spy_price_only is None else f"{result.spy_price_only:.2%}"
        )
        return pages(
            f"{self.tax.env} · {window} · {result.start} to {result.end} ({result.sessions} sessions)\n"
            f"P&L {self._money(result.total_pnl)} · average {self._money(result.average_dollars)}/day ({result.average_return:.2%})\n"
            f"TWR {result.twr:.2%} · SPY {benchmark} (price only)\n"
            f"Up/down/flat {result.up}/{result.down}/{result.flat} · best {result.best_session}: {self._money(result.best_pnl)} · worst {result.worst_session}: {self._money(result.worst_pnl)}\n"
            f"Max drawdown {result.max_drawdown:.2%}: {result.drawdown_peak_session} to {result.drawdown_trough_session}\n"
            "Cash/holdings backfill is COMPUTED; modeled fees are estimates. External flows are excluded. These are not tax numbers."
        )

    async def tax_summary(self, argument: str = "") -> tuple[str, ...]:
        if argument.strip():
            return ("Use /tax for YTD totals.\n" + NOTICE,)
        try:
            _after, complete = await asyncio.to_thread(self.tax._checkpoint)
            if not complete:
                raise DataIntegrityError("TX-02: complete history unavailable")
            book = await asyncio.to_thread(self.tax.book)
            income = await asyncio.to_thread(self.tax.incomes)
            today = trade_day(self.state.clock.now())
            result = annual(
                book,
                income,
                self.tax.settings.tax_profile,
                today.year,
                today,
                account=self.tax.account_id,
                simulate=self.tax.env == "PAPER",
            )
            estimate = (
                "Rates unset: totals only."
                if result.set_aside_estimate is None
                else "Set-aside estimate " + self._money(result.set_aside_estimate)
            )
            label = SIMULATED if self.tax.env == "PAPER" else "LIVE · estimate"
            return pages(
                f"{label} · YTD {today.year}\nST {self._money(result.net_st)} · LT {self._money(result.net_lt)}\n"
                f"Wash-disallowed {self._money(result.wash_disallowed)} (permanent {self._money(result.permanent_disallowed)})\n"
                f"Dividends {self._money(result.dividends)} (unclassified until 1099-DIV) · interest {self._money(result.interest)}\n{estimate}\n"
                "A loss sale remains open to subsequent 30-day replacements; other-account records depend on your imports.\n"
                + NOTICE
            )
        except Exception:
            return (
                f"{self.tax.env} · Tax totals UNVERIFIED: complete account evidence is unavailable.\n"
                + NOTICE,
            )

    async def digest_line(self) -> str:
        days = await asyncio.to_thread(
            read_days, self.state.ledger, self.tax.account_id, self.tax.env
        )
        if not days:
            return f"{self.tax.env} · P&L UNVERIFIED: no completed series."
        today, week, month, ytd = tuple(
            statistics(days, window, self.calendar) for window in ("today", "week", "month", "ytd")
        )
        try:
            spy = await self.spy(self.calendar.previous_sessions(ytd.start, 1)[0], ytd.end)
            ytd = statistics(days, "ytd", self.calendar, spy_closes=spy)
        except Exception:
            ytd = statistics(days, "ytd", self.calendar)
        benchmark = "UNVERIFIED" if ytd.spy_price_only is None else f"{ytd.spy_price_only:.1%}"
        return (
            f"{self.tax.env} · Today {self._money(today.total_pnl)} ({today.twr:.2%}) · 7-day avg {self._money(week.average_dollars)}/day · "
            f"30-day avg {self._money(month.average_dollars)}/day · YTD {ytd.twr:.1%} vs SPY {benchmark} (price only). P&L is not tax; backfill COMPUTED."
        )
