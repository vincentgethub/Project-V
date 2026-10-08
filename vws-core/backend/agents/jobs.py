"""GD-04: concrete daily, pending-fact and held-exit job bodies.

Connected source composition and host lifecycle belong to Stage H; report
production belongs to G. Dependencies are required, never silent placeholders.
"""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import DeskCommands, PositionView, SymbolQuote
from backend.agents.desk import Desk
from backend.agents.fundamentals import FundamentalReport, framework_allows
from backend.agents.news_reader import NewsAssessment
from backend.agents.orchestrator import JobBody, JobCounts, JobName
from backend.agents.position_monitor import Protection, monitor
from backend.agents.swarm_runner import ResearchRequest
from backend.core.clock import ensure_utc
from backend.core.database import Alert, AlertEvent, ResearchReport, SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.corporate_actions import CorporateActionsResult
from backend.domain.models import (
    FrozenModel,
    MarketContext,
    MarketStatus,
    ProviderStatus,
    SentimentClassification,
    UTCDateTime,
)
from backend.notifications.telegram_bot import TelegramBot
from backend.risk.risk_cro import earnings_rule


class ScanCycle(FrozenModel):
    as_of: UTCDateTime
    symbols_scanned: int = Field(strict=True, ge=0, le=1000)
    requests: tuple[ResearchRequest, ...] = Field(max_length=3000)
    spy_above_ema200: bool | None = Field(default=None, strict=True)


class ReviewEvidence(FrozenModel):
    market: MarketContext
    actions: CorporateActionsResult
    fundamental: FundamentalReport
    news: NewsAssessment


class JobSources(Protocol):
    async def scan(self) -> ScanCycle: ...
    async def review(self, symbol: str, as_of: datetime) -> ReviewEvidence: ...
    async def positions(self) -> PositionView: ...
    async def open_tickets(self) -> tuple[Protection, ...]: ...
    async def quote(self, symbol: str) -> SymbolQuote: ...
    async def news(self, symbol: str, as_of: datetime) -> NewsAssessment: ...


