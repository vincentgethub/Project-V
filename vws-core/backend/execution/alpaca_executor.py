"""AX-10/12: the sole module with Alpaca order requests and order calls.

SDK 0.44.0 uses float annotations for prices. These narrow subclasses retain
Decimal cents and whole integers through validation, and serialize exact text.
No SDK retries or money-movement route is enabled. MANUAL never imports this.
"""

import asyncio
import hmac
import re
import ssl
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from time import monotonic_ns
from typing import Any, Literal, Protocol, Self, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrderByIdRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    StopLossRequest,
    StopOrderRequest,
    TakeProfitRequest,
)
from alpaca.trading.stream import TradingStream
from pydantic import ConfigDict, Field, model_validator
from requests import Session
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from backend.agents.fundamentals import compute_fundamentals, framework_allows
from backend.core.clock import ensure_utc
from backend.core.config import Settings, YamlConfig, assert_broker_endpoint
from backend.core.database import (
    Alert,
    ApprovalEvent,
    ExecutionFillRecord,
    ExecutionOrderRecord,
    Order,
    OrderEvent,
    ResearchReport,
    RiskDecision,
    RiskRuleResult,
    SecurityEvent,
    SystemControl,
    transaction,
)
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EntryAdmissionRevoked,
    ExecutionDisabledError,
    OrderRejectedError,
    ProviderError,
    ReconciliationError,
)
from backend.core.money import decimal_money, validate_cent_price
from backend.core.system_state import SystemState, SystemStateStore, financial_state
from backend.data.fill_polling import ObservedFill
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    Decision,
    Intent,
    MarketContext,
    MarketStatus,
    Playbook,
    PortfolioSnapshot,
    PositiveQty,
    Price,
    ProposalSource,
    Severity,
    Side,
    Symbol,
    TradeProposal,
)
from backend.execution.exit_variants import (
    HeldEntry,
    HeldExitObservation,
    HeldQuoteObservation,
    StopMoved,
    StopRaiseApproval,
    stop_raise_plan,
)
from backend.execution.fill_capture import ExecutionFillCapture
from backend.execution.live_guard import LiveGuard
from backend.execution.models import (
    AutoPrerequisites,
    BindingEvidence,
    BrokerOrder,
    EntryApprovalEvidence,
    ExitApprovalEvidence,
    ExitCycleEvidence,
    Submission,
    SubmitOutcome,
)
from backend.execution.modes import ModeStore, account_lock, assert_auto_binding
from backend.execution.policy import (
    automatic_exit_reason,
    entry_window,
    exit_limit,
    live_ceiling_reasons,
)
from backend.execution.reporting import fill_fyi
from backend.execution.stop_evidence import current_stop, moved_stops, stop_approvals
from backend.execution.storage import (
    approval_evidence,
    bindings,
    exit_approvals,
    exit_cycles,
    filled_quantity,
    held_quantity,
)
from backend.execution.worker import SingleAttemptWorker
from backend.net.egress import EgressPolicy
from backend.net.http import make_order_session
from backend.notifications.callbacks import CallbackClick, FreshInputs, FreshSource, callback_data
from backend.notifications.card_formatter import display_time
from backend.risk.boundary import RiskBoundary
from backend.risk.compliance import day_trade_activity
from backend.risk.compliance_boundary import ComplianceBoundary
from backend.security.secrets import SecretStore

_EXACT_REQUEST_CONFIG = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class ExactTakeProfit(TakeProfitRequest):
    model_config = _EXACT_REQUEST_CONFIG
    # Pinned SDK float field replaced intentionally; serialized only as exact text.
    limit_price: Price  # type: ignore[assignment]

    def to_request_fields(self) -> dict[str, Any]:
        checked = ExactTakeProfit.model_validate(self)
        return {"limit_price": format(checked.limit_price, ".2f")}


class ExactStopLoss(StopLossRequest):
    model_config = _EXACT_REQUEST_CONFIG
    stop_price: Price  # type: ignore[assignment]  # verified SDK Decimal shim
    limit_price: None = None

    def to_request_fields(self) -> dict[str, Any]:
        checked = ExactStopLoss.model_validate(self)
        return {"stop_price": format(checked.stop_price, ".2f")}


class ExactLimit(LimitOrderRequest):
    model_config = _EXACT_REQUEST_CONFIG
    type: OrderType = OrderType.LIMIT
    symbol: Symbol
    qty: PositiveQty
    limit_price: Price  # type: ignore[assignment]  # verified SDK Decimal shim
    client_order_id: str = Field(min_length=1, max_length=128, pattern=r"^vws-")
    take_profit: ExactTakeProfit | None = None
    stop_loss: ExactStopLoss | None = None

    @model_validator(mode="after")
    def allowed_shape(self) -> Self:
        if (
            self.notional is not None
            or self.legs is not None
            or self.position_intent is not None
            or self.extended_hours is not None
        ):
            raise ValueError("Only whole-share regular-hours equity orders are allowed")
        bracket = self.order_class == OrderClass.BRACKET
        if bracket:
            if (
                self.side != OrderSide.BUY
                or self.time_in_force != TimeInForce.GTC
                or self.take_profit is None
                or self.stop_loss is None
                or not self.stop_loss.stop_price < self.limit_price < self.take_profit.limit_price
            ):
                raise ValueError("Entry requires one BUY GTC bracket with ordered cent prices")
        elif self.order_class == OrderClass.OTO:
            if (
                self.side != OrderSide.BUY
                or self.time_in_force != TimeInForce.GTC
                or self.take_profit is not None
                or self.stop_loss is None
                or self.stop_loss.stop_price >= self.limit_price
            ):
                raise ValueError("EX-02: OTO is BUY GTC LIMIT with a protective stop only")
        elif self.order_class == OrderClass.OCO:
            if (
                self.side != OrderSide.SELL
                or self.time_in_force != TimeInForce.GTC
                or self.take_profit is None
                or self.stop_loss is None
                or self.limit_price != self.take_profit.limit_price
                or self.stop_loss.stop_price >= self.limit_price
            ):
                raise ValueError("EX-05: OCO is a protected SELL GTC exit with an exact target")
        elif (
            self.order_class not in {None, OrderClass.SIMPLE}
            or self.side != OrderSide.SELL
            or self.time_in_force != TimeInForce.DAY
            or self.take_profit is not None
            or self.stop_loss is not None
        ):
            raise ValueError("Plain limits are DAY SELL exits only")
        return self

    def to_request_fields(self) -> dict[str, Any]:
        checked = ExactLimit.model_validate(self)
        if checked.side is None:
            raise DataIntegrityError("Validated order has no side")
        result: dict[str, Any] = {
            "symbol": checked.symbol,
            "qty": str(checked.qty),
            "side": checked.side.value,
            "type": "limit",
            "time_in_force": checked.time_in_force.value,
            "order_class": "bracket"
            if checked.order_class == OrderClass.BRACKET
            else "oto"
            if checked.order_class == OrderClass.OTO
            else "oco"
            if checked.order_class == OrderClass.OCO
            else "simple",
            "client_order_id": checked.client_order_id,
            "limit_price": format(checked.limit_price, ".2f"),
        }
        if checked.take_profit is not None:
            result["take_profit"] = checked.take_profit.to_request_fields()
        if checked.stop_loss is not None:
            result["stop_loss"] = checked.stop_loss.to_request_fields()
        if checked.order_class == OrderClass.OCO:
            # VERIFY: OCO target is represented by take_profit in the request;
            # the response reports that target as the LIMIT parent.
            del result["limit_price"]
        return result


class ExactStop(StopOrderRequest):
    model_config = _EXACT_REQUEST_CONFIG
    type: OrderType = OrderType.STOP
    symbol: Symbol
    qty: PositiveQty
    stop_price: Price  # type: ignore[assignment]  # verified SDK Decimal shim
    client_order_id: str = Field(min_length=1, max_length=128, pattern=r"^vws-")

    @model_validator(mode="after")
    def protective_shape(self) -> Self:
        if (
            self.side != OrderSide.SELL
            or self.time_in_force != TimeInForce.GTC
            or self.order_class not in {None, OrderClass.SIMPLE}
            or self.extended_hours is not None
            or self.notional is not None
            or self.legs is not None
            or self.position_intent is not None
            or self.take_profit is not None
            or self.stop_loss is not None
        ):
            raise ValueError("Stop repair requires one whole-share SELL GTC stop")
        return self

    def to_request_fields(self) -> dict[str, Any]:
        checked = ExactStop.model_validate(self)
        return {
            "symbol": checked.symbol,
            "qty": str(checked.qty),
            "side": "sell",
            "type": "stop",
            "time_in_force": "gtc",
            "client_order_id": checked.client_order_id,
            "stop_price": format(checked.stop_price, ".2f"),
        }


def configure_execution_client(
    client: TradingClient,
    settings: Settings,
    policy: EgressPolicy,
    *,
    before_request: Callable[[], None],
) -> None:
    """AX-15/16: endpoint assertion, exact JSON, one physical SDK attempt."""
    if settings.execution_mode == "MANUAL":
        raise ConfigurationError("MANUAL cannot acquire an order transport")
    base = getattr(client, "_base_url", None)
    endpoint = getattr(base, "value", base)
    old_session = getattr(client, "_session", None)
    if (
        not isinstance(endpoint, str)
        or not isinstance(old_session, Session)
        or not hasattr(client, "_retry")
    ):
        raise ConfigurationError("Pinned Alpaca SDK transport contract changed")
    assert_broker_endpoint(settings, endpoint)
    session = make_order_session(
        settings.broker_endpoint,
        settings.request_timeout_seconds,
        policy=policy,
        before_request=before_request,
    )
    old_session.close()
    bound = cast(Any, client)
    bound._session, bound._retry, bound._use_raw_data = session, 0, True


def make_execution_client(
    settings: Settings,
    policy: EgressPolicy,
    *,
    before_request: Callable[[], None],
) -> TradingClient:
    if settings.execution_mode == "MANUAL":
        raise ConfigurationError("MANUAL cannot create an execution client")
    client = TradingClient(
        api_key=settings.broker_api_key.get_secret_value(),
        secret_key=settings.broker_secret_key.get_secret_value(),
        paper=settings.paper_trading,
        raw_data=True,
    )
    try:
        configure_execution_client(client, settings, policy, before_request=before_request)
    except Exception:
        client._session.close()
        raise
    return client


def _whole(value: object, *, positive: bool) -> int:
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise DataIntegrityError("Broker share quantity must be exact text or integer")
    number = decimal_money(value)
    if (
        number != number.to_integral_value()
        or number < (1 if positive else 0)
        or number > 2**31 - 1
    ):
        raise DataIntegrityError("Broker share quantity is not a bounded whole number")
    return int(number)


def _price(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise DataIntegrityError("Broker price must retain exact money")
    return validate_cent_price(decimal_money(value))


def _instant(value: object) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str) or len(value) > 64:
        raise DataIntegrityError("Broker order timestamp is unavailable")
    try:
        return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        raise DataIntegrityError("Broker order timestamp is invalid") from None


def parse_order(raw: object, *, parent_id: UUID | None = None) -> BrokerOrder:
    """AX-31: project only permitted raw fields; unsupported broker states refuse."""
    if not isinstance(raw, Mapping):
        raise DataIntegrityError("Broker order must be exact raw JSON")
    try:
        identifier = UUID(str(raw["id"]))
        legs = raw.get("legs")
        if legs is not None and (
            not isinstance(legs, list) or len(legs) > 2 or parent_id is not None
        ):
            raise DataIntegrityError("Broker bracket leg collection is invalid")
        result = BrokerOrder(
            order_id=identifier,
            client_order_id=raw["client_order_id"],
            symbol=raw["symbol"],
            side=raw["side"],
            order_type=raw["type"],
            order_class=raw.get("order_class") or "simple",
            time_in_force=raw["time_in_force"],
            qty=_whole(raw["qty"], positive=True),
            filled_qty=_whole(raw["filled_qty"], positive=False),
            status=raw["status"],
            limit_price=_price(raw.get("limit_price")),
            stop_price=_price(raw.get("stop_price")),
            submitted_at=_instant(raw["submitted_at"]),
            parent_id=parent_id,
            legs=tuple(parse_order(row, parent_id=identifier) for row in legs or ()),
        )
    except Exception as error:
        if isinstance(error, DataIntegrityError):
            raise
        raise DataIntegrityError("Broker order identity or shape cannot be verified") from None
    return result


def order_not_found(error: Exception) -> bool:
    """Only a verified HTTP 404 proves the client ID lookup found no order."""
    return isinstance(error, APIError) and error.status_code == 404


async def inspect_paper_cancel_semantics(
    settings: Settings, reader: Any, client: Any, oto_id: UUID, oco_id: UUID
) -> tuple[BrokerOrder, BrokerOrder]:
    """EX-06 integration: explicit existing paper exercise, four fresh GETs only."""
    policy = Settings.validated_copy(settings)
    if not policy.paper_trading or policy.execution_mode != "AUTO_PAPER" or oto_id == oco_id:
        raise ExecutionDisabledError("EX-06: two distinct explicit AUTO_PAPER roots required")
    assert_broker_endpoint(policy, str(client._base_url))
    account = await reader.run(client.get_account)
    if (
        not isinstance(account, Mapping)
        or account.get("status") != "ACTIVE"
        or account.get("currency") != "USD"
        or not isinstance(account.get("id"), str)
        or any(
            account.get(flag) is not False
            for flag in ("trading_blocked", "account_blocked", "trade_suspended_by_user")
        )
    ):
        raise ReconciliationError("EX-06: bound active USD paper account unavailable")
    roots = []
    for identity in (oto_id, oco_id):
        raw = await reader.run(
            lambda order_id=identity: client.get_order_by_id(
                order_id, filter=GetOrderByIdRequest(nested=True)
            )
        )
        root = parse_order(raw)
        if root.order_id != identity or len(root.legs) != 1 or root.legs[0].order_type != "stop":
            raise DataIntegrityError("EX-06: root must expose its one actual stop leg")
        stop = parse_order(
            await reader.run(
                lambda child_id=root.legs[0].order_id: client.get_order_by_id(child_id)
            ),
            parent_id=root.order_id,
        )
        if stop != root.legs[0] or stop.status != "canceled":
            raise DataIntegrityError("EX-06: fresh generated stop cancellation differs")
        roots.append(root)
    oto, oco = roots
    if (
        oto.order_class != "oto"
        or oto.side != "buy"
        or oto.status not in {"canceled", "filled"}
        or oco.order_class != "oco"
        or oco.side != "sell"
        or oco.status != "canceled"
        or oto.legs[0].order_id == oco.legs[0].order_id
    ):
        raise DataIntegrityError("EX-06: OTO stop and OCO siblings not proved canceled")
    return oto, oco


