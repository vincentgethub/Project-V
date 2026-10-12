"""EX: pure held-exit observations and typed upward-stop authorizations.

No SDK imports or order calls. Observations cannot change rules or trade sizes.
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import _provider_money
from backend.data.history import Digest, HistorySeries, canonical_bytes
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    FrozenModel,
    Money,
    PositiveQty,
    Price,
    SessionDate,
    Symbol,
    UTCDateTime,
)
from backend.execution.models import payload_instant
from backend.indicators.vectorized import atr, ema_last


class HeldEntry(FrozenModel):
    entry_id: UUID
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Literal["PAPER", "LIVE"]
    symbol: Symbol
    first_fill: UTCDateTime
    filled_qty: PositiveQty
    entry_cost: Money = Field(gt=0)
    entry_limit: Price
    initial_stop: Price
    variant: Literal["BASELINE", "SPLIT_1R", "SPLIT_1R_TRAIL", "TRAIL_EMA20"]
    hold_sessions: Literal[10, 20, 30]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.initial_stop >= self.entry_limit:
            raise ValueError("EX: positive recorded entry risk required")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "HeldEntry":
        return cls.model_validate(
            {
                **payload,
                "first_fill": payload_instant(payload["first_fill"]),
                "entry_limit": _provider_money(payload["entry_limit"]),
                "initial_stop": _provider_money(payload["initial_stop"]),
            }
        )


class HeldQuoteObservation(FrozenModel):
    entry_id: UUID
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Literal["PAPER", "LIVE"]
    symbol: Symbol
    price: Price
    trade_at: UTCDateTime
    known_at: UTCDateTime

    @model_validator(mode="after")
    def causal(self) -> Self:
        if self.trade_at > self.known_at:
            raise ValueError("EX-03: observed peak cannot use a future trade")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "HeldQuoteObservation":
        return cls.model_validate(
            {
                **payload,
                "price": _provider_money(payload["price"]),
                "trade_at": payload_instant(payload["trade_at"]),
                "known_at": payload_instant(payload["known_at"]),
            }
        )


class HeldExitObservation(FrozenModel):
    entry: HeldEntry
    session: SessionDate
    known_at: UTCDateTime
    history_sha256: Digest
    close: Price
    ema20: Price | None
    atr14: Price | None
    verified_peak: Price | None

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "HeldExitObservation":
        values = dict(payload)
        values["entry"] = HeldEntry.recorded(values["entry"])
        values["session"] = date.fromisoformat(values["session"])
        values["known_at"] = payload_instant(values["known_at"])
        for name in ("close", "ema20", "atr14", "verified_peak"):
            values[name] = None if values[name] is None else _provider_money(values[name])
        return cls.model_validate(values)

    @property
    def ema_signal(self) -> bool:
        return (
            self.entry.variant == "TRAIL_EMA20"
            and self.verified_peak is not None
            and self.ema20 is not None
            and self.close < self.ema20
            and self.verified_peak * self.entry.filled_qty - self.entry.entry_cost
            >= (self.entry.entry_limit - self.entry.initial_stop) * self.entry.filled_qty
        )


def observe_held_exit(
    entry: HeldEntry,
    native: HistorySeries,
    calendar: MarketCalendar,
    now: datetime,
    *,
    scan_delay_minutes: int,
    last_trade: Decimal | None = None,
    trade_at: datetime | None = None,
    verified_peaks: tuple[HeldQuoteObservation, ...] = (),
) -> HeldExitObservation:
    """Do not use the high of a partially held entry day to claim a reached MFE."""
    import hashlib
    from zoneinfo import ZoneInfo

    held, history = HeldEntry.model_validate(entry), HistorySeries.model_validate(native)
    instant = ensure_utc(now)
    if (
        history.symbol != held.symbol
        or history.adjustment != "SPLIT"
        or held.first_fill > instant
        or type(scan_delay_minutes) is not int
        or not 0 <= scan_delay_minutes <= 120
    ):
        raise DataIntegrityError("EX: bound completed native-basis evidence required")
    session = history.sessions[-1]
    known = calendar.session_close(session) + timedelta(minutes=scan_delay_minutes)
    if (
        known > instant
        or calendar.last_completed_session(instant - timedelta(minutes=scan_delay_minutes))
        != session
    ):
        raise DataIntegrityError("EX: stale or unfinished held-exit session")
    fill_day = held.first_fill.astimezone(ZoneInfo("America/New_York")).date()
    peaks = [
        bar.high
        for bar in history.bars
        if bar.session_date > fill_day
        or (bar.session_date == fill_day and held.first_fill == calendar.session_open(fill_day))
    ]
    if not isinstance(verified_peaks, tuple) or len(verified_peaks) > 100000:
        raise DataIntegrityError("EX-03: bounded verified peak observations required")
    closed_at = calendar.session_close(session)
    for item in verified_peaks:
        peak = HeldQuoteObservation.model_validate(item)
        if (peak.entry_id, peak.account_id, peak.environment, peak.symbol) != (
            held.entry_id,
            held.account_id,
            held.environment,
            held.symbol,
        ) or not held.first_fill <= peak.trade_at <= peak.known_at <= instant:
            raise DataIntegrityError("EX-03: quote peak is unbound, predates entry or is future")
        if peak.trade_at <= closed_at and peak.known_at <= known:
            peaks.append(peak.price)
    if last_trade is not None or trade_at is not None:
        from backend.core.money import validate_cent_price

        if last_trade is None or trade_at is None:
            raise DataIntegrityError("EX: trade observation needs a paired exact time and price")
        trade = ensure_utc(trade_at)
        if not held.first_fill <= trade <= instant:
            raise DataIntegrityError("EX: peak observation cannot precede entry or be future")
        price = validate_cent_price(last_trade)
        if trade <= closed_at:
            peaks.append(price)
    return HeldExitObservation(
        entry=held,
        session=session,
        known_at=known,
        history_sha256=hashlib.sha256(canonical_bytes(history)).hexdigest(),
        close=history.bars[-1].close,
        ema20=ema_last(tuple(bar.close for bar in history.bars), 20),
        atr14=atr(history.bars)[-1],
        verified_peak=max(peaks) if peaks else None,
    )


class StopRaiseApproval(FrozenModel):
    raise_id: UUID
    entry_id: UUID
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    environment: Literal["PAPER", "LIVE"]
    symbol: Symbol
    qty: PositiveQty
    old_stop: Price
    new_stop: Price
    last_trade: Price
    atr14: Price
    quote_at: UTCDateTime
    checked_at: UTCDateTime
    session: SessionDate
    history_sha256: Digest
    config_hash: Digest
    yaml_hash: Digest

    @model_validator(mode="after")
    def safe_raise(self) -> Self:
        if (
            self.new_stop <= self.old_stop
            or self.last_trade < self.new_stop + Decimal("0.5") * self.atr14
            or self.quote_at > self.checked_at
        ):
            raise ValueError("EX-05: upward stop, half-ATR buffer and nonfuture quote required")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "StopRaiseApproval":
        values = dict(payload)
        values["session"] = date.fromisoformat(values["session"])
        for name in ("old_stop", "new_stop", "last_trade", "atr14"):
            values[name] = _provider_money(values[name])
        for name in ("quote_at", "checked_at"):
            values[name] = payload_instant(values[name])
        return cls.model_validate(values)


class StopMoved(FrozenModel):
    approval: StopRaiseApproval
    status: Literal["APPLIED", "REPAIRED", "FAILED", "CANCEL_UNCONFIRMED"]
    confirmed_stop: Price | None
    window_ms: int = Field(strict=True, ge=0, le=9223372036854775807)
    completed_at: UTCDateTime

    @model_validator(mode="after")
    def truthful(self) -> Self:
        if (self.status in {"APPLIED", "REPAIRED"}) != (
            self.confirmed_stop is not None
        ) or self.completed_at < self.approval.checked_at:
            raise ValueError("EX-05: successful raise/repair requires confirmed coverage")
        if self.confirmed_stop is not None and (
            self.confirmed_stop < self.approval.old_stop
            or self.confirmed_stop > self.approval.new_stop
        ):
            raise ValueError("EX-05: confirmed repair cannot lower the proved old stop")
        if self.status == "APPLIED" and self.confirmed_stop != self.approval.new_stop:
            raise ValueError("EX-05: applied raise requires the proposed stop")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "StopMoved":
        return cls.model_validate(
            {
                **payload,
                "approval": StopRaiseApproval.recorded(payload["approval"]),
                "confirmed_stop": None
                if payload["confirmed_stop"] is None
                else _provider_money(payload["confirmed_stop"]),
                "completed_at": payload_instant(payload["completed_at"]),
            }
        )


def stop_raise_plan(
    entry: HeldEntry,
    observation: HeldExitObservation,
    calendar: MarketCalendar,
    now: datetime,
    *,
    raise_id: UUID,
    qty: int,
    old_stop: Decimal,
    last_trade: Decimal,
    quote_at: datetime,
    stale_quote_seconds: int,
    trail_atr_mult: Decimal,
    config_hash: str,
    yaml_hash: str,
) -> StopRaiseApproval | None:
    """EX-05: completed-close decision, upward cents, fresh regular-hours quote."""
    held = HeldEntry.model_validate(entry)
    observed = HeldExitObservation.model_validate(observation)
    instant, quote = ensure_utc(now), ensure_utc(quote_at)
    if observed.entry != held or observed.known_at > instant or observed.atr14 is None:
        raise DataIntegrityError("EX-05: bound completed daily ATR evidence required")
    if type(qty) is not int or not 1 <= qty <= held.filled_qty:
        raise DataIntegrityError("EX-05: bounded broker-held whole shares required")
    if (
        type(stale_quote_seconds) is not int
        or not 0 < stale_quote_seconds <= 300
        or not timedelta(0) <= instant - quote <= timedelta(seconds=stale_quote_seconds)
        or not isinstance(trail_atr_mult, Decimal)
        or trail_atr_mult != Decimal(3)
    ):
        raise DataIntegrityError("EX-05: fresh quote and registered 3.0 ATR rule required")
    from zoneinfo import ZoneInfo

    from backend.core.money import validate_cent_price

    old, last = validate_cent_price(old_stop), validate_cent_price(last_trade)
    today = instant.astimezone(ZoneInfo("America/New_York")).date()
    if not calendar.is_open(instant) or not (
        calendar.session_open(today) + timedelta(minutes=30)
        <= instant
        < calendar.session_close(today) - timedelta(minutes=30)
    ):
        return None
    if calendar.add_sessions(observed.session, 1) != today:
        raise DataIntegrityError("EX-05: preceding completed session required")
    with localcontext() as context:
        context.prec = 80
        new = (observed.close - trail_atr_mult * observed.atr14).quantize(
            Decimal("0.01"), rounding=ROUND_FLOOR
        )
    if new <= old or last < new + Decimal("0.5") * observed.atr14:
        return None
    return StopRaiseApproval(
        raise_id=raise_id,
        entry_id=held.entry_id,
        account_id=held.account_id,
        environment=held.environment,
        symbol=held.symbol,
        qty=qty,
        old_stop=old,
        new_stop=new,
        last_trade=last,
        atr14=observed.atr14,
        quote_at=quote,
        checked_at=instant,
        session=observed.session,
        history_sha256=observed.history_sha256,
        config_hash=config_hash,
        yaml_hash=yaml_hash,
    )
