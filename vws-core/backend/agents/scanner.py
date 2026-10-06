"""R-02/R-03/R-11/R-13/DAT-03/GD-03: deterministic completed-daily scanner.

A hit needs anomalous RVOL plus positive momentum. It is research evidence,
never an approval, a setup score, or executable levels. Calendar queries use an
already-compiled immutable schedule. No provider, database, log or clock I/O
occurs here; callers supply the instant and raw data-snapshot SHA256.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Self, cast

from pydantic import Field, model_validator

from backend.agents import indicators
from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError, SafetyError, StaleDataError
from backend.data.data_layer import Bar
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    FrozenModel,
    MarketStatus,
    Money,
    Price,
    ProviderStatus,
    ScannerHit,
    SessionDate,
    Symbol,
    UTCDateTime,
    validate_symbol,
)


class AnchorKind(StrEnum):
    """GD-03: an anchor requires attested earnings or a confirmed structural low."""

    EARNINGS_GAP = "EARNINGS_GAP"
    SWING_LOW = "SWING_LOW"


class ScannerConfig(FrozenModel):
    """GD-03: explicit deterministic research thresholds, independent of CRO limits."""

    anomalous_rvol: Money = Field(default=Decimal("1.5"), ge=Decimal("1.5"), le=Decimal(100))
    momentum_rsi: Money = Field(default=Decimal(60), ge=Decimal(50), le=Decimal(100))
    swing_left: int = Field(default=2, strict=True, ge=1, le=10)
    swing_right: int = Field(default=2, strict=True, ge=1, le=10)
    earnings_gap_fraction: Money = Field(default=Decimal("0.05"), gt=Decimal(0), le=Decimal(1))
    daily_grace_seconds: int = Field(default=900, strict=True, ge=0, le=3600)


class IndicatorSnapshot(FrozenModel):
    """R-13/DAT-03/GD-03: cent-valued levels with completed-session provenance."""

    session: SessionDate
    close: Price
    ema20: Price
    ema50: Price
    ema200: Price
    rsi14: Money = Field(ge=Decimal(0), le=Decimal(100))
    atr14: Money = Field(ge=Decimal(0))
    macd_line: Money
    macd_signal: Money
    macd_histogram: Money
    rvol20: Money = Field(ge=Decimal(0))
    anchored_vwap: Price
    anchor_session: SessionDate
    anchor_kind: AnchorKind

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        """R-02/R-13: signed price differences remain cents; anchors cannot be future."""
        with localcontext() as context:
            context.prec = 80
            for value in (self.atr14, self.macd_line, self.macd_signal, self.macd_histogram):
                if value != value.quantize(Decimal("0.01")):
                    raise ValueError("price-valued indicators must be Decimal cents")
        if self.anchor_session > self.session:
            raise ValueError("anchor cannot follow indicator session")
        return self


class ScannerResult(FrozenModel):
    """R-02/GD-03: unavailable inputs have no facts or hits; provenance is explicit."""

    symbol: Symbol
    as_of: UTCDateTime
    status: ProviderStatus
    data_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    completed_bars_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    indicators: IndicatorSnapshot | None
    hits: tuple[ScannerHit, ...] = Field(max_length=1)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        """R-02/DAT-03: bind every hit to this symbol, instant and exact facts."""
        if self.status != ProviderStatus.OK:
            if self.indicators is not None or self.hits:
                raise ValueError("unavailable scanner cannot carry facts or hits")
        elif self.indicators is None:
            raise ValueError("OK scanner requires indicator facts")
        for hit in self.hits:
            if (
                hit.symbol != self.symbol
                or hit.as_of != self.as_of
                or self.indicators is None
                or hit.last_price != self.indicators.close
                or hit.rvol != self.indicators.rvol20
                or hit.rsi != self.indicators.rsi14
            ):
                raise ValueError("scanner hit does not match result provenance")
        return self


def _checked_bars(
    bars: tuple[Bar, ...], now: datetime, calendar: MarketCalendar, config: ScannerConfig
) -> tuple[Bar, ...]:
    """DAT-01..03: require ordered continuous completed sessions and fresh tail."""
    checked = indicators._bars(bars)
    expected = calendar.last_completed_session(now)
    if now < calendar.session_close(expected) + timedelta(seconds=config.daily_grace_seconds):
        expected = calendar.previous_sessions(expected, 1)[0]
    for index, bar in enumerate(checked):
        if not calendar.is_session(bar.session_date):
            raise DataIntegrityError("DAT-02: scanner bar is not an exchange session")
        if bar.timestamp > now or calendar.session_close(bar.session_date) > now:
            raise DataIntegrityError("DAT-03: scanner forbids future or in-progress daily bars")
        if index and calendar.add_sessions(checked[index - 1].session_date, 1) != bar.session_date:
            raise DataIntegrityError("DAT-02: scanner daily sessions are missing or duplicated")
    if checked[-1].session_date < expected:
        raise StaleDataError("DAT-01: scanner latest completed daily session is stale")
    return checked


def _anchor(
    bars: tuple[Bar, ...], earnings_gap: date | None, config: ScannerConfig
) -> tuple[int, AnchorKind] | None:
    """DAT-03/GD-03: use no future bars to confirm the most recent swing low."""
    if earnings_gap is not None:
        if type(earnings_gap) is not date:
            raise DataIntegrityError("GD-03: earnings-gap anchor must be an explicit session date")
        matching = [index for index, bar in enumerate(bars) if bar.session_date == earnings_gap]
        if not matching or matching[0] == 0:
            raise DataIntegrityError("GD-03: earnings-gap anchor lacks a prior completed close")
        index = matching[0]
        with localcontext() as context:
            context.prec = 80
            if abs(bars[index].open / bars[index - 1].close - 1) < config.earnings_gap_fraction:
                raise DataIntegrityError("GD-03: attested earnings anchor lacks the configured gap")
        return index, AnchorKind.EARNINGS_GAP
    for index in range(len(bars) - config.swing_right - 1, config.swing_left - 1, -1):
        neighbours = (
            *bars[index - config.swing_left : index],
            *bars[index + 1 : index + config.swing_right + 1],
        )
        if all(bars[index].low < bar.low for bar in neighbours):
            return index, AnchorKind.SWING_LOW
    return None


def scan(
    symbol: str,
    bars: tuple[Bar, ...],
    *,
    now: datetime,
    calendar: MarketCalendar,
    data_snapshot_hash: str,
    market_status: MarketStatus,
    earnings_gap: date | None = None,
    config: ScannerConfig | None = None,
    memo: indicators.IndicatorMemo | None = None,
) -> ScannerResult:
    """R-02/R-03/GD-03: deterministic high-volume positive-momentum daily facts.

    Need 200 sessions for every required EMA, defined RSI/RVOL, and an anchor.
    RVOL>=1.5 and RSI>=60 are inclusive; MACD histogram and close-minus-EMA20
    must be strictly positive after boundary cent quantization. The earnings
    date is a caller-attested latest earnings gap, not inferred from price.
    Missing warmup/anchor/ratios returns UNAVAILABLE and zero hits. Invalid,
    stale, suspect or future data never produces a hit. An optional explicitly
    injected memo reuses indicator series; no provider, ledger or clock is read.
    """
    try:
        validate_symbol(symbol)
        instant = ensure_utc(now)
        settings = ScannerConfig.model_validate(config or ScannerConfig())
        if (
            not isinstance(data_snapshot_hash, str)
            or re.fullmatch(r"[a-f0-9]{64}", data_snapshot_hash) is None
        ):
            raise DataIntegrityError("DAT-03: scanner needs the raw data-snapshot SHA256")
        if not isinstance(market_status, MarketStatus):
            raise DataIntegrityError("DAT-02: scanner market status must be explicit")
        checked = _checked_bars(bars, instant, calendar, settings)
        payload = json.dumps(
            [bar.model_dump(mode="json") for bar in checked], sort_keys=True, separators=(",", ":")
        )
        completed_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        def unavailable(reason: str) -> ScannerResult:
            return ScannerResult(
                symbol=symbol,
                as_of=instant,
                status=ProviderStatus.UNAVAILABLE,
                data_snapshot_hash=data_snapshot_hash,
                completed_bars_hash=completed_hash,
                indicators=None,
                hits=(),
                reason=reason,
            )

        if market_status != MarketStatus.OK:
            return unavailable("DAT-02: symbol is SUSPECT pending operator acknowledgement")
        if len(checked) < 200:
            return unavailable("GD-03: 200 completed sessions are required for indicator warmup")
        anchor = _anchor(checked, earnings_gap, settings)
        if anchor is None:
            return unavailable("GD-03: no attested earnings gap or confirmed swing-low anchor")
        if memo is not None and not isinstance(memo, indicators.IndicatorMemo):
            raise DataIntegrityError("DAT-05: indicator memo must be explicitly validated")
        series = (memo if memo is not None else indicators.IndicatorMemo()).calculate(
            symbol, checked, anchor[0]
        )
        values = (
            series.ema20[-1],
            series.ema50[-1],
            series.ema200[-1],
            series.rsi14[-1],
            series.atr14[-1],
            series.macd.line[-1],
            series.macd.signal[-1],
            series.macd.histogram[-1],
            series.rvol20[-1],
            series.anchored_vwap[-1],
        )
        if any(value is None for value in values):
            return unavailable("GD-03: one or more required indicators are undefined")
        present = tuple(cast(Decimal, value) for value in values)
        facts = IndicatorSnapshot(
            session=checked[-1].session_date,
            close=checked[-1].close,
            ema20=present[0],
            ema50=present[1],
            ema200=present[2],
            rsi14=present[3],
            atr14=present[4],
            macd_line=present[5],
            macd_signal=present[6],
            macd_histogram=present[7],
            rvol20=present[8],
            anchored_vwap=present[9],
            anchor_session=checked[anchor[0]].session_date,
            anchor_kind=anchor[1],
        )
        anomalous = (
            facts.rvol20 >= settings.anomalous_rvol
            and facts.rsi14 >= settings.momentum_rsi
            and facts.macd_histogram > 0
            and facts.close > facts.ema20
        )
        hits = (
            (
                ScannerHit(
                    symbol=symbol,
                    as_of=instant,
                    last_price=facts.close,
                    rvol=facts.rvol20,
                    rsi=facts.rsi14,
                    reason="GD-03: anomalous prior-20-session RVOL and positive RSI/MACD/EMA20 momentum",
                ),
            )
            if anomalous
            else ()
        )
        return ScannerResult(
            symbol=symbol,
            as_of=instant,
            status=ProviderStatus.OK,
            data_snapshot_hash=data_snapshot_hash,
            completed_bars_hash=completed_hash,
            indicators=facts,
            hits=hits,
            reason="GD-03: completed daily indicators computed deterministically",
        )
    except SafetyError:
        raise
    except Exception as exc:
        raise DataIntegrityError(
            "R-02/GD-03: scanner inputs or computation cannot be verified"
        ) from exc
