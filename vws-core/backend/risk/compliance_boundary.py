"""R-02/R-03/CMP-01..07: compliance audit and HALT effects outside pure rules."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from backend.core.clock import Clock, ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.domain.models import (
    AccountFlags,
    Intent,
    PortfolioSnapshot,
    Severity,
    TradeProposal,
    snapshot_hash,
)
from backend.risk.compliance import (
    ComplianceAssessment,
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TradeRecord,
)


class ComplianceFindingSink(Protocol):
    """R-07: audit only nonsensitive rule/proposal/severity identities."""

    def record(self, rule_id: str, proposal_id: UUID, severity: Severity) -> None:
        """R-02: an unavailable sink raises rather than silently dropping evidence."""
        raise DataIntegrityError("R-02: compliance audit sink has no implementation")


class LoggingComplianceFindingSink:
    """CMP-01..07/R-07: static text; no external account/history payload in logs."""

    def record(self, rule_id: str, proposal_id: UUID, severity: Severity) -> None:
        logging.getLogger(__name__).warning(
            "compliance_finding rule_id=%s proposal_id=%s severity=%s",
            rule_id,
            proposal_id,
            severity,
        )


class ComplianceBoundary:
    """R-02/R-03/CMP-06: pure evidence plus durable fault escalation.

    This assessment does not authorize an alert or a trade ticket. The later
    service combines it with CRO evidence and fresh authenticated human approval.
    Current broker restrictions and unexpected provider/input faults persist a
    HALT. A valid held exit still receives WARN findings (R-09); subsequent CRO
    calls observe the persisted HALTED state and require the manual exception.
    """

    def __init__(
        self,
        engine: ComplianceEngine,
        state: SystemStateStore,
        clock: Clock,
        *,
        finding_sink: ComplianceFindingSink | None = None,
    ) -> None:
        self.engine = engine
        self.state = state
        self.clock = clock
        self.finding_sink = LoggingComplianceFindingSink() if finding_sink is None else finding_sink

    def _checked(
        self,
        assessment: ComplianceAssessment,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        now: datetime,
        flags: AccountFlags | None,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
    ) -> ComplianceAssessment:
        """R-02/R-03/R-09: complete bound evidence cannot silently change severity."""
        checked = ComplianceAssessment.model_validate(assessment)
        proposal = TradeProposal.model_validate(proposal)
        try:
            identity = self.engine.input_hash(
                proposal, snapshot, lots, history, external_accounts, flags
            )
        except DataIntegrityError:
            identity = "0" * 64
        if checked.input_hash != identity or (
            identity == "0" * 64
            and (
                checked.recommended_state != SystemState.HALTED
                or all(row.passed for row in checked.results)
            )
        ):
            raise DataIntegrityError("R-03: compliance assessment inputs do not match")
        if (
            checked.proposal_id != proposal.proposal_id
            or checked.config_hash != self.engine.config.config_hash
            or checked.evaluated_at != now
            or tuple(row.rule_id for row in checked.results)
            != tuple(f"CMP-{number:02d}" for number in range(1, 8))
        ):
            raise DataIntegrityError(
                "R-02: compliance assessment provenance or evidence is invalid"
            )
        if checked.snapshot_hash != snapshot_hash(snapshot):
            # Invalid input can produce a maximally restrictive auditable report.
            # The ordinary snapshot_hash path still validates every valid input.
            if (
                checked.snapshot_hash != "0" * 64
                or checked.recommended_state != SystemState.HALTED
                or any(row.passed for row in checked.results)
            ):
                raise DataIntegrityError("R-03: compliance assessment snapshot does not match")
        exit_trade = proposal.intent in {Intent.REDUCE, Intent.EXIT}
        if exit_trade:
            held = snapshot.positions.get(proposal.symbol)
            pending = snapshot.reserved_sell_shares(proposal.symbol)
            verifiable = (
                held is not None
                and proposal.qty <= held.qty - pending
                and proposal.account_id == snapshot.account_id
                and proposal.created_at <= checked.evaluated_at < proposal.expires_at
                and timedelta(0)
                <= now - snapshot.as_of
                <= timedelta(seconds=self.engine.config.stale_quote_seconds)
            )
            if verifiable and any(row.severity != Severity.WARN for row in checked.results):
                raise DataIntegrityError("R-09: compliance evidence would trap a verifiable exit")
        else:
            for row in checked.results:
                if (
                    row.rule_id in {"CMP-03", "CMP-04", "CMP-06", "CMP-07"}
                    and row.severity != Severity.BLOCK
                ):
                    raise DataIntegrityError("R-02: compliance blocking-rule severity was altered")
            forward = checked.results[0]
            if self.engine.config.wash_sale_mode == "BLOCK" and forward.severity != Severity.BLOCK:
                raise DataIntegrityError("CMP-01: configured BLOCK policy was downgraded")
        broker = checked.results[5]
        try:
            expected_blocked = flags is None or AccountFlags.model_validate(flags).blocked
        except (ValueError, TypeError):
            expected_blocked = True
        if expected_blocked and broker.passed:
            raise DataIntegrityError("CMP-06: assessment concealed missing or blocked broker flags")
        if not broker.passed and checked.recommended_state != SystemState.HALTED:
            raise DataIntegrityError("CMP-06: broker restriction must recommend HALTED")
        return checked

    def evaluate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        lots: tuple[TaxLot, ...],
        history: tuple[TradeRecord, ...],
        external_accounts: tuple[ExternalAccount, ...],
        *,
        flags: AccountFlags | None = None,
    ) -> ComplianceAssessment:
        """R-02/CMP-06: any boundary failure logs, halts, and raises a typed error."""
        try:
            now = ensure_utc(self.clock.now())
            self.state.ledger.verify_chain()
            self.state.current()
            assessment = self._checked(
                self.engine.assess(
                    proposal, snapshot, lots, history, external_accounts, now, flags=flags
                ),
                proposal,
                snapshot,
                now,
                flags,
                lots,
                history,
                external_accounts,
            )
            self.state.escalate(assessment.recommended_state, "CMP-06 compliance assessment")
            for row in assessment.results:
                if not row.passed:
                    # Identity has been checked above; no invalid None can reach the sink.
                    self.finding_sink.record(row.rule_id, proposal.proposal_id, row.severity)
            return assessment
        except Exception as exc:
            try:
                logging.getLogger(__name__).error(
                    "compliance_boundary_fault error_type=%s", type(exc).__name__
                )
            except Exception as log_error:
                exc = DataIntegrityError(
                    f"R-02: compliance fault audit unavailable ({type(log_error).__name__})"
                )
            try:
                self.state.halt_for_error(exc)
            except Exception as halt_error:
                raise DataIntegrityError(
                    "R-02: compliance boundary failed; HALT persistence unavailable"
                ) from halt_error
            raise DataIntegrityError("R-02: compliance boundary failed and latched HALTED") from exc
