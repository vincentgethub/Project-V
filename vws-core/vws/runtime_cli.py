"""OPS-02/AX-11: connected composition, only on explicit guarded host start."""

import asyncio
import signal
from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import FrameType
from typing import Literal, Protocol, TypeVar, overload
from uuid import UUID
from zoneinfo import ZoneInfo

from requests import Session as RequestsSession
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import DeskCommands
from backend.agents.desk import Desk
from backend.agents.indicators import IndicatorMemo
from backend.agents.jobs import DeskJobs
from backend.agents.llm_client import LLMClient
from backend.agents.news_reader import NewsReader
from backend.agents.orchestrator import JobCounts, Orchestrator
from backend.agents.setup_hunter import SetupHunter
from backend.agents.swarm_runner import SwarmRunner
from backend.core.config import MANUAL_CSV_DISABLED_MESSAGE, load_yaml_config
from backend.core.database import Alert, ExecutionOrderRecord, JobRun, SecurityEvent
from backend.core.errors import ConfigurationError
from backend.core.logging import configure_logging
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.boundary import ReadBoundary
from backend.data.broker_clock import BrokerTimeVerifier
from backend.data.broker_state import AlpacaBrokerState
from backend.data.corporate_actions import AlpacaCorporateActionsProvider
from backend.data.data_layer import AsyncAlpacaMarketData, ResilientReader
from backend.data.earnings import EarningsProvider
from backend.data.fee_schedule import load_fee_schedule
from backend.data.fill_polling import ObservedFill, TicketFillMatcher
from backend.data.liquidity import BalanceReading, LiquidityGate, PlaidLiquiditySource
from backend.data.market_calendar import MarketCalendar
from backend.data.news import (
    AlpacaNewsProvider,
    NewsApiProvider,
    NewsProvider,
    NewsStore,
    RssNewsProvider,
)
from backend.data.sec_edgar import SecEdgarProvider
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import Playbook, PortfolioSnapshot
from backend.evaluation.ledger_source import LedgerWeeklySource
from backend.evaluation.publication import WeeklyPublisher
from backend.execution.control_evidence import JobBinding
from backend.execution.fill_capture import ExecutionFillCapture
from backend.execution.jobs import AutoJobs
from backend.execution.live_guard import LiveGuard
from backend.execution.modes import ModeStore
from backend.execution.protocol import OrderExecutor
from backend.execution.readiness import HostPrerequisites
from backend.execution.reporting import daily_summary
from backend.execution.worker import SingleAttemptWorker
from backend.funding.activities import AlpacaActivitiesSource
from backend.notifications.callbacks import ApprovalGate
from backend.notifications.telegram_bot import TelegramBot
from backend.ops.account_context import LedgerAccountContext
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.doctor import DoctorResult
from backend.ops.job_health import JobHealth
from backend.ops.journal import Journal
from backend.ops.k_runtime import ExtraControls
from backend.ops.macro_events import MacroCalendar
from backend.ops.maintenance import NightlyMaintenance
from backend.ops.process import ProcessLock
from backend.ops.read_checks import ReadChecksClient
from backend.ops.report_publisher import ReportPublisher
from backend.ops.runtime import HostRuntime
from backend.ops.trading_controls import ControlScope
from backend.ops.watch import WatchDesk
from backend.ops.watchdog import Watchdog
from backend.pnl.history import EquityHistory, read_history
from backend.pnl.service import AccountingReports
from backend.risk.boundary import RiskBoundary
from backend.risk.compliance import ComplianceEngine
from backend.risk.compliance_boundary import ComplianceBoundary
from backend.risk.portfolio_marks import PersistedPortfolioMarks
from backend.risk.risk_cro import ChiefRiskOfficer
from backend.security.secrets import KeyringSecretStore, SecretStore
from backend.tax.service import TaxService
from vws import security_cli
from vws.drill_cli import verified_drill
from vws.host_config import load_host_settings

ReadT = TypeVar("ReadT")


class ExecutionStream(Protocol):
    async def start(self) -> None: ...
    async def aclose(self) -> None: ...


