"""RS-01..05: exact all-adjusted comparisons; no change to setup scores."""

from collections.abc import Mapping
from decimal import Decimal, localcontext

from pydantic import Field

from backend.core.config import RelativeStrengthConfig
from backend.core.errors import DataIntegrityError
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, FrozenModel, Money, Symbol
from backend.indicators.portfolio import Prices, prices

SECTORS = {
    "Materials": "XLB",
    "Communication Services": "XLC",
    "Energy": "XLE",
    "Financials": "XLF",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Consumer Staples": "XLP",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
}


class RelativeStrength(FrozenModel):
    symbol: Symbol
    relative_return: Money | None
    stock_percentile: Money | None = Field(ge=0, le=100)
    sector_etf: Symbol | None
    sector_rank: int | None = Field(strict=True, ge=1, le=11)
    top_sectors: tuple[Symbol, ...] = Field(max_length=11)
    multiplier: Money = Field(ge=0, le=1)
    reason: str = Field(strict=True, min_length=1, max_length=280)


def relative_return(stock: Prices, benchmark: Prices) -> Decimal | None:
    first, second = prices(stock), prices(benchmark)
    if len(first) < 127 or len(second) < 127:
        return None
    if tuple(day for day, _ in first[-127:]) != tuple(day for day, _ in second[-127:]):
        raise DataIntegrityError("RS-01: return endpoints use different completed sessions")
    with localcontext() as context:
        context.prec = 80
        return (
            sum(
                (
                    first[-1][1] / first[-1 - span][1] - second[-1][1] / second[-1 - span][1]
                    for span in (63, 126)
                ),
                Decimal(0),
            )
            / 2
        )


def assess(
    symbol: str,
    all_prices: Mapping[str, Prices],
    watchlist: tuple[str, ...],
    registry: InstrumentRegistry,
    policy: RelativeStrengthConfig,
) -> RelativeStrength:
    config = RelativeStrengthConfig.model_validate(policy)
    instrument = registry.get(symbol)
    if (
        len(all_prices) > 1000
        or not isinstance(watchlist, tuple)
        or len(set(watchlist)) != len(watchlist)
    ):
        raise DataIntegrityError("RS-01/02: bounded unique universe required")
    benchmark = all_prices.get("SPY")
    if benchmark is None:
        raise DataIntegrityError("RS-01: all-adjusted SPY benchmark is unavailable")
    ranks = {}
    for etf in sorted(SECTORS.values()):
        rows = all_prices.get(etf)
        if rows is not None:
            value = relative_return(rows, benchmark)
            if value is not None:
                ranks[etf] = value
    ranked = tuple(sorted(ranks, key=lambda key: (-ranks[key], key))) if len(ranks) == 11 else ()
    values = {}
    for name in watchlist:
        registry.get(name)
        rows = all_prices.get(name)
        if rows is not None:
            value = relative_return(rows, benchmark)
            if value is not None:
                values[name] = value
    percentile = None
    result = values.get(symbol)
    if result is None and symbol in all_prices:
        result = relative_return(all_prices[symbol], benchmark)
    if len(values) >= 20 and symbol in values:
        lower = sum(value < values[symbol] for value in values.values())
        ties = sum(value == values[symbol] for value in values.values())
        with localcontext() as context:
            context.prec = 80
            percentile = (Decimal(lower) + Decimal(ties - 1) / 2) * 100 / (len(values) - 1)
    sector = (
        symbol
        if instrument.asset_class == AssetClass.SECTOR_ETF
        else SECTORS.get(instrument.gics_sector)
    )
    exempt = instrument.asset_class in {AssetClass.BROAD_ETF, AssetClass.CASH_EQUIV}
    rank = ranked.index(sector) + 1 if sector in ranked else None
    multiplier = Decimal(1)
    reasons = []
    if not ranked:
        reasons.append("sector rank unavailable")
    if config.min_stock_percentile > 0 and not exempt:
        if percentile is None or percentile < config.min_stock_percentile:
            multiplier = Decimal(0)
            reasons.append("stock percentile below threshold or unavailable")
    if (
        config.sector_filter != "annotate"
        and not exempt
        and (rank is None or rank > config.top_n_sectors)
    ):
        multiplier = min(
            multiplier,
            Decimal("0.5") if config.sector_filter == "half_size_outside" else Decimal(0),
        )
        reasons.append("outside top sectors or rank unavailable")
    if percentile is None:
        reasons.append("stock percentile n/a: fewer than 20 available symbols")
    return RelativeStrength(
        symbol=symbol,
        relative_return=None if result is None else result.quantize(Decimal("0.000001")),
        stock_percentile=None if percentile is None else percentile.quantize(Decimal("0.000001")),
        sector_etf=sector,
        sector_rank=rank,
        top_sectors=ranked[: config.top_n_sectors],
        multiplier=multiplier,
        reason="; ".join(reasons) or "all-adjusted sector and stock comparisons available",
    )


def breadth_regime(spy_above: bool, breadth: Decimal | None, enabled: bool) -> str:
    if type(spy_above) is not bool or type(enabled) is not bool:
        raise DataIntegrityError("RS-04: explicit regime evidence required")
    if not enabled:
        return "RISK_ON" if spy_above else "RISK_OFF"
    if not isinstance(breadth, Decimal) or not breadth.is_finite() or not 0 <= breadth <= 1:
        raise DataIntegrityError("RS-04: breadth is unavailable")
    passing = int(spy_above) + int(breadth >= Decimal("0.5"))
    return ("RISK_OFF", "NEUTRAL", "RISK_ON")[passing]
