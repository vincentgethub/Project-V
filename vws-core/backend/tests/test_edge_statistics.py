"""QV/ER statistical goldens and exact kill-switch boundaries, no I/O."""

from decimal import Decimal, localcontext
from itertools import product
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.indicators.statistics import (
    BootstrapEstimate,
    annualized_returns,
    circular_bootstrap,
    spearman,
)
from backend.ops.playbook_kill import playbook_kill_condition

D = Decimal


def test_QV_05_circular_bootstrap_seed_and_known_bounds() -> None:
    values = (D(2), D(-1), D("0.5"), D(-1), D(3))
    first = circular_bootstrap(values)
    assert first == circular_bootstrap(values)
    assert first is not None and first.resamples == 10000 and first.block_length == 2
    # Enumerate all 125 three-block paths using exact arithmetic independently.
    means = sorted(
        (values[a] + values[(a + 1) % 5] + values[b] + values[(b + 1) % 5] + values[c]) / 5
        for a, b, c in product(range(5), repeat=3)
    )
    assert first.lower == means[6] == means[7] == D("-0.4")
    assert first.upper == means[117] == means[118] == D("1.8")
    assert D(0) < first.p_nonpositive < 1
    different = circular_bootstrap(values, seed=1)
    assert different is not None and first.p_nonpositive != different.p_nonpositive
    assert circular_bootstrap(()) is None
    one = circular_bootstrap((D(-1),))
    assert one is not None and one.lower == one.upper == -1 and one.p_nonpositive == 1


def test_ER_01_daily_return_statistics_independent_decimal_golden() -> None:
    values = (D("0.01"), D("-0.02"), D("0.03"), D("-0.01"))
    actual = annualized_returns(values)
    with localcontext() as precision:
        precision.prec = 60
        mean = sum(values, D(0)) / D(4)
        variance = sum(((value - mean) ** 2 for value in values), D(0)) / D(3)
        downside = sum((min(value, D(0)) ** 2 for value in values), D(0)) / D(4)
        assert actual.sharpe == (mean / variance.sqrt() * D(252).sqrt()).quantize(D("0.000001"))
        assert actual.sortino == (mean / downside.sqrt() * D(252).sqrt()).quantize(D("0.000001"))
    constant = annualized_returns((D("0.01"),) * 3)
    assert constant.sharpe is None and constant.sortino is None
    assert annualized_returns((D(0),)).sharpe is None
    losing = annualized_returns((D("-0.01"),) * 3)
    assert losing.sortino == -D(252).sqrt().quantize(D("0.000001"))


def test_ER_05_spearman_ties_and_constants() -> None:
    assert spearman((D(7), D(8), D(9)), (D(-1), D(0), D(1))) == 1
    assert spearman((D(7), D(8), D(9)), (D(1), D(0), D(-1))) == -1
    assert spearman((D(7), D(7), D(9)), (D(-1), D(-1), D(1))) == 1
    assert spearman((D(7), D(7)), (D(-1), D(1))) is None
    assert spearman((D(7), D(8)), (D(1), D(1))) is None
    assert spearman((), ()) is None
    with pytest.raises(DataIntegrityError):
        spearman((D(7),), ())


@pytest.mark.parametrize(
    "count,mean,expected",
    [
        (29, "-1", False),
        (30, "-1", True),
        (30, "0", False),
        (30, "0.1", False),
        (50, "-0.000001", True),
    ],
)
def test_XK_05_exact_mean_boundary(count: int, mean: str, expected: bool) -> None:
    assert playbook_kill_condition((D(mean),) * count) is expected
    assert playbook_kill_condition((D("-1e-100"),) * 30)


@pytest.mark.parametrize("bad", [True, 1.0, "1", D("NaN"), D("1e129")])
def test_ER_invalid_statistical_inputs_fail_closed(bad: object) -> None:
    for operation in (circular_bootstrap, annualized_returns, playbook_kill_condition):
        with pytest.raises(DataIntegrityError):
            operation((bad,))  # type: ignore[arg-type]
    with pytest.raises(DataIntegrityError):
        circular_bootstrap((D(1),), seed=True)
    with pytest.raises(DataIntegrityError):
        annualized_returns([D(1)])  # type: ignore[arg-type]
    with pytest.raises(DataIntegrityError):
        playbook_kill_condition([D(1)])  # type: ignore[arg-type]


def test_QV_confidence_bounds_cannot_be_reversed() -> None:
    with pytest.raises(ValidationError):
        BootstrapEstimate(lower=D(1), upper=D(0), p_nonpositive=D(0), block_length=1, seed=1)


def test_ER_numerical_corruption_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:

    original = np.asarray

    def nonfinite_array(*args: Any, **kwargs: Any) -> Any:
        return original([D("Infinity")], dtype=np.float64)

    monkeypatch.setattr(np, "asarray", nonfinite_array)
    with pytest.raises(DataIntegrityError, match="malformed"):
        circular_bootstrap((D(1),))
    monkeypatch.setattr(np, "asarray", original)

    def nonfinite_limits(*args: Any, **kwargs: Any) -> Any:
        return original([D("NaN"), D("NaN")], dtype=np.float64)

    monkeypatch.setattr(np, "percentile", nonfinite_limits)
    with pytest.raises(DataIntegrityError, match="nonfinite"):
        circular_bootstrap((D(1),))
