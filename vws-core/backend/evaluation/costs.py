"""CM-01..06: one pure hypothetical fill/fee model, exact at every boundary.

This module never reads files or sends orders. All callers supply the same dated
fee schedule and cost policy. Entry prices round up, exit prices round down;
fees round up per component per trade, conservatively versus broker daily totals.
"""

import hashlib
import json
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from typing import Annotated, Literal, Self, cast
from uuid import UUID

from pydantic import BeforeValidator, Field, model_validator

from backend.core.config import CostModelConfig, _bounded_exact_decimal
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT, decimal_money, validate_cent_price
from backend.data.data_layer import Bar
from backend.domain.models import FrozenModel, Money, PositiveQty, Price, SessionDate, Side
from backend.domain.tax_profile import TaxProfile

Exact = Annotated[Decimal, BeforeValidator(_bounded_exact_decimal)]
Note = Annotated[str, Field(strict=True, min_length=1, max_length=240)]
_ZERO = Decimal(0)
_BPS = Decimal(10000)


def cost_policy_sha256(policy: CostModelConfig) -> str:
    checked = CostModelConfig.model_validate(policy)
    encoded = json.dumps(
        checked.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


class CostOrder(FrozenModel):
    """Simulation intent only; a decision at close fills no earlier than t+1."""

    side: Side
    kind: Literal["ENTRY", "STOP", "TARGET", "TIME", "SIGNAL"]
    qty: PositiveQty = Field(le=10**9)
    level: Price | None = None
    decision_session: SessionDate

    @model_validator(mode="after")
    def long_only(self) -> Self:
        if (self.side == Side.BUY) != (self.kind == "ENTRY"):
            raise ValueError("CM: only long entries and held exits are modeled")
        if (self.level is not None) != (self.kind in {"ENTRY", "STOP", "TARGET"}):
            raise ValueError("CM: limit/stop/target require their exact level")
        return self


class CostContext(FrozenModel):
    median_dollar_volume_20: Money | None = Field(default=None, ge=0)
    measured_half_spread_bps: Exact | None = Field(default=None, ge=0, le=10000)
    atr14: Money = Field(ge=0)
    policy: CostModelConfig = Field(default_factory=CostModelConfig)

    @model_validator(mode="after")
    def cent_atr(self) -> Self:
        with localcontext() as precision:
            precision.prec = 256
            if self.atr14 != self.atr14.quantize(CENT):
                raise ValueError("CM: ATR14 must cross the indicator boundary in cents")
        return self


class FillResult(FrozenModel):
    status: Literal["NOT_FILLED", "PARTIAL", "FILLED"]
    requested_qty: PositiveQty
    qty: int = Field(strict=True, ge=0)
    price: Price | None
    reason: Literal[
        "OPEN_WITH_SPREAD",
        "TRADE_THROUGH",
        "NOT_TOUCHED",
        "VOLUME_CAP",
        "STOP",
        "GAP_STOP",
        "TARGET",
        "TIME",
        "SIGNAL",
    ]
    half_spread_bps: Exact = Field(ge=0, le=10000)
    notes: tuple[Note, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def quantity_status(self) -> Self:
        expected = (
            "NOT_FILLED"
            if self.qty == 0
            else "FILLED"
            if self.qty == self.requested_qty
            else "PARTIAL"
        )
        if (
            self.qty > self.requested_qty
            or self.status != expected
            or (self.price is None) != (self.qty == 0)
        ):
            raise ValueError("CM: fill status, quantity and price must agree")
        return self


def half_spread(ctx: CostContext) -> tuple[Decimal, tuple[str, ...]]:
    checked = CostContext.model_validate(ctx)
    volume, floors = checked.median_dollar_volume_20, checked.policy.spread_floor_bps
    floor = (
        floors.high
        if volume is not None and volume >= 500_000_000
        else (floors.mid if volume is not None and volume >= 50_000_000 else floors.low)
    )
    notes = ("ADV20 unavailable; lowest-liquidity spread floor used",) if volume is None else ()
    return max(floor, checked.measured_half_spread_bps or _ZERO), notes


def estimate_fill(order: CostOrder, bar: Bar, ctx: CostContext) -> FillResult:
    """CM-02/03: deterministic trade-through, participation and gap handling."""
    try:
        intent, observed, context = (
            CostOrder.model_validate(order),
            Bar.model_validate(bar),
            CostContext.model_validate(ctx),
        )
        observed.validate_integrity()
        if observed.volume <= 0:
            raise DataIntegrityError("DQ-03: zero-volume session cannot model a fill")
        next_session = intent.kind in {"ENTRY", "TIME", "SIGNAL"}
        if observed.session_date < intent.decision_session or (
            next_session and observed.session_date == intent.decision_session
        ):
            raise DataIntegrityError(
                "CM/QV-06: a close decision cannot fill before the next session"
            )
        spread, notes = half_spread(context)
        level, quantity = cast(Decimal, intent.level), intent.qty
        price: Decimal | None = None
        reason: Literal[
            "OPEN_WITH_SPREAD",
            "TRADE_THROUGH",
            "NOT_TOUCHED",
            "VOLUME_CAP",
            "STOP",
            "GAP_STOP",
            "TARGET",
            "TIME",
            "SIGNAL",
        ] = "NOT_TOUCHED"
        with localcontext() as precision:
            precision.prec = 256
            fraction = spread / _BPS
            if intent.kind == "ENTRY":
                if observed.open <= level:
                    price, reason = min(observed.open * (1 + fraction), level), "OPEN_WITH_SPREAD"
                elif observed.low <= level - CENT:
                    price, reason = level, "TRADE_THROUGH"
                quantity = min(
                    intent.qty,
                    int(
                        (context.policy.max_participation * observed.volume).to_integral_value(
                            rounding=ROUND_FLOOR
                        )
                    ),
                )
                if quantity == 0:
                    price, reason = None, "VOLUME_CAP"
            elif intent.kind == "STOP":
                if observed.low <= level:
                    if observed.open < level:
                        price, reason = observed.open * (1 - fraction), "GAP_STOP"
                    else:
                        price, reason = (
                            level * (1 - fraction)
                            - context.policy.stop_slip_atr_frac * context.atr14,
                            "STOP",
                        )
            elif intent.kind == "TARGET":
                if observed.high >= level + CENT:
                    price, reason = level, "TARGET"
            else:
                price = observed.open * (1 - fraction)
                reason = "TIME" if intent.kind == "TIME" else "SIGNAL"
            if price is not None:
                price = validate_cent_price(
                    price.quantize(
                        CENT, rounding=ROUND_CEILING if intent.side == Side.BUY else ROUND_FLOOR
                    )
                )
            else:
                quantity = 0
        return FillResult(
            status="NOT_FILLED"
            if quantity == 0
            else "FILLED"
            if quantity == intent.qty
            else "PARTIAL",
            requested_qty=intent.qty,
            qty=quantity,
            price=price,
            reason=reason,
            half_spread_bps=spread,
            notes=notes,
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("CM: malformed fill inputs cannot produce an outcome") from None


class FeeRow(FrozenModel):
    effective_from: SessionDate
    commission_per_share: Exact = Field(ge=0, le=1)
    sec_sell_rate: Exact = Field(ge=0, le=1)
    taf_sell_per_share: Exact = Field(ge=0, le=1)
    taf_sell_cap: Money = Field(ge=0)
    cat_per_share: Exact = Field(ge=0, le=1)


class FeeSchedule(FrozenModel):
    verified_on: SessionDate
    review_due: SessionDate
    commission_plan: Literal["retail_standard_unverified_account"]
    rows: tuple[FeeRow, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.review_due < self.verified_on or any(
            following.effective_from <= previous.effective_from
            for previous, following in zip(self.rows, self.rows[1:], strict=False)
        ):
            raise ValueError(
                "CM-04: fee rows need unique increasing effective dates and review date"
            )
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class FeeBreakdown(FrozenModel):
    commission: Money = Field(ge=0)
    sec: Money = Field(ge=0)
    taf: Money = Field(ge=0)
    cat: Money = Field(ge=0)
    source: Literal["MODELED", "BROKER"]
    notes: tuple[Note, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def cents(self) -> Self:
        with localcontext() as precision:
            precision.prec = 256
            if any(
                value != value.quantize(CENT)
                for value in (self.commission, self.sec, self.taf, self.cat)
            ):
                raise ValueError("CM-04: component fees must be exact nonnegative cents")
        return self

    @property
    def total(self) -> Decimal:
        with localcontext() as precision:
            precision.prec = 256
            return decimal_money(self.commission + self.sec + self.taf + self.cat)


class ObservedFees(FrozenModel):
    """FN-02 feeds this proof later; simulations never impersonate FEE activities."""

    account_id: UUID
    mode: Literal["PAPER", "LIVE"]
    side: Side
    qty: PositiveQty
    price: Price
    trade_date: SessionDate
    activity_ids: tuple[Annotated[str, Field(strict=True, min_length=1, max_length=128)], ...] = (
        Field(min_length=1, max_length=100)
    )
    breakdown: FeeBreakdown

    @model_validator(mode="after")
    def broker_proof(self) -> Self:
        if self.breakdown.source != "BROKER" or len(set(self.activity_ids)) != len(
            self.activity_ids
        ):
            raise ValueError("CM-04: observed fees need unique broker activity provenance")
        return self


def fees(
    side: Side,
    qty: int,
    price: Decimal,
    trade_date: date,
    *,
    schedule: FeeSchedule,
    observed: ObservedFees | None = None,
    account_id: UUID | None = None,
    mode: Literal["PAPER", "LIVE"] | None = None,
) -> FeeBreakdown:
    """CM-04: select dated rates; account/mode-bound actual fees take precedence."""
    try:
        table = FeeSchedule.model_validate(schedule)
        if (
            not isinstance(side, Side)
            or type(qty) is not int
            or not 1 <= qty <= 10**9
            or type(trade_date) is not date
        ):
            raise DataIntegrityError("CM-04: fee inputs require side, whole shares and trade date")
        validate_cent_price(price)
        if observed is not None:
            actual = ObservedFees.model_validate(observed)
            if (
                actual.account_id,
                actual.mode,
                actual.side,
                actual.qty,
                actual.price,
                actual.trade_date,
            ) != (account_id, mode, side, qty, price, trade_date):
                raise DataIntegrityError("CM-04: observed fee account/mode/trade binding differs")
            return actual.breakdown
        eligible = tuple(row for row in table.rows if row.effective_from <= trade_date)
        selected = eligible[-1] if eligible else table.rows[0]
        notes = ["Commission assumes the standard retail plan; account plan unverified"]
        if not eligible:
            notes.append("Trade predates the first fee row; first known model rates used")
        if trade_date > table.review_due:
            notes.append("Fee schedule review overdue; rates remain estimates")
        with localcontext() as precision:
            precision.prec = 256
            commission = selected.commission_per_share * qty
            sec = selected.sec_sell_rate * price * qty if side == Side.SELL else _ZERO
            taf = (
                min(selected.taf_sell_per_share * qty, selected.taf_sell_cap)
                if side == Side.SELL
                else _ZERO
            )
            cat = selected.cat_per_share * qty
            rounded = tuple(
                value.quantize(CENT, rounding=ROUND_CEILING)
                for value in (commission, sec, taf, cat)
            )
        return FeeBreakdown(
            commission=rounded[0],
            sec=rounded[1],
            taf=rounded[2],
            cat=rounded[3],
            source="MODELED",
            notes=tuple(notes),
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("CM-04: malformed fee evidence cannot model zero cost") from None


def after_tax_year(net_gains: Decimal, profile: TaxProfile) -> Decimal | None:
    """CM-05's rough yearly ST formula; wash/carryovers ignored, no transfer."""
    try:
        checked = TaxProfile.model_validate(profile)
        gains = decimal_money(net_gains)
        if not checked.estimate_available:
            return None
        with localcontext() as precision:
            precision.prec = 80
            rate = sum(
                (
                    cast(Decimal, value)
                    for value in (checked.federal_st_rate, checked.state_rate, checked.niit_rate)
                ),
                _ZERO,
            )
            if rate > 1:
                raise DataIntegrityError("CM-05: combined supplied tax rates exceed one")
            return gains * (1 - rate)
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("CM-05: malformed tax inputs cannot produce an estimate") from None