class _AdmittedReads:
    """The outer worker owns timeouts; the SDK GET hook charges physical calls."""

    def __init__(self, reader: AsyncAlpacaReader) -> None:
        self.reader = reader

    def run(self, operation: Callable[[], ReadT], *, budget_request: bool = True) -> ReadT:
        self.reader.ensure_active()
        return operation()


class _UnavailableChecking:
    """Unset Plaid evidence stays unavailable and yields zero deployable funds."""

    def __init__(self, context: security_cli.SecurityContext) -> None:
        self.clock = context.ledger.clock

    def read(self) -> BalanceReading:
        return BalanceReading(available=None, current=None, currency="USD", as_of=self.clock.now())


@overload
async def compose(
    context: security_cli.SecurityContext,
    store: SecretStore,
    verified_doctor: DoctorResult,
    *,
    resources: AsyncExitStack,
    accounting_only: Literal[False] = False,
) -> HostRuntime: ...


@overload
async def compose(
    context: security_cli.SecurityContext,
    store: SecretStore,
    verified_doctor: DoctorResult,
    *,
    resources: AsyncExitStack,
    accounting_only: Literal[True],
) -> None: ...


async def compose(
    context: security_cli.SecurityContext,
    store: SecretStore,
    verified_doctor: DoctorResult,
    *,
    resources: AsyncExitStack,
    accounting_only: bool = False,
) -> HostRuntime | None:
    if accounting_only and context.settings.execution_mode != "AUTO_LIVE":
        raise ConfigurationError(
            "Accounting unlock preflight requires explicit AUTO_LIVE configuration"
        )
    if context.settings.broker_state_source != "ALPACA":
        raise ConfigurationError(MANUAL_CSV_DISABLED_MESSAGE)
    if (
        verified_doctor.exit_code != 0
        or (context.settings.execution_mode != "MANUAL" and not verified_doctor.fully_green)
        or (context.settings.execution_mode == "MANUAL" and not context.settings.paper_trading)
    ):
        raise ConfigurationError(
            "Connected composition requires verified doctor checks and a bound execution mode"
        )
    project, settings, state, clock = (
        security_cli.PROJECT,
        context.settings,
        context.state,
        context.ledger.clock,
    )
    registry, calendar = InstrumentRegistry.from_csv(project / "config"), MarketCalendar()
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    policy = security_cli._require_network_policy(context, config)
    reader = AsyncAlpacaReader(clock, state, plan=settings.alpaca_data_plan)
    resources.push_async_callback(reader.aclose)
    reader.bind_policy(settings, state.ledger)
    reads = ReadChecksClient(policy, clock, alpaca_request_hook=reader.bucket.acquire)
    account = await reads.account(settings, settings.broker_api_key, settings.broker_secret_key)
    account_id = str(account.account_id)
    modes = None if settings.execution_mode == "MANUAL" else ModeStore(settings, state, account_id)
    execution: OrderExecutor | None = None
    stream: ExecutionStream | None = None
    prerequisites: HostPrerequisites | None = None
    marks = PersistedPortfolioMarks(state.ledger, account_id, calendar, settings)
    from backend.data.broker_state import configure_alpaca_transport

    broker = AlpacaBrokerState(
        settings, clock, marks, known_symbols=registry.symbols, reader=_AdmittedReads(reader)
    )
    configure_alpaca_transport(
        broker._client, settings.request_timeout_seconds, before_request=reader.before_request
    )
    resources.callback(_close_sdk, broker._client)
    liquidity = (
        PlaidLiquiditySource(
            settings, clock, reader=ResilientReader(clock, state), secret_store=store
        )
        if settings.plaid_account_id
        and settings.plaid_client_id.get_secret_value()
        and settings.plaid_secret.get_secret_value()
        else _UnavailableChecking(context)
    )
    boundary = ReadBoundary(
        settings,
        state,
        clock,
        broker,
        LiquidityGate(settings, liquidity, clock),
        account_id=account_id,
        marks=marks,
    )
    memo = IndicatorMemo()
    market = AsyncAlpacaMarketData(
        settings,
        reader,
        calendar,
        state.ledger,
        daily_scan_delay_minutes=config.schedule.daily_scan_delay_minutes,
        sip_lag_seconds=config.schedule.daily_bar_sip_lag_seconds,
        invalidate_indicators=memo.invalidate_symbol,
    )
    resources.callback(_close_sdk, market.client)
    sec = (
        SecEdgarProvider(settings, state.ledger, config=config.fundamentals)
        if settings.sec_user_agent is not None
        else None
    )
    earnings = EarningsProvider(
        project / "config/earnings_calendar.csv",
        known_symbols=registry.symbols,
        submissions=None if sec is None else sec.submissions,
    )
    cro = ChiefRiskOfficer(settings, registry, calendar)
    macro = MacroCalendar(project / "config/macro_events.csv")
    macro.read()
    risk, compliance = (
        RiskBoundary(
            cro,
            state,
            clock,
            marks=marks,
            additional_blackouts=lambda: (
                tuple(row.window() for row in macro.read())
                if modes is not None and modes.effective != "MANUAL"
                else ()
            ),
        ),
        ComplianceBoundary(ComplianceEngine(settings, registry, calendar), state, clock),
    )
    llm = LLMClient(settings, state.ledger, clock, policy=policy, notifier=state.notifier)
    resources.push_async_callback(llm.aclose)
    news_reader, news_store = (
        NewsReader(settings, llm),
        NewsStore(state.ledger, allowed_hosts=policy.hosts),
    )
    news: NewsProvider
    if settings.news_provider == "ALPACA":
        news = AlpacaNewsProvider(settings, reader, news_store)
        resources.callback(_close_sdk, news.client)
    elif settings.news_provider == "RSS":
        news = RssNewsProvider(config.news.rss_urls, news_store, policy=policy)
    else:
        # Never assume paid provider terms have been verified from a saved key.
        news = NewsApiProvider(
            news_store,
            api_key=settings.newsapi_key,
            enabled=True,
            terms_verified=False,
            policy=policy,
        )
    actions = AlpacaCorporateActionsProvider(settings, reader, state.ledger)
    resources.callback(_close_sdk, actions.client)
    source = ConnectedDeskSource(
        project,
        settings,
        config,
        state,
        clock,
        calendar,
        registry,
        market,
        boundary,
        reader,
        SetupHunter(cro, config, memo),
        earnings,
        actions,
        news,
        news_reader,
        LedgerAccountContext(state, account_id, "PAPER" if settings.paper_trading else "LIVE"),
        sec,
    )
    swarm = SwarmRunner(
        settings,
        config,
        risk,
        compliance,
        state,
        clock,
        news_reader,
        news=news,
        fundamentals=sec,
        peers=source,
        earnings=earnings,
        memo=memo,
    )
    gate = ApprovalGate(settings, config, state, risk, compliance, clock, source, modes=modes)
    commands = DeskCommands(state, settings, account_id, calendar, source, modes=modes)
    bot = TelegramBot(settings, state, clock, gate, policy, commands.handlers())
    scope = ControlScope(
        account_id=account_id, environment="PAPER" if settings.paper_trading else "LIVE"
    )
    journal = Journal(state.ledger, scope)
    extras = ExtraControls(state.ledger, scope, config, source, macro, bot.notify)
    desk = Desk(swarm)
    bot.watch_handler = WatchDesk(desk, source, bot, journal)

    async def bound_note(user: int, chat: int, message: int, text: str) -> UUID:
        return await asyncio.to_thread(
            journal.note,
            user_id=user,
            chat_id=chat,
            message_id=message,
            text=text,
            allowed=settings.telegram_allowed_user_ids,
        )

    bot.note_handler = bound_note

    def extra_status() -> tuple[str, ...]:
        drill = (
            ()
            if verified_drill(project, settings, store, clock.now(), 31)
            else ("Monthly drill due: run vws ops drill --operator NAME on the host.",)
        )
        return (*extras.status(), *drill)

    commands.extra_status = extra_status

    def card_annotations(alert: Alert) -> tuple[str, ...]:
        extras.update_playbooks()
        lines = ["Playbook paused"] if extras.controls.paused(Playbook(alert.playbook)) else []
        batch = source._batch
        if batch is None:
            lines.append("SPY regime UNVERIFIED")
        else:
            from backend.agents.indicators import ema

            spy = batch.for_symbol("SPY", "ALL")
            average = None if not spy else ema(tuple(bar.close for bar in spy), 200)[-1]
            if average is None:
                lines.append("SPY regime UNVERIFIED")
            elif spy[-1].close < average:
                lines.append(
                    "SPY below EMA200; automatic size is reduced or blocked by configuration."
                )
        day = clock.now().astimezone(ZoneInfo("America/New_York")).date()
        lines.extend(
            f"Macro event today: {event.event}; automatic blackout applies."
            for event in macro.read()
            if event.date == day
        )
        return tuple(lines)

    bot.card_annotations = card_annotations
    fill_source = AlpacaActivitiesSource(settings, account_id, state, clock, reader, policy)
    resources.push_async_callback(fill_source.close)
    matcher = TicketFillMatcher(settings, account_id, state, registry)
    auto_matcher = None if modes is None else ExecutionFillCapture(modes)

    async def portfolio() -> PortfolioSnapshot:
        return (await boundary.portfolio_async(reader)).snapshot

    schedule = load_fee_schedule(project / "config/fees.yaml")

    async def prepare_fills(symbols: tuple[str, ...]) -> None:
        start = calendar.previous_sessions(calendar.last_completed_session(clock.now()), 280)[0]
        for offset in range(0, len(symbols), 199):
            await market.completed_daily_bars(symbols[offset : offset + 199], start)
        if execution is not None:
            await execution.prepare_fills(symbols)

    def observe_fill(fill: ObservedFill) -> object:
        return matcher.record(fill) if auto_matcher is None else auto_matcher.record(fill)

    tax = TaxService(
        project,
        state,
        settings,
        account_id,
        registry,
        fill_source,
        portfolio,
        bot.notify,
        schedule,
        buying_power=lambda: broker.last_buying_power,
        observe_fill=observe_fill,
        prepare_fills=prepare_fills,
    )

    async def history(start: date, end: date) -> EquityHistory:
        return await read_history(fill_source, start, end, calendar)

    async def spy_closes(start: date, end: date) -> tuple[tuple[date, Decimal], ...]:
        batch = await market.completed_daily_bars(("SPY",), start, adjustment="RAW")
        return tuple(
            (bar.session_date, bar.close)
            for bar in batch.for_symbol("SPY")
            if bar.session_date <= end
        )

    accounting = AccountingReports(
        tax, calendar, config.schedule.daily_scan_delay_minutes, history, spy_closes
    )
    if accounting_only:
        await tax.sync(force=True)
        await accounting.capture()
        state.ledger.append(
            SecurityEvent,
            kind="HOST_ACCOUNTING_READY",
            detail={
                "account_id": account_id,
                "environment": "LIVE",
                "config_hash": settings.config_hash,
            },
        )
        return None
    bot.commands.update({"/pnl": accounting.pnl, "/tax": accounting.tax_summary})
    reports = ReportPublisher(
        project / "data/reports", scope, accounting, source, commands, bot, extra_status
    )
    bot.report_document = reports.latest

    async def sync_context() -> None:
        await tax.sync()

    source.sync_account_context = sync_context

    async def fill_poll() -> JobCounts:
        if execution is not None:
            if prerequisites is None:
                raise ConfigurationError("Execution prerequisite refresh is unavailable")
            await prerequisites.refresh(lambda: security_cli.doctor_result(context, store))
        result = await tax.sync(force=True)
        if execution is not None:
            await execution.reconcile()
            if scope.environment == "LIVE":
                await extras.observe_ramp(await portfolio())
        await asyncio.to_thread(journal.sync)
        await reports.flush()
        return result

    if modes is not None:
        with Session(state.engine) as session:
            managed = (
                session.scalar(
                    select(ExecutionOrderRecord.id)
                    .where(
                        ExecutionOrderRecord.account_id == account_id,
                        ExecutionOrderRecord.environment == modes.environment,
                    )
                    .limit(1)
                )
                is not None
            )
        if modes.effective != "MANUAL" or managed:
            # AX-11: the sole concrete execution module is imported only for an
            # AUTO configuration. A downgrade retains only managed protection.
            from backend.execution.alpaca_executor import (
                AlpacaExecutor,
                ManagedTradingStream,
                ProtectionRecovery,
            )

            prerequisites = HostPrerequisites(
                modes, verified_doctor, security_cli.backups(context, store)
            )
            constructor = AlpacaExecutor if modes.effective != "MANUAL" else ProtectionRecovery
            execution = constructor(
                settings,
                config,
                state,
                modes,
                source,
                risk,
                compliance,
                calendar,
                SingleAttemptWorker(reader.bucket),
                store,
                prerequisites(),
                policy=policy,
                notify=bot.notify,
                trade_notice=bot.notify_trade,
                size_entry=extras.size,
                portfolio=portfolio,
                configuration_check=lambda: context.drift.check(
                    context.config_hash(), mode=settings.execution_mode
                ),
                prerequisites_source=prerequisites,
                live_guard=LiveGuard(
                    settings,
                    state,
                    calendar,
                    account_id,
                    context.config_hash,
                    security_reasons=security_cli.live_security_guard(context, store),
                    drill_ready=lambda: verified_drill(project, settings, store, clock.now(), 45),
                )
                if settings.execution_mode == "AUTO_LIVE"
                else None,
            )
            resources.push_async_callback(execution.close)
            gate.bind_auto(execution, modes)

            async def capture_stream_fills() -> object:
                result = await tax.sync(force=True)
                await asyncio.to_thread(journal.sync)
                return result

            stream = ManagedTradingStream(execution, policy, capture_stream_fills)
            resources.push_async_callback(stream.aclose)
    auto_jobs = (
        None
        if execution is None or modes is None
        else AutoJobs(settings, modes, calendar, execution, fill_poll)
    )

    async def maintenance() -> JobCounts:
        await reports.capture()
        result = await NightlyMaintenance(
            security_cli.backups(context, store), settings.backup_retention_days
        )()
        anchor = await asyncio.to_thread(context.anchors.record)
        await bot.notify(anchor.message(), True)
        return result

    weekly_publisher = WeeklyPublisher(
        state,
        settings,
        config,
        account_id,
        calendar,
        project / "data/reports",
        LedgerWeeklySource(
            state,
            settings,
            config,
            account_id,
            calendar,
            source,
            schedule,
        ),
        bot.notify,
    )

    async def weekly() -> JobCounts:
        result = await weekly_publisher()
        await asyncio.to_thread(journal.resolve)
        await asyncio.to_thread(extras.update_playbooks)
        for reminder in extra_status():
            await bot.notify(reminder, False)
        for page in await accounting.tax_summary():
            await bot.notify(page, False)
        await reports.weekly()
        return result

    async def auto_summary() -> str:
        if modes is None:
            raise ConfigurationError("An automatic summary needs the bound mode store")
        return daily_summary(settings, modes, await portfolio(), await asyncio.to_thread(tax.book))

    jobs = DeskJobs(
        desk,
        bot,
        commands,
        source,
        weekly,
        maintenance,
        fill_poll,
        refresh_request=source.refresh_request,
        accounting_capture=accounting.capture,
        pnl_digest=accounting.digest_line,
        auto_summary=None if modes is None else auto_summary,
        journal_sync=journal.sync,
        briefing=extras.briefing,
        veto_digest=journal.veto_digest,
    )
    watchdog = Watchdog(state, calendar, clock, lambda message: bot.notify(message, True))
    job_health = JobHealth(watchdog, policy, settings.healthcheck_ping_url)

    async def on_finished(run: JobRun) -> None:
        if modes is not None:
            proof = JobBinding(
                job_run_id=run.id,
                account_id=account_id,
                environment=modes.environment,
                config_hash=settings.config_hash,
            )
            state.ledger.append(
                SecurityEvent, kind="DESK_JOB_BINDING", detail=proof.model_dump(mode="json")
            )
        await job_health(run)

    orchestrator = Orchestrator(
        config,
        calendar,
        state,
        clock,
        jobs.bodies(),
        on_finished=on_finished,
        auto_tick=None if auto_jobs is None else auto_jobs.tick,
    )

    async def clock_read() -> object:
        return await reads.broker_clock(
            settings, settings.broker_api_key, settings.broker_secret_key
        )

    async def calendar_read(start: date, end: date) -> object:
        return await reads.broker_calendar(
            settings, settings.broker_api_key, settings.broker_secret_key, start, end
        )

    verifier = BrokerTimeVerifier(settings, calendar, clock, state, clock_read, calendar_read)

    async def doctor() -> DoctorResult:
        return verified_doctor

    async def close_resources() -> None:
        if stream is not None:
            await stream.aclose()
        if execution is not None:
            await execution.close()
        await reader.aclose()
        await resources.aclose()

    async def initialize_account() -> object:
        result = await fill_poll()
        state.ledger.append(
            SecurityEvent,
            kind="HOST_ACCOUNTING_READY",
            detail={
                "account_id": account_id,
                "environment": "PAPER" if settings.paper_trading else "LIVE",
                "config_hash": settings.config_hash,
            },
        )
        return result

    return HostRuntime(
        settings,
        state,
        orchestrator,
        bot,
        watchdog,
        project / "data/runtime-heartbeat.json",
        doctor,
        close_resources=close_resources,
        verify_broker_time=verifier.verify,
        initialize_account=initialize_account,
        modes=modes,
        start_execution=None if stream is None else stream.start,
    )


