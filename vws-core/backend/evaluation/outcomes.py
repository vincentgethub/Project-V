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
from backend.indicators.portfolio import causal_split_atr, causal_split_ema

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
ExitVariant = Literal["BASELINE", "SPLIT_1R", "SPLIT_1R_TRAIL", "TRAIL_EMA20"]
EXIT_VARIANTS = frozenset({"BASELINE", "SPLIT_1R", "SPLIT_1R_TRAIL", "TRAIL_EMA20"})


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
    context_tags: tuple[str, ...] = Field(
        default=(), max_length=21, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            not self.stop < self.limit < self.target
            or self.valid_until_session < self.decision_session
        ):
            raise ValueError("EV-01: ordered long levels and non-reversed validity required")
        from backend.realtime.models import ContextTag

        if len(set(self.context_tags)) != len(self.context_tags) or any(
            value not in {tag.value for tag in ContextTag} for value in self.context_tags
        ):
            raise ValueError("RT-12: closed unique realtime context taxonomy required")
        return self


class PartialExit(FrozenModel):
    """EX-01: immutable A-leg cash flow; shares use that day's native basis."""

    session: SessionDate
    fill: FillResult
    fees: FeeBreakdown
    basis_ratio: Exact = Field(gt=0)

    @model_validator(mode="after")
    def filled(self) -> Self:
        if self.fill.status != "FILLED" or self.fill.qty <= 0 or self.fill.reason != "TARGET":
            raise ValueError("EX-01: A requires a complete target fill")
        return self


class StopMove(FrozenModel):
    decided_session: SessionDate
    effective_session: SessionDate
    old_stop: Price
    new_stop: Price
    basis_ratio: Exact = Field(gt=0)

    @model_validator(mode="after")
    def upward(self) -> Self:
        if self.decided_session >= self.effective_session or self.new_stop <= self.old_stop:
            raise ValueError("EX-02: upward stop decision applies after its close")
        return self


