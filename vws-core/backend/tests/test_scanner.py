"""R-02/R-03/R-11/R-13/DAT-01..03/GD-03: pure completed-daily scanner safety."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any

import pytest
from pydantic import ValidationError

from backend.agents import indicators, scanner
from backend.core.errors import DataIntegrityError, StaleDataError
from backend.data.data_layer import Bar
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import MarketStatus, ProviderStatus


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2027, 12, 31))


@pytest.fixture
def bars(calendar: MarketCalendar) -> tuple[Bar, ...]:
    sessions = (*calendar.previous_sessions(date(2026, 9, 28), 199), date(2026, 9, 28))
    result: list[Bar] = []
    for index, session in enumerate(sessions):
        price = Decimal(100) + Decimal(index) / 10
        if index == 199:
            price += 5
        low = price - (5 if index == 190 else 1)
        result.append(
            Bar(
                timestamp=calendar.session_open(session) - timedelta(hours=5, minutes=30),
                open=price,
                high=price + 1,
                low=low,
                close=price,
                volume=150 if index == 199 else 100,
            )
        )
    return tuple(result)


def _scan(bars: tuple[Bar, ...], calendar: MarketCalendar, **kwargs: Any) -> scanner.ScannerResult:
    arguments: dict[str, Any] = {
        "now": datetime(2026, 9, 29, 15, tzinfo=UTC),
        "calendar": calendar,
        "data_snapshot_hash": "a" * 64,
        "market_status": MarketStatus.OK,
    }
    arguments.update(kwargs)
    return scanner.scan("NVDA", bars, **arguments)


def test_gd03_scanner_deterministic_anomalous_rvol_positive_momentum(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    result = _scan(bars, calendar)
    assert result == _scan(bars, calendar)
    assert result.status == ProviderStatus.OK
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.rvol == Decimal("1.500000")
    assert hit.rsi == Decimal("100.000000")
    assert hit.last_price == Decimal("124.90")
    assert result.indicators is not None
    assert result.indicators.anchor_kind == scanner.AnchorKind.SWING_LOW
    assert result.indicators.anchor_session == bars[190].session_date
    assert result.indicators.ema200 == Decimal("109.98")
    for value in (
        result.indicators.ema20,
        result.indicators.ema50,
        result.indicators.ema200,
        result.indicators.atr14,
        result.indicators.macd_line,
        result.indicators.macd_signal,
        result.indicators.macd_histogram,
        result.indicators.anchored_vwap,
    ):
        assert value.as_tuple().exponent == -2
    payload = json.dumps(
        [bar.model_dump(mode="json") for bar in bars], sort_keys=True, separators=(",", ":")
    )
    assert result.completed_bars_hash == hashlib.sha256(payload.encode()).hexdigest()
    assert result.data_snapshot_hash == "a" * 64
    with pytest.raises(ValidationError):
        result.reason = "tampered"


@pytest.mark.parametrize("volume,expected", [(149, 0), (150, 1), (151, 1)])
def test_gd03_rvol_threshold_exact_boundary_and_one_share(
    bars: tuple[Bar, ...], calendar: MarketCalendar, volume: int, expected: int
) -> None:
    changed = (*bars[:-1], bars[-1].model_copy(update={"volume": volume}))
    assert len(_scan(changed, calendar).hits) == expected


def test_gd03_momentum_must_be_positive_after_cent_quantization(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    flat = tuple(
        bar.model_copy(
            update={
                "close": Decimal(100),
                "open": Decimal(100),
                "high": Decimal(101),
                "low": Decimal(95) if index == 190 else Decimal(99),
            }
        )
        for index, bar in enumerate(bars)
    )
    result = _scan(flat, calendar)
    assert result.status == ProviderStatus.UNAVAILABLE
    assert "undefined" in result.reason
    assert result.hits == ()
    # A steady linear sequence has defined RSI and a zero MACD histogram.
    linear = (
        *bars[:-1],
        bars[-1].model_copy(
            update={
                "open": Decimal("119.90"),
                "high": Decimal("120.90"),
                "low": Decimal("118.90"),
                "close": Decimal("119.90"),
            }
        ),
    )
    result = _scan(linear, calendar)
    assert result.status == ProviderStatus.OK
    assert result.hits == ()
    assert result.indicators is not None
    assert result.indicators.macd_histogram == 0


def test_gd03_scanner_earnings_gap_anchor_is_attested_and_exact_fraction_boundary(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    index = 150
    price = (bars[index - 1].close * Decimal("1.05")).quantize(Decimal("0.01"))
    # Prior close=114.90 and 5% produces120.645; ROUND_HALF_EVEN120.64 is below5%.
    # Use120.65, first cent strictly above the exact fractional threshold.
    price += Decimal("0.01")
    gap = bars[index].model_copy(update={"open": price, "high": price + 1})
    changed = (*bars[:index], gap, *bars[index + 1 :])
    result = _scan(changed, calendar, earnings_gap=gap.session_date)
    assert result.indicators is not None
    assert result.indicators.anchor_kind == scanner.AnchorKind.EARNINGS_GAP
    assert result.indicators.anchor_session == gap.session_date
    # Scanner gap arithmetic does not inherit a caller's Decimal precision.
    with localcontext() as context:
        context.prec = 2
        assert _scan(changed, calendar, earnings_gap=gap.session_date) == result
    prior = bars[index - 1].model_copy(
        update={
            "close": Decimal(100),
            "open": Decimal(100),
            "high": Decimal(101),
            "low": Decimal(99),
        }
    )
    exact = gap.model_copy(update={"open": Decimal(105), "high": Decimal(116), "low": Decimal(104)})
    changed = (*bars[: index - 1], prior, exact, *bars[index + 1 :])
    assert _scan(changed, calendar, earnings_gap=exact.session_date).indicators is not None
    for value in (bars[0].session_date, date(2027, 1, 4), datetime(2026, 9, 28, tzinfo=UTC)):
        with pytest.raises(DataIntegrityError):
            _scan(bars, calendar, earnings_gap=value)
    with pytest.raises(DataIntegrityError, match="lacks the configured gap"):
        _scan(bars, calendar, earnings_gap=bars[150].session_date)


def test_gd03_anchor_needs_confirmed_swing_and_never_uses_future_right_bars(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    ascending = tuple(bar.model_copy(update={"low": bar.close - 1}) for bar in bars)
    assert _scan(ascending, calendar).status == ProviderStatus.UNAVAILABLE
    assert "anchor" in _scan(ascending, calendar).reason
    # Last observation cannot be a confirmed two-right-bars swing low.
    changed = (*ascending[:-1], ascending[-1].model_copy(update={"low": Decimal(1)}))
    assert _scan(changed, calendar).status == ProviderStatus.UNAVAILABLE
    assert _scan(bars[-199:], calendar).status == ProviderStatus.UNAVAILABLE
    assert "warmup" in _scan(bars[-199:], calendar).reason


def test_dat02_suspect_and_undefined_volume_have_no_hits_or_facts(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    result = _scan(bars, calendar, market_status=MarketStatus.SUSPECT)
    assert result.status == ProviderStatus.UNAVAILABLE
    assert result.hits == ()
    assert result.indicators is None
    zero = tuple(bar.model_copy(update={"volume": 0}) for bar in bars)
    assert _scan(zero, calendar).status == ProviderStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "now", [datetime(2026, 9, 29, 20, tzinfo=UTC), datetime(2026, 9, 29, 20, 14, 59, tzinfo=UTC)]
)
def test_dat01_daily_sip_grace_allows_prior_completed_tail(
    bars: tuple[Bar, ...], calendar: MarketCalendar, now: datetime
) -> None:
    assert _scan(bars, calendar, now=now).status == ProviderStatus.OK


def test_dat01_daily_sip_grace_exact_end_requires_latest_session(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    with pytest.raises(StaleDataError):
        _scan(bars, calendar, now=datetime(2026, 9, 29, 20, 15, tzinfo=UTC))
    with pytest.raises(StaleDataError):
        _scan(bars[:-1], calendar)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 25, 23, tzinfo=UTC),
        datetime(2026, 9, 26, 15, tzinfo=UTC),
        datetime(2026, 9, 27, 15, tzinfo=UTC),
        datetime(2026, 11, 26, 15, tzinfo=UTC),
        datetime(2026, 3, 8, 15, tzinfo=UTC),
    ],
)
def test_dat01_night_weekend_holiday_dst_uses_last_completed_session(
    bars: tuple[Bar, ...], calendar: MarketCalendar, now: datetime
) -> None:
    final = calendar.last_completed_session(now)
    sessions = (*calendar.previous_sessions(final, 199), final)
    shifted = tuple(
        bar.model_copy(
            update={"timestamp": calendar.session_open(day) - timedelta(hours=5, minutes=30)}
        )
        for bar, day in zip(bars, sessions, strict=True)
    )
    assert _scan(shifted, calendar, now=now).status == ProviderStatus.OK


def test_dat03_future_in_progress_and_missing_sessions_are_rejected(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    current = bars[-1].model_copy(update={"timestamp": datetime(2026, 9, 29, 4, tzinfo=UTC)})
    with pytest.raises(DataIntegrityError, match="in-progress"):
        _scan((*bars, current), calendar)
    future = bars[-1].model_copy(update={"timestamp": datetime(2026, 9, 30, 4, tzinfo=UTC)})
    with pytest.raises(DataIntegrityError, match="future"):
        _scan((*bars, future), calendar)
    with pytest.raises(DataIntegrityError, match="missing or duplicated"):
        _scan((*bars[:100], *bars[101:]), calendar)
    duplicate = bars[-1].model_copy(update={"timestamp": bars[-1].timestamp + timedelta(hours=1)})
    with pytest.raises(DataIntegrityError, match="missing or duplicated"):
        _scan((*bars, duplicate), calendar)
    weekend = bars[-1].model_copy(update={"timestamp": datetime(2026, 9, 27, 4, tzinfo=UTC)})
    with pytest.raises(DataIntegrityError, match="not an exchange session"):
        _scan((*bars[:-1], weekend), calendar)


@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, None, 1])
def test_dat03_raw_provenance_hash_must_be_explicit_valid_sha256(
    bars: tuple[Bar, ...], calendar: MarketCalendar, value: object
) -> None:
    with pytest.raises(DataIntegrityError):
        _scan(bars, calendar, data_snapshot_hash=value)


def test_r02_gd03_invalid_market_status_clock_symbol_config_fail_closed(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    for value in ("OK", None, 1):
        with pytest.raises(DataIntegrityError):
            _scan(bars, calendar, market_status=value)
    with pytest.raises(DataIntegrityError):
        _scan(bars, calendar, now=datetime(2026, 9, 29))
    with pytest.raises(DataIntegrityError):
        scanner.scan(
            "nvda",
            bars,
            now=datetime(2026, 9, 29, tzinfo=UTC),
            calendar=calendar,
            data_snapshot_hash="a" * 64,
            market_status=MarketStatus.OK,
        )
    config = scanner.ScannerConfig().model_copy(update={"swing_right": True})
    with pytest.raises(DataIntegrityError):
        _scan(bars, calendar, config=config)


def test_r02_gd03_every_unexpected_computation_and_calendar_fault_is_typed(
    bars: tuple[Bar, ...], calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("untrusted failure")

    with monkeypatch.context() as patch:
        patch.setattr(indicators, "ema", broken)
        with pytest.raises(DataIntegrityError):
            _scan(bars, calendar)
    with monkeypatch.context() as patch:
        patch.setattr(calendar, "is_session", broken)
        with pytest.raises(DataIntegrityError):
            _scan(bars, calendar)


def test_r02_r13_gd03_result_models_reject_unbound_hits_missing_facts_subcent_and_future_anchor(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    result = _scan(bars, calendar)
    assert result.indicators is not None
    facts = result.indicators
    for updates in (
        {"atr14": Decimal("1.001")},
        {"anchor_session": date(2027, 1, 4)},
        {"ema20": Decimal("1.001")},
    ):
        with pytest.raises(ValidationError):
            scanner.IndicatorSnapshot.model_validate(facts.model_copy(update=updates))
    for result_updates in (
        {"status": ProviderStatus.UNAVAILABLE},
        {"status": ProviderStatus.ERROR},
        {"indicators": None},
        {"symbol": "SPY"},
        {"as_of": result.as_of + timedelta(seconds=1)},
    ):
        with pytest.raises(ValidationError):
            scanner.ScannerResult.model_validate(result.model_copy(update=result_updates))
    for hit_updates in ({"last_price": Decimal(1)}, {"rvol": Decimal(1)}, {"rsi": Decimal(1)}):
        changed = result.hits[0].model_copy(update=hit_updates)
        with pytest.raises(ValidationError):
            scanner.ScannerResult.model_validate(result.model_copy(update={"hits": (changed,)}))
    with pytest.raises(ValidationError):
        scanner.ScannerResult.model_validate(result.model_copy(update={"extra": 1}))


def test_dat03_provenance_changes_when_completed_price_changes(
    bars: tuple[Bar, ...], calendar: MarketCalendar
) -> None:
    original = _scan(bars, calendar)
    last = bars[-1].model_copy(update={"close": bars[-1].close + Decimal("0.01")})
    changed = _scan((*bars[:-1], last), calendar)
    assert original.completed_bars_hash != changed.completed_bars_hash
    assert original.hits[0].last_price + Decimal("0.01") == changed.hits[0].last_price
