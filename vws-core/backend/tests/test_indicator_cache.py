"""DAT-05: reuse immutable indicator evidence once per symbol/session."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from backend.agents import indicators
from backend.agents.indicators import IndicatorMemo
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar


def _bars(count: int = 210) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=1000 + index,
        )
        for index in range(count)
    )


def test_DAT_05_indicators_compute_once_per_symbol_session(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = indicators.macd

    def observed(
        prices: tuple[Decimal, ...], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> indicators.MACDSeries:
        nonlocal calls
        calls += 1
        return original(prices, fast, slow, signal)

    monkeypatch.setattr(indicators, "macd", observed)
    memo = IndicatorMemo()
    bars = _bars()
    first = memo.calculate("AAPL", bars, 0)
    assert memo.calculate("AAPL", bars, 0) == first and calls == 1
    memo.calculate("MSFT", bars, 0)
    memo.calculate("AAPL", _bars(211), 0)
    assert calls == 3


def test_DAT_05_changed_same_session_history_or_anchor_is_refused() -> None:
    memo = IndicatorMemo()
    bars = _bars()
    memo.calculate("AAPL", bars, 0)
    with pytest.raises(DataIntegrityError):
        memo.calculate("AAPL", bars, 1)
    changed = (bars[0].model_copy(update={"volume": 9999}), *bars[1:])
    with pytest.raises(DataIntegrityError):
        memo.calculate("AAPL", changed, 0)


def test_DAT_05_memo_revalidates_forged_cached_output_and_invalid_identity() -> None:
    bars = _bars()
    memo = IndicatorMemo()
    result = memo.calculate("AAPL", bars, 0)
    key = ("AAPL", "SPLIT", bars[-1].session_date)
    digest, anchor, _ = memo._entries[key]
    memo._entries[key] = (digest, anchor, result.model_copy(update={"rsi14": (Decimal(101),)}))
    with pytest.raises(DataIntegrityError):
        memo.calculate("AAPL", bars, 0)
    with pytest.raises(DataIntegrityError):
        memo.calculate("aapl", bars, 0)
