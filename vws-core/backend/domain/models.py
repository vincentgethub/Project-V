"""R-01/R-02/R-04/R-05/R-11/R-13: frozen contracts for trading and research."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Generic, Self, TypeVar, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.core.money import MoneyInput, decimal_money, validate_cent_price
from backend.core.system_state import SystemState

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,14}$")


def _exact_money(value: object) -> Decimal:
    """R-04: reject float, bool, NaN and sub-micro-unit money at ingress."""
    try:
        return decimal_money(cast(MoneyInput, value))
    except DataIntegrityError as exc:
        raise ValueError(str(exc)) from exc


def _aware_utc(value: object) -> datetime:
    """R-05: the boundary requires an aware datetime and normalizes to UTC."""
    try:
        return ensure_utc(cast(datetime, value))
    except DataIntegrityError as exc:
        raise ValueError(str(exc)) from exc


def _cent_price(value: object) -> Decimal:
    """R-13: only exact positive Decimal cent prices cross module boundaries."""
    try:
        return validate_cent_price(cast(Decimal, value))
    except DataIntegrityError as exc:
        raise ValueError(str(exc)) from exc


def _session_date(value: object) -> date:
    """R-05/CRO-13: earnings are calendar dates, never guessed timestamps."""
    if type(value) is not date:
        raise ValueError("earnings date must be an explicit calendar date")
    return value


def _sentiment_score(value: object) -> Decimal:
    """R-11: finite exact sentiment is clamped to the stated advisory range."""
    amount = _exact_money(value)
    return max(Decimal("-5"), min(Decimal("5"), amount))


def validate_symbol(value: str) -> str:
    """R-02: symbols must already be unambiguous uppercase US ticker labels."""
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError("symbol must be an uppercase US ticker label")
    return value


Money = Annotated[Decimal, BeforeValidator(_exact_money)]
Price = Annotated[Decimal, BeforeValidator(_cent_price)]
UTCDateTime = Annotated[datetime, BeforeValidator(_aware_utc)]
SessionDate = Annotated[date, BeforeValidator(_session_date)]
PositiveQty = Annotated[int, Field(strict=True, gt=0)]
NonnegativeQty = Annotated[int, Field(strict=True, ge=0)]
Symbol = Annotated[str, BeforeValidator(validate_symbol)]
Identifier = Annotated[str, Field(strict=True, min_length=1)]


class AssetClass(StrEnum):
    STOCK = "STOCK"
    BROAD_ETF = "BROAD_ETF"
    SECTOR_ETF = "SECTOR_ETF"
    COMMODITY_ETF = "COMMODITY_ETF"
    CASH_EQUIV = "CASH_EQUIV"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Intent(StrEnum):
    ENTRY = "ENTRY"
    ADD = "ADD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class ProposalSource(StrEnum):
    SIGNAL = "SIGNAL"
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class AccountType(StrEnum):
    CASH = "CASH"
    MARGIN = "MARGIN"


class MarketStatus(StrEnum):
    OK = "OK"
    SUSPECT = "SUSPECT"


class EarningsStatus(StrEnum):
    """DAT-11/CRO-13: an estimated or unknown date never establishes clearance."""

    KNOWN = "KNOWN"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class CapitalStatus(StrEnum):
    OK = "OK"
    BUFFER_BREACH = "BUFFER_BREACH"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class Severity(StrEnum):
    BLOCK = "BLOCK"
    WARN = "WARN"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    VETOED = "VETOED"


class DayTradeRegime(StrEnum):
    INTRADAY_MARGIN = "INTRADAY_MARGIN"
    LEGACY_PDT = "LEGACY_PDT"


class ProviderStatus(StrEnum):
    """R-02/R-11: unavailable research cannot be inferred to be positive."""

    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class Playbook(StrEnum):
    """R-11/GD-03: code chooses the setup playbook."""

    TREND_50EMA = "TREND_50EMA"
    BASE_BREAKOUT = "BASE_BREAKOUT"
    ANCHORED_VWAP_RECLAIM = "ANCHORED_VWAP_RECLAIM"
    INTRADAY_ORB = "INTRADAY_ORB"
    INTRADAY_VWAP_RECLAIM = "INTRADAY_VWAP_RECLAIM"


class SentimentClassification(StrEnum):
    """R-11: sentiment context does not decide a proposal or risk verdict."""

    THESIS_CHANGING = "THESIS_CHANGING"
    CONFIRMING = "CONFIRMING"
    NOISE = "NOISE"


class FrozenModel(BaseModel):
    """R-02/R-03: unexpected fields and mutation cannot silently change rules."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        revalidate_instances="always",
    )

    @field_validator("*", mode="after")
    @classmethod
    def nonblank_strings(cls, value: object) -> object:
        """R-02: whitespace-only identifiers are unverifiable state."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("text fields cannot be blank")
        return value


class Instrument(FrozenModel):
    """R-01/CRO-02/CRO-05: explicit, allowlisted instrument metadata."""

    symbol: Symbol
    asset_class: AssetClass
    gics_sector: Identifier
    themes: tuple[Identifier, ...] = ()
    is_leveraged: bool = Field(strict=True)
    is_inverse: bool = Field(strict=True)
    tradable: bool = Field(strict=True)

    @field_validator("themes")
    @classmethod
    def unique_themes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """CRO-05: duplicate theme labels must not distort exposure aggregation."""
        if len(value) != len(set(value)):
            raise ValueError("instrument themes must be unique")
        if any(not theme.strip() for theme in value):
            raise ValueError("instrument themes cannot be blank")
        return value


class TradeProposal(FrozenModel):
    """R-01/R-04/R-05: whole-share long-only LIMIT proposal linked to a signal."""

    proposal_id: UUID
    signal_id: UUID
    account_id: Identifier
    symbol: Symbol
    side: Side
    intent: Intent
    qty: PositiveQty
    limit_price: Price
    stop_price: Price | None = None
    target_price: Price | None = None
    source: ProposalSource
    created_at: UTCDateTime
    expires_at: UTCDateTime

    @model_validator(mode="after")
    def validate_long_only_shape(self) -> Self:
        """R-01: additions are buys with a stop, reductions are sells."""
        if self.intent in (Intent.ENTRY, Intent.ADD):
            if self.side != Side.BUY:
                raise ValueError("ENTRY/ADD must be BUY")
            if self.stop_price is None or self.stop_price >= self.limit_price:
                raise ValueError("ENTRY/ADD requires a stop strictly below the limit")
            if self.target_price is not None and self.target_price <= self.limit_price:
                raise ValueError("ENTRY/ADD target must exceed the limit")
        elif self.side != Side.SELL:
            raise ValueError("REDUCE/EXIT must be SELL")
        if self.expires_at <= self.created_at:
            raise ValueError("proposal expiry must follow its creation")
        return self


class Position(FrozenModel):
    """R-01/R-04: a long position with exact cost and current valuation."""

    qty: NonnegativeQty
    avg_cost: Price
    last_price: Price

    @property
    def value(self) -> Decimal:
        """CRO-03/CRO-06: whole-share notional without float conversion."""
        with localcontext() as context:
            context.prec = max(80, len(str(self.qty)) + 40)
            return self.qty * self.last_price


class OpenOrder(FrozenModel):
    """CRO-03/CRO-06: read-only pending LIMIT notional."""

    symbol: Symbol
    side: Side
    qty: PositiveQty
    limit_price: Price
    stop_price: Price | None = None

    @model_validator(mode="after")
    def validate_stop(self) -> Self:
        """R-01/CRO-04: an optional pending BUY stop must precede its limit."""
        if (
            self.side == Side.BUY
            and self.stop_price is not None
            and self.stop_price >= self.limit_price
        ):
            raise ValueError("pending BUY stop must be below its limit")
        return self


class ProtectiveStop(FrozenModel):
    """AX-27: a pending SELL stop is recorded separately from LIMIT exposure."""

    symbol: Symbol
    qty: PositiveQty
    stop_price: Price


class PortfolioSnapshot(FrozenModel):
    """R-03/R-04/R-05/CRO-09: immutable managed-account state.

    Signed balances are retained so a negative broker balance can trigger a
    veto/halt rather than be lost through coercion. Position quantities remain
    nonnegative. Funding values must be present even when they are zero.
    """

    account_id: Identifier
    account_type: AccountType
    as_of: UTCDateTime
    equity: Money
    cash: Money
    settled_cash: Money
    positions: Mapping[str, Position]
    open_orders: tuple[OpenOrder, ...]
    protective_stops: tuple[ProtectiveStop, ...] = Field(default=(), max_length=500)
    high_water_mark: Money = Field(ge=Decimal(0))
    day_start_equity: Money = Field(ge=Decimal(0))

    def reserved_sell_shares(self, symbol: str) -> int:
        """R-01: outstanding sells reserve shares until cancellation is proved."""
        return sum(
            order.qty
            for order in self.open_orders
            if order.symbol == symbol and order.side == Side.SELL
        ) + sum(stop.qty for stop in self.protective_stops if stop.symbol == symbol)

    @field_validator("positions", mode="after")
    @classmethod
    def immutable_positions(cls, value: Mapping[str, Position]) -> Mapping[str, Position]:
        """R-03: detach mutable input dictionaries and validate every symbol."""
        for symbol in value:
            validate_symbol(symbol)
        return MappingProxyType(dict(value))

    @field_serializer("positions")
    def serialize_positions(self, value: Mapping[str, Position]) -> dict[str, Position]:
        """R-03: expose sorted JSON data without weakening stored immutability."""
        return {symbol: value[symbol] for symbol in sorted(value)}


class EarningsInfo(FrozenModel):
    """DAT-11: dated evidence distinguishes confirmed events from estimate windows."""

    date: SessionDate | None = None
    status: EarningsStatus
    source: str = Field(strict=True, min_length=1, max_length=280)
    window_start: SessionDate | None = None
    window_end: SessionDate | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        """R-02: no partial window or invented date can imply a known event."""
        if self.status == EarningsStatus.KNOWN:
            if self.date is None or self.window_start is not None or self.window_end is not None:
                raise ValueError("known earnings require one exact date and no estimate window")
        elif self.status == EarningsStatus.ESTIMATED:
            if (
                self.date is not None
                or self.window_start is None
                or self.window_end is None
                or self.window_start > self.window_end
            ):
                raise ValueError("estimated earnings require an ordered window and no exact date")
        elif self.date is not None or self.window_start is not None or self.window_end is not None:
            raise ValueError("unknown earnings cannot contain a date or window")
        return self


class MarketContext(FrozenModel):
    """DAT-01/DAT-02/CRO-07/CRO-08: validated per-symbol pricing state."""

    last_price: Price
    last_price_ts: UTCDateTime
    adv20_usd: Money = Field(ge=Decimal(0))
    next_earnings_date: SessionDate | None = None
    earnings: EarningsInfo | None = None
    status: MarketStatus

    @model_validator(mode="after")
    def validate_earnings_binding(self) -> Self:
        """DAT-11: the legacy confirmed date cannot contradict richer evidence."""
        if self.earnings is not None and self.next_earnings_date is not None:
            if (
                self.earnings.status != EarningsStatus.KNOWN
                or self.earnings.date != self.next_earnings_date
            ):
                raise ValueError("earnings evidence conflicts with the confirmed date")
        return self


class DeployableCapital(FrozenModel):
    """CRO-12: advisory NEW funding capacity; never a transfer instruction."""

    checking_used: Money = Field(ge=Decimal(0))
    buffer: Money = Field(ge=Decimal(0))
    reserved: Money = Field(ge=Decimal(0))
    deployable: Money = Field(ge=Decimal(0))
    status: CapitalStatus

    @model_validator(mode="after")
    def validate_deployable(self) -> Self:
        """CRO-12: unavailable balances cannot accidentally advertise funding."""
        if self.status != CapitalStatus.OK and self.deployable != 0:
            raise ValueError("non-OK funding state must have zero deployable capital")
        if self.status == CapitalStatus.OK:
            with localcontext() as context:
                context.prec = 80
                expected = max(Decimal(0), self.checking_used - self.buffer - self.reserved)
                if self.deployable != expected:
                    raise ValueError("deployable does not equal checking less buffer and reserves")
            if self.checking_used < self.buffer:
                raise ValueError("checking below its buffer cannot have OK status")
        return self


class AccountFlags(FrozenModel):
    """R-02/CMP-06: exact current broker account-status flags, explicitly required."""

    trading_blocked: bool = Field(strict=True)
    account_blocked: bool = Field(strict=True)
    trade_suspended_by_user: bool = Field(strict=True)
    status: Identifier

    @property
    def blocked(self) -> bool:
        """CMP-06: any broker restriction requires the caller to latch HALTED."""
        return (
            self.status != "ACTIVE"
            or self.trading_blocked
            or self.account_blocked
            or self.trade_suspended_by_user
        )


class BlackoutWindow(FrozenModel):
    """CRO-11/R-05: UTC interval; CRO blocks both endpoints conservatively."""

    start: UTCDateTime
    end: UTCDateTime
    symbol: Symbol | None = None
    reason: Identifier

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """CRO-11: a missing/reversed interval cannot silently disable a blackout."""
        if self.start >= self.end:
            raise ValueError("blackout start must precede end")
        return self


class RuleResult(FrozenModel):
    """R-02/CRO-01..13/CMP-01..07: complete, reviewable rule evidence."""

    rule_id: Identifier
    passed: bool = Field(strict=True)
    severity: Severity
    observed: str
    limit: str
    message: Identifier


class Verdict(FrozenModel):
    """R-02/R-03/R-05: reproducible verdict with configuration/snapshot hashes."""

    proposal_id: UUID
    decision: Decision
    results: tuple[RuleResult, ...]
    config_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluated_at: UTCDateTime
    recommended_state: SystemState = SystemState.RUNNING

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        """R-02: an APPROVED verdict requires evidence and no blocking failure."""
        if self.decision == Decision.APPROVED and (
            not self.results
            or any(
                not result.passed and result.severity == Severity.BLOCK for result in self.results
            )
        ):
            raise ValueError("APPROVED verdict requires passing blocking-rule evidence")
        return self


Payload = TypeVar("Payload", bound=FrozenModel)


class ProviderResult(FrozenModel, Generic[Payload]):
    """R-02/R-11: typed evidence is present only when a provider succeeds."""

    status: ProviderStatus
    payload: Payload | None
    reason: str = Field(max_length=2000)

    @model_validator(mode="after")
    def validate_available_evidence(self) -> Self:
        """R-02: an unavailable/error result never carries inferred evidence."""
        if (self.status == ProviderStatus.OK) != (self.payload is not None):
            raise ValueError("provider OK requires payload; non-OK requires no payload")
        return self


class ScannerHit(FrozenModel):
    """R-11/R-13/GD-03: deterministic scanner facts from completed bars."""

    symbol: Symbol
    as_of: UTCDateTime
    last_price: Price
    rvol: Money = Field(ge=Decimal(0))
    rsi: Money = Field(ge=Decimal(0), le=Decimal(100))
    reason: str = Field(min_length=1, max_length=2000)


class SetupCriterion(FrozenModel):
    """R-11/GD-03: code supplies each graded playbook criterion."""

    name: Identifier
    points: Money = Field(ge=Decimal(0), le=Decimal(10))
    reason: str = Field(min_length=1, max_length=2000)


class SetupCandidate(FrozenModel):
    """R-11/R-13/GD-03: code supplies score, levels, size, and criteria."""

    symbol: Symbol
    playbook: Playbook
    score: Money = Field(ge=Decimal(1), le=Decimal(10))
    criteria: tuple[SetupCriterion, ...] = Field(min_length=1)
    entry_price: Price
    stop_price: Price
    target_price: Price
    qty: PositiveQty
    as_of: UTCDateTime

    @model_validator(mode="after")
    def validate_deterministic_levels(self) -> Self:
        """R-01/R-11: criteria reconcile to score and long levels are ordered."""
        names = tuple(criterion.name for criterion in self.criteria)
        if len(names) != len(set(names)):
            raise ValueError("setup criteria names must be unique")
        with localcontext() as context:
            context.prec = 80
            if sum((criterion.points for criterion in self.criteria), Decimal(0)) != self.score:
                raise ValueError("setup score must equal deterministic criterion points")
        if not self.stop_price < self.entry_price < self.target_price:
            raise ValueError("setup levels require stop < entry < target")
        return self


class SentimentSignal(FrozenModel):
    """R-11/R-12: bounded advisory LLM output without executable trade fields."""

    score: Annotated[Decimal, BeforeValidator(_sentiment_score)]
    classification: SentimentClassification
    evidence_headline_ids: tuple[Identifier, ...] = Field(max_length=100)
    summary: str = Field(min_length=1, max_length=280)

    @model_validator(mode="after")
    def validate_cited_claim(self) -> Self:
        """R-11/R-12: non-noise sentiment requires explicit evidence ids."""
        if len(self.evidence_headline_ids) != len(set(self.evidence_headline_ids)):
            raise ValueError("headline evidence ids must be unique")
        if (
            self.score != 0 or self.classification != SentimentClassification.NOISE
        ) and not self.evidence_headline_ids:
            raise ValueError("non-neutral sentiment requires cited headline ids")
        return self


class FlowSignal(FrozenModel):
    """R-02/R-11: unavailable flow remains explicit and has no positive claim."""

    status: ProviderStatus
    summary: str | None = Field(default=None, max_length=2000)
    evidence_ids: tuple[Identifier, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_flow_evidence(self) -> Self:
        """R-02: unavailable/error flow never masquerades as evidence."""
        if self.status != ProviderStatus.OK and (self.summary is not None or self.evidence_ids):
            raise ValueError("non-OK flow cannot carry claims or evidence")
        if self.status == ProviderStatus.OK and (self.summary is None or not self.evidence_ids):
            raise ValueError("OK flow requires a summary and evidence ids")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("flow evidence ids must be unique")
        return self


class ResearchThesis(FrozenModel):
    """R-11/R-12: advisory narrative cannot set score, levels, or quantity."""

    narrative: str = Field(min_length=1, max_length=4000)
    evidence_headline_ids: tuple[Identifier, ...] = Field(max_length=100)

    @field_validator("evidence_headline_ids")
    @classmethod
    def unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """R-12: duplicate citations cannot inflate evidence counts."""
        if len(value) != len(set(value)):
            raise ValueError("headline evidence ids must be unique")
        return value


def _canonical(value: object) -> object:
    """R-03/R-04: stable exact JSON data independent of Decimal display scale."""
    if isinstance(value, Decimal):
        text = format(value, "f")
        return "0" if value == 0 else text.rstrip("0").rstrip(".") if "." in text else text
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise DataIntegrityError("snapshot contains a value that cannot be hashed exactly")


def snapshot_hash(snapshot: PortfolioSnapshot) -> str:
    """R-03/R-04: SHA256 of canonical non-secret portfolio JSON."""
    try:
        checked = PortfolioSnapshot.model_validate(snapshot)
        payload = json.dumps(
            _canonical(checked), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    except DataIntegrityError:
        raise
    except Exception as exc:
        raise DataIntegrityError("R-02: invalid snapshot cannot be hashed") from exc
