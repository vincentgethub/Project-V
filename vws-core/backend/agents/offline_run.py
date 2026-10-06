"""GD-08/E acceptance: recorded synthetic inputs, RAM ledger, no network.

This acceptance harness cannot start the connected runtime or approve trades.
F builds the live provider composition and authenticated ticket lifecycle.
"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from backend.agents.expiry import proposal_expiry
from backend.agents.flow_tracker import FlowTracker
from backend.agents.fundamentals import compute_fundamentals, framework_allows
from backend.agents.indicators import IndicatorMemo
from backend.agents.llm_client import FakeLLMClient
from backend.agents.news_reader import NewsReader
from backend.agents.providers import NullEarningsProvider, NullIVProvider
from backend.agents.scanner import scan
from backend.agents.setup_hunter import SetupHunter
from backend.core.clock import FrozenClock
from backend.core.config import Settings, load_yaml_config
from backend.core.database import (
    Alert,
    DataSnapshot,
    Order,
    ResearchReport,
    Signal,
    create_database,
    create_schema,
)
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.data.data_layer import Bar
from backend.data.market_calendar import MarketCalendar
from backend.data.news import NewsInput, NewsProviderName, NewsResult, NewsStore
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    CapitalStatus,
    Decision,
    DeployableCapital,
    FrozenModel,
    Intent,
    MarketContext,
    MarketStatus,
    PortfolioSnapshot,
    ProposalSource,
    ProviderStatus,
    Side,
    Symbol,
    TradeProposal,
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
        fundamental = compute_fundamentals(registry.get(symbol), None, now, config.fundamentals)
        recorded = ledger.append(
            DataSnapshot,
            symbol=symbol,
            timeframe="1Day",
            range_start=bars[0].timestamp,
            range_end=bars[-1].timestamp,
            feed="IEX",
            adjustment="SPLIT",
            fetched_at=now,
            bar_count=len(bars),
            sha256=digest,
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
        for candidate in hunted.candidates if scanned.status.value == "OK" else ():
            signal = ledger.append(
                Signal,
                agent_name="SetupHunter",
                symbol=symbol,
                direction="BUY",
                confidence=candidate.score / 10,
                structured_thesis=candidate.model_dump(mode="json"),
                invalidation="stop or revalidation failure",
                data_snapshot_id=recorded.id,
                prompt_hash=None,
            )
            proposal = TradeProposal(
                proposal_id=uuid4(),
                signal_id=signal.id,
                account_id=snapshot.account_id,
                symbol=symbol,
                side=Side.BUY,
                intent=Intent.ENTRY,
                qty=candidate.qty,
                limit_price=candidate.entry_price,
                stop_price=candidate.stop_price,
                target_price=candidate.target_price,
                source=ProposalSource.SIGNAL,
                created_at=now,
                expires_at=proposal_expiry(now, settings.proposal_ttl_sessions, calendar),
            )
            first = risk.evaluate(proposal, snapshot, market, deployable=capital)
            if first.decision != Decision.APPROVED:
                vetoes.extend(
                    row.rule_id
                    for row in first.results
                    if not row.passed and row.severity.value == "BLOCK"
                )
                continue
            if not framework_allows(fundamental, config.fundamentals):
                dropped.append("FA-08: required fundamentals unavailable/failed")
                continue
            earnings, iv, flow = await asyncio.gather(
                NullEarningsProvider().get(symbol, now),
                NullIVProvider().get(symbol, now),
                FlowTracker().read(symbol, now),
            )
            market = MarketContext.model_validate({**market.model_dump(), "earnings": earnings})
            assessment = await reader.read(symbol, news, eligible=True)
            final = risk.evaluate(proposal, snapshot, market, deployable=capital)
            cmp = compliance.evaluate(
                proposal,
                snapshot,
                (),
                (),
                (ExternalAccount(account_id=snapshot.account_id, tax_status=TaxStatus.TAXABLE),),
                flags=AccountFlags(
                    trading_blocked=False,
                    account_blocked=False,
                    trade_suspended_by_user=False,
                    status="ACTIVE",
                ),
            )
            failed = tuple(
                row.rule_id
                for row in (*final.results, *cmp.results)
                if not row.passed and row.severity.value == "BLOCK"
            )
            if failed or state.current().value != "RUNNING":
                vetoes.extend(failed or ("CRO-01",))
                continue
            context = CardContext(
                candidate=candidate,
                proposal=proposal,
                snapshot=snapshot,
                verdict=final,
                compliance=cmp,
                fundamentals=fundamental,
                news=assessment,
                flow=flow,
                market_context="SPY unavailable (synthetic offline fixture)",
            )
            card = format_card(context, settings)
            ledger.append(
                Order,
                **proposal.model_dump(exclude={"created_at", "expires_at"}),
                client_order_id="offline-" + proposal.proposal_id.hex,
                order_type="LIMIT",
            )
            alert = ledger.append(
                Alert,
                proposal_id=proposal.proposal_id,
                signal_id=signal.id,
                symbol=symbol,
                playbook=candidate.playbook.value,
                score=candidate.score,
                status="PENDING",
                telegram_chat_id=None,
                telegram_message_id=None,
                card_text=card,
                config_hash=settings.config_hash,
                expires_at=proposal.expires_at,
            )
            for name, payload, status in (
                ("fundamentals", fundamental, "OK"),
                ("news", assessment, news.status.value),
                ("flow", flow, flow.status.value),
                ("iv", iv, iv.status.value),
                (
                    "earnings",
                    earnings,
                    "UNAVAILABLE" if earnings.status.value == "UNKNOWN" else "OK",
                ),
                ("cro", final, "OK"),
                ("compliance", cmp, "OK"),
            ):
                ledger.append(
                    ResearchReport,
                    alert_id=alert.id,
                    agent_name=name,
                    status=status,
                    payload=payload.model_dump(mode="json"),
                    prompt_hash=None,
                )
            cards.append(card)
            contexts.append(context)
            previews.append(manual_instructions(proposal, settings))
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
