"""GD-08/E acceptance: recorded synthetic inputs, RAM ledger, no network.

This acceptance harness cannot start the connected runtime or approve trades.
F builds the live provider composition and authenticated ticket lifecycle.
"""

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import Field

from backend.agents.indicators import IndicatorMemo
from backend.agents.llm_client import FakeLLMClient
from backend.agents.news_reader import NewsReader
from backend.agents.scanner import scan
from backend.agents.setup_hunter import SetupHunter
from backend.agents.swarm_runner import ResearchRequest, SwarmRunner
from backend.core.clock import FrozenClock
from backend.core.config import Settings, load_yaml_config
from backend.core.database import (
    DataSnapshot,
    create_database,
    create_schema,
)
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.data.data_layer import Bar, _bars_digest
from backend.data.market_calendar import MarketCalendar
from backend.data.news import NewsInput, NewsProviderName, NewsResult, NewsStore
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    CapitalStatus,
    DeployableCapital,
    FrozenModel,
    MarketContext,
    MarketStatus,
    PortfolioSnapshot,
    ProviderStatus,
    Symbol,
    validate_symbol,
)
from backend.notifications.card_formatter import CardContext, format_card, manual_instructions
from backend.risk.boundary import RiskBoundary
from backend.risk.compliance import ComplianceEngine, ExternalAccount, TaxStatus
from backend.risk.compliance_boundary import ComplianceBoundary


class OfflineResult(FrozenModel):
    symbol: Symbol
    cards: tuple[str, ...] = Field(max_length=3)
    previews: tuple[str, ...] = Field(max_length=3)
    contexts: tuple[CardContext, ...] = Field(max_length=3)
    veto_ids: tuple[str, ...]
    dropped: tuple[str, ...]
    llm_calls: int
    ledger_verified: bool = Field(strict=True)


async def offline_run(symbol: str, *, require_fundamentals: bool = False) -> OfflineResult:
    try:
        return await _offline_run(symbol, require_fundamentals=require_fundamentals)
    except (ConfigurationError, DataIntegrityError):
        raise
    except Exception:
        raise DataIntegrityError("GD-08: offline evidence or pipeline failed validation") from None


