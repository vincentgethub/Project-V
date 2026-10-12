"""PR/RS/SZ/QV hand-computed boundaries and exposure properties."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.core.clock import FrozenClock
from backend.core.config import RelativeStrengthConfig, SizingConfig, VerdictConfig
from backend.core.errors import DataIntegrityError
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import ProtectiveStop
from backend.indicators.portfolio import correlation, prices, volatility
from backend.indicators.validation import deflated_sharpe, holm
from backend.risk.overlays import (
    SizeEvidence,
    confidence_multiplier,
    fit_open_risk,
    open_risk,
    volatility_multiplier,
)
from backend.risk.relative_strength import SECTORS, assess, breadth_regime
from backend.tests.test_risk_cro import _position, _proposal, _snapshot

D = Decimal
PROJECT = Path(__file__).resolve().parents[2]


def test_PR_01_exact_portfolio_risk_golden_and_unknown_protection(clock: FrozenClock) -> None:
    book = _snapshot(
        clock,
        positions={"MSFT": _position(40)},
        protective_stops=(ProtectiveStop(symbol="MSFT", qty=40, stop_price=D(92)),),
    )
    proposal = _proposal(clock, qty=60, stop_price=D(98))
    assert open_risk(book) == 320
    assert fit_open_risk(60, proposal, book, D("0.04")) == 40
    assert fit_open_risk(60, proposal, book, D("0.02")) == 0
    assert open_risk(book.model_copy(update={"protective_stops": ()})) == 4000
    assert (
        open_risk(
            book.model_copy(
                update={
                    "protective_stops": (ProtectiveStop(symbol="MSFT", qty=20, stop_price=D(92)),)
                }
            )
        )
        == 2160
    )


@pytest.mark.parametrize(
    "sigma, expected", [(D("0.32"), D("0.5")), (D("0.10"), D(1)), (D(0), D(1)), (D(2), D("0.25"))]
)
def test_PR_03_volatility_boundaries(sigma: Decimal, expected: Decimal) -> None:
    assert volatility_multiplier(sigma, D("0.16")) == expected


def test_PR_04_one_product_one_floor_and_skip() -> None:
    assert SizeEvidence(base_qty=40, correlation=D("0.75"), volatility=D("0.5")).qty == 15
    assert SizeEvidence(base_qty=40, volatility=D("0.5"), regime=D("0.4")).qty == 0
    assert SizeEvidence(base_qty=3, correlation=D("0.75"), volatility=D("0.5")).qty == 1


@given(st.integers(0, 100000), st.integers(0, 100), st.integers(0, 100), st.integers(0, 100))
def test_PR_05_overlays_never_increase_whole_share_exposure(
    qty: int, regime: int, vol: int, corr: int
) -> None:
    evidence = SizeEvidence(
        base_qty=qty, regime=D(regime) / 100, volatility=D(vol) / 100, correlation=D(corr) / 100
    )
    assert 0 <= evidence.qty <= qty and 0 <= evidence.product <= 1


@pytest.mark.parametrize(
    "score, expected",
    [
        ("7", "0.5"),
        ("7.999999", "0.5"),
        ("8", "0.75"),
        ("8.999999", "0.75"),
        ("9", "1"),
        ("10", "1"),
        ("6.99", "0"),
    ],
)
def test_SZ_01_confidence_bands(score: str, expected: str) -> None:
    assert confidence_multiplier(D(score), SizingConfig(confidence_mode="bands")) == D(expected)
    assert confidence_multiplier(D(score), SizingConfig()) == 1


@pytest.mark.parametrize(
    "bands",
    [
        ((D(7), D("0.8")), (D(8), D("0.5"))),
        ((D(7), D(1)), (D(7), D(1))),
        ((D(7), D(0)),),
        ((D(7), D("1.01")),),
    ],
)
def test_SZ_01_invalid_confidence_bands_refused(bands: Any) -> None:
    with pytest.raises(ValidationError):
        SizingConfig(confidence_bands=bands)


@pytest.mark.parametrize(
    "values, expected",
    [
        (("0.01", "0.04", "0.08"), (True, True, True)),
        (("0.01", "0.06", "0.08"), (True, False, False)),
        (("0.1",), (True,)),
    ],
)
def test_QV_05_hand_computed_holm(values: tuple[str, ...], expected: tuple[bool, ...]) -> None:
    assert holm(tuple(D(value) for value in values)) == expected


def test_QV_05_daily_dsr_equals_psr_at_one_trial_and_deflates_multiple_trials() -> None:
    centered = (D("-0.01"), D(0), D("0.01"))
    assert deflated_sharpe(centered, (centered,), 1) == D("0.5")
    positive = (D(0), D("0.01"), D("0.02"))
    assert deflated_sharpe(centered, (centered, positive), 2) < D("0.5")  # type: ignore[operator]
    assert deflated_sharpe((), ((),), 1) is None
    assert deflated_sharpe(centered, ((D(0),) * 3,), 2) is None
    with pytest.raises(DataIntegrityError):
        deflated_sharpe(centered, (positive,), 0)
    with pytest.raises(DataIntegrityError):
        deflated_sharpe(centered, ((D(0),),), 1)


def series(slope: int, count: int = 127) -> tuple[tuple[date, Decimal], ...]:
    return tuple(
        (date(2025, 1, 1) + timedelta(days=i), D(100) + D(i * slope) / 100) for i in range(count)
    )


@pytest.mark.parametrize(
    "mode, expected", [("annotate", D(1)), ("half_size_outside", D("0.5")), ("top_n", D(0))]
)
def test_RS_01_03_eleven_sector_golden_each_filter(mode: str, expected: Decimal) -> None:
    registry = InstrumentRegistry.from_csv(PROJECT / "config")
    rows = {name: series(i + 1) for i, name in enumerate(sorted(SECTORS.values()))}
    rows["SPY"] = series(0)
    result = assess(
        "XLB",
        rows,
        tuple(rows),
        registry,
        RelativeStrengthConfig.model_validate({"sector_filter": mode}),
    )
    assert result.sector_rank == 11 and result.top_sectors == ("XLY", "XLV", "XLU", "XLRE")
    assert result.multiplier == expected and result.stock_percentile is None
    exempt = assess(
        "SPY",
        rows,
        tuple(rows),
        registry,
        RelativeStrengthConfig.model_validate({"sector_filter": mode}),
    )
    assert exempt.multiplier == 1


@pytest.mark.parametrize(
    "spy, breadth, expected",
    [
        (True, D("0.5"), "RISK_ON"),
        (True, D("0.499999"), "NEUTRAL"),
        (False, D("0.5"), "NEUTRAL"),
        (False, D("0.499999"), "RISK_OFF"),
    ],
)
def test_RS_04_breadth_boundary(spy: bool, breadth: Decimal, expected: str) -> None:
    assert breadth_regime(spy, breadth, True) == expected
    assert breadth_regime(spy, None, False) == ("RISK_ON" if spy else "RISK_OFF")


def test_PR_02_03_returns_missing_overlap_and_fallback_anchor() -> None:
    assert correlation(series(1), series(1)) == 1
    assert correlation(series(1, 50), series(1)) is None
    assert correlation(series(0), series(1)) is None
    sigma, anchor = volatility(series(1))
    assert sigma >= 0 and anchor == D("0.16")
    with pytest.raises(DataIntegrityError):
        volatility(series(1, 20))


@pytest.mark.parametrize("price", [D("NaN"), D("Infinity"), D(0), D("1e129"), 1.0, True])
def test_PR_malformed_price_samples_fail_with_typed_error(price: Any) -> None:
    with pytest.raises(DataIntegrityError):
        prices(((date(2026, 1, 1), price),))


@pytest.mark.parametrize(
    "field, value",
    [
        ("min_paper_trades", 49),
        ("min_sessions", 59),
        ("max_drawdown", D("0.100001")),
        ("benchmark_sharpe_tolerance", D("0.200001")),
        ("no_halt_sessions", 19),
        ("drill_max_age_days", 32),
        ("ready_max_age_days", 36),
    ],
)
def test_GV_02_thresholds_never_weaken(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        VerdictConfig.model_validate({field: value})
