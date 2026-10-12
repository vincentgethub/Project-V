"""OPS-02: actual read-only sources for scans, reviews and held exit warnings."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.agents.briefing import PositionView, SymbolQuote
from backend.agents.fundamentals import compute_fundamentals
from backend.agents.indicators import ema
from backend.agents.jobs import ReviewEvidence, ScanCycle
from backend.agents.news_reader import NewsAssessment, NewsReader
from backend.agents.peer_strength import (
    SECTOR_ETFS,
    NullPeerProvider,
    PeerStrength,
    calculate_peer_strength,
)
from backend.agents.position_monitor import Protection
from backend.agents.scanner import scan
from backend.agents.setup_hunter import SetupHunter
from backend.agents.swarm_runner import ResearchRequest
from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings, YamlConfig
from backend.core.database import (
    Alert,
    DataSnapshot,
    Fill,
    Order,
    SecurityEvent,
    TicketEvent,
    TradeTicket,
)
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.system_state import SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.boundary import ReadBoundary
from backend.data.corporate_actions import CorporateActionsProvider
from backend.data.data_layer import AsyncAlpacaMarketData, BatchBars, _eligible_session
from backend.data.earnings import EarningsProvider
from backend.data.earnings_reports import EarningsReport
from backend.data.history import HistorySeries, load_history
from backend.data.market_calendar import MarketCalendar
from backend.data.news import NewsProvider
from backend.data.sec_edgar import SecEdgarProvider, SecPayload
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, MarketContext, MarketStatus
from backend.evaluation.ledger_source import WeeklyHistory
from backend.evaluation.weekly import ReportContext
from backend.execution.exit_variants import (
    HeldEntry,
    HeldExitObservation,
    HeldQuoteObservation,
    observe_held_exit,
)
from backend.notifications.callbacks import FreshInputs
from backend.ops.account_context import AccountContext


class AccountContextSource(Protocol):
    def read(self) -> AccountContext: ...


class ConnectedDeskSource:
    def __init__(
        self,
        project: Path,
        settings: Settings,
        config: YamlConfig,
        state: SystemStateStore,
        clock: Clock,
        calendar: MarketCalendar,
        registry: InstrumentRegistry,
        market: AsyncAlpacaMarketData,
        boundary: ReadBoundary,
        reader: AsyncAlpacaReader,
        hunter: SetupHunter,
        earnings: EarningsProvider,
        actions: CorporateActionsProvider,
        news: NewsProvider,
        news_reader: NewsReader,
        account_context: AccountContextSource,
        sec: SecEdgarProvider | None,
        *,
        sync_account_context: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.settings, self.config = (
            Settings.validated_copy(settings),
            YamlConfig.model_validate(config),
        )
        self.config.assert_settings_consistent(self.settings)
        if (
            state.clock is not clock
            or reader.state is not state
            or boundary.state is not state
            or hunter.cro.config.config_hash != settings.config_hash
        ):
            raise ConfigurationError(
                "Connected source requires one clock, state and defense policy"
            )
        self.project, self.state, self.clock, self.calendar, self.registry = (
            project,
            state,
            clock,
            calendar,
            registry,
        )
        self.market, self.boundary, self.reader, self.hunter = market, boundary, reader, hunter
        self.earnings, self.actions, self.news_provider, self.news_reader = (
            earnings,
            actions,
            news,
            news_reader,
        )
        self.account_context, self.sec = account_context, sec
        self.sync_account_context = sync_account_context
        self._batch: BatchBars | None = None
        self._daily_lock = asyncio.Lock()

    async def daily(self, symbols: tuple[str, ...] = ()) -> BatchBars:
        async with self._daily_lock:
            now = ensure_utc(self.clock.now())
            tail = _eligible_session(
                self.calendar, now, self.config.schedule.daily_scan_delay_minutes
            )
            benchmarks = tuple(sorted({"SPY", *SECTOR_ETFS.values()} & self.registry.symbols))
            selected = tuple(sorted(set(self.config.watchlist) | set(symbols)))
            if any(symbol not in self.registry.symbols for symbol in selected):
                raise DataIntegrityError("Connected source received an unregistered instrument")
            cached = self._batch
            if (
                cached is not None
                and cached.through == tail
                and all(
                    symbol in {row.symbol for row in cached.entries}
                    for symbol in (*selected, *benchmarks)
                )
            ):
                return cached
            # Fixed warmup for the specified 200-day average and playbook windows.
            start = self.calendar.previous_sessions(tail, 260)[0]
            today = now.astimezone(ZoneInfo("America/New_York")).date()
            actions = await self.actions.fetch(
                tuple(sorted(set(selected) | set(benchmarks))), today - timedelta(days=30), today
            )
            result = await self.market.completed_daily_evidence(
                selected, start, benchmarks=benchmarks, corporate_actions=actions
            )
            from backend.agents.indicators import atr
            from backend.core.errors import ProviderError
            from backend.data.feed_crosscheck import record as record_crosscheck

            try:
                secondary = await self.market.secondary_completed_bars(
                    tuple(sorted(set(selected) | set(benchmarks))), tail
                )
                suspect = set()
                for row in secondary:
                    primary = result.for_symbol(row.symbol)
                    value = atr(primary)[-1]
                    if value is None:
                        raise DataIntegrityError("DQ-02: primary ATR evidence unavailable")
                    check = await asyncio.to_thread(
                        record_crosscheck,
                        self.state.ledger,
                        self.calendar,
                        row.symbol,
                        primary[-1],
                        row.bars[-1],
                        value,
                    )
                    if check.status == MarketStatus.SUSPECT:
                        suspect.add(row.symbol)
                        await asyncio.to_thread(
                            self.market._status.mark_suspect,
                            row.symbol,
                            "DQ-02: three consecutive SIP/IEX cross-check warnings",
                        )
                if suspect:
                    result = BatchBars.model_validate(
                        {
                            **result.model_dump(),
                            "entries": tuple(
                                type(row).model_validate(
                                    {**row.model_dump(), "status": MarketStatus.SUSPECT}
                                )
                                if row.symbol in suspect
                                else row
                                for row in result.entries
                            ),
                        }
                    )
            except ProviderError:
                self.state.ledger.append(
                    SecurityEvent,
                    kind="FEED_CROSSCHECK_UNAVAILABLE",
                    detail={
                        "session": tail.isoformat(),
                        "reason": "secondary IEX evidence unavailable",
                    },
                )
            self._batch = BatchBars.model_validate(result)
            return self._batch

    async def filings(self, symbol: str) -> tuple[SecPayload | None, str | None]:
        if self.sec is None:
            return None, None
        from backend.core.errors import ProviderError

        try:
            identity = await self.sec.cik_for(symbol)
            payload = await self.sec.companyfacts(symbol)
            return payload, identity
        except ProviderError:
            return None, None

    async def quote(self, symbol: str) -> SymbolQuote:
        batch = await self.daily((symbol,))
        facts = await self.market.latest_market(symbol, batch)
        earnings = await self.earnings.get(symbol, ensure_utc(self.clock.now()))
        return SymbolQuote(
            symbol=symbol,
            feed="IEX",
            market=MarketContext.model_validate(
                {**facts.model_dump(), "earnings": earnings, "next_earnings_date": earnings.date}
            ),
        )

    async def held_exit_observation(
        self, entry: HeldEntry, inputs: FreshInputs
    ) -> HeldExitObservation:
        held, fresh = HeldEntry.model_validate(entry), FreshInputs.model_validate(inputs)
        if (
            held.account_id != self.boundary.account_id
            or fresh.portfolio.account_id != self.boundary.account_id
        ):
            raise DataIntegrityError("EX: held exit belongs to another account")
        batch = await self.daily((held.symbol,))
        series = next(
            (
                row
                for row in batch.entries
                if row.symbol == held.symbol
                and row.adjustment == "SPLIT"
                and row.status == MarketStatus.OK
            ),
            None,
        )
        if series is None:
            raise DataIntegrityError("EX: completed split-based held exit data unavailable")
        with Session(self.state.engine) as session:
            records = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "HELD_QUOTE_OBSERVED",
                        SecurityEvent.detail["entry_id"].as_string() == str(held.entry_id),
                    )
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
        if len(records) > 100000:
            raise DataIntegrityError("EX: held peak inventory exceeds its bound")
        peaks = tuple(
            HeldQuoteObservation.recorded(row.detail)
            for row in records
            if row.detail.get("entry_id") == str(held.entry_id)
        )
        return observe_held_exit(
            held,
            HistorySeries(symbol=held.symbol, adjustment="SPLIT", bars=series.bars),
            self.calendar,
            self.clock.now(),
            scan_delay_minutes=self.config.schedule.daily_scan_delay_minutes,
            last_trade=fresh.market.last_price
            if fresh.market.last_price_ts >= held.first_fill
            else None,
            trade_at=fresh.market.last_price_ts
            if fresh.market.last_price_ts >= held.first_fill
            else None,
            verified_peaks=peaks,
        )

    async def refresh(self, symbol: str) -> FreshInputs:
        # Unknown account history never becomes an empty, passing history.
        if self.sync_account_context is not None:
            await self.sync_account_context()
        context = await asyncio.to_thread(self.account_context.read)
        account = await self.boundary.portfolio_async(self.reader)
        quote = await self.quote(symbol)
        funds = await self.boundary.funding_async(self.reader, refresh=True)
        filings, cik = await self.filings(symbol)
        return FreshInputs(
            quote_feed="IEX",
            portfolio=account.snapshot,
            market=quote.market,
            capital=funds,
            flags=account.flags,
            lots=context.lots,
            history=context.history,
            tax_accounts=context.accounts,
            filings=filings,
            expected_cik=cik,
        )

    async def scan(self, selected: tuple[str, ...] | None = None) -> ScanCycle:
        symbols = self.config.watchlist if selected is None else selected
        if (
            not symbols
            or len(symbols) > 1000
            or any(symbol not in self.registry.symbols for symbol in symbols)
        ):
            raise DataIntegrityError("XK-09: bounded registered scan symbols required")
        if self.sync_account_context is not None:
            await self.sync_account_context()
        context = await asyncio.to_thread(self.account_context.read)
        batch = await self.daily(symbols)
        requests: list[ResearchRequest] = []
        for symbol in symbols:
            quote = await self.quote(symbol)
            account = await self.boundary.portfolio_async(self.reader)
            funds = await self.boundary.funding_async(self.reader, refresh=True)
            now = ensure_utc(self.clock.now())
            bars = batch.for_symbol(symbol)
            scanned = scan(
                symbol,
                bars,
                now=now,
                calendar=self.calendar,
                data_snapshot_hash=next(
                    row.data_sha256
                    for row in batch.entries
                    if row.symbol == symbol and row.adjustment == "SPLIT"
                ),
                market_status=batch.status_for(symbol),
                memo=self.hunter.memo,
            )
            if scanned.status.value != "OK":
                continue
            reports = await self.past_earnings(symbol, now)
            hunted = self.hunter.hunt(
                symbol,
                bars,
                account.snapshot,
                quote.market,
                now,
                earnings_reports=reports,
                spy_bars=batch.for_symbol("SPY", "ALL"),
                stock_return_bars=batch.for_symbol(symbol, "ALL"),
            )
            with Session(self.state.engine) as session:
                snapshot = session.scalar(
                    select(DataSnapshot)
                    .where(
                        DataSnapshot.symbol == symbol,
                        DataSnapshot.adjustment == "SPLIT",
                        DataSnapshot.fetched_at <= now,
                    )
                    .order_by(DataSnapshot.seq.desc())
                    .limit(1)
                )
            if snapshot is None:
                raise DataIntegrityError("Completed daily source lacks immutable SPLIT provenance")
            for drop in hunted.drops:
                if drop.filtered_candidate is not None and drop.reductions is not None:
                    from uuid import uuid5

                    from backend.agents.expiry import proposal_expiry
                    from backend.agents.indicators import atr
                    from backend.evaluation.calibrated_costs import snapshot as cost_snapshot
                    from backend.evaluation.costs import CostContext
                    from backend.evaluation.filter_shadows import NAMESPACE, FilterShadow
                    from backend.evaluation.filter_shadows import record as record_shadow
                    from backend.evaluation.provenance import EvaluationProvenance
                    from backend.ops.trading_controls import ControlScope

                    candidate = drop.filtered_candidate
                    evidence_atr = atr(bars)[-1]
                    if evidence_atr is None:
                        raise DataIntegrityError("ER-04: filter ATR unavailable")
                    dollars = sorted(bar.close * bar.volume for bar in bars[-20:])
                    scope = ControlScope(
                        account_id=account.snapshot.account_id,
                        environment="PAPER" if self.settings.paper_trading else "LIVE",
                    )
                    proof = EvaluationProvenance(
                        cohort=scope.environment,
                        expires_at=proposal_expiry(
                            now, self.settings.proposal_ttl_sessions, self.calendar
                        ),
                        yaml_hash=self.config.config_hash,
                        settings_hash=self.settings.config_hash,
                        evidence_session=bars[-1].session_date,
                        initial_equity=account.snapshot.equity,
                        cost_context=cost_snapshot(
                            self.state.ledger, scope.environment, scope=scope
                        ).context(
                            CostContext(
                                median_dollar_volume_20=(dollars[9] + dollars[10]) / 2,
                                atr14=evidence_atr,
                                policy=self.config.cm,
                            )
                        ),
                    )
                    identity = uuid5(
                        NAMESPACE,
                        f"{scope.account_id}/{scope.environment}/{snapshot.id}/{candidate.playbook}/{candidate.as_of}/{proof.yaml_hash}",
                    )
                    await asyncio.to_thread(
                        record_shadow,
                        self.state.ledger,
                        FilterShadow(
                            identity=identity,
                            scope=scope,
                            data_snapshot_id=snapshot.id,
                            candidate=candidate,
                            factors=drop.reductions,
                            provenance=proof,
                            cro_cap=drop.filtered_cro_cap,
                        ),
                    )
                self.state.ledger.append(
                    SecurityEvent,
                    kind="HUNTER_DROPPED",
                    detail={
                        "symbol": symbol,
                        "playbook": drop.playbook.value,
                        "reason": drop.reason,
                    },
                )
            requests.extend(
                ResearchRequest(
                    manual_only=selected is not None,
                    candidate=candidate,
                    data_snapshot_id=snapshot.id,
                    portfolio=account.snapshot,
                    market=quote.market,
                    capital=funds,
                    flags=account.flags,
                    lots=context.lots,
                    history=context.history,
                    tax_accounts=context.accounts,
                )
                for candidate in hunted.candidates
            )
        spy = batch.for_symbol("SPY", "ALL")
        average = ema(tuple(bar.close for bar in spy), 200)[-1]
        return ScanCycle(
            as_of=ensure_utc(self.clock.now()),
            symbols_scanned=len(symbols),
            requests=tuple(requests),
            spy_above_ema200=None if average is None else spy[-1].close > average,
        )

    async def refresh_request(self, request: ResearchRequest) -> ResearchRequest | None:
        """Refresh each proposal immediately before CRO, after a long scan batch."""
        fresh = await self.refresh(request.candidate.symbol)
        batch = await self.daily((request.candidate.symbol,))
        hunted = self.hunter.hunt(
            request.candidate.symbol,
            batch.for_symbol(request.candidate.symbol),
            fresh.portfolio,
            fresh.market,
            ensure_utc(self.clock.now()),
            earnings_reports=await self.past_earnings(
                request.candidate.symbol, ensure_utc(self.clock.now())
            ),
            spy_bars=batch.for_symbol("SPY", "ALL"),
            stock_return_bars=batch.for_symbol(request.candidate.symbol, "ALL"),
        )
        candidate = next(
            (row for row in hunted.candidates if row.playbook == request.candidate.playbook), None
        )
        if candidate is None:
            return None
        return ResearchRequest(
            manual_only=request.manual_only,
            candidate=candidate,
            data_snapshot_id=request.data_snapshot_id,
            portfolio=fresh.portfolio,
            market=fresh.market,
            capital=fresh.capital,
            flags=fresh.flags,
            lots=fresh.lots,
            history=fresh.history,
            tax_accounts=fresh.tax_accounts,
        )

    async def past_earnings(self, symbol: str, as_of: datetime) -> tuple[EarningsReport, ...]:
        if (
            "EARNINGS_GAP" not in self.config.enabled_playbooks
            or self.registry.get(symbol).asset_class != AssetClass.STOCK
        ):
            return ()
        if self.sec is None:
            self.state.ledger.append(
                SecurityEvent,
                kind="EARNINGS_REPORTS_UNAVAILABLE",
                detail={"symbol": symbol, "reason": "SEC submissions not configured"},
            )
            return ()
        try:
            return await self.sec.earnings_reports(symbol, as_of)
        except ProviderError:
            self.state.ledger.append(
                SecurityEvent,
                kind="EARNINGS_REPORTS_UNAVAILABLE",
                detail={"symbol": symbol, "reason": "SEC submissions read unavailable"},
            )
            return ()

    async def get(self, symbol: str, as_of: datetime) -> PeerStrength:
        batch = await self.daily((symbol,))
        # Keep fetch provenance intact. The pure calculation separately checks
        # that these completed bars still end at the required session.
        sector = SECTOR_ETFS.get(self.registry.get(symbol).gics_sector)
        available = {
            row.symbol
            for row in batch.entries
            if row.adjustment == "ALL" and row.status == MarketStatus.OK
        }
        if sector is None or not {symbol, sector, "SPY"}.issubset(available):
            return await NullPeerProvider().get(symbol, as_of)
        return calculate_peer_strength(
            symbol,
            batch.for_symbol(symbol, "ALL"),
            batch.for_symbol(sector, "ALL"),
            batch.for_symbol("SPY", "ALL"),
            registry=self.registry,
            calendar=self.calendar,
            as_of=as_of,
        )

    async def news(self, symbol: str, as_of: datetime) -> NewsAssessment:
        evidence = await self.news_provider.fetch((symbol,), as_of - timedelta(days=1), as_of)
        return await self.news_reader.read(symbol, evidence, eligible=False)

    async def review(self, symbol: str, as_of: datetime) -> ReviewEvidence:
        quote = await self.quote(symbol)
        today = ensure_utc(self.clock.now()).astimezone(ZoneInfo("America/New_York")).date()
        actions = await self.actions.fetch((symbol,), today - timedelta(days=30), today)
        filings, _cik = await self.filings(symbol)
        at = ensure_utc(self.clock.now())
        fundamental = compute_fundamentals(
            self.registry.get(symbol), filings, at, self.config.fundamentals
        )
        return ReviewEvidence(
            market=quote.market,
            actions=actions,
            fundamental=fundamental,
            news=await self.news(symbol, at),
        )

    async def _tickets(self) -> tuple[tuple[TradeTicket, int], ...]:
        def read() -> tuple[tuple[TradeTicket, int], ...]:
            self.state.ledger.verify_chain()
            with Session(self.state.engine) as session:
                result: list[tuple[TradeTicket, int]] = []
                for ticket in session.scalars(select(TradeTicket).order_by(TradeTicket.seq)):
                    alert = session.get(Alert, ticket.alert_id)
                    order = (
                        None
                        if alert is None
                        else session.scalar(
                            select(Order).where(Order.proposal_id == alert.proposal_id)
                        )
                    )
                    if order is None or order.account_id != self.boundary.account_id:
                        raise DataIntegrityError(
                            "Manual ticket has missing or different account provenance"
                        )
                    skipped = session.scalar(
                        select(TicketEvent.id)
                        .where(
                            TicketEvent.ticket_id == ticket.id,
                            TicketEvent.action == "TICKET_SKIPPED",
                        )
                        .limit(1)
                    )
                    if skipped is not None:
                        continue
                    filled = sum(session.scalars(select(Fill.qty).where(Fill.order_id == order.id)))
                    result.append((ticket, filled))
                return tuple(result)

        return await asyncio.to_thread(read)

    async def open_tickets(self) -> tuple[Protection, ...]:
        now = ensure_utc(self.clock.now())
        return tuple(
            Protection(
                symbol=ticket.symbol,
                qty=ticket.qty - filled,
                stop=ticket.stop_price,
                target=ticket.target_price,
                kind="OPEN_TICKET",
            )
            for ticket, filled in await self._tickets()
            if filled < ticket.qty
            and ticket.valid_until > now
            and ticket.side == "BUY"
            and ticket.stop_price is not None
        )

    async def positions(self) -> PositionView:
        account = await self.boundary.portfolio_async(self.reader)
        quotes = tuple([await self.quote(symbol) for symbol in sorted(account.snapshot.positions)])
        if self.settings.execution_mode != "MANUAL":
            observed = []
            for symbol, broker_held in account.snapshot.positions.items():
                stops = tuple(
                    row for row in account.snapshot.protective_stops if row.symbol == symbol
                )
                if stops and sum(row.qty for row in stops) == broker_held.qty:
                    observed.append(
                        Protection(
                            symbol=symbol,
                            qty=broker_held.qty,
                            stop=min(row.stop_price for row in stops),
                            kind="HELD",
                        )
                    )
            return PositionView(
                portfolio=account.snapshot,
                quotes=quotes,
                protections=tuple(observed),
                protections_at_broker=True,
            )
        planned: dict[str, Protection] = {}
        for ticket, filled in await self._tickets():
            held = account.snapshot.positions.get(ticket.symbol)
            if (
                held is not None
                and held.qty > 0
                and filled > 0
                and ticket.side == "BUY"
                and ticket.stop_price is not None
            ):
                planned[ticket.symbol] = Protection(
                    symbol=ticket.symbol,
                    qty=min(held.qty, filled),
                    stop=ticket.stop_price,
                    target=ticket.target_price,
                    kind="HELD",
                )
        return PositionView(
            portfolio=account.snapshot, quotes=quotes, protections=tuple(planned.values())
        )

    async def read(self) -> PositionView:
        return await self.positions()

    async def weekly_history(self) -> WeeklyHistory:
        # Only sealed, validated RAW/SPLIT/ALL evidence supports a report.
        # No generated prices, invented split ratios or stale history fallback.
        history = await asyncio.to_thread(
            load_history, self.project / "data/history", self.calendar
        )
        end = _eligible_session(
            self.calendar,
            ensure_utc(self.clock.now()),
            self.config.schedule.daily_scan_delay_minutes,
        )
        if any(row.sessions[-1] != end for row in history.bundle.series):
            raise DataIntegrityError(
                "Weekly report history is stale; freeze current verified public history"
            )
        start = self.calendar.previous_sessions(end, 4)[0]
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            first_alert = session.scalar(
                select(func.min(Alert.created_at))
                .join(Order, Order.proposal_id == Alert.proposal_id)
                .where(Order.account_id == self.boundary.account_id)
            )
        if first_alert is not None:
            first_day = ensure_utc(first_alert).astimezone(ZoneInfo("America/New_York")).date()
            while not self.calendar.is_session(first_day):
                first_day -= timedelta(days=1)
            start = min(start, first_day)
        return WeeklyHistory(
            context=ReportContext(
                account_id=self.boundary.account_id,
                cohort="PAPER" if self.settings.paper_trading else "LIVE",
                start=start,
                end=end,
                config_sha256=self.config.config_hash,
            ),
            history=history,
        )