async def _offline_run(symbol: str, *, require_fundamentals: bool) -> OfflineResult:
    """No env file, keyring, SDK, Telegram or persistent ledger is opened."""
    validate_symbol(symbol)
    if symbol != "NVDA":
        raise ConfigurationError("GD-08: only the recorded synthetic NVDA fixture is available")
    project = Path(__file__).resolve().parents[2]
    raw = (project / "backend/tests/fixtures/offline_nvda.json").read_bytes()
    if len(raw) > 1_000_000:
        raise DataIntegrityError("GD-08: offline fixture exceeds its boundary")
    fixture = json.loads(raw)
    if fixture["kind"] != "SYNTHETIC_OFFLINE" or fixture["symbol"] != symbol:
        raise DataIntegrityError("GD-08: offline fixture identity is invalid")
    now = datetime.fromisoformat(fixture["as_of"])
    clock = FrozenClock(now)
    calendar = MarketCalendar()
    # BaseSettings' direct Pydantic validator avoids every ambient env source.
    base = Settings.__new__(Settings)
    Settings.__pydantic_validator__.validate_python(
        {"broker_account_type": "CASH"}, self_instance=base
    )
    settings = Settings.validated_copy(base)
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    if require_fundamentals:
        config = type(config).model_validate(
            {
                **config.model_dump(),
                "fundamentals": {**config.fundamentals.model_dump(), "mode": "require"},
            }
        )
    bars = tuple(
        Bar.model_validate(
            {
                **row,
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                **{name: Decimal(row[name]) for name in ("open", "high", "low", "close")},
            }
        )
        for row in fixture["bars"]
    )
    database = create_database("sqlite:///:memory:")
    create_schema(database)
    try:
        state = SystemStateStore(database, clock, ConsoleNotifier())
        ledger = state.ledger
        snapshot = PortfolioSnapshot(
            account_id="synthetic-paper-fixture",
            account_type=AccountType.CASH,
            as_of=now,
            equity=Decimal("10000"),
            cash=Decimal("10000"),
            settled_cash=Decimal("10000"),
            positions={},
            open_orders=(),
            high_water_mark=Decimal("10000"),
            day_start_equity=Decimal("10000"),
        )
        market = MarketContext(
            last_price=bars[-1].close,
            last_price_ts=now,
            adv20_usd=Decimal("100000000"),
            status=MarketStatus.OK,
        )
        capital = DeployableCapital(
            checking_used=Decimal("5000"),
            buffer=Decimal("1500"),
            reserved=Decimal("0"),
            deployable=Decimal("3500"),
            status=CapitalStatus.OK,
        )
        from backend.risk.risk_cro import ChiefRiskOfficer

        cro = ChiefRiskOfficer(settings, registry, calendar)
        risk = RiskBoundary(cro, state, clock)
        compliance = ComplianceBoundary(
            ComplianceEngine(settings, registry, calendar), state, clock
        )
        memo = IndicatorMemo()
        digest = hashlib.sha256(raw).hexdigest()
        scanned = scan(
            symbol,
            bars,
            now=now,
            calendar=calendar,
            data_snapshot_hash=digest,
            market_status=market.status,
            memo=memo,
        )
        hunted = SetupHunter(cro, config, memo).hunt(symbol, bars, snapshot, market, now)
        recorded = ledger.append(
            DataSnapshot,
            symbol=symbol,
            timeframe="1Day",
            range_start=bars[0].timestamp,
            range_end=bars[-1].timestamp,
            feed="FAKE",
            adjustment="SPLIT",
            fetched_at=now,
            bar_count=len(bars),
            sha256=_bars_digest(bars)[0],
            bars=[bar.model_dump(mode="json") for bar in bars],
        )
        news_store = NewsStore(ledger)
        news = NewsResult(
            provider=NewsProviderName.FAKE,
            status=ProviderStatus.OK,
            as_of=now,
            reason="Recorded synthetic offline fixture",
            headlines=news_store.ingest(
                NewsProviderName.FAKE,
                tuple(
                    NewsInput(
                        provider_id=f"offline-{i}",
                        headline=title,
                        published_at=now - timedelta(hours=1),
                        symbols=(symbol,),
                    )
                    for i, title in enumerate(fixture["headlines"])
                ),
            ),
        )
        reader = NewsReader(settings, FakeLLMClient())
        cards: list[str] = []
        previews: list[str] = []
        contexts: list[CardContext] = []
        vetoes: list[str] = []
        dropped = [f"{row.playbook.value}: {row.reason}" for row in hunted.drops]

        class RecordedNews:
            async def fetch(
                self, symbols: tuple[str, ...], start: datetime, end: datetime
            ) -> NewsResult:
                return news

        swarm = SwarmRunner(
            settings,
            config,
            risk,
            compliance,
            state,
            clock,
            reader,
            news=RecordedNews(),
            memo=memo,
            offline=True,
        )
        for candidate in hunted.candidates if scanned.status.value == "OK" else ():
            result = await swarm.run(
                ResearchRequest(
                    candidate=candidate,
                    data_snapshot_id=recorded.id,
                    portfolio=snapshot,
                    market=market,
                    capital=capital,
                    tax_accounts=(
                        ExternalAccount(
                            account_id=snapshot.account_id, tax_status=TaxStatus.TAXABLE
                        ),
                    ),
                    flags=AccountFlags(
                        trading_blocked=False,
                        account_blocked=False,
                        trade_suspended_by_user=False,
                        status="ACTIVE",
                    ),
                )
            )
            if result.status == "DROPPED":
                dropped.extend(result.reasons)
            elif result.status == "VETOED":
                vetoes.extend(result.reasons)
            elif result.context is not None and result.proposal is not None:
                cards.append(format_card(result.context, settings))
                contexts.append(result.context)
                previews.append(manual_instructions(result.proposal, settings))
        ledger.verify_chain()
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session

        from backend.core.database import LLMCall

        with Session(database) as session:
            count = int(session.scalar(select(func.count()).select_from(LLMCall)) or 0)
        return OfflineResult(
            symbol=symbol,
            cards=tuple(cards),
            previews=tuple(previews),
            contexts=tuple(contexts),
            veto_ids=tuple(sorted(set(vetoes))),
            dropped=tuple(dropped),
            llm_calls=count,
            ledger_verified=True,
        )
    finally:
        database.dispose()