class DeskJobs:
    def __init__(
        self,
        desk: Desk,
        bot: TelegramBot,
        commands: DeskCommands,
        source: JobSources,
        weekly_report: JobBody,
        maintenance: JobBody,
        fill_poll: Callable[[], Awaitable[JobCounts]],
        *,
        refresh_request: Callable[[ResearchRequest], Awaitable[ResearchRequest | None]]
        | None = None,
        accounting_capture: Callable[[], Awaitable[JobCounts]] | None = None,
        pnl_digest: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        if bot.state is not desk.swarm.state or commands.state is not bot.state:
            raise ConfigurationError("GD-04: job bodies must share the defensive desk")
        self.desk, self.bot, self.commands, self.source = desk, bot, commands, source
        self.weekly_report, self.maintenance, self.fill_poll = weekly_report, maintenance, fill_poll
        self.state, self.clock = bot.state, bot.clock
        self.refresh_request = refresh_request
        self.accounting_capture, self.pnl_digest = accounting_capture, pnl_digest

    def bodies(self) -> dict[JobName, JobBody]:
        return {
            JobName.DAILY_SCAN: self.daily_scan,
            JobName.PREMARKET_CHECK: self.premarket_check,
            JobName.POSITION_MONITOR: self.position_monitor,
            JobName.NEWS_WATCH: self.news_watch,
            JobName.WEEKLY_REPORT: self.weekly_report,
            JobName.HOUSEKEEPING: self.housekeeping,
        }

    def pending(self) -> tuple[Alert, ...]:
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            return tuple(
                session.scalars(
                    select(Alert)
                    .where(
                        ~select(AlertEvent.id)
                        .where(
                            AlertEvent.alert_id == Alert.id,
                            AlertEvent.state.in_(
                                ("APPROVED", "REJECTED", "EXPIRED", "REVALIDATION_FAILED")
                            ),
                        )
                        .exists()
                    )
                    .order_by(Alert.seq)
                )
            )

    async def daily_scan(self) -> JobCounts:
        accounting = JobCounts(counts={})
        if self.accounting_capture is not None:
            accounting = JobCounts.model_validate(await self.accounting_capture())
        if self.state.current() != SystemState.RUNNING:
            return JobCounts(counts={**accounting.counts, "entries_skipped": 1})
        expired = await self.bot.expire_alerts()
        cycle = ScanCycle.model_validate(await self.source.scan())
        now = ensure_utc(self.clock.now())
        if not timedelta(0) <= now - cycle.as_of <= timedelta(seconds=30):
            raise DataIntegrityError("GD-04: scan cycle is stale/future")
        if (
            cycle.symbols_scanned > len(self.desk.swarm.config.watchlist)
            or len({row.candidate.symbol for row in cycle.requests}) > cycle.symbols_scanned
        ):
            raise DataIntegrityError("GD-04: scan counts do not match its registered watchlist")
        counts: Counter[str] = Counter(
            {
                "symbols": cycle.symbols_scanned,
                "candidates": len(cycle.requests),
                "expired": expired,
            }
        )
        for request in cycle.requests:
            if self.refresh_request is not None:
                refreshed = await self.refresh_request(request)
                if refreshed is None:
                    counts["fresh_setup_dropped"] += 1
                    continue
                refreshed = ResearchRequest.model_validate(refreshed)
                if (
                    refreshed.candidate.symbol != request.candidate.symbol
                    or refreshed.candidate.playbook != request.candidate.playbook
                    or refreshed.data_snapshot_id != request.data_snapshot_id
                ):
                    raise DataIntegrityError(
                        "Refreshed setup changed its symbol, playbook or data provenance"
                    )
                request = refreshed
            result = await self.desk.research(request)
            counts[result.status.lower()] += 1
            if result.status == "ALERT":
                if result.research is None or result.research.alert_id is None:
                    raise DataIntegrityError("GD-04: desk alert lacks its immutable identity")
                counts["sent"] += int(
                    await self.bot.deliver(
                        result.research.alert_id, self.bot.settings.telegram_allowed_user_ids[0]
                    )
                )
        context = (
            "SPY unavailable"
            if cycle.spy_above_ema200 is None
            else "SPY " + ("above" if cycle.spy_above_ema200 else "below") + " 200-day avg"
        )
        pnl = None if self.pnl_digest is None else await self.pnl_digest()
        await self.bot.notify(self.commands.save_digest(context, pnl=pnl), False)
        counts.update(accounting.counts)
        return JobCounts(counts=dict(counts))

    async def premarket_check(self) -> JobCounts:
        expired = await self.bot.expire_alerts()
        now = ensure_utc(self.clock.now())
        today = now.astimezone(ZoneInfo("America/New_York")).date()
        counts: Counter[str] = Counter({"expired": expired})
        for alert in self.pending():
            async with asyncio.timeout(30):
                evidence = ReviewEvidence.model_validate(
                    await self.source.review(alert.symbol, now)
                )
            now = ensure_utc(self.clock.now())
            actions, fund, news = evidence.actions, evidence.fundamental, evidence.news
            if (
                fund.symbol != alert.symbol
                or news.symbol != alert.symbol
                or alert.symbol not in actions.symbols
                or actions.fetched_at > now
                or now - actions.fetched_at > timedelta(seconds=30)
                or fund.as_of > now
                or now - fund.as_of
                > timedelta(hours=self.desk.swarm.config.fundamentals.cache_hours)
                or news.news.as_of > now
                or now - news.news.as_of > timedelta(seconds=30)
            ):
                raise DataIntegrityError("GD-04: overnight review issuer/time/cache binding failed")
            failures: list[str] = []
            annotations: list[str] = []
            if evidence.market.status == MarketStatus.SUSPECT:
                failures.append("symbol is SUSPECT")
            if (
                actions.status != ProviderStatus.OK
                or not actions.process_start <= today <= actions.process_end
            ):
                annotations.append("corporate-action evidence unavailable")
            elif (alert.symbol, today) in actions.known_actions:
                failures.append("price-effective corporate action changed the setup")
            earnings = earnings_rule(
                evidence.market, now, self.bot.settings, self.desk.swarm.risk.cro.calendar
            )
            if not earnings.passed:
                if earnings.severity.value == "BLOCK":
                    failures.append("earnings now inside blackout")
                else:
                    annotations.append(
                        "earnings unavailable or estimated; operator review required"
                    )
            if not framework_allows(fund, self.desk.swarm.config.fundamentals):
                failures.append("required fundamental checks unavailable or failed")
            annotations.append(f"Fundamentals {fund.passed_count}/5 {fund.framework_status.value}")
            annotation = self._news_flag(news)
            if annotation:
                annotations.append(annotation)
            self.state.ledger.append(
                ResearchReport,
                alert_id=alert.id,
                agent_name="premarket",
                status="ERROR"
                if failures
                else (
                    "UNAVAILABLE"
                    if actions.status != ProviderStatus.OK
                    or news.news.status != ProviderStatus.OK
                    or fund.framework_status.value == "INCOMPLETE"
                    else "OK"
                ),
                payload=evidence.model_dump(mode="json"),
            )
            if failures:
                counts["closed"] += int(await self.bot.invalidate(alert.id, "; ".join(failures)))
            else:
                counts["annotated"] += int(
                    await self.bot.annotate(alert.id, "; ".join(annotations))
                )
        return JobCounts(counts=dict(counts))

    @staticmethod
    def _news_flag(news: NewsAssessment) -> str | None:
        checked = NewsAssessment.model_validate(news)
        if checked.news.status != ProviderStatus.OK:
            return "overnight news unavailable"
        if (
            checked.sentiment is not None
            and checked.sentiment.classification == SentimentClassification.THESIS_CHANGING
        ):
            return "public news summary flags a thesis change; review the cited headlines"
        if checked.sentiment_status == "OFF" and any(
            any(
                word in headline.headline.lower()
                for word in (
                    "recall",
                    "fraud",
                    "bankruptcy",
                    "guidance",
                    "investigation",
                    "restatement",
                )
            )
            for headline in checked.news.headlines
        ):
            return "public headline keyword flag; review before approving"
        return None

    async def position_monitor(self) -> JobCounts:
        poll_failed = False
        try:
            fills = JobCounts.model_validate(await self.fill_poll())
        except Exception:
            self.state.escalate(
                SystemState.HALTED,
                "Account activity/history check failed; held exits still require review",
            )
            poll_failed = True
            fills = JobCounts(counts={"account_activity_failures": 1})
        view = PositionView.model_validate(await self.source.positions())
        if view.portfolio.account_id != self.commands.account_id:
            raise DataIntegrityError("GD-04: monitored positions belong to another account")
        quotes = {row.symbol: row for row in view.quotes}
        checks = list(view.protections)
        checks.extend(Protection.model_validate(row) for row in await self.source.open_tickets())
        count = 0
        for protection in checks:
            quote = quotes.get(protection.symbol)
            if quote is None:
                async with asyncio.timeout(30):
                    quote = SymbolQuote.model_validate(await self.source.quote(protection.symbol))
            if quote.symbol != protection.symbol:
                raise DataIntegrityError("GD-04: exit quote belongs to another symbol")
            for warning in monitor(
                protection,
                view.portfolio,
                quote.market,
                now=self.clock.now(),
                quote_feed=quote.feed,
                settings=self.bot.settings,
                calendar=self.desk.swarm.risk.cro.calendar,
            ):
                # One unchanged warning per symbol/reason/session; urgent stops
                # bypass quiet hours, and no entry risk rule runs here.
                day = (
                    ensure_utc(self.clock.now())
                    .astimezone(ZoneInfo("America/New_York"))
                    .date()
                    .isoformat()
                )
                with Session(self.state.engine) as session:
                    previous = session.scalar(
                        select(SecurityEvent)
                        .where(
                            SecurityEvent.kind == "EXIT_WARNING",
                            SecurityEvent.detail["symbol"].as_string() == warning.symbol,
                            SecurityEvent.detail["reason"].as_string() == warning.reason,
                            SecurityEvent.detail["day"].as_string() == day,
                        )
                        .limit(1)
                    )
                if previous is None:
                    await self.bot.notify(warning.text, warning.urgent)
                    self.state.ledger.append(
                        SecurityEvent,
                        kind="EXIT_WARNING",
                        detail={"symbol": warning.symbol, "reason": warning.reason, "day": day},
                    )
                    count += 1
        if poll_failed:
            raise DataIntegrityError(
                "Account activity check failed; held exit warnings were still evaluated"
            )
        return JobCounts(counts={**fills.counts, "exit_suggestions": count})

    async def news_watch(self) -> JobCounts:
        pending = self.pending()
        view = PositionView.model_validate(await self.source.positions())
        now = ensure_utc(self.clock.now())
        if view.portfolio.account_id != self.commands.account_id or not timedelta(
            0
        ) <= now - view.portfolio.as_of <= timedelta(seconds=self.bot.settings.stale_quote_seconds):
            raise DataIntegrityError("GD-04: news-watch positions have wrong account or stale time")
        symbols = sorted(set(view.portfolio.positions) | {row.symbol for row in pending})
        flagged = 0
        for symbol in symbols:
            async with asyncio.timeout(30):
                news = NewsAssessment.model_validate(await self.source.news(symbol, now))
            completed = ensure_utc(self.clock.now())
            if news.symbol != symbol or not timedelta(
                0
            ) <= completed - news.news.as_of <= timedelta(seconds=30):
                raise DataIntegrityError("GD-04: news-watch issuer/time binding failed")
            flag = self._news_flag(news)
            if flag is None:
                continue
            self.state.ledger.append(
                SecurityEvent,
                kind="NEWS_WATCH_FLAG",
                detail={"symbol": symbol, "flag": flag, "as_of": now},
            )
            for alert in pending:
                if alert.symbol == symbol:
                    await self.bot.annotate(alert.id, flag)
            if symbol in view.portfolio.positions:
                await self.bot.notify(symbol + ": " + flag, False)
            flagged += 1
        return JobCounts(counts={"symbols": len(symbols), "flagged": flagged})

    async def housekeeping(self) -> JobCounts:
        expired = await self.bot.expire_alerts()
        self.state.ledger.verify_chain()
        counts = JobCounts.model_validate(await self.maintenance())
        await self.bot.flush_pending()
        return JobCounts(counts={**counts.counts, "expired": expired})
