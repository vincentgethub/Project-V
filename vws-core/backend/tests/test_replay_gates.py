"""PF-03: full-prefix reference parity, future poison and native split basis."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.agents.anchors import select_anchor
from backend.agents.indicators import IndicatorMemo
from backend.agents.setup_hunter import SetupHunter, evaluate_playbook
from backend.core.clock import FrozenClock
from backend.core.config import Settings, YamlConfig
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.history import HistorySeries, KnownSplit
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import MarketContext, MarketStatus, Playbook
from backend.indicators.replay import precompute_symbol
from backend.risk.risk_cro import ChiefRiskOfficer
from backend.tests import test_setup_hunter as golden
from backend.tests.test_risk_cro import _snapshot

calendar = golden.calendar
policy = golden.policy
bars = golden.bars
D = Decimal


def test_PF_03_precomputed_grades_equal_full_reference_prefixes(
    bars: tuple[Bar, ...], policy: YamlConfig
) -> None:  # noqa: F811
    raw = HistorySeries(symbol="AAPL", adjustment="RAW", bars=bars)
    result = precompute_symbol(raw, (), policy, "a" * 64)
    assert all(day.evidence == (None, None, None) for day in result.days[:199])
    for i in range(199, len(bars)):
        prefix = bars[: i + 1]
        values = IndicatorMemo().calculate("AAPL", prefix, select_anchor(prefix)[0])
        expected = tuple(
            evaluate_playbook(Playbook(name), prefix, values, weights, policy.sizing)
            for name, weights in policy.playbooks.items()
        )
        assert result.days[i].evidence == expected
        assert result.days[i].atr14 == values.atr14[-1]
    assert result.days[-1].adv20 == sum((bar.close * bar.volume for bar in bars[-20:]), D(0)) / 20


def test_PF_03_future_prices_and_future_splits_cannot_poison_earlier_gates(
    bars: tuple[Bar, ...], policy: YamlConfig, calendar: MarketCalendar
) -> None:  # noqa: F811
    original = precompute_symbol(
        HistorySeries(symbol="AAPL", adjustment="RAW", bars=bars), (), policy, "a" * 64
    )
    following = calendar.add_sessions(bars[-1].session_date, 1)
    future = Bar(
        timestamp=calendar.session_open(following) - timedelta(hours=5, minutes=30),
        open=D(500),
        high=D(900),
        low=D(5),
        close=D(800),
        volume=5000000,
    )
    poisoned = precompute_symbol(
        HistorySeries(symbol="AAPL", adjustment="RAW", bars=(*bars, future)),
        (KnownSplit(symbol="AAPL", effective_session=following, new_shares_per_old=D(2)),),
        policy,
        "b" * 64,
    )
    assert poisoned.days[:-1] == original.days


def test_PF_03_native_split_gate_quantization_uses_the_day_basis(
    bars: tuple[Bar, ...], policy: YamlConfig
) -> None:  # noqa: F811
    # All these prices are divisible by two in cents: no silent rounding needed.
    index = 205
    raw = (
        *bars[:index],
        *(
            Bar(
                timestamp=bar.timestamp,
                open=bar.open / 2,
                high=bar.high / 2,
                low=bar.low / 2,
                close=bar.close / 2,
                volume=bar.volume * 2,
            )
            for bar in bars[index:]
        ),
    )
    action = KnownSplit(
        symbol="AAPL", effective_session=bars[index].session_date, new_shares_per_old=D(2)
    )
    result = precompute_symbol(
        HistorySeries(symbol="AAPL", adjustment="RAW", bars=raw), (action,), policy, "a" * 64
    )
    for i in range(index, len(raw)):
        adjusted = tuple(
            Bar(
                timestamp=bar.timestamp,
                open=bar.open / 2,
                high=bar.high / 2,
                low=bar.low / 2,
                close=bar.close / 2,
                volume=bar.volume * 2,
            )
            for bar in bars[: i + 1]
        )
        series = IndicatorMemo().calculate("AAPL", adjusted, select_anchor(adjusted)[0])
        assert result.days[i].evidence == tuple(
            evaluate_playbook(Playbook(name), adjusted, series, weights, policy.sizing)
            for name, weights in policy.playbooks.items()
        )


def test_PF_03_precomputed_sizing_retains_cro_caps_and_boundary_checks(
    bars: tuple[Bar, ...], policy: YamlConfig, calendar: MarketCalendar
) -> None:  # noqa: F811
    project = Path(__file__).resolve().parents[2]
    registry = InstrumentRegistry.from_csv(project / "config")
    cro = ChiefRiskOfficer(Settings(), registry, calendar)
    hunter = SetupHunter(cro, policy, IndicatorMemo())
    now = calendar.session_close(bars[-1].session_date) + timedelta(minutes=30)
    market = MarketContext(
        last_price=bars[-1].close, last_price_ts=now, adv20_usd=D(100000000), status=MarketStatus.OK
    )
    snapshot = _snapshot(FrozenClock(now), as_of=now)
    precomputed = precompute_symbol(
        HistorySeries(symbol="AAPL", adjustment="RAW", bars=bars), (), policy, "a" * 64
    )
    assert hunter.hunt("AAPL", bars, snapshot, market, now) == hunter.size_evidence(
        "AAPL", precomputed.days[-1].evidence, snapshot, market, now
    )
    with pytest.raises(DataIntegrityError):
        hunter.size_evidence("AAPL", (), snapshot, market, now)
    with pytest.raises(DataIntegrityError):
        precompute_symbol(
            HistorySeries(symbol="AAPL", adjustment="ALL", bars=bars), (), policy, "a" * 64
        )


def test_PF_03_subcent_split_gate_is_explicitly_unavailable(
    bars: tuple[Bar, ...], policy: YamlConfig
) -> None:  # noqa: F811
    raw = (
        *bars[:-1],
        bars[-1].model_copy(
            update={
                "open": D("35.33"),
                "high": D(37),
                "low": D(35),
                "close": D("36.67"),
                "volume": 600,
            }
        ),
    )
    action = KnownSplit(
        symbol="AAPL", effective_session=raw[-1].session_date, new_shares_per_old=D(3)
    )
    result = precompute_symbol(
        HistorySeries(symbol="AAPL", adjustment="RAW", bars=raw), (action,), policy, "a" * 64
    )
    assert result.days[-1].evidence == (None, None, None) and "subcents" in result.days[-1].reason
