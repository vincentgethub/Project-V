"""GD-05/FA-08: deterministic escaped cards and manual instructions."""

from datetime import datetime
from decimal import localcontext
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.fundamentals import FrameworkStatus, FundamentalReport
from backend.agents.news_reader import NewsAssessment
from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import (
    Alert,
    ComplianceCheck,
    ResearchReport,
    RiskDecision,
    RiskRuleResult,
    TradeTicket,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger, ticket_digest
from backend.domain.models import (
    Decision,
    FlowSignal,
    FrozenModel,
    PortfolioSnapshot,
    ProviderStatus,
    SetupCandidate,
    TradeProposal,
    Verdict,
    snapshot_hash,
)
from backend.risk.compliance import ComplianceAssessment


def display_time(instant: datetime, settings: Settings) -> str:
    checked = Settings.validated_copy(settings)
    local = ensure_utc(instant).astimezone(ZoneInfo(checked.display_tz))
    suffix = "CT" if checked.display_tz == "America/Chicago" else local.tzname()
    return f"{local:%a %b %d, %I:%M %p} {suffix}"


class CardContext(FrozenModel):
    candidate: SetupCandidate
    proposal: TradeProposal
    snapshot: PortfolioSnapshot
    verdict: Verdict
    compliance: ComplianceAssessment
    fundamentals: FundamentalReport
    news: NewsAssessment
    flow: FlowSignal
    market_context: str = Field(min_length=1, max_length=280)


def checked_context(context: CardContext, settings: Settings) -> CardContext:
    """No forged mismatched evidence can label a card as risk approved."""
    item = CardContext.model_validate(context)
    p, c, v = item.proposal, item.candidate, item.verdict
    if (
        p.symbol != c.symbol
        or p.symbol != item.fundamentals.symbol
        or p.symbol != item.news.symbol
        or p.account_id != item.snapshot.account_id
        or p.size_evidence != c.size_evidence
        or (p.qty, p.limit_price, p.stop_price, p.target_price)
        != (c.qty, c.entry_price, c.stop_price, c.target_price)
        or v.proposal_id != p.proposal_id
        or v.snapshot_hash != snapshot_hash(item.snapshot)
        or v.config_hash != settings.config_hash
        or v.decision != Decision.APPROVED
        or tuple(row.rule_id for row in v.results) != tuple(f"CRO-{i:02d}" for i in range(1, 15))
        or any(
            not row.passed or row.severity.value != "BLOCK"
            for row in v.results
            if row.rule_id != "CRO-13"
        )
        or item.compliance.proposal_id != p.proposal_id
        or item.compliance.config_hash != settings.config_hash
        or item.compliance.snapshot_hash != v.snapshot_hash
        or tuple(row.rule_id for row in item.compliance.results)
        != tuple(f"CMP-{i:02d}" for i in range(1, 8))
        or any(not row.passed and row.severity.value == "BLOCK" for row in item.compliance.results)
    ):
        raise DataIntegrityError("GD-05: card lacks consistent passing risk/compliance evidence")
    return item


def format_card(context: CardContext, settings: Settings) -> str:
    policy = Settings.validated_copy(settings)
    item = checked_context(context, policy)
    p, c = item.proposal, item.candidate
    with localcontext() as ctx:
        ctx.prec = 80
        notional = p.qty * p.limit_price
        risk = p.qty * (p.limit_price - c.stop_price + p.limit_price * policy.stop_slippage_buffer)
        weight = notional / item.snapshot.equity * 100
        risk_pct = risk / item.snapshot.equity * 100
        reward_risk = (c.target_price - p.limit_price) / (
            p.limit_price - c.stop_price + p.limit_price * policy.stop_slippage_buffer
        )
    f = item.fundamentals
    fundamental_text = (
        "n/a"
        if f.framework_status == FrameworkStatus.NOT_APPLICABLE
        else f"{f.passed_count}/5 {f.framework_status.value}"
        + (" · " + "; ".join(f.failure_reasons) if f.failure_reasons else "")
    )
    news = item.news
    news_text = (
        "unavailable"
        if news.news.status != ProviderStatus.OK
        else f"{len(news.news.headlines)} headlines (sentiment {news.sentiment_status.lower()})"
    )
    if news.sentiment is not None:
        news_text = f"{news.sentiment.score:+f} {news.sentiment.classification.value} " + " ".join(
            f"[{value[:12]}]" for value in news.sentiment.evidence_headline_ids
        )
    size_text = "$•••" if policy.telegram_mask_amounts else f"{p.qty} sh = ${notional:.2f}"
    risk_text = "$•••" if policy.telegram_mask_amounts else f"-${risk:.2f}"
    lines = [
        f"{escape(p.symbol)} · Buy setup · {escape(c.playbook.value)} (score {c.score:f}/10)",
        *(
            ["WARN: optional earnings-gap playbook; a real trading edge is unverified."]
            if c.playbook.value == "EARNINGS_GAP" and policy.execution_mode == "MANUAL"
            else []
        ),
        f"Buy limit ${p.limit_price:.2f} · Stop ${c.stop_price:.2f} · Target ${c.target_price:.2f}",
        f"Size {size_text} ({weight:.2f}% of account)",
        *(
            [
                "Size "
                + f"{p.size_evidence.product:f}× ("
                + ", ".join(
                    f"{name} {value}"
                    for name, value in p.size_evidence.model_dump().items()
                    if name not in {"base_qty", "minimum"} and value < 1
                )
                + ")"
            ]
            if p.size_evidence is not None and p.size_evidence.product < 1
            else []
        ),
        f"If stopped: about {risk_text} ({risk_pct:.2f}%) · Reward:risk {reward_risk:.2f}",
        f"News: {news_text} · Fundamentals {escape(fundamental_text)}",
        *[f"[{row.stable_id[:12]}] {escape(row.headline)}" for row in news.news.headlines[:3]],
        f"Market: {escape(item.market_context)} · Flow: "
        + (
            "n/a (unavailable)"
            if item.flow.status != ProviderStatus.OK
            else escape(item.flow.summary or "")
        ),
        *[
            f"WARN {escape(row.rule_id)}: {escape(row.message)}"
            for row in (*item.verdict.results, *item.compliance.results)
            if not row.passed
        ],
        f"All blocking risk/compliance checks passed · Valid until {display_time(p.expires_at, policy)}",
        "Manual review required; no broker order has been sent."
        if policy.execution_mode == "MANUAL"
        else "Research checks passed; no broker order has been sent.",
    ]
    rendered = "\n".join(lines)
    if len(rendered.encode("utf-16-le")) // 2 > 4096:
        raise DataIntegrityError("GD-05: card exceeds Telegram's message boundary")
    return rendered


def manual_instructions(proposal: TradeProposal, settings: Settings) -> str:
    """Read-only preview; the authenticated F gate creates an actual ticket."""
    p = TradeProposal.model_validate(proposal)
    if p.side.value != "BUY" or p.stop_price is None or p.target_price is None:
        raise DataIntegrityError("GD-05: this entry preview needs long protection")
    qty = "$•••" if Settings.validated_copy(settings).telegram_mask_amounts else str(p.qty)
    return "\n".join(
        (
            f"Manual instructions preview (valid until {display_time(p.expires_at, settings)})",
            f"1) BUY {qty} {escape(p.symbol)}, LIMIT ${p.limit_price:.2f}, DAY",
            f"2) After it fills: SELL STOP {qty} {escape(p.symbol)} at ${p.stop_price:.2f}, GTC",
            f"3) Optional: SELL LIMIT {qty} {escape(p.symbol)} at ${p.target_price:.2f}, GTC (use OCO if supported)",
            "Requires fresh checks and human approval. No order sent.",
        )
    )


def ticket_card(ticket: TradeTicket, settings: Settings) -> str:
    """Ticket fields are checked against their immutable digest before display."""
    policy = Settings.validated_copy(settings)
    if (
        ticket.ticket_sha256 != ticket_digest(ticket)
        or ticket.side not in {"BUY", "SELL"}
        or (ticket.side == "BUY" and ticket.stop_price is None)
    ):
        raise DataIntegrityError("GD-06: invalid manual ticket")
    qty = "$•••" if policy.telegram_mask_amounts else str(ticket.qty)
    lines = [
        f"TICKET {ticket.id.hex[:12]} (valid until {display_time(ticket.valid_until, policy)})",
        f"1) {ticket.side} {qty} {escape(ticket.symbol)}, LIMIT ${ticket.limit_price:.2f}, DAY",
    ]
    if ticket.side == "SELL":
        lines.append("Check held shares and existing broker stops before placing this exit.")
    else:
        lines.append(
            f"2) After it fills: SELL STOP {qty} {escape(ticket.symbol)} at ${ticket.stop_price:.2f}, GTC"
        )
    if ticket.side == "BUY" and ticket.target_price is not None:
        lines.append(
            f"3) Optional: SELL LIMIT {qty} {escape(ticket.symbol)} at ${ticket.target_price:.2f}, GTC (use OCO if supported)"
        )
    lines.append("Manual instructions only. No broker order sent.")
    return "\n".join(lines)


def details_cards(alert_id: UUID, ledger: Ledger, settings: Settings) -> tuple[str, ...]:
    """Every persisted rule is shown; overflow continues in read-only messages."""
    policy = Settings.validated_copy(settings)
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        alert = session.get(Alert, alert_id)
        if alert is None or alert.config_hash != policy.config_hash:
            raise DataIntegrityError("GD-06: details lack bound alert policy")
        decision = session.scalar(
            select(RiskDecision)
            .where(RiskDecision.proposal_id == alert.proposal_id)
            .order_by(RiskDecision.seq.desc())
            .limit(1)
        )
        if decision is None:
            raise DataIntegrityError("GD-06: details lack risk evidence")
        rules = tuple(
            session.scalars(
                select(RiskRuleResult)
                .where(RiskRuleResult.risk_decision_id == decision.id)
                .order_by(RiskRuleResult.seq)
            )
        )
        checks = tuple(
            session.scalars(
                select(ComplianceCheck)
                .where(ComplianceCheck.proposal_id == alert.proposal_id)
                .order_by(ComplianceCheck.seq)
            )
        )
        reports = tuple(
            session.scalars(
                select(ResearchReport)
                .where(ResearchReport.alert_id == alert.id)
                .order_by(ResearchReport.seq)
            )
        )
    lines = [
        f"Details {escape(alert.symbol)} · config {alert.config_hash[:12]}",
        f"Risk checked {display_time(decision.evaluated_at, policy)} · snapshot {decision.snapshot_hash[:12]}",
    ]
    combined: tuple[RiskRuleResult | ComplianceCheck, ...] = (*rules, *checks)
    for row in combined:
        observed = "$•••" if policy.telegram_mask_amounts else str(row.observed)
        limit = "$•••" if policy.telegram_mask_amounts else str(row.limit)
        lines.append(
            f"{row.rule_id} {'PASS' if row.passed else row.severity}: observed {observed}; limit {limit}; {row.message}"
        )
    for report in reports:
        lines.append(
            f"{report.agent_name}: {report.status}; evidence time {display_time(report.created_at, policy)}"
        )
        if report.agent_name == "fundamentals":
            from backend.agents.fundamentals import FundamentalReport

            fundamental = FundamentalReport.from_recorded(report.payload)
            for metric in fundamental.metrics:
                lines.append(
                    f"{metric.name}: {metric.status.value}; value {metric.value}; threshold {metric.threshold}; {metric.note}"
                )
    pages: list[str] = []
    page = ""
    for line in lines:
        text = escape(line)
        if len(text.encode("utf-16-le")) // 2 > 4096:
            raise DataIntegrityError("GD-06: detail line exceeds message boundary")
        if len((page + "\n" + text).encode("utf-16-le")) // 2 > 4096:
            pages.append(page)
            page = ""
        page += ("\n" if page else "") + text
    pages.append(page)
    return tuple(pages)
