"""XK-02: idempotent append-only journal projection; notes never enter research."""

import csv
import io
import json
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
from typing import Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.fundamentals import FrameworkStatus, FundamentalReport
from backend.core.database import (
    Alert,
    AlertEvent,
    ComplianceCheck,
    ExecutionFillRecord,
    ExecutionOrderRecord,
    Fill,
    Order,
    ResearchReport,
    RiskDecision,
    RiskRuleResult,
    SecurityEvent,
    Signal,
    TaxEvent,
    transaction,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.money import decimal_money
from backend.data.data_layer import _provider_money
from backend.domain.models import FrozenModel, PositiveQty, SetupCandidate, UTCDateTime
from backend.ops.trading_controls import ControlScope
from backend.tax.models import TaxFill

WHY = {
    "CRO-01": "New entries need a running account",
    "CRO-02": "Instrument, position and stop evidence must be valid",
    "CRO-03": "Single-position weight exceeds its cap",
    "CRO-04": "Reserved stop risk plus slippage exceeds the trade-risk cap",
    "CRO-05": "Sector or theme concentration exceeds its cap",
    "CRO-06": "Gross exposure, position count or the cash buffer exceeds its limit",
    "CRO-07": "The limit price or quote freshness is outside its limit",
    "CRO-08": "Trade notional exceeds the average-volume cap",
    "CRO-09": "Drawdown requires reduced exposure or a halt",
    "CRO-10": "The daily loss limit blocks entries for this session",
    "CRO-11": "An event blackout blocks a new entry",
    "CRO-12": "Checking-buffer and funding evidence must be available",
    "CRO-13": "Earnings are inside the configured blackout",
    "CRO-14": "Total held, pending and new stop risk exceeds the portfolio cap",
    "CMP-01": "A recent loss sale can create a forward wash-sale risk",
    "CMP-02": "A potential wash sale needs review",
    "CMP-03": "Sale proceeds have not settled",
    "CMP-04": "Borrowing or leverage is unavailable",
    "CMP-05": "The day-trade limit blocks another opening trade",
    "CMP-06": "The broker account is restricted",
    "CMP-07": "This instrument is restricted",
}


class JournalRule(FrozenModel):
    rule_id: str = Field(strict=True, pattern=r"^(CRO|CMP)-[0-9]{2}$")
    passed: bool = Field(strict=True)
    severity: Literal["BLOCK", "WARN"]
    observed: str = Field(strict=True, max_length=4096)
    limit: str = Field(strict=True, max_length=4096)
    message: str = Field(strict=True, min_length=1, max_length=4000)


class JournalEntry(FrozenModel):
    trigger: Literal["ALERT", "ENTRY", "EXIT", "VETO", "OUTCOME"]
    source_id: UUID
    proposal_id: UUID
    alert_id: UUID | None
    scope: ControlScope
    created_at: UTCDateTime
    setup: SetupCandidate
    qty: PositiveQty
    framework_status: FrameworkStatus
    fundamentals_json: str | None = Field(default=None, strict=True, max_length=65536)
    news_ids: tuple[str, ...] = Field(default=(), max_length=100)
    cro: tuple[JournalRule, ...] = Field(max_length=14)
    compliance: tuple[JournalRule, ...] = Field(max_length=7)
    outcome_json: str | None = Field(default=None, strict=True, max_length=65536)

    @model_validator(mode="after")
    def bound(self) -> "JournalEntry":
        if (
            self.created_at < self.setup.as_of
            or any(
                not isinstance(value, str) or not 1 <= len(value) <= 256 for value in self.news_ids
            )
            or len(set(self.news_ids)) != len(self.news_ids)
        ):
            raise ValueError("XK-02: bounded unique news and chronological setup evidence required")
        if self.fundamentals_json is None and self.framework_status != FrameworkStatus.INCOMPLETE:
            raise ValueError("XK-02: missing fundamentals cannot become a pass")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, object]) -> "JournalEntry":
        try:
            raw = dict(payload)
            raw["created_at"] = datetime.fromisoformat(str(raw["created_at"]))
            setup = raw["setup"]
            if not isinstance(setup, dict):
                raise ValueError("missing setup")
            raw["setup"] = _recorded_setup(setup)
            return cls.model_validate(raw)
        except Exception:
            raise DataIntegrityError("XK-02: recorded journal evidence is unverifiable") from None


