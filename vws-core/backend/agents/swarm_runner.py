"""GD-03/FA-08: bounded public research and two deterministic defense checks.

Only local evidence is written. Delivery and authenticated manual approval are
separate boundaries. No executor is imported or broker order is submitted.
"""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.expiry import proposal_expiry
from backend.agents.flow_tracker import FlowTracker
from backend.agents.fundamentals import (
    FrameworkStatus,
    FundamentalReport,
    compute_fundamentals,
    framework_allows,
)
from backend.agents.indicators import IndicatorMemo
from backend.agents.news_reader import NewsReader
from backend.agents.peer_strength import NullPeerProvider, PeerProvider, PeerStrength
from backend.agents.providers import (
    EarningsProvider,
    IVComparison,
    IVProvider,
    NullEarningsProvider,
    NullIVProvider,
)
from backend.agents.setup_hunter import SetupHunter, score_eligible
from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings, YamlConfig
from backend.core.database import (
    Alert,
    ComplianceCheck,
    DataSnapshot,
    Order,
    ResearchReport,
    RiskDecision,
    RiskRuleResult,
    SecurityEvent,
    Signal,
)
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EgressDeniedError,
    ProviderError,
)
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.data_layer import AsyncAlpacaMarketData, Bar, _bars_digest
from backend.data.news import NewsProvider, NewsProviderName, NewsResult
from backend.data.sec_edgar import SecPayload
from backend.domain.compliance_models import ExternalAccount, TaxLot, TradeRecord
from backend.domain.models import (
    AccountFlags,
    Decision,
    DeployableCapital,
    EarningsInfo,
    EarningsStatus,
    FlowSignal,
    FrozenModel,
    Intent,
    MarketContext,
    PortfolioSnapshot,
    ProposalSource,
    ProviderStatus,
    SetupCandidate,
    Side,
    TradeProposal,
    Verdict,
)
from backend.notifications.card_formatter import CardContext, format_card
from backend.risk.boundary import RiskBoundary
from backend.risk.compliance import ComplianceAssessment
from backend.risk.compliance_boundary import ComplianceBoundary

_NAMESPACE = UUID("b8a7dc1f-b9c7-4705-9e6c-d980065a7b3a")


class FundamentalProvider(Protocol):
    async def cik_for(self, symbol: str) -> str: ...
    async def companyfacts(self, symbol: str) -> SecPayload: ...


class ResearchRequest(FrozenModel):
    candidate: SetupCandidate
    data_snapshot_id: UUID
    portfolio: PortfolioSnapshot
    market: MarketContext
    capital: DeployableCapital | None = None
    flags: AccountFlags | None = None
    lots: tuple[TaxLot, ...] = Field(default=(), max_length=10000)
    history: tuple[TradeRecord, ...] = Field(default=(), max_length=100000)
    tax_accounts: tuple[ExternalAccount, ...] = Field(default=(), max_length=1000)


class SwarmResult(FrozenModel):
    status: Literal["DROPPED", "VETOED", "ALERT"]
    proposal: TradeProposal | None = None
    alert_id: UUID | None = None
    context: CardContext | None = None
    reasons: tuple[str, ...] = Field(default=(), max_length=30)
    unavailable: tuple[str, ...] = Field(default=(), max_length=6)


