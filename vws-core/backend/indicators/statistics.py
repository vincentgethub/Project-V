"""ER-01/05 and QV-05 baseline math; float64 stays inside indicator math.

No model selection, parameter search, account inputs or persistent state lives
here. Samples are supplied in exit-date order. Bootstrap uses 10,000 circular
block resamples with a local generator; array sizes are bounded in batches.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pydantic import Field, model_validator

from backend.agents.indicators import _fail_closed
from backend.core.config import _bounded_exact_decimal
from backend.core.errors import DataIntegrityError
from backend.domain.models import FrozenModel
from backend.evaluation.costs import Exact

RESAMPLES = 10000
DEFAULT_SEED = 20261006
_QUANTUM = Decimal("0.000001")
_MAX_SAMPLE = 100000
Array = NDArray[np.float64]


def _samples(values: tuple[Decimal, ...]) -> Array:
    if not isinstance(values, tuple) or len(values) > _MAX_SAMPLE:
        raise DataIntegrityError("ER/QV: statistics require a bounded immutable sample")
    try:
        checked = tuple(_bounded_exact_decimal(value) for value in values)
        if any(not isinstance(value, Decimal) for value in values):
            raise ValueError("statistics accept exact Decimals only")
        result = np.asarray(checked, dtype=np.float64)
        if not np.all(np.isfinite(result)):
            raise ValueError("nonfinite numerical sample")
        return result
    except Exception:
        raise DataIntegrityError("ER/QV: malformed statistical sample") from None


def _exact(value: np.float64) -> Decimal:
    if not np.isfinite(value):
        raise DataIntegrityError("ER/QV: nonfinite statistical result")
    with localcontext() as precision:
        precision.prec = 256
        return _bounded_exact_decimal(
            Decimal(str(value)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
        )


class BootstrapEstimate(FrozenModel):
    lower: Exact
    upper: Exact
    p_nonpositive: Exact = Field(ge=0, le=1)
    block_length: int = Field(strict=True, ge=1)
    resamples: int = Field(default=RESAMPLES, strict=True, ge=RESAMPLES, le=RESAMPLES)
    seed: int = Field(strict=True, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def ordered(self) -> BootstrapEstimate:
        if self.lower > self.upper:
            raise ValueError("QV-05: confidence limits are reversed")
        return self


@_fail_closed
def circular_bootstrap(
    values: tuple[Decimal, ...], *, seed: int = DEFAULT_SEED
) -> BootstrapEstimate | None:
    """QV-05: 90% percentile CI and one-sided share of means <= 0."""
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise DataIntegrityError("QV-05: bootstrap seed must be a bounded integer")
    observed = _samples(values)
    count = len(observed)
    if count == 0:
        return None
    length = max(1, int(round(np.cbrt(count))))
    blocks = (count + length - 1) // length
    generator = np.random.default_rng(seed)
    means = np.empty(RESAMPLES, dtype=np.float64)
    batch = max(1, min(128, 1_000_000 // count))
    offsets = np.arange(length, dtype=np.int64)
    for start in range(0, RESAMPLES, batch):
        size = min(batch, RESAMPLES - start)
        starts = generator.integers(0, count, size=(size, blocks))
        indices = ((starts[:, :, None] + offsets) % count).reshape(size, -1)[:, :count]
        means[start : start + size] = np.mean(observed[indices], axis=1, dtype=np.float64)
    limits = np.percentile(means, [5, 95], method="linear")
    with localcontext() as precision:
        precision.prec = 80
        probability = Decimal(int(np.count_nonzero(means <= 0))) / RESAMPLES
    return BootstrapEstimate(
        lower=_exact(limits[0]),
        upper=_exact(limits[1]),
        p_nonpositive=probability,
        block_length=length,
        seed=seed,
    )


class ReturnStatistics(FrozenModel):
    sharpe: Exact | None
    sortino: Exact | None


@_fail_closed
def annualized_returns(values: tuple[Decimal, ...]) -> ReturnStatistics:
    """ER-01: daily sample-standard-deviation Sharpe, target-zero Sortino."""
    observed = _samples(values)
    if len(observed) < 2:
        return ReturnStatistics(sharpe=None, sortino=None)
    mean = np.mean(observed, dtype=np.float64)
    deviation = np.std(observed, ddof=1, dtype=np.float64)
    downside = np.sqrt(np.mean(np.minimum(observed, 0) ** 2, dtype=np.float64))
    annualizer = np.sqrt(np.float64(252))
    return ReturnStatistics(
        sharpe=_exact(mean / deviation * annualizer) if deviation > 0 else None,
        sortino=_exact(mean / downside * annualizer) if downside > 0 else None,
    )


@_fail_closed
def spearman(scores: tuple[Decimal, ...], r_multiples: tuple[Decimal, ...]) -> Decimal | None:
    """ER-05: average ranks for ties, no fabricated correlation for constants."""
    x, y = _samples(scores), _samples(r_multiples)
    if len(x) != len(y):
        raise DataIntegrityError("ER-05: score and outcome sample lengths differ")
    if len(x) < 2 or np.all(x == x[0]) or np.all(y == y[0]):
        return None
    ranked_x = pd.Series(x).rank(method="average").to_numpy(dtype=np.float64)
    ranked_y = pd.Series(y).rank(method="average").to_numpy(dtype=np.float64)
    return _exact(np.corrcoef(ranked_x, ranked_y)[0, 1])