class UnassignedExit(FrozenModel):
    """An external manual sale has no invented Project V setup or risk approval."""

    scope: ControlScope
    fill: TaxFill
    context_status: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    reason: Literal[
        "Physical sale has no recorded Project V proposal; setup, criteria, fundamentals, news and CRO evidence are unavailable."
    ] = "Physical sale has no recorded Project V proposal; setup, criteria, fundamentals, news and CRO evidence are unavailable."

    @model_validator(mode="after")
    def bound(self) -> "UnassignedExit":
        if (
            self.fill.side.value != "SELL"
            or self.fill.account_id != self.scope.account_id
            or self.fill.env != self.scope.environment
        ):
            raise ValueError("XK-02: unassigned sale must bind to this account and environment")
        return self


def why_not(symbol: str, rule: JournalRule) -> str:
    checked = JournalRule.model_validate(rule)
    if checked.rule_id not in WHY:
        raise DataIntegrityError("XK-02: unknown rule has no approved explanation")
    return f"Skipped {symbol}: {WHY[checked.rule_id]}. {checked.message}"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _recorded_setup(payload: dict[str, object]) -> SetupCandidate:
    values = dict(payload)
    values["as_of"] = datetime.fromisoformat(str(values["as_of"]))
    for name in ("entry_price", "stop_price", "target_price"):
        values[name] = _provider_money(values[name])
    values["score"] = _recorded_money(values["score"])
    criteria = values["criteria"]
    if not isinstance(criteria, list):
        raise DataIntegrityError("XK-02: recorded criteria must be a bounded serialized list")
    decoded = tuple(
        {**row, "points": _recorded_money(row["points"])}
        for row in criteria
        if isinstance(row, dict)
    )
    if len(decoded) != len(criteria):
        raise DataIntegrityError("XK-02: malformed criteria cannot be omitted")
    values["criteria"] = decoded
    return SetupCandidate.model_validate(values)


def _recorded_money(value: object) -> Decimal:
    if not isinstance(value, (Decimal, str, int)):
        raise DataIntegrityError("XK-02: exact recorded score/points required")
    return decimal_money(value)


