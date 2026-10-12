"""PR/RS/SZ: shared, causal reduction evidence for connected and replay sizing."""

from collections.abc import Mapping
from datetime import date
from decimal import ROUND_FLOOR, Decimal, localcontext
from types import MappingProxyType

from pydantic import Field

from backend.core.config import YamlConfig
from backend.core.errors import DataIntegrityError
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import FrozenModel, Money, PortfolioSnapshot, SizeEvidence
from backend.indicators.portfolio import Prices, correlation, prices, volatility
from backend.indicators.vectorized import ema_last
from backend.ops.trading_controls import regime_multiplier
from backend.risk.overlays import confidence_multiplier, volatility_multiplier
from backend.risk.relative_strength import RelativeStrength, assess, breadth_regime

ONE = Decimal(1)


class PortfolioSizing(FrozenModel):
    factors: SizeEvidence
    relative_strength: RelativeStrength
    regime: str = Field(pattern=r"^(RISK_ON|NEUTRAL|RISK_OFF)$")
    breadth: Money | None = Field(ge=0, le=1)
    correlation_unknown: bool = Field(strict=True)


class PortfolioSizer:
    """One detached completed market frame; fresh portfolio checks on every call.

    This memo is private process state, never accepted as external evidence.
    Only immutable public price inputs and market indicators are reused. Cash,
    positions, correlations, scores, ramp, event reductions and CRO stay fresh.
    """

    def __init__(
        self,
        split_prices: Mapping[str, Prices],
        all_prices: Mapping[str, Prices],
        registry: InstrumentRegistry,
        config: YamlConfig,
        session: date,
    ) -> None:
        self._policy = YamlConfig.model_validate(config)
        if type(session) is not date or max(len(split_prices), len(all_prices)) > 1000:
            raise DataIntegrityError("PR/RS: bounded completed-session sizing inputs required")
        checked = []
        for mapping in (split_prices, all_prices):
            detached = {}
            for name, rows in mapping.items():
                registry.get(name)
                observations = prices(rows)
                if observations[-1][0] != session:
                    raise DataIntegrityError("PR/RS: price series has another completed tail")
                detached[name] = observations
            checked.append(MappingProxyType(detached))
        self._split = checked[0]
        # All full histories were checked above. RS consumes only 126 completed
        # returns; shorter endpoint slices cannot change its computed evidence.
        self._all = MappingProxyType({name: rows[-127:] for name, rows in checked[1].items()})
        self._registry, self.session = registry, session
        spy = self._split.get("SPY")
        if spy is None:
            raise DataIntegrityError("PR/RS: candidate or SPY evidence is unavailable")
        average = ema_last(tuple(price for _, price in spy), 200)
        if average is None:
            raise DataIntegrityError("RS-04: SPY EMA200 is unavailable")
        self._average, self._spy_close = average, spy[-1][1]
        breadth_rows = []
        for name in self._policy.watchlist:
            watch_rows = self._split.get(name)
            if watch_rows is not None:
                value = ema_last(tuple(price for _, price in watch_rows), 50)
                if value is not None:
                    breadth_rows.append(watch_rows[-1][1] > value)
        self._breadth: Decimal | None = None
        if len(breadth_rows) == len(self._policy.watchlist):
            with localcontext() as precision:
                precision.prec = 80
                self._breadth = (Decimal(sum(breadth_rows)) / len(breadth_rows)).quantize(
                    Decimal("0.000001")
                )
        self._regime = breadth_regime(
            spy[-1][1] > average, self._breadth, self._policy.rs.use_breadth
        )
        sigma, anchor = volatility(spy, self._policy.pr.vol_anchor)
        self._volatility = volatility_multiplier(sigma, anchor).quantize(
            Decimal("0.000001"), rounding=ROUND_FLOOR
        )
        self._strengths: dict[str, RelativeStrength] = {}

    def assess(
        self,
        symbol: str,
        score: Decimal,
        base_qty: int,
        portfolio: PortfolioSnapshot,
        *,
        auto: bool,
        ramp: Decimal = ONE,
        events: Decimal = ONE,
    ) -> PortfolioSizing:
        account = PortfolioSnapshot.model_validate(portfolio)
        if type(auto) is not bool:
            raise DataIntegrityError("PR/RS: explicit automatic-mode identity required")
        candidate = self._split.get(symbol)
        if candidate is None:
            raise DataIntegrityError("PR/RS: candidate or SPY evidence is unavailable")
        policy = self._policy
        if policy.rs.use_breadth:
            action = policy.regime_filter.auto
            regime_factor = (
                ONE
                if not auto or self._regime != "RISK_OFF" or action == "annotate"
                else Decimal("0.5")
                if action == "half_size"
                else Decimal(0)
            )
        else:
            regime_factor = regime_multiplier(
                self._spy_close, self._average, policy.regime_filter, auto=auto
            )
        k, unknown = 0, False
        for name, held in account.positions.items():
            if held.qty == 0:
                continue
            rows = self._split.get(name)
            observed = None if rows is None else correlation(candidate[-61:], rows[-61:])
            if observed is None:
                unknown = True
            elif observed >= policy.pr.corr_threshold:
                k += 1
        corr = policy.pr.corr_multipliers[min(k, 3)]
        if unknown:
            corr = min(corr, policy.pr.corr_multipliers[1])
        if symbol not in self._strengths:
            self._strengths[symbol] = assess(
                symbol, self._all, policy.watchlist, self._registry, policy.rs
            )
        strength = RelativeStrength.model_validate(self._strengths[symbol])
        return PortfolioSizing(
            factors=SizeEvidence(
                base_qty=base_qty,
                regime=regime_factor,
                ramp=ramp,
                correlation=corr,
                volatility=self._volatility,
                relative_strength=strength.multiplier,
                confidence=confidence_multiplier(score, policy.sizing),
                events=events,
                minimum=policy.sizing.min_multiplier,
            ),
            relative_strength=strength,
            regime=self._regime,
            breadth=self._breadth,
            correlation_unknown=unknown,
        )


def assess_size(
    symbol: str,
    score: Decimal,
    base_qty: int,
    portfolio: PortfolioSnapshot,
    split_prices: Mapping[str, Prices],
    all_prices: Mapping[str, Prices],
    registry: InstrumentRegistry,
    config: YamlConfig,
    session: date,
    *,
    auto: bool,
    ramp: Decimal = ONE,
    events: Decimal = ONE,
) -> PortfolioSizing:
    return PortfolioSizer(split_prices, all_prices, registry, config, session).assess(
        symbol,
        score,
        base_qty,
        portfolio,
        auto=auto,
        ramp=ramp,
        events=events,
    )
