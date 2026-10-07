"""EV-01: pure, fee-inclusive hypothetical outcomes for every alert cohort.

The amended CM rules replace the older fill and time-stop rules. R divides net
P&L by the recorded limit-to-stop risk of the shares actually filled. Dividends
are excluded. Split prices verify continuity; raw audit bars keep native cents,
whole shares, participation and dated fees correct. Recorded levels never change.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Literal, Self, cast
from uuid import UUID

from pydantic import Field, model_validator

from backend.agents.fundamentals import FrameworkStatus
from backend.core.config import EvaluationConfig
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.data_layer import _provider_money
from backend.data.history import Digest, FrozenHistory, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    FrozenModel,
    Money,
    Playbook,
    PositiveQty,
    Price,
    SessionDate,
    Side,
    Symbol,
)
from backend.evaluation.costs import (
    CostContext,
    CostOrder,
    Exact,
    FeeBreakdown,
    FeeSchedule,
    FillResult,
    Note,
    cost_policy_sha256,
    estimate_fill,
    fees,
)
from backend.evaluation.dividends import (
    NOTICE as DISTRIBUTION_NOTICE,
)
from backend.evaluation.dividends import (
    DistributionCredit,
    distribution_credit,
    distribution_rates,
)

MICRO = Decimal("0.000001")
ZERO = Decimal(0)
NOTES = (
    "Hypothetical/past results; not indicative of future returns.",
    "Dividends ignored; MAE/MFE are daily-bar price bounds before fees and may include prices outside the holding interval.",
)
REPLAY_NOTES = (NOTES[0], DISTRIBUTION_NOTICE)
Cohort = Literal["PAPER", "LIVE", "REPLAY_IN_SAMPLE", "REPLAY_OOS"]
Disposition = Literal[
    "APPROVED",
    "REJECTED",
    "EXPIRED",
    "PENDING",
    "REVALIDATION_FAILED",
    "CRO_VETO",
    "RS_FILTER",
    "PR_FILTER",
    "SZ_FILTER",
]
ExitReason = Literal[
    "STOP",
    "GAP_STOP",
    "TARGET",
    "TIME",
    "SIGNAL",
    "ALERT_UNFILLED",
    "ENTRY_HALTED",
    "HISTORY_PENDING",
    "FRACTIONAL_SPLIT",
    "SUBCENT_SPLIT",
]


class OutcomeSetup(FrozenModel):
    alert_id: UUID
    symbol: Symbol
    playbook: Playbook
    variant: str = Field(default="baseline", strict=True, pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    cohort: Cohort
    disposition: Disposition
    fundamentals_status: FrameworkStatus
    score: Money = Field(ge=1, le=10)
    qty: PositiveQty = Field(le=10**9)
    limit: Price
    stop: Price
    target: Price
    decision_session: SessionDate
    valid_until_session: SessionDate

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            not self.stop < self.limit < self.target
            or self.valid_until_session < self.decision_session
        ):
            raise ValueError("EV-01: ordered long levels and non-reversed validity required")
        return self


class Outcome(FrozenModel):
    setup: OutcomeSetup
    manifest_sha256: Digest
    fee_schedule_sha256: Digest
    cost_policy_sha256: Digest
    status: Literal["NOT_FILLED", "OPEN", "RESOLVED", "INCOMPLETE"]
    reason: ExitReason
    entry_session: SessionDate | None
    exit_session: SessionDate | None
    entry_fill: FillResult | None
    exit_fill: FillResult | None
    entry_fees: FeeBreakdown | None
    exit_fees: FeeBreakdown | None
    entry_basis_ratio: Exact | None = Field(gt=0)
    initial_risk_money: Money | None = Field(ge=0)
    net_money: Money | None
    r_multiple: Exact | None
    mae_money: Money | None = Field(le=0)
    mfe_money: Money | None = Field(ge=0)
    sessions_held: int = Field(strict=True, ge=0, le=31)
    distributions: tuple[DistributionCredit, ...] = Field(default=(), max_length=30)
    notes: tuple[Note, ...] = Field(default=NOTES, min_length=2, max_length=2)

    @classmethod
    def from_recorded(cls, payload: dict[str, Any]) -> Outcome:
        """Decode explicit canonical dates/prices, then reconstruct the full schema."""
        try:
            values = dict(payload)
            intent = dict(values["setup"])
            for name in ("decision_session", "valid_until_session"):
                intent[name] = date.fromisoformat(intent[name])
            for name in ("limit", "stop", "target"):
                intent[name] = _provider_money(intent[name])
            values["setup"] = intent
            for name in ("entry_session", "exit_session"):
                values[name] = None if values[name] is None else date.fromisoformat(values[name])
            for name in ("entry_fill", "exit_fill"):
                if values[name] is not None:
                    fill = dict(values[name])
                    fill["price"] = (
                        None if fill["price"] is None else _provider_money(fill["price"])
                    )
                    values[name] = fill
            values["distributions"] = tuple(
                {**row, "session": date.fromisoformat(row["session"])}
                for row in values.get("distributions", ())
            )
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("EV-01: recorded outcome is unverifiable") from None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        entry = self.entry_fill
        replay = self.setup.cohort.startswith("REPLAY")
        if self.notes != (REPLAY_NOTES if replay else NOTES) or (entry is None) != (
            self.entry_basis_ratio is None
        ):
            raise ValueError("EV-01: fixed disclosures and entry split basis are required")
        days = tuple(item.session for item in self.distributions)
        if (
            days != tuple(sorted(set(days)))
            or (self.distributions and not replay)
            or any(
                self.entry_session is None
                or not self.entry_session < item.session
                or (self.exit_session is not None and item.session > self.exit_session)
                for item in self.distributions
            )
        ):
            raise ValueError("DQ-01: distributions require preceding held replay shares")
        if (entry is None) != (self.entry_session is None) or (entry is None) != (
            self.entry_fees is None
        ):
            raise ValueError("EV-01: entry evidence must be complete")
        if entry is not None and (entry.qty <= 0 or entry.price is None):
            raise ValueError("EV-01: entry evidence must show a fill")
        if (self.exit_fill is None) != (self.exit_session is None) or (self.exit_fill is None) != (
            self.exit_fees is None
        ):
            raise ValueError("EV-01: exit evidence must be complete")
        if (
            self.entry_session is not None
            and not self.setup.decision_session
            < self.entry_session
            <= self.setup.valid_until_session
        ):
            raise ValueError("EV-01: fill must follow the decision within validity")
        if self.exit_session is not None and (
            self.entry_session is None or self.exit_session < self.entry_session
        ):
            raise ValueError("EV-01: exit must follow entry")
        if self.status == "RESOLVED":
            if (
                any(
                    value is None
                    for value in (
                        entry,
                        self.exit_fill,
                        self.entry_fees,
                        self.exit_fees,
                        self.initial_risk_money,
                        self.net_money,
                        self.r_multiple,
                        self.mae_money,
                        self.mfe_money,
                    )
                )
                or self.sessions_held == 0
            ):
                raise ValueError("EV-01: resolved result requires complete fill/cost/risk evidence")
            incoming, outgoing = cast(FillResult, entry), cast(FillResult, self.exit_fill)
            if outgoing.qty <= 0 or outgoing.price is None or outgoing.status != "FILLED":
                raise ValueError("EV-01: exit must cover all modeled held shares")
            with localcontext() as precision:
                precision.prec = 80
                risk = (
                    (self.setup.limit - self.setup.stop)
                    * incoming.qty
                    / cast(Decimal, self.entry_basis_ratio)
                )
                net = (
                    outgoing.price * outgoing.qty
                    - cast(Decimal, incoming.price) * incoming.qty
                    - cast(FeeBreakdown, self.entry_fees).total
                    - cast(FeeBreakdown, self.exit_fees).total
                    + sum((item.amount for item in self.distributions), ZERO)
                )
                if (
                    self.initial_risk_money != risk
                    or self.net_money != net
                    or self.r_multiple != (net / risk).quantize(MICRO, rounding=ROUND_HALF_EVEN)
                ):
                    raise ValueError("EV-01: net result or R differs from recorded fills and fees")
            if (
                self.reason not in {"STOP", "GAP_STOP", "TARGET", "TIME", "SIGNAL"}
                or outgoing.reason != self.reason
            ):
                raise ValueError("EV-01: exit reason must follow the shared cost model")
        elif any(
            value is not None
            for value in (
                self.exit_fill,
                self.exit_session,
                self.exit_fees,
                self.net_money,
                self.r_multiple,
            )
        ):
            raise ValueError("EV-01: unresolved evidence cannot claim a realized result")
        if self.status == "NOT_FILLED" and (
            entry is not None
            or self.reason not in {"ALERT_UNFILLED", "ENTRY_HALTED"}
            or self.sessions_held
        ):
            raise ValueError("EV-01: not-filled result cannot have exposure")
        if self.status == "OPEN" and (entry is None or self.reason != "HISTORY_PENDING"):
            raise ValueError("EV-01: open result requires entry and pending history")
        if self.status == "INCOMPLETE" and self.reason not in {
            "HISTORY_PENDING",
            "FRACTIONAL_SPLIT",
            "SUBCENT_SPLIT",
        }:
            raise ValueError("EV-01: incomplete results need unavailable evidence")
        return self


def simulate_outcome(
    setup: OutcomeSetup,
    history: FrozenHistory,
    context: CostContext,
    calendar: MarketCalendar,
    schedule: FeeSchedule,
    *,
    policy: EvaluationConfig | None = None,
    signal_exit_session: date | None = None,
    cancel_entry_at: date | None = None,
) -> Outcome:
    """EV-01: no I/O, no trades, no discretion or model output changes the rules."""
    try:
        intent = OutcomeSetup.model_validate(setup)
        frozen = FrozenHistory.model_validate(history)
        checked_context = CostContext.model_validate(context)
        checked_schedule = FeeSchedule.model_validate(schedule)
        hold = EvaluationConfig.model_validate(policy or EvaluationConfig())
        validate_history(frozen.bundle, calendar)
        calendar.session_open(intent.decision_session)
        calendar.session_open(intent.valid_until_session)
        if cancel_entry_at is not None:
            if type(cancel_entry_at) is not date or cancel_entry_at < intent.decision_session:
                raise DataIntegrityError("EV-01: entry cancellation needs a non-past session")
            calendar.session_close(cancel_entry_at)
        if signal_exit_session is not None:
            if (
                type(signal_exit_session) is not date
                or signal_exit_session < intent.decision_session
            ):
                raise DataIntegrityError(
                    "EV-01: signal exit needs a session at or after the decision"
                )
            calendar.session_close(signal_exit_session)
        return _simulate(
            intent,
            frozen,
            checked_context,
            checked_schedule,
            hold,
            signal_exit_session,
            cancel_entry_at=cancel_entry_at,
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-01: invalid outcome evidence; no result inferred") from None


def _simulate(
    setup: OutcomeSetup,
    history: FrozenHistory,
    context: CostContext,
    schedule: FeeSchedule,
    policy: EvaluationConfig,
    signal_exit_session: date | None,
    end_session: date | None = None,
    cancel_entry_at: date | None = None,
    distribution_evidence: dict[date, Decimal] | None = None,
) -> Outcome:
    """Internal replay reuse after its public boundary validates the sealed bundle."""
    native = history.bundle.for_symbol(setup.symbol, "RAW")
    replay = setup.cohort.startswith("REPLAY")
    rates = (
        (
            distribution_rates(history, setup.symbol, end_session)
            if distribution_evidence is None
            else distribution_evidence
        )
        if replay
        else {}
    )
    distributions: list[DistributionCredit] = []
    if setup.decision_session not in native.sessions:
        raise DataIntegrityError("EV-01: decision session is absent from frozen history")
    actions = {
        item.effective_session: item.new_shares_per_old
        for item in history.bundle.splits
        if item.symbol == setup.symbol
    }
    qty, limit, stop, target = setup.qty, setup.limit, setup.stop, setup.target
    entry: FillResult | None = None
    entry_day: date | None = None
    entry_cost: FeeBreakdown | None = None
    entry_value: Decimal = ZERO
    risk: Decimal | None = None
    basis = Decimal(1)
    entry_basis: Decimal | None = None
    mae: Decimal | None = None
    mfe: Decimal | None = None
    held = 0
    pending: Literal["TIME", "SIGNAL"] | None = None
    pending_day: date | None = None

    def result(
        status: Literal["NOT_FILLED", "OPEN", "RESOLVED", "INCOMPLETE"],
        reason: ExitReason,
        outgoing: FillResult | None = None,
        day: date | None = None,
    ) -> Outcome:
        exit_cost = None
        net = None
        multiple = None
        if outgoing is not None:
            exit_cost = fees(
                Side.SELL,
                outgoing.qty,
                cast(Decimal, outgoing.price),
                cast(date, day),
                schedule=schedule,
            )
            net = (
                cast(Decimal, outgoing.price) * outgoing.qty
                - entry_value
                - cast(FeeBreakdown, entry_cost).total
                - exit_cost.total
                + sum((item.amount for item in distributions), ZERO)
            )
            multiple = (net / cast(Decimal, risk)).quantize(MICRO, rounding=ROUND_HALF_EVEN)
        return Outcome(
            setup=setup,
            manifest_sha256=history.manifest.sha256,
            fee_schedule_sha256=schedule.sha256,
            cost_policy_sha256=cost_policy_sha256(context.policy),
            status=status,
            reason=reason,
            entry_session=entry_day,
            exit_session=day,
            entry_fill=entry,
            exit_fill=outgoing,
            entry_fees=entry_cost,
            exit_fees=exit_cost,
            entry_basis_ratio=entry_basis,
            initial_risk_money=risk,
            net_money=net,
            r_multiple=multiple,
            mae_money=mae,
            mfe_money=mfe,
            sessions_held=held,
            distributions=tuple(distributions),
            notes=REPLAY_NOTES if replay else NOTES,
        )

    with localcontext() as precision:
        precision.prec = 80
        for bar in native.bars:
            day = bar.session_date
            if end_session is not None and day > end_session:
                break
            if day <= setup.decision_session:
                continue
            if entry is None and day > setup.valid_until_session:
                return result("NOT_FILLED", "ALERT_UNFILLED")
            if entry is None and cancel_entry_at is not None and day > cancel_entry_at:
                return result("NOT_FILLED", "ENTRY_HALTED")
            ratio = actions.get(day)
            if ratio is not None:
                shares = qty * ratio
                if shares != shares.to_integral_value() or not 1 <= shares <= 10**9:
                    return result("INCOMPLETE", "FRACTIONAL_SPLIT")
                levels = (limit / ratio, stop / ratio, target / ratio, context.atr14 / ratio)
                if any(value != value.quantize(CENT) for value in levels):
                    return result("INCOMPLETE", "SUBCENT_SPLIT")
                qty = int(shares)
                basis *= ratio
                limit, stop, target, atr = levels
                context = CostContext.model_validate({**context.model_dump(), "atr14": atr})
            if entry is not None:
                credit = distribution_credit(day, qty, rates.get(day))
                if credit is not None:
                    distributions.append(credit)
            if entry is None:
                incoming = estimate_fill(
                    CostOrder(
                        side=Side.BUY,
                        kind="ENTRY",
                        qty=qty,
                        level=limit,
                        decision_session=setup.decision_session,
                    ),
                    bar,
                    context,
                )
                if incoming.qty == 0:
                    continue
                entry, entry_day, qty = incoming, day, incoming.qty
                entry_basis = basis
                entry_cost = fees(
                    Side.BUY, qty, cast(Decimal, incoming.price), day, schedule=schedule
                )
                entry_value = cast(Decimal, incoming.price) * qty
                risk = (limit - stop) * qty
                mae, mfe = ZERO, ZERO
            stopped = estimate_fill(
                CostOrder(
                    side=Side.SELL,
                    kind="STOP",
                    qty=qty,
                    level=stop,
                    decision_session=cast(date, entry_day),
                ),
                bar,
                context,
            )
            if pending is not None and stopped.reason != "GAP_STOP":
                outgoing = estimate_fill(
                    CostOrder(
                        side=Side.SELL,
                        kind=pending,
                        qty=qty,
                        decision_session=cast(date, pending_day),
                    ),
                    bar,
                    context,
                )
                mae = min(cast(Decimal, mae), bar.open * qty - entry_value)
                mfe = max(cast(Decimal, mfe), bar.open * qty - entry_value)
                return result("RESOLVED", pending, outgoing, day)
            held += 1
            mae = min(
                cast(Decimal, mae),
                (bar.open if stopped.reason == "GAP_STOP" else bar.low) * qty - entry_value,
            )
            mfe = max(
                cast(Decimal, mfe),
                (bar.open if stopped.reason == "GAP_STOP" else bar.high) * qty - entry_value,
            )
            if stopped.qty:
                return result("RESOLVED", cast(ExitReason, stopped.reason), stopped, day)
            targeted = estimate_fill(
                CostOrder(
                    side=Side.SELL,
                    kind="TARGET",
                    qty=qty,
                    level=target,
                    decision_session=cast(date, entry_day),
                ),
                bar,
                context,
            )
            if targeted.qty:
                return result("RESOLVED", "TARGET", targeted, day)
            if day == signal_exit_session:
                pending, pending_day = "SIGNAL", day
            elif held >= policy.max_hold_sessions:
                pending, pending_day = "TIME", day
        if entry is not None:
            return result("OPEN", "HISTORY_PENDING")
        if cancel_entry_at is not None:
            return result("NOT_FILLED", "ENTRY_HALTED")
        if (
            min(native.sessions[-1], end_session or native.sessions[-1])
            >= setup.valid_until_session
        ):
            return result("NOT_FILLED", "ALERT_UNFILLED")
        return result("INCOMPLETE", "HISTORY_PENDING")
