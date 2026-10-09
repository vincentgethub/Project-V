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
    ExecutionOrderRecord,
    Order,
    ResearchReport,
    RiskDecision,
    Signal,
    transaction,
)
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.data_layer import _provider_money
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, SetupCandidate
from backend.evaluation.outcomes import Disposition, OutcomeSetup
from backend.evaluation.provenance import EvaluationProvenance
from backend.evaluation.weekly import ReportContext

NY = ZoneInfo("America/New_York")
SHADOW_NAMESPACE = UUID("cfa2f9b5-d014-49bd-88e5-d03a5857d21f")


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
                    .limit(100001)
                )
            )
            if len(orders) > 100000:
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
                    automatic = session.scalar(
                        select(ExecutionOrderRecord).where(
                            ExecutionOrderRecord.order_id == order.id,
                            ExecutionOrderRecord.role == "ENTRY",
                        )
                    )
                    if automatic is not None:
                        if (
                            automatic.account_id != scope.account_id
                            or automatic.environment != scope.cohort
                            or automatic.config_hash != provenance.settings_hash
                            or automatic.created_at > now
                            or type(automatic.qty) is not int
                            or not 1 <= automatic.qty <= order.qty
                            or (automatic.limit_price, automatic.stop_price, automatic.target_price)
                            != (order.limit_price, order.stop_price, order.target_price)
                        ):
                            raise ValueError(
                                "auto tracker intent has unbound account, mode, quantity or levels"
                            )
                        # This is approval of the hypothetical setup, never a
                        # claim that its broker order actually filled.
                        status = "APPROVED"
                        approved_qty = automatic.qty
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