class Journal:
    def __init__(self, ledger: Ledger, scope: ControlScope) -> None:
        self.ledger, self.scope = ledger, ControlScope.model_validate(scope)

    def _entries(self, session: Session) -> tuple[JournalEntry, ...]:
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "TRADE_JOURNAL")
                .order_by(SecurityEvent.seq)
                .limit(100001)
            )
        )
        if len(rows) > 100000:
            raise DataIntegrityError("XK-02: journal exceeds its bound")
        return tuple(JournalEntry.recorded(row.detail) for row in rows)

    def entries(self) -> tuple[JournalEntry, ...]:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            rows = self._entries(session)
        if any(row.created_at > self.ledger.clock.now() for row in rows):
            raise DataIntegrityError("XK-02: journal contains future evidence")
        return tuple(row for row in rows if row.scope == self.scope)

    def _build(
        self,
        session: Session,
        order: Order,
        source_id: UUID,
        trigger: str,
        instant: datetime,
        cutoff: int,
    ) -> JournalEntry:
        signal = session.get(Signal, order.signal_id)
        if signal is None or signal.agent_name != "SetupHunter":
            raise DataIntegrityError(
                "XK-02: journal requires immutable deterministic setup evidence"
            )
        setup = _recorded_setup(signal.structured_thesis["setup"])
        quantity = order.qty
        if trigger == "ENTRY":
            instruction = session.get(ExecutionOrderRecord, source_id)
            if (
                instruction is None
                or instruction.account_id != self.scope.account_id
                or instruction.environment != self.scope.environment
            ):
                raise DataIntegrityError("XK-02: automatic journal entry has no bound intent")
            quantity = instruction.qty
        elif trigger == "EXIT":
            physical = session.get(ExecutionFillRecord, source_id)
            manual = session.get(Fill, source_id)
            if (physical is None) == (manual is None):
                raise DataIntegrityError("XK-02: exit journal requires exactly one physical fill")
            quantity = (
                physical.qty if physical is not None else manual.qty if manual is not None else 0
            )
        alert = session.scalar(select(Alert).where(Alert.proposal_id == order.proposal_id))
        decision = session.scalar(
            select(RiskDecision)
            .where(RiskDecision.proposal_id == order.proposal_id, RiskDecision.seq <= cutoff)
            .order_by(RiskDecision.seq.desc())
            .limit(1)
        )
        cro = (
            ()
            if decision is None
            else tuple(
                session.scalars(
                    select(RiskRuleResult)
                    .where(RiskRuleResult.risk_decision_id == decision.id)
                    .order_by(RiskRuleResult.seq)
                )
            )
        )
        compliance = tuple(
            session.scalars(
                select(ComplianceCheck)
                .where(
                    ComplianceCheck.proposal_id == order.proposal_id, ComplianceCheck.seq <= cutoff
                )
                .order_by(ComplianceCheck.seq)
            )
        )
        checks = {row.rule_id: row for row in compliance}
        fundamental = (
            None
            if alert is None
            else session.scalar(
                select(ResearchReport)
                .where(
                    ResearchReport.alert_id == alert.id,
                    ResearchReport.agent_name == "fundamentals",
                    ResearchReport.seq <= cutoff,
                )
                .order_by(ResearchReport.seq.desc())
                .limit(1)
            )
        )
        report = (
            None if fundamental is None else FundamentalReport.from_recorded(fundamental.payload)
        )
        news = (
            None
            if alert is None
            else session.scalar(
                select(ResearchReport)
                .where(
                    ResearchReport.alert_id == alert.id,
                    ResearchReport.agent_name == "news",
                    ResearchReport.seq <= cutoff,
                )
                .order_by(ResearchReport.seq.desc())
                .limit(1)
            )
        )

        def rule(row: RiskRuleResult | ComplianceCheck) -> JournalRule:
            return JournalRule.model_validate(
                {
                    "rule_id": row.rule_id,
                    "passed": row.passed == 1,
                    "severity": row.severity,
                    "observed": _json(row.observed),
                    "limit": _json(row.limit),
                    "message": row.message,
                }
            )

        return JournalEntry.model_validate(
            {
                "trigger": trigger,
                "source_id": source_id,
                "proposal_id": order.proposal_id,
                "alert_id": None if alert is None else alert.id,
                "scope": self.scope,
                "created_at": instant,
                "setup": setup,
                "qty": quantity,
                "framework_status": FrameworkStatus.INCOMPLETE
                if report is None
                else report.framework_status,
                "fundamentals_json": None if report is None else report.model_dump_json(),
                "news_ids": ()
                if news is None
                else tuple(row["stable_id"] for row in news.payload["news"]["headlines"]),
                "cro": tuple(rule(row) for row in cro),
                "compliance": tuple(rule(checks[name]) for name in sorted(checks)),
            }
        )

    def sync(self) -> int:
        self.ledger.verify_chain()
        try:
            with transaction(self.ledger.engine) as session:
                self.ledger._verify_in_session(session)
                known: set[tuple[str, UUID]] = {
                    (row.trigger, row.source_id) for row in self._entries(session)
                }
                orders = tuple(
                    session.scalars(
                        select(Order)
                        .where(Order.account_id == self.scope.account_id)
                        .order_by(Order.seq)
                        .limit(100001)
                    )
                )
                if len(orders) > 100000:
                    raise ValueError("unbounded proposals")
                added = 0
                for order in orders:
                    signal = session.get(Signal, order.signal_id)
                    if signal is None or signal.agent_name != "SetupHunter":
                        continue
                    if (
                        signal.structured_thesis["evaluation_provenance"]["cohort"]
                        != self.scope.environment
                    ):
                        continue
                    sources: list[tuple[int, UUID, str, datetime]] = []
                    alert = session.scalar(
                        select(Alert).where(Alert.proposal_id == order.proposal_id)
                    )
                    if alert is not None:
                        # Bind facts published after the alert, before its delivery.
                        last_fact = (
                            session.scalar(
                                select(ResearchReport.seq)
                                .where(
                                    ResearchReport.alert_id == alert.id,
                                    ResearchReport.agent_name == "desk_policy",
                                )
                                .order_by(ResearchReport.seq.desc())
                                .limit(1)
                            )
                            or alert.seq
                        )
                        sources.append((last_fact, alert.id, "ALERT", alert.created_at))
                    for veto in session.scalars(
                        select(RiskDecision).where(
                            RiskDecision.proposal_id == order.proposal_id,
                            RiskDecision.decision == "VETOED",
                        )
                    ):
                        sources.append((veto.seq, veto.id, "VETO", veto.created_at))
                    for check in session.scalars(
                        select(ComplianceCheck).where(
                            ComplianceCheck.proposal_id == order.proposal_id,
                            ComplianceCheck.passed == 0,
                            ComplianceCheck.severity == "BLOCK",
                        )
                    ):
                        sources.append((check.seq, check.id, "VETO", check.created_at))
                    for instruction in session.scalars(
                        select(ExecutionOrderRecord).where(
                            ExecutionOrderRecord.order_id == order.id,
                            ExecutionOrderRecord.role == "ENTRY",
                        )
                    ):
                        sources.append(
                            (instruction.seq, instruction.id, "ENTRY", instruction.created_at)
                        )
                    for fill in session.scalars(
                        select(Fill)
                        .join(Order, Fill.order_id == Order.id)
                        .where(Fill.order_id == order.id, Order.side == "SELL")
                    ):
                        sources.append((fill.seq, fill.id, "EXIT", fill.created_at))
                    for execution_fill in session.scalars(
                        select(ExecutionFillRecord)
                        .join(
                            ExecutionOrderRecord,
                            ExecutionFillRecord.execution_order_id == ExecutionOrderRecord.id,
                        )
                        .where(
                            ExecutionOrderRecord.parent_execution_id.in_(
                                select(ExecutionOrderRecord.id).where(
                                    ExecutionOrderRecord.order_id == order.id
                                )
                            ),
                            ExecutionOrderRecord.side == "SELL",
                        )
                    ):
                        sources.append(
                            (
                                execution_fill.seq,
                                execution_fill.id,
                                "EXIT",
                                execution_fill.created_at,
                            )
                        )
                    for cutoff, identity, trigger, instant in sorted(sources):
                        if (trigger, identity) in known:
                            continue
                        entry = self._build(session, order, identity, trigger, instant, cutoff)
                        self.ledger.append_in_session(
                            session,
                            SecurityEvent,
                            kind="TRADE_JOURNAL",
                            detail=entry.model_dump(mode="json"),
                        )
                        known.add((trigger, identity))
                        added += 1
                physical = tuple(
                    session.scalars(
                        select(TaxEvent)
                        .where(
                            TaxEvent.account_id == self.scope.account_id,
                            TaxEvent.env == self.scope.environment,
                            TaxEvent.kind == "FILL",
                        )
                        .order_by(TaxEvent.seq)
                        .limit(100001)
                    )
                )
                external = tuple(
                    session.scalars(
                        select(SecurityEvent)
                        .where(SecurityEvent.kind == "JOURNAL_UNASSIGNED_EXIT")
                        .order_by(SecurityEvent.seq)
                        .limit(100001)
                    )
                )
                if len(physical) > 100000 or len(external) > 100000:
                    raise DataIntegrityError("XK-02: external sale evidence exceeds its bound")
                seen_sales = {
                    (
                        TaxFill.from_payload(row.detail["fill"]).activity_id,
                        TaxFill.from_payload(row.detail["fill"]).payload_sha256,
                    )
                    for row in external
                    if ControlScope.model_validate(row.detail["scope"]) == self.scope
                }
                known_broker_sales = set(
                    session.scalars(
                        select(ExecutionFillRecord.broker_fill_id)
                        .join(
                            ExecutionOrderRecord,
                            ExecutionFillRecord.execution_order_id == ExecutionOrderRecord.id,
                        )
                        .where(
                            ExecutionOrderRecord.account_id == self.scope.account_id,
                            ExecutionOrderRecord.environment == self.scope.environment,
                        )
                    )
                )
                known_broker_sales.update(
                    session.scalars(
                        select(Fill.broker_fill_id)
                        .join(Order, Fill.order_id == Order.id)
                        .where(Order.account_id == self.scope.account_id)
                    )
                )
                superseded = set(
                    session.scalars(
                        select(TaxEvent.supersedes).where(TaxEvent.supersedes.is_not(None))
                    )
                )
                for record in physical:
                    tax_fill = TaxFill.from_payload(record.payload)
                    sale_key = (tax_fill.activity_id, tax_fill.payload_sha256)
                    if (
                        record.id in superseded
                        or tax_fill.side.value != "SELL"
                        or sale_key in seen_sales
                        or tax_fill.activity_id in known_broker_sales
                    ):
                        continue
                    if tax_fill.ts > self.ledger.clock.now():
                        raise DataIntegrityError("XK-02: physical sale is future")
                    unassigned = UnassignedExit(scope=self.scope, fill=tax_fill)
                    self.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="JOURNAL_UNASSIGNED_EXIT",
                        detail=unassigned.model_dump(mode="json"),
                    )
                    seen_sales.add(sale_key)
                    added += 1
                return added
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError(
                "XK-02: journal projection failed; no invented evidence"
            ) from None

    def note(
        self, *, user_id: int, chat_id: int, message_id: int, text: str, allowed: tuple[int, ...]
    ) -> UUID:
        if (
            type(user_id) is not int
            or user_id not in allowed
            or chat_id != user_id
            or type(message_id) is not int
            or message_id <= 0
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > 1000
        ):
            raise DataIntegrityError(
                "XK-02: private allowlisted reply and at most 1000 characters required"
            )
        self.ledger.verify_chain()
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            delivery = session.scalar(
                select(AlertEvent).where(
                    AlertEvent.telegram_chat_id == chat_id,
                    AlertEvent.telegram_message_id == message_id,
                    AlertEvent.state == "SENT",
                )
            )
            binding = None
            # FYI bindings are looked up by exact private message identities.
            if delivery is None:
                rows = tuple(
                    session.scalars(
                        select(SecurityEvent)
                        .where(SecurityEvent.kind == "TRADE_FYI_BINDING")
                        .order_by(SecurityEvent.seq.desc())
                        .limit(100001)
                    )
                )
                if len(rows) > 100000:
                    raise DataIntegrityError("XK-02: message bindings exceed their bound")
                binding = next(
                    (
                        row
                        for row in rows
                        if row.detail["chat_id"] == chat_id
                        and row.detail["message_id"] == message_id
                    ),
                    None,
                )
            alert_id = (
                delivery.alert_id
                if delivery is not None
                else None
                if binding is None
                else UUID(binding.detail["alert_id"])
            )
            alert = None if alert_id is None else session.get(Alert, alert_id)
            order = (
                None
                if alert is None
                else session.scalar(select(Order).where(Order.proposal_id == alert.proposal_id))
            )
            if order is None or order.account_id != self.scope.account_id:
                raise DataIntegrityError(
                    "XK-02: reply is not bound to this account's card or trade FYI"
                )
            signal = session.get(Signal, order.signal_id)
            if (
                signal is None
                or signal.structured_thesis["evaluation_provenance"]["cohort"]
                != self.scope.environment
            ):
                raise DataIntegrityError(
                    "XK-02: reply note belongs to a different paper/live cohort"
                )
            row = self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="JOURNAL_NOTE",
                telegram_user_id=user_id,
                detail={
                    "alert_id": str(alert_id),
                    "scope": self.scope.model_dump(mode="json"),
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": escape(text),
                    "untrusted": True,
                },
            )
            return row.id

    def resolve(self) -> int:
        """Append G outcomes including CRO shadows; never relabel them physical fills."""
        from hashlib import sha256

        from backend.evaluation.ledger_inputs import SHADOW_NAMESPACE
        from backend.ops.k_runtime import tracker_outcomes

        self.sync()
        outcomes = tracker_outcomes(self.ledger, self.scope)
        added = 0
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            recorded = self._entries(session)
            known = {(row.trigger, row.source_id) for row in recorded}
            orders = tuple(
                session.scalars(
                    select(Order).where(Order.account_id == self.scope.account_id).limit(100001)
                )
            )
            if len(orders) > 100000:
                raise DataIntegrityError("XK-02: outcome proposal history exceeds its bound")
            for outcome in outcomes:
                if outcome.status != "RESOLVED":
                    continue
                payload = outcome.model_dump_json()
                identity = uuid5(SHADOW_NAMESPACE, sha256(payload.encode()).hexdigest())
                if ("OUTCOME", identity) in known:
                    continue
                alert = session.get(Alert, outcome.setup.alert_id)
                order = next(
                    (
                        row
                        for row in orders
                        if (alert is not None and row.proposal_id == alert.proposal_id)
                        or uuid5(SHADOW_NAMESPACE, row.proposal_id.hex) == outcome.setup.alert_id
                    ),
                    None,
                )
                if order is None or order.symbol != outcome.setup.symbol:
                    raise DataIntegrityError("XK-02: resolved outcome has no bound proposal")
                prior = tuple(
                    row
                    for row in recorded
                    if row.proposal_id == order.proposal_id
                    and row.trigger in {"ENTRY", "ALERT", "VETO"}
                )
                if not prior:
                    raise DataIntegrityError("XK-02: outcome has no recorded decision evidence")
                entry = max(prior, key=lambda row: (row.trigger == "ENTRY", row.created_at))
                if entry.setup.playbook != outcome.setup.playbook:
                    raise DataIntegrityError("XK-02: outcome playbook differs from proposal")
                entry = JournalEntry.model_validate(
                    entry.model_copy(
                        update={
                            "trigger": "OUTCOME",
                            "source_id": identity,
                            "created_at": self.ledger.clock.now(),
                            "outcome_json": payload,
                        }
                    )
                )
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="TRADE_JOURNAL",
                    detail=entry.model_dump(mode="json"),
                )
                known.add(("OUTCOME", identity))
                added += 1
        return added

    def csv(self) -> bytes:
        def safe(value: object) -> object:
            return (
                "'" + value
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                else value
            )

        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            (
                "trigger",
                "source_id",
                "proposal_id",
                "alert_id",
                "account",
                "environment",
                "created_at",
                "symbol",
                "playbook",
                "evidence_json",
            )
        )
        for row in self.entries():
            writer.writerow(
                tuple(
                    safe(value)
                    for value in (
                        row.trigger,
                        row.source_id,
                        row.proposal_id,
                        row.alert_id,
                        row.scope.account_id,
                        row.scope.environment,
                        row.created_at.isoformat(),
                        row.setup.symbol,
                        row.setup.playbook.value,
                        row.model_dump_json(),
                    )
                )
            )
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            notes = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "JOURNAL_NOTE")
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
            if len(notes) > 100000:
                raise DataIntegrityError("XK-02: journal notes exceed their bound")
            for note in notes:
                if ControlScope.model_validate(note.detail["scope"]) == self.scope:
                    writer.writerow(
                        tuple(
                            safe(value)
                            for value in (
                                "NOTE",
                                str(note.id),
                                "",
                                note.detail["alert_id"],
                                self.scope.account_id,
                                self.scope.environment,
                                note.ts.isoformat(),
                                "",
                                "",
                                _json(note.detail),
                            )
                        )
                    )
            external = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "JOURNAL_UNASSIGNED_EXIT")
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
            if len(external) > 100000:
                raise DataIntegrityError("XK-02: unassigned exit journal exceeds its bound")
            for record in external:
                sale = UnassignedExit(
                    scope=ControlScope.model_validate(record.detail["scope"]),
                    fill=TaxFill.from_payload(record.detail["fill"]),
                )
                if sale.scope == self.scope:
                    writer.writerow(
                        tuple(
                            safe(value)
                            for value in (
                                "EXIT",
                                str(sale.fill.fill_id),
                                "",
                                "",
                                self.scope.account_id,
                                self.scope.environment,
                                sale.fill.ts.isoformat(),
                                sale.fill.symbol,
                                "UNASSIGNED",
                                sale.model_dump_json(),
                            )
                        )
                    )
        return output.getvalue().encode("utf-8")

    def veto_digest(self) -> tuple[str, ...]:
        rows = tuple(
            row
            for row in self.entries()
            if row.trigger == "VETO"
            and self.ledger.clock.now() - row.created_at <= timedelta(days=1)
        )
        return tuple(
            why_not(row.setup.symbol, result)
            for row in reversed(rows)
            for result in (*row.cro, *row.compliance)
            if not result.passed and result.severity == "BLOCK"
        )[:5]
