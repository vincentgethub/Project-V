"""R-02/R-04/R-05/R-08: local immutable audit ledger and reconciliation.

Hash chains detect accidental corruption and unauthorized row edits, not an
administrator capable of rewriting an entire database and all its hash chains.
Use database access controls and independent backups in production.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Any, TypeVar, overload
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.database import (
    LEDGER_MODELS,
    Alert,
    AlertEvent,
    AppendControl,
    ApprovalEvent,
    AutoJobRun,
    CashFlow,
    ConfigSnapshot,
    DailyPnL,
    ExecutionFillRecord,
    ExecutionOrderRecord,
    Fill,
    JobRun,
    LedgerRecord,
    LLMCall,
    MoneyType,
    NewsHeadlineRecord,
    Order,
    OrderEvent,
    PortfolioState,
    ResearchReport,
    SecurityEvent,
    Signal,
    SystemControl,
    SystemEvent,
    TaxEvent,
    TicketEvent,
    TradeTicket,
    UTCDateTime,
    transaction,
)
from backend.core.errors import (
    DataIntegrityError,
    LedgerIntegrityError,
    ReconciliationError,
    SafetyError,
)
from backend.core.money import money_to_scaled, scaled_to_money, validate_cent_price
from backend.core.notifier import ConsoleNotifier, DeduplicatingNotifier

RecordT = TypeVar("RecordT", bound=LedgerRecord)
GENESIS_HASH = "0" * 64
_ORDER_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"PROPOSED"}),
    "PROPOSED": frozenset({"APPROVED"}),
    "APPROVED": frozenset({"SUBMITTED"}),
    "SUBMITTED": frozenset(
        {"PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "CANCEL_REQUESTED"}
    ),
    "PARTIALLY_FILLED": frozenset(
        {"PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "CANCEL_REQUESTED"}
    ),
    "CANCEL_REQUESTED": frozenset({"FILLED", "CANCELED"}),
    "FILLED": frozenset(),
    "CANCELED": frozenset(),
    "REJECTED": frozenset(),
}
_STATE_RANK = {"RUNNING": 0, "REDUCE_ONLY": 1, "HALTED": 2}
_APPROVAL_STATES = {
    "MANUALLY_APPROVED": "APPROVED",
    "USER_VETOED": "REJECTED",
    "EXPIRED": "EXPIRED",
    "REVALIDATION_FAILED": "REVALIDATION_FAILED",
}
_ALERT_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"PENDING"}),
    "PENDING": frozenset({"SENT", "EXPIRED", "REVALIDATION_FAILED"}),
    "SENT": frozenset({"APPROVED", "REJECTED", "EXPIRED", "REVALIDATION_FAILED"}),
    "APPROVED": frozenset(),
    "REJECTED": frozenset(),
    "EXPIRED": frozenset(),
    "REVALIDATION_FAILED": frozenset(),
}


def _json_value(value: Any) -> Any:
    """R-04/R-05: make exact JSON; reject floats, secrets and unknown objects."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        return format(scaled_to_money(money_to_scaled(value)), "f")
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise DataIntegrityError("Ledger JSON keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise DataIntegrityError("Ledger JSON contains an unsupported or inexact value")


def canonical_json(record: LedgerRecord) -> str:
    """R-04/R-05: canonical row includes identity and sequence, excludes hashes."""
    values: dict[str, Any] = {}
    for column in record.__table__.columns:
        if column.name in {"row_hash", "prev_hash"}:
            continue
        value = record.__dict__[column.name]
        # Money hashes use stored micro-units so Decimal exponent is irrelevant.
        values[column.name] = (
            {"decimal_micro_units": money_to_scaled(value)}
            if isinstance(value, Decimal)
            else _json_value(value)
        )
    return json.dumps(
        values,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def row_digest(record: LedgerRecord) -> str:
    """R-02: bind each row to its predecessor and full canonical content."""
    return hashlib.sha256((record.prev_hash + canonical_json(record)).encode("utf-8")).hexdigest()


def ticket_digest(record: TradeTicket) -> str:
    """R-10/R-14: deterministic digest binds only immutable manual-ticket fields."""
    values = {
        "alert_id": record.alert_id,
        "symbol": record.symbol,
        "side": record.side,
        "qty": record.qty,
        "limit_price": record.limit_price,
        "stop_price": record.stop_price,
        "target_price": record.target_price,
        "valid_until": record.valid_until,
    }
    canonical = json.dumps(_json_value(values), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _valid_transition(previous: str | None, target: str) -> bool:
    return target in _ORDER_TRANSITIONS.get(previous, frozenset())


class Ledger:
    """R-02/R-08: serialize appends; no broker order or funding API exists."""

    def __init__(
        self,
        engine: Engine,
        clock: Clock,
        *,
        halt_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self._notifier = DeduplicatingNotifier(ConsoleNotifier())
        self.halt_callback = halt_callback or (
            lambda reason: self._notifier.notify("HALTED", reason)
        )

    def append(self, model_type: type[RecordT], **fields: Any) -> RecordT:
        """R-02: append one record and its automatic lifecycle evidence atomically."""
        with transaction(self.engine) as session:
            record = self.append_in_session(session, model_type, **fields)
        return record

    def append_in_session(
        self, session: Session, model_type: type[RecordT], **fields: Any
    ) -> RecordT:
        """R-02: share transaction(engine) with an atomic system-state transition.

        Callers own the transaction and must use the serialized transaction helper.
        Reserved identity/chain fields cannot be supplied by application code.
        """
        if model_type not in LEDGER_MODELS:
            raise LedgerIntegrityError("Unregistered append-only ledger record type")
        if {"id", "seq", "prev_hash", "row_hash"}.intersection(fields):
            raise LedgerIntegrityError("Ledger identity and hash fields are reserved")
        if not session.in_transaction():
            session.begin()
        try:
            control = session.scalar(
                select(AppendControl).where(AppendControl.id == 1).with_for_update()
            )
            if control is None:
                raise LedgerIntegrityError("Ledger allocation control is missing")
            normalized = dict(fields)
            if model_type is Signal:
                normalized.setdefault("signal_type", "SIGNAL")
            if model_type is Order:
                normalized.setdefault("order_type", "LIMIT")
                normalized.setdefault("target_price", None)
            if model_type.__tablename__ == "data_snapshots":
                normalized.setdefault("bars", [])
            if model_type is PortfolioState:
                normalized.setdefault("cash_flow_amount", Decimal(0))
                normalized.setdefault("cash_flow_at", None)
            if model_type is Alert:
                normalized.setdefault("status", "PENDING")
                normalized.setdefault("telegram_chat_id", None)
                normalized.setdefault("telegram_message_id", None)
            if model_type is AlertEvent:
                normalized.setdefault("approval_event_id", None)
                normalized.setdefault("telegram_chat_id", None)
                normalized.setdefault("telegram_message_id", None)
            if model_type is ResearchReport:
                normalized.setdefault("prompt_hash", None)
            if model_type is ApprovalEvent or model_type is SecurityEvent:
                normalized.setdefault("ts", self.clock.now())
                normalized.setdefault("telegram_user_id", None)
            for column in model_type.__table__.columns:
                if column.nullable:
                    normalized.setdefault(column.name, None)
                if column.name in normalized:
                    value = normalized[column.name]
                    if isinstance(value, float):
                        raise DataIntegrityError("Ledger fields reject float values")
                    if value is not None and column.name in {
                        "limit_price",
                        "stop_price",
                        "target_price",
                        "price",
                    }:
                        normalized[column.name] = validate_cent_price(value)
                    if column.type.__class__.__name__ == "JSON":
                        normalized[column.name] = _json_value(value)
                    elif isinstance(value, datetime):
                        normalized[column.name] = ensure_utc(value)
            record = model_type(**normalized)
            record.id = uuid4()
            record.seq = control.next_seq
            record.created_at = ensure_utc(normalized.get("created_at", self.clock.now()))
            previous = session.scalar(select(model_type).order_by(model_type.seq.desc()).limit(1))
            record.prev_hash = GENESIS_HASH if previous is None else previous.row_hash
            self._validate_record(session, record)
            if isinstance(record, TradeTicket):
                if "ticket_sha256" not in normalized:
                    record.ticket_sha256 = ticket_digest(record)
                elif record.ticket_sha256 != ticket_digest(record):
                    raise LedgerIntegrityError("Trade-ticket digest does not bind its exact fields")
            record.row_hash = row_digest(record)
            control.next_seq += 1
            session.add(record)
            session.flush()
            if isinstance(record, Order):
                self.append_in_session(
                    session,
                    OrderEvent,
                    order_id=record.id,
                    state="PROPOSED",
                    reason="local proposal recorded",
                    broker_order_id=None,
                )
            elif isinstance(record, Fill):
                order = session.get(Order, record.order_id)
                if order is None:
                    raise LedgerIntegrityError("Fill refers to a missing order")
                total = sum(
                    fill.qty
                    for fill in session.scalars(
                        select(Fill).where(Fill.order_id == record.order_id)
                    )
                )
                state = "FILLED" if total == order.qty else "PARTIALLY_FILLED"
                latest = session.scalar(
                    select(OrderEvent)
                    .where(OrderEvent.order_id == record.order_id)
                    .order_by(OrderEvent.seq.desc())
                    .limit(1)
                )
                if latest is None or latest.state != "CANCEL_REQUESTED":
                    self.append_in_session(
                        session,
                        OrderEvent,
                        order_id=record.order_id,
                        state=state,
                        reason="observed fill recorded",
                        broker_order_id=None,
                    )
            elif isinstance(record, ExecutionFillRecord):
                from backend.execution.storage import (
                    entry_filled_quantity,
                    entry_quantity,
                    finalize_shared_order,
                )

                instruction = session.get(ExecutionOrderRecord, record.execution_order_id)
                if instruction is None:
                    raise LedgerIntegrityError("Execution fill instruction is missing")
                if instruction.role == "ENTRY":
                    total = entry_filled_quantity(session, instruction.order_id)
                    expected = entry_quantity(session, instruction.order_id)
                    latest = session.scalar(
                        select(OrderEvent)
                        .where(OrderEvent.order_id == instruction.order_id)
                        .order_by(OrderEvent.seq.desc())
                        .limit(1)
                    )
                    if latest is None or latest.state != "CANCEL_REQUESTED":
                        if total != expected:
                            self.append_in_session(
                                session,
                                OrderEvent,
                                order_id=instruction.order_id,
                                state="PARTIALLY_FILLED",
                                reason="observed auto entry fill recorded",
                                broker_order_id=None,
                            )
                        finalize_shared_order(
                            self,
                            session,
                            instruction.order_id,
                            reason="observed auto entry fill recorded",
                        )
            elif isinstance(record, Alert):
                self.append_in_session(
                    session,
                    AlertEvent,
                    alert_id=record.id,
                    state="PENDING",
                    reason="immutable alert candidate recorded",
                )
            elif isinstance(record, ApprovalEvent):
                self.append_in_session(
                    session,
                    AlertEvent,
                    alert_id=record.alert_id,
                    state=_APPROVAL_STATES[record.action],
                    approval_event_id=record.id,
                    reason="human decision or lifecycle failure recorded",
                )
            return record
        except SafetyError:
            raise
        except Exception as exc:
            raise LedgerIntegrityError("Ledger append failed; transaction must roll back") from exc

    def _validate_record(self, session: Session, record: LedgerRecord) -> None:
        self._validate_common(record)
        if isinstance(record, SecurityEvent):
            from backend.execution.control_evidence import CONTROL_EVENTS, validate_control

            if record.kind in CONTROL_EVENTS:
                validate_control(session, record)
        if isinstance(record, (ExecutionOrderRecord, ExecutionFillRecord)) or (
            isinstance(record, SecurityEvent)
            and record.kind
            in {
                "EXECUTION_ORDER_OBSERVED",
                "AUTO_ENTRY_APPROVAL",
                "EXECUTION_SUBMIT_OUTCOME",
                "AUTO_EXIT_CYCLE",
                "AUTO_EXIT_APPROVAL",
                "STOP_RAISE_APPROVAL",
                "STOP_MOVED",
                "PAPER_CANCEL_SEMANTICS",
            }
        ):
            from backend.execution.storage import validate_record as validate_execution_record

            validate_execution_record(session, record)
        if isinstance(record, (CashFlow, DailyPnL, TaxEvent)):
            from backend.tax.storage import validate_record

            self._reject_secret_fields(record.payload)
            validate_record(session, record)
        if isinstance(record, SystemEvent):
            prior = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1))
            prior_state = "RUNNING" if prior is None else prior.state
            if record.state not in _STATE_RANK or prior_state not in _STATE_RANK:
                raise LedgerIntegrityError("System event requires a known operating state")
            if (
                _STATE_RANK[record.state] < _STATE_RANK[prior_state]
                and record.event_type != "OPERATOR_RESET"
            ):
                raise LedgerIntegrityError("Only an operator reset may lower the operating state")
            if record.event_type == "INITIALIZED" and (
                prior is not None or record.state != "RUNNING"
            ):
                raise LedgerIntegrityError("Initialization is allowed only once in RUNNING")
        if isinstance(record, Order):
            if isinstance(record.qty, bool) or not isinstance(record.qty, int):
                raise DataIntegrityError("Order quantity requires whole shares")
            if not isinstance(record.signal_id, UUID):
                raise LedgerIntegrityError("Order requires an explicit signal UUID")
            signal = session.get(Signal, record.signal_id)
            if signal is None or signal.symbol != record.symbol or signal.direction != record.side:
                raise LedgerIntegrityError("Order cannot be traced to a matching signal")
            if signal.signal_type != record.source:
                raise LedgerIntegrityError("Order source must match its explicit signal type")
        if isinstance(record, OrderEvent):
            previous = session.scalar(
                select(OrderEvent)
                .where(OrderEvent.order_id == record.order_id)
                .order_by(OrderEvent.seq.desc())
                .limit(1)
            )
            previous_state = None if previous is None else previous.state
            if not _valid_transition(previous_state, record.state):
                raise LedgerIntegrityError("Invalid appended order lifecycle transition")
            order = session.get(Order, record.order_id)
            if order is None:
                raise LedgerIntegrityError("Order event has no local order")
            total = sum(
                fill.qty
                for fill in session.scalars(select(Fill).where(Fill.order_id == record.order_id))
            )
            from backend.execution.storage import entry_filled_quantity, entry_quantity

            execution = session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.order_id == order.id,
                    ExecutionOrderRecord.role == "ENTRY",
                )
            )
            expected_qty = entry_quantity(session, order.id) or order.qty
            if execution is not None:
                total += entry_filled_quantity(session, order.id)
            if record.state == "FILLED" and total != expected_qty:
                raise LedgerIntegrityError(
                    "FILLED event requires the complete observed fill quantity"
                )
            if record.state == "PARTIALLY_FILLED" and not 0 < total < expected_qty:
                raise LedgerIntegrityError("Partial event requires observed partial fills")
        if isinstance(record, Fill):
            self._validate_fill(session, record)
        if isinstance(record, ConfigSnapshot):
            self._reject_secret_fields(record.settings)
        if isinstance(record, Alert):
            order = session.scalar(select(Order).where(Order.proposal_id == record.proposal_id))
            if (
                order is None
                or order.signal_id != record.signal_id
                or order.symbol != record.symbol
                or record.status != "PENDING"
            ):
                raise LedgerIntegrityError("Alert requires the proposal's exact matching signal")
            if record.expires_at <= record.created_at or record.expires_at <= self.clock.now():
                raise LedgerIntegrityError("Alert must have a future expiry after creation")
            if record.telegram_message_id is not None:
                raise LedgerIntegrityError("Alert delivery binding belongs in a SENT event")
        if isinstance(record, ApprovalEvent):
            self._validate_approval(session, record)
        if isinstance(record, AlertEvent):
            self._validate_alert_event(session, record)
        if isinstance(record, TradeTicket):
            self._validate_ticket(session, record)
        if isinstance(record, TicketEvent):
            ticket = session.get(TradeTicket, record.ticket_id)
            if (
                ticket is None
                or ticket.created_at > record.created_at
                or record.action not in {"TICKET_PLACED", "TICKET_SKIPPED"}
                or type(record.telegram_user_id) is not int
                or record.telegram_user_id <= 0
                or session.scalar(
                    select(TicketEvent).where(TicketEvent.ticket_id == record.ticket_id)
                )
                is not None
            ):
                raise LedgerIntegrityError(
                    "GD-06: ticket follow-up lacks single-use approved provenance"
                )
        if isinstance(record, (JobRun, AutoJobRun)):
            if (
                record.finished_at < record.started_at
                or record.finished_at > record.created_at
                or type(record.duration_ms) is not int
                or record.duration_ms < 0
            ):
                raise LedgerIntegrityError("GD-04: job interval or duration is invalid")

    def _validate_common(self, record: LedgerRecord, *, verifying: bool = False) -> None:
        """R-02/R-04/R-05/R-13: exact field boundaries also apply during verification."""
        if isinstance(record, (JobRun, AutoJobRun)):
            self._validate_job_run(record)
        for column in record.__table__.columns:
            if column.name in {"row_hash", "ticket_sha256"} and not verifying:
                continue
            value = record.__dict__.get(column.name)
            if value is None:
                if not column.nullable:
                    raise DataIntegrityError("A required ledger field is missing")
                continue
            if isinstance(value, float):
                raise DataIntegrityError("Ledger values must not contain floats")
            if isinstance(column.type, MoneyType):
                if not isinstance(value, Decimal):
                    raise DataIntegrityError("Ledger money requires Decimal")
                money_to_scaled(value)
            if isinstance(column.type, UTCDateTime):
                if not isinstance(value, datetime):
                    raise DataIntegrityError("Ledger timestamps require datetime values")
                ensure_utc(value)
            if column.type.__class__.__name__ == "JSON":
                if column.name in {"bars", "reasons"}:
                    if not isinstance(value, list):
                        raise DataIntegrityError("Ledger array fields require JSON arrays")
                elif not isinstance(value, dict):
                    raise DataIntegrityError("Ledger object fields require JSON objects")
                _json_value(value)
            if column.name in {
                "qty",
                "input_tokens",
                "output_tokens",
                "latency_ms",
                "version",
                "source_version",
            }:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise DataIntegrityError("Counts and whole shares require integers")
            if column.name in {"telegram_chat_id", "telegram_message_id", "telegram_user_id"}:
                if isinstance(value, bool) or not isinstance(value, int) or value == 0:
                    raise DataIntegrityError("Telegram identifiers require nonzero integers")
            if column.name in {"limit_price", "stop_price", "target_price", "price"}:
                if not isinstance(value, Decimal):
                    raise DataIntegrityError("Ledger prices require Decimal values")
                validate_cent_price(value)
            if column.name in {
                "config_hash",
                "snapshot_hash",
                "prompt_hash",
                "sha256",
                "ticket_sha256",
                "stable_id",
                "headline_sha256",
                "backup_sha256",
                "payload_sha256",
            }:
                if not isinstance(value, str) or len(value) != 64:
                    raise DataIntegrityError(
                        "Ledger provenance requires a SHA-256 hexadecimal digest"
                    )
                if any(character not in "0123456789abcdef" for character in value):
                    raise DataIntegrityError("Ledger provenance digest is malformed")
        if record.created_at > ensure_utc(self.clock.now()):
            raise DataIntegrityError("Ledger creation timestamp is in the future")
        if isinstance(record, LLMCall):
            self._validate_llm_call(record)
        if isinstance(record, NewsHeadlineRecord):
            self._validate_news_headline(record)
        if isinstance(record, ConfigSnapshot):
            self._reject_secret_fields(record.settings)

    @staticmethod
    def _validate_job_run(record: JobRun | AutoJobRun) -> None:
        if isinstance(record, AutoJobRun) and (
            not isinstance(record.account_id, str)
            or not 1 <= len(record.account_id) <= 128
            or record.account_id != record.account_id.strip()
            or not record.account_id.isprintable()
            or record.environment not in {"PAPER", "LIVE"}
            or not isinstance(record.config_hash, str)
            or re.fullmatch(r"[a-f0-9]{64}", record.config_hash) is None
        ):
            raise LedgerIntegrityError(
                "AX-44: auto job account/environment/configuration is invalid"
            )
        allowed = (
            {"auto_entry", "auto_poll"}
            if isinstance(record, AutoJobRun)
            else {
                "daily_scan",
                "premarket_check",
                "position_monitor",
                "news_watch",
                "weekly_report",
                "housekeeping",
            }
        )
        if (
            record.job not in allowed
            or record.outcome not in {"PASS", "FAIL", "SKIPPED"}
            or record.finished_at < record.started_at
            or record.finished_at > record.created_at
            or type(record.duration_ms) is not int
            or record.duration_ms < 0
            or not isinstance(record.counts, dict)
            or len(record.counts) > 30
            or any(
                not isinstance(key, str)
                or not 1 <= len(key) <= 48
                or not key.isascii()
                or not key.replace("_", "").isalnum()
                or type(value) is not int
                or not 0 <= value <= 10**9
                for key, value in record.counts.items()
            )
        ):
            raise LedgerIntegrityError("GD-04: job run evidence is invalid")

    @staticmethod
    def _validate_news_headline(record: NewsHeadlineRecord) -> None:
        """DAT-09/SEC-60: revalidate public evidence on append and chain verification."""
        from backend.core.content import headline_digest, headline_stable_id, sanitize_text

        if record.provider not in {"ALPACA", "RSS", "NEWSAPI", "FAKE"}:
            raise DataIntegrityError("DAT-09: news provider is unknown")
        provider_id = record.provider_id
        if provider_id is not None and (
            not isinstance(provider_id, str)
            or not 1 <= len(provider_id) <= 280
            or provider_id != provider_id.strip()
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in provider_id)
        ):
            raise DataIntegrityError("DAT-09: provider headline ID is invalid")
        if (
            not isinstance(record.headline, str)
            or not record.headline
            or record.headline != sanitize_text(record.headline)
            or record.headline_sha256 != headline_digest(record.headline)
            or record.stable_id
            != headline_stable_id(record.provider, provider_id, record.headline_sha256)
        ):
            raise DataIntegrityError("DAT-09: headline citation or sanitized content is invalid")
        details = record.details
        if (
            set(details) != {"symbols", "summary_allowed"}
            or type(details["summary_allowed"]) is not bool
            or not isinstance(details["symbols"], list)
            or len(details["symbols"]) > 50
            or any(
                not isinstance(symbol, str)
                or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) is None
                for symbol in details["symbols"]
            )
            or len(set(details["symbols"])) != len(details["symbols"])
        ):
            raise DataIntegrityError("DAT-09: headline public metadata is invalid")
        if record.published_at > record.created_at:
            raise DataIntegrityError("DAT-09: headline publication is in the future")

    @staticmethod
    def _validate_llm_call(record: LLMCall) -> None:
        """GD-01/R-02: unknown transport usage never implies a free successful call."""
        if record.outcome not in {"VALID", "INVALID", "TIMEOUT", "BUDGET"}:
            raise DataIntegrityError("LLM call requires a known outcome")
        if record.latency_ms < 0 or any(
            count is not None and count < 0 for count in (record.input_tokens, record.output_tokens)
        ):
            raise DataIntegrityError("LLM usage and latency cannot be negative")
        if record.est_cost_usd is not None and record.est_cost_usd < 0:
            raise DataIntegrityError("LLM estimated cost cannot be negative")
        if record.outcome == "VALID" and None in (
            record.input_tokens,
            record.output_tokens,
            record.est_cost_usd,
        ):
            raise DataIntegrityError("Valid LLM calls require accountable usage and cost")
        if record.outcome == "BUDGET" and (
            record.input_tokens != 0
            or record.output_tokens != 0
            or record.est_cost_usd != Decimal(0)
        ):
            raise DataIntegrityError("Budget veto is a zero-cost no-call outcome")
        if not record.provider.strip() or not record.model.strip():
            raise DataIntegrityError("LLM call requires an explicit provider and model")
        host = record.base_url_host
        if not host or any(character in host for character in "/:@?# "):
            raise DataIntegrityError("LLM audit stores only the base URL hostname")

    @staticmethod
    def _latest_alert_event(session: Session, alert_id: UUID) -> AlertEvent | None:
        return session.scalar(
            select(AlertEvent)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.seq.desc())
            .limit(1)
        )

    def _validate_approval(self, session: Session, record: ApprovalEvent) -> None:
        """GD-05/R-14: consume one delivered candidate or record its expiry/failure."""
        alert = session.get(Alert, record.alert_id)
        prior = self._latest_alert_event(session, record.alert_id)
        target = _APPROVAL_STATES.get(record.action)
        if alert is None or prior is None or target is None:
            raise LedgerIntegrityError("Approval event has no known alert or action")
        if (
            session.scalar(
                select(ExecutionOrderRecord)
                .join(Order)
                .where(Order.proposal_id == alert.proposal_id, ExecutionOrderRecord.role == "ENTRY")
            )
            is not None
        ):
            raise LedgerIntegrityError("Alert was already consumed by an auto entry")
        if target not in _ALERT_TRANSITIONS.get(prior.state, frozenset()):
            raise LedgerIntegrityError("Alert is already handled or not delivered")
        if (
            session.scalar(select(ApprovalEvent).where(ApprovalEvent.alert_id == alert.id))
            is not None
        ):
            raise LedgerIntegrityError("Alert approval is single-use")
        if (
            record.ts < alert.created_at
            or record.ts > record.created_at
            or record.ts > ensure_utc(self.clock.now())
        ):
            raise LedgerIntegrityError("Approval event timestamp is unverifiable")
        if record.action in {"MANUALLY_APPROVED", "USER_VETOED"}:
            if (
                isinstance(record.telegram_user_id, bool)
                or not isinstance(record.telegram_user_id, int)
                or record.telegram_user_id <= 0
            ):
                raise LedgerIntegrityError("Human approval events require explicit attribution")
            if record.ts >= alert.expires_at or self.clock.now() >= alert.expires_at:
                raise LedgerIntegrityError("Expired alert cannot receive a human decision")
        if record.action == "EXPIRED" and record.ts < alert.expires_at:
            raise LedgerIntegrityError("Expiry requires the expiry timestamp to have passed")
        if not isinstance(record.reasons, list):
            raise DataIntegrityError("Approval evidence requires a JSON array of findings")
        if record.action == "REVALIDATION_FAILED" and not record.reasons:
            raise LedgerIntegrityError("Revalidation failure requires explicit failure findings")

    def _validate_alert_event(self, session: Session, record: AlertEvent) -> None:
        """GD-05: delivery and terminal state are immutable auditable transitions."""
        alert = session.get(Alert, record.alert_id)
        prior = self._latest_alert_event(session, record.alert_id)
        previous = None if prior is None else prior.state
        if alert is None or record.state not in _ALERT_TRANSITIONS.get(previous, frozenset()):
            raise LedgerIntegrityError("Invalid appended alert lifecycle transition")
        if record.created_at < alert.created_at:
            raise LedgerIntegrityError("Alert event timestamp precedes its parent alert")
        if record.state == "SENT":
            if (
                isinstance(record.telegram_chat_id, bool)
                or not isinstance(record.telegram_chat_id, int)
                or record.telegram_chat_id == 0
                or isinstance(record.telegram_message_id, bool)
                or not isinstance(record.telegram_message_id, int)
                or record.telegram_message_id <= 0
            ):
                raise LedgerIntegrityError("SENT event requires a Telegram chat/message binding")
            if self.clock.now() >= alert.expires_at:
                raise LedgerIntegrityError("Expired candidate cannot become actionable")
            if (
                alert.telegram_chat_id is not None
                and record.telegram_chat_id != alert.telegram_chat_id
            ):
                raise LedgerIntegrityError("Delivery chat does not match its alert destination")
        if record.state in _APPROVAL_STATES.values():
            approval = session.get(ApprovalEvent, record.approval_event_id)
            if (
                approval is None
                or approval.alert_id != record.alert_id
                or _APPROVAL_STATES.get(approval.action) != record.state
            ):
                raise LedgerIntegrityError(
                    "Terminal alert state requires matching approval evidence"
                )
        elif record.approval_event_id is not None:
            raise LedgerIntegrityError("Delivery events cannot carry terminal approval evidence")

    @staticmethod
    def _ticket_matches_proposal(ticket: TradeTicket, order: Order, alert: Alert) -> bool:
        return (
            ticket.symbol == order.symbol
            and ticket.side == order.side
            and ticket.qty == order.qty
            and ticket.limit_price == order.limit_price
            and ticket.stop_price == order.stop_price
            and ticket.target_price == order.target_price
            and ticket.valid_until <= alert.expires_at
        )

    def _validate_ticket(self, session: Session, record: TradeTicket) -> None:
        """R-10/R-14: a single ticket exactly repeats an approved local proposal.

        Authentication and fresh external revalidation belong to the Stage F
        human gate. This writer is a local evidence API, not an authorization API.
        """
        alert = session.get(Alert, record.alert_id)
        if alert is None:
            raise LedgerIntegrityError("Manual ticket has no alert provenance")
        approval = session.scalar(select(ApprovalEvent).where(ApprovalEvent.alert_id == alert.id))
        state = self._latest_alert_event(session, alert.id)
        order = session.scalar(select(Order).where(Order.proposal_id == alert.proposal_id))
        if (
            approval is None
            or approval.action != "MANUALLY_APPROVED"
            or state is None
            or state.state != "APPROVED"
            or order is None
            or not self._ticket_matches_proposal(record, order, alert)
        ):
            raise LedgerIntegrityError("Ticket must exactly bind the manually approved proposal")
        if record.created_at < approval.ts or record.valid_until <= self.clock.now():
            raise LedgerIntegrityError("Manual ticket validity interval is unverifiable")
        if session.scalar(select(TradeTicket).where(TradeTicket.alert_id == alert.id)) is not None:
            raise LedgerIntegrityError("Alert already has its single-use trade ticket")

    def current_alert_status(self, alert_id: UUID) -> str:
        """GD-05: derive current status from history, leaving Alert.status PENDING."""
        self.verify_chain()
        try:
            with transaction(self.engine) as session:
                alert = session.get(Alert, alert_id)
                current = self._latest_alert_event(session, alert_id)
                if alert is None or current is None:
                    raise LedgerIntegrityError("Alert status cannot be resolved")
                if (
                    session.scalar(
                        select(ExecutionOrderRecord)
                        .join(Order)
                        .where(
                            Order.proposal_id == alert.proposal_id,
                            ExecutionOrderRecord.role == "ENTRY",
                        )
                    )
                    is not None
                ):
                    return "AUTO_APPROVED"
                return current.state
        except SafetyError:
            raise
        except Exception as exc:
            raise LedgerIntegrityError("Alert status read failed") from exc

    def alert_is_actionable(self, alert_id: UUID) -> bool:
        """GD-05/R-14: delivery success makes a pending candidate actionable."""
        self.verify_chain()
        with transaction(self.engine) as session:
            alert = session.get(Alert, alert_id)
            current = self._latest_alert_event(session, alert_id)
            if alert is None or current is None:
                raise LedgerIntegrityError("Alert actionability cannot be resolved")
            if (
                session.scalar(
                    select(ExecutionOrderRecord)
                    .join(Order)
                    .where(
                        Order.proposal_id == alert.proposal_id, ExecutionOrderRecord.role == "ENTRY"
                    )
                )
                is not None
            ):
                return False
            return current.state == "SENT" and ensure_utc(self.clock.now()) < alert.expires_at

    def record_trade_ticket(
        self,
        alert_id: UUID,
        *,
        telegram_user_id: int,
        reasons: list[dict[str, Any]],
        valid_until: datetime,
    ) -> TradeTicket:
        """R-10/R-14: atomically persist a revalidated human decision and its ticket.

        This local writer assumes the caller has authenticated the human and
        completed all fresh external checks. It cannot perform those checks or
        issue broker instructions. Concurrent replays fail without partial rows.
        """
        self.verify_chain()
        with transaction(self.engine) as session:
            alert = session.get(Alert, alert_id)
            if alert is None:
                raise LedgerIntegrityError("Manual ticket requires a known alert")
            order = session.scalar(select(Order).where(Order.proposal_id == alert.proposal_id))
            if order is None:
                raise LedgerIntegrityError("Manual ticket requires a local proposal")
            self.append_in_session(
                session,
                ApprovalEvent,
                alert_id=alert.id,
                action="MANUALLY_APPROVED",
                telegram_user_id=telegram_user_id,
                ts=self.clock.now(),
                reasons=reasons,
            )
            return self.append_in_session(
                session,
                TradeTicket,
                alert_id=alert.id,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
                target_price=order.target_price,
                valid_until=valid_until,
            )

    @staticmethod
    def _reject_secret_fields(settings: Any) -> None:
        secret_names = {
            "secret",
            "password",
            "token",
            "api_key",
            "access_token",
            "fernet_key",
            "db_url",
        }
        secret_suffixes = ("_secret", "_password", "_token", "_api_key", "_secret_key")
        if isinstance(settings, Mapping):
            for key, value in settings.items():
                lowered = key.lower()
                if lowered in secret_names or lowered.endswith(secret_suffixes):
                    raise DataIntegrityError("Config snapshots cannot contain secret fields")
                Ledger._reject_secret_fields(value)
        elif isinstance(settings, (tuple, list)):
            for value in settings:
                Ledger._reject_secret_fields(value)

    def _validate_fill(self, session: Session, fill: Fill) -> None:
        order = session.get(Order, fill.order_id)
        if order is None:
            raise LedgerIntegrityError("Observed fill has no local order")
        if (
            session.scalar(
                select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.order_id == fill.order_id,
                )
            )
            is not None
        ):
            raise LedgerIntegrityError("Auto fills require their exact execution instruction")
        latest = session.scalar(
            select(OrderEvent)
            .where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.seq.desc())
            .limit(1)
        )
        if latest is None or latest.state not in {
            "SUBMITTED",
            "PARTIALLY_FILLED",
            "CANCEL_REQUESTED",
        }:
            raise LedgerIntegrityError("Observed fill requires an active submitted order")
        if isinstance(fill.qty, bool) or not isinstance(fill.qty, int) or fill.qty <= 0:
            raise DataIntegrityError("Observed fill requires a positive whole-share quantity")
        if not isinstance(fill.price, Decimal) or fill.price <= 0:
            raise DataIntegrityError("Observed fill requires a positive Decimal price")
        already_filled = sum(
            existing.qty
            for existing in session.scalars(select(Fill).where(Fill.order_id == order.id))
        )
        if already_filled + fill.qty > order.qty:
            raise LedgerIntegrityError("Observed fills exceed the order's whole-share quantity")
        if (order.side == "BUY" and fill.price > order.limit_price) or (
            order.side == "SELL" and fill.price < order.limit_price
        ):
            raise LedgerIntegrityError("Observed fill violates the recorded LIMIT price")
        if ensure_utc(fill.filled_at) > ensure_utc(self.clock.now()):
            raise LedgerIntegrityError("Observed fill timestamp is in the future")

    def _halt(self, reason: str) -> None:
        """R-02: persist a fail-closed control state even after chain corruption."""
        with transaction(self.engine) as session:
            control = session.scalar(
                select(SystemControl).where(SystemControl.id == 1).with_for_update()
            )
            if control is None:
                control = SystemControl(id=1, state="HALTED", version=0)
                session.add(control)
            count = len(list(session.scalars(select(SystemEvent))))
            control.state = "HALTED"
            control.version = count + 1
            self.append_in_session(
                session,
                SystemEvent,
                state="HALTED",
                reason=reason,
                operator_id=None,
                event_type="ESCALATE",
            )
        try:
            self.halt_callback(reason)
        except Exception as exc:
            raise LedgerIntegrityError("HALTED persisted; halt notification failed") from exc

    def verify_chain(self) -> None:
        """R-02: verify every hash, global sequence, FK and state projection.

        A failure persists HALTED before raising a typed error. Database failure
        can prevent persistence; the caller must also keep a process halt latch.
        """
        try:
            with transaction(self.engine) as session:
                self._verify_in_session(session)
        except Exception as exc:
            try:
                self._halt("ledger verification failed")
            except Exception as halt_error:
                raise LedgerIntegrityError(
                    "Ledger verification failed and durable halt could not be confirmed"
                ) from halt_error
            raise LedgerIntegrityError("Ledger verification failed; system is HALTED") from exc

    def _verify_in_session(self, session: Session) -> None:
        sequences: list[int] = []
        all_records: list[LedgerRecord] = []
        system_events: list[SystemEvent] = []
        for model_type in LEDGER_MODELS:
            previous = GENESIS_HASH
            for record in session.scalars(select(model_type).order_by(model_type.seq)):
                self._validate_common(record, verifying=True)
                if (
                    record.seq <= 0
                    or record.prev_hash != previous
                    or record.row_hash != row_digest(record)
                ):
                    raise LedgerIntegrityError(f"Broken hash chain in {model_type.__tablename__}")
                previous = record.row_hash
                sequences.append(record.seq)
                all_records.append(record)
                if isinstance(record, SystemEvent):
                    system_events.append(record)
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            raise LedgerIntegrityError("Global ledger sequences are missing or duplicated")
        allocation = session.get(AppendControl, 1)
        if allocation is None or allocation.next_seq != len(sequences) + 1:
            raise LedgerIntegrityError("Ledger sequence allocation disagrees with recorded rows")
        control = session.get(SystemControl, 1)
        expected_state = system_events[-1].state if system_events else "RUNNING"
        if (
            control is None
            or control.state != expected_state
            or control.version != len(system_events)
        ):
            raise LedgerIntegrityError(
                "Mutable state control disagrees with immutable system events"
            )
        self._verify_relationships(session, all_records)
        self._verify_lifecycle(all_records)
        self._verify_research_lifecycle(all_records)
        previous_state = "RUNNING"
        for event in system_events:
            if event.state not in _STATE_RANK:
                raise LedgerIntegrityError("Unknown system state in ledger")
            if (
                event.event_type != "OPERATOR_RESET"
                and _STATE_RANK[event.state] < _STATE_RANK[previous_state]
            ):
                raise LedgerIntegrityError("Unaudited system-state de-escalation")
            if event.event_type == "OPERATOR_RESET" and not (event.operator_id or "").strip():
                raise LedgerIntegrityError("Operator reset lacks attribution")
            if event.event_type == "INITIALIZED" and (
                event is not system_events[0] or event.state != "RUNNING"
            ):
                raise LedgerIntegrityError("Invalid repeated or nonrunning initialization event")
            previous_state = event.state

    @staticmethod
    def _verify_relationships(session: Session, records: list[LedgerRecord]) -> None:
        for record in records:
            if isinstance(record, SecurityEvent):
                from backend.execution.control_evidence import CONTROL_EVENTS, validate_control

                if record.kind in CONTROL_EVENTS:
                    validate_control(session, record)
            if isinstance(record, (ExecutionOrderRecord, ExecutionFillRecord)) or (
                isinstance(record, SecurityEvent)
                and record.kind
                in {
                    "EXECUTION_ORDER_OBSERVED",
                    "AUTO_ENTRY_APPROVAL",
                    "EXECUTION_SUBMIT_OUTCOME",
                    "AUTO_EXIT_CYCLE",
                    "AUTO_EXIT_APPROVAL",
                    "STOP_RAISE_APPROVAL",
                    "STOP_MOVED",
                    "PAPER_CANCEL_SEMANTICS",
                }
            ):
                from backend.execution.storage import validate_record as validate_execution_record

                validate_execution_record(session, record)
            if isinstance(record, (CashFlow, DailyPnL, TaxEvent)):
                from backend.tax.storage import validate_record

                validate_record(session, record)
            for column in record.__table__.columns:
                value = record.__dict__[column.name]
                if value is None and not column.nullable:
                    raise LedgerIntegrityError("Nonnullable ledger field is missing")
                if value is None:
                    continue
                for foreign_key in column.foreign_keys:
                    target = foreign_key.column
                    parent_seq = session.scalar(select(target.table.c.seq).where(target == value))
                    if parent_seq is None or parent_seq >= record.seq:
                        raise LedgerIntegrityError("Ledger foreign key cannot be resolved")

    def _verify_lifecycle(self, records: list[LedgerRecord]) -> None:
        orders = {record.id: record for record in records if isinstance(record, Order)}
        signals = {record.id: record for record in records if isinstance(record, Signal)}
        executions = {
            record.id: record for record in records if isinstance(record, ExecutionOrderRecord)
        }
        execution_quantities: dict[UUID, int] = {}
        for execution in executions.values():
            if execution.role == "ENTRY":
                execution_quantities[execution.order_id] = (
                    execution_quantities.get(execution.order_id, 0) + execution.qty
                )
        for original_order in orders.values():
            signal = signals.get(original_order.signal_id)
            if (
                signal is None
                or signal.symbol != original_order.symbol
                or signal.direction != original_order.side
            ):
                raise LedgerIntegrityError("Order does not resolve to a matching signal")
            if signal.signal_type != original_order.source:
                raise LedgerIntegrityError("Order source and signal type disagree")
        states: dict[UUID, str] = {}
        totals: dict[UUID, int] = {}
        for record in sorted(records, key=lambda row: row.seq):
            if isinstance(record, ExecutionFillRecord):
                instruction = executions.get(record.execution_order_id)
                if instruction is None:
                    raise LedgerIntegrityError("Auto fill instruction cannot be resolved")
                if instruction.role == "ENTRY":
                    if states.get(instruction.order_id) not in {
                        "SUBMITTED",
                        "PARTIALLY_FILLED",
                        "CANCEL_REQUESTED",
                    }:
                        raise LedgerIntegrityError("Auto fill was recorded outside an active entry")
                    totals[instruction.order_id] = totals.get(instruction.order_id, 0) + record.qty
            if isinstance(record, Fill):
                if record.order_id in execution_quantities:
                    raise LedgerIntegrityError(
                        "Legacy fill cannot overwrite an auto execution instruction"
                    )
                order = orders.get(record.order_id)
                if order is None or states.get(record.order_id) not in {
                    "SUBMITTED",
                    "PARTIALLY_FILLED",
                    "CANCEL_REQUESTED",
                }:
                    raise LedgerIntegrityError("Fill was recorded outside an active order")
                totals[record.order_id] = totals.get(record.order_id, 0) + record.qty
                if record.qty <= 0 or totals[record.order_id] > order.qty:
                    raise LedgerIntegrityError("Invalid cumulative fill quantity")
                if (
                    record.price <= 0
                    or (order.side == "BUY" and record.price > order.limit_price)
                    or (order.side == "SELL" and record.price < order.limit_price)
                ):
                    raise LedgerIntegrityError("Fill price violates the recorded LIMIT order")
                if ensure_utc(record.filled_at) > ensure_utc(self.clock.now()):
                    raise LedgerIntegrityError("Observed fill timestamp is in the future")
            if isinstance(record, OrderEvent):
                if not _valid_transition(states.get(record.order_id), record.state):
                    raise LedgerIntegrityError("Raw order-event lifecycle is invalid")
                order = orders.get(record.order_id)
                if order is None:
                    raise LedgerIntegrityError("Order event has no matching order")
                expected_qty = execution_quantities.get(record.order_id, order.qty)
                if record.state == "FILLED" and totals.get(record.order_id, 0) != expected_qty:
                    raise LedgerIntegrityError(
                        "FILLED lifecycle does not match observed fill quantity"
                    )
                if (
                    record.state == "PARTIALLY_FILLED"
                    and not 0 < totals.get(record.order_id, 0) < expected_qty
                ):
                    raise LedgerIntegrityError(
                        "Partial lifecycle does not match observed fill quantity"
                    )
                states[record.order_id] = record.state
        if set(orders) != set(states):
            raise LedgerIntegrityError("Every order requires its initial PROPOSED event")

    def _verify_research_lifecycle(self, records: list[LedgerRecord]) -> None:
        """GD-01/GD-03/GD-05/R-14: replay immutable evidence in global sequence order.

        Hash-valid raw SQL rows cannot bypass delivery, attribution, expiry,
        single use or exact proposal-to-ticket provenance.
        """
        orders = {record.proposal_id: record for record in records if isinstance(record, Order)}
        alerts = {record.id: record for record in records if isinstance(record, Alert)}
        approvals = {record.id: record for record in records if isinstance(record, ApprovalEvent)}
        states: dict[UUID, str] = {}
        decisions: dict[UUID, ApprovalEvent] = {}
        ticket_alerts: set[UUID] = set()
        event_approvals: set[UUID] = set()
        tickets: dict[UUID, TradeTicket] = {}
        ticket_followups: set[UUID] = set()
        for record in sorted(records, key=lambda row: row.seq):
            if isinstance(record, TicketEvent):
                ticket = tickets.get(record.ticket_id)
                if (
                    ticket is None
                    or record.ticket_id in ticket_followups
                    or record.action not in {"TICKET_PLACED", "TICKET_SKIPPED"}
                    or type(record.telegram_user_id) is not int
                    or record.telegram_user_id <= 0
                    or record.created_at < ticket.created_at
                ):
                    raise LedgerIntegrityError("GD-06: forged/replayed ticket follow-up")
                ticket_followups.add(record.ticket_id)
            if isinstance(record, TradeTicket):
                tickets[record.id] = record
            if isinstance(record, Alert):
                order = orders.get(record.proposal_id)
                if (
                    order is None
                    or order.signal_id != record.signal_id
                    or order.symbol != record.symbol
                    or record.status != "PENDING"
                    or not Decimal(1) <= record.score <= Decimal(10)
                    or record.expires_at <= record.created_at
                    or record.telegram_message_id is not None
                ):
                    raise LedgerIntegrityError(
                        "Alert proposal provenance or immutable shape is invalid"
                    )
            if isinstance(record, ResearchReport):
                alert = alerts.get(record.alert_id)
                if (
                    alert is None
                    or record.created_at < alert.created_at
                    or record.status not in {"OK", "UNAVAILABLE", "ERROR"}
                ):
                    raise LedgerIntegrityError("Research outcome lacks valid alert provenance")
            if isinstance(record, ApprovalEvent):
                alert = alerts.get(record.alert_id)
                target = _APPROVAL_STATES.get(record.action)
                if (
                    alert is None
                    or target
                    not in _ALERT_TRANSITIONS.get(states.get(record.alert_id), frozenset())
                    or record.alert_id in decisions
                    or record.ts < alert.created_at
                    or record.ts > record.created_at
                    or not isinstance(record.reasons, list)
                ):
                    raise LedgerIntegrityError("Approval event is forged, replayed or unverifiable")
                if record.action in {"MANUALLY_APPROVED", "USER_VETOED"} and (
                    record.telegram_user_id is None
                    or record.telegram_user_id <= 0
                    or record.ts >= alert.expires_at
                ):
                    raise LedgerIntegrityError("Human decision is unattributed or expired")
                if record.action == "EXPIRED" and record.ts < alert.expires_at:
                    raise LedgerIntegrityError("Alert was expired before its validity ended")
                if record.action == "REVALIDATION_FAILED" and not record.reasons:
                    raise LedgerIntegrityError("Revalidation failure has no recorded findings")
                decisions[record.alert_id] = record
            if isinstance(record, AlertEvent):
                alert = alerts.get(record.alert_id)
                if (
                    alert is None
                    or record.state
                    not in _ALERT_TRANSITIONS.get(states.get(record.alert_id), frozenset())
                    or record.created_at < alert.created_at
                ):
                    raise LedgerIntegrityError("Raw alert lifecycle transition is invalid")
                if record.state == "SENT" and (
                    record.telegram_chat_id is None
                    or record.telegram_chat_id == 0
                    or record.telegram_message_id is None
                    or record.telegram_message_id <= 0
                    or record.created_at >= alert.expires_at
                    or (
                        alert.telegram_chat_id is not None
                        and record.telegram_chat_id != alert.telegram_chat_id
                    )
                ):
                    raise LedgerIntegrityError(
                        "Alert delivery binding or delivery expiry is invalid"
                    )
                if record.state in _APPROVAL_STATES.values():
                    approval = (
                        None
                        if record.approval_event_id is None
                        else approvals.get(record.approval_event_id)
                    )
                    if (
                        approval is None
                        or approval.alert_id != record.alert_id
                        or _APPROVAL_STATES.get(approval.action) != record.state
                        or approval.id in event_approvals
                        or approval.seq >= record.seq
                    ):
                        raise LedgerIntegrityError(
                            "Terminal alert state lacks exact approval evidence"
                        )
                    event_approvals.add(approval.id)
                elif record.approval_event_id is not None:
                    raise LedgerIntegrityError(
                        "Nonterminal delivery event carries approval evidence"
                    )
                states[record.alert_id] = record.state
            if isinstance(record, TradeTicket):
                alert = alerts.get(record.alert_id)
                approval = decisions.get(record.alert_id)
                order = None if alert is None else orders.get(alert.proposal_id)
                if (
                    alert is None
                    or approval is None
                    or approval.action != "MANUALLY_APPROVED"
                    or states.get(record.alert_id) != "APPROVED"
                    or record.alert_id in ticket_alerts
                    or order is None
                    or not self._ticket_matches_proposal(record, order, alert)
                    or record.valid_until <= record.created_at
                    or record.created_at < approval.ts
                    or record.ticket_sha256 != ticket_digest(record)
                ):
                    raise LedgerIntegrityError(
                        "Trade ticket is forged, replayed or loses provenance"
                    )
                ticket_alerts.add(record.alert_id)
        if set(alerts) != set(states):
            raise LedgerIntegrityError("Every alert requires its immutable PENDING lifecycle event")
        if set(approvals) != event_approvals:
            raise LedgerIntegrityError(
                "Every approval event requires exactly one terminal projection"
            )
        approved_alerts = {
            alert_id
            for alert_id, decision in decisions.items()
            if decision.action == "MANUALLY_APPROVED"
        }
        if approved_alerts != ticket_alerts:
            raise LedgerIntegrityError(
                "Every manual approval requires exactly one atomic trade ticket"
            )

    @overload
    def record_fill(
        self,
        order_id: UUID,
        *,
        broker_fill_id: str,
        qty: int,
        price: Decimal,
        filled_at: datetime,
        session: Session | None = None,
        execution_order_id: None = None,
    ) -> Fill: ...

    @overload
    def record_fill(
        self,
        order_id: UUID,
        *,
        broker_fill_id: str,
        qty: int,
        price: Decimal,
        filled_at: datetime,
        session: Session | None = None,
        execution_order_id: UUID,
    ) -> ExecutionFillRecord: ...

    def record_fill(
        self,
        order_id: UUID,
        *,
        broker_fill_id: str,
        qty: int,
        price: Decimal,
        filled_at: datetime,
        session: Session | None = None,
        execution_order_id: UUID | None = None,
    ) -> Fill | ExecutionFillRecord:
        """R-08: record a broker-observed fill locally; mismatch latches HALTED."""
        try:
            if execution_order_id is not None:
                if session is None:
                    with transaction(self.engine) as owned:
                        return self.record_fill(
                            order_id,
                            broker_fill_id=broker_fill_id,
                            qty=qty,
                            price=price,
                            filled_at=filled_at,
                            session=owned,
                            execution_order_id=execution_order_id,
                        )
                instruction = session.get(ExecutionOrderRecord, execution_order_id)
                if instruction is None or instruction.order_id != order_id:
                    raise LedgerIntegrityError("Fill execution binding differs from its proposal")
                return self.append_in_session(
                    session,
                    ExecutionFillRecord,
                    execution_order_id=execution_order_id,
                    broker_fill_id=broker_fill_id,
                    qty=qty,
                    price=price,
                    filled_at=filled_at,
                )
            if session is not None:
                # The owner of the serialized transaction rolls back and halts
                # on failure; a nested writer cannot safely perform that halt.
                return self.append_in_session(
                    session,
                    Fill,
                    order_id=order_id,
                    broker_fill_id=broker_fill_id,
                    qty=qty,
                    price=price,
                    filled_at=filled_at,
                )
            return self.append(
                Fill,
                order_id=order_id,
                broker_fill_id=broker_fill_id,
                qty=qty,
                price=price,
                filled_at=filled_at,
            )
        except Exception as exc:
            if session is not None:
                raise ReconciliationError(
                    "Observed fill rejected; owning transaction must halt"
                ) from exc
            try:
                self._halt("observed fill could not be reconciled")
            except Exception as halt_error:
                raise ReconciliationError(
                    "Fill failed and durable halt is unconfirmed"
                ) from halt_error
            raise ReconciliationError("Observed fill rejected; system is HALTED") from exc

    def reconcile(
        self, broker_positions: Mapping[str, int], ledger_positions: Mapping[str, int]
    ) -> None:
        """R-01/R-02/R-08: compare complete long-only whole-share inventories."""
        try:
            for positions in (broker_positions, ledger_positions):
                for symbol, qty in positions.items():
                    if not symbol or isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
                        raise ReconciliationError("Unverifiable long-only position inventory")
            broker = {symbol: qty for symbol, qty in broker_positions.items() if qty != 0}
            local = {symbol: qty for symbol, qty in ledger_positions.items() if qty != 0}
            if broker != local:
                raise ReconciliationError("Broker and ledger positions disagree")
        except Exception as exc:
            try:
                self._halt("broker/ledger reconciliation failed")
            except Exception as halt_error:
                raise ReconciliationError(
                    "Reconciliation failed and durable halt is unconfirmed"
                ) from halt_error
            raise ReconciliationError("Reconciliation failed; system is HALTED") from exc

    def record_cash_flow(
        self, account_id: str, amount: Decimal, ts: datetime, equity_before: Decimal
    ) -> PortfolioState:
        """CRO-09/CRO-10/R-08: record observed external cash flow, never move money.

        Both drawdown baselines scale by equity_after/equity_before. Repeating
        decimal results round upward to a micro-unit, conservatively preserving
        loss sensitivity. Deposits never become settled cash until broker proof;
        withdrawals reduce settled cash, with a zero floor. Account attribution,
        an exact previous equity, and positive marked equity are mandatory.
        """
        try:
            with transaction(self.engine) as session:
                return self.record_cash_flow_in_session(
                    session, account_id, amount, ts, equity_before
                )
        except Exception as exc:
            try:
                self._halt("observed external cash flow could not be reconciled")
            except Exception as halt_error:
                raise ReconciliationError(
                    "Cash flow failed and durable halt is unconfirmed"
                ) from halt_error
            raise ReconciliationError("Cash flow rejected; system is HALTED") from exc

    def record_cash_flow_in_session(
        self,
        session: Session,
        account_id: str,
        amount: Decimal,
        ts: datetime,
        equity_before: Decimal,
    ) -> PortfolioState:
        """FN-03: same CRO-09 operation in the activity deduplication transaction.

        The caller must roll back first and persist HALT on any reconciliation fault.
        """
        bind = session.get_bind()
        if (
            not isinstance(bind, Connection)
            or bind.engine is not self.engine
            or not bind.in_transaction()
        ):
            raise ReconciliationError("Cash flow requires the bound serialized transaction")
        if not isinstance(amount, Decimal) or not isinstance(equity_before, Decimal):
            raise DataIntegrityError("Cash flow requires exact Decimal inputs")
        money_to_scaled(amount)
        money_to_scaled(equity_before)
        instant = ensure_utc(ts)
        if instant > ensure_utc(self.clock.now()):
            raise ReconciliationError("Cash flow timestamp is in the future")
        prior = session.scalar(
            select(PortfolioState)
            .where(PortfolioState.account_id == account_id)
            .order_by(PortfolioState.seq.desc())
            .limit(1)
        )
        if prior is None or equity_before <= 0 or prior.equity != equity_before:
            raise ReconciliationError("Cash flow cannot resolve its prior managed-account equity")
        if instant < prior.as_of or prior.high_water_mark <= 0 or prior.day_start_equity <= 0:
            raise ReconciliationError("Cash flow cannot verify its timestamp or loss baselines")
        with localcontext() as context:
            context.prec = 80
            equity_after = equity_before + amount
            cash_after = prior.cash + amount
            if equity_after <= 0 or cash_after < 0:
                raise ReconciliationError(
                    "Cash flow would make equity nonpositive or require borrowing"
                )
            quantum = Decimal("0.000001")
            high_water = (prior.high_water_mark * equity_after / equity_before).quantize(
                quantum, rounding=ROUND_CEILING
            )
            day_start = (prior.day_start_equity * equity_after / equity_before).quantize(
                quantum, rounding=ROUND_CEILING
            )
        settled = max(Decimal(0), prior.settled_cash + min(Decimal(0), amount))
        return self.append_in_session(
            session,
            PortfolioState,
            account_id=account_id,
            account_type=prior.account_type,
            as_of=instant,
            equity=equity_after,
            cash=cash_after,
            settled_cash=settled,
            positions=prior.positions,
            high_water_mark=high_water,
            day_start_equity=day_start,
            cash_flow_amount=amount,
            cash_flow_at=instant,
        )
