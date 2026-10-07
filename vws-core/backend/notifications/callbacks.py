"""GD-06: authenticated, fresh, single-use manual ticket gate.

This boundary writes local tickets only. Telegram delivery is separate; no
broker order API or execution module is imported.
"""

import asyncio
import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.fundamentals import compute_fundamentals, framework_allows
from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings, YamlConfig
from backend.core.database import (
    Alert,
    AlertEvent,
    ApprovalEvent,
    ComplianceCheck,
    Order,
    ResearchReport,
    RiskDecision,
    RiskRuleResult,
    SecurityEvent,
    SystemControl,
    SystemEvent,
    TicketEvent,
    TradeTicket,
    transaction,
)
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.sec_edgar import SecPayload
from backend.domain.compliance_models import ExternalAccount, TaxLot, TradeRecord
from backend.domain.models import (
    AccountFlags,
    DeployableCapital,
    FrozenModel,
    Intent,
    MarketContext,
    PortfolioSnapshot,
    ProposalSource,
    Side,
    TradeProposal,
)
from backend.notifications.card_formatter import details_cards, ticket_card
from backend.risk.boundary import RiskBoundary
from backend.risk.compliance_boundary import ComplianceBoundary

Action = Literal["A", "R", "D", "P", "S"]
_WIRE = re.compile(r"v1:([ARDPS]):([0-9a-f]{32}):([0-9a-f]{16})\Z")


def callback_data(action: Action, proposal_id: UUID, chat_id: int, settings: Settings) -> str:
    policy = Settings.validated_copy(settings)
    policy.assert_telegram_ready()
    if action not in {"A", "R", "D", "P", "S"} or type(chat_id) is not int or chat_id <= 0:
        raise DataIntegrityError("GD-06: callback action/chat invalid")
    bound = f"v1|{action}|{proposal_id.hex}|{chat_id}".encode()
    digest = hmac.new(
        policy.telegram_callback_secret.get_secret_value().encode(), bound, hashlib.sha256
    ).hexdigest()[:16]
    return f"v1:{action}:{proposal_id.hex}:{digest}"


class CallbackClick(FrozenModel):
    user_id: int = Field(strict=True, gt=0, lt=2**63)
    chat_id: int = Field(strict=True, gt=0, lt=2**63)
    message_id: int = Field(strict=True, gt=0, lt=2**63)
    chat_type: str = Field(min_length=1, max_length=32)
    data: str = Field(min_length=1, max_length=64)


class FreshInputs(FrozenModel):
    quote_feed: Literal["IEX"]
    portfolio: PortfolioSnapshot
    market: MarketContext
    capital: DeployableCapital | None = None
    flags: AccountFlags
    lots: tuple[TaxLot, ...] = Field(default=(), max_length=10000)
    history: tuple[TradeRecord, ...] = Field(default=(), max_length=100000)
    tax_accounts: tuple[ExternalAccount, ...] = Field(default=(), max_length=1000)
    filings: SecPayload | None = None
    expected_cik: str | None = Field(default=None, pattern=r"^[0-9]{10}$")


class FreshSource(Protocol):
    async def refresh(self, symbol: str) -> FreshInputs: ...


class ClickResult(FrozenModel):
    status: Literal[
        "IGNORED",
        "HANDLED",
        "DETAILS",
        "TICKET",
        "PLACED",
        "SKIPPED",
        "REJECTED",
        "EXPIRED",
        "FAILED",
    ]
    text: str | None = Field(default=None, max_length=4096)
    ticket_id: UUID | None = None
    continuation: tuple[str, ...] = Field(default=(), max_length=30)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.status == "IGNORED":
            if self.text is not None or self.ticket_id is not None or self.continuation:
                raise ValueError("ignored clicks cannot disclose data")
        elif self.text is None or not self.text:
            raise ValueError("handled clicks require bounded display evidence")
        if self.status in {"TICKET", "PLACED", "SKIPPED"} and self.ticket_id is None:
            raise ValueError("ticket state requires its immutable identity")
        return self


