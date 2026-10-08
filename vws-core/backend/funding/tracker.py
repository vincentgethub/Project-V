"""FN-02..05: durable activity deduplication and CRO baselines share a transaction."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy import select

from backend.core.database import CashFlow, PortfolioState, SecurityEvent, transaction
from backend.core.errors import DataIntegrityError, ReconciliationError
from backend.core.system_state import SystemState, SystemStateStore
from backend.funding.models import CORPORATE_TYPES, EXTERNAL_TYPES, Activity


class FundingTracker:
    def __init__(
        self, state: SystemStateStore, account_id: str, env: Literal["PAPER", "LIVE"]
    ) -> None:
        if not account_id or len(account_id) > 128 or env not in {"PAPER", "LIVE"}:
            raise DataIntegrityError("FN-02: explicit activity account/environment required")
        self.state, self.account_id, self.env = state, account_id, env

    def record(
        self, activity: Activity, *, historical_inclusion: bool = False
    ) -> tuple[CashFlow, bool]:
        """Historical flows need an existing later snapshot, never an invented baseline.\n
        The startup complete-history capture declares inclusion explicitly. Later\n
        polls cannot use that exception to suppress a new observed external flow.
        """
        try:
            row = Activity.model_validate(activity)
            if (
                (row.account_id, row.env) != (self.account_id, self.env)
                or row.observed_at > self.state.clock.now()
                or type(historical_inclusion) is not bool
            ):
                raise DataIntegrityError("FN-02: observed activity binding/freshness differs")
            self.state.ledger.verify_chain()
            with transaction(self.state.engine) as session:
                duplicate = session.scalar(
                    select(CashFlow).where(
                        CashFlow.account_id == self.account_id,
                        CashFlow.env == self.env,
                        CashFlow.activity_id == row.activity_id,
                    )
                )
                if duplicate is not None:
                    if (
                        duplicate.payload_sha256 != row.payload_sha256
                        or Activity.from_payload(duplicate.payload).model_copy(
                            update={"observed_at": row.observed_at}
                        )
                        != row
                    ):
                        raise ReconciliationError(
                            "FN-02: same activity ID has conflicting evidence"
                        )
                    return duplicate, False
                effect = "NONE"
                portfolio: PortfolioState | None = None
                if row.type in EXTERNAL_TYPES:
                    prior = session.scalar(
                        select(PortfolioState)
                        .where(PortfolioState.account_id == self.account_id)
                        .order_by(PortfolioState.seq.desc())
                        .limit(1)
                    )
                    if prior is None:
                        raise ReconciliationError(
                            "FN-03: external flow has no verified equity baseline"
                        )
                    if historical_inclusion:
                        # A date-only broker posting can only establish inclusion when the
                        # entire calendar day precedes the opening observed snapshot.
                        if not (
                            row.occurred_at is not None
                            and row.occurred_at <= prior.as_of
                            or row.occurred_at is None
                            and row.source == "BROKER"
                            and row.observed_at <= prior.as_of
                            or row.occurred_at is None
                            and row.date < prior.as_of.date()
                        ):
                            raise ReconciliationError("FN-03: historical inclusion is unproven")
                        effect, portfolio = "INCLUDED", prior
                    else:
                        if row.occurred_at is None:
                            # Exact posting time is absent; the observation is the audited
                            # scaling time. A later broker snapshot must still reconcile.
                            instant = row.observed_at
                        else:
                            instant = row.occurred_at
                        portfolio = self.state.ledger.record_cash_flow_in_session(
                            session, self.account_id, row.amount, instant, prior.equity
                        )
                        effect = "SCALED"
                record = self.state.ledger.append_in_session(
                    session,
                    CashFlow,
                    account_id=self.account_id,
                    env=self.env,
                    activity_id=row.activity_id,
                    type=row.type,
                    amount=row.amount,
                    date=row.date.isoformat(),
                    payload_sha256=row.payload_sha256,
                    payload=row.model_dump(mode="json"),
                    baseline_effect=effect,
                    portfolio_state_id=None if portfolio is None else portfolio.id,
                )
                if row.type in CORPORATE_TYPES:
                    self.state.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="CORPORATE_ACTION_OBSERVED",
                        detail={
                            "account_id": self.account_id,
                            "cohort": self.env,
                            "activity_id": row.activity_id,
                            "type": row.type,
                            "symbol": row.symbol,
                            "payload_sha256": row.payload_sha256,
                        },
                    )
                return record, True
        except Exception:
            self.state.escalate(
                SystemState.HALTED, "FN-02/03: account activity could not be reconciled"
            )
            raise ReconciliationError("FN-02/03: activity rejected; system HALTED") from None

    @staticmethod
    def message(
        activity: Activity, buying_power: Decimal | None, *, mask: bool = False
    ) -> tuple[str, bool]:
        row = Activity.model_validate(activity)
        from backend.domain.models import _exact_money

        if type(mask) is not bool:
            raise DataIntegrityError("FN-04: masking flag must be explicit")
        if buying_power is not None:
            buying_power = _exact_money(buying_power)
            if buying_power < 0:
                raise DataIntegrityError("FN-04: negative buying power is unverified")
        amount = "$•••" if mask else f"${row.amount.copy_abs():,.2f}"
        if row.type == "CSW" or row.type == "JNLC" and row.amount < 0:
            return (
                f"⚠️ {row.env} · Withdrawal of {amount} detected; if this wasn't you, secure your broker account now",
                True,
            )
        if row.type == "CSD":
            available = (
                "UNVERIFIED"
                if buying_power is None
                else ("$•••" if mask else f"${buying_power:,.2f}")
            )
            return (
                f"💵 {row.env} · Deposit of {amount} detected · buying power now {available}",
                False,
            )
        return (
            f"{row.env} · Account activity {row.type} detected · {'$•••' if mask else f'${row.amount:,.2f}'}. Recorded for review.",
            False,
        )
