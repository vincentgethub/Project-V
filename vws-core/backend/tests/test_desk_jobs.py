"""GD-04/UX: actual desk bodies, fake public/broker data and private SDK HTTP."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import DeskCommands, PositionView, SymbolQuote, pages, read_status
from backend.agents.desk import Desk
from backend.agents.fundamentals import compute_fundamentals
from backend.agents.jobs import DeskJobs, ReviewEvidence, ScanCycle
from backend.agents.news_reader import NewsAssessment
from backend.agents.orchestrator import JobCounts, JobName, Orchestrator
from backend.agents.position_monitor import Protection
from backend.core.database import JobRun, ResearchReport
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.corporate_actions import CorporateActionsResult
from backend.data.news import NewsInput, NewsProviderName, NewsResult, NewsStore
from backend.domain.models import MarketStatus, Position, ProviderStatus
from backend.tests.test_swarm_and_callbacks import (  # noqa: F401
    Harness,
    ack,
    click,
    count,
    deliver,
    make_research_harness,
)
from backend.tests.test_telegram_flow import API, make


class Sources:
    def __init__(self, h: Harness) -> None:
        self.h = h
        self.protections: tuple[Protection, ...] = ()
        self.ticket_protection: tuple[Protection, ...] = ()
        self.suspect = False
        self.flag = False

    async def read(self) -> PositionView:
        return await self.positions()

    async def positions(self) -> PositionView:
        return PositionView(
            portfolio=self.h.source.inputs.portfolio,
            quotes=(SymbolQuote(symbol="NVDA", feed="IEX", market=self.h.source.inputs.market),),
            protections=self.protections,
        )

    async def scan(self) -> ScanCycle:
        return ScanCycle(as_of=self.h.clock.now(), symbols_scanned=1, requests=(self.h.request,))

    async def quote(self, symbol: str) -> SymbolQuote:
        return SymbolQuote(symbol=symbol, feed="IEX", market=self.h.source.inputs.market)

    async def open_tickets(self) -> tuple[Protection, ...]:
        return self.ticket_protection

    async def news(self, symbol: str, as_of: datetime) -> NewsAssessment:
        if self.flag:
            headlines = NewsStore(self.h.state.ledger).ingest(
                NewsProviderName.FAKE,
                (
                    NewsInput(
                        provider_id="guidance",
                        headline="NVDA guidance changed",
                        published_at=as_of - timedelta(seconds=1),
                        symbols=(symbol,),
                    ),
                ),
            )
            result = NewsResult(
                provider=NewsProviderName.FAKE,
                status=ProviderStatus.OK,
                as_of=as_of,
                headlines=headlines,
                reason="stored public headline",
            )
        else:
            result = NewsResult(
                provider=NewsProviderName.FAKE,
                status=ProviderStatus.UNAVAILABLE,
                as_of=as_of,
                reason="offline unavailable",
            )
        return NewsAssessment(symbol=symbol, news=result, sentiment=None, sentiment_status="OFF")

    async def review(self, symbol: str, as_of: datetime) -> ReviewEvidence:
        h = self.h
        return ReviewEvidence(
            market=h.source.inputs.market.model_copy(
                update={"status": MarketStatus.SUSPECT if self.suspect else MarketStatus.OK}
            ),
            actions=CorporateActionsResult(
                provider="FAKE",
                status=ProviderStatus.OK,
                fetched_at=as_of,
                symbols=(symbol,),
                process_start=as_of.date(),
                process_end=as_of.date(),
                reason="explicit public coverage",
            ),
            fundamental=compute_fundamentals(
                h.swarm.risk.cro.registry.get(symbol), None, as_of, h.config.fundamentals
            ),
            news=await self.news(symbol, as_of),
        )


def composition(h: Harness) -> tuple[DeskJobs, Sources, API]:
    source, api = Sources(h), API()
    bot = make(h, api)
    commands = DeskCommands(
        h.state, h.settings, h.request.portfolio.account_id, h.swarm.risk.cro.calendar, source
    )
    bot.commands.update(commands.handlers())

    async def fixture_body() -> JobCounts:
        return JobCounts(counts={"fixture_dependency": 1})

    return (
        DeskJobs(Desk(h.swarm), bot, commands, source, fixture_body, fixture_body, fixture_body),
        source,
        api,
    )


@pytest.mark.asyncio
async def test_GD_04_actual_daily_body_sends_one_card_and_persisted_digest(
    harness: Harness,
) -> None:
    h = harness
    jobs, _, api = composition(h)
    assert set(jobs.bodies()) == set(JobName)
    await jobs.bot.start()
    try:
        result = await jobs.daily_scan()
        assert result.counts == {"symbols": 1, "candidates": 1, "expired": 0, "alert": 1, "sent": 1}
        assert len(api.messages) == 2 and "Setups saved: 1" in api.messages[-1]
        assert "Pending: 1" in "".join(await jobs.commands.digest(""))
        status = read_status(h.state, h.settings)
        assert (
            status.pending_alerts == 1
            and status.open_tickets == 0
            and status.llm_committed_today == 0
        )
        assert "no successful run" in "".join(await jobs.commands.status(""))
        assert (await jobs.daily_scan()).counts["cooldown"] == 1
        h.state.escalate(SystemState.HALTED, "stop entry scan")
        assert (await jobs.daily_scan()).counts == {"entries_skipped": 1}
    finally:
        await jobs.bot.stop()


@pytest.mark.asyncio
async def test_GD_04_premarket_unavailable_facts_annotate_then_suspect_closes(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    jobs, source, api = composition(h)
    await jobs.bot.start()
    try:
        assert (await jobs.premarket_check()).counts == {"expired": 0, "annotated": 1}
        assert (
            "INCOMPLETE" in api.edit_messages[-1]
            and "earnings unavailable" in api.edit_messages[-1]
        )
        with Session(h.state.engine) as session:
            row = session.scalar(
                select(ResearchReport).where(ResearchReport.agent_name == "premarket")
            )
            assert row is not None and row.status == "UNAVAILABLE"
        source.suspect = True
        assert (await jobs.premarket_check()).counts["closed"] == 1
        assert h.state.ledger.current_alert_status(alert.id) == "REVALIDATION_FAILED"
        assert (await h.gate.handle(click(h, "A"), acknowledge=ack)).status == "HANDLED"
    finally:
        await jobs.bot.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("accounting_fails", [False, True])
async def test_R_09_monitor_body_sends_urgent_capped_exit_while_halted_and_deduplicates(
    harness: Harness,
    accounting_fails: bool,
) -> None:
    h = harness
    jobs, source, api = composition(h)
    source.protections = (Protection(symbol="NVDA", qty=9, stop=Decimal(95)),)
    h.source.inputs = h.source.inputs.model_copy(
        update={
            "portfolio": h.source.inputs.portfolio.model_copy(
                update={
                    "positions": {
                        "NVDA": Position(qty=3, avg_cost=Decimal(100), last_price=Decimal(95))
                    }
                }
            ),
            "market": h.source.inputs.market.model_copy(update={"last_price": Decimal(95)}),
        }
    )
    h.state.escalate(SystemState.HALTED, "test monitor after entry halt")
    if accounting_fails:

        async def failed_poll() -> JobCounts:
            raise DataIntegrityError("Synthetic accounting failure")

        jobs.fill_poll = failed_poll
    await jobs.bot.start()
    try:
        if accounting_fails:
            with pytest.raises(DataIntegrityError, match="held exit warnings"):
                await jobs.position_monitor()
        else:
            assert (await jobs.position_monitor()).counts["exit_suggestions"] == 1
        assert "Held cap 3 shares" in api.messages[-1] and "IEX" in api.messages[-1]
        if accounting_fails:
            with pytest.raises(DataIntegrityError):
                await jobs.position_monitor()
        else:
            assert (await jobs.position_monitor()).counts["exit_suggestions"] == 0
        assert "distance 0.00%" in "".join(await jobs.commands.positions(""))
        assert h.state.current() == SystemState.HALTED
    finally:
        await jobs.bot.stop()


@pytest.mark.asyncio
async def test_GD_04_news_watch_only_held_or_pending_and_housekeeping_keeps_ledger(
    harness: Harness,
) -> None:
    h = harness
    await deliver(h)
    jobs, source, api = composition(h)
    source.flag = True
    await jobs.bot.start()
    try:
        result = await jobs.news_watch()
        assert result.counts == {"symbols": 1, "flagged": 1}
        assert "keyword flag" in api.edit_messages[-1]
        before = count(h, ResearchReport)
        assert (await jobs.housekeeping()).counts == {"fixture_dependency": 1, "expired": 0}
        assert count(h, ResearchReport) == before
        h.state.ledger.verify_chain()
    finally:
        await jobs.bot.stop()


@pytest.mark.asyncio
async def test_UX_private_commands_preserve_full_progress_and_visible_missing_evidence(
    harness: Harness,
) -> None:
    jobs, _, _ = composition(harness)
    commands = jobs.commands
    assert "not available yet" in "".join(await commands.digest(""))
    assert "No weekly report" in "".join(await commands.report(""))
    assert "No holdings" in "".join(await commands.positions(""))
    assert "Details is read-only" in "".join(await commands.help(""))
    from html import unescape

    from vws.progress import read_progress

    assert unescape("\n".join(await commands.progress(""))) == read_progress().rstrip("\n")


def test_UX_utf16_command_boundaries_preserve_all_text() -> None:
    text = "a" * 4000 + "\n" + "b" * 4000
    assert "\n".join(pages(text)) == text and len(pages(text)) == 2
    for invalid in ("", "x" * 4097, "😀" * 2049):
        with pytest.raises(DataIntegrityError):
            pages(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["other_account", "stale", "future"])
async def test_GD_04_news_watch_rejects_wrong_or_stale_private_holdings(
    harness: Harness, fault: str
) -> None:
    h = harness
    jobs, source, api = composition(h)
    h.clock.current = datetime.fromisoformat("2026-09-30T15:00:00+00:00")
    changes = (
        {"account_id": "another-account"}
        if fault == "other_account"
        else {
            "as_of": h.clock.now()
            + timedelta(seconds=1 if fault == "future" else -(h.settings.stale_quote_seconds + 1))
        }
    )
    h.source.inputs = h.source.inputs.model_copy(
        update={"portfolio": h.source.inputs.portfolio.model_copy(update=changes)}
    )
    source.flag = True
    runner = Orchestrator(h.config, h.swarm.risk.cro.calendar, h.state, h.clock, jobs.bodies())
    await runner.tick(JobName.NEWS_WATCH)
    assert h.state.current() == SystemState.HALTED and not api.messages
    with Session(h.state.engine) as session:
        run = session.scalar(select(JobRun).where(JobRun.job == "news_watch"))
        assert run is not None and run.outcome == "FAIL"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["feed", "symbol"])
async def test_GD_04_open_ticket_exit_warning_requires_bound_iex_quote(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    h = harness
    jobs, source, api = composition(h)
    h.clock.current = datetime.fromisoformat("2026-09-30T15:00:00+00:00")
    source.ticket_protection = (
        Protection(symbol="NVDA", qty=9, stop=Decimal(95), kind="OPEN_TICKET"),
    )

    async def positions_without_quote() -> PositionView:
        return PositionView(portfolio=h.source.inputs.portfolio, quotes=(), protections=())

    async def wrong_quote(symbol: str) -> SymbolQuote:
        return SymbolQuote(symbol=symbol, feed="IEX", market=h.source.inputs.market).model_copy(
            update={"feed": "SIP"} if fault == "feed" else {"symbol": "SPY"}
        )

    monkeypatch.setattr(source, "positions", positions_without_quote)
    monkeypatch.setattr(source, "quote", wrong_quote)
    runner = Orchestrator(h.config, h.swarm.risk.cro.calendar, h.state, h.clock, jobs.bodies())
    await runner.tick(JobName.POSITION_MONITOR)
    assert h.state.current() == SystemState.HALTED and not api.messages
    with Session(h.state.engine) as session:
        run = session.scalar(select(JobRun).where(JobRun.job == "position_monitor"))
        assert run is not None and run.outcome == "FAIL"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["", "dropped", "foreign_symbol", "foreign_snapshot"])
async def test_OPS_02_refresh_before_research_never_changes_bound_identity(
    harness: Harness, fault: str
) -> None:
    from uuid import uuid4

    from backend.agents.swarm_runner import ResearchRequest

    h = harness
    jobs, _, api = composition(h)
    called: list[str] = []

    async def refresh(request: ResearchRequest) -> ResearchRequest | None:
        called.append(request.candidate.symbol)
        if fault == "dropped":
            return None
        if fault == "foreign_symbol":
            return request.model_copy(
                update={"candidate": request.candidate.model_copy(update={"symbol": "SPY"})}
            )
        if fault == "foreign_snapshot":
            return request.model_copy(update={"data_snapshot_id": uuid4()})
        return request

    jobs.refresh_request = refresh
    await jobs.bot.start()
    try:
        if fault.startswith("foreign"):
            with pytest.raises(DataIntegrityError, match="changed"):
                await jobs.daily_scan()
            assert not api.messages
        else:
            result = await jobs.daily_scan()
            assert result.counts["fresh_setup_dropped" if fault else "sent"] == 1
        assert called == ["NVDA"]
    finally:
        await jobs.bot.stop()
