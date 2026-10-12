"""EV-01: bounded read-only alert and CRO-shadow reconstruction from verified rows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.agents.fundamentals import FrameworkStatus, FundamentalReport
from backend.core.config import Settings
from backend.core.database import (
    Alert,
    AlertEvent,
    DataSnapshot,
    ExecutionOrderRecord,
    Order,
    ResearchReport,
    RiskDecision,
    SecurityEvent,
    Signal,
    transaction,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.data_layer import _provider_money
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, SetupCandidate
from backend.evaluation.filter_shadows import FilterShadow
from backend.evaluation.filter_shadows import filters as reduction_filters
from backend.evaluation.outcomes import Disposition, OutcomeSetup
from backend.evaluation.provenance import EvaluationProvenance
from backend.evaluation.weekly import ReportContext

NY = ZoneInfo("America/New_York")
SHADOW_NAMESPACE = UUID("cfa2f9b5-d014-49bd-88e5-d03a5857d21f")
MAX_TRACKED_SETUPS = 100000


class TrackedSetup(FrozenModel):
    setup: OutcomeSetup
    provenance: EvaluationProvenance


def collect_tracked_setups(
    ledger: Ledger, settings: Settings, context: ReportContext, calendar: MarketCalendar
) -> tuple[TrackedSetup, ...]:
    """Every alert state is explicit; only actual CRO vetoes become its shadow.

    Failed compliance/fundamental admission alone is not called a CRO veto.
    Missing provenance refuses tracking rather than guessing old expiry/mode.
    """
    try:
        policy = Settings.validated_copy(settings)
        scope = ReportContext.model_validate(context)
        if scope.cohort != ("PAPER" if policy.paper_trading else "LIVE"):
            raise ValueError("tracker mode differs from managed account policy")
        ledger.verify_chain()
        setups: list[TrackedSetup] = []
        with transaction(ledger.engine) as session:
            ledger._verify_in_session(session)
            now = ledger.clock.now()
            orders = tuple(
                session.scalars(
                    select(Order)
                    .where(
                        Order.account_id == scope.account_id,
                        Order.side == "BUY",
                        Order.intent == "ENTRY",
                        Order.source == "SIGNAL",
                    )
                    .order_by(Order.seq)
                    .limit(MAX_TRACKED_SETUPS + 1)
                )
            )
            if len(orders) > MAX_TRACKED_SETUPS:
                raise DataIntegrityError("EV-01: tracker proposal count exceeds its bound")
            for order in orders:
                signal = session.get(Signal, order.signal_id)
                if signal is None or signal.agent_name != "SetupHunter":
                    continue
                if signal.created_at > now:
                    raise ValueError("future tracker evidence")
                values = dict(signal.structured_thesis["setup"])
                values["as_of"] = datetime.fromisoformat(values["as_of"])
                for name in ("entry_price", "stop_price", "target_price"):
                    values[name] = _provider_money(values[name])
                candidate = SetupCandidate.model_validate(values)
                if candidate.as_of > signal.created_at:
                    raise ValueError("candidate postdates its immutable signal")
                day = candidate.as_of.astimezone(NY).date()
                if not scope.start <= day <= scope.end:
                    continue
                calendar.session_close(day)
                if (
                    candidate.symbol,
                    candidate.qty,
                    candidate.entry_price,
                    candidate.stop_price,
                    candidate.target_price,
                ) != (
                    order.symbol,
                    order.qty,
                    order.limit_price,
                    order.stop_price,
                    order.target_price,
                ):
                    raise ValueError("candidate levels/shares differ from immutable proposal")
                provenance = EvaluationProvenance.from_recorded(
                    signal.structured_thesis["evaluation_provenance"]
                )
                if calendar.session_close(provenance.evidence_session) > candidate.as_of:
                    raise ValueError("tracker cost evidence includes future/incomplete bars")
                if provenance.spread_measurement is not None and (
                    provenance.spread_measurement.symbol != candidate.symbol
                    or provenance.spread_measurement.fetched_at > candidate.as_of
                ):
                    raise ValueError("tracker quotes include future or other-issuer evidence")
                if provenance.cohort != scope.cohort or provenance.yaml_hash != scope.config_sha256:
                    raise ValueError(
                        "tracker evidence uses a different mode or strategy configuration"
                    )
                alert = session.scalar(select(Alert).where(Alert.proposal_id == order.proposal_id))
                status: Disposition
                approved_qty = order.qty
                fundamental = FrameworkStatus.INCOMPLETE
                if alert is not None:
                    if (
                        alert.expires_at != provenance.expires_at
                        or alert.config_hash != provenance.settings_hash
                    ):
                        raise ValueError(
                            "alert expiry/configuration differs from recorded provenance"
                        )
                    event = session.scalar(
                        select(AlertEvent)
                        .where(AlertEvent.alert_id == alert.id)
                        .order_by(AlertEvent.seq.desc())
                        .limit(1)
                    )
                    if event is None or event.created_at > now:
                        raise ValueError("alert lifecycle is unavailable or future")
                    mapping: dict[str, Disposition] = {
                        "PENDING": "PENDING",
                        "SENT": "PENDING",
                        "APPROVED": "APPROVED",
                        "REJECTED": "REJECTED",
                        "EXPIRED": "EXPIRED",
                        "REVALIDATION_FAILED": "REVALIDATION_FAILED",
                    }
                    status = mapping[event.state]
                    automatic = tuple(
                        session.scalars(
                            select(ExecutionOrderRecord)
                            .where(
                                ExecutionOrderRecord.order_id == order.id,
                                ExecutionOrderRecord.role == "ENTRY",
                            )
                            .limit(3)
                        )
                    )
                    if automatic:
                        from backend.execution.storage import entry_quantity

                        if len(automatic) > 2 or any(
                            row.account_id != scope.account_id
                            or row.environment != scope.cohort
                            or row.config_hash != provenance.settings_hash
                            or row.created_at > now
                            or type(row.qty) is not int
                            or not 1 <= row.qty <= order.qty
                            or (row.limit_price, row.stop_price)
                            != (order.limit_price, order.stop_price)
                            for row in automatic
                        ):
                            raise ValueError(
                                "auto tracker intent has unbound account, mode, quantity or levels"
                            )
                        # This is approval of the hypothetical setup, never a
                        # claim that its broker order actually filled.
                        status = "APPROVED"
                        quantity = entry_quantity(session, order.id)
                        if quantity is None or not 1 <= quantity <= order.qty:
                            raise ValueError("EX-01: bound aggregate entry quantity is unavailable")
                        approved_qty = quantity
                    fact = session.scalar(
                        select(ResearchReport)
                        .where(
                            ResearchReport.alert_id == alert.id,
                            ResearchReport.agent_name == "fundamentals",
                        )
                        .order_by(ResearchReport.seq.desc())
                        .limit(1)
                    )
                    if fact is not None:
                        report = FundamentalReport.from_recorded(fact.payload)
                        if report.symbol != order.symbol or report.as_of > now:
                            raise ValueError("fundamental report issuer/time differs")
                        fundamental = report.framework_status
                    identity = alert.id
                else:
                    veto = session.scalar(
                        select(RiskDecision)
                        .where(
                            RiskDecision.proposal_id == order.proposal_id,
                            RiskDecision.decision == "VETOED",
                        )
                        .order_by(RiskDecision.seq.desc())
                        .limit(1)
                    )
                    if veto is None:
                        continue
                    if veto.evaluated_at > now or veto.config_hash != provenance.settings_hash:
                        raise ValueError("CRO shadow risk evidence is unbound or future")
                    status = "CRO_VETO"
                    identity = uuid5(SHADOW_NAMESPACE, order.proposal_id.hex)
                    if candidate.size_evidence is not None:
                        approved_qty = candidate.size_evidence.base_qty
                valid = provenance.expires_at.astimezone(NY).date()
                if not calendar.is_session(valid):
                    raise ValueError("tracker validity is not an XNYS session")
                setups.append(
                    TrackedSetup(
                        provenance=provenance,
                        setup=OutcomeSetup(
                            alert_id=identity,
                            symbol=order.symbol,
                            playbook=candidate.playbook,
                            cohort=scope.cohort,
                            disposition=status,
                            fundamentals_status=fundamental,
                            score=candidate.score,
                            qty=approved_qty,
                            limit=order.limit_price,
                            stop=cast(Decimal, order.stop_price),
                            target=cast(Decimal, order.target_price),
                            decision_session=day,
                            valid_until_session=valid,
                        ),
                    )
                )
                factors = candidate.size_evidence
                if factors is not None and (
                    factors.base_qty > approved_qty or status == "CRO_VETO"
                ):
                    filters = reduction_filters(
                        factors, accepted_qty=0 if status == "CRO_VETO" else approved_qty
                    )
                    for filtered in filters:
                        if filtered == status:
                            continue  # The original CRO-veto cohort already records this cause.
                        # Overlapping counterfactuals retain one immutable base.
                        # They are hypothetical outcomes, never approvals/fills.
                        shadow = OutcomeSetup.model_validate(
                            {
                                **setups[-1].setup.model_dump(),
                                "alert_id": uuid5(
                                    SHADOW_NAMESPACE, f"{order.proposal_id}/{filtered}"
                                ),
                                "disposition": filtered,
                                "qty": factors.base_qty,
                            }
                        )
                        setups.append(TrackedSetup(setup=shadow, provenance=provenance))
            records = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "FILTER_SHADOW")
                    .order_by(SecurityEvent.seq)
                    .limit(MAX_TRACKED_SETUPS + 1)
                )
            )
            if len(records) > MAX_TRACKED_SETUPS:
                raise DataIntegrityError("ER-04: filtered setup inventory exceeds its bound")
            for filter_event in records:
                zero_shadow = FilterShadow.recorded(filter_event.detail)
                if (
                    zero_shadow.scope.account_id != scope.account_id
                    or zero_shadow.scope.environment != scope.cohort
                ):
                    continue
                candidate, provenance = zero_shadow.candidate, zero_shadow.provenance
                day = candidate.as_of.astimezone(NY).date()
                if not scope.start <= day <= scope.end:
                    continue
                source = session.get(DataSnapshot, zero_shadow.data_snapshot_id)
                if (
                    source is None
                    or source.symbol != candidate.symbol
                    or source.seq >= filter_event.seq
                    or source.fetched_at > candidate.as_of
                    or candidate.as_of > filter_event.created_at
                    or filter_event.created_at > now
                    or provenance.settings_hash != policy.config_hash
                    or provenance.yaml_hash != scope.config_sha256
                ):
                    raise DataIntegrityError("ER-04: filter source/configuration is unbound")
                for name in zero_shadow.cohorts:
                    setups.append(
                        TrackedSetup(
                            provenance=provenance,
                            setup=OutcomeSetup(
                                alert_id=uuid5(SHADOW_NAMESPACE, f"{zero_shadow.identity}/{name}"),
                                symbol=candidate.symbol,
                                playbook=candidate.playbook,
                                cohort=scope.cohort,
                                disposition=name,
                                fundamentals_status=FrameworkStatus.INCOMPLETE,
                                score=candidate.score,
                                qty=zero_shadow.factors.base_qty,
                                limit=candidate.entry_price,
                                stop=candidate.stop_price,
                                target=candidate.target_price,
                                decision_session=day,
                                valid_until_session=provenance.expires_at.astimezone(NY).date(),
                            ),
                        )
                    )
        if len(setups) > MAX_TRACKED_SETUPS:
            raise DataIntegrityError("ER-04: alert plus counterfactual count exceeds its bound")
        return tuple(
            sorted(
                setups,
                key=lambda item: (
                    item.setup.decision_session,
                    item.setup.symbol,
                    item.setup.alert_id.hex,
                ),
            )
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-01: ledger tracker evidence is unverifiable") from None


def collect_outcome_setups(
    ledger: Ledger, settings: Settings, context: ReportContext, calendar: MarketCalendar
) -> tuple[OutcomeSetup, ...]:
    return tuple(item.setup for item in collect_tracked_setups(ledger, settings, context, calendar))
