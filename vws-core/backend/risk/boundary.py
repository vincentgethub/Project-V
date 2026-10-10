"""R-02/R-03/CRO-01..13: durable state and veto logs outside pure rules."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from backend.core.clock import Clock, ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore, financial_state
from backend.domain.models import (
    BlackoutWindow,
    Decision,
    DeployableCapital,
    Intent,
    MarketContext,
    PortfolioSnapshot,
    Severity,
    TradeProposal,
    Verdict,
    snapshot_hash,
)
from backend.risk.portfolio_marks import PersistedPortfolioMarks
from backend.risk.risk_cro import ChiefRiskOfficer, earnings_rule


class VetoSink(Protocol):
    """R-07: an audit sink receives only the required nonsensitive identities."""

    def record(self, rule_id: str, proposal_id: UUID) -> None:
        """R-02: emit a veto record, raising if the audit sink is unavailable."""
        raise DataIntegrityError("R-02: veto audit sink has no implementation")


class LoggingVetoSink:
    """R-02/R-07: static log text plus rule and proposal identifiers."""

    def record(self, rule_id: str, proposal_id: UUID) -> None:
        logging.getLogger(__name__).warning(
            "risk_veto rule_id=%s proposal_id=%s", rule_id, proposal_id
        )


class RiskBoundary:
    """R-02/R-03: evaluate locally, latch tiers, and emit every blocking veto.

    This returns research evidence, never an execution authorization. Complete
    RuleResults travel in the immutable Verdict; the later service records them
    against its signal/proposal ledger rows. Fresh approval revalidation belongs
    at the later human approval boundary. A newly detected financial HALT does
    not retroactively trap an otherwise valid held exit (R-09); subsequent calls
    observe HALTED and require a MANUAL exit.
    """

    def __init__(
        self,
        cro: ChiefRiskOfficer,
        state: SystemStateStore,
        clock: Clock,
        *,
        veto_sink: VetoSink | None = None,
        marks: PersistedPortfolioMarks | None = None,
        additional_blackouts: Callable[[], tuple[BlackoutWindow, ...]] | None = None,
    ) -> None:
        self.cro = cro
        self.state = state
        self.clock = clock
        self.veto_sink = LoggingVetoSink() if veto_sink is None else veto_sink
        self.marks = marks
        self.additional_blackouts = additional_blackouts
        if marks is not None and (
            marks.ledger.engine is not state.engine
            or marks.config.config_hash != cro.config.config_hash
        ):
            raise DataIntegrityError("CRO-09/CRO-10: persisted marks differ from risk policy")

    def _checked(
        self,
        verdict: Verdict,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        daily_loss_blocked: bool = False,
    ) -> Verdict:
        """R-02/R-03: an altered verdict cannot become passing audit evidence."""
        checked = Verdict.model_validate(verdict)
        identifiers = tuple(result.rule_id for result in checked.results)
        expected = tuple(f"CRO-{number:02d}" for number in range(1, 14))
        if (
            checked.proposal_id != proposal.proposal_id
            or checked.config_hash != self.cro.config.config_hash
            or not identifiers
            or len(identifiers) != len(set(identifiers))
            or any(identifier not in expected for identifier in identifiers)
        ):
            raise DataIntegrityError("R-02: risk verdict identity or rule evidence is invalid")
        if checked.decision == Decision.APPROVED:
            proposal = TradeProposal.model_validate(proposal)
            if daily_loss_blocked and proposal.intent in {Intent.ENTRY, Intent.ADD}:
                raise DataIntegrityError(
                    "CRO-10: approval concealed a witnessed session loss block"
                )
            if (
                proposal.intent in {Intent.ENTRY, Intent.ADD}
                and checked.recommended_state != SystemState.RUNNING
            ):
                raise DataIntegrityError(
                    "CRO-01: approved entry cannot recommend a restricted state"
                )
            required = expected if proposal.intent in {Intent.ENTRY, Intent.ADD} else expected[:2]
            if identifiers != required or checked.snapshot_hash != snapshot_hash(snapshot):
                raise DataIntegrityError("R-02: approval lacks complete bound rule evidence")
            blocking = checked.results[:12] if len(required) == 13 else checked.results
            if any(not result.passed or result.severity != Severity.BLOCK for result in blocking):
                raise DataIntegrityError("R-02: approval has altered blocking-rule evidence")
            if len(required) == 13:
                earnings = checked.results[-1]
                if market is None or earnings != earnings_rule(
                    market, ensure_utc(self.clock.now()), self.cro.config, self.cro.calendar
                ):
                    raise DataIntegrityError("CRO-13: approval has invalid earnings evidence")
        elif not any(
            not result.passed and result.severity == Severity.BLOCK for result in checked.results
        ):
            raise DataIntegrityError("R-02: veto lacks a blocking reason")
        # An auditable fail-closed verdict may accompany deliberately invalid
        # snapshot input. HALTED is already maximally restrictive in that case.
        if checked.recommended_state != SystemState.HALTED:
            needed = financial_state(
                snapshot.equity,
                snapshot.high_water_mark,
                snapshot.day_start_equity,
                self.cro.config,
            )
            if needed == SystemState.HALTED or (
                needed == SystemState.REDUCE_ONLY
                and checked.recommended_state == SystemState.RUNNING
            ):
                raise DataIntegrityError(
                    "CRO-09: verdict concealed required drawdown state escalation"
                )
        return checked

    def evaluate(
        self,
        proposal: TradeProposal,
        snapshot: PortfolioSnapshot,
        market: MarketContext | None,
        *,
        deployable: DeployableCapital | None = None,
    ) -> Verdict:
        """R-02/CRO-01/CRO-09: latch drawdown/faults; daily entry veto stays local."""
        try:
            now = ensure_utc(self.clock.now())
            self.state.ledger.verify_chain()
            officer = self.cro
            if self.additional_blackouts is not None:
                extra = self.additional_blackouts()
                if not isinstance(extra, tuple) or len(extra) > 500:
                    raise DataIntegrityError("CRO-11: bounded immutable extra windows required")
                officer = ChiefRiskOfficer(
                    self.cro.config,
                    self.cro.registry,
                    self.cro.calendar,
                    blackout_windows=tuple(
                        window
                        for window in self.cro.blackout_windows
                        if window not in self.cro.registry.blackout_windows
                    )
                    + tuple(BlackoutWindow.model_validate(window) for window in extra),
                )
            daily_loss_blocked = False
            if self.marks is not None:
                snapshot = self.marks.observe(snapshot)
                daily_loss_blocked = self.marks.daily_loss_blocked(now)
            initial = self.state.current()
            verdict = self._checked(
                officer.evaluate(
                    proposal,
                    snapshot,
                    market,
                    initial,
                    now,
                    deployable=deployable,
                    daily_loss_blocked=daily_loss_blocked,
                ),
                proposal,
                snapshot,
                market,
                daily_loss_blocked,
            )
            current = self.state.current()
            if current != initial:
                verdict = self._checked(
                    officer.evaluate(
                        proposal,
                        snapshot,
                        market,
                        current,
                        now,
                        deployable=deployable,
                        daily_loss_blocked=daily_loss_blocked,
                    ),
                    proposal,
                    snapshot,
                    market,
                    daily_loss_blocked,
                )
            if verdict.evaluated_at != now:
                raise DataIntegrityError("R-05: verdict time does not match injected clock")
            latched = self.state.escalate(
                verdict.recommended_state, "CRO-09 drawdown risk evaluation"
            )
            if latched != current and latched != verdict.recommended_state:
                verdict = self._checked(
                    officer.evaluate(
                        proposal,
                        snapshot,
                        market,
                        latched,
                        now,
                        deployable=deployable,
                        daily_loss_blocked=daily_loss_blocked,
                    ),
                    proposal,
                    snapshot,
                    market,
                    daily_loss_blocked,
                )
                if verdict.evaluated_at != now:
                    raise DataIntegrityError("R-05: rechecked verdict time differs from clock")
                self.state.escalate(verdict.recommended_state, "CRO-09 concurrent state recheck")
            for result in verdict.results:
                if not result.passed and result.severity == Severity.BLOCK:
                    self.veto_sink.record(result.rule_id, verdict.proposal_id)
            return verdict
        except Exception as exc:
            try:
                logging.getLogger(__name__).error(
                    "risk_boundary_fault error_type=%s", type(exc).__name__
                )
            except Exception as log_error:
                exc = DataIntegrityError(
                    f"R-02: risk fault audit unavailable ({type(log_error).__name__})"
                )
            try:
                self.state.halt_for_error(exc)
            except Exception as halt_error:
                raise DataIntegrityError(
                    "R-02: risk boundary failed; HALT persistence unavailable"
                ) from halt_error
            raise DataIntegrityError("R-02: risk boundary failed and latched HALTED") from exc
