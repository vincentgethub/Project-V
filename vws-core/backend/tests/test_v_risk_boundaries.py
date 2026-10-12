"""PR/RS/SZ: independent malformed evidence and reduction-only boundary gates."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from backend.core.clock import FrozenClock
from backend.core.config import (
    RelativeStrengthConfig,
    Settings,
    SizingConfig,
    YamlConfig,
    load_yaml_config,
)
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import OpenOrder, ProtectiveStop, Side
from backend.risk.overlays import (
    confidence_multiplier,
    fit_open_risk,
    open_risk,
    volatility_multiplier,
)
from backend.risk.portfolio_sizing import PortfolioSizer
from backend.risk.relative_strength import SECTORS, assess, breadth_regime, relative_return
from backend.risk.risk_cro import ChiefRiskOfficer
from backend.tests.test_risk_cro import _market, _position, _proposal, _registry, _snapshot
from backend.tests.test_v_risk import series

D = Decimal
ROOT = Path(__file__).resolve().parents[2]


def test_CRO14_internal_entry_rule_still_requires_protection(
    clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    cro = ChiefRiskOfficer(Settings(), _registry(), MarketCalendar())
    checked = cro._risk(_proposal(clock), _snapshot(clock))
    monkeypatch.setattr(cro, "_risk", lambda *a: checked)
    forged = _proposal(clock).model_copy(update={"stop_price": None})
    with pytest.raises(DataIntegrityError, match="entry protection"):
        cro._rules(forged, _snapshot(clock), _market(clock), clock.now(), None, False)


@pytest.mark.parametrize("qty", [True, -1, 10**9 + 1])
def test_PR_untrusted_base_quantity_refused(clock: FrozenClock, qty: Any) -> None:
    with pytest.raises(DataIntegrityError):
        fit_open_risk(qty, _proposal(clock), _snapshot(clock), D("0.04"))


@pytest.mark.parametrize("cap", [True, D("NaN"), D("Infinity"), D("-0.01"), D("0.060001")])
def test_PR_untrusted_risk_cap_refused(clock: FrozenClock, cap: Any) -> None:
    with pytest.raises(DataIntegrityError):
        fit_open_risk(1, _proposal(clock), _snapshot(clock), cap)


def test_PR_risk_fit_cannot_mix_accounts_or_unprotected_exit(clock: FrozenClock) -> None:
    with pytest.raises(DataIntegrityError):
        fit_open_risk(1, _proposal(clock), _snapshot(clock, account_id="other"), D("0.04"))
    exit_proposal = _proposal(clock, side=Side.SELL, intent="EXIT", stop_price=None)
    with pytest.raises(DataIntegrityError):
        fit_open_risk(1, exit_proposal, _snapshot(clock), D("0.04"))


def test_PR_excess_and_unrelated_stops_cannot_create_negative_open_risk(clock: FrozenClock) -> None:
    snapshot = _snapshot(
        clock,
        positions={"MSFT": _position(2)},
        protective_stops=(
            ProtectiveStop(symbol="MSFT", qty=5, stop_price=D(90)),
            ProtectiveStop(symbol="MSFT", qty=1, stop_price=D(110)),
            ProtectiveStop(symbol="IBM", qty=10, stop_price=D(90)),
        ),
        open_orders=(
            OpenOrder(symbol="AAPL", side=Side.BUY, qty=2, limit_price=D(100)),
            OpenOrder(symbol="IBM", side=Side.SELL, qty=2, limit_price=D(100)),
        ),
    )
    assert open_risk(snapshot) == 220


@pytest.mark.parametrize("value", [True, D("NaN"), D("Infinity"), D(-1)])
def test_PR_bad_volatility_evidence_refused(value: Any) -> None:
    with pytest.raises(DataIntegrityError):
        volatility_multiplier(value, D("0.16"))
    with pytest.raises(DataIntegrityError):
        volatility_multiplier(D("0.16"), value)


@pytest.mark.parametrize("value", [True, D("NaN"), D(-1), D("10.000001")])
def test_SZ_bad_score_refused_even_when_sizing_is_off(value: Any) -> None:
    with pytest.raises(DataIntegrityError):
        confidence_multiplier(value, SizingConfig())


def test_RS_short_or_misaligned_endpoints_never_produce_rank() -> None:
    assert relative_return(series(1, 126), series(0)) is None
    shifted = tuple((day + timedelta(days=1), price) for day, price in series(1))
    with pytest.raises(DataIntegrityError, match="different completed sessions"):
        relative_return(shifted, series(0))


@pytest.mark.parametrize("case", ["duplicate", "list", "bound", "benchmark"])
def test_RS_invalid_universe_and_missing_benchmark_refused(case: str) -> None:
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    mapping = {"SPY": series(0), "NVDA": series(1)}
    watchlist: Any = ("NVDA",)
    if case == "duplicate":
        watchlist = ("NVDA", "NVDA")
    elif case == "list":
        watchlist = ["NVDA"]
    elif case == "bound":
        mapping.update({f"fake{i}": series(0, 1) for i in range(1000)})
    else:
        mapping.pop("SPY")
    with pytest.raises(DataIntegrityError):
        assess("NVDA", mapping, watchlist, registry, RelativeStrengthConfig())


def test_RS_full_stock_percentile_and_short_optional_series() -> None:
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    config = load_yaml_config(ROOT / "config/config.yaml", allowed_symbols=registry.symbols)
    watchlist = config.watchlist[:20]
    mapping = {name: series(i + 1) for i, name in enumerate(watchlist)}
    mapping.update({name: series(1) for name in SECTORS.values()})
    mapping["SPY"] = series(0)
    assert len(watchlist) == 20
    policy = RelativeStrengthConfig(min_stock_percentile=D(50))
    lowest = assess(watchlist[0], mapping, watchlist, registry, policy)
    highest = assess(watchlist[-1], mapping, watchlist, registry, policy)
    assert lowest.stock_percentile == 0 and lowest.multiplier == 0
    assert highest.stock_percentile == 100 and highest.multiplier == 1
    mapping["XLB"] = series(1, 126)
    mapping[watchlist[0]] = series(1, 126)
    mapping.pop("XLC")
    mapping.pop(watchlist[1])
    partial = assess("XLK", mapping, watchlist, registry, policy)
    assert partial.sector_rank is None and partial.stock_percentile is None
    assert assess("SPY", mapping, watchlist, registry, policy).multiplier == 1


@pytest.mark.parametrize("value", [True, D("NaN"), D(-1), D("1.000001"), None])
def test_RS_missing_or_invalid_breadth_refused_when_required(value: Any) -> None:
    with pytest.raises(DataIntegrityError):
        breadth_regime(True, value, True)


@pytest.mark.parametrize("spy, enabled", [(1, False), (True, 1)])
def test_RS_regime_flags_require_boolean_identity(spy: Any, enabled: Any) -> None:
    with pytest.raises(DataIntegrityError):
        breadth_regime(spy, None, enabled)


@pytest.mark.parametrize(
    "case",
    [
        "session",
        "short_spy",
        "missing_candidate",
        "auto",
        "short_watch",
        "zero_held",
        "correlated",
        "uncorrelated",
    ],
)
def test_PR_sizing_frame_boundary_and_fresh_holdings(clock: FrozenClock, case: str) -> None:
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    policy = load_yaml_config(ROOT / "config/config.yaml", allowed_symbols=registry.symbols)
    rows = series(1, 260)
    mapping = {name: rows for name in (*policy.watchlist, "SPY")}
    session: Any = rows[-1][0]
    book = _snapshot(clock)
    if case == "session":
        session = "2025-09-17"
    elif case == "short_spy":
        mapping["SPY"] = rows[-199:]
    elif case == "missing_candidate":
        mapping.pop("NVDA")
    elif case == "short_watch":
        mapping["MSFT"] = rows[-49:]
    elif case in {"zero_held", "correlated", "uncorrelated"}:
        book = _snapshot(clock, positions={"MSFT": _position(int(case != "zero_held"))})
        if case == "uncorrelated":
            mapping["MSFT"] = tuple(
                (day, (D(100) + D(i * i) / 10000).quantize(D("0.01")))
                for i, (day, _) in enumerate(rows)
            )
    if case in {"session", "short_spy"}:
        with pytest.raises(DataIntegrityError):
            PortfolioSizer(mapping, mapping, registry, policy, session)
        return
    frame = PortfolioSizer(mapping, mapping, registry, policy, session)
    if case in {"missing_candidate", "auto"}:
        with pytest.raises(DataIntegrityError):
            frame.assess("NVDA", D(8), 40, book, auto=None if case == "auto" else False)  # type: ignore[arg-type]
        return
    result = frame.assess("NVDA", D(8), 40, book, auto=False)
    assert result.factors.qty == (30 if case == "correlated" else 40)
    assert frame.assess("NVDA", D(8), 40, book, auto=False) == result


@pytest.mark.parametrize(
    "action, expected", [("annotate", 40), ("half_size", 20), ("no_new_entries", 0)]
)
def test_RS_breadth_only_reduces_automatic_risk_off_entries(
    clock: FrozenClock, action: str, expected: int
) -> None:
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    base = load_yaml_config(ROOT / "config/config.yaml", allowed_symbols=registry.symbols)
    policy = YamlConfig.model_validate(
        {**base.model_dump(), "rs": {"use_breadth": True}, "regime_filter": {"auto": action}}
    )
    rows = series(0, 260)
    mapping = {name: rows for name in (*policy.watchlist, "SPY")}
    frame = PortfolioSizer(mapping, mapping, registry, policy, rows[-1][0])
    assert frame.assess("NVDA", D(8), 40, _snapshot(clock), auto=True).factors.qty == expected
    assert frame.assess("NVDA", D(8), 40, _snapshot(clock), auto=False).factors.qty == 40