class TradingCalls(Protocol):
    """Only this isolated module may invoke the pinned order methods."""

    def submit_order(self, order_data: ExactLimit | ExactStop) -> object: ...
    def cancel_order_by_id(self, order_id: UUID | str) -> None: ...
    def get_order_by_client_id(self, client_id: str) -> object: ...
    def get_order_by_id(
        self, order_id: UUID | str, filter: GetOrderByIdRequest | None = None
    ) -> object: ...
    def get_orders(self, filter: GetOrdersRequest | None = None) -> object: ...
    def get_all_positions(self) -> object: ...
    def get_account(self) -> object: ...


class AlpacaExecutor:
    """AX-11/20..31: account-serialized admission and immutable recovery evidence."""

    def __init__(
        self,
        settings: Settings,
        config: YamlConfig,
        state: SystemStateStore,
        modes: ModeStore,
        source: FreshSource,
        risk: RiskBoundary,
        compliance: ComplianceBoundary,
        calendar: MarketCalendar,
        worker: SingleAttemptWorker,
        store: SecretStore,
        prerequisites: AutoPrerequisites,
        *,
        policy: EgressPolicy,
        notify: Callable[[str, bool], Awaitable[None]],
        client: TradingCalls | None = None,
        live_guard: LiveGuard | None = None,
        prerequisites_source: Callable[[], AutoPrerequisites] | None = None,
        portfolio: Callable[[], Awaitable[PortfolioSnapshot]] | None = None,
        configuration_check: Callable[[], object] | None = None,
        size_entry: Callable[[TradeProposal, FreshInputs], Awaitable[int]] | None = None,
        entry_variant_allowed: Callable[[], bool] | None = None,
        playbook_allowed: Callable[[Playbook], bool] | None = None,
        stop_raise_readiness: Callable[[], tuple[str, ...]] | None = None,
        held_exit_observation: Callable[[HeldEntry, FreshInputs], Awaitable[HeldExitObservation]]
        | None = None,
        trade_notice: Callable[[str, bool, UUID], Awaitable[None]] | None = None,
        realtime_entry: Callable[[UUID], Awaitable[None]] | None = None,
        realtime_exit: Callable[[str, datetime], tuple[Literal["DELIST", "DILUTION"], str] | None]
        | None = None,
    ) -> None:
        self.settings, self.config = (
            Settings.validated_copy(settings),
            YamlConfig.model_validate(config),
        )
        self.config.assert_settings_consistent(self.settings)
        recovery = isinstance(self, ProtectionRecovery)
        if modes.effective == "MANUAL" and not recovery:
            raise ExecutionDisabledError("AlpacaExecutor requires an effective AUTO_* mode")
        if recovery and self.settings.execution_mode == "MANUAL":
            raise ExecutionDisabledError(
                "Configured MANUAL cannot import or acquire a protection executor"
            )
        assert_auto_binding(self.settings, store)
        if (
            modes.settings.config_hash != self.settings.config_hash
            or modes.state is not state
            or risk.state is not state
            or compliance.state is not state
            or risk.clock is not state.clock
            or compliance.clock is not state.clock
            or risk.cro.config.config_hash != self.settings.config_hash
            or compliance.engine.config.config_hash != self.settings.config_hash
        ):
            raise ConfigurationError("Execution defense policies or state differ")
        self.state, self.modes, self.source, self.risk, self.compliance = (
            state,
            modes,
            source,
            risk,
            compliance,
        )
        self.calendar, self.worker, self.store, self.notify = calendar, worker, store, notify

        async def timed_notice(text: str, urgent: bool) -> None:
            suffix = (
                ""
                if text.endswith(" CT")
                else " · " + display_time(state.clock.now(), self.settings)
            )
            await notify(text + suffix, urgent)

        self.notify = timed_notice
        self.prerequisites = AutoPrerequisites.model_validate(prerequisites)
        self.prerequisites_source, self.portfolio = prerequisites_source, portfolio
        self.configuration_check = configuration_check
        self.live_guard = live_guard
        self.size_entry, self.trade_notice = size_entry, trade_notice
        self.entry_variant_allowed = entry_variant_allowed
        self.playbook_allowed = playbook_allowed
        self.stop_raise_readiness = stop_raise_readiness
        self._arrival_quotes: dict[str, MarketContext] = {}
        self.held_exit_observation = held_exit_observation
        self.realtime_entry, self.realtime_exit = realtime_entry, realtime_exit
        if recovery:
            managed = self._instructions()
            if not managed:
                raise ExecutionDisabledError(
                    "Protection recovery requires existing managed execution evidence"
                )
        if self.settings.execution_mode == "AUTO_LIVE" and not recovery:
            if live_guard is None:
                raise ExecutionDisabledError(
                    "AUTO_LIVE is locked: history, drill, READY and healthy feeds required"
                )
            if (
                live_guard.state is not state
                or live_guard.settings.config_hash != self.settings.config_hash
                or live_guard.account_id != modes.account_id
            ):
                raise ConfigurationError("Live readiness guard account or configuration differs")
            live_guard.assert_ready()
        if not recovery:
            self._assert_ops()
        self.client = (
            client
            if client is not None
            else make_execution_client(
                self.settings,
                policy,
                before_request=self.worker.before_request,
            )
        )
        resolved = getattr(self.client, "_base_url", None)
        resolved = getattr(resolved, "value", resolved)
        if not isinstance(resolved, str):
            raise ConfigurationError("Execution client endpoint is unavailable")
        assert_broker_endpoint(self.settings, resolved)

    @property
    def environment(self) -> str:
        return self.modes.environment

    def _quantity(self, quantity: int) -> str:
        return "•••" if self.settings.telegram_mask_amounts else str(quantity)

    def _assert_ops(self) -> None:
        if self.configuration_check is not None:
            self.configuration_check()
        if self.prerequisites_source is not None:
            self.prerequisites = AutoPrerequisites.model_validate(self.prerequisites_source())
        if self.settings.execution_mode == "AUTO_LIVE":
            if self.live_guard is None:
                raise ExecutionDisabledError("AUTO_LIVE readiness is unavailable")
            self.live_guard.assert_ready()
        proof, now = self.prerequisites, ensure_utc(self.state.clock.now())
        if (
            proof.account_id != self.modes.account_id
            or proof.environment != self.modes.environment
            or proof.config_hash != self.settings.config_hash
            or not proof.doctor_fully_green
            or not proof.watchdog_enabled
            or not proof.backup_chain_verified
            or not self.settings.healthcheck_ping_url.get_secret_value().strip()
            or not timedelta(0) <= now - proof.backup_verified_at < timedelta(hours=26)
            or not timedelta(0) <= now - proof.telegram_verified_at <= timedelta(minutes=5)
            or not timedelta(0) <= now - proof.clock_verified_at <= timedelta(minutes=5)
        ):
            raise ExecutionDisabledError(
                "AUTO prerequisites are unverified, stale or bound to another account"
            )

    async def _verify_account(self) -> None:
        raw = await self.worker.attempt(self.client.get_account)
        if (
            not isinstance(raw, Mapping)
            or str(raw.get("id")) != self.modes.account_id
            or raw.get("status") != "ACTIVE"
            or raw.get("currency") != "USD"
            or any(
                raw.get(key) is not False
                for key in (
                    "trading_blocked",
                    "account_blocked",
                    "trade_suspended_by_user",
                )
            )
        ):
            raise ReconciliationError("Alpaca account identity, status or restrictions differ")

    def _loaded(
        self, proposal_id: UUID, click: CallbackClick | None
    ) -> tuple[Order, Alert, TradeProposal]:
        self.state.ledger.verify_chain()
        with DatabaseSession(self.state.engine) as session:
            order = session.scalar(select(Order).where(Order.proposal_id == proposal_id))
            alert = session.scalar(select(Alert).where(Alert.proposal_id == proposal_id))
            if order is None or alert is None:
                raise DataIntegrityError("Auto entry has no published local research proposal")
            from backend.core.database import Signal

            signal = session.get(Signal, order.signal_id)
            if signal is None or signal.structured_thesis.get("manual_only") is True:
                raise ExecutionDisabledError("XK-09: watch cards never authorize automatic orders")
            desk = session.scalar(
                select(ResearchReport).where(
                    ResearchReport.alert_id == alert.id, ResearchReport.agent_name == "desk_policy"
                )
            )
            delivery = self.state.ledger._latest_alert_event(session, alert.id)
            research_checks = tuple(
                session.scalars(
                    select(RiskDecision)
                    .where(RiskDecision.proposal_id == proposal_id, RiskDecision.seq < alert.seq)
                    .order_by(RiskDecision.seq)
                )
            )
            if len(research_checks) < 2:
                raise ExecutionDisabledError("AX-20 requires both recorded research CRO checks")
            for decision in research_checks[-2:]:
                results = tuple(
                    session.scalars(
                        select(RiskRuleResult)
                        .where(RiskRuleResult.risk_decision_id == decision.id)
                        .order_by(RiskRuleResult.seq)
                    )
                )
                if (
                    decision.decision != "APPROVED"
                    or decision.config_hash != self.settings.config_hash
                    or tuple(row.rule_id for row in results)
                    != tuple(f"CRO-{n:02d}" for n in range(1, 15))
                    or any(row.passed != 1 and row.severity == "BLOCK" for row in results)
                ):
                    raise ExecutionDisabledError(
                        "Recorded research CRO evidence is incomplete or blocked"
                    )
            if (
                desk is None
                or desk.payload != {"yaml_hash": self.config.config_hash}
                or alert.config_hash != self.settings.config_hash
                or alert.score < self.settings.min_setup_score
                or delivery is None
                or delivery.state != "SENT"
                or session.scalar(select(ApprovalEvent).where(ApprovalEvent.alert_id == alert.id))
                is not None
            ):
                raise ExecutionDisabledError(
                    "Research policy, delivered candidate or single-use decision differs"
                )
            if click is None:
                if alert.score < self.settings.auto_min_score:
                    raise ExecutionDisabledError("This score needs a fresh hybrid approval")
            else:
                click = CallbackClick.model_validate(click)
                if (
                    click.user_id not in self.settings.telegram_allowed_user_ids
                    or click.chat_type != "private"
                    or click.chat_id != delivery.telegram_chat_id
                    or click.message_id != delivery.telegram_message_id
                    or not hmac.compare_digest(
                        click.data, callback_data("A", proposal_id, click.chat_id, self.settings)
                    )
                ):
                    raise ExecutionDisabledError(
                        "Hybrid approval is not privately authenticated and message-bound"
                    )
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
                size_evidence=signal.structured_thesis["setup"].get("size_evidence"),
            )
            if (
                proposal.side != Side.BUY
                or proposal.intent != Intent.ENTRY
                or proposal.target_price is None
            ):
                raise ExecutionDisabledError("Auto entry requires one long entry bracket")
            return order, alert, proposal

    def _daily_count(self) -> int:
        from zoneinfo import ZoneInfo

        day = ensure_utc(self.state.clock.now()).astimezone(ZoneInfo("America/New_York")).date()
        with DatabaseSession(self.state.engine) as session:
            return len(
                {
                    row.order_id
                    for row in session.scalars(
                        select(ExecutionOrderRecord).where(
                            ExecutionOrderRecord.account_id == self.modes.account_id,
                            ExecutionOrderRecord.environment == self.environment,
                            ExecutionOrderRecord.role == "ENTRY",
                        )
                    )
                    if row.created_at.astimezone(ZoneInfo("America/New_York")).date() == day
                }
            )

    async def _lookup(self, client_id: str) -> BrokerOrder | None:
        try:
            raw = await self.worker.attempt(lambda: self.client.get_order_by_client_id(client_id))
        except Exception as error:
            if order_not_found(error):
                return None
            raise ProviderError(
                "Client-ID lookup is unavailable; never retry this intent"
            ) from None
        order = parse_order(raw)
        if order.client_order_id != client_id:
            raise ReconciliationError("Client-ID lookup returned another order")
        return order

    def _observe(self, instruction: ExecutionOrderRecord, broker: BrokerOrder) -> None:
        with DatabaseSession(self.state.engine) as session:
            if bindings(session).get(instruction.id) == broker:
                return
        checked = BindingEvidence(
            execution_order_id=instruction.id,
            broker_order=broker,
            observed_at=self.state.clock.now(),
        )
        self.state.ledger.append(
            SecurityEvent, kind="EXECUTION_ORDER_OBSERVED", detail=checked.model_dump(mode="json")
        )

    def _outcome(
        self, instruction: ExecutionOrderRecord, outcome: str, error: Exception | None = None
    ) -> None:
        checked = SubmitOutcome.model_validate(
            {
                "execution_order_id": instruction.id,
                "account_id": self.modes.account_id,
                "environment": self.environment,
                "outcome": outcome,
                "error_type": "NONE" if error is None else type(error).__name__,
            }
        )
        self.state.ledger.append(
            SecurityEvent, kind="EXECUTION_SUBMIT_OUTCOME", detail=checked.model_dump(mode="json")
        )
        if outcome not in {"ACCEPTED", "NOT_SENT"}:
            failures = 0
            with DatabaseSession(self.state.engine) as session:
                for row in session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME",
                    )
                    .order_by(SecurityEvent.seq.desc())
                ):
                    evidence = SubmitOutcome.model_validate(row.detail)
                    if (
                        evidence.account_id != self.modes.account_id
                        or evidence.environment != self.environment
                    ):
                        continue
                    if evidence.outcome == "ACCEPTED":
                        break
                    if evidence.outcome == "NOT_SENT":
                        continue
                    failures += 1
                    if failures >= self.settings.auto_max_consecutive_order_failures:
                        self.state.escalate(
                            SystemState.HALTED,
                            "AX-31 consecutive order failures; manual trading belongs in a different account",
                        )
                        break

    async def _submit(
        self,
        instruction: ExecutionOrderRecord,
        request: ExactLimit | ExactStop,
        *,
        guard: Callable[[], None] = lambda: None,
    ) -> tuple[BrokerOrder, bool]:
        from backend.evaluation.tca_store import record_arrival

        record_arrival(
            self.state.ledger,
            instruction,
            self._arrival_quotes.get(instruction.symbol),
            self.settings.stale_quote_seconds,
        )
        try:
            raw = await self.worker.attempt(lambda: self.client.submit_order(request), guard=guard)
            broker = parse_order(raw)
            recovered = False
        except asyncio.CancelledError:
            self.state.escalate(
                SystemState.HALTED,
                "Order attempt canceled; look up the client ID before any recovery",
            )
            raise
        except EntryAdmissionRevoked as error:
            # The physical request guard runs before Session.request. A host
            # downgrade is a verified no-send, not an ambiguous broker failure.
            self._outcome(instruction, "NOT_SENT", error)
            raise
        except Exception as error:
            # Even a nominal reject is checked: a server may have accepted before
            # the response failed. There is never an automatic second POST.
            try:
                looked_up = await self._lookup(instruction.client_order_id)
            except Exception as lookup_error:
                self._outcome(instruction, "ERROR", error)
                self.state.halt_for_error(lookup_error)
                raise ProviderError("Ambiguous order and failed lookup; HALTED, no retry") from None
            if looked_up is None:
                rejected = isinstance(error, APIError) and error.status_code in {
                    400,
                    401,
                    403,
                    404,
                    422,
                }
                self._outcome(instruction, "REJECTED" if rejected else "ERROR", error)
                if not rejected:
                    self.state.escalate(
                        SystemState.HALTED,
                        "Order outcome unconfirmed; client ID retained and no retry",
                    )
                else:
                    raise OrderRejectedError(
                        "Broker rejected the order; client-ID lookup confirmed no order"
                    ) from None
                raise ProviderError("Order was refused or remains unconfirmed; no retry") from None
            broker = looked_up
            recovered = True
        self._observe(instruction, broker)
        if broker.status == "rejected":
            self._outcome(instruction, "REJECTED", OrderRejectedError("Broker rejected order"))
            raise OrderRejectedError("Broker order reports a confirmed rejection")
        self._outcome(instruction, "ACCEPTED")
        return broker, recovered

    def _entry_requests(self, proposal: TradeProposal) -> tuple[ExactLimit, ...]:
        """EX-01/02: a single approved quantity, split without increasing exposure."""
        if proposal.stop_price is None or proposal.target_price is None:
            raise DataIntegrityError("EX: ordered entry levels required")
        base = "vws-" + proposal.proposal_id.hex
        variant = self.config.exits.variant
        split = variant in {"SPLIT_1R", "SPLIT_1R_TRAIL"}
        if split and proposal.qty < 2:
            raise ExecutionDisabledError("EX-01: split entry requires at least two shares")
        specs = (
            ((base, proposal.qty, proposal.target_price),)
            if not split
            else (
                (
                    base + "-a",
                    proposal.qty // 2,
                    proposal.limit_price + (proposal.limit_price - proposal.stop_price),
                ),
                (
                    base + "-b",
                    proposal.qty - proposal.qty // 2,
                    None if variant == "SPLIT_1R_TRAIL" else proposal.target_price,
                ),
            )
        )
        return tuple(
            ExactLimit(
                symbol=proposal.symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.OTO if target is None else OrderClass.BRACKET,
                client_order_id=identity,
                limit_price=proposal.limit_price,
                take_profit=None if target is None else ExactTakeProfit(limit_price=target),
                stop_loss=ExactStopLoss(stop_price=proposal.stop_price),
            )
            for identity, qty, target in specs
        )

    def _assert_entry_variant(self) -> None:
        check = self.entry_variant_allowed
        if check is None:
            raise ExecutionDisabledError("EX-06: registered WORKING exit evidence unavailable")
        elif check() is not True:
            raise ExecutionDisabledError(
                "EX-06: configured exit needs current registered WORKING evidence"
            )
        if (
            self.config.exits.variant in {"SPLIT_1R_TRAIL", "TRAIL_EMA20"}
            and self.held_exit_observation is None
        ):
            raise ExecutionDisabledError("EX: required held-exit observation hook is unavailable")
        if self.config.exits.variant == "SPLIT_1R_TRAIL" and self.environment == "LIVE":
            self._assert_live_raises()

    def _assert_playbook(self, name: str) -> None:
        if (
            name in {"TREND_50EMA", "BASE_BREAKOUT", "ANCHORED_VWAP_RECLAIM", "EARNINGS_GAP"}
            and name not in self.config.enabled_playbooks
        ):
            raise ExecutionDisabledError("EG-01: configured playbook is disabled")
        if name == "EARNINGS_GAP" and (
            self.playbook_allowed is None
            or self.playbook_allowed(Playbook.EARNINGS_GAP) is not True
        ):
            raise ExecutionDisabledError(
                "EG-01: AUTO earnings-gap requires registered WORKING walk-forward evidence"
            )

    def _assert_live_raises(self) -> None:
        if self.stop_raise_readiness is None:
            raise ExecutionDisabledError(
                "EX-06: live paper-raise and OCO/OTO integration evidence unavailable"
            )
        findings = self.stop_raise_readiness()
        if (
            not isinstance(findings, tuple)
            or len(findings) > 50
            or any(not isinstance(item, str) or not 1 <= len(item) <= 500 for item in findings)
        ):
            raise ExecutionDisabledError("EX-06: typed paper-raise evidence is UNVERIFIED")
        if findings:
            raise ExecutionDisabledError("EX-06: live stop raises locked: " + "; ".join(findings))

    async def enter(self, proposal_id: UUID, *, click: CallbackClick | None = None) -> Submission:
        async with account_lock(self.modes.account_id, self.environment):
            try:
                self._assert_ops()
                if not self.modes.entries_enabled or (
                    self.risk.marks is not None
                    and self.risk.marks.daily_loss_blocked(self.state.clock.now())
                ):
                    raise ExecutionDisabledError("Effective mode or account state blocks entries")
                now = ensure_utc(self.state.clock.now())
                if not entry_window(self.settings, self.calendar, now):
                    raise ExecutionDisabledError("AX-22 market-hours guard blocks entry")
                order, alert, proposal = self._loaded(proposal_id, click)
                with DatabaseSession(self.state.engine) as session:
                    existing = tuple(
                        session.scalars(
                            select(ExecutionOrderRecord)
                            .where(
                                ExecutionOrderRecord.order_id == order.id,
                                ExecutionOrderRecord.role == "ENTRY",
                            )
                            .order_by(ExecutionOrderRecord.seq)
                        )
                    )
                if existing:
                    known_orders = []
                    for prior in existing:
                        known = await self._lookup(prior.client_order_id)
                        if known is None:
                            raise ExecutionDisabledError(
                                "Prior durable intent is retained; never resubmit"
                            )
                        self._observe(prior, known)
                        known_orders.append(known)
                    return Submission(
                        proposal_id=proposal_id,
                        broker_order=known_orders[0],
                        recovered_after_ambiguity=True,
                        broker_orders=tuple(known_orders) if len(known_orders) > 1 else (),
                    )
                self._assert_entry_variant()
                if self.realtime_entry is not None:
                    await self.realtime_entry(proposal_id)
                self._assert_playbook(alert.playbook)
                await self._verify_account()
                async with asyncio.timeout(30):
                    inputs = FreshInputs.model_validate(await self.source.refresh(proposal.symbol))
                    self._arrival_quotes[proposal.symbol] = inputs.market
                if (
                    inputs.portfolio.account_id != self.modes.account_id
                    or inputs.portfolio.account_id != proposal.account_id
                ):
                    raise ReconciliationError("Fresh portfolio belongs to another account")
                if inputs.market.status != MarketStatus.OK:
                    raise ExecutionDisabledError("STALE or SUSPECT evidence blocks entry")
                if inputs.filings is not None and (
                    inputs.expected_cik != inputs.filings.cik or inputs.filings.fetched_at > now
                ):
                    raise DataIntegrityError("Fresh filing issuer or timestamp differs")
                if self.size_entry is not None or self.settings.execution_mode == "AUTO_LIVE":
                    qty = (
                        await self.size_entry(proposal, inputs)
                        if self.size_entry is not None
                        else proposal.qty // 4
                    )
                    if type(qty) is not int or not 0 <= qty <= proposal.qty:
                        raise DataIntegrityError(
                            "XK-03/06: entry overlays must only reduce whole shares"
                        )
                    if qty == 0:
                        raise ExecutionDisabledError("Reducing entry overlays produce zero shares")
                    proposal = TradeProposal.model_validate(
                        proposal.model_copy(update={"qty": qty})
                    )
                fundamental = compute_fundamentals(
                    self.risk.cro.registry.get(proposal.symbol),
                    inputs.filings,
                    self.state.clock.now(),
                    self.config.fundamentals,
                )
                if not framework_allows(fundamental, self.config.fundamentals):
                    raise ExecutionDisabledError("FA-08 fresh fundamental framework blocks entry")
                if self.realtime_entry is not None:
                    await self.realtime_entry(proposal_id)
                verdict = self.risk.evaluate(
                    proposal, inputs.portfolio, inputs.market, deployable=inputs.capital
                )
                assessment = self.compliance.evaluate(
                    proposal,
                    inputs.portfolio,
                    inputs.lots,
                    inputs.history,
                    inputs.tax_accounts,
                    flags=inputs.flags,
                )
                if (
                    verdict.decision != Decision.APPROVED
                    or any(
                        not row.passed and row.severity == Severity.BLOCK
                        for row in assessment.results
                    )
                    or self.state.current() != SystemState.RUNNING
                ):
                    raise ExecutionDisabledError("Fresh CRO or compliance blocks entry")
                if self.settings.day_trade_regime == "LEGACY_PDT":
                    _, completed = day_trade_activity(
                        self.calendar,
                        proposal.account_id,
                        proposal.symbol,
                        proposal.side,
                        inputs.history,
                        now,
                    )
                    if completed >= 2:
                        raise ExecutionDisabledError(
                            "AX-25 legacy five-session day-trade count blocks entry"
                        )
                count = self._daily_count()
                if count >= self.settings.auto_max_entries_per_day:
                    raise ExecutionDisabledError("AX-25 daily entry cap reached")
                with DatabaseSession(self.state.engine) as session:
                    prior_bindings = bindings(session)
                    for pending in session.scalars(
                        select(ExecutionOrderRecord).where(
                            ExecutionOrderRecord.account_id == self.modes.account_id,
                            ExecutionOrderRecord.environment == self.environment,
                            ExecutionOrderRecord.role == "ENTRY",
                            ExecutionOrderRecord.symbol == proposal.symbol,
                        )
                    ):
                        latest = session.scalar(
                            select(OrderEvent)
                            .where(OrderEvent.order_id == pending.order_id)
                            .order_by(OrderEvent.seq.desc())
                            .limit(1)
                        )
                        observed = prior_bindings.get(pending.id)
                        if held_quantity(session, pending.id) > 0 or (
                            (observed is None or observed.is_open)
                            and (latest is None or latest.state not in {"CANCELED", "REJECTED"})
                        ):
                            raise ExecutionDisabledError(
                                "AX-25 persisted position or pending intent blocks duplicate entry"
                            )
                if self.settings.execution_mode == "AUTO_LIVE" and live_ceiling_reasons(
                    self.settings, proposal, inputs.portfolio, count
                ):
                    raise ExecutionDisabledError("AX-42 live ceilings block entry")
                if (
                    (
                        proposal.symbol in inputs.portfolio.positions
                        and inputs.portfolio.positions[proposal.symbol].qty > 0
                    )
                    or any(row.symbol == proposal.symbol for row in inputs.portfolio.open_orders)
                    or any(
                        row.symbol == proposal.symbol for row in inputs.portfolio.protective_stops
                    )
                ):
                    raise ExecutionDisabledError(
                        "AX-25 existing position or pending order blocks duplicate entry"
                    )
                requests = self._entry_requests(proposal)
                for planned in requests:
                    if await self._lookup(planned.client_order_id) is not None:
                        raise ReconciliationError(
                            "An unrecorded order already uses this proposal client ID"
                        )
                if (
                    proposal.stop_price is None
                    or proposal.target_price is None
                    or proposal.stop_price
                    > min(proposal.limit_price, inputs.market.last_price) - Decimal("0.01")
                ):
                    raise ExecutionDisabledError(
                        "Bracket stop lacks Alpaca's one-cent base-price distance"
                    )

                def submit_guard() -> None:
                    try:
                        self._assert_ops()
                        self._assert_entry_variant()
                        self._assert_playbook(alert.playbook)
                    except ExecutionDisabledError as error:
                        raise EntryAdmissionRevoked(str(error)) from None
                    instant = ensure_utc(self.state.clock.now())
                    if (
                        not self.modes.entries_enabled
                        or (
                            self.risk.marks is not None
                            and self.risk.marks.daily_loss_blocked(instant)
                        )
                        or instant >= proposal.expires_at
                        or not entry_window(self.settings, self.calendar, instant)
                        or not timedelta(0)
                        <= instant - inputs.portfolio.as_of
                        <= timedelta(seconds=self.settings.stale_quote_seconds)
                        or not timedelta(0)
                        <= instant - inputs.market.last_price_ts
                        <= timedelta(seconds=self.settings.stale_quote_seconds)
                    ):
                        raise EntryAdmissionRevoked(
                            "Final mode, state, expiry or freshness guard blocks entry"
                        )
                    assert_auto_binding(self.settings, self.store)

                submit_guard()
                with transaction(self.state.engine) as session:
                    control = session.get(SystemControl, 1)
                    mode, paused = self.modes.in_session(session)
                    if control is None:
                        raise DataIntegrityError("Entry state projection is missing")
                    self.state._verify_projection(session, control)
                    if (
                        mode == "MANUAL"
                        or paused
                        or control.state != "RUNNING"
                        or self.state.clock.now() >= proposal.expires_at
                    ):
                        raise ExecutionDisabledError("Serialized state or mode check blocks entry")
                    approval = EntryApprovalEvidence(
                        proposal_id=proposal_id,
                        alert_id=alert.id,
                        account_id=self.modes.account_id,
                        environment=self.modes.environment,
                        actor="auto" if click is None else "telegram",
                        user_id=None if click is None else click.user_id,
                        config_hash=self.settings.config_hash,
                        yaml_hash=self.config.config_hash,
                        snapshot_hash=verdict.snapshot_hash,
                        compliance_input_hash=assessment.input_hash,
                        qty=proposal.qty,
                        exit_variant=self.config.exits.variant,
                        hold_sessions=cast(
                            Literal[10, 20, 30], self.config.evaluation.max_hold_sessions
                        ),
                        checked_at=verdict.evaluated_at,
                        risk_results=verdict.results,
                        compliance_results=assessment.results,
                    )
                    self.state.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="AUTO_ENTRY_APPROVAL",
                        detail={
                            **approval.model_dump(mode="json"),
                        },
                    )
                    self.state.ledger.append_in_session(
                        session,
                        OrderEvent,
                        order_id=order.id,
                        state="APPROVED",
                        reason="AUTO_APPROVED" if click is None else "AUTO_HYBRID_APPROVED",
                        broker_order_id=None,
                    )
                    instructions = []
                    for request in requests:
                        instruction = self.state.ledger.append_in_session(
                            session,
                            ExecutionOrderRecord,
                            order_id=order.id,
                            parent_execution_id=None,
                            client_order_id=request.client_order_id,
                            account_id=self.modes.account_id,
                            environment=self.environment,
                            symbol=proposal.symbol,
                            role="ENTRY",
                            side="BUY",
                            order_type="LIMIT",
                            qty=request.qty,
                            limit_price=proposal.limit_price,
                            stop_price=proposal.stop_price,
                            target_price=None
                            if request.take_profit is None
                            else request.take_profit.limit_price,
                            time_in_force="GTC",
                            config_hash=self.settings.config_hash,
                            valid_until=proposal.expires_at,
                        )
                        instructions.append(instruction)
                    self.state.ledger.append_in_session(
                        session,
                        OrderEvent,
                        order_id=order.id,
                        state="SUBMITTED",
                        reason="durable client-ID intent; broker acknowledgement not yet confirmed",
                        broker_order_id=None,
                    )
                try:
                    submitted = []
                    recovered = False
                    for instruction, request in zip(instructions, requests, strict=True):
                        broker, ambiguous = await self._submit(
                            instruction, request, guard=submit_guard
                        )
                        recovered = recovered or ambiguous
                        self._register_children(instruction, broker)
                        submitted.append(broker)
                except EntryAdmissionRevoked:
                    self.state.ledger.append(
                        OrderEvent,
                        order_id=order.id,
                        state="CANCELED",
                        reason="final guard revoked admission before physical request; no submit",
                        broker_order_id=None,
                    )
                    raise
                except OrderRejectedError:
                    self.state.ledger.append(
                        OrderEvent,
                        order_id=order.id,
                        state="REJECTED",
                        reason="broker rejection confirmed; no retry",
                        broker_order_id=None,
                    )
                    raise
                await self._trade_notice(
                    f"{self.environment} · Submitted {self._quantity(proposal.qty)} {proposal.symbol} LIMIT ${proposal.limit_price:.2f}; broker stop verification pending.",
                    False,
                    order.id,
                )
                return Submission(
                    proposal_id=proposal_id,
                    broker_order=submitted[0],
                    recovered_after_ambiguity=recovered,
                    broker_orders=tuple(submitted) if len(submitted) > 1 else (),
                )
            except ExecutionDisabledError as error:
                self.state.ledger.append(
                    SecurityEvent,
                    kind="AUTO_ENTRY_BLOCKED",
                    detail={"proposal_id": str(proposal_id), "reason": str(error)[:280]},
                )
                raise

            except Exception as error:
                self.state.halt_for_error(error)
                raise ProviderError(
                    "Automatic entry failed closed; inspect persisted intent"
                ) from None

    async def _trade_notice(self, text: str, urgent: bool, order_id: UUID) -> None:
        if self.trade_notice is None:
            await self.notify(text, urgent)
            return
        with DatabaseSession(self.state.engine) as session:
            order = session.get(Order, order_id)
            if order is None or order.account_id != self.modes.account_id:
                raise DataIntegrityError("XK-02: trade FYI requires a bound proposal")
            proposal_id = order.proposal_id
        await self.trade_notice(
            text + " · " + display_time(self.state.clock.now(), self.settings), urgent, proposal_id
        )

    def _instructions(self) -> tuple[ExecutionOrderRecord, ...]:
        self.state.ledger.verify_chain()
        with DatabaseSession(self.state.engine) as session:
            return tuple(
                session.scalars(
                    select(ExecutionOrderRecord)
                    .where(
                        ExecutionOrderRecord.account_id == self.modes.account_id,
                        ExecutionOrderRecord.environment == self.environment,
                    )
                    .order_by(ExecutionOrderRecord.seq)
                )
            )

    def _register_children(self, parent: ExecutionOrderRecord, broker: BrokerOrder) -> None:
        """AX-31: generated child IDs are accepted only from the proved bracket."""
        if parent.role == "REPAIR" and broker.order_class == "oco":
            with DatabaseSession(self.state.engine) as session:
                held_entry = session.get(ExecutionOrderRecord, parent.parent_execution_id)
            if held_entry is None or held_entry.role != "ENTRY":
                raise ReconciliationError("EX-05: OCO stop child lost its held entry")
            parent = held_entry
        elif parent.role != "ENTRY":
            return
        for child in broker.legs:
            with DatabaseSession(self.state.engine) as session:
                instruction = session.scalar(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.client_order_id == child.client_order_id
                    )
                )
            if instruction is None:
                instruction = self.state.ledger.append(
                    ExecutionOrderRecord,
                    order_id=parent.order_id,
                    parent_execution_id=parent.id,
                    client_order_id=child.client_order_id,
                    account_id=parent.account_id,
                    environment=parent.environment,
                    symbol=parent.symbol,
                    role="STOP" if child.order_type == "stop" else "TARGET",
                    side="SELL",
                    order_type=child.order_type.upper(),
                    qty=child.qty,
                    limit_price=child.limit_price,
                    stop_price=child.stop_price,
                    target_price=None,
                    time_in_force="GTC",
                    config_hash=parent.config_hash,
                    valid_until=None,
                    created_at=child.submitted_at,
                )
                self._observe(instruction, child)
            elif instruction.parent_execution_id != parent.id:
                raise ReconciliationError("Generated child already belongs to another entry")

    async def prepare_fills(self, symbols: tuple[str, ...]) -> None:
        """Bind broker identities before the tax activity batch calls record_fill.

        This read/audit hook never places orders or reacquires the entry lock:
        fresh-entry refresh may call it while the account lock is already held.
        Resized existing children are observed after the entire activity batch,
        when the ledger can prove their reduced remaining quantity.
        """
        try:
            for row in self._instructions():
                if row.role != "ENTRY" or row.symbol not in symbols:
                    continue
                broker = await self._lookup(row.client_order_id)
                if broker is not None:
                    self._observe(row, broker)
                    self._register_children(row, broker)
        except Exception as error:
            self.state.halt_for_error(error)
            raise ReconciliationError("Fill identities cannot be bound; entries halted") from None

    def observe_fill(self, observation: ObservedFill) -> ExecutionFillRecord:
        """AX-26: one exact, account-bound activity ID through the shared ledger."""
        return ExecutionFillCapture(self.modes).record(observation)

    async def _read_bound(self, instruction: ExecutionOrderRecord) -> BrokerOrder | None:
        with DatabaseSession(self.state.engine) as session:
            previous = bindings(session).get(instruction.id)
        if previous is not None:
            try:
                raw = await self.worker.attempt(
                    lambda: self.client.get_order_by_id(previous.order_id)
                )
                broker = parse_order(raw, parent_id=previous.parent_id)
            except Exception as error:
                raise ReconciliationError("Previously bound broker order disappeared") from error
        else:
            looked_up = await self._lookup(instruction.client_order_id)
            if looked_up is None:
                return None
            broker = looked_up
        if instruction.role in {"STOP", "TARGET"}:
            with DatabaseSession(self.state.engine) as session:
                parents = tuple(
                    row
                    for row in bindings(session).values()
                    if any(
                        leg.order_id == broker.order_id
                        and leg.client_order_id == broker.client_order_id
                        for leg in row.legs
                    )
                )
            if len(parents) != 1:
                raise ReconciliationError("Generated broker child has no proved parent")
            broker = BrokerOrder.model_validate(
                broker.model_copy(update={"parent_id": parents[0].order_id})
            )
        self._observe(instruction, broker)
        if instruction.role == "ENTRY" or broker.order_class == "oco":
            self._register_children(instruction, broker)
        return broker

    async def _positions(self) -> dict[str, int]:
        raw = await self.worker.attempt(self.client.get_all_positions)
        if not isinstance(raw, list) or len(raw) > 500:
            raise ReconciliationError("Broker position collection is unavailable or unbounded")
        positions: dict[str, int] = {}
        for row in raw:
            if (
                not isinstance(row, Mapping)
                or row.get("side") != "long"
                or row.get("asset_class") != "us_equity"
                or not isinstance(row.get("symbol"), str)
            ):
                raise ReconciliationError("Broker position is not a verified long equity")
            symbol = row["symbol"]
            if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) is None:
                raise ReconciliationError("Broker position symbol is invalid")
            if symbol in positions:
                raise ReconciliationError("Broker positions contain a duplicate symbol")
            positions[symbol] = _whole(row.get("qty"), positive=True)
        return positions

    async def record_paper_cancel_semantics(self, oto_entry_id: UUID, oco_exit_id: UUID) -> None:
        """EX-06: fresh, read-only verification of an explicit integration exercise.

        The caller supplies already-recorded paper roots. This cannot manufacture
        orders, cancel a held stop, or certify live service from stored observations.
        """
        from backend.execution.stop_readiness import CancelSemanticsProof

        if not self.settings.paper_trading or self.modes.effective != "AUTO_PAPER":
            raise ExecutionDisabledError("EX-06: explicit AUTO_PAPER integration only")
        async with account_lock(self.modes.account_id, "PAPER"):
            self.state.ledger.verify_chain()
            await self._verify_account()
            with DatabaseSession(self.state.engine) as session:
                oto = session.get(ExecutionOrderRecord, oto_entry_id)
                oco = session.get(ExecutionOrderRecord, oco_exit_id)
                if (
                    oto is None
                    or oco is None
                    or oto.role != "ENTRY"
                    or oco.role != "REPAIR"
                    or any(
                        row.account_id != self.modes.account_id
                        or row.environment != "PAPER"
                        or row.config_hash != self.settings.config_hash
                        for row in (oto, oco)
                    )
                ):
                    raise DataIntegrityError("EX-06: bound canonical paper roots required")
            for root in (oto, oco):
                with DatabaseSession(self.state.engine) as session:
                    prior = bindings(session).get(root.id)
                if prior is None:
                    raise DataIntegrityError("EX-06: previously bound paper root required")
                # VERIFIED pinned SDK 0.44.0: nested=True is required to inspect
                # fresh generated legs, rather than trusting saved child lists.
                root_id = prior.order_id

                def read_nested_root(order_id: UUID = root_id) -> Any:
                    return self.client.get_order_by_id(
                        order_id, filter=GetOrderByIdRequest(nested=True)
                    )

                raw = await self.worker.attempt(read_nested_root)
                broker = parse_order(raw)
                self._observe(root, broker)
                self._register_children(root, broker)
            with DatabaseSession(self.state.engine) as session:
                proved = bindings(session)
                parent = proved.get(oto.id)
                target = proved.get(oco.id)
                if parent is None or target is None:
                    raise DataIntegrityError("EX-06: fresh paper roots unavailable")
                stops = tuple(
                    session.scalars(
                        select(ExecutionOrderRecord).where(
                            ExecutionOrderRecord.role == "STOP",
                            ExecutionOrderRecord.parent_execution_id.in_(
                                (oto.id, oco.parent_execution_id)
                            ),
                        )
                    )
                )
                matched = tuple(
                    next((row for row in stops if row.client_order_id == leg.client_order_id), None)
                    for root in (parent, target)
                    for leg in root.legs
                    if leg.order_type == "stop"
                )
                if len(matched) != 2 or any(row is None for row in matched):
                    raise DataIntegrityError("EX-06: two recorded generated stop legs required")
            first, second = (cast(ExecutionOrderRecord, row) for row in matched)
            await self._read_bound(first)
            await self._read_bound(second)
            proof = CancelSemanticsProof(
                account_id=self.modes.account_id,
                yaml_hash=self.config.config_hash,
                config_hash=self.settings.config_hash,
                oto_entry_id=oto.id,
                oto_stop_id=first.id,
                oco_exit_id=oco.id,
                oco_stop_id=second.id,
                observed_at=self.state.clock.now(),
            )
            # The shared append validator checks the actual canceled statuses,
            # parent identities and pinned SDK binding before publishing proof.
            self.state.ledger.append(
                SecurityEvent, kind="PAPER_CANCEL_SEMANTICS", detail=proof.model_dump(mode="json")
            )

    async def _open_orders(self) -> tuple[BrokerOrder, ...]:
        # VERIFY: pinned GetOrdersRequest, OPEN + nested; a full page is not proof
        # of completeness and fails closed instead of hiding additional orders.
        raw = await self.worker.attempt(
            lambda: self.client.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500, nested=True)
            )
        )
        if not isinstance(raw, list) or len(raw) >= 500:
            raise ReconciliationError("Complete open-order collection cannot be verified")
        return tuple(parse_order(row) for row in raw)

    async def _cancel_confirmed(
        self, instruction: ExecutionOrderRecord, broker: BrokerOrder, *, deadline_seconds: int = 30
    ) -> BrokerOrder:
        if type(deadline_seconds) is not int or not 1 <= deadline_seconds <= 30:
            raise ProviderError("Cancel confirmation requires a bounded deadline")
        async with asyncio.timeout(deadline_seconds):
            return await self._cancel_and_poll(instruction, broker)

    async def _cancel_and_poll(
        self, instruction: ExecutionOrderRecord, broker: BrokerOrder
    ) -> BrokerOrder:
        if not broker.is_open:
            return broker
        try:
            # A cancel is also a single physical attempt. On ambiguity read the
            # order; never repeat DELETE blindly or guess that it was canceled.
            await self.worker.attempt(lambda: self.client.cancel_order_by_id(broker.order_id))
        except Exception as error:
            self.state.ledger.append(
                SecurityEvent,
                kind="EXECUTION_CANCEL_AMBIGUOUS",
                detail={
                    "account_id": self.modes.account_id,
                    "environment": self.environment,
                    "execution_order_id": str(instruction.id),
                    "error_type": type(error).__name__,
                },
            )
        async with asyncio.timeout(30):
            for attempt in range(3):
                raw = await self.worker.attempt(
                    lambda: self.client.get_order_by_id(broker.order_id)
                )
                checked = parse_order(raw, parent_id=broker.parent_id)
                self._observe(instruction, checked)
                if not checked.is_open:
                    break
                if attempt < 2:
                    await asyncio.sleep(0.2)
        if checked.is_open:
            raise ProviderError("Cancellation is unconfirmed; no replacement or retry")
        with DatabaseSession(self.state.engine) as session:
            if checked.filled_qty != filled_quantity(session, instruction.id):
                raise ReconciliationError(
                    "Cancellation raced a fill; capture activities before recovery"
                )
        return checked

    async def _repair_stop(
        self,
        entry: ExecutionOrderRecord,
        qty: int,
        *,
        approval: StopRaiseApproval | None = None,
        repair: bool = False,
        repair_level: Decimal | None = None,
    ) -> BrokerOrder:
        """AX-27/30: protective SELL is independent of entry state and mode."""
        if qty <= 0 or entry.stop_price is None:
            raise ReconciliationError("Stop repair has no verified positive held shares or level")
        await self._verify_account()
        broker_qty = (await self._positions()).get(entry.symbol, 0)
        with DatabaseSession(self.state.engine) as session:
            held = held_quantity(session, entry.id)
            level = current_stop(session, entry) if approval is None else approval.new_stop
            if repair_level is not None:
                if approval is None or not repair or not approval.old_stop <= repair_level <= level:
                    raise ReconciliationError("EX-05: repair cannot lower proved protection")
                level = repair_level
            attempts = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.parent_execution_id == entry.id,
                        ExecutionOrderRecord.role.in_(("REPAIR", "EXIT")),
                    )
                )
            )
        if qty != held or qty > broker_qty:
            raise ReconciliationError("Protective sell exceeds verified managed broker shares")
        target = entry.target_price if approval is not None and not repair else None
        client_id = (
            f"vws-x-{entry.client_order_id.removeprefix('vws-')}-{len(attempts) + 1}"
            if approval is None
            else "vws-m-" + approval.raise_id.hex + ("-r" if repair else "")
        )
        if await self._lookup(client_id) is not None:
            raise ReconciliationError("New stop client ID already exists without a local intent")
        instruction = self.state.ledger.append(
            ExecutionOrderRecord,
            order_id=entry.order_id,
            parent_execution_id=entry.id,
            client_order_id=client_id,
            account_id=entry.account_id,
            environment=entry.environment,
            symbol=entry.symbol,
            role="REPAIR",
            side="SELL",
            order_type="STOP" if target is None else "LIMIT",
            qty=qty,
            limit_price=target,
            stop_price=level,
            target_price=target,
            time_in_force="GTC",
            config_hash=self.settings.config_hash,
            valid_until=None,
        )
        request: ExactLimit | ExactStop = (
            ExactStop(
                symbol=entry.symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                client_order_id=client_id,
                stop_price=level,
            )
            if target is None
            else ExactLimit(
                symbol=entry.symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                client_order_id=client_id,
                order_class=OrderClass.OCO,
                limit_price=target,
                take_profit=ExactTakeProfit(limit_price=target),
                stop_loss=ExactStopLoss(stop_price=level),
            )
        )

        def protect_guard() -> None:
            assert_auto_binding(self.settings, self.store)
            with DatabaseSession(self.state.engine) as session:
                if held_quantity(session, entry.id) != qty:
                    raise ReconciliationError("Held shares changed before protective submit")
            if (
                approval is not None
                and not repair
                and not timedelta(0)
                <= (self.state.clock.now() - approval.quote_at)
                <= timedelta(seconds=self.settings.stale_quote_seconds)
            ):
                raise EntryAdmissionRevoked("EX-05: stop-raise quote expired before submit")

        try:
            await self._submit(instruction, request, guard=protect_guard)
            confirmed = await self._read_bound(instruction)
            if (
                confirmed is None
                or not confirmed.is_open
                or confirmed.status in {"held", "suspended", "pending_cancel"}
            ):
                raise ReconciliationError("Submitted protective stop is not confirmed active")
            if target is not None and not any(
                child.order_type == "stop"
                and child.is_open
                and child.status not in {"held", "suspended", "pending_cancel"}
                and child.stop_price == level
                and child.qty - child.filled_qty == qty
                for child in confirmed.legs
            ):
                raise ReconciliationError("EX-05: OCO stop child is not confirmed active")
            if approval is None:
                await self._trade_notice(
                    f"{self.environment} · Stop repaired for {self._quantity(qty)} {entry.symbol} at ${level:.2f} (at broker).",
                    True,
                    entry.order_id,
                )
            return confirmed
        except Exception as error:
            self.state.halt_for_error(error)
            await self._trade_notice(
                f"{self.environment} · HALTED: stop repair failed for {entry.symbol}; inspect broker protection urgently.",
                True,
                entry.order_id,
            )
            raise ReconciliationError("Protective stop could not be confirmed; HALTED") from None

    async def _ensure_stop(self, entry: ExecutionOrderRecord, qty: int) -> None:
        with DatabaseSession(self.state.engine) as session:
            proved = bindings(session)
            level = current_stop(session, entry)
            children = tuple(
                row
                for row in session.scalars(
                    select(ExecutionOrderRecord)
                    .where(ExecutionOrderRecord.parent_execution_id == entry.id)
                    .order_by(ExecutionOrderRecord.seq)
                )
                if row.id not in proved or proved[row.id].is_open
            )
        opened: list[tuple[ExecutionOrderRecord, BrokerOrder]] = []
        for row in children:
            broker = await self._read_bound(row)
            if broker is not None and broker.is_open:
                opened.append((row, broker))
            elif broker is None and not self._confirmed_absence(row):
                raise ReconciliationError(
                    "Unconfirmed sell outcome prevents overlapping stop coverage"
                )
        active = [
            (row, order)
            for row, order in opened
            if row.role in {"STOP", "REPAIR"}
            and order.order_type == "stop"
            and order.status not in {"held", "suspended", "pending_cancel"}
        ]
        covered = sum(order.qty - order.filled_qty for _, order in active)
        if covered == qty and all(order.stop_price == level for _, order in active):
            return
        # Clear known old sell reservations, including inactive bracket legs,
        # before one exact repair. Canceling a group leg may cancel its sibling.
        for row, _broker in opened:
            current = await self._read_bound(row)
            if current is not None and current.is_open:
                await self._cancel_confirmed(row, current)
        await self._repair_stop(entry, qty)

    def _cycle_event(self, cycle: ExitCycleEvidence, state: str) -> None:
        checked = ExitCycleEvidence.model_validate(cycle.model_copy(update={"state": state}))
        self.state.ledger.append(
            SecurityEvent, kind="AUTO_EXIT_CYCLE", detail=checked.model_dump(mode="json")
        )

    async def _fresh_exit_inputs(self, entry: ExecutionOrderRecord) -> FreshInputs:
        async with asyncio.timeout(30):
            inputs = FreshInputs.model_validate(await self.source.refresh(entry.symbol))
            self._arrival_quotes[entry.symbol] = inputs.market
        now = ensure_utc(self.state.clock.now())
        if (
            inputs.portfolio.account_id != self.modes.account_id
            or not timedelta(0)
            <= now - inputs.market.last_price_ts
            <= timedelta(seconds=self.settings.stale_quote_seconds)
            or not timedelta(0)
            <= now - inputs.portfolio.as_of
            <= timedelta(seconds=self.settings.stale_quote_seconds)
        ):
            raise ExecutionDisabledError(
                "A fresh bound IEX quote and broker snapshot are required for an exit limit"
            )
        return inputs

    async def _cancel_sells(
        self, entry: ExecutionOrderRecord, *, deadline_seconds: int = 30
    ) -> None:
        with DatabaseSession(self.state.engine) as session:
            proved = bindings(session)
            rows = tuple(
                row
                for row in session.scalars(
                    select(ExecutionOrderRecord)
                    .where(ExecutionOrderRecord.parent_execution_id == entry.id)
                    .order_by(ExecutionOrderRecord.seq)
                )
                if row.id not in proved or proved[row.id].is_open
            )
        for row in rows:
            current = await self._read_bound(row)
            if current is not None and current.is_open:
                await self._cancel_confirmed(row, current, deadline_seconds=deadline_seconds)
            elif current is None and not self._confirmed_absence(row):
                raise ReconciliationError(
                    "An unknown sell outcome prevents a conflicting stop or replacement"
                )

    def _confirmed_absence(self, instruction: ExecutionOrderRecord) -> bool:
        with DatabaseSession(self.state.engine) as session:
            for event in session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
                .order_by(SecurityEvent.seq.desc())
            ):
                evidence = SubmitOutcome.model_validate(event.detail)
                if evidence.execution_order_id == instruction.id:
                    return evidence.outcome in {"NOT_SENT", "REJECTED"}
        return False

    def _held_entry(self, entry: ExecutionOrderRecord) -> HeldEntry:
        with DatabaseSession(self.state.engine) as session:
            original = session.get(Order, entry.order_id)
            approval = (
                None
                if original is None
                else approval_evidence(session, original.proposal_id, entry.seq)
            )
            fills = tuple(
                session.scalars(
                    select(ExecutionFillRecord)
                    .where(ExecutionFillRecord.execution_order_id == entry.id)
                    .order_by(ExecutionFillRecord.filled_at)
                    .limit(100001)
                )
            )
        if (
            approval is None
            or not fills
            or len(fills) > 100000
            or entry.stop_price is None
            or entry.limit_price is None
        ):
            raise ReconciliationError(
                "EX: held entry lacks its original approval or captured fills"
            )
        with localcontext() as precision:
            precision.prec = 80
            cost = sum((row.price * row.qty for row in fills), Decimal(0))
        return HeldEntry(
            entry_id=entry.id,
            account_id=entry.account_id,
            environment=self.modes.environment,
            symbol=entry.symbol,
            first_fill=fills[0].filled_at,
            filled_qty=sum(row.qty for row in fills),
            entry_cost=cost,
            entry_limit=entry.limit_price,
            initial_stop=entry.stop_price,
            variant=approval.exit_variant,
            hold_sessions=approval.hold_sessions,
        )

    def _record_held_quote(self, held: HeldEntry, inputs: FreshInputs) -> None:
        if inputs.market.last_price_ts < held.first_fill:
            return
        observed = HeldQuoteObservation(
            entry_id=held.entry_id,
            account_id=held.account_id,
            environment=held.environment,
            symbol=held.symbol,
            price=inputs.market.last_price,
            trade_at=inputs.market.last_price_ts,
            known_at=self.state.clock.now(),
        )
        payload = observed.model_dump(mode="json")
        with DatabaseSession(self.state.engine) as session:
            latest = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "HELD_QUOTE_OBSERVED",
                    SecurityEvent.detail["entry_id"].as_string() == str(held.entry_id),
                )
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
        if latest is not None:
            prior = HeldQuoteObservation.recorded(latest.detail)
            if (prior.trade_at, prior.price) == (observed.trade_at, observed.price):
                return
        self.state.ledger.append(SecurityEvent, kind="HELD_QUOTE_OBSERVED", detail=payload)
        from backend.evaluation.tca_store import record_arrival

        with DatabaseSession(self.state.engine) as session:
            active = bindings(session)
            protections = tuple(
                session.scalars(
                    select(ExecutionOrderRecord)
                    .where(
                        ExecutionOrderRecord.parent_execution_id == held.entry_id,
                        ExecutionOrderRecord.order_type == "STOP",
                    )
                    .limit(1001)
                )
            )
            if len(protections) > 1000:
                raise DataIntegrityError("XA-01: stop quote inventory exceeds its bound")
        for instruction in protections:
            proved = active.get(instruction.id)
            if (
                proved is not None
                and proved.is_open
                and proved.status not in {"held", "suspended", "pending_cancel"}
            ):
                record_arrival(
                    self.state.ledger, instruction, inputs.market, self.settings.stale_quote_seconds
                )

    async def _held_observation(
        self, entry: ExecutionOrderRecord, inputs: FreshInputs
    ) -> HeldExitObservation:
        held = self._held_entry(entry)
        self._record_held_quote(held, inputs)
        hook = self.held_exit_observation
        if hook is None:
            raise DataIntegrityError("EX: completed held-exit observation unavailable")
        async with asyncio.timeout(30):
            observation = HeldExitObservation.model_validate(await hook(held, inputs))
        if (
            observation.entry != held
            or observation.known_at
            < self.calendar.session_close(observation.session)
            + timedelta(minutes=self.config.schedule.daily_scan_delay_minutes)
            or observation.known_at > self.state.clock.now()
            or observation.session
            != self.calendar.last_completed_session(
                self.state.clock.now()
                - timedelta(minutes=self.config.schedule.daily_scan_delay_minutes)
            )
        ):
            raise DataIntegrityError(
                "EX: held-exit evidence has another entry, future or stale session"
            )
        return observation

    async def _exit_step(self, entry: ExecutionOrderRecord, qty: int) -> bool:
        """AX-29/30: one initial DAY limit, at most three fixed reprices.

        Each reprice is a new immutable instruction after confirmed cancellation.
        A failed cycle restores a broker stop and sends an urgent notice. The
        same failed reason is not restarted repeatedly in the same session.
        """
        now = ensure_utc(self.state.clock.now())
        today = now.astimezone(ZoneInfo("America/New_York")).date()
        with DatabaseSession(self.state.engine) as session:
            history = tuple(row for row in exit_cycles(session) if row.entry_id == entry.id)
            cycle = history[-1] if history else None
            first_fill = session.scalar(
                select(ExecutionFillRecord.filled_at)
                .where(ExecutionFillRecord.execution_order_id == entry.id)
                .order_by(ExecutionFillRecord.filled_at)
                .limit(1)
            )
        if qty == 0:
            if cycle is not None and cycle.state == "ACTIVE":
                self._cycle_event(cycle, "DONE")
                await self._trade_notice(
                    f"{self.environment} · {entry.symbol} exit completed; no held shares remain.",
                    False,
                    entry.order_id,
                )
            return False
        if cycle is None or cycle.state != "ACTIVE":
            if not self.calendar.is_open(now) or not self.settings.auto_exits:
                return False
            inputs = await self._fresh_exit_inputs(entry)
            if first_fill is None:
                raise ReconciliationError("Exit has no captured entry fill")
            held_policy = self._held_entry(entry)
            values = self.config.model_dump(mode="python")
            values["evaluation"]["max_hold_sessions"] = held_policy.hold_sessions
            entry_policy = YamlConfig.model_validate(values)
            hard = (
                None if self.realtime_exit is None else self.realtime_exit(entry.symbol, first_fill)
            )
            if hard is not None and any(row.rt_event_key == hard[1] for row in history):
                hard = None  # At most one AX-29 cycle for this event and held entry.
            reason = (
                hard[0]
                if hard is not None
                else automatic_exit_reason(
                    self.settings, entry_policy, self.calendar, first_fill, inputs.market, now
                )
            )
            if reason is None and held_policy.variant == "TRAIL_EMA20":
                observation = await self._held_observation(entry, inputs)
                if observation.ema_signal and now >= self.calendar.session_open(
                    self.calendar.add_sessions(observation.session, 1)
                ):
                    self.state.ledger.append(
                        SecurityEvent,
                        kind="HELD_EXIT_SIGNAL",
                        detail=observation.model_dump(mode="json"),
                    )
                    reason = "EMA20"
            if reason is None or (
                cycle is not None
                and cycle.state == "FAILED"
                and cycle.session_date == today
                and cycle.reason == reason
            ):
                return False
            cycle = ExitCycleEvidence(
                cycle_id=uuid4(),
                entry_id=entry.id,
                account_id=entry.account_id,
                environment=self.modes.environment,
                config_hash=self.settings.config_hash,
                reason=reason,
                state="ACTIVE",
                session_date=today,
                rt_event_key=None if hard is None else hard[1],
            )
            self._cycle_event(cycle, "ACTIVE")
        with DatabaseSession(self.state.engine) as session:
            approvals = tuple(
                row for row in exit_approvals(session) if row.cycle_id == cycle.cycle_id
            )
            previous = (
                None
                if not approvals
                else session.scalar(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.client_order_id == approvals[-1].client_order_id
                    )
                )
            )
        if previous is not None:
            broker = await self._read_bound(previous)
            if broker is None:
                raise ReconciliationError("Pending exit outcome is unverifiable; no retry")
            if broker.is_open:
                if self.calendar.is_open(now) and now - previous.created_at < timedelta(minutes=2):
                    return True
                await self._cancel_confirmed(previous, broker)
        if not self.calendar.is_open(now) or len(approvals) >= 4:
            await self._ensure_stop(entry, qty)
            self._cycle_event(cycle, "FAILED")
            await self._trade_notice(
                f"{self.environment} · {entry.symbol} exit remains unfilled; broker stop restored. Operator review required.",
                True,
                entry.order_id,
            )
            return False
        try:
            inputs = await self._fresh_exit_inputs(entry)
            await self._cancel_sells(entry)
            await self._verify_account()
            broker_qty = (await self._positions()).get(entry.symbol, 0)
            with DatabaseSession(self.state.engine) as session:
                held = held_quantity(session, entry.id)
                attempts = tuple(
                    session.scalars(
                        select(ExecutionOrderRecord).where(
                            ExecutionOrderRecord.parent_execution_id == entry.id,
                            ExecutionOrderRecord.role.in_(("EXIT", "REPAIR")),
                        )
                    )
                )
            if qty != held or qty > broker_qty:
                raise ReconciliationError("Exit would exceed verified held broker shares")
            client_id = f"vws-x-{entry.client_order_id.removeprefix('vws-')}-{len(attempts) + 1}"
            if await self._lookup(client_id) is not None:
                raise ReconciliationError(
                    "Exit client ID already exists without a local instruction"
                )
            limit = exit_limit(inputs.market.last_price, self.settings.auto_exit_limit_offset)
            authorization = ExitApprovalEvidence(
                cycle_id=cycle.cycle_id,
                entry_id=entry.id,
                client_order_id=client_id,
                attempt=len(approvals) + 1,
                account_id=entry.account_id,
                environment=self.modes.environment,
                config_hash=self.settings.config_hash,
                qty=qty,
                market_price=inputs.market.last_price,
                limit_price=limit,
                offset=self.settings.auto_exit_limit_offset,
                quote_at=inputs.market.last_price_ts,
                checked_at=self.state.clock.now(),
            )
            with transaction(self.state.engine) as session:
                self.state.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="AUTO_EXIT_APPROVAL",
                    detail=authorization.model_dump(mode="json"),
                )
                instruction = self.state.ledger.append_in_session(
                    session,
                    ExecutionOrderRecord,
                    order_id=entry.order_id,
                    parent_execution_id=entry.id,
                    client_order_id=client_id,
                    account_id=entry.account_id,
                    environment=entry.environment,
                    symbol=entry.symbol,
                    role="EXIT",
                    side="SELL",
                    order_type="LIMIT",
                    qty=qty,
                    limit_price=limit,
                    stop_price=None,
                    target_price=None,
                    time_in_force="DAY",
                    config_hash=self.settings.config_hash,
                    valid_until=None,
                )
            request = ExactLimit(
                symbol=entry.symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.SIMPLE,
                client_order_id=client_id,
                limit_price=limit,
            )

            def exit_guard() -> None:
                assert_auto_binding(self.settings, self.store)
                instant = ensure_utc(self.state.clock.now())
                with DatabaseSession(self.state.engine) as session:
                    current = held_quantity(session, entry.id)
                if (
                    current != qty
                    or not self.calendar.is_open(instant)
                    or not timedelta(0)
                    <= instant - inputs.market.last_price_ts
                    <= timedelta(seconds=self.settings.stale_quote_seconds)
                ):
                    raise EntryAdmissionRevoked(
                        "Exit quantity, session or quote changed before physical request"
                    )

            await self._submit(instruction, request, guard=exit_guard)
            await self._trade_notice(
                f"{self.environment} · {entry.symbol} {cycle.reason.lower()} exit submitted: {self._quantity(qty)} shares LIMIT ${limit:.2f}; attempt {authorization.attempt}/4.",
                False,
                entry.order_id,
            )
            return True
        except Exception:
            # A live DAY exit with an ambiguous outcome must first be located
            # and canceled. Never overlap a new stop with unknown sell shares.
            await self._cancel_sells(entry)
            await self._ensure_stop(entry, qty)
            self._cycle_event(cycle, "FAILED")
            await self._trade_notice(
                f"{self.environment} · {entry.symbol} exit failed; broker stop restored. Operator review required.",
                True,
                entry.order_id,
            )
            raise

    async def _reconcile(self) -> tuple[tuple[ExecutionOrderRecord, int], ...]:
        await self._verify_account()
        instructions = self._instructions()
        entries = tuple(row for row in instructions if row.role == "ENTRY")
        with DatabaseSession(self.state.engine) as session:
            held = tuple((row, held_quantity(session, row.id)) for row in entries)
        local: dict[str, int] = {}
        for row, qty in held:
            local[row.symbol] = local.get(row.symbol, 0) + qty
        positions = await self._positions()
        self.state.ledger.reconcile(positions, local)
        with DatabaseSession(self.state.engine) as session:
            proved = bindings(session)
        managed = {order.order_id for order in proved.values()}
        for parent in await self._open_orders():
            if parent.order_id not in managed:
                raise ReconciliationError(
                    "Unknown broker order; manual trading belongs in a different account"
                )
            for child in parent.legs:
                if child.order_id not in managed:
                    raise ReconciliationError("Unbound bracket child is present in the account")
        active_parents = {row.id for row, qty in held if qty > 0}
        active_parents.update(
            row.id
            for row in instructions
            if row.role == "ENTRY" and (row.id not in proved or proved[row.id].is_open)
        )
        for instruction in instructions:
            if (
                instruction.id in proved
                and not proved[instruction.id].is_open
                and instruction.id not in active_parents
            ):
                continue
            broker = await self._read_bound(instruction)
            if broker is None:
                if instruction.role != "ENTRY" and self._confirmed_absence(instruction):
                    with DatabaseSession(self.state.engine) as session:
                        if filled_quantity(session, instruction.id) != 0:
                            raise ReconciliationError("Absent sell intent has captured fills")
                    continue
                with DatabaseSession(self.state.engine) as session:
                    latest = session.scalar(
                        select(OrderEvent)
                        .where(OrderEvent.order_id == instruction.order_id)
                        .order_by(OrderEvent.seq.desc())
                        .limit(1)
                    )
                not_sent = False
                if latest is not None and latest.state == "CANCELED":
                    with DatabaseSession(self.state.engine) as session:
                        not_sent = any(
                            evidence.execution_order_id == instruction.id
                            and evidence.outcome == "NOT_SENT"
                            for evidence in (
                                SubmitOutcome.model_validate(row.detail)
                                for row in session.scalars(
                                    select(SecurityEvent).where(
                                        SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME"
                                    )
                                )
                            )
                        )
                if (
                    instruction.role != "ENTRY"
                    or latest is None
                    or (latest.state != "REJECTED" and not not_sent)
                ):
                    raise ReconciliationError(
                        "Durable order outcome remains unverifiable; no retry"
                    )
                continue
            with DatabaseSession(self.state.engine) as session:
                if broker.filled_qty != filled_quantity(session, instruction.id):
                    raise ReconciliationError("Broker order fills differ from captured activities")
        self.state.ledger.append(
            SecurityEvent,
            kind="AUTO_RECONCILED",
            detail={
                "account_id": self.modes.account_id,
                "environment": self.environment,
                "config_hash": self.settings.config_hash,
                "yaml_hash": self.config.config_hash,
            },
        )
        return held

    async def _recover_verified_protection(self, *, protection_only: bool = False) -> None:
        """AX-30: an unrelated mismatch cannot suppress provable held protection.

        Account, exact managed holdings and the complete same-symbol order set
        are rechecked. Unknown same-symbol reservations or uncaptured fills
        forbid sells. This is entered only after reconciliation fails, never
        after an attempted repair, so a failed repair is not retried blindly.
        """
        try:
            self.state.ledger.verify_chain()
            await self._verify_account()
            positions, opened = await self._positions(), await self._open_orders()
            with DatabaseSession(self.state.engine) as session:
                proved = bindings(session)
                entries = tuple(
                    (row, held_quantity(session, row.id))
                    for row in self._instructions()
                    if row.role == "ENTRY"
                )
            totals: dict[str, int] = {}
            for row, qty in entries:
                totals[row.symbol] = totals.get(row.symbol, 0) + qty
            known = {row.order_id for row in proved.values()}
            for entry, qty in entries:
                try:
                    await self._recover_verified_entry(
                        entry, qty, positions, opened, totals, known, protection_only
                    )
                except Exception as error:
                    self.state.halt_for_error(error)
                    await self._trade_notice(
                        f"{self.environment} · HALTED: verified protection recovery failed for {entry.symbol}; inspect broker stops urgently.",
                        True,
                        entry.order_id,
                    )
        except Exception as error:
            self.state.halt_for_error(error)
            await self.notify(
                f"{self.environment} · HALTED: recovery cannot prove held protection; inspect broker stops urgently.",
                True,
            )

    async def _recover_verified_entry(
        self,
        entry: ExecutionOrderRecord,
        qty: int,
        positions: dict[str, int],
        opened: tuple[BrokerOrder, ...],
        totals: dict[str, int],
        known: set[UUID],
        protection_only: bool,
    ) -> None:
        relevant = tuple(
            row for parent in opened for row in (parent, *parent.legs) if row.symbol == entry.symbol
        )
        if positions.get(entry.symbol, 0) != totals[entry.symbol] or any(
            row.order_id not in known for row in relevant
        ):
            return
        broker = await self._read_bound(entry)
        with DatabaseSession(self.state.engine) as session:
            captured = filled_quantity(session, entry.id)
        children = tuple(row for row in self._instructions() if row.parent_execution_id == entry.id)
        captured_children = True
        for child in children:
            observed = await self._read_bound(child)
            with DatabaseSession(self.state.engine) as session:
                amount = filled_quantity(session, child.id)
            if observed is None or observed.filled_qty != amount:
                captured_children = False
                break
        if broker is None or broker.filled_qty != captured or not captured_children:
            return
        if broker.is_open:
            canceled = await self._cancel_confirmed(entry, broker)
            if canceled.status in {"canceled", "expired", "rejected"}:
                self.state.ledger.append(
                    OrderEvent,
                    order_id=entry.order_id,
                    state="REJECTED" if canceled.status == "rejected" else "CANCELED",
                    reason="reconciliation halt canceled verified unfilled remainder",
                    broker_order_id=str(canceled.order_id),
                )
        if protection_only:
            if qty:
                await self._ensure_stop(entry, qty)
            else:
                await self._cancel_sells(entry)
        else:
            await self._protect_and_exit(entry, qty)

    async def _reconcile_or_protect(self) -> tuple[tuple[ExecutionOrderRecord, int], ...]:
        try:
            return await self._reconcile()
        except Exception as error:
            self.state.halt_for_error(error)
            await self._recover_verified_protection()
            raise

    async def _publish_fill_notices(self) -> None:
        with DatabaseSession(self.state.engine) as session:
            instructions = {row.id: row for row in self._instructions()}
            published = {
                row.detail["fill_id"]
                for row in session.scalars(
                    select(SecurityEvent).where(
                        SecurityEvent.kind == "EXECUTION_FILL_NOTICE_QUEUED"
                    )
                )
            }
            fills = tuple(
                row
                for row in session.scalars(
                    select(ExecutionFillRecord).order_by(ExecutionFillRecord.seq)
                )
                if row.execution_order_id in instructions and str(row.id) not in published
            )
            notices = []
            cycles = {row.cycle_id: row for row in exit_cycles(session)}
            approvals = {row.client_order_id: row for row in exit_approvals(session)}
            for fill in fills:
                instruction = instructions[fill.execution_order_id]
                if instruction.role == "ENTRY":
                    entry = instruction
                elif instruction.parent_execution_id is not None:
                    entry = instructions[instruction.parent_execution_id]
                else:
                    raise ReconciliationError("Fill notification lost its managed entry")
                buys = tuple(
                    row
                    for row in session.scalars(
                        select(ExecutionFillRecord).where(
                            ExecutionFillRecord.execution_order_id == entry.id
                        )
                    )
                )
                if not buys:
                    raise ReconciliationError("Fill notice has no verified acquisition basis")
                with localcontext() as precision:
                    precision.prec = 80
                    average_cost = sum((row.price * row.qty for row in buys), Decimal(0)) / sum(
                        row.qty for row in buys
                    )
                authorization = approvals.get(instruction.client_order_id)
                cycle = None if authorization is None else cycles.get(authorization.cycle_id)
                notices.append(
                    (
                        fill.id,
                        entry.order_id,
                        fill_fyi(
                            self.settings,
                            instruction,
                            entry,
                            fill,
                            held_quantity(session, entry.id),
                            unit_cost=average_cost,
                            exit_reason=None if cycle is None else cycle.reason,
                            protective_level=current_stop(session, entry),
                        ),
                    )
                )
        for identity, order_id, text in notices:
            await self._trade_notice(text, False, order_id)
            self.state.ledger.append(
                SecurityEvent,
                kind="EXECUTION_FILL_NOTICE_QUEUED",
                detail={"fill_id": str(identity)},
            )

    async def reconcile(self) -> None:
        async with account_lock(self.modes.account_id, self.environment):
            try:
                held = await self._reconcile_or_protect()
                protection_failed = False
                for entry, qty in held:
                    try:
                        await self._protect_and_exit(entry, qty)
                    except Exception as error:
                        self.state.halt_for_error(error)
                        protection_failed = True
                if protection_failed:
                    raise ReconciliationError(
                        "Held protection failed; other verified holdings were checked"
                    )
                await self._publish_fill_notices()
            except Exception as error:
                self.state.halt_for_error(error)
                await self.notify(
                    f"{self.environment} · HALTED: broker reconciliation or stop protection failed; manual trading belongs in a different account.",
                    True,
                )
                raise ReconciliationError("Broker reconciliation failed closed") from None

    async def cancel_unfilled_entries(self) -> None:
        """SEC-73: after durable HALT, cancel known remainders and preserve stops.

        This never requests exit analysis or flattens holdings. A cancellation
        racing an uncaptured fill refuses any replacement until reconciliation.
        """
        if self.state.current() != SystemState.HALTED:
            raise ExecutionDisabledError("Panic cancellation requires a durable HALT first")
        async with account_lock(self.modes.account_id, self.environment):
            try:
                held = await self._reconcile()
            except Exception as error:
                self.state.halt_for_error(error)
                await self._recover_verified_protection(protection_only=True)
                raise ReconciliationError("Panic reconciliation failed closed") from None
            for entry, qty in held:
                broker = await self._read_bound(entry)
                if broker is not None and broker.is_open:
                    canceled = await self._cancel_confirmed(entry, broker)
                    self.state.ledger.append(
                        OrderEvent,
                        order_id=entry.order_id,
                        state="REJECTED" if canceled.status == "rejected" else "CANCELED",
                        reason="local panic canceled verified unfilled remainder",
                        broker_order_id=str(canceled.order_id),
                    )
                if qty:
                    await self._ensure_stop(entry, qty)
                else:
                    await self._cancel_sells(entry)

    async def monitor(self) -> None:
        async with account_lock(self.modes.account_id, self.environment):
            try:
                held = await self._reconcile_or_protect()
                blocked = not self.modes.entries_enabled
                now = ensure_utc(self.state.clock.now())
                if self.configuration_check is not None:
                    try:
                        self.configuration_check()
                        blocked = blocked or not self.modes.entries_enabled
                    except Exception as error:
                        self.state.halt_for_error(error)
                        blocked = True
                if self.portfolio is not None:
                    try:
                        snapshot = PortfolioSnapshot.model_validate(await self.portfolio())
                        if snapshot.account_id != self.modes.account_id:
                            raise ReconciliationError("Monitor snapshot account differs")
                        marks = self.risk.marks
                        if marks is None:
                            raise ReconciliationError("Monitor financial marks are unavailable")
                        snapshot = marks.observe(snapshot)
                        recommended = financial_state(
                            snapshot.equity,
                            snapshot.high_water_mark,
                            snapshot.day_start_equity,
                            self.settings,
                        )
                        if recommended != SystemState.RUNNING:
                            self.state.escalate(
                                recommended, "Automatic monitor financial risk tier"
                            )
                        blocked = (
                            blocked
                            or recommended != SystemState.RUNNING
                            or marks.daily_loss_blocked(now)
                        )
                    except Exception as error:
                        self.state.halt_for_error(error)
                        blocked = True
                protection_failed = False
                for entry, qty in held:
                    try:
                        await self._monitor_entry(entry, qty, blocked, now)
                    except Exception as error:
                        self.state.halt_for_error(error)
                        protection_failed, blocked = True, True
                if protection_failed:
                    raise ReconciliationError(
                        "Held protection failed; other verified holdings were checked"
                    )
                await self._publish_fill_notices()
            except Exception as error:
                self.state.halt_for_error(error)
                await self.notify(
                    f"{self.environment} · HALTED: automatic monitor failed; inspect held stops urgently.",
                    True,
                )
                raise ReconciliationError("Automatic monitor failed closed") from None

    async def _monitor_entry(
        self, entry: ExecutionOrderRecord, qty: int, blocked: bool, now: datetime
    ) -> None:
        broker = await self._read_bound(entry)
        if (
            broker is not None
            and broker.is_open
            and (
                blocked
                or entry.valid_until is None
                or now >= entry.valid_until
                or (qty > 0 and broker.filled_qty < broker.qty)
            )
        ):
            canceled = await self._cancel_confirmed(entry, broker)
            if canceled.status in {"canceled", "expired", "rejected"}:
                self.state.ledger.append(
                    OrderEvent,
                    order_id=entry.order_id,
                    state="CANCELED" if canceled.status != "rejected" else "REJECTED",
                    reason="unfilled remainder canceled; held shares retained",
                    broker_order_id=str(canceled.order_id),
                )
                await self._trade_notice(
                    f"{self.environment} · Canceled unfilled {entry.symbol} entry; {self._quantity(qty)} filled shares retained.",
                    False,
                    entry.order_id,
                )
        await self._protect_and_exit(entry, qty)

    async def _protect_and_exit(self, entry: ExecutionOrderRecord, qty: int) -> None:
        if qty == 0:
            # A completed or canceled parent cannot leave an orphan SELL that
            # would open a short position. Confirm cancellation before proceeding.
            await self._cancel_sells(entry)
        with DatabaseSession(self.state.engine) as session:
            cycles = tuple(row for row in exit_cycles(session) if row.entry_id == entry.id)
        active = bool(cycles and cycles[-1].state == "ACTIVE")
        # Confirm or repair stops before optional fresh exit analysis. Missing
        # quotes or expired entry prerequisites must never suppress protection.
        if qty and not active:
            await self._resume_stop_moves(entry, qty)
            await self._ensure_stop(entry, qty)
        exiting = await self._exit_step(entry, qty)
        if qty and active and not exiting:
            await self._ensure_stop(entry, qty)
        if qty and not exiting:
            await self._raise_step(entry, qty)

    def _stop_moved(
        self,
        plan: StopRaiseApproval,
        status: Literal["APPLIED", "REPAIRED", "FAILED", "CANCEL_UNCONFIRMED"],
        level: Decimal | None,
        *,
        started_ns: int | None = None,
    ) -> None:
        now = ensure_utc(self.state.clock.now())
        elapsed = now - plan.checked_at
        clock_ms = (elapsed.days * 86400 + elapsed.seconds) * 1000 + elapsed.microseconds // 1000
        physical_ms = 0 if started_ns is None else (monotonic_ns() - started_ns) // 1000000
        movement = StopMoved(
            approval=plan,
            status=status,
            confirmed_stop=level,
            window_ms=max(clock_ms, physical_ms),
            completed_at=now,
        )
        self.state.ledger.append(
            SecurityEvent, kind="STOP_MOVED", detail=movement.model_dump(mode="json")
        )
        if movement.window_ms > 30000:
            self.state.ledger.append(
                SecurityEvent,
                kind="STOP_WINDOW_EXCEEDED",
                detail={
                    "raise_id": str(plan.raise_id),
                    "account_id": plan.account_id,
                    "environment": plan.environment,
                    "window_ms": movement.window_ms,
                },
            )

    async def _raise_repair(self, entry: ExecutionOrderRecord, plan: StopRaiseApproval) -> Decimal:
        """Repair only after every conflicting sell has a confirmed terminal result."""
        if self.worker.has_pending_attempts:
            raise ReconciliationError(
                "EX-05: unresolved physical attempt forbids a conflicting repair"
            )
        with DatabaseSession(self.state.engine) as session:
            children = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.parent_execution_id == entry.id
                    )
                )
            )
        confirmed_stops = []
        for child in children:
            broker = await self._read_bound(child)
            if broker is None and not self._confirmed_absence(child):
                raise ReconciliationError("EX-05: unknown sell outcome forbids overlapping repair")
            if (
                broker is not None
                and broker.is_open
                and broker.order_type == "stop"
                and broker.status not in {"held", "suspended", "pending_cancel"}
            ):
                confirmed_stops.append(broker)
        if (
            len(confirmed_stops) == 1
            and confirmed_stops[0].qty - confirmed_stops[0].filled_qty == plan.qty
            and confirmed_stops[0].stop_price in {plan.old_stop, plan.new_stop}
        ):
            return confirmed_stops[0].stop_price
        await self._cancel_sells(entry, deadline_seconds=10)
        level = plan.old_stop
        try:
            inputs = await self._fresh_exit_inputs(entry)
            if plan.new_stop < inputs.market.last_price:
                level = plan.new_stop
        except ExecutionDisabledError:
            # Protect at the proved old level when a fresh quote is unavailable.
            pass
        identity = "vws-m-" + plan.raise_id.hex + "-r"
        with DatabaseSession(self.state.engine) as session:
            previous = session.scalar(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.client_order_id == identity)
            )
        if previous is not None:
            confirmed = await self._read_bound(previous)
            if confirmed is None or not confirmed.is_open or confirmed.stop_price != level:
                raise ReconciliationError("EX-05: durable repair cannot be repeated")
        else:
            confirmed = await self._repair_stop(
                entry, plan.qty, approval=plan, repair=True, repair_level=level
            )
        if confirmed.status in {"held", "suspended", "pending_cancel"}:
            raise ReconciliationError("EX-05: repair is not confirmed active")
        return level

    async def _resume_stop_moves(self, entry: ExecutionOrderRecord, qty: int) -> None:
        with DatabaseSession(self.state.engine) as session:
            approvals = stop_approvals(session, entry)
            completed = {row.approval.raise_id for row in moved_stops(session, entry)}
        for plan in approvals:
            if plan.raise_id in completed:
                continue
            if plan.qty != qty:
                raise ReconciliationError("EX-05: unfinished stop raise has changed held shares")
            with DatabaseSession(self.state.engine) as session:
                instruction = session.scalar(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.client_order_id == "vws-m-" + plan.raise_id.hex
                    )
                )
            if instruction is not None:
                confirmed = await self._read_bound(instruction)
                if (
                    confirmed is not None
                    and confirmed.is_open
                    and confirmed.status not in {"held", "suspended", "pending_cancel"}
                    and (
                        confirmed.stop_price == plan.new_stop
                        or any(
                            child.order_type == "stop"
                            and child.is_open
                            and child.status not in {"held", "suspended", "pending_cancel"}
                            and child.stop_price == plan.new_stop
                            and child.qty - child.filled_qty == plan.qty
                            for child in confirmed.legs
                        )
                    )
                ):
                    self._stop_moved(plan, "APPLIED", plan.new_stop)
                    continue
            try:
                level = await self._raise_repair(entry, plan)
                self._stop_moved(plan, "REPAIRED", level)
            except Exception:
                self._stop_moved(plan, "FAILED", None)
                raise
            self.state.escalate(
                SystemState.HALTED, "EX-05 interrupted stop raise repaired; audited reset required"
            )

    def _split_profit_taken(self, entry: ExecutionOrderRecord) -> bool:
        if not entry.client_order_id.endswith("-b"):
            return False
        with DatabaseSession(self.state.engine) as session:
            sibling = session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.order_id == entry.order_id,
                    ExecutionOrderRecord.client_order_id == entry.client_order_id[:-1] + "a",
                    ExecutionOrderRecord.role == "ENTRY",
                )
            )
            if sibling is None or filled_quantity(session, sibling.id) != sibling.qty:
                return False
            targets = tuple(
                session.scalars(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.parent_execution_id == sibling.id,
                        ExecutionOrderRecord.role == "TARGET",
                    )
                )
            )
            return sum(filled_quantity(session, row.id) for row in targets) == sibling.qty

    async def _raise_step(self, entry: ExecutionOrderRecord, qty: int) -> None:
        held = self._held_entry(entry)
        if held.variant != "SPLIT_1R_TRAIL" or not self._split_profit_taken(entry):
            return
        now = ensure_utc(self.state.clock.now())
        today = now.astimezone(ZoneInfo("America/New_York")).date()
        if not self.calendar.is_open(now) or not (
            self.calendar.session_open(today) + timedelta(minutes=30)
            <= now
            < self.calendar.session_close(today) - timedelta(minutes=30)
        ):
            return
        with DatabaseSession(self.state.engine) as session:
            prior = stop_approvals(session, entry)
            level = current_stop(session, entry)
        preceding = self.calendar.previous_sessions(today, 1)[0]
        if any(row.session == preceding for row in prior):
            return
        if self.modes.effective == "MANUAL":
            with DatabaseSession(self.state.engine) as session:
                if (
                    session.scalar(
                        select(SecurityEvent).where(
                            SecurityEvent.kind == "STOP_RAISE_SUGGESTED",
                            SecurityEvent.detail["entry_id"].as_string() == str(entry.id),
                            SecurityEvent.detail["session"].as_string() == preceding.isoformat(),
                        )
                    )
                    is not None
                ):
                    return
        inputs = await self._fresh_exit_inputs(entry)
        observed = await self._held_observation(entry, inputs)
        plan = stop_raise_plan(
            held,
            observed,
            self.calendar,
            now,
            raise_id=uuid4(),
            qty=qty,
            old_stop=level,
            last_trade=inputs.market.last_price,
            quote_at=inputs.market.last_price_ts,
            stale_quote_seconds=self.settings.stale_quote_seconds,
            trail_atr_mult=self.config.ex.trail_atr_mult,
            config_hash=self.settings.config_hash,
            yaml_hash=self.config.config_hash,
        )
        if plan is None:
            return
        if self.modes.effective == "MANUAL":
            self.state.ledger.append(
                SecurityEvent, kind="STOP_RAISE_SUGGESTED", detail=plan.model_dump(mode="json")
            )
            await self._trade_notice(
                f"{self.environment} · {entry.symbol}: Raise stop to ${plan.new_stop:.2f}. Manual suggestion for {self._quantity(qty)} held shares.",
                False,
                entry.order_id,
            )
            return
        if self.environment == "LIVE":
            self._assert_live_raises()
            if self.entry_variant_allowed is None or self.entry_variant_allowed() is not True:
                raise ExecutionDisabledError(
                    "EX-06: live stop raises require current WORKING evidence"
                )
        await self._verify_account()
        broker_qty = (await self._positions()).get(entry.symbol, 0)
        with DatabaseSession(self.state.engine) as session:
            other = sum(
                held_quantity(session, row.id)
                for row in session.scalars(
                    select(ExecutionOrderRecord).where(
                        ExecutionOrderRecord.role == "ENTRY",
                        ExecutionOrderRecord.symbol == entry.symbol,
                        ExecutionOrderRecord.id != entry.id,
                    )
                )
            )
        if broker_qty - other != qty:
            raise ReconciliationError(
                "EX-05: allocated broker quantity differs from managed held shares"
            )
        self.state.ledger.append(
            SecurityEvent, kind="STOP_RAISE_APPROVAL", detail=plan.model_dump(mode="json")
        )
        started = monotonic_ns()
        try:
            async with asyncio.timeout(10):
                await self._cancel_sells(entry, deadline_seconds=10)
        except Exception as error:
            self._stop_moved(plan, "CANCEL_UNCONFIRMED", None, started_ns=started)
            self.state.halt_for_error(error)
            await self._trade_notice(
                f"{self.environment} · HALTED: {entry.symbol} stop cancellation unconfirmed; inspect broker protection urgently.",
                True,
                entry.order_id,
            )
            raise ReconciliationError(
                "EX-05: cancellation unconfirmed; no conflicting sell"
            ) from None
        try:
            await self._repair_stop(entry, qty, approval=plan)
            self._stop_moved(plan, "APPLIED", plan.new_stop, started_ns=started)
            await self._trade_notice(
                f"{self.environment} · Raised {entry.symbol} stop to ${plan.new_stop:.2f} (at broker).",
                False,
                entry.order_id,
            )
        except Exception as error:
            try:
                repaired = await self._raise_repair(entry, plan)
                self._stop_moved(plan, "REPAIRED", repaired, started_ns=started)
            except Exception:
                self._stop_moved(plan, "FAILED", None, started_ns=started)
                self.state.halt_for_error(error)
                await self._trade_notice(
                    f"{self.environment} · HALTED: {entry.symbol} raised stop and repair unconfirmed; inspect broker protection urgently.",
                    True,
                    entry.order_id,
                )
                raise ReconciliationError(
                    "EX-05: raise and repair could not be confirmed"
                ) from None
            self.state.escalate(
                SystemState.HALTED, "EX-05 failed stop raise repaired; audited reset required"
            )
            await self._trade_notice(
                f"{self.environment} · HALTED: {entry.symbol} stop raise failed; protection restored at ${repaired:.2f} (at broker).",
                True,
                entry.order_id,
            )

    async def close(self) -> None:
        await self.worker.aclose()
        session = getattr(self.client, "_session", None)
        if isinstance(session, Session):
            session.close()