class SwarmRunner:
    def __init__(
        self,
        settings: Settings,
        config: YamlConfig,
        risk: RiskBoundary,
        compliance: ComplianceBoundary,
        state: SystemStateStore,
        clock: Clock,
        news_reader: NewsReader,
        *,
        news: NewsProvider | None = None,
        fundamentals: FundamentalProvider | None = None,
        peers: PeerProvider | None = None,
        earnings: EarningsProvider | None = None,
        iv: IVProvider | None = None,
        flow: FlowTracker | None = None,
        timeout_seconds: int = 30,
        concurrency: int = 4,
        memo: IndicatorMemo | None = None,
        offline: bool = False,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.config = YamlConfig.model_validate(config)
        self.config.assert_settings_consistent(self.settings)
        if (
            type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 30
            or type(concurrency) is not int
            or not 1 <= concurrency <= 8
        ):
            raise ConfigurationError("GD-03: research deadline/concurrency out of bounds")
        if (
            risk.state is not state
            or compliance.state is not state
            or risk.cro.config.config_hash != self.settings.config_hash
            or compliance.engine.config.config_hash != self.settings.config_hash
            or news_reader.settings.config_hash != self.settings.config_hash
            or state.clock is not clock
            or risk.clock is not clock
            or compliance.clock is not clock
        ):
            raise ConfigurationError("GD-03: research defense policies/state differ")
        self.risk, self.compliance, self.state, self.clock = risk, compliance, state, clock
        self.ledger: Ledger = state.ledger
        self.news_reader, self.news, self.fundamentals = news_reader, news, fundamentals
        self.peers, self.earnings, self.iv = (
            peers or NullPeerProvider(),
            earnings or NullEarningsProvider(),
            iv or NullIVProvider(),
        )
        self.flow = flow or FlowTracker()
        self.timeout_seconds = timeout_seconds
        self._slots = asyncio.Semaphore(concurrency)
        self.hunter = SetupHunter(risk.cro, self.config, memo or IndicatorMemo())
        if type(offline) is not bool or (
            offline and self.ledger.engine.url.database not in {None, "", ":memory:"}
        ):
            raise ConfigurationError("GD-08: offline research requires an in-memory ledger")
        self.offline = offline
        if not offline and risk.marks is None:
            raise ConfigurationError("GD-03: connected research requires persisted financial marks")

    def _verify_candidate(self, request: ResearchRequest, now: datetime) -> None:
        """Rebuild the entire immutable incremental bar cache, then re-score.

        The caller's source UUID caps the cache at that recorded revision. A
        later snapshot cannot repair or silently revise the supplied evidence.
        """
        c = request.candidate
        with Session(self.ledger.engine) as session:
            source = session.get(DataSnapshot, request.data_snapshot_id)
            if source is None or source.symbol != c.symbol or source.fetched_at > c.as_of:
                raise DataIntegrityError("GD-03: candidate lacks bound bar provenance")
            if (source.feed, source.adjustment) != (
                ("FAKE", "ALL") if self.offline else ("SIP", "ALL")
            ):
                raise DataIntegrityError("DAT-07: candidate requires bound completed daily feed")
            records = tuple(
                session.scalars(
                    select(DataSnapshot)
                    .where(
                        DataSnapshot.symbol == c.symbol,
                        DataSnapshot.timeframe == "1Day",
                        DataSnapshot.feed == source.feed,
                        DataSnapshot.adjustment == source.adjustment,
                        DataSnapshot.seq <= source.seq,
                    )
                    .order_by(DataSnapshot.seq)
                    .limit(10001)
                )
            )
        by_session: dict[date, Bar] = {}
        if len(records) > 10000:
            raise DataIntegrityError("GD-03: candidate cache exceeds the bounded provenance window")
        observations = 0
        for record in records:
            observations += record.bar_count
            if observations > 100000 or record.fetched_at > now:
                raise DataIntegrityError("GD-03: candidate cache size/time is unverifiable")
            bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in record.bars)
            if (
                not bars
                or record.fetched_at > c.as_of
                or record.bar_count != len(bars)
                or record.sha256 != _bars_digest(bars)[0]
                or record.range_start != bars[0].timestamp
                or record.range_end != bars[-1].timestamp
            ):
                raise DataIntegrityError("GD-03: candidate bar digest/range is invalid")
            previous = None
            for bar in bars:
                bar.validate_integrity()
                if previous is not None and bar.session_date <= previous:
                    raise DataIntegrityError("GD-03: candidate bar sessions are unordered")
                previous = bar.session_date
                close = self.risk.cro.calendar.session_close(bar.session_date)
                if close + timedelta(seconds=0 if self.offline else 960) > record.fetched_at:
                    raise DataIntegrityError("GD-03: candidate uses an incomplete recorded session")
                existing = by_session.get(bar.session_date)
                if existing is not None and existing != bar:
                    raise DataIntegrityError("GD-03: conflicting immutable bar revisions")
                by_session[bar.session_date] = bar
        rebuilt = self.hunter.hunt(
            c.symbol,
            tuple(by_session[d] for d in sorted(by_session)),
            request.portfolio,
            request.market,
            c.as_of,
        )
        if c not in rebuilt.candidates:
            raise DataIntegrityError("GD-03: candidate score/levels/size differ from recorded bars")

    async def _bounded(self, call: Callable[[], Awaitable[object]]) -> object:
        async with asyncio.timeout(self.timeout_seconds):
            async with self._slots:
                return await call()

    async def _fundamental(self, symbol: str, as_of: datetime) -> FundamentalReport:
        instrument = self.risk.cro.registry.get(symbol)
        unavailable = compute_fundamentals(instrument, None, as_of, self.config.fundamentals)
        if (
            unavailable.framework_status == FrameworkStatus.NOT_APPLICABLE
            or self.fundamentals is None
        ):
            return unavailable
        expected_cik = await self.fundamentals.cik_for(symbol)
        payload = SecPayload.model_validate(await self.fundamentals.companyfacts(symbol))
        if payload.cik != expected_cik or payload.fetched_at > ensure_utc(self.clock.now()):
            raise DataIntegrityError("FA-02: filing provenance issuer/time differs")
        return compute_fundamentals(instrument, payload, as_of, self.config.fundamentals)

    async def _news(self, symbol: str, as_of: datetime) -> NewsResult:
        if self.news is None:
            return NewsResult(
                provider=NewsProviderName.ALPACA,
                status=ProviderStatus.UNAVAILABLE,
                as_of=as_of,
                reason="news provider unconfigured",
            )
        return await self.news.fetch((symbol,), as_of - timedelta(days=1), as_of)

    def _audit_risk(self, verdict: Verdict) -> None:
        decision = self.ledger.append(
            RiskDecision,
            proposal_id=verdict.proposal_id,
            decision=verdict.decision.value,
            config_hash=verdict.config_hash,
            snapshot_hash=verdict.snapshot_hash,
            evaluated_at=verdict.evaluated_at,
        )
        for row in verdict.results:
            self.ledger.append(
                RiskRuleResult,
                risk_decision_id=decision.id,
                rule_id=row.rule_id,
                passed=int(row.passed),
                severity=row.severity.value,
                observed={"text": row.observed},
                limit={"text": row.limit},
                message=row.message,
            )

    def _audit_compliance(self, proposal: TradeProposal, assessment: ComplianceAssessment) -> None:
        for row in assessment.results:
            self.ledger.append(
                ComplianceCheck,
                proposal_id=proposal.proposal_id,
                rule_id=row.rule_id,
                passed=int(row.passed),
                severity=row.severity.value,
                observed={"text": row.observed},
                limit={"text": row.limit},
                message=row.message,
                checked_at=assessment.evaluated_at,
            )

    def _proposal(self, request: ResearchRequest, now: datetime) -> TradeProposal:
        c = request.candidate
        identity = hashlib.sha256(
            json.dumps(
                {
                    "snapshot": str(request.data_snapshot_id),
                    "candidate": c.model_dump(mode="json"),
                    "account": request.portfolio.account_id,
                    "config": self.settings.config_hash,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        proposal_id = uuid5(_NAMESPACE, identity)
        with Session(self.ledger.engine) as session:
            existing = session.scalar(select(Order).where(Order.proposal_id == proposal_id))
            if existing is not None:
                raise DataIntegrityError(
                    "GD-03: repeated candidate must be suppressed by the orchestrator"
                )
        signal = self.ledger.append(
            Signal,
            agent_name="SetupHunter",
            symbol=c.symbol,
            direction="BUY",
            confidence=c.score / 10,
            structured_thesis={
                "setup": c.model_dump(mode="json"),
                "confidence_kind": "uncalibrated score fraction",
            },
            invalidation="stop or fresh revalidation failure",
            data_snapshot_id=request.data_snapshot_id,
            prompt_hash=None,
        )
        p = TradeProposal(
            proposal_id=proposal_id,
            signal_id=signal.id,
            account_id=request.portfolio.account_id,
            symbol=c.symbol,
            side=Side.BUY,
            intent=Intent.ENTRY,
            qty=c.qty,
            limit_price=c.entry_price,
            stop_price=c.stop_price,
            target_price=c.target_price,
            source=ProposalSource.SIGNAL,
            created_at=now,
            expires_at=proposal_expiry(
                now, self.settings.proposal_ttl_sessions, self.risk.cro.calendar
            ),
        )
        self.ledger.append(
            Order,
            **p.model_dump(exclude={"created_at", "expires_at"}),
            client_order_id="vws-research-" + p.proposal_id.hex,
            order_type="LIMIT",
        )
        return p

    async def run(self, request: ResearchRequest) -> SwarmResult:
        """Typed failures audit and HALT; expected public outages stay visible.

        Order rows below are immutable local proposals, not broker requests.
        This method does not deliver alerts or authenticate human decisions.
        """
        try:
            return await self._run(ResearchRequest.model_validate(request))
        except asyncio.CancelledError:
            self.state.escalate(SystemState.HALTED, "GD-03 research cycle cancelled")
            raise
        except Exception as exc:
            try:
                self.state.halt_for_error(exc)
                self.ledger.append(
                    SecurityEvent, kind="RESEARCH_FAULT", detail={"error_type": type(exc).__name__}
                )
            except Exception:
                raise DataIntegrityError("GD-03: research fault; HALT/audit unavailable") from None
            raise DataIntegrityError("GD-03: invalid research halted entries") from None

    async def _run(self, request: ResearchRequest) -> SwarmResult:
        now = ensure_utc(self.clock.now())
        c = request.candidate
        self.ledger.verify_chain()
        if c.symbol not in self.config.watchlist or not timedelta(0) <= now - c.as_of <= timedelta(
            seconds=self.timeout_seconds
        ):
            raise DataIntegrityError("GD-03: candidate is outside the current cycle/watchlist")
        self._verify_candidate(request, now)
        if not score_eligible(c.score, self.settings.min_setup_score):
            self.ledger.append(
                SecurityEvent,
                kind="SETUP_DROPPED",
                detail={"symbol": c.symbol, "playbook": c.playbook.value, "reason": "score"},
            )
            return SwarmResult(status="DROPPED", reasons=("score below minimum",))
        p = self._proposal(request, now)
        first = self.risk.evaluate(p, request.portfolio, request.market, deployable=request.capital)
        self._audit_risk(first)
        if first.decision != Decision.APPROVED:
            return SwarmResult(
                status="VETOED",
                proposal=p,
                reasons=tuple(
                    row.rule_id
                    for row in first.results
                    if not row.passed and row.severity.value == "BLOCK"
                ),
            )
        # Fundamentals always precede the optional paid call.
        try:
            fundamental = FundamentalReport.model_validate(
                await self._bounded(lambda: self._fundamental(c.symbol, now))
            )
        except EgressDeniedError:
            raise
        except (TimeoutError, ProviderError) as exc:
            self.ledger.append(
                SecurityEvent,
                kind="RESEARCH_UNAVAILABLE",
                detail={
                    "symbol": c.symbol,
                    "agent": "fundamentals",
                    "error_type": type(exc).__name__,
                },
            )
            fundamental = compute_fundamentals(
                self.risk.cro.registry.get(c.symbol), None, now, self.config.fundamentals
            )
        if not framework_allows(fundamental, self.config.fundamentals):
            self.ledger.append(
                SecurityEvent,
                kind="SETUP_DROPPED",
                detail={
                    "symbol": c.symbol,
                    "playbook": c.playbook.value,
                    "reason": "FA-08",
                    "fundamentals": fundamental.model_dump(mode="json"),
                },
            )
            return SwarmResult(
                status="DROPPED",
                proposal=p,
                reasons=(
                    "FA-08: required fundamentals unavailable/failed",
                    *fundamental.failure_reasons,
                ),
            )
        names = ("peers", "earnings", "iv", "flow", "news")
        values = list(
            await asyncio.gather(
                self._bounded(lambda: self.peers.get(c.symbol, now)),
                self._bounded(lambda: self.earnings.get(c.symbol, now)),
                self._bounded(lambda: self.iv.get(c.symbol, now)),
                self._bounded(lambda: self.flow.read(c.symbol, now)),
                self._bounded(lambda: self._news(c.symbol, now)),
                return_exceptions=True,
            )
        )
        unavailable: list[str] = []
        for i, (name, value) in enumerate(zip(names, values, strict=True)):
            if isinstance(value, EgressDeniedError):
                raise DataIntegrityError("SEC-31: public research egress was denied")
            if isinstance(value, (TimeoutError, ProviderError)):
                self.ledger.append(
                    SecurityEvent,
                    kind="RESEARCH_UNAVAILABLE",
                    detail={"symbol": c.symbol, "agent": name, "error_type": type(value).__name__},
                )
                unavailable.append(name)
                values[i] = None
            elif isinstance(value, BaseException):
                raise DataIntegrityError("GD-03: unexpected public provider fault")
        peer = (
            PeerStrength.model_validate(values[0])
            if values[0] is not None
            else await NullPeerProvider().get(c.symbol, now)
        )
        earnings = (
            EarningsInfo.model_validate(values[1])
            if values[1] is not None
            else EarningsInfo(status=EarningsStatus.UNKNOWN, source="provider unavailable")
        )
        iv = (
            IVComparison.model_validate(values[2])
            if values[2] is not None
            else await NullIVProvider().get(c.symbol, now)
        )
        flow = (
            FlowSignal.model_validate(values[3])
            if values[3] is not None
            else FlowSignal(status=ProviderStatus.UNAVAILABLE)
        )
        news = (
            NewsResult.model_validate(values[4])
            if values[4] is not None
            else NewsResult(
                provider=NewsProviderName.ALPACA,
                status=ProviderStatus.UNAVAILABLE,
                as_of=now,
                reason="provider unavailable",
            )
        )
        if (
            peer.symbol != c.symbol
            or iv.symbol != c.symbol
            or peer.as_of != now
            or iv.as_of != now
            or news.as_of > ensure_utc(self.clock.now())
        ):
            raise DataIntegrityError("GD-03: research returned wrong symbol/time")
        if any(c.symbol not in row.symbols for row in news.headlines if row.symbols):
            raise DataIntegrityError("GD-03: news returned another symbol's facts")
        market = MarketContext.model_validate(
            {
                **request.market.model_dump(),
                "next_earnings_date": earnings.date
                if earnings.status == EarningsStatus.KNOWN
                else None,
                "earnings": earnings,
            }
        )
        summary = await self.news_reader.read(c.symbol, news, eligible=True)
        final = self.risk.evaluate(p, request.portfolio, market, deployable=request.capital)
        self._audit_risk(final)
        compliance = self.compliance.evaluate(
            p,
            request.portfolio,
            request.lots,
            request.history,
            request.tax_accounts,
            flags=request.flags,
        )
        self._audit_compliance(p, compliance)
        reasons = tuple(
            row.rule_id
            for row in (*final.results, *compliance.results)
            if not row.passed and row.severity.value == "BLOCK"
        )
        if reasons or self.state.current() != SystemState.RUNNING:
            return SwarmResult(
                status="VETOED",
                proposal=p,
                reasons=reasons or ("CRO-01",),
                unavailable=tuple(unavailable),
            )
        context_text = "SPY unavailable; peer context unavailable"
        if peer.status == ProviderStatus.OK:
            context_text = "SPY " + ("above" if peer.spy_above_ema200 else "below") + " 200-day avg"
        if iv.status != ProviderStatus.OK:
            context_text += "; IV/HV unavailable"
        context = CardContext(
            candidate=c,
            proposal=p,
            snapshot=request.portfolio,
            verdict=final,
            compliance=compliance,
            fundamentals=fundamental,
            news=summary,
            flow=flow,
            market_context=context_text,
        )
        card = format_card(context, self.settings)
        alert = self.ledger.append(
            Alert,
            proposal_id=p.proposal_id,
            signal_id=p.signal_id,
            symbol=c.symbol,
            playbook=c.playbook.value,
            score=c.score,
            status="PENDING",
            telegram_chat_id=None,
            telegram_message_id=None,
            card_text=card,
            config_hash=self.settings.config_hash,
            expires_at=p.expires_at,
        )
        facts = (
            (
                "fundamentals",
                fundamental,
                ProviderStatus.UNAVAILABLE
                if fundamental.framework_status == FrameworkStatus.INCOMPLETE
                else ProviderStatus.OK,
            ),
            ("peers", peer, peer.status),
            (
                "earnings",
                earnings,
                ProviderStatus.UNAVAILABLE
                if earnings.status == EarningsStatus.UNKNOWN
                else ProviderStatus.OK,
            ),
            ("iv", iv, iv.status),
            ("flow", flow, flow.status),
            ("news", summary, news.status),
        )
        for name, payload, status in facts:
            self.ledger.append(
                ResearchReport,
                alert_id=alert.id,
                agent_name=name,
                status=status.value,
                payload=payload.model_dump(mode="json"),
                prompt_hash=None,
            )
            if status != ProviderStatus.OK and name not in unavailable:
                unavailable.append(name)
        self.ledger.append(
            ResearchReport,
            alert_id=alert.id,
            agent_name="desk_policy",
            status="OK",
            payload={"yaml_hash": self.config.config_hash},
        )
        return SwarmResult(
            status="ALERT",
            proposal=p,
            alert_id=alert.id,
            context=context,
            unavailable=tuple(unavailable),
        )