def _combined_fees(parts: tuple[FeeBreakdown, ...]) -> FeeBreakdown:
    return FeeBreakdown(
        commission=sum((row.commission for row in parts), ZERO),
        sec=sum((row.sec for row in parts), ZERO),
        taf=sum((row.taf for row in parts), ZERO),
        cat=sum((row.cat for row in parts), ZERO),
        source="MODELED",
    )


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
    partial_exits: tuple[PartialExit, ...] = Field(
        default=(), max_length=1, exclude_if=lambda v: not v
    )
    stop_moves: tuple[StopMove, ...] = Field(default=(), max_length=30, exclude_if=lambda v: not v)
    exit_basis_ratio: Exact | None = Field(default=None, gt=0, exclude_if=lambda v: v is None)
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
            values["partial_exits"] = tuple(
                {
                    **row,
                    "session": date.fromisoformat(row["session"]),
                    "fill": {**row["fill"], "price": _provider_money(row["fill"]["price"])},
                }
                for row in values.get("partial_exits", ())
            )
            values["stop_moves"] = tuple(
                {
                    **row,
                    "decided_session": date.fromisoformat(row["decided_session"]),
                    "effective_session": date.fromisoformat(row["effective_session"]),
                    "old_stop": _provider_money(row["old_stop"]),
                    "new_stop": _provider_money(row["new_stop"]),
                }
                for row in values.get("stop_moves", ())
            )
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("EV-01: recorded outcome is unverifiable") from None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        entry = self.entry_fill
        replay = self.setup.cohort.startswith("REPLAY")
        split = self.setup.variant in {"SPLIT_1R", "SPLIT_1R_TRAIL"}
        if (self.partial_exits and not split) or (
            self.stop_moves and self.setup.variant != "SPLIT_1R_TRAIL"
        ):
            raise ValueError("EX: leg and stop evidence requires its recorded variant")
        if any(
            self.entry_session is None
            or row.session < self.entry_session
            or (self.exit_session is not None and row.session > self.exit_session)
            for row in self.partial_exits
        ):
            raise ValueError("EX-01: partial exit must be inside the holding interval")
        if any(
            self.entry_session is None
            or row.decided_session < self.entry_session
            or (self.exit_session is not None and row.effective_session > self.exit_session)
            for row in self.stop_moves
        ) or any(
            a.effective_session >= b.effective_session
            or a.new_stop * a.basis_ratio > b.old_stop * b.basis_ratio
            for a, b in zip(self.stop_moves, self.stop_moves[1:], strict=False)
        ):
            raise ValueError("EX-02: stop evidence must be ordered and never lowered")
        if self.stop_moves and (
            not self.partial_exits
            or self.stop_moves[0].decided_session < self.partial_exits[0].session
        ):
            raise ValueError("EX-02: A must fill before B trails")
        if self.notes != (REPLAY_NOTES if replay else NOTES) or (entry is None) != (
            self.entry_basis_ratio is None
        ):
            raise ValueError("EV-01: fixed disclosures and entry split basis are required")
        if self.partial_exits and (
            entry is None
            or self.entry_basis_ratio is None
            or sum((Decimal(row.fill.qty) / row.basis_ratio for row in self.partial_exits), ZERO)
            >= entry.qty / self.entry_basis_ratio
        ):
            raise ValueError("EX-01: the A exit must leave held B shares")
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
                    + sum(
                        (
                            cast(Decimal, row.fill.price) * row.fill.qty - row.fees.total
                            for row in self.partial_exits
                        ),
                        ZERO,
                    )
                )
                if split and (
                    self.exit_basis_ratio is None
                    or sum(
                        (Decimal(row.fill.qty) / row.basis_ratio for row in self.partial_exits),
                        ZERO,
                    )
                    + outgoing.qty / self.exit_basis_ratio
                    != incoming.qty / cast(Decimal, self.entry_basis_ratio)
                ):
                    raise ValueError("EX-01: exits must conserve split-adjusted filled shares")
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
    exit_variant: ExitVariant = "BASELINE",
) -> Outcome:
    """EV-01: no I/O, no trades, no discretion or model output changes the rules."""
    try:
        intent = OutcomeSetup.model_validate(setup)
        frozen = FrozenHistory.model_validate(history)
        checked_context = CostContext.model_validate(context)
        checked_schedule = FeeSchedule.model_validate(schedule)
        hold = EvaluationConfig.model_validate(policy or EvaluationConfig())
        if exit_variant not in EXIT_VARIANTS or (
            exit_variant != "BASELINE" and intent.variant != exit_variant
        ):
            raise DataIntegrityError("EX-03: recorded and supported exit variant required")
        if exit_variant.startswith("SPLIT_") and intent.qty < 2:
            raise DataIntegrityError("EX-01: split entry needs at least two shares")
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
            exit_variant=exit_variant,
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
    exit_variant: ExitVariant = "BASELINE",
    close_exit_ema: dict[date, Decimal | None] | None = None,
    close_trail_atr: dict[date, Decimal | None] | None = None,
) -> Outcome:
    """Internal replay reuse after its public boundary validates the sealed bundle."""
    native = history.bundle.for_symbol(setup.symbol, "RAW")
    if exit_variant == "TRAIL_EMA20" and close_exit_ema is None:
        close_exit_ema = causal_split_ema(
            native, history.bundle.splits, 20, end_session or native.sessions[-1]
        )
    if exit_variant == "SPLIT_1R_TRAIL" and close_trail_atr is None:
        close_trail_atr = causal_split_atr(
            native, history.bundle.splits, end_session or native.sessions[-1]
        )
    split = exit_variant in {"SPLIT_1R", "SPLIT_1R_TRAIL"}
    if split and setup.qty < 2:
        raise DataIntegrityError("EX-01: split entry needs at least two shares")
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
    partial_exits: list[PartialExit] = []
    stop_moves: list[StopMove] = []
    a_qty = 0
    a_target = limit + (limit - stop)
    realized_gross = ZERO
    pending_stop: tuple[date, Decimal] | None = None

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
            if split and a_qty:
                exit_cost = _combined_fees(
                    tuple(
                        fees(
                            Side.SELL,
                            shares,
                            cast(Decimal, outgoing.price),
                            cast(date, day),
                            schedule=schedule,
                        )
                        for shares in (a_qty, qty - a_qty)
                        if shares
                    )
                )
            net = (
                cast(Decimal, outgoing.price) * outgoing.qty
                - entry_value
                - cast(FeeBreakdown, entry_cost).total
                - exit_cost.total
                + sum((item.amount for item in distributions), ZERO)
                + realized_gross
                - sum((row.fees.total for row in partial_exits), ZERO)
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
            partial_exits=tuple(partial_exits),
            stop_moves=tuple(stop_moves),
            exit_basis_ratio=basis if split and outgoing is not None else None,
        )

    if exit_variant == "TRAIL_EMA20" and (
        close_exit_ema is None or close_exit_ema.get(setup.decision_session) is None
    ):
        return result("INCOMPLETE", "HISTORY_PENDING")
    if exit_variant == "SPLIT_1R_TRAIL" and (
        close_trail_atr is None or close_trail_atr.get(setup.decision_session) is None
    ):
        return result("INCOMPLETE", "HISTORY_PENDING")

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
                a_shares = a_qty * ratio
                if a_shares != a_shares.to_integral_value():
                    return result("INCOMPLETE", "FRACTIONAL_SPLIT")
                a_qty = int(a_shares)
                basis *= ratio
                limit, stop, target, atr = levels
                a_target /= ratio
                if pending_stop is not None:
                    pending_stop = (pending_stop[0], pending_stop[1] / ratio)
                context = CostContext.model_validate({**context.model_dump(), "atr14": atr})
            if pending_stop is not None and day > pending_stop[0]:
                decided, raised = pending_stop
                if raised != raised.quantize(CENT):
                    return result("INCOMPLETE", "SUBCENT_SPLIT")
                # Revalidate every queued raise, including its strict upward
                # direction. Corrupt protection must fail, not disappear.
                stop_moves.append(
                    StopMove(
                        decided_session=decided,
                        effective_session=day,
                        old_stop=stop,
                        new_stop=raised,
                        basis_ratio=basis,
                    )
                )
                stop = raised
                pending_stop = None
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
                if split:
                    a_qty = qty // 2
                    parts = tuple(
                        fees(
                            Side.BUY, shares, cast(Decimal, incoming.price), day, schedule=schedule
                        )
                        for shares in (a_qty, qty - a_qty)
                        if shares
                    )
                    entry_cost = _combined_fees(parts)
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
                mae = min(cast(Decimal, mae), realized_gross + bar.open * qty - entry_value)
                mfe = max(cast(Decimal, mfe), realized_gross + bar.open * qty - entry_value)
                return result("RESOLVED", pending, outgoing, day)
            held += 1
            mae = min(
                cast(Decimal, mae),
                realized_gross
                + (bar.open if stopped.reason == "GAP_STOP" else bar.low) * qty
                - entry_value,
            )
            mfe = max(
                cast(Decimal, mfe),
                realized_gross
                + (bar.open if stopped.reason == "GAP_STOP" else bar.high) * qty
                - entry_value,
            )
            if stopped.qty:
                return result("RESOLVED", cast(ExitReason, stopped.reason), stopped, day)
            if split and a_qty:
                a_fill = estimate_fill(
                    CostOrder(
                        side=Side.SELL,
                        kind="TARGET",
                        qty=a_qty,
                        level=a_target,
                        decision_session=cast(date, entry_day),
                    ),
                    bar,
                    context,
                )
                if a_fill.qty:
                    partial_exits.append(
                        PartialExit(
                            session=day,
                            fill=a_fill,
                            fees=fees(
                                Side.SELL,
                                a_qty,
                                cast(Decimal, a_fill.price),
                                day,
                                schedule=schedule,
                            ),
                            basis_ratio=basis,
                        )
                    )
                    realized_gross += cast(Decimal, a_fill.price) * a_qty
                    qty -= a_qty
                    a_qty = 0
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
            if targeted.qty and exit_variant != "SPLIT_1R_TRAIL":
                return result("RESOLVED", "TARGET", targeted, day)
            if exit_variant == "SPLIT_1R_TRAIL" and partial_exits:
                atr_value = None if close_trail_atr is None else close_trail_atr.get(day)
                if atr_value is None:
                    return result("INCOMPLETE", "HISTORY_PENDING")
                raised = bar.close - Decimal(3) * atr_value
                if raised > stop:
                    pending_stop = (day, raised)
            if day == signal_exit_session:
                pending, pending_day = "SIGNAL", day
            elif exit_variant == "TRAIL_EMA20" and mfe >= cast(Decimal, risk):
                average = None if close_exit_ema is None else close_exit_ema.get(day)
                if average is None:
                    return result("INCOMPLETE", "HISTORY_PENDING")
                if bar.close < average:
                    pending, pending_day = "SIGNAL", day
                elif held >= policy.max_hold_sessions:
                    pending, pending_day = "TIME", day
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
