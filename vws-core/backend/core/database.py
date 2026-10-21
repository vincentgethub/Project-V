"""R-02/R-04/R-05/R-08: typed, append-only SQLAlchemy ledger storage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    event,
    inspect,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import TypeDecorator

from backend.core.clock import ensure_utc
from backend.core.errors import DatabaseError, LedgerIntegrityError, SafetyError
from backend.core.money import money_to_scaled, scaled_to_money, validate_cent_price

SCHEMA_VERSION = 8


class MoneyType(TypeDecorator[Decimal]):
    """R-04: store finite Decimal money as signed 64-bit millionths."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise DatabaseError("MoneyType requires Decimal values")
        return money_to_scaled(value)

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else scaled_to_money(value)


class PriceType(MoneyType):
    """R-04/R-13: cent prices at ORM boundaries, millionth-unit integer storage."""

    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> int | None:
        return None if value is None else money_to_scaled(validate_cent_price(value))

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else validate_cent_price(scaled_to_money(value))


class UTCDateTime(TypeDecorator[datetime]):
    """R-05: validate UTC input; restore timezone metadata lost by SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else ensure_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            if dialect.name != "sqlite":
                raise DatabaseError("Database returned a timezone-naive timestamp")
            return value.replace(tzinfo=UTC)
        return ensure_utc(value)


class Base(DeclarativeBase):
    """SQLAlchemy registry for ledger and explicitly mutable control rows."""


class LedgerRecord(Base):
    """R-02/R-05: immutable identity, global sequence and per-table chain."""

    __abstract__ = True

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DataSnapshot(LedgerRecord):
    """DAT-03: reproducible vendor data provenance without look-ahead."""

    __tablename__ = "data_snapshots"
    __table_args__ = (
        CheckConstraint("bar_count >= 0", name="ck_snapshot_bar_count"),
        CheckConstraint("range_end >= range_start", name="ck_snapshot_range"),
        CheckConstraint("feed IN ('IEX', 'SIP', 'FAKE')", name="ck_snapshot_feed"),
        CheckConstraint(
            "adjustment IN ('RAW', 'SPLIT', 'DIVIDEND', 'ALL')",
            name="ck_snapshot_adjustment",
        ),
    )

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    range_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    range_end: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    feed: Mapped[str] = mapped_column(String(16), nullable=False)
    adjustment: Mapped[str] = mapped_column(String(16), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    bar_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bars: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class NewsHeadlineRecord(LedgerRecord):
    """DAT-09/SEC-60: stable, bounded public citations with durable deduplication."""

    __tablename__ = "news_headlines"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('ALPACA', 'RSS', 'NEWSAPI', 'FAKE')", name="ck_news_provider"
        ),
        CheckConstraint("published_at <= created_at", name="ck_news_published_at"),
        CheckConstraint("length(headline) BETWEEN 1 AND 280", name="ck_news_headline"),
        UniqueConstraint("provider", "provider_id", name="uq_news_provider_id"),
    )

    stable_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(280), nullable=True)
    headline: Mapped[str] = mapped_column(String(280), nullable=False)
    headline_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Signal(LedgerRecord):
    """R-01/R-08: every proposed order has an auditable signal origin."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint("direction IN ('BUY', 'SELL', 'HOLD')", name="ck_signal_direction"),
        CheckConstraint("signal_type IN ('SIGNAL', 'SYSTEM', 'MANUAL')", name="ck_signal_type"),
        CheckConstraint("confidence >= 0 AND confidence <= 1000000", name="ck_signal_confidence"),
    )

    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    structured_thesis: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    invalidation: Mapped[str] = mapped_column(Text, nullable=False)
    data_snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("data_snapshots.id"), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Order(LedgerRecord):
    """R-01/R-08: local LIMIT proposal record; never submits to a broker."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_order_qty"),
        CheckConstraint("limit_price > 0", name="ck_order_limit"),
        CheckConstraint("limit_price % 10000 = 0", name="ck_order_limit_cents"),
        CheckConstraint(
            "stop_price IS NULL OR (stop_price > 0 AND stop_price % 10000 = 0)",
            name="ck_order_stop_cents",
        ),
        CheckConstraint(
            "target_price IS NULL OR (target_price > 0 AND target_price % 10000 = 0)",
            name="ck_order_target_cents",
        ),
        CheckConstraint(
            "side != 'BUY' OR target_price IS NULL OR target_price > limit_price",
            name="ck_order_long_target",
        ),
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_order_side"),
        CheckConstraint("intent IN ('ENTRY', 'ADD', 'REDUCE', 'EXIT')", name="ck_order_intent"),
        CheckConstraint("source IN ('SIGNAL', 'SYSTEM', 'MANUAL')", name="ck_order_source"),
        CheckConstraint("order_type = 'LIMIT'", name="ck_order_type"),
        CheckConstraint(
            "(side = 'BUY' AND intent IN ('ENTRY', 'ADD')) OR "
            "(side = 'SELL' AND intent IN ('REDUCE', 'EXIT'))",
            name="ck_order_side_intent",
        ),
        CheckConstraint(
            "intent NOT IN ('ENTRY', 'ADD') OR "
            "(stop_price IS NOT NULL AND stop_price > 0 AND stop_price < limit_price)",
            name="ck_order_entry_stop",
        ),
    )

    proposal_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), unique=True, nullable=False)
    signal_id: Mapped[UUID] = mapped_column(ForeignKey("signals.id"), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    intent: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal] = mapped_column(PriceType(), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(8), nullable=False)


class OrderEvent(LedgerRecord):
    """R-02/R-08: append lifecycle transitions instead of changing orders."""

    __tablename__ = "order_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PROPOSED', 'APPROVED', 'SUBMITTED', 'PARTIALLY_FILLED', "
            "'FILLED', 'CANCELED', 'REJECTED', 'CANCEL_REQUESTED')",
            name="ck_order_event_state",
        ),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Fill(LedgerRecord):
    """R-04/R-08: observed whole-share fills, never execution instructions."""

    __tablename__ = "fills"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_fill_qty"),
        CheckConstraint("price > 0", name="ck_fill_price"),
        CheckConstraint("price % 10000 = 0", name="ck_fill_price_cents"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    broker_fill_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(PriceType(), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ExecutionOrderRecord(LedgerRecord):
    """AX-16/26: durable order intent, including truthful STOP child instructions."""

    __tablename__ = "execution_orders"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_execution_qty"),
        CheckConstraint("environment IN ('PAPER', 'LIVE')", name="ck_execution_environment"),
        CheckConstraint(
            "role IN ('ENTRY', 'TARGET', 'STOP', 'EXIT', 'REPAIR')", name="ck_execution_role"
        ),
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_execution_side"),
        CheckConstraint("order_type IN ('LIMIT', 'STOP')", name="ck_execution_type"),
        CheckConstraint(
            "(role = 'ENTRY' AND side = 'BUY' AND order_type = 'LIMIT') OR (role != 'ENTRY' AND side = 'SELL')",
            name="ck_execution_direction",
        ),
        CheckConstraint(
            "(order_type = 'LIMIT' AND limit_price IS NOT NULL AND limit_price > 0 AND limit_price % 10000 = 0) OR (order_type = 'STOP' AND limit_price IS NULL AND stop_price IS NOT NULL AND stop_price > 0 AND stop_price % 10000 = 0)",
            name="ck_execution_price",
        ),
        CheckConstraint("time_in_force IN ('DAY', 'GTC')", name="ck_execution_tif"),
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    parent_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("execution_orders.id"), nullable=True
    )
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(5), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(6), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    order_type: Mapped[str] = mapped_column(String(5), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    time_in_force: Mapped[str] = mapped_column(String(3), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ExecutionFillRecord(LedgerRecord):
    """AX-26: exact fills through record_fill, without relabeling stops as limits."""

    __tablename__ = "execution_fills"
    __table_args__ = (
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_execution_fill_qty"),
        CheckConstraint("price > 0 AND price % 10000 = 0", name="ck_execution_fill_price"),
    )
    execution_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("execution_orders.id"), nullable=False, index=True
    )
    broker_fill_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(PriceType(), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class AutoJobRun(LedgerRecord):
    """AX-22/28/40: additive auto jobs, preserving the original job constraints."""

    __tablename__ = "auto_job_runs"
    __table_args__ = (
        CheckConstraint("job IN ('auto_entry', 'auto_poll')", name="ck_auto_job_name"),
        CheckConstraint("outcome IN ('PASS', 'FAIL', 'SKIPPED')", name="ck_auto_job_outcome"),
        CheckConstraint(
            "finished_at >= started_at AND duration_ms >= 0", name="ck_auto_job_interval"
        ),
        CheckConstraint("environment IN ('PAPER', 'LIVE')", name="ck_auto_job_environment"),
    )
    job: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(5), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RiskDecision(LedgerRecord):
    """R-03: verdict provenance binds an existing proposal and config."""

    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVED', 'VETOED')", name="ck_risk_decision"),
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("orders.proposal_id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(8), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RiskRuleResult(LedgerRecord):
    """R-03: one complete deterministic result for each evaluated rule."""

    __tablename__ = "risk_rule_results"
    __table_args__ = (
        CheckConstraint("severity IN ('BLOCK', 'WARN')", name="ck_risk_rule_severity"),
        CheckConstraint("passed IN (0, 1)", name="ck_risk_rule_passed"),
    )

    risk_decision_id: Mapped[UUID] = mapped_column(ForeignKey("risk_decisions.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    observed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    limit: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class ComplianceCheck(LedgerRecord):
    """CMP-01..07: compliance findings remain separate audit records."""

    __tablename__ = "compliance_checks"
    __table_args__ = (
        CheckConstraint("severity IN ('BLOCK', 'WARN')", name="ck_compliance_severity"),
        CheckConstraint("passed IN (0, 1)", name="ck_compliance_passed"),
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("orders.proposal_id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    observed: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    limit: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class PortfolioState(LedgerRecord):
    """CRO-09/CRO-10: immutable managed-account baselines and positions."""

    __tablename__ = "portfolio_state"
    __table_args__ = (
        CheckConstraint("account_type IN ('CASH', 'MARGIN')", name="ck_portfolio_account_type"),
    )

    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str] = mapped_column(String(8), nullable=False)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    equity: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    cash: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    settled_cash: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    positions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    high_water_mark: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    day_start_equity: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    cash_flow_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    cash_flow_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SystemEvent(LedgerRecord):
    """R-02/R-09: persistent escalation and identified operator resets."""

    __tablename__ = "system_events"
    __table_args__ = (
        CheckConstraint("state IN ('RUNNING', 'REDUCE_ONLY', 'HALTED')", name="ck_system_state"),
        CheckConstraint(
            "event_type IN ('ESCALATE', 'OPERATOR_RESET', 'INITIALIZED')",
            name="ck_system_event_type",
        ),
        CheckConstraint(
            "event_type != 'OPERATOR_RESET' OR "
            "(operator_id IS NOT NULL AND length(trim(operator_id)) > 0)",
            name="ck_system_operator",
        ),
    )

    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    operator_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)


class ConfigSnapshot(LedgerRecord):
    """R-06/R-07: only nonsecret canonical settings belong in this ledger."""

    __tablename__ = "config_snapshots"

    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class Alert(LedgerRecord):
    """GD-03/GD-05/R-14: immutable proposal card; lifecycle is AlertEvent history.

    The UUID primary key is the stable logical alert_id. Initial status is
    always PENDING; delivery and approval never mutate this row.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("status = 'PENDING'", name="ck_alert_initial_status"),
        CheckConstraint("score >= 1000000 AND score <= 10000000", name="ck_alert_score"),
        CheckConstraint("expires_at > created_at", name="ck_alert_expiry"),
        CheckConstraint(
            "telegram_message_id IS NULL OR telegram_chat_id IS NOT NULL",
            name="ck_alert_message_chat",
        ),
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("orders.proposal_id"), nullable=False)
    signal_id: Mapped[UUID] = mapped_column(ForeignKey("signals.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    playbook: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    card_text: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    @property
    def alert_id(self) -> UUID:
        """R-14: stable parent identity used by reports, events and tickets."""
        return self.id


class ResearchReport(LedgerRecord):
    """GD-03: every deterministic or advisory research outcome is attributable."""

    __tablename__ = "research_reports"
    __table_args__ = (
        CheckConstraint("status IN ('OK', 'UNAVAILABLE', 'ERROR')", name="ck_research_status"),
    )

    alert_id: Mapped[UUID] = mapped_column(ForeignKey("alerts.id"), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ApprovalEvent(LedgerRecord):
    """GD-05/R-14: single-use human decision or explicit expiry/failure evidence."""

    __tablename__ = "approval_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('MANUALLY_APPROVED', 'USER_VETOED', 'EXPIRED', 'REVALIDATION_FAILED')",
            name="ck_approval_action",
        ),
        CheckConstraint(
            "action NOT IN ('MANUALLY_APPROVED', 'USER_VETOED') OR "
            "(telegram_user_id IS NOT NULL AND telegram_user_id > 0)",
            name="ck_approval_user",
        ),
    )

    alert_id: Mapped[UUID] = mapped_column(
        ForeignKey("alerts.id"), nullable=False, unique=True, index=True
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    @property
    def event_id(self) -> UUID:
        """GD-05: event_id is its immutable UUID primary key."""
        return self.id


class AlertEvent(LedgerRecord):
    """GD-05/R-14: append-only delivery and actionable approval projections."""

    __tablename__ = "alert_events"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PENDING', 'SENT', 'APPROVED', 'REJECTED', 'EXPIRED', "
            "'REVALIDATION_FAILED')",
            name="ck_alert_event_state",
        ),
        CheckConstraint(
            "state NOT IN ('APPROVED', 'REJECTED', 'EXPIRED', 'REVALIDATION_FAILED') OR "
            "approval_event_id IS NOT NULL",
            name="ck_alert_event_evidence",
        ),
        CheckConstraint(
            "state != 'SENT' OR (telegram_chat_id IS NOT NULL AND "
            "telegram_message_id IS NOT NULL AND telegram_message_id > 0)",
            name="ck_alert_delivery_binding",
        ),
    )

    alert_id: Mapped[UUID] = mapped_column(ForeignKey("alerts.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    approval_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_events.id"), nullable=True, unique=True
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class TradeTicket(LedgerRecord):
    """R-10/R-13/R-14: immutable manual broker ticket, never an execution request."""

    __tablename__ = "trade_tickets"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_ticket_side"),
        CheckConstraint("qty > 0 AND qty = CAST(qty AS BIGINT)", name="ck_ticket_qty"),
        CheckConstraint("limit_price > 0 AND limit_price % 10000 = 0", name="ck_ticket_limit"),
        CheckConstraint(
            "stop_price IS NULL OR (stop_price > 0 AND stop_price % 10000 = 0)",
            name="ck_ticket_stop",
        ),
        CheckConstraint(
            "target_price IS NULL OR (target_price > 0 AND target_price % 10000 = 0)",
            name="ck_ticket_target",
        ),
        CheckConstraint(
            "side != 'BUY' OR (stop_price IS NOT NULL AND stop_price < limit_price)",
            name="ck_ticket_long_stop",
        ),
        CheckConstraint(
            "side != 'BUY' OR target_price IS NULL OR target_price > limit_price",
            name="ck_ticket_long_target",
        ),
        CheckConstraint("valid_until > created_at", name="ck_ticket_expiry"),
    )

    alert_id: Mapped[UUID] = mapped_column(ForeignKey("alerts.id"), nullable=False, unique=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal] = mapped_column(PriceType(), nullable=False)
    stop_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(PriceType(), nullable=True)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ticket_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    @property
    def ticket_id(self) -> UUID:
        """R-14: ticket_id is its immutable UUID primary key."""
        return self.id


