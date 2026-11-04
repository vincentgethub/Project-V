"""AX-16/23/27/31: exact, frozen broker execution evidence."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.core.clock import ensure_utc
from backend.core.money import decimal_money
from backend.domain.models import (
    FrozenModel,
    Money,
    NonnegativeQty,
    PositiveQty,
    Price,
    RuleResult,
    Severity,
    Symbol,
    UTCDateTime,
)

ExecutionMode = Literal["MANUAL", "AUTO_PAPER", "AUTO_LIVE"]
Environment = Literal["PAPER", "LIVE"]
OrderStatus = Literal[
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
    "filled",
    "done_for_day",
    "canceled",
    "expired",
    "rejected",
    "pending_cancel",
    "held",
    "stopped",
    "suspended",
    "calculated",
    "accepted_for_bidding",
]
OPEN_STATUSES = frozenset(
    {
        "new",
        "accepted",
        "pending_new",
        "partially_filled",
        "done_for_day",
        "pending_cancel",
        "held",
        "stopped",
        "suspended",
        "accepted_for_bidding",
    }
)
TERMINAL_STATUSES = frozenset({"filled", "canceled", "expired", "rejected"})


class IntentOrderView(FrozenModel):
    """Sanitized GET evidence; no broker free text or rejection message."""

    order_id: UUID
    client_order_id: str = Field(strict=True, min_length=1, max_length=128)
    symbol: Symbol
    side: Literal["buy", "sell"]
    qty: PositiveQty
    filled_qty: NonnegativeQty
    status: OrderStatus


class IntentBrokerSnapshot(FrozenModel):
    observed_at: UTCDateTime
    order: IntentOrderView | None
    not_found: bool = Field(default=False, strict=True)
    position_qty: NonnegativeQty
    fill_qty: NonnegativeQty
    activity_ids: tuple[str, ...]
    complete: bool = Field(strict=True)
    open_orders: tuple[IntentOrderView, ...] = ()

    @property
    def taken_at(self) -> datetime:
        return self.observed_at


class IntentSnapshot(FrozenModel):
    intent_id: UUID
    order_id: UUID
    client_order_id: str = Field(strict=True, min_length=1, max_length=128)
    account: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    symbol: Symbol
    side: Literal["buy", "sell"]
    qty: PositiveQty
    submitted_at: UTCDateTime
    broker_order_id: UUID | None
    position_qty: NonnegativeQty
    filled_qty: NonnegativeQty
    audit_id: UUID
    audit_seq: int = Field(strict=True, gt=0)
    state: Literal["RUNNING", "REDUCE_ONLY", "HALTED"]
    state_id: UUID | None
    state_version: int = Field(strict=True, ge=0)
    mode: ExecutionMode
    override_mode: ExecutionMode | None
    paused: bool = Field(strict=True)
    pause_owner: str | None
    contradiction: bool = Field(strict=True)


class IntentDryRun(FrozenModel):
    intent_id: UUID
    account: str
    environment: Literal["PAPER"] = "PAPER"
    outcome: Literal["TERMINAL", "QUALIFIED_NOT_FOUND"]
    status: OrderStatus | None
    pause_owner: str | None
    apply_allowed: Literal[False] = False
    quiescence_verified: bool = Field(default=False, strict=True)

    def lines(self) -> tuple[str, ...]:
        owner = "none" if self.pause_owner is None else "other owner (redacted)"
        if self.pause_owner is not None and self.pause_owner.startswith("attempt-fence:"):
            try:
                owner = "attempt-fence:" + UUID(self.pause_owner.removeprefix("attempt-fence:")).hex
            except ValueError:
                pass
        return (
            f"Dry run: intent {self.intent_id}; account {self.account}; PAPER.",
            f"Path A evidence: {self.outcome}; status {self.status or 'NOT_FOUND'}; apply permitted: NO.",
            f"Pause owner: {owner}.",
            (
                "Quiescence: VERIFIED for this sampled window (runtime lock, eight broker slots, unchanged epoch); paper residual risk applies; no cached apply authorization."
                if self.quiescence_verified
                else "Quiescence: UNVERIFIED (standalone panic not coordinated). A later apply would REFUSE until panic coordination is built."
            ),
            "Ledger chain NOT verified by dry-run; a later apply must verify it.",
            "A separately approved apply could record resolution; it must preserve HALT and effective PAUSE. No order, sell, restoration, resubmit or reset is authorized.",
        )


def payload_instant(value: object) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Execution payload requires an exact UTC timestamp")
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


class BrokerOrder(FrozenModel):
    order_id: UUID
    client_order_id: str = Field(strict=True, min_length=1, max_length=128)
    symbol: Symbol
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "stop"]
    order_class: Literal["simple", "bracket", "oco", "oto"]
    time_in_force: Literal["day", "gtc"]
    qty: PositiveQty
    filled_qty: NonnegativeQty
    status: OrderStatus
    limit_price: Price | None = None
    stop_price: Price | None = None
    submitted_at: UTCDateTime
    parent_id: UUID | None = None
    rejection_reason: str | None = Field(
        default=None, strict=True, max_length=512, exclude_if=lambda v: v is None
    )
    rejected_at: UTCDateTime | None = Field(default=None, exclude_if=lambda v: v is None)
    legs: tuple["BrokerOrder", ...] = Field(default=(), max_length=2)

    @field_validator("rejected_at", mode="before")
    @classmethod
    def decode_rejection_time(cls, value: object) -> datetime | None:
        return None if value is None else payload_instant(value)

    @field_validator("submitted_at", mode="before")
    @classmethod
    def decode_time(cls, value: object) -> datetime:
        return payload_instant(value)

    @field_validator("limit_price", "stop_price", mode="before")
    @classmethod
    def decode_price(cls, value: object) -> Decimal | None:
        if value is None or isinstance(value, Decimal):
            return value
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError("Execution payload prices require Decimal or exact decimal text")
        return decimal_money(value)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.rejected_at is not None and self.rejected_at < self.submitted_at:
            raise ValueError("Broker rejection precedes order submission")
        if self.filled_qty > self.qty:
            raise ValueError("Broker fills exceed requested shares")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("Broker limit order has no exact limit")
        if self.order_type == "stop" and (self.stop_price is None or self.side != "sell"):
            raise ValueError("Only protective sell stops are permitted")
        if self.status == "filled" and self.filled_qty != self.qty:
            raise ValueError("Filled broker order has incomplete shares")
        if self.parent_id == self.order_id or len({leg.order_id for leg in self.legs}) != len(
            self.legs
        ):
            raise ValueError("Broker parent/child identities are invalid")
        if any(
            leg.parent_id != self.order_id
            or leg.legs
            or leg.symbol != self.symbol
            or leg.side != "sell"
            or leg.qty > self.qty
            or leg.time_in_force != self.time_in_force
            for leg in self.legs
        ):
            raise ValueError("Broker legs differ from their proved parent")
        return self

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


class ExecutionFill(FrozenModel):
    execution_id: UUID
    broker_order_id: UUID
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    symbol: Symbol
    side: Literal["buy", "sell"]
    qty: PositiveQty
    price: Price
    filled_at: UTCDateTime


class Submission(FrozenModel):
    proposal_id: UUID
    broker_order: BrokerOrder
    recovered_after_ambiguity: bool = Field(strict=True)
    broker_orders: tuple[BrokerOrder, ...] = Field(
        default=(), max_length=2, exclude_if=lambda v: not v
    )


class BindingEvidence(FrozenModel):
    execution_order_id: UUID
    broker_order: BrokerOrder
    observed_at: UTCDateTime

    @field_validator("observed_at", mode="before")
    @classmethod
    def decode_time(cls, value: object) -> datetime:
        return payload_instant(value)


class SubmitOutcome(FrozenModel):
    execution_order_id: UUID
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    outcome: Literal["ACCEPTED", "REJECTED", "ERROR", "NOT_SENT"]
    error_type: str = Field(strict=True, min_length=1, max_length=128)
    reason: Literal["fenced before transport"] | None = None


class TransportAttemptEvidence(FrozenModel):
    attempt_id: UUID
    client_order_id: str | None = Field(max_length=128)
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    state: Literal["PENDING", "ENTERED", "ABANDONED"]
    reason: Literal["timeout", "cancelled"]
    timestamp: UTCDateTime
    never_entered_transport: bool = Field(strict=True)
    broker_order_id: UUID | None = None


class AutoPrerequisites(FrozenModel):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    doctor_fully_green: bool = Field(strict=True)
    watchdog_enabled: bool = Field(strict=True)
    backup_chain_verified: bool = Field(strict=True)
    backup_verified_at: UTCDateTime
    telegram_verified_at: UTCDateTime
    clock_verified_at: UTCDateTime

    @field_validator(
        "backup_verified_at", "telegram_verified_at", "clock_verified_at", mode="before"
    )
    @classmethod
    def decode_time(cls, value: object) -> datetime:
        return payload_instant(value)


class EntryApprovalEvidence(FrozenModel):
    proposal_id: UUID
    alert_id: UUID
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    actor: Literal["auto", "telegram"]
    user_id: int | None = Field(default=None, strict=True, gt=0, lt=2**63)
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    yaml_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    compliance_input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    qty: PositiveQty
    exit_variant: Literal["BASELINE", "SPLIT_1R", "SPLIT_1R_TRAIL", "TRAIL_EMA20"] = Field(
        default="BASELINE", exclude_if=lambda v: v == "BASELINE"
    )
    hold_sessions: Literal[10, 20, 30] = Field(default=20, exclude_if=lambda v: v == 20)
    checked_at: UTCDateTime
    # Historical approvals remain readable for held exits/protection. New
    # executor admissions require all fourteen rules independently.
    risk_results: tuple[RuleResult, ...] = Field(min_length=13, max_length=14)
    compliance_results: tuple[RuleResult, ...] = Field(min_length=7, max_length=7)

    @field_validator("checked_at", mode="before")
    @classmethod
    def decode_time(cls, value: object) -> datetime:
        return payload_instant(value)

    @model_validator(mode="after")
    def complete_defenses(self) -> Self:
        if (
            (self.actor == "auto") != (self.user_id is None)
            or tuple(row.rule_id for row in self.risk_results)
            not in (
                tuple(f"CRO-{n:02d}" for n in range(1, 14)),
                tuple(f"CRO-{n:02d}" for n in range(1, 15)),
            )
            or tuple(row.rule_id for row in self.compliance_results)
            != tuple(f"CMP-{n:02d}" for n in range(1, 8))
            or any(
                not row.passed and row.severity == Severity.BLOCK
                for row in (*self.risk_results, *self.compliance_results)
            )
            or any(
                max(len(row.observed), len(row.limit), len(row.message)) > 4096
                for row in (*self.risk_results, *self.compliance_results)
            )
        ):
            raise ValueError(
                "Auto approval requires complete finite passing defenses and real attribution"
            )
        return self


class ModeOverride(FrozenModel):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    mode: ExecutionMode
    paused: bool = Field(strict=True)
    action: Literal["MANUAL", "PAUSE", "HALT", "DISABLE_LIVE", "RESUME"]
    actor: str = Field(strict=True, min_length=1, max_length=128)
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def downgrade_shape(self) -> Self:
        if any(
            value != value.strip() or not value.isprintable()
            for value in (self.account_id, self.actor)
        ):
            raise ValueError("Mode evidence requires printable account and actor identities")
        if (self.mode == "AUTO_PAPER" and self.environment != "PAPER") or (
            self.mode == "AUTO_LIVE" and self.environment != "LIVE"
        ):
            raise ValueError("Mode evidence environment differs")
        if self.action != "RESUME" and not self.paused:
            raise ValueError("Downgrade must pause new entries")
        if self.action in {"MANUAL", "HALT", "DISABLE_LIVE"} and self.mode != "MANUAL":
            raise ValueError("Explicit manual downgrade cannot preserve auto mode")
        if self.action == "RESUME" and (self.paused or self.mode == "MANUAL"):
            raise ValueError("Host resume requires an auto mode without a pause")
        return self


class ExitCycleEvidence(FrozenModel):
    cycle_id: UUID
    entry_id: UUID
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: Literal["TIME", "EARNINGS", "SUSPECT", "EMA20", "DELIST", "DILUTION"]
    state: Literal["ACTIVE", "DONE", "FAILED"]
    session_date: date
    rt_event_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def hard_event_bound(self) -> Self:
        if (self.reason in {"DELIST", "DILUTION"}) != (self.rt_event_key is not None):
            raise ValueError("AC-02: a hard-event exit needs its durable event identity")
        return self


class ExitApprovalEvidence(FrozenModel):
    cycle_id: UUID
    entry_id: UUID
    client_order_id: str = Field(strict=True, min_length=1, max_length=128, pattern=r"^vws-x-")
    attempt: int = Field(strict=True, ge=1, le=4)
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Environment
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    qty: PositiveQty
    market_price: Price
    limit_price: Price
    offset: Money = Field(ge=Decimal(0), le=Decimal("0.01"))
    quote_at: UTCDateTime
    checked_at: UTCDateTime

    @field_validator("quote_at", "checked_at", mode="before")
    @classmethod
    def decode_time(cls, value: object) -> datetime:
        return payload_instant(value)

    @field_validator("market_price", "limit_price", "offset", mode="before")
    @classmethod
    def decode_money(cls, value: object) -> Decimal:
        if not isinstance(value, (Decimal, str)) or isinstance(value, str) and len(value) > 64:
            raise ValueError("Exit evidence requires bounded exact decimal money")
        return decimal_money(value)

    @model_validator(mode="after")
    def exact_limit(self) -> Self:
        from backend.execution.policy import exit_limit

        if (
            self.limit_price != exit_limit(self.market_price, self.offset)
            or self.quote_at > self.checked_at
        ):
            raise ValueError("Exit limit differs from its fresh fixed-offset quote")
        return self
