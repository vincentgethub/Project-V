"""QV-05: family correction and deflated daily Sharpe; no parameter search."""

from decimal import Decimal
from statistics import NormalDist

import numpy as np

from backend.core.errors import DataIntegrityError
from backend.indicators.statistics import _exact, _samples


def holm(
    p_values: tuple[Decimal, ...], alpha: Decimal = Decimal("0.10"), *, unobserved_trials: int = 0
) -> tuple[bool, ...]:
    if (
        not isinstance(p_values, tuple)
        or not 1 <= len(p_values) <= 24
        or not isinstance(alpha, Decimal)
        or not alpha.is_finite()
        or not 0 < alpha <= Decimal("0.10")
        or type(unobserved_trials) is not int
        or not 0 <= unobserved_trials <= 1000000
        or any(not isinstance(p, Decimal) or not p.is_finite() or not 0 <= p <= 1 for p in p_values)
    ):
        raise DataIntegrityError("QV-05: invalid family p-values or alpha")
    result = [False] * len(p_values)
    for rank, index in enumerate(sorted(range(len(p_values)), key=lambda i: (p_values[i], i))):
        # LP-02: cumulative attempts with unavailable p-values remain in the
        # family denominator, conservatively equivalent to padding with ones.
        if p_values[index] > alpha / (len(p_values) + unobserved_trials - rank):
            break
        result[index] = True
    return tuple(result)


def deflated_sharpe(
    selected: tuple[Decimal, ...], variants: tuple[tuple[Decimal, ...], ...], trials: int
) -> Decimal | None:
    """Daily, unannualized SR in the stated Bailey/Lopez de Prado formula."""
    if type(trials) is not int or not 1 <= trials <= 1000000:
        raise DataIntegrityError("QV-05: bounded cumulative trials required")
    if not isinstance(variants, tuple) or not 1 <= len(variants) <= 8:
        raise DataIntegrityError("QV-05: explicit registered variant series required")
    values = _samples(selected)
    rows = tuple(_samples(row) for row in variants)
    if any(len(row) != len(values) for row in rows):
        raise DataIntegrityError("QV-05: daily OOS dates/lengths must agree")
    if len(values) < 2:
        return None
    deviation = np.std(values, ddof=1)
    if deviation <= 0:
        return None
    if any(np.std(row, ddof=1) <= 0 for row in rows):
        return None
    mean = np.mean(values)
    sr = mean / deviation
    centered = values - mean
    second = np.mean(centered**2)
    skew = np.mean(centered**3) / second ** np.float64("1.5")
    kurtosis = np.mean(centered**4) / second**2
    sharpes = np.asarray(
        [np.mean(row) / np.std(row, ddof=1) for row in rows],
        dtype=np.float64,
    )
    variance = np.var(sharpes, ddof=1) if len(sharpes) > 1 else np.float64(0)
    threshold = np.float64(0)
    normal = NormalDist()
    if trials >= 2:
        gamma = np.float64("0.5772156649")
        threshold = np.sqrt(variance) * (
            (1 - gamma) * normal.inv_cdf(1 - 1 / trials)
            + gamma * normal.inv_cdf(1 - 1 / (trials * np.e))
        )
    denominator = 1 - skew * sr + ((kurtosis - 1) / 4) * sr**2
    if denominator <= 0:
        return None
    z = (sr - threshold) * np.sqrt(len(values) - 1) / np.sqrt(denominator)
    if not np.isfinite(z):
        raise DataIntegrityError("QV-05: deflated Sharpe is nonfinite")
    return _exact(np.float64(normal.cdf(z)))
