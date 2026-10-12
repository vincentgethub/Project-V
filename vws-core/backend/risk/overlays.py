"""PR: pure reduction-only sizing before the independent final CRO check."""

from decimal import Decimal, localcontext

from backend.core.config import SizingConfig
from backend.core.errors import DataIntegrityError
from backend.domain.models import PortfolioSnapshot, Side, TradeProposal
from backend.domain.models import SizeEvidence as SizeEvidence


def open_risk(snapshot: PortfolioSnapshot) -> Decimal:
    """Uncovered shares and unknown pending stops reserve full cost/notional."""
    checked = PortfolioSnapshot.model_validate(snapshot)
    with localcontext() as precision:
        precision.prec = 256
        total = Decimal(0)
        for symbol, position in checked.positions.items():
            covered = 0
            for stop in sorted(
                (s for s in checked.protective_stops if s.symbol == symbol),
                key=lambda s: s.stop_price,
            ):
                qty = min(stop.qty, position.qty - covered)
                if qty > 0:
                    total += max(Decimal(0), position.avg_cost - stop.stop_price) * qty
                    covered += qty
            total += position.avg_cost * (position.qty - covered)
        for order in checked.open_orders:
            if order.side == Side.BUY:
                total += (order.limit_price - (order.stop_price or Decimal(0))) * order.qty
        return total


def fit_open_risk(
    base_qty: int, proposal: TradeProposal, snapshot: PortfolioSnapshot, cap: Decimal
) -> int:
    checked = TradeProposal.model_validate(proposal)
    account = PortfolioSnapshot.model_validate(snapshot)
    if (
        type(base_qty) is not int
        or not 0 <= base_qty <= 10**9
        or not isinstance(cap, Decimal)
        or not cap.is_finite()
        or not 0 <= cap <= Decimal("0.06")
        or account.account_id != checked.account_id
        or checked.stop_price is None
    ):
        raise DataIntegrityError("PR-01: invalid sizing evidence")
    with localcontext() as precision:
        precision.prec = 256
        available = max(Decimal(0), cap * account.equity - open_risk(account))
        return min(base_qty, int(available / (checked.limit_price - checked.stop_price)))


def volatility_multiplier(sigma: Decimal, anchor: Decimal) -> Decimal:
    if any(not isinstance(x, Decimal) or not x.is_finite() or x < 0 for x in (sigma, anchor)):
        raise DataIntegrityError("PR-03: invalid volatility evidence")
    return Decimal(1) if sigma == 0 else max(Decimal("0.25"), min(Decimal(1), anchor / sigma))


def confidence_multiplier(score: Decimal, policy: SizingConfig) -> Decimal:
    config = SizingConfig.model_validate(policy)
    if not isinstance(score, Decimal) or not score.is_finite() or not 0 <= score <= 10:
        raise DataIntegrityError("SZ-01: invalid score")
    if config.confidence_mode == "off":
        return Decimal(1)
    eligible = [multiplier for start, multiplier in config.confidence_bands if score >= start]
    return eligible[-1] if eligible else Decimal(0)