def _close_sdk(client: object) -> None:
    # VERIFY: pinned alpaca-py APIClient owns a requests.Session in _session.
    session = getattr(client, "_session", None)
    if isinstance(session, RequestsSession):
        session.close()


async def execute(env_file: Path | None) -> None:
    project = security_cli.PROJECT
    selected = project / ".env" if env_file is None else env_file
    store = KeyringSecretStore()
    settings = load_host_settings(project, selected, store)
    if settings.execution_mode == "MANUAL" and not settings.paper_trading:
        raise ConfigurationError(
            "MANUAL host start requires paper binding; AUTO_LIVE requires its full explicit unlock"
        )
    data = project / "data"
    if data.is_symlink() or data.parent.resolve(strict=True) != data.parent:
        raise ConfigurationError("Host data directory must be a direct private path")
    data.mkdir(mode=0o700, exist_ok=True)
    with ProcessLock(data / "runtime.lock"):
        context = security_cli.open_context(selected, store=store)
        try:
            if context.settings.config_hash != settings.config_hash:
                raise ConfigurationError("Startup settings changed while opening the host context")
            context.settings_source = lambda: load_host_settings(project, selected, store)
            result = await security_cli.doctor_result(context, store)
            for line in result.lines():
                print(line)
            if result.exit_code:
                raise ConfigurationError("Resolve all required doctor checks before starting")
            log = context.settings.log_file_path or project / "logs/vws.log"
            if not log.is_absolute():
                log = project / log
            configure_logging(
                log_path=log,
                retention_days=context.settings.log_retention_days,
                clock=context.ledger.clock,
            )
            context.drift.check(context.config_hash(), mode=context.settings.execution_mode)
            for name in ("reports", "history"):
                directory = data / name
                if directory.is_symlink():
                    raise ConfigurationError("Runtime evidence directory cannot be a link")
                directory.mkdir(mode=0o700, exist_ok=True)
            async with AsyncExitStack() as resources:
                runtime = await compose(context, store, result, resources=resources)
                stop = asyncio.Event()
                loop = asyncio.get_running_loop()

                def request_stop(_number: int, _frame: FrameType | None) -> None:
                    loop.call_soon_threadsafe(stop.set)

                previous = {
                    number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)
                }
                try:
                    for number in previous:
                        signal.signal(number, request_stop)
                    await runtime.run(stop)
                finally:
                    for number, handler in previous.items():
                        signal.signal(number, handler)
        finally:
            context.engine.dispose()
