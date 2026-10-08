"""OPS-02: connected MANUAL paper composition, only on explicit host start."""

import asyncio
import signal
from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import FrameType
from typing import TypeVar

from requests import Session as RequestsSession

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
from backend.data.fill_polling import TicketFillMatcher
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
from backend.domain.models import PortfolioSnapshot
from backend.evaluation.ledger_source import LedgerWeeklySource
from backend.evaluation.publication import WeeklyPublisher
from backend.funding.activities import AlpacaActivitiesSource
from backend.notifications.callbacks import ApprovalGate
from backend.notifications.telegram_bot import TelegramBot
from backend.ops.account_context import LedgerAccountContext
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.doctor import DoctorResult
from backend.ops.job_health import JobHealth
from backend.ops.maintenance import NightlyMaintenance
from backend.ops.process import ProcessLock
from backend.ops.read_checks import ReadChecksClient
from backend.ops.runtime import HostRuntime
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
from vws.host_config import load_host_settings

ReadT = TypeVar("ReadT")


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


async def compose(
    context: security_cli.SecurityContext,
    store: SecretStore,
    verified_doctor: DoctorResult,
    *,
    resources: AsyncExitStack,
) -> HostRuntime:
    if context.settings.broker_state_source != "ALPACA":
        raise ConfigurationError(MANUAL_CSV_DISABLED_MESSAGE)
    if (
        verified_doctor.exit_code != 0
        or context.settings.execution_mode != "MANUAL"
        or not context.settings.paper_trading
    ):
        raise ConfigurationError(
            "Connected composition requires verified required checks and MANUAL paper mode"
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
    account = await reads.paper_account(settings.broker_api_key, settings.broker_secret_key)
    account_id = str(account.account_id)
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
    risk, compliance = (
        RiskBoundary(cro, state, clock, marks=marks),
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
        LedgerAccountContext(state, account_id, "PAPER"),
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
    gate = ApprovalGate(settings, config, state, risk, compliance, clock, source)
    commands = DeskCommands(state, settings, account_id, calendar, source)
    bot = TelegramBot(settings, state, clock, gate, policy, commands.handlers())
    fill_source = AlpacaActivitiesSource(settings, account_id, state, clock, reader, policy)
    resources.push_async_callback(fill_source.close)
    matcher = TicketFillMatcher(settings, account_id, state, registry)

    async def portfolio() -> PortfolioSnapshot:
        return (await boundary.portfolio_async(reader)).snapshot

    schedule = load_fee_schedule(project / "config/fees.yaml")

    async def prepare_fills(symbols: tuple[str, ...]) -> None:
        start = calendar.previous_sessions(calendar.last_completed_session(clock.now()), 280)[0]
        for offset in range(0, len(symbols), 199):
            await market.completed_daily_bars(symbols[offset : offset + 199], start)

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
        observe_fill=matcher.record,
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
    bot.commands.update({"/pnl": accounting.pnl, "/tax": accounting.tax_summary})

    async def sync_context() -> None:
        await tax.sync()

    source.sync_account_context = sync_context

    async def fill_poll() -> JobCounts:
        return await tax.sync(force=True)

    async def maintenance() -> JobCounts:
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
        for page in await accounting.tax_summary():
            await bot.notify(page, False)
        return result

    jobs = DeskJobs(
        Desk(swarm),
        bot,
        commands,
        source,
        weekly,
        maintenance,
        fill_poll,
        refresh_request=source.refresh_request,
        accounting_capture=accounting.capture,
        pnl_digest=accounting.digest_line,
    )
    watchdog = Watchdog(state, calendar, clock, lambda message: bot.notify(message, True))
    orchestrator = Orchestrator(
        config,
        calendar,
        state,
        clock,
        jobs.bodies(),
        on_finished=JobHealth(watchdog, policy, settings.healthcheck_ping_url),
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
        await reader.aclose()
        await resources.aclose()

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
        initialize_account=fill_poll,
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
    if settings.execution_mode != "MANUAL" or not settings.paper_trading:
        raise ConfigurationError(
            "Stage H start accepts only MANUAL paper; automatic modes remain locked"
        )
    data = project / "data"
    if data.is_symlink() or data.parent.resolve(strict=True) != data.parent:
        raise ConfigurationError("Host data directory must be a direct private path")
    data.mkdir(mode=0o700, exist_ok=True)
    with ProcessLock(data / "runtime.lock"):
        context = security_cli.open_context(selected, store=store)
        try:
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
            context.drift.check(context.config_hash(), mode="MANUAL")
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