class TicketEvent(LedgerRecord):
    """GD-06: one append-only placed/skipped follow-up per approved ticket.

    Separate additive table preserves the earlier ApprovalEvent CHECK and its
    single decision constraint without rewriting any existing ledger row.
    """

    __tablename__ = "ticket_events"
    __table_args__ = (
        CheckConstraint("action IN ('TICKET_PLACED', 'TICKET_SKIPPED')", name="ck_ticket_action"),
        CheckConstraint("telegram_user_id > 0", name="ck_ticket_user"),
    )
    ticket_id: Mapped[UUID] = mapped_column(
        ForeignKey("trade_tickets.id"), nullable=False, unique=True
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class JobRun(LedgerRecord):
    """GD-04: complete or failed scheduled runs remain immutable."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint("finished_at >= started_at", name="ck_job_interval"),
        CheckConstraint("duration_ms >= 0", name="ck_job_duration"),
        CheckConstraint("outcome IN ('PASS', 'FAIL', 'SKIPPED')", name="ck_job_outcome"),
        CheckConstraint(
            "job IN ('daily_scan', 'premarket_check', 'position_monitor', 'news_watch', 'weekly_report', 'housekeeping')",
            name="ck_job_name",
        ),
    )
    job: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LLMCall(LedgerRecord):
    """GD-01: exact observed costs; missing transport usage is explicitly unknown."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('VALID', 'INVALID', 'TIMEOUT', 'BUDGET')", name="ck_llm_outcome"
        ),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_llm_input_tokens"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="ck_llm_output_tokens"),
        CheckConstraint("est_cost_usd IS NULL OR est_cost_usd >= 0", name="ck_llm_cost"),
        CheckConstraint("latency_ms >= 0", name="ck_llm_latency"),
        CheckConstraint(
            "outcome != 'VALID' OR (input_tokens IS NOT NULL AND output_tokens IS NOT NULL "
            "AND est_cost_usd IS NOT NULL)",
            name="ck_llm_valid_usage",
        ),
        CheckConstraint(
            "outcome != 'BUDGET' OR (input_tokens IS NOT NULL AND output_tokens IS NOT NULL "
            "AND est_cost_usd IS NOT NULL AND input_tokens = 0 AND output_tokens = 0 AND "
            "est_cost_usd = 0)",
            name="ck_llm_budget_no_call",
        ),
    )

    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url_host: Mapped[str] = mapped_column(String(253), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    est_cost_usd: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)


