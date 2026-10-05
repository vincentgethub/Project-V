"""R-02/R-03/R-08: audited, serialized orchestration around pure risk rules."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import (
    ComplianceCheck,
    ConfigSnapshot,
    Order,
    OrderEvent,
    PortfolioState,
    RiskDecision,
    RiskRuleResult,
    Signal,
    transaction,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemStateStore
from backend.data.broker_state import BrokerStateProvider
from backend.data.data_layer import DataLayer, ResilientReader
from backend.data.liquidity import LiquidityGate
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    AccountFlags,
    Decision,
    DeployableCapital,
    Intent,
    MarketContext,
    OpenOrder,
    PortfolioSnapshot,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    Verdict,
    snapshot_hash,
)
from backend.risk.compliance import ComplianceEngine, ExternalAccount, TaxLot, TradeRecord
from backend.risk.risk_cro import ChiefRiskOfficer


class PersistedPortfolioMarks:
    """CRO-09/CRO-10: inject persisted managed-account drawdown baselines.

    Initial observation starts both baselines at equity. Operators must record
    external cash flows before observing post-flow equity. No money is moved.
    Daily baseline rollover never resets a latched REDUCE_ONLY/HALTED state.
    """

    def __init__(self, ledger: Ledger, account_id: str, calendar: MarketCalendar) -> None:
        self.ledger = ledger
        self.account_id = account_id
        self.calendar = calendar

    def __call__(self, equity: Decimal, now: datetime) -> tuple[Decimal, Decimal]:
        instant = ensure_utc(now)
        with transaction(self.ledger.engine) as session:
            previous = session.scalar(
                select(PortfolioState)
                .where(PortfolioState.account_id == self.account_id)
                .order_by(PortfolioState.seq.desc())
                .limit(1)
            )
            if previous is None:
                return equity, equity
            if instant < previous.as_of:
                raise DataIntegrityError("CRO-09: portfolio observation moved backward")
            current_session = self._session(instant)
            previous_session = self._session(previous.as_of)
            daily = equity if current_session > previous_session else previous.day_start_equity
            return max(previous.high_water_mark, equity), daily

    def _session(self, instant: datetime) -> date:
        if self.calendar.is_open(instant):
            from zoneinfo import ZoneInfo

            return instant.astimezone(ZoneInfo("America/New_York")).date()
        return self.calendar.last_completed_session(instant)


class DefensiveGate:
    """R-02/R-03: broker/data reads and audit writes never enter CRO rule logic."""

    def __init__(
        self,
        config: Settings,
        clock: Clock,
        state: SystemStateStore,
        ledger: Ledger,
        cro: ChiefRiskOfficer,
        compliance: ComplianceEngine,
    ) -> None:
        self.config = config
        self.clock = clock
        self.state = state
        self.ledger = ledger
        self.cro = cro
        self.compliance = compliance

    def _fault_verdict(self, proposal: TradeProposal, error: Exception) -> Verdict:
        self.state.halt_for_error(error)
        verdict = Verdict(
            proposal_id=proposal.proposal_id,
            decision=Decision.VETOED,
            results=(
                RuleResult(
                    rule_id="R-02",
                    passed=False,
                    severity=Severity.BLOCK,
                    observed=type(error).__name__,
                    limit="verified inputs and audit storage",
                    message="boundary failure latched HALTED; proposal vetoed",
                ),
            ),
            config_hash=self.config.config_hash,
            snapshot_hash="0" * 64,
            evaluated_at=ensure_utc(self.clock.now()),
        )
        self._log(verdict)
        return verdict

    @staticmethod
    def _log(verdict: Verdict) -> None:
        if verdict.decision == Decision.VETOED:
            logger = structlog.get_logger()
            for result in verdict.results:
                if not result.passed:
                    logger.warning(
                        "proposal_veto",
                        rule_id=result.rule_id,
                        proposal_id=str(verdict.proposal_id),
                        severity=result.severity.value,
                    )

    def evaluate_from_sources(
        self,
        proposal: TradeProposal,
        broker: BrokerStateProvider,
        markets: DataLayer,
        liquidity: LiquidityGate,
        *,
        lots: tuple[TaxLot, ...] = (),
        history: tuple[TradeRecord, ...] = (),
        external_accounts: tuple[ExternalAccount, ...] = (),
        reader: ResilientReader | None = None,
    ) -> Verdict:
        """R-02/R-09: provider faults veto; exits avoid entry-only market/bank reads."""
        try:
            self.ledger.verify_chain()
            now = ensure_utc(self.clock.now())
            reads = reader or ResilientReader(self.clock, self.state)
            snapshot = reads.run(lambda: broker.snapshot(now))
            if proposal.intent in {Intent.ENTRY, Intent.ADD}:
                market: MarketContext | None = markets.latest_market(proposal.symbol)
                funding: DeployableCapital | None = liquidity.evaluate()
            else:
                market, funding = None, None
            return self.evaluate(
                proposal,
                snapshot,
                market,
                funding,
                flags=broker.last_flags,
                lots=lots,
                history=history,
                external_accounts=external_accounts,
            )
        except Exception as exc:
            return self._fault_verdict(proposal, exc)

    def evaluate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        deployable: DeployableCapital | None,
        *,
        flags: AccountFlags | None,
        lots: tuple[TaxLot, ...] = (),
        history: tuple[TradeRecord, ...] = (),
        external_accounts: tuple[ExternalAccount, ...] = (),
    ) -> Verdict:
        """R-03: serialize pending reservations, verdict evidence and local approval.

        Local APPROVED events reserve capital for subsequent proposals. These
        records are not sent to a broker. The order remains purely audit evidence.
        """
        try:
            now = ensure_utc(self.clock.now())
            proposal = TradeProposal.model_validate(proposal.model_dump())
            snapshot = PortfolioSnapshot.model_validate(snapshot.model_dump())
            self.ledger.verify_chain()
            if flags is None or flags.blocked:
                self.state.halt_for_error(
                    DataIntegrityError("CMP-06: account flags unverifiable or blocked")
                )
            if proposal.intent in {Intent.ENTRY, Intent.ADD}:
                self.state.apply_financial_limits(
                    snapshot.equity,
                    snapshot.high_water_mark,
                    snapshot.day_start_equity,
                    self.config,
                )
            with transaction(self.ledger.engine) as session:
                from backend.core.database import SystemControl
                from backend.core.system_state import SystemState

                control = session.get(SystemControl, 1)
                if control is None:
                    raise DataIntegrityError("R-02: missing state during decision transaction")
                mode = SystemState(control.state)
                signal = session.get(Signal, proposal.signal_id)
                if (
                    signal is None
                    or signal.symbol != proposal.symbol
                    or signal.direction != proposal.side.value
                    or signal.signal_type != proposal.source.value
                ):
                    raise DataIntegrityError("R-02: signal does not resolve to proposal")
                pending: list[OpenOrder] = list(snapshot.open_orders)
                for local in session.scalars(
                    select(Order).where(Order.account_id == snapshot.account_id)
                ):
                    latest = session.scalar(
                        select(OrderEvent)
                        .where(OrderEvent.order_id == local.id)
                        .order_by(OrderEvent.seq.desc())
                        .limit(1)
                    )
                    if latest is not None and latest.state == "APPROVED":
                        pending.append(
                            OpenOrder(
                                symbol=local.symbol,
                                side=Side(local.side),
                                qty=local.qty,
                                limit_price=local.limit_price,
                            )
                        )
                effective = PortfolioSnapshot.model_validate(
                    {**snapshot.model_dump(), "open_orders": tuple(pending)}
                )
                order = self.ledger.append_in_session(
                    session,
                    Order,
                    proposal_id=proposal.proposal_id,
                    signal_id=proposal.signal_id,
                    account_id=proposal.account_id,
                    symbol=proposal.symbol,
                    side=proposal.side.value,
                    intent=proposal.intent.value,
                    qty=proposal.qty,
                    limit_price=proposal.limit_price,
                    stop_price=proposal.stop_price,
                    source=proposal.source.value,
                    client_order_id=str(proposal.proposal_id),
                )
                risk = self.cro.evaluate(
                    proposal, effective, market, mode, now, deployable=deployable
                )
                checks = self.compliance.check(
                    proposal, effective, lots, history, external_accounts, now, flags=flags
                )
                results = risk.results + tuple(checks)
                approved = not any(
                    not item.passed and item.severity == Severity.BLOCK for item in results
                )
                verdict = Verdict(
                    proposal_id=proposal.proposal_id,
                    decision=Decision.APPROVED if approved else Decision.VETOED,
                    results=results,
                    config_hash=self.config.config_hash,
                    snapshot_hash=snapshot_hash(effective),
                    evaluated_at=now,
                )
                decision = self.ledger.append_in_session(
                    session,
                    RiskDecision,
                    proposal_id=proposal.proposal_id,
                    decision=verdict.decision.value,
                    config_hash=verdict.config_hash,
                    snapshot_hash=verdict.snapshot_hash,
                    evaluated_at=now,
                )
                for result in risk.results:
                    self.ledger.append_in_session(
                        session,
                        RiskRuleResult,
                        risk_decision_id=decision.id,
                        rule_id=result.rule_id,
                        passed=int(result.passed),
                        severity=result.severity.value,
                        observed={"value": result.observed},
                        limit={"value": result.limit},
                        message=result.message,
                    )
                for result in checks:
                    self.ledger.append_in_session(
                        session,
                        ComplianceCheck,
                        proposal_id=proposal.proposal_id,
                        rule_id=result.rule_id,
                        passed=int(result.passed),
                        severity=result.severity.value,
                        observed={"value": result.observed},
                        limit={"value": result.limit},
                        message=result.message,
                        checked_at=now,
                    )
                self.ledger.append_in_session(
                    session,
                    ConfigSnapshot,
                    config_hash=self.config.config_hash,
                    settings=self.config.nonsecret_snapshot(),
                )
                self.ledger.append_in_session(
                    session,
                    PortfolioState,
                    account_id=snapshot.account_id,
                    account_type=snapshot.account_type.value,
                    as_of=snapshot.as_of,
                    equity=snapshot.equity,
                    cash=snapshot.cash,
                    settled_cash=snapshot.settled_cash,
                    positions=snapshot.model_dump(mode="json")["positions"],
                    high_water_mark=snapshot.high_water_mark,
                    day_start_equity=snapshot.day_start_equity,
                )
                if approved:
                    self.ledger.append_in_session(
                        session,
                        OrderEvent,
                        order_id=order.id,
                        state="APPROVED",
                        reason="deterministic gate approved locally",
                        broker_order_id=None,
                    )
            self._log(verdict)
            return verdict
        except Exception as exc:
            return self._fault_verdict(proposal, exc)
