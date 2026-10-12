"""V connection boundaries: real replay samples, sizing provenance and earnings gates."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.agents.earnings_gap import evaluate_earnings_gap
from backend.agents.indicators import IndicatorSeries, MACDSeries
from backend.core.clock import FrozenClock
from backend.core.config import SizingConfig, load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.data_layer import Bar
from backend.data.earnings_reports import EarningsReport, gap_sessions, sec_reports
from backend.data.fee_schedule import load_fee_schedule
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, SizeEvidence, TradeProposal
from backend.evaluation.fixtures import offline_settings, seal_offline_fixtures
from backend.evaluation.registry import Registrations, Variant, VariantFamily, VariantRegistry
from backend.evaluation.replay import ReplayPreparation, ReplayRequest, prepare_replay, replay
from backend.evaluation.validation_runner import ReplayEvaluator, context_hash
from backend.risk.portfolio_sizing import assess_size
from backend.tests.test_replay import request
from backend.tests.test_risk_cro import _proposal, _snapshot

D = Decimal
ONE = D(1)
PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2017, 1, 1), end=date(2028, 1, 1))


@pytest.fixture(scope="module")
def registry() -> InstrumentRegistry:
    return InstrumentRegistry.from_csv(PROJECT / "config")


@pytest.fixture
def earnings(
    calendar: MarketCalendar,
) -> tuple[tuple[Bar, ...], IndicatorSeries, tuple[Bar, ...], EarningsReport]:
    sessions = (*calendar.previous_sessions(date(2026, 9, 28), 209), date(2026, 9, 28))
    flat = tuple(
        Bar(
            timestamp=calendar.session_open(day) - timedelta(hours=5, minutes=30),
            open=D(100),
            high=D(101),
            low=D(99),
            close=D(100),
            volume=1000000,
        )
        for day in sessions
    )
    tape = list(flat)
    for index, values in (
        (207, (104, 106, 103, "105.50")),
        (208, (106, 107, 104, 106)),
        (209, (107, 108, 105, 107)),
    ):
        tape[index] = Bar.model_validate(
            {
                **tape[index].model_dump(),
                **dict(
                    zip(
                        ("open", "high", "low", "close"),
                        (D(value) for value in values),
                        strict=True,
                    )
                ),
                "volume": 3000000,
            }
        )
    series = IndicatorSeries(
        ema20=(D(102),) * 210,
        ema50=(D(101),) * 210,
        ema200=(D(99),) * 210,
        rsi14=(D(60),) * 210,
        atr14=(D("2.50"),) * 210,
        rvol20=(D(3),) * 210,
        anchored_vwap=(D(101),) * 210,
        macd=MACDSeries(line=(ONE,) * 210, signal=(ONE,) * 210, histogram=(D(0),) * 210),
    )
    stamp = calendar.session_open(sessions[207]) - timedelta(hours=1)
    report = EarningsReport(
        symbol="NVDA",
        report_date=sessions[207],
        known_at=stamp,
        accepted_at=stamp,
        accession="0001045810-26-000123",
        source="SEC_8K_ITEM_202",
    )
    return tuple(tape), series, flat, report


@pytest.mark.parametrize(
    "case",
    [
        "pass",
        "gap",
        "rvol",
        "filled",
        "midpoint",
        "ema",
        "late",
        "unknown",
        "etf",
        "future",
        "wrong_issuer",
    ],
)
def test_EG_fixed_points_and_each_gate(
    calendar: MarketCalendar,
    registry: InstrumentRegistry,
    earnings: tuple[tuple[Bar, ...], IndicatorSeries, tuple[Bar, ...], EarningsReport],
    case: str,
) -> None:
    bars, series, spy, report = earnings
    values = list(bars)
    fields: dict[str, Any] = {}
    if case == "gap":
        fields["open"] = D("103.99")
    elif case == "filled":
        fields["low"] = D(100)
    if fields:
        values[207] = Bar.model_validate({**values[207].model_dump(), **fields})
    if case in {"rvol", "ema"}:
        name, index, value = (
            ("rvol20", 207, D("1.99")) if case == "rvol" else ("ema50", 209, D(108))
        )
        vals = list(series.model_dump()[name])
        vals[index] = value
        series = IndicatorSeries.model_validate({**series.model_dump(), name: tuple(vals)})
    if case == "midpoint":
        values[-1] = Bar.model_validate({**values[-1].model_dump(), "close": D(105), "low": D(104)})
        values[207] = Bar.model_validate({**values[207].model_dump(), "high": D(108)})
    if case == "late":
        stamp = calendar.session_open(bars[205].session_date) - timedelta(hours=1)
        report = EarningsReport.model_validate(
            {
                **report.model_dump(),
                "report_date": bars[205].session_date,
                "known_at": stamp,
                "accepted_at": stamp,
            }
        )
    if case == "unknown":
        report = EarningsReport.model_validate(
            {**report.model_dump(), "source": "KNOWN_CALENDAR", "accepted_at": None}
        )
    if case == "wrong_issuer":
        report = EarningsReport.model_validate({**report.model_dump(), "symbol": "AAPL"})
    asset = registry.get("NVDA")
    if case == "etf":
        asset = asset.model_copy(update={"asset_class": AssetClass.BROAD_ETF})
    instant = calendar.session_close(bars[-1].session_date) + timedelta(minutes=30)
    if case == "future":
        instant = calendar.session_open(bars[-1].session_date)
    if case in {"future", "wrong_issuer"}:
        with pytest.raises(DataIntegrityError):
            evaluate_earnings_gap(
                asset, tuple(values), series, spy, (report,), SizingConfig(), instant, calendar
            )
        return
    found = evaluate_earnings_gap(
        asset, tuple(values), series, spy, (report,), SizingConfig(), instant, calendar
    )
    if case in {"pass", "unknown"}:
        assert found is not None
        assert (found.score, found.entry, found.stop, found.target) == (
            D(9),
            D("108.01"),
            D("102.99"),
            D("118.05"),
        )
        assert found.stop > D(99)  # The pre-gap swing low must not set this stop.
    else:
        assert found is None


@pytest.mark.parametrize(
    "case",
    ["before", "after", "date_only", "future", "naive", "mismatched", "duplicate", "not_earnings"],
)
def test_EG_SEC_acceptance_is_point_in_time(calendar: MarketCalendar, case: str) -> None:
    day = date(2026, 9, 25)
    before = calendar.session_open(day) - timedelta(minutes=1)
    after = calendar.session_open(day) + timedelta(minutes=1)
    now = calendar.session_close(day) + timedelta(minutes=30)
    stamp = after if case == "after" else before
    if case == "date_only":
        report = EarningsReport(
            symbol="NVDA", report_date=day, known_at=before, source="KNOWN_CALENDAR"
        )
        assert gap_sessions(report, now, calendar) == (day, calendar.add_sessions(day, 1))
        return
    columns = {
        "form": ["8-K"],
        "items": ["2.02,9.01"],
        "acceptanceDateTime": [stamp.isoformat()],
        "accessionNumber": ["0001045810-26-000123"],
    }
    if case == "future":
        columns["acceptanceDateTime"] = [(now + timedelta(days=1)).isoformat()]
    elif case == "naive":
        columns["acceptanceDateTime"] = [stamp.replace(tzinfo=None).isoformat()]
    elif case == "mismatched":
        columns["items"] = []
    elif case == "duplicate":
        columns = {name: vals * 2 for name, vals in columns.items()}
    elif case == "not_earnings":
        columns["items"] = ["12.02"]
    if case in {"naive", "mismatched", "duplicate"}:
        with pytest.raises(DataIntegrityError):
            sec_reports("NVDA", {"filings": {"recent": columns}}, now)
        return
    rows = sec_reports("NVDA", {"filings": {"recent": columns}}, now)
    if case in {"future", "not_earnings"}:
        assert rows == ()
    else:
        assert gap_sessions(rows[0], now, calendar) == (
            calendar.add_sessions(day, 1) if case == "after" else day,
        )


def test_PR_proposal_cannot_exceed_recorded_single_product(clock: FrozenClock) -> None:
    factors = SizeEvidence(base_qty=40, regime=D("0.5"), correlation=D("0.75"))
    assert factors.qty == 15
    with pytest.raises(ValidationError, match="recorded reduction"):
        TradeProposal.model_validate(
            {**_proposal(clock).model_dump(), "qty": 16, "size_evidence": factors}
        )


@pytest.mark.parametrize("case", ["normal", "unknown", "future", "missing_spy", "confidence"])
def test_PR_connected_math_has_one_product(
    registry: InstrumentRegistry, clock: FrozenClock, case: str
) -> None:
    policy = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    if case == "confidence":
        policy = policy.model_copy(
            update={"sizing": policy.sizing.model_copy(update={"confidence_mode": "bands"})}
        )
    rows = tuple((date(2025, 1, 1) + timedelta(days=i), D(100) + D(i) / 100) for i in range(260))
    mapping = {name: rows for name in (*policy.watchlist, "SPY")}
    account = _snapshot(clock, positions={})
    if case == "unknown":
        from backend.domain.models import Position

        account = _snapshot(
            clock, positions={"MSFT": Position(qty=1, avg_cost=D(100), last_price=D(100))}
        )
        mapping.pop("MSFT", None)
    elif case == "missing_spy":
        mapping.pop("SPY")
    if case in {"future", "missing_spy"}:
        with pytest.raises(DataIntegrityError):
            assess_size(
                "NVDA",
                D(7),
                40,
                account,
                mapping,
                mapping,
                registry,
                policy,
                rows[-1][0] - timedelta(days=int(case == "future")),
                auto=False,
            )
        return
    result = assess_size(
        "NVDA", D(7), 40, account, mapping, mapping, registry, policy, rows[-1][0], auto=False
    )
    assert result.factors.qty == (20 if case == "confidence" else 30 if case == "unknown" else 40)
    assert result.regime == "RISK_ON"


def test_QV_real_replay_not_a_stub(
    engine: Engine,
    clock: FrozenClock,
    tmp_path: Path,
    calendar: MarketCalendar,
    registry: InstrumentRegistry,
) -> None:
    policy = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    seed = ReplayRequest.model_validate(
        {
            **request().model_dump(),
            "symbols": ("NVDA",),
            "start": date(2019, 1, 2),
            "end": date(2025, 12, 31),
            "synthetic": True,
        }
    )
    history, filings = seal_offline_fixtures(tmp_path, seed, calendar)
    limits = offline_settings()
    fees = load_fee_schedule(PROJECT / "config/fees.yaml")
    registered = VariantRegistry(
        families=(
            VariantFamily(
                name="EXITS",
                variants=(
                    Variant(name="BASELINE"),
                    Variant(name="SPLIT_1R", overrides={"exits.variant": "SPLIT_1R"}),
                ),
            ),
        )
    )
    proof = Registrations(Ledger(engine, clock)).register(
        registered,
        "a" * 64,
        history,
        policy.qv,
        calendar,
        context_sha256=context_hash(limits, policy, filings, fees, seed, registry),
    )
    runner = ReplayEvaluator(
        proof, seed, history, filings, limits, policy, registry, calendar, fees
    )
    with pytest.raises(ConfigurationError, match="unregistered family"):
        runner.preflight("UNKNOWN")
    runner.preflight("EXITS")
    end = calendar.add_sessions(proof.training_start, 40)
    result = runner(Variant(name="BASELINE"), proof.training_start, end)
    assert result.daily and result.history_sha256 == history.manifest.sha256
    assert runner(Variant(name="BASELINE"), proof.training_start, end) == result
    with pytest.raises(ConfigurationError, match="holdout"):
        runner(Variant(name="BASELINE"), proof.holdout_start, proof.holdout_end)
    with pytest.raises(ConfigurationError, match="unregistered"):
        runner(
            Variant(name="TIME_10", overrides={"evaluation.max_hold_sessions": 10}),
            proof.training_start,
            end,
        )
    changed = limits.model_copy(update={"max_open_positions": 1})
    with pytest.raises(ConfigurationError, match="frozen run inputs"):
        ReplayEvaluator(proof, seed, history, filings, changed, policy, registry, calendar, fees)
    prepared = prepare_replay(seed.symbols, end, history, filings, policy, registry)
    small = ReplayRequest.model_validate(
        {**seed.model_dump(), "start": proof.training_start, "end": end}
    )
    plain = replay(small, history, filings, limits, policy, registry, calendar, fees)
    reused = replay(
        small, history, filings, limits, policy, registry, calendar, fees, preparation=prepared
    )
    assert plain.sha256 == reused.sha256
    bad = prepared.model_copy(update={"config_sha256": "0" * 64})
    with pytest.raises(ValidationError):
        ReplayPreparation.model_validate(bad)


@pytest.mark.parametrize(
    "action, auto, breadth, expected",
    [
        ("half_size", True, True, D("0.5")),
        ("no_new_entries", True, True, D(0)),
        ("annotate", True, True, ONE),
        ("half_size", False, True, ONE),
        ("half_size", True, False, ONE),
    ],
)
def test_RS_breadth_risk_off_at_equal_spy_ema(
    registry: InstrumentRegistry,
    clock: FrozenClock,
    action: str,
    auto: bool,
    breadth: bool,
    expected: Decimal,
) -> None:
    raw = load_yaml_config(
        PROJECT / "config/config.yaml", allowed_symbols=registry.symbols
    ).model_dump()
    raw["rs"]["use_breadth"] = breadth
    raw["regime_filter"]["auto"] = action
    from backend.core.config import YamlConfig

    policy = YamlConfig.model_validate(raw)
    rows = tuple((date(2025, 1, 1) + timedelta(days=i), D(100)) for i in range(260))
    mapping = {name: rows for name in (*policy.watchlist, "SPY")}
    result = assess_size(
        "NVDA",
        D(7),
        40,
        _snapshot(clock, positions={}),
        mapping,
        mapping,
        registry,
        policy,
        rows[-1][0],
        auto=auto,
    )
    assert result.regime == "RISK_OFF" and result.factors.regime == expected


def test_PR_volatility_factor_rounds_down(
    registry: InstrumentRegistry,
    clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.risk import portfolio_sizing

    policy = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    rows = tuple((date(2025, 1, 1) + timedelta(days=i), D(100)) for i in range(260))
    mapping = {name: rows for name in (*policy.watchlist, "SPY")}
    monkeypatch.setattr(portfolio_sizing, "volatility", lambda *_: (D(".24"), D(".16")))
    result = assess_size(
        "NVDA",
        D(7),
        40,
        _snapshot(clock, positions={}),
        mapping,
        mapping,
        registry,
        policy,
        rows[-1][0],
        auto=False,
    )
    assert result.factors.volatility == D(".666666")


def test_PF_market_memo_detaches_inputs_and_keeps_portfolio_and_factors_fresh(
    registry: InstrumentRegistry,
    clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.domain.models import Position
    from backend.risk import portfolio_sizing

    policy = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    policy = policy.model_copy(
        update={"sizing": policy.sizing.model_copy(update={"confidence_mode": "bands"})}
    )
    rows = tuple((date(2025, 1, 1) + timedelta(days=i), D(100) + D(i) / 100) for i in range(260))
    mapping = {name: rows for name in (*policy.watchlist, "SPY")}
    calls = []
    from backend.indicators.portfolio import volatility as original

    def counted(*args: Any) -> tuple[Decimal, Decimal]:
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(portfolio_sizing, "volatility", counted)
    memo = portfolio_sizing.PortfolioSizer(mapping, mapping, registry, policy, rows[-1][0])
    account = _snapshot(clock, positions={})
    baseline = memo.assess("NVDA", D(9), 40, account, auto=False)
    assert baseline == assess_size(
        "NVDA", D(9), 40, account, mapping, mapping, registry, policy, rows[-1][0], auto=False
    )
    assert len(calls) == 2
    mapping.clear()
    assert memo.assess("NVDA", D(9), 40, account, auto=False) == baseline
    assert memo.assess("NVDA", D(7), 40, account, auto=False).factors.qty == 20
    assert memo.assess("NVDA", D(9), 40, account, auto=False, ramp=D(".5")).factors.qty == 20
    assert memo.assess("NVDA", D(9), 40, account, auto=False, events=D(".5")).factors.qty == 20
    changed = _snapshot(
        clock, positions={"MSFT": Position(qty=1, avg_cost=D(100), last_price=D(100))}
    )
    assert memo.assess("NVDA", D(9), 40, changed, auto=False).factors.qty == 30
    assert len(calls) == 2