class SecurityEvent(LedgerRecord):
    """GD-05/R-12/R-14: rejected authentication, signature and replay attempts."""

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint("length(trim(kind)) > 0", name="ck_security_kind"),
        CheckConstraint(
            "telegram_user_id IS NULL OR telegram_user_id > 0", name="ck_security_user"
        ),
    )

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class CashFlow(LedgerRecord):
    """FN-02: one observed activity; no operation initiates a cash transfer."""

    __tablename__ = "cash_flows"
    __table_args__ = (
        UniqueConstraint("account_id", "env", "activity_id", name="uq_cash_activity"),
        CheckConstraint("env IN ('PAPER', 'LIVE')", name="ck_cash_env"),
        CheckConstraint("baseline_effect IN ('SCALED', 'INCLUDED', 'NONE')", name="ck_cash_effect"),
    )
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    env: Mapped[str] = mapped_column(String(8), nullable=False)
    activity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    baseline_effect: Mapped[str] = mapped_column(String(8), nullable=False)
    portfolio_state_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_state.id"), nullable=True
    )


class DailyPnL(LedgerRecord):
    """PL-01: corrections append a new version of the same bound session."""

    __tablename__ = "daily_pnl"
    __table_args__ = (
        CheckConstraint("env IN ('PAPER', 'LIVE')", name="ck_pnl_env"),
        CheckConstraint("source IN ('BROKER', 'COMPUTED')", name="ck_pnl_source"),
        CheckConstraint("equity > 0 AND cash >= 0 AND long_market_value >= 0", name="ck_pnl_long"),
        UniqueConstraint("supersedes", name="uq_pnl_superseded_once"),
    )
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    env: Mapped[str] = mapped_column(String(8), nullable=False)
    session_date: Mapped[str] = mapped_column(String(10), nullable=False)
    equity: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    cash: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    long_market_value: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    supersedes: Mapped[UUID | None] = mapped_column(ForeignKey("daily_pnl.id"), nullable=True)


