"""GD-03: independent playbook goldens, strict gates and CRO-capped sizing."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.agents.anchors import AnchorKind, select_anchor
from backend.agents.indicators import IndicatorMemo, IndicatorSeries, MACDSeries
from backend.agents.setup_hunter import (
    PlaybookEvidence,
    SetupHunter,
    evaluate_playbook,
    score_eligible,
)
from backend.core.clock import FrozenClock
from backend.core.config import PlaybookConfig, Settings, SizingConfig, YamlConfig, load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import MarketStatus, Playbook
from backend.risk.risk_cro import ChiefRiskOfficer
from backend.tests.test_risk_cro import _market, _registry, _snapshot

PROJECT = Path(__file__).resolve().parents[2]
DAILY = (Playbook.TREND_50EMA, Playbook.BASE_BREAKOUT, Playbook.ANCHORED_VWAP_RECLAIM)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 1), end=date(2027, 12, 31))


@pytest.fixture
def policy() -> YamlConfig:
    return load_yaml_config(
        PROJECT / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(PROJECT / "config").symbols,
    )


@pytest.fixture
def bars(calendar: MarketCalendar) -> tuple[Bar, ...]:
    days = (*calendar.previous_sessions(date(2026, 9, 28), 209), date(2026, 9, 28))
    return tuple(
        Bar(
            timestamp=calendar.session_open(day) - timedelta(hours=5, minutes=30),
            open=Decimal(106),
            high=Decimal(111 if i == 209 else 108),
            low=Decimal(105 if i >= 200 else 100),
            close=Decimal(110 if i == 209 else 107 if i == 208 else 106),
            volume=200 if i == 209 else 100,
        )
        for i, day in enumerate(days)
    )


@pytest.fixture
def series() -> IndicatorSeries:
    """Indicator output fixture. The point table is hand-evaluated below.

    Reference-indicator arithmetic is independently covered in test_indicators;
    these isolated fixtures let every playbook hard gate be changed alone.
    """
    return IndicatorSeries(
        ema20=(Decimal(108),) * 210,
        ema50=(Decimal(103),) * 200 + (Decimal(106),) * 10,
        ema200=(Decimal(90),) * 210,
        rsi14=(Decimal(60),) * 210,
        atr14=(Decimal(4),) * 210,
        rvol20=(Decimal(2),) * 210,
        anchored_vwap=(Decimal(108),) * 209 + (Decimal(109),),
        macd=MACDSeries(
            line=(Decimal(1),) * 210,
            signal=(Decimal("0.5"),) * 210,
            histogram=(Decimal("0.5"),) * 210,
        ),
    )


def change_series(
    series: IndicatorSeries, key: str, value: Decimal | None, index: int = -1
) -> IndicatorSeries:
    vals = list(series.model_dump()[key])
    vals[index] = value
    return IndicatorSeries.model_validate({**series.model_dump(), key: tuple(vals)})


@pytest.mark.parametrize("playbook", DAILY)
def test_GD_03_each_playbook_golden_max_score_and_exact_levels(
    playbook: Playbook, bars: tuple[Bar, ...], series: IndicatorSeries, policy: YamlConfig
) -> None:
    result = evaluate_playbook(playbook, bars, series, policy.playbooks[playbook], policy.sizing)
    assert result is not None
    # entry111+.01=111.01; min(111.01-2*4,105-.01)=103.01; 2R target127.01.
    assert (result.entry, result.stop, result.target) == (
        Decimal("111.01"),
        Decimal("103.01"),
        Decimal("127.01"),
    )
    assert result.score == 10 and sum(item.points for item in result.criteria) == 10
    assert [item.points for item in result.criteria] == (
        [Decimal(2), Decimal(2), Decimal(2), Decimal("1.5"), Decimal(1), Decimal("1.5")]
        if playbook == Playbook.TREND_50EMA
        else [Decimal(2), Decimal(2), Decimal(2), Decimal(2), Decimal(1), Decimal(1)]
    )
    assert (
        evaluate_playbook(playbook, bars, series, policy.playbooks[playbook], policy.sizing)
        == result
    )
    with localcontext() as context:
        context.prec = 2
        assert (
            evaluate_playbook(playbook, bars, series, policy.playbooks[playbook], policy.sizing)
            == result
        )


@pytest.mark.parametrize(
    "gate", ["above200", "rising50", "touch50", "reclaim50", "above_prior_high"]
)
def test_GD_03_trend_one_failure_per_hard_gate(
    gate: str, bars: tuple[Bar, ...], series: IndicatorSeries, policy: YamlConfig
) -> None:
    if gate == "above200":
        series = change_series(series, "ema200", Decimal(110))
    elif gate == "rising50":
        series = change_series(series, "ema50", Decimal(106), -11)
    elif gate == "touch50":
        bars = (
            *bars[:-5],
            *(
                bar.model_copy(
                    update={
                        "low": Decimal(108),
                        "open": Decimal(108),
                        "close": max(bar.close, Decimal(108)),
                    }
                )
                for bar in bars[-5:]
            ),
        )
    elif gate == "reclaim50":
        series = change_series(series, "ema50", Decimal(110))
    else:
        bars = (*bars[:-2], bars[-2].model_copy(update={"high": Decimal(110)}), bars[-1])
    assert (
        evaluate_playbook(
            Playbook.TREND_50EMA,
            bars,
            series,
            policy.playbooks[Playbook.TREND_50EMA],
            policy.sizing,
        )
        is None
    )


@pytest.mark.parametrize("gate", ["breakout", "rvol", "base_range"])
def test_GD_03_base_one_failure_per_hard_gate(
    gate: str, bars: tuple[Bar, ...], series: IndicatorSeries, policy: YamlConfig
) -> None:
    if gate == "breakout":
        bars = (*bars[:-2], bars[-2].model_copy(update={"high": Decimal(110)}), bars[-1])
    elif gate == "rvol":
        series = change_series(series, "rvol20", Decimal("1.499999"))
    else:
        bars = (*bars[:-21], bars[-21].model_copy(update={"low": Decimal(90)}), *bars[-20:])
    assert (
        evaluate_playbook(
            Playbook.BASE_BREAKOUT,
            bars,
            series,
            policy.playbooks[Playbook.BASE_BREAKOUT],
            policy.sizing,
        )
        is None
    )


@pytest.mark.parametrize("gate", ["prior_below", "now_above", "rvol"])
def test_GD_03_reclaim_one_failure_per_hard_gate(
    gate: str, bars: tuple[Bar, ...], series: IndicatorSeries, policy: YamlConfig
) -> None:
    if gate == "prior_below":
        series = change_series(series, "anchored_vwap", Decimal(107), -2)
    elif gate == "now_above":
        series = change_series(series, "anchored_vwap", Decimal(110))
    else:
        series = change_series(series, "rvol20", Decimal("1.199999"))
    assert (
        evaluate_playbook(
            Playbook.ANCHORED_VWAP_RECLAIM,
            bars,
            series,
            policy.playbooks[Playbook.ANCHORED_VWAP_RECLAIM],
            policy.sizing,
        )
        is None
    )


@pytest.mark.parametrize(
    "playbook,field,value,name,expected",
    [
        (Playbook.TREND_50EMA, "ema50", "104.03", "slope", "1"),  # slope1.0% exactly vs old103
        (Playbook.TREND_50EMA, "rsi14", "45", "rsi", "1.5"),
        (Playbook.TREND_50EMA, "rsi14", "65", "rsi", "1.5"),
        (Playbook.TREND_50EMA, "rsi14", "65.000001", "rsi", "0"),
        (Playbook.TREND_50EMA, "rvol20", "1.2", "relative_volume", "1"),
        (Playbook.TREND_50EMA, "rvol20", "1.199999", "relative_volume", "0"),
        (Playbook.BASE_BREAKOUT, "rvol20", "1.5", "relative_volume", "1"),
        (Playbook.BASE_BREAKOUT, "rvol20", "2", "relative_volume", "2"),
        (Playbook.ANCHORED_VWAP_RECLAIM, "rvol20", "1.2", "relative_volume", "1"),
        (Playbook.ANCHORED_VWAP_RECLAIM, "rvol20", "1.5", "relative_volume", "2"),
    ],
)
def test_GD_03_criterion_boundaries(
    playbook: Playbook,
    field: str,
    value: str,
    name: str,
    expected: str,
    bars: tuple[Bar, ...],
    series: IndicatorSeries,
    policy: YamlConfig,
) -> None:
    if field == "ema50":
        # Retain the touch hard gate with low104.0 inside1% of EMA104.03.
        bars = (*bars[:-5], *(bar.model_copy(update={"low": Decimal(104)}) for bar in bars[-5:]))
    result = evaluate_playbook(
        playbook,
        bars,
        change_series(series, field, Decimal(value)),
        policy.playbooks[playbook],
        policy.sizing,
    )
    assert result is not None
    assert next(item.points for item in result.criteria if item.name == name) == Decimal(expected)


@pytest.mark.parametrize("score,allowed", [("7.0", True), ("6.99", False), ("7.01", True)])
def test_GD_03_minimum_score_boundary_never_rounds_up(score: str, allowed: bool) -> None:
    assert score_eligible(Decimal(score), Decimal(7)) == allowed


def test_GD_03_stop_uses_lower_structure_and_discards_overwide_risk(
    bars: tuple[Bar, ...], series: IndicatorSeries, policy: YamlConfig
) -> None:
    changed = (*bars[:-10], bars[-10].model_copy(update={"low": Decimal(100)}), *bars[-9:])
    result = evaluate_playbook(
        Playbook.BASE_BREAKOUT,
        changed,
        series,
        policy.playbooks[Playbook.BASE_BREAKOUT],
        policy.sizing,
    )
    assert result is not None and result.stop == Decimal("99.99")
    changed = (*bars[:-10], bars[-10].model_copy(update={"low": Decimal(95)}), *bars[-9:])
    assert (
        evaluate_playbook(
            Playbook.BASE_BREAKOUT,
            changed,
            series,
            policy.playbooks[Playbook.BASE_BREAKOUT],
            policy.sizing,
        )
        is None
    )


def test_GD_03_no_lookahead_both_anchor_types_and_ties(bars: tuple[Bar, ...]) -> None:
    anchor, kind = select_anchor(bars)
    assert kind == AnchorKind.LOWEST_LOW and anchor == 199  # most recent tied100 low
    gap = bars[205].model_copy(
        update={"open": Decimal("111.30"), "high": Decimal(112), "volume": 200}
    )  # prior106 ->5%
    changed = (*bars[:205], gap, *bars[206:])
    assert select_anchor(changed) == (205, AnchorKind.GAP)
    # A later low supersedes the gap; future rows cannot affect a prefix call.
    later = bars[-1].model_copy(update={"low": Decimal(99)})
    assert select_anchor((*changed[:-1], later)) == (209, AnchorKind.LOWEST_LOW)
    assert select_anchor(changed[:-5]) == select_anchor(bars[:-5])
    with pytest.raises(DataIntegrityError):
        select_anchor(bars[-59:])


def hunter(policy: YamlConfig, calendar: MarketCalendar) -> SetupHunter:
    # The test's reduced watchlist uses only its known registry. No credentials.
    config = YamlConfig.model_validate({**policy.nonsecret_snapshot(), "watchlist": ["AAPL"]})
    cro = ChiefRiskOfficer(Settings(), _registry(), calendar)
    return SetupHunter(cro, config, IndicatorMemo())


def test_GD_03_hunter_matches_risk_budget_and_CRO_cap(
    policy: YamlConfig,
    calendar: MarketCalendar,
    bars: tuple[Bar, ...],
    series: IndicatorSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = hunter(policy, calendar)
    monkeypatch.setattr(worker.memo, "calculate", lambda *args: series)
    clock = FrozenClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    market = _market(clock, last_price=Decimal(110))
    result = worker.hunt("AAPL", bars, _snapshot(clock), market, clock.now())
    assert len(result.candidates) == 3
    # floor(.005*10000 / (8 +111.01*.002)) =6; each exact CRO max retains6.
    assert all(candidate.qty == 6 for candidate in result.candidates)
    assert result == worker.hunt("AAPL", bars, _snapshot(clock), market, clock.now())
    constrained = _snapshot(clock, cash=Decimal(120), settled_cash=Decimal(120))
    # Retaining the required cash buffer makes CRO reduce affordable qty to zero.
    result = worker.hunt("AAPL", bars, constrained, market, clock.now())
    assert not result.candidates and all("quantity zero" in item.reason for item in result.drops)


def test_GD_03_zero_size_suspect_low_score_and_malformed_inputs(
    policy: YamlConfig,
    calendar: MarketCalendar,
    bars: tuple[Bar, ...],
    series: IndicatorSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = hunter(policy, calendar)
    monkeypatch.setattr(worker.memo, "calculate", lambda *args: series)
    clock = FrozenClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    tiny = _snapshot(
        clock,
        equity=Decimal(1),
        cash=Decimal(1),
        settled_cash=Decimal(1),
        high_water_mark=Decimal(1),
        day_start_equity=Decimal(1),
    )
    assert not worker.hunt("AAPL", bars, tiny, _market(clock), clock.now()).candidates
    assert not worker.hunt(
        "AAPL", bars, _snapshot(clock), _market(clock, status=MarketStatus.SUSPECT), clock.now()
    ).candidates
    with pytest.raises(DataIntegrityError):
        worker.hunt("MSFT", bars, _snapshot(clock), _market(clock), clock.now())
    with pytest.raises(DataIntegrityError):
        worker.hunt(
            "AAPL", bars, _snapshot(clock), _market(clock), clock.now().replace(tzinfo=None)
        )
    with pytest.raises(ConfigurationError):
        SetupHunter(None, policy, IndicatorMemo())  # type: ignore[arg-type]
    for bad in (Decimal("NaN"), Decimal(11)):
        with pytest.raises(DataIntegrityError):
            score_eligible(bad, Decimal(7))


def test_GD_03_evidence_contract_and_undefined_series_fail_closed(
    bars: tuple[Bar, ...], series: IndicatorSeries, policy: YamlConfig
) -> None:
    playbook = Playbook.BASE_BREAKOUT
    result = evaluate_playbook(playbook, bars, series, policy.playbooks[playbook], policy.sizing)
    assert result is not None
    for update in ({"score": Decimal(9)}, {"target": Decimal(112)}, {"stop": Decimal(112)}):
        with pytest.raises(ValidationError):
            PlaybookEvidence.model_validate(result.model_copy(update=update))
    assert (
        evaluate_playbook(
            playbook,
            bars,
            change_series(series, "atr14", None),
            policy.playbooks[playbook],
            policy.sizing,
        )
        is None
    )
    with pytest.raises(DataIntegrityError):
        evaluate_playbook(playbook, bars[:-1], series, policy.playbooks[playbook], policy.sizing)
    bad = copy_policy(policy)
    bad["playbooks"][playbook]["criteria_weights"] = {"unknown": "1"}
    with pytest.raises(ConfigurationError):
        evaluate_playbook(
            playbook,
            bars,
            series,
            PlaybookConfig.model_validate(bad["playbooks"][playbook]),
            SizingConfig(),
        )
    with pytest.raises(ValidationError):
        YamlConfig.model_validate(bad)


def copy_policy(policy: YamlConfig) -> dict[str, Any]:
    return policy.nonsecret_snapshot()