class ProtectionRecovery(AlpacaExecutor):
    """AX-30: recover existing stops after a persisted downgrade in AUTO config.

    Configured MANUAL never imports this module. Normal AlpacaExecutor still
    refuses effective MANUAL. This narrow recovery service cannot enter even
    after a host resume; restart to construct the normal guarded executor.
    Expired entry prerequisites never trap an existing valid protective exit.
    """

    async def enter(self, proposal_id: UUID, *, click: CallbackClick | None = None) -> Submission:
        raise ExecutionDisabledError(
            "Protection recovery cannot submit entries; host resume and restart required"
        )


class ManagedTradingStream(TradingStream):
    """AX-28/SEC-30: pinned stream adapter with finite retries and redacted faults.

    VERIFY: alpaca-py 0.44.0 TradingStream accepts raw_data=True and verified
    websocket_params. Its raw callback includes stream/data, not just data.
    Its default run loop retries indefinitely and logs raw exceptions, so this
    adapter owns that loop while retaining the pinned connect/auth/subscribe.
    Canonical activities, rather than a second stream fill ID, feed the ledger.
    """

    def __init__(
        self,
        executor: AlpacaExecutor,
        policy: EgressPolicy,
        capture_fills: Callable[[], Awaitable[object]],
    ) -> None:
        self.executor, self.capture_fills = executor, capture_fills
        settings = executor.settings
        assert_auto_binding(settings, executor.store)
        host = "paper-api.alpaca.markets" if settings.paper_trading else "api.alpaca.markets"
        if host not in policy.hosts or policy.ledger.engine is not executor.state.engine:
            raise ConfigurationError("Trade stream account or egress policy differs")
        cast(Callable[..., None], super().__init__)(
            api_key=settings.broker_api_key.get_secret_value(),
            secret_key=settings.broker_secret_key.get_secret_value(),
            paper=settings.paper_trading,
            raw_data=True,
            websocket_params={
                "ssl": ssl.create_default_context(),
                "open_timeout": 10,
                "close_timeout": 5,
                "ping_interval": 10,
                "ping_timeout": 20,
                "max_queue": 64,
                "max_size": 1_048_576,
            },
        )
        resolved = getattr(self._endpoint, "value", self._endpoint)
        if resolved != f"wss://{host}/stream":
            raise ConfigurationError("Trade stream endpoint differs from its bound account")
        # VERIFY: the pinned SDK initializes this slot to None, then assigns a
        # coroutine in subscribe_trade_updates; its inferred stub is too narrow.
        self._trade_updates_handler = self._update  # type: ignore[assignment]
        self._runner: asyncio.Task[None] | None = None
        self._update_lock = asyncio.Lock()

    async def _update(self, message: object) -> None:
        async with self._update_lock:
            try:
                if not isinstance(message, dict) or message.get("stream") != "trade_updates":
                    raise DataIntegrityError("Trade update envelope is unverifiable")
                data = message.get("data")
                if not isinstance(data, dict) or data.get("event") not in {
                    "new",
                    "accepted",
                    "pending_new",
                    "fill",
                    "partial_fill",
                    "canceled",
                    "expired",
                    "rejected",
                    "pending_cancel",
                    "stopped",
                    "suspended",
                    "done_for_day",
                    "order_cancel_rejected",
                    "order_replace_rejected",
                    "replaced",
                }:
                    raise DataIntegrityError("Trade update event is unknown")
                broker = parse_order(data.get("order"))
                instructions = self.executor._instructions()
                with DatabaseSession(self.executor.state.engine) as session:
                    proved = bindings(session)
                if not any(
                    row.client_order_id == broker.client_order_id
                    or (row.id in proved and proved[row.id].order_id == broker.order_id)
                    for row in instructions
                ):
                    # A generated child can arrive before the submit response.
                    await self.executor.prepare_fills((broker.symbol,))
                    with DatabaseSession(self.executor.state.engine) as session:
                        proved = bindings(session)
                    if not any(row.order_id == broker.order_id for row in proved.values()):
                        raise ReconciliationError(
                            "Unbound trade update; use a separate manual account"
                        )
                async with asyncio.timeout(600):
                    await self.capture_fills()
                    await self.executor.reconcile()
            except Exception as error:
                self.executor.state.halt_for_error(error)
                await self.executor.notify(
                    f"{self.executor.environment} · HALTED: trade update could not be reconciled.",
                    True,
                )
                raise ReconciliationError("Trade update failed closed") from None

    async def _run_forever(self) -> None:
        # VERIFY: TradingStream._run_forever assigns the same SDK None slot.
        self._loop = asyncio.get_running_loop()  # type: ignore[assignment]
        self._stop_stream_event = asyncio.Event()
        self._should_run = True
        failures = 0
        try:
            while self._should_run and failures < 3:
                try:
                    async with asyncio.timeout(30):
                        await cast(Callable[[], Awaitable[None]], self._start_ws)()
                    self._running = True
                    await cast(Callable[[], Awaitable[None]], self._consume)()
                    if self._should_run:
                        raise ProviderError("Trade stream ended unexpectedly")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failures += 1
                    await self.close()
                    self.executor.state.ledger.append(
                        SecurityEvent,
                        kind="TRADE_STREAM_FAILED",
                        detail={
                            "account_id": self.executor.modes.account_id,
                            "environment": self.executor.environment,
                            "error_type": type(error).__name__,
                            "attempt": failures,
                        },
                    )
                    if failures < 3 and self._should_run:
                        await asyncio.sleep(failures)
            if self._should_run:
                self.executor.state.escalate(
                    SystemState.HALTED,
                    "Trade stream exhausted three connection attempts; REST stop monitoring continues",
                )
                await self.executor.notify(
                    f"{self.executor.environment} · HALTED: trade stream unavailable; REST stop monitoring continues.",
                    True,
                )
        finally:
            await self.close()

    async def start(self) -> None:
        if self._runner is not None:
            raise ConfigurationError("A trade stream cannot be started twice")
        self._runner = asyncio.create_task(self._run_forever())

    async def aclose(self) -> None:
        self._should_run = False
        await self.stop_ws()
        await self.close()
        if self._runner is not None:
            self._runner.cancel()
            async with asyncio.timeout(35):
                await asyncio.gather(self._runner, return_exceptions=True)
