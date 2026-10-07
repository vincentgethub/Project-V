"""GD-03: public, informational relative returns; no score or size changes."""

from datetime import datetime
from decimal import Decimal, localcontext
from types import MappingProxyType
from typing import Protocol, Self

from pydantic import Field, model_validator

from backend.agents.indicators import ema
from backend.agents.scanner import ScannerConfig, _checked_bars
from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar, BatchBars
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    FrozenModel,
    MarketStatus,
    Money,
    ProviderStatus,
    Symbol,
    UTCDateTime,
    validate_symbol,
)

SECTOR_ETFS = MappingProxyType(
    {
        "Information Technology": "XLK",
        "Communication Services": "XLC",
        "Consumer Discretionary": "XLY",
        "Consumer Staples": "XLP",
        "Energy": "XLE",
        "Financials": "XLF",
        "Industrials": "XLI",
        "Materials": "XLB",
        "Real Estate": "XLRE",
        "Utilities": "XLU",
        "Health Care": "XLV",
    }
)


class PeerStrength(FrozenModel):
    symbol: Symbol
    as_of: UTCDateTime
    status: ProviderStatus
    sector_etf: Symbol | None = None
    lookback_sessions: int = Field(default=20, strict=True, ge=20, le=20)
    relative_sector_return: Money | None = None
    relative_spy_return: Money | None = None
    spy_above_ema200: bool | None = Field(default=None, strict=True)
    reason: str = Field(min_length=1, max_length=280)

    @model_validator(mode="after")
    def evidence_bound(self) -> Self:
        facts = (self.relative_sector_return, self.relative_spy_return, self.spy_above_ema200)
        if self.status == ProviderStatus.OK:
            if self.sector_etf is None or any(value is None for value in facts):
                raise ValueError("peer OK needs aligned stock/sector/SPY evidence")
        elif any(value is not None for value in facts):
            raise ValueError("unavailable peers cannot carry inferred return or regime")
        return self


class PeerProvider(Protocol):
    async def get(self, symbol: str, as_of: datetime) -> PeerStrength: ...


class NullPeerProvider:
    async def get(self, symbol: str, as_of: datetime) -> PeerStrength:
        return PeerStrength(
            symbol=symbol,
            as_of=ensure_utc(as_of),
            status=ProviderStatus.UNAVAILABLE,
            reason="stock/sector/SPY completed bars unavailable",
        )


class BatchPeerProvider:
    """Use the exact shared daily stock/benchmark batch; no extra API requests."""

    def __init__(
        self, batch: BatchBars, registry: InstrumentRegistry, calendar: MarketCalendar
    ) -> None:
        self.batch = BatchBars.model_validate(batch)
        self.registry, self.calendar = registry, calendar

    async def get(self, symbol: str, as_of: datetime) -> PeerStrength:
        if ensure_utc(as_of) != self.batch.as_of:
            raise DataIntegrityError("GD-03: peer context differs from the scanner batch time")
        sector = SECTOR_ETFS.get(self.registry.get(symbol).gics_sector)
        available = {
            row.symbol
            for row in self.batch.entries
            if row.adjustment == "ALL" and row.status == MarketStatus.OK
        }
        if sector is None or not {symbol, sector, "SPY"}.issubset(available):
            return await NullPeerProvider().get(symbol, as_of)
        return calculate_peer_strength(
            symbol,
            self.batch.for_symbol(symbol, "ALL"),
            self.batch.for_symbol(sector, "ALL"),
            self.batch.for_symbol("SPY", "ALL"),
            registry=self.registry,
            calendar=self.calendar,
            as_of=as_of,
        )


def calculate_peer_strength(
    symbol: str,
    stock: tuple[Bar, ...],
    sector: tuple[Bar, ...],
    spy: tuple[Bar, ...],
    *,
    registry: InstrumentRegistry,
    calendar: MarketCalendar,
    as_of: datetime,
) -> PeerStrength:
    """Fixed 20-session return differences plus SPY/EMA200 context.

    The window is an explicit informational implementation choice, not an edge
    estimate or tuning parameter. Freshness and session alignment are required.
    """
    try:
        validate_symbol(symbol)
        instant = ensure_utc(as_of)
        sector_symbol = SECTOR_ETFS.get(registry.get(symbol).gics_sector)
        if sector_symbol is None or min(len(stock), len(sector), len(spy)) < 200:
            return PeerStrength(
                symbol=symbol,
                as_of=instant,
                status=ProviderStatus.UNAVAILABLE,
                sector_etf=sector_symbol,
                reason="known sector mapping and 200 completed sessions required",
            )
        rows = tuple(
            _checked_bars(bars, instant, calendar, ScannerConfig()) for bars in (stock, sector, spy)
        )
        if len({tuple(bar.session_date for bar in bars[-200:]) for bars in rows}) != 1:
            raise DataIntegrityError("GD-03: peer bar sessions differ")
        trend = ema(tuple(bar.close for bar in rows[2]), 200)[-1]
        if trend is None:
            raise DataIntegrityError("GD-03: peer benchmark EMA is undefined")
        with localcontext() as context:
            context.prec = 80
            returns = tuple(bars[-1].close / bars[-21].close - 1 for bars in rows)
            return PeerStrength(
                symbol=symbol,
                as_of=instant,
                status=ProviderStatus.OK,
                sector_etf=sector_symbol,
                relative_sector_return=(returns[0] - returns[1]).quantize(Decimal("0.000001")),
                relative_spy_return=(returns[0] - returns[2]).quantize(Decimal("0.000001")),
                spy_above_ema200=rows[2][-1].close > trend,
                reason="20-session stock return minus sector ETF/SPY; informational only",
            )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("GD-03: public peer evidence failed validation") from None