class TaxEvent(LedgerRecord):
    """TX-10: exact imported/fill evidence; corrections never edit prior rows."""

    __tablename__ = "tax_events"
    __table_args__ = (
        CheckConstraint("env IN ('PAPER', 'LIVE')", name="ck_tax_env"),
        CheckConstraint(
            "kind IN ('FILL', 'INCOME', 'IMPORT', 'MARKED_LOT', 'CORPORATE_ACTION')",
            name="ck_tax_kind",
        ),
        UniqueConstraint("supersedes", name="uq_tax_superseded_once"),
    )
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    env: Mapped[str] = mapped_column(String(8), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    supersedes: Mapped[UUID | None] = mapped_column(ForeignKey("tax_events.id"), nullable=True)


class SchemaVersion(LedgerRecord):
    """OPS-05: immutable versioned migrations with the verified backup digest."""

    __tablename__ = "schema_version"
    __table_args__ = (
        CheckConstraint(
            "version > source_version AND source_version >= 2", name="ck_migration_forward"
        ),
        UniqueConstraint("version", name="uq_migration_version"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    backup_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class SchemaMeta(Base):
    """R-02: refuse older schemas instead of silently mixing audit contracts."""

    __tablename__ = "schema_meta"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_schema_singleton"),
        CheckConstraint("version > 0", name="ck_schema_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class SystemControl(Base):
    """R-02: mutable singleton projection, checked against system events."""

    __tablename__ = "system_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_control_singleton"),
        CheckConstraint("state IN ('RUNNING', 'REDUCE_ONLY', 'HALTED')", name="ck_control_state"),
        CheckConstraint("version >= 0", name="ck_control_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class AppendControl(Base):
    """R-02: transaction-locked singleton allocates a global ledger sequence."""

    __tablename__ = "append_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_append_singleton"),
        CheckConstraint("next_seq > 0", name="ck_append_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    next_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


LEDGER_MODELS: tuple[type[LedgerRecord], ...] = (
    DataSnapshot,
    NewsHeadlineRecord,
    Signal,
    Order,
    OrderEvent,
    Fill,
    RiskDecision,
    RiskRuleResult,
    ComplianceCheck,
    PortfolioState,
    SystemEvent,
    ConfigSnapshot,
    Alert,
    ResearchReport,
    ApprovalEvent,
    AlertEvent,
    TradeTicket,
    TicketEvent,
    JobRun,
    LLMCall,
    SecurityEvent,
    SchemaVersion,
    CashFlow,
    DailyPnL,
    TaxEvent,
    ExecutionOrderRecord,
    ExecutionFillRecord,
    AutoJobRun,
)


def _reject_mutation(mapper: Any, connection: Connection, target: LedgerRecord) -> None:
    """R-02: ORM mutation protection is independent of database triggers."""
    raise LedgerIntegrityError(f"Append-only ledger rejects mutation of {target.__tablename__}")


for _model in LEDGER_MODELS:
    for _column in _model.__table__.columns:
        if isinstance(_column.type, MoneyType):
            cast(Table, _model.__table__).append_constraint(
                CheckConstraint(
                    f"{_column.name} IS NULL OR {_column.name} = CAST({_column.name} AS BIGINT)",
                    name=f"ck_{_model.__tablename__}_{_column.name}_integer_storage",
                )
            )
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)


def _sqlite_foreign_keys(connection: Any, connection_record: Any) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA recursive_triggers=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
    finally:
        cursor.close()


def create_database(url: str) -> Engine:
    """R-02: create SQLite/PostgreSQL storage; SQLite FKs are always enabled."""
    try:
        engine = create_engine(url, pool_pre_ping=True)
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            engine.dispose()
            raise DatabaseError("Only SQLite and PostgreSQL databases are supported")
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _sqlite_foreign_keys)
        return engine
    except SafetyError:
        raise
    except Exception as exc:
        raise DatabaseError("Database engine initialization failed") from exc


def enable_sqlite_wal(engine: Engine) -> None:
    """OPS-02: explicit host startup only, after schema/backup verification."""
    if engine.dialect.name != "sqlite":
        return
    if engine.url.database in {None, "", ":memory:"}:
        raise DatabaseError("Host WAL requires a file-backed SQLite ledger")
    try:
        with engine.connect() as connection:
            mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar()
            if mode != "wal":
                raise DatabaseError("SQLite WAL could not be enabled")
    except SafetyError:
        raise
    except Exception:
        raise DatabaseError("SQLite WAL setup failed") from None


@contextmanager
def transaction(engine: Engine) -> Iterator[Session]:
    """R-02: serialize SQLite writers; lock the allocation row on PostgreSQL."""
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            with Session(bind=connection, expire_on_commit=False) as session:
                try:
                    if engine.dialect.name == "postgresql":
                        control = session.scalar(
                            select(AppendControl).where(AppendControl.id == 1).with_for_update()
                        )
                        if control is None:
                            raise LedgerIntegrityError("Ledger allocation control is missing")
                    yield session
                    session.flush()
                    connection.commit()
                except Exception:
                    session.rollback()
                    connection.rollback()
                    raise
    except SafetyError:
        raise
    except Exception as exc:
        raise DatabaseError("Database transaction failed") from exc


def prepare_panic_schema(engine: Engine) -> None:
    """SEC-73/OPS-05: keep local HALT reachable on the exact pre-news schema.

    Only emergency host composition calls this. It never upgrades an existing
    schema and never certifies its chains. Ordinary startup still requires the
    current version and an explicit backed-up migration for an older database.
    """
    try:
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        if "schema_meta" in existing:
            with engine.connect() as connection:
                version = connection.scalar(select(SchemaMeta.version).where(SchemaMeta.id == 1))
            if version in {2, 3, 4, 5, 6, 7}:
                expected = {
                    name
                    for name in Base.metadata.tables
                    if name
                    not in {
                        *(
                            {
                                ExecutionOrderRecord.__tablename__,
                                ExecutionFillRecord.__tablename__,
                                AutoJobRun.__tablename__,
                            }
                            if version < 7
                            else set()
                        ),
                    }
                    and (
                        version >= 6
                        or name
                        not in {
                            CashFlow.__tablename__,
                            DailyPnL.__tablename__,
                            TaxEvent.__tablename__,
                        }
                    )
                    and (version >= 5 or name != SchemaVersion.__tablename__)
                    and (
                        version >= 4
                        or name not in {TicketEvent.__tablename__, JobRun.__tablename__}
                    )
                    and (version != 2 or name != NewsHeadlineRecord.__tablename__)
                }
                if existing != expected:
                    raise DatabaseError("Emergency ledger table inventory is incompatible")
                for name in expected:
                    persisted = {column["name"] for column in inspector.get_columns(name)}
                    if persisted != {column.name for column in Base.metadata.tables[name].columns}:
                        raise DatabaseError("Emergency ledger control schema is incompatible")
                return
        create_schema(engine)
    except SafetyError:
        raise
    except Exception:
        raise DatabaseError("Emergency ledger schema could not be verified") from None


def create_schema(engine: Engine) -> None:
    """R-02: initialize a fresh schema or refuse any incompatible persisted one.

    Schema upgrades need an explicit audited migration; create_all is never
    used to conceal an old database missing new columns or ledger tables.
    """
    try:
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        if existing:
            if "schema_meta" not in existing:
                raise DatabaseError("Existing ledger needs an explicit schema migration")
            with engine.connect() as connection:
                version = connection.scalar(select(SchemaMeta.version).where(SchemaMeta.id == 1))
            if version != SCHEMA_VERSION:
                raise DatabaseError("Persisted ledger schema version is incompatible")
            if existing != set(Base.metadata.tables):
                raise DatabaseError("Persisted ledger table inventory is incompatible")
            for table in Base.metadata.sorted_tables:
                persisted_columns = {column["name"] for column in inspector.get_columns(table.name)}
                if persisted_columns != {column.name for column in table.columns}:
                    raise DatabaseError("Persisted ledger columns require an explicit migration")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            install_append_only_triggers(connection)
        with engine.begin() as connection:
            insert = sqlite_insert if engine.dialect.name == "sqlite" else postgresql_insert
            connection.execute(
                insert(SchemaMeta)
                .values(id=1, version=SCHEMA_VERSION)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            connection.execute(
                insert(SystemControl)
                .values(id=1, state="RUNNING", version=0)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            connection.execute(
                insert(AppendControl)
                .values(id=1, next_seq=1)
                .on_conflict_do_nothing(index_elements=["id"])
            )
    except SafetyError:
        raise
    except Exception as exc:
        raise DatabaseError("Database schema initialization failed") from exc


def install_append_only_triggers(connection: Connection) -> None:
    """OPS-05: share exact immutable-table protection with additive migration."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION vws_reject_ledger_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append-only ledger'; END; $$"
        )
    for model in LEDGER_MODELS:
        table = model.__tablename__
        for operation in ("UPDATE", "DELETE"):
            trigger = f"vws_{table}_{operation.lower()}"
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END"
                )
            else:
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
                connection.exec_driver_sql(
                    f"CREATE TRIGGER {trigger} BEFORE {operation} ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION vws_reject_ledger_mutation()"
                )