class ApprovalGate:
    def __init__(
        self,
        settings: Settings,
        config: YamlConfig,
        state: SystemStateStore,
        risk: RiskBoundary,
        compliance: ComplianceBoundary,
        clock: Clock,
        source: FreshSource,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.settings.assert_telegram_ready()
        self.config = YamlConfig.model_validate(config)
        self.config.assert_settings_consistent(self.settings)
        if (
            risk.state is not state
            or compliance.state is not state
            or state.clock is not clock
            or risk.clock is not clock
            or compliance.clock is not clock
            or risk.cro.config.config_hash != self.settings.config_hash
            or compliance.engine.config.config_hash != self.settings.config_hash
            or risk.marks is None
        ):
            raise ConfigurationError("GD-06: approval defense state/policies differ")
        self.state, self.risk, self.compliance, self.clock = state, risk, compliance, clock
        self.ledger, self.source = state.ledger, source
        self._lock = asyncio.Lock()

    def _audit(self, kind: str, user_id: int | None = None) -> None:
        self.ledger.append(SecurityEvent, kind=kind, telegram_user_id=user_id, detail={})

    async def handle(
        self, click: CallbackClick, *, acknowledge: Callable[[str], Awaitable[None]]
    ) -> ClickResult:
        try:
            item = CallbackClick.model_validate(click)
            self.ledger.verify_chain()
            if (
                item.chat_type != "private"
                or item.chat_id != item.user_id
                or item.user_id not in self.settings.telegram_allowed_user_ids
            ):
                self._audit("CALLBACK_UNAUTHORIZED", item.user_id)
                return ClickResult(status="IGNORED")
            match = _WIRE.fullmatch(item.data)
            if match is None:
                self._audit("CALLBACK_BAD_WIRE", item.user_id)
                return ClickResult(status="IGNORED")
            action, hex_id = match[1], match[2]
            # The literal action inventory was established by _WIRE above.
            from typing import cast

            expected = callback_data(
                cast(Action, action), UUID(hex_id), item.chat_id, self.settings
            )
            if not hmac.compare_digest(item.data, expected):
                self._audit("CALLBACK_BAD_HMAC", item.user_id)
                return ClickResult(status="IGNORED")
            async with self._lock:
                return await self._handle(item, action, UUID(hex_id), acknowledge)
        except asyncio.CancelledError:
            self.state.escalate(SystemState.HALTED, "GD-06 approval cancelled")
            raise
        except Exception as exc:
            self.state.halt_for_error(exc)
            self._audit("CALLBACK_FAULT")
            return ClickResult(
                status="FAILED", text="Fresh checks failed; entries halted. No ticket."
            )

    async def _handle(
        self,
        click: CallbackClick,
        action: str,
        proposal_id: UUID,
        acknowledge: Callable[[str], Awaitable[None]],
    ) -> ClickResult:
        with Session(self.ledger.engine) as session:
            alert = session.scalar(select(Alert).where(Alert.proposal_id == proposal_id))
            delivery = (
                None
                if alert is None
                else session.scalar(
                    select(AlertEvent)
                    .where(AlertEvent.alert_id == alert.id, AlertEvent.state == "SENT")
                    .limit(1)
                )
            )
            order = session.scalar(select(Order).where(Order.proposal_id == proposal_id))
            desk_policy = (
                None
                if alert is None
                else session.scalar(
                    select(ResearchReport).where(
                        ResearchReport.alert_id == alert.id,
                        ResearchReport.agent_name == "desk_policy",
                    )
                )
            )
        if (
            alert is None
            or delivery is None
            or order is None
            or delivery.telegram_chat_id != click.chat_id
            or delivery.telegram_message_id != click.message_id
            or alert.config_hash != self.settings.config_hash
            or desk_policy is None
            or desk_policy.payload != {"yaml_hash": self.config.config_hash}
        ):
            self._audit("CALLBACK_BINDING_MISMATCH", click.user_id)
            return ClickResult(status="IGNORED")
        self._audit("CALLBACK_" + action, click.user_id)
        current = self.ledger.current_alert_status(alert.id)
        if action in {"P", "S"}:
            if current != "APPROVED":
                return ClickResult(status="HANDLED", text="Ticket not approved or already handled.")
            with transaction(self.ledger.engine) as session:
                ticket = session.scalar(select(TradeTicket).where(TradeTicket.alert_id == alert.id))
                if (
                    ticket is None
                    or session.scalar(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id))
                    is not None
                ):
                    return ClickResult(status="HANDLED", text="Ticket already handled.")
                self.ledger.append_in_session(
                    session,
                    TicketEvent,
                    ticket_id=ticket.id,
                    action="TICKET_PLACED" if action == "P" else "TICKET_SKIPPED",
                    telegram_user_id=click.user_id,
                )
            return ClickResult(
                status="PLACED" if action == "P" else "SKIPPED",
                text="Recorded. Broker fills are checked separately.",
                ticket_id=ticket.id,
            )
        if current != "SENT":
            return ClickResult(status="HANDLED", text="Expired or already handled.")
        if ensure_utc(self.clock.now()) >= alert.expires_at:
            self.ledger.append(ApprovalEvent, alert_id=alert.id, action="EXPIRED", reasons=[])
            return ClickResult(status="EXPIRED", text="Expired. No ticket.")
        if action == "D":
            pages = details_cards(alert.id, self.ledger, self.settings)
            return ClickResult(status="DETAILS", text=pages[0], continuation=pages[1:])
        if action == "R":
            self.ledger.append(
                ApprovalEvent,
                alert_id=alert.id,
                action="USER_VETOED",
                telegram_user_id=click.user_id,
                reasons=[],
            )
            return ClickResult(status="REJECTED", text="Rejected. No ticket.")
        await acknowledge("Re-checking…")
        async with asyncio.timeout(30):
            inputs = FreshInputs.model_validate(await self.source.refresh(order.symbol))
        proposal = TradeProposal(
            proposal_id=order.proposal_id,
            signal_id=order.signal_id,
            account_id=order.account_id,
            symbol=order.symbol,
            side=Side(order.side),
            intent=Intent(order.intent),
            qty=order.qty,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            target_price=order.target_price,
            source=ProposalSource(order.source),
            created_at=order.created_at,
            expires_at=alert.expires_at,
        )
        now = ensure_utc(self.clock.now())
        if inputs.portfolio.account_id != order.account_id:
            raise DataIntegrityError("GD-06: fresh broker account differs")
        if inputs.filings is not None and (
            inputs.expected_cik != inputs.filings.cik or inputs.filings.fetched_at > now
        ):
            raise DataIntegrityError("GD-06: fresh filing issuer/time differs")
        fundamental = compute_fundamentals(
            self.risk.cro.registry.get(order.symbol), inputs.filings, now, self.config.fundamentals
        )
        verdict = self.risk.evaluate(
            proposal, inputs.portfolio, inputs.market, deployable=inputs.capital
        )
        compliance = self.compliance.evaluate(
            proposal,
            inputs.portfolio,
            inputs.lots,
            inputs.history,
            inputs.tax_accounts,
            flags=inputs.flags,
        )
        findings = [row.model_dump(mode="json") for row in (*verdict.results, *compliance.results)]
        reasons = [row for row in findings if not row["passed"] and row["severity"] == "BLOCK"]
        entry = proposal.intent in {Intent.ENTRY, Intent.ADD}
        if entry and not framework_allows(fundamental, self.config.fundamentals):
            reasons.append({"rule_id": "FA-08", "message": "; ".join(fundamental.failure_reasons)})
        late_quote = False
        with transaction(self.ledger.engine) as session:
            # The serialized writer closes the state/expiry race with /halt.
            latest = self.ledger._latest_alert_event(session, alert.id)
            if latest is None or latest.state != "SENT":
                return ClickResult(status="HANDLED", text="Already handled.")
            control = session.scalar(
                select(SystemControl).where(SystemControl.id == 1).with_for_update()
            )
            if control is None:
                raise DataIntegrityError("GD-06: approval state control missing")
            self.state._verify_projection(session, control)
            commit_now = ensure_utc(self.clock.now())
            if commit_now >= alert.expires_at:
                self.ledger.append_in_session(
                    session, ApprovalEvent, alert_id=alert.id, action="EXPIRED", reasons=[]
                )
                return ClickResult(status="EXPIRED", text="Expired during fresh checks. No ticket.")
            if entry and control.state != "RUNNING":
                reasons.append({"rule_id": "CRO-01", "message": "entries halted or reduced"})
            if (
                commit_now - inputs.market.last_price_ts
            ).total_seconds() > self.settings.stale_quote_seconds:
                reasons.append(
                    {"rule_id": "CRO-07", "message": "quote expired during fresh checks"}
                )
                late_quote = True
                if control.state != "HALTED":
                    control.state = "HALTED"
                    control.version += 1
                    self.ledger.append_in_session(
                        session,
                        SystemEvent,
                        state="HALTED",
                        reason="GD-06: quote expired during fresh checks",
                        operator_id=None,
                        event_type="ESCALATE",
                    )
            decision = self.ledger.append_in_session(
                session,
                RiskDecision,
                proposal_id=proposal_id,
                decision=verdict.decision.value,
                config_hash=verdict.config_hash,
                snapshot_hash=verdict.snapshot_hash,
                evaluated_at=verdict.evaluated_at,
            )
            for row in verdict.results:
                self.ledger.append_in_session(
                    session,
                    RiskRuleResult,
                    risk_decision_id=decision.id,
                    rule_id=row.rule_id,
                    passed=int(row.passed),
                    severity=row.severity.value,
                    observed={"text": row.observed},
                    limit={"text": row.limit},
                    message=row.message,
                )
            for row in compliance.results:
                self.ledger.append_in_session(
                    session,
                    ComplianceCheck,
                    proposal_id=proposal_id,
                    rule_id=row.rule_id,
                    passed=int(row.passed),
                    severity=row.severity.value,
                    observed={"text": row.observed},
                    limit={"text": row.limit},
                    message=row.message,
                    checked_at=compliance.evaluated_at,
                )
            if reasons:
                self.ledger.append_in_session(
                    session,
                    ApprovalEvent,
                    alert_id=alert.id,
                    action="REVALIDATION_FAILED",
                    telegram_user_id=click.user_id,
                    reasons=reasons,
                )
                result = ClickResult(
                    status="FAILED", text="Fresh checks vetoed this setup. No ticket."
                )
            else:
                self.ledger.append_in_session(
                    session,
                    ApprovalEvent,
                    alert_id=alert.id,
                    action="MANUALLY_APPROVED",
                    telegram_user_id=click.user_id,
                    reasons=findings,
                )
                ticket = self.ledger.append_in_session(
                    session,
                    TradeTicket,
                    alert_id=alert.id,
                    symbol=order.symbol,
                    side=order.side,
                    qty=order.qty,
                    limit_price=order.limit_price,
                    stop_price=order.stop_price,
                    target_price=order.target_price,
                    valid_until=alert.expires_at,
                )
                result = ClickResult(
                    status="TICKET", text=ticket_card(ticket, self.settings), ticket_id=ticket.id
                )
        if late_quote:
            # The halt is durable before notification; never nest ledger writers.
            self.state.escalate(SystemState.HALTED, "GD-06: quote expired during fresh checks")
        return result
