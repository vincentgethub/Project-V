"""LJ/LP: deterministic ledger projections and review-only weekly mining."""

from datetime import datetime
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import YamlConfig
from backend.core.database import (
    ExecutionFillRecord,
    ExecutionOrderRecord,
    Fill,
    Order,
    SecurityEvent,
)
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.evaluation.availability import GradePublication
from backend.evaluation.costs import FeeSchedule
from backend.evaluation.fill_quality import percentile
from backend.evaluation.filter_shadows import FilterShadow
from backend.evaluation.physical import resolved_trades
from backend.evaluation.registry import Registrations
from backend.evaluation.tca_store import inventory
from backend.execution.storage import approval_evidence, bindings
from backend.learning.journal import MistakeJournal, Observation
from backend.learning.proposals import ProposalStore, mine
from backend.ops.journal import Journal, JournalEntry
from backend.ops.k_runtime import tracker_outcomes
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import ContextTag, RealtimeContext, RealtimeEvent
from backend.realtime.policy import NY
from backend.realtime.storage import RealtimeStore
from backend.tax.accounting import build_tax_book
from backend.tax.service import managed_accounts
from backend.tax.storage import read_fills

NAMESPACE = UUID("0957d65a-6033-461e-87a7-a4d8bdfb09f1")


class LearningService:
    def __init__(
        self,
        ledger: Ledger,
        scope: ControlScope,
        config: YamlConfig,
        calendar: MarketCalendar,
        fees: FeeSchedule,
        project: Path,
    ) -> None:
        self.ledger, self.scope = ledger, ControlScope.model_validate(scope)
        self.config, self.calendar, self.fees, self.project = (
            YamlConfig.model_validate(config),
            calendar,
            fees,
            project,
        )
        self.journal, self.proposals = MistakeJournal(ledger, scope), ProposalStore(ledger, scope)
        self.decisions = Journal(ledger, scope)

    def _base(self, row: JournalEntry, at: datetime, identity: UUID) -> Observation:
        tags: set[ContextTag] = set()
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            contexts = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "REALTIME_CONTEXT",
                        SecurityEvent.detail["proposal_id"].as_string() == str(row.proposal_id),
                    )
                    .order_by(SecurityEvent.seq)
                    .limit(1001)
                )
            )
        if len(contexts) > 1000:
            raise DataIntegrityError("LJ: proposal context exceeds its bound")
        for stored in contexts:
            value = RealtimeContext.recorded(stored.detail["context"])
            if value.scope != self.scope or stored.ts > self.ledger.clock.now():
                raise DataIntegrityError("LJ: opening context scope or receipt differs")
            if value.as_of <= at and stored.ts <= at:
                tags.update(value.tags)
        mean, deviation = self._normal_band(row.setup.playbook.value, at)
        return Observation(
            trade_id=identity,
            proposal_id=row.proposal_id,
            scope=self.scope,
            symbol=row.setup.symbol,
            playbook=row.setup.playbook.value,
            at=at,
            stop=row.setup.stop_price,
            target=row.setup.target_price,
            multiplier_product=Decimal(1)
            if row.setup.size_evidence is None
            else row.setup.size_evidence.product,
            context_tags=tuple(sorted(tags)),
            blocked_rules=tuple(
                rule.rule_id
                for rule in (*row.cro, *row.compliance)
                if not rule.passed and rule.severity == "BLOCK"
            ),
            oos_abs_mean=mean,
            oos_stddev=deviation,
        )

    def _cause_context(
        self, symbol: str, entry_at: datetime, exit_at: datetime
    ) -> tuple[ContextTag, ...]:
        """LJ-04: causal loss-day news and events during the hold, not entry tags."""
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            receipts = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "REALTIME_EVENT",
                        SecurityEvent.ts <= exit_at,
                        SecurityEvent.detail["scope"]["account_id"].as_string()
                        == self.scope.account_id,
                        SecurityEvent.detail["scope"]["environment"].as_string()
                        == self.scope.environment,
                        SecurityEvent.detail["policy_sha256"].as_string()
                        == self.config.config_hash,
                        SecurityEvent.detail["event"]["symbol"].as_string() == symbol,
                    )
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
        if len(receipts) > 100000:
            raise DataIntegrityError("LJ-04: held event inventory exceeds its bound")
        tags: set[ContextTag] = set()
        for receipt in receipts:
            value = RealtimeEvent.recorded(receipt.detail["event"])
            if value.observed_at > receipt.ts or receipt.detail["key"] != RealtimeStore.key(value):
                raise DataIntegrityError("LJ-04: event receipt identity or causal time differs")
            if (
                value.kind == "NEWS_NEG"
                and value.occurred_at.astimezone(NY).date() == exit_at.astimezone(NY).date()
            ):
                tags.add(ContextTag.NEWS_NEG)
            elif entry_at <= value.occurred_at <= exit_at:
                if value.kind == "DILUTION":
                    tags.add(ContextTag.DILUTION)
                elif value.kind == "HALT":
                    tags.add(ContextTag.HALT)
        return tuple(sorted(tags))

    def _normal_band(self, playbook: str, at: datetime) -> tuple[Decimal | None, Decimal | None]:
        """Only validation published before the trade may define expected noise."""
        with Session(self.ledger.engine) as session:
            rows = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "VALIDATION_REPORT", SecurityEvent.ts <= at)
                    .order_by(SecurityEvent.seq.desc())
                    .limit(1001)
                )
            )
        if len(rows) > 1000:
            raise DataIntegrityError("LJ: OOS publication inventory exceeds its bound")
        for stored in rows:
            publication = GradePublication.recorded(stored.detail)
            if (
                publication.kind != "WALKFORWARD"
                or publication.baseline.config_hash != self.config.config_hash
            ):
                continue
            # Baseline is a fixed preregistered reference, not a selected winner.
            reference = next(
                (row for row in publication.result.results if row.variant == "BASELINE"), None
            )
            if reference is None:
                continue
            sample = tuple(
                row.r_multiple
                for row in reference.sample.trades
                if row.playbook is not None and row.playbook.value == playbook
            )
            if len(sample) < 15:
                continue
            with localcontext() as precision:
                precision.prec = 80
                mean = sum(sample, Decimal(0)) / len(sample)
                deviation = (
                    sum(((value - mean) ** 2 for value in sample), Decimal(0)) / (len(sample) - 1)
                ).sqrt()
                return abs(mean), deviation
        return None, None

    @staticmethod
    def _decision(rows: tuple[JournalEntry, ...], proposal: UUID, at: datetime) -> JournalEntry:
        known = tuple(
            row
            for row in rows
            if row.proposal_id == proposal
            and row.created_at <= at
            and row.trigger in {"ALERT", "ENTRY", "VETO"}
        )
        if not known:
            raise DataIntegrityError("LJ: physical trade lacks causal recorded decision evidence")
        return min(known, key=lambda row: (row.created_at, row.source_id.hex))

    def sync(self) -> int:
        self.decisions.sync()
        rows = self.decisions.entries()
        quality = inventory(self.ledger, self.scope)
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            orders = {
                row.proposal_id: row
                for row in session.scalars(
                    select(Order).where(Order.account_id == self.scope.account_id).limit(100001)
                )
            }
            instructions = {
                row.id: row
                for row in session.scalars(
                    select(ExecutionOrderRecord)
                    .where(
                        ExecutionOrderRecord.account_id == self.scope.account_id,
                        ExecutionOrderRecord.environment == self.scope.environment,
                    )
                    .limit(100001)
                )
            }
            fills = {
                row.id: row
                for row in session.scalars(
                    select(ExecutionFillRecord)
                    .where(ExecutionFillRecord.execution_order_id.in_(tuple(instructions)))
                    .limit(100001)
                )
            }
        if max(len(orders), len(instructions), len(fills)) > 100000:
            raise DataIntegrityError("LJ: physical inventory exceeds its bound")
        added = 0
        for trade in resolved_trades(self.ledger, self.scope, self.fees):
            row = self._decision(rows, trade.proposal_id, trade.entry_at)
            members = tuple(fills[key] for key in trade.fill_ids)
            bought = sorted(
                (fill for fill in members if instructions[fill.execution_order_id].side == "BUY"),
                key=lambda fill: (fill.filled_at, fill.seq),
            )
            sold = sorted(
                (fill for fill in members if instructions[fill.execution_order_id].side == "SELL"),
                key=lambda fill: (fill.filled_at, fill.seq),
            )
            base = self._base(row, trade.entry_at, trade.proposal_id)
            with Session(self.ledger.engine) as session:
                proof = approval_evidence(
                    session, trade.proposal_id, instructions[bought[0].execution_order_id].seq
                )
            if proof is None:
                raise DataIntegrityError("LJ: resolved trade variant approval unavailable")
            observation = Observation.model_validate(
                base.model_copy(
                    update={
                        "at": trade.exit_at,
                        "entry_at": trade.entry_at,
                        "exit_at": trade.exit_at,
                        "entry_price": bought[0].price,
                        "exit_price": sold[-1].price,
                        "r_after_costs": trade.r_multiple,
                        "variant_id": proof.exit_variant,
                        "cause_context_tags": self._cause_context(
                            row.setup.symbol, trade.entry_at, trade.exit_at
                        ),
                        "stopped": any(
                            instructions[fill.execution_order_id].order_type == "STOP"
                            for fill in sold
                        ),
                    }
                )
            )
            added += self.journal.record(observation)
        added += self._manual(rows, orders, {row.order_id for row in instructions.values()})
        # Each stop or excessive-slip fill is an episode even while its position
        # remains open. LP counts distinct proposals, never split-fill rows.
        for value in quality:
            fill = fills.get(value.fill_id)
            if fill is None:
                raise DataIntegrityError("LJ: quality has no bound physical fill")
            instruction = instructions[fill.execution_order_id]
            proposal = next(
                (key for key, order in orders.items() if order.id == instruction.order_id), None
            )
            if proposal is None:
                raise DataIntegrityError("LJ: physical fill proposal missing")
            prior = tuple(
                row.model_slippage_bps
                for row in quality
                if row.bucket == value.bucket
                and row.filled_at < value.filled_at
                and row.model_slippage_bps is not None
            )
            threshold = percentile(prior, Decimal("0.9"))
            slip = value.model_slippage_bps
            if not value.is_stop and (slip is None or threshold is None or slip <= threshold):
                continue
            decision = self._decision(rows, proposal, fill.filled_at)
            base = self._base(decision, fill.filled_at, fill.id)
            added += self.journal.record(
                Observation.model_validate(
                    base.model_copy(
                        update={
                            "fill_vs_model_bps": slip,
                            "bucket_p90_bps": threshold,
                            "stopped": value.is_stop,
                        }
                    )
                )
            )
        for row in rows:
            base = self._base(
                row, row.created_at, uuid5(NAMESPACE, "incident:" + str(row.source_id))
            )
            if (
                ContextTag.UNAVAILABLE in base.context_tags
                or ContextTag.CLOCK_SKEW in base.context_tags
                or any(not rule.passed and rule.rule_id in {"CRO-02", "CRO-07"} for rule in row.cro)
            ):
                added += self.journal.record(
                    Observation.model_validate(
                        base.model_copy(
                            update={
                                "incident": "Recorded data or realtime fault affected this decision"
                            }
                        )
                    )
                )
        added += self._missed(rows, orders, instructions)
        added += self._context_incidents(rows)
        return added

    def _context_incidents(self, decisions: tuple[JournalEntry, ...]) -> int:
        with Session(self.ledger.engine) as session:
            contexts = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "REALTIME_CONTEXT",
                        SecurityEvent.detail["scope"]["account_id"].as_string()
                        == self.scope.account_id,
                        SecurityEvent.detail["scope"]["environment"].as_string()
                        == self.scope.environment,
                    )
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
        if len(contexts) > 100000:
            raise DataIntegrityError("LJ: decision context inventory exceeds its bound")
        added = 0
        for stored in contexts:
            context = RealtimeContext.recorded(stored.detail["context"])
            if (
                context.as_of > stored.ts
                or stored.ts > self.ledger.clock.now()
                or context.scope != self.scope
            ):
                raise DataIntegrityError("LJ: decision incident has invalid causal binding")
            if (
                ContextTag.UNAVAILABLE not in context.tags
                and ContextTag.CLOCK_SKEW not in context.tags
            ):
                continue
            proposal = UUID(stored.detail["proposal_id"])
            decision = self._decision(decisions, proposal, context.as_of)
            base = self._base(
                decision, context.as_of, uuid5(NAMESPACE, "context:" + str(stored.id))
            )
            added += self.journal.record(
                Observation.model_validate(
                    base.model_copy(
                        update={
                            "incident": "Recorded realtime availability or clock incident affected this decision"
                        }
                    )
                )
            )
        return added

    def _missed(
        self,
        decisions: tuple[JournalEntry, ...],
        orders: dict[UUID, Order],
        instructions: dict[UUID, ExecutionOrderRecord],
    ) -> int:
        """A missed actual limit needs both broker closure and frozen tape proof."""
        with Session(self.ledger.engine) as session:
            observed = bindings(session)
        outcomes = tracker_outcomes(self.ledger, self.scope)
        added = 0
        for outcome in outcomes:
            if (
                outcome.status != "NOT_FILLED"
                or outcome.reason != "ALERT_UNFILLED"
                or outcome.setup.disposition != "APPROVED"
            ):
                continue
            decision = next(
                (row for row in decisions if row.alert_id == outcome.setup.alert_id), None
            )
            if decision is None:
                continue
            order = orders.get(decision.proposal_id)
            roots = tuple(
                row
                for row in instructions.values()
                if order is not None and row.order_id == order.id and row.role == "ENTRY"
            )
            if not roots or any(
                row.id not in observed
                or observed[row.id].is_open
                or observed[row.id].filled_qty != 0
                or observed[row.id].status not in {"canceled", "expired"}
                for row in roots
            ):
                continue
            at = self.calendar.session_close(outcome.setup.valid_until_session)
            if at > self.ledger.clock.now():
                continue
            base = self._base(
                decision,
                decision.created_at,
                uuid5(NAMESPACE, "missed:" + str(decision.proposal_id)),
            )
            added += self.journal.record(
                Observation.model_validate(
                    base.model_copy(update={"at": at, "never_traded_through": True})
                )
            )
        return added

    def _manual(
        self, decisions: tuple[JournalEntry, ...], orders: dict[UUID, Order], automated: set[UUID]
    ) -> int:
        """Resolve mapped MANUAL acquisitions using the shared physical FIFO book.

        Unassigned holdings have no invented proposal, stop, initial R or tag.
        Tax wash adjustments are excluded from economic trading performance.
        """
        owners = tuple(
            row
            for row in managed_accounts(self.project, self.scope.account_id)
            if row.id == self.scope.account_id
        )
        tax_fills = read_fills(
            self.ledger, self.scope.account_id, self.scope.environment, csv=False
        )
        if not tax_fills:
            return 0
        book = build_tax_book(
            tax_fills,
            owners,
            InstrumentRegistry.from_csv(self.project / "config"),
            self.scope.environment,
        )
        by_activity = {row.activity_id: row for row in tax_fills}
        by_id = {row.fill_id: row for row in tax_fills}
        with Session(self.ledger.engine) as session:
            fills = tuple(
                session.scalars(
                    select(Fill)
                    .where(Fill.order_id.in_(tuple(row.id for row in orders.values())))
                    .order_by(Fill.filled_at, Fill.seq)
                    .limit(100001)
                )
            )
        if len(fills) > 100000:
            raise DataIntegrityError("LJ: manual fill inventory exceeds its bound")
        added = 0
        for proposal, order in orders.items():
            if order.id in automated or order.side != "BUY":
                continue
            bought = tuple(row for row in fills if row.order_id == order.id)
            if not bought:
                continue
            mapped = tuple(by_activity.get(row.broker_fill_id) for row in bought)
            if any(row is None for row in mapped):
                continue  # Attributed physical fills are required; never estimate identity.
            acquisitions = tuple(row for row in mapped if row is not None)
            identities = {row.fill_id for row in acquisitions}
            if any(row.acquisition_id in identities for row in book.lots):
                continue
            sales = tuple(row for row in book.sales if row.acquisition_id in identities)
            if sum(row.qty for row in sales) != sum(row.qty for row in acquisitions):
                continue
            if order.stop_price is None or any(row.price <= order.stop_price for row in bought):
                raise DataIntegrityError("LJ: physical manual initial stop risk unavailable")
            entry = min(row.ts for row in acquisitions)
            exit_at = max(row.sold_at for row in sales)
            last = max(
                (by_id[row.fill_id] for row in sales), key=lambda row: (row.ts, row.fill_id.hex)
            )
            decision = self._decision(decisions, proposal, entry)
            base = self._base(decision, entry, proposal)
            with localcontext() as precision:
                precision.prec = 80
                risk = sum(((row.price - order.stop_price) * row.qty for row in bought), Decimal(0))
                result = sum((row.realized_before_wash for row in sales), Decimal(0)) / risk
            added += self.journal.record(
                Observation.model_validate(
                    base.model_copy(
                        update={
                            "at": exit_at,
                            "entry_at": entry,
                            "exit_at": exit_at,
                            "entry_price": bought[0].price,
                            "exit_price": last.price,
                            "r_after_costs": result,
                            "cause_context_tags": self._cause_context(order.symbol, entry, exit_at),
                        }
                    )
                )
            )
        return added

    def regret(self, proposal_id: UUID) -> str:
        if not isinstance(proposal_id, UUID):
            raise DataIntegrityError("LJ-01: canonical proposal UUID required")
        self.decisions.sync()
        known = tuple(
            row
            for row in self.decisions.entries()
            if row.proposal_id == proposal_id and row.trigger == "VETO"
        )
        if not known:
            with Session(self.ledger.engine) as session:
                filtered = session.scalar(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "FILTER_SHADOW",
                        SecurityEvent.detail["identity"].as_string() == str(proposal_id),
                    )
                    .limit(1)
                )
            if filtered is None or filtered.ts > self.ledger.clock.now():
                raise DataIntegrityError(
                    "LJ-01: REGRETTED requires a recorded rule-blocked candidate"
                )
            shadow = FilterShadow.recorded(filtered.detail)
            if shadow.scope != self.scope:
                raise DataIntegrityError("LJ-01: filtered candidate account differs")
            self.journal.record(
                Observation(
                    trade_id=uuid5(NAMESPACE, "regret:" + str(proposal_id)),
                    proposal_id=proposal_id,
                    scope=self.scope,
                    symbol=shadow.candidate.symbol,
                    playbook=shadow.candidate.playbook.value,
                    at=shadow.candidate.as_of,
                    stop=shadow.candidate.stop_price,
                    target=shadow.candidate.target_price,
                    multiplier_product=shadow.factors.product,
                    blocked_rules=shadow.cohorts,
                    regretted=True,
                )
            )
            return "Recorded REGRETTED. No rule, setting or trading mode changed."
        row = min(known, key=lambda item: (item.created_at, item.source_id.hex))
        base = self._base(row, row.created_at, uuid5(NAMESPACE, "regret:" + str(proposal_id)))
        self.journal.record(Observation.model_validate(base.model_copy(update={"regretted": True})))
        return "Recorded REGRETTED. No rule, setting or trading mode changed."

    def mine(self) -> str:
        self.sync()
        try:
            proof = Registrations(self.ledger).latest()
        except ConfigurationError:
            return "Lessons: INSUFFICIENT; fixed registered OOS evidence is unavailable. No change proposed."
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            publications = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "VALIDATION_REPORT")
                    .order_by(SecurityEvent.seq)
                    .limit(1001)
                )
            )
        if len(publications) > 1000:
            raise DataIntegrityError("LP: validation inventory exceeds its bound")
        latest = {}
        for row in publications:
            publication = GradePublication.recorded(row.detail)
            if row.ts > self.ledger.clock.now():
                raise DataIntegrityError("LP: future validation publication")
            if (
                publication.registration_sha256 == proof.sha256
                and publication.baseline.config_hash == self.config.config_hash
                and publication.result.kind == "WALKFORWARD"
            ):
                latest[publication.family] = publication.result
        result = mine(
            self.journal.rows(),
            proof,
            tuple(latest[key] for key in sorted(latest)),
            self.config,
            self.config.lj,
            self.config.lp,
            open_count=len(self.proposals.open()),
            calendar=self.calendar,
        )
        for proposal in result.proposals:
            self.proposals.publish(proposal, self.project)
        return self.proposals.masked() + (
            "\n" + "\n".join(result.insufficient) if result.insufficient else ""
        )
