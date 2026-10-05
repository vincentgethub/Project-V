"""DAT-01..04/R-02/R-04: offline market-data safety and SDK-shape regressions."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import requests
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockLatestTradeRequest
from plaid.exceptions import ApiException
from pydantic import ValidationError
from sqlalchemy import Engine, select
from urllib3 import HTTPConnectionPool
from urllib3.exceptions import ReadTimeoutError

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import DataSnapshot, SystemEvent, transaction
from backend.core.errors import DataIntegrityError, ProviderError, SafetyError, StaleDataError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.broker_state import ExactJSONResponse, TimeoutSession
from backend.data.data_layer import (
    AlpacaMarketData,
    Bar,
    DataLayer,
    FakeMarketData,
    MarketDataProvider,
    ResilientReader,
    validate_clock_skew,
    validate_quote,
)
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import MarketContext, MarketStatus

NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def notify(self, state: str, reason: str) -> None:
        self.events.append((state, reason))


class RawProvider:
    def __init__(self, bars: tuple[Bar, ...], context: MarketContext) -> None:
        self.bars = bars
        self.context = context

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        return self.bars

    def latest_market(self, symbol: str, now: datetime) -> MarketContext:
        return self.context


def market(timestamp: datetime, **values: Any) -> MarketContext:
    return MarketContext(
        last_price=values.get("last_price", Decimal("100")),
        last_price_ts=timestamp,
        adv20_usd=values.get("adv20_usd", Decimal("1000000")),
        status=values.get("status", MarketStatus.OK),
    )


def daily_bar(day: date, **values: Any) -> Bar:
    fields: dict[str, Any] = {
        "timestamp": datetime(day.year, day.month, day.day, tzinfo=NEW_YORK),
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100"),
        "volume": 1000,
    }
    fields.update(values)
    return Bar(**fields)


def intraday_bar(timestamp: datetime) -> Bar:
    return daily_bar(timestamp.date(), timestamp=timestamp)


def make_layer(
    engine: Engine,
    calendar: MarketCalendar,
    *,
    now: datetime = NOW,
    bars: tuple[Bar, ...] = (),
    context: MarketContext | None = None,
    provider: MarketDataProvider | None = None,
    **values: Any,
) -> tuple[DataLayer, SystemStateStore, Ledger, RecordingNotifier]:
    clock = FrozenClock(now)
    notifier = RecordingNotifier()
    state = SystemStateStore(engine, clock, notifier)
    ledger = Ledger(engine, clock)
    layer = DataLayer(
        Settings(),
        provider or RawProvider(bars, context or market(now)),
        calendar,
        clock,
        state,
        ledger,
        **values,
    )
    return layer, state, ledger, notifier


@pytest.mark.parametrize("age,passes", [(0, True), (60, True), (61, False)])
def test_DAT_01_regular_quote_age_exact_boundary(
    calendar: MarketCalendar,
    age: int,
    passes: bool,
) -> None:
    context = market(NOW - timedelta(seconds=age))
    if passes:
        validate_quote(context, NOW, Settings(), calendar)
    else:
        with pytest.raises(StaleDataError):
            validate_quote(context, NOW, Settings(), calendar)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 29, 23, 0, tzinfo=UTC),
        datetime(2026, 10, 3, 18, 0, tzinfo=UTC),
        datetime(2026, 10, 4, 18, 0, tzinfo=UTC),
        datetime(2026, 7, 3, 18, 0, tzinfo=UTC),
        datetime(2026, 11, 27, 18, 30, tzinfo=UTC),
        datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
    ],
)
def test_DAT_01_frozen_night_weekend_holiday_earlyclose_and_dst_do_not_halt(
    engine: Engine,
    calendar: MarketCalendar,
    now: datetime,
) -> None:
    close = calendar.session_close(calendar.last_completed_session(now))
    layer, state, _, notifier = make_layer(engine, calendar, now=now, context=market(close))
    assert layer.latest_market("AAPL").last_price_ts == close
    assert state.current() == SystemState.RUNNING
    assert notifier.events == []


def test_DAT_01_offhours_quote_age_measured_from_last_close(calendar: MarketCalendar) -> None:
    now = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
    close = calendar.session_close(date(2026, 10, 2))
    validate_quote(market(close - timedelta(seconds=60)), now, Settings(), calendar)
    with pytest.raises(StaleDataError):
        validate_quote(market(close - timedelta(seconds=61)), now, Settings(), calendar)


@pytest.mark.parametrize(
    "timestamp", [NOW + timedelta(microseconds=1), NOW - timedelta(seconds=61)]
)
def test_DAT_01_DAT_02_invalid_quote_halts_with_typed_error(
    engine: Engine,
    calendar: MarketCalendar,
    timestamp: datetime,
) -> None:
    layer, state, _, notifier = make_layer(engine, calendar, context=market(timestamp))
    with pytest.raises(SafetyError):
        layer.latest_market("AAPL")
    assert state.current() == SystemState.HALTED
    assert notifier.events[-1][0] == "HALTED"


@pytest.mark.parametrize("seconds,passes", [(2, True), (-2, True), (3, False), (-3, False)])
def test_DAT_02_clock_skew_exact_boundary(seconds: int, passes: bool) -> None:
    if passes:
        validate_clock_skew(NOW + timedelta(seconds=seconds), NOW, Settings())
    else:
        with pytest.raises(DataIntegrityError):
            validate_clock_skew(NOW + timedelta(seconds=seconds), NOW, Settings())


def test_DAT_03_inprogress_daily_is_persisted_raw_and_not_returned(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    previous = daily_bar(date(2026, 9, 28))
    current = daily_bar(date(2026, 9, 29))
    layer, state, ledger, _ = make_layer(engine, calendar, bars=(previous, current))
    assert layer.completed_daily_bars("AAPL", date(2026, 9, 28)) == (previous,)
    assert state.current() == SystemState.RUNNING
    with transaction(engine) as session:
        snapshots = tuple(session.scalars(select(DataSnapshot)))
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.bar_count == 2 and len(snapshot.bars) == 2
    assert snapshot.feed == "SIP" and snapshot.adjustment == "ALL"
    assert snapshot.fetched_at == NOW
    assert len(snapshot.sha256) == 64
    ledger.verify_chain()


@pytest.mark.parametrize("elapsed,passes", [(899, True), (900, False)])
def test_DAT_01_sip_daily_grace_exact_boundary(
    engine: Engine,
    calendar: MarketCalendar,
    elapsed: int,
    passes: bool,
) -> None:
    now = calendar.session_close(date(2026, 9, 29)) + timedelta(seconds=elapsed)
    previous = daily_bar(date(2026, 9, 28))
    layer, state, _, _ = make_layer(engine, calendar, now=now, bars=(previous,))
    if passes:
        assert layer.completed_daily_bars("AAPL", date(2026, 9, 28)) == (previous,)
        assert state.current() == SystemState.RUNNING
    else:
        with pytest.raises(StaleDataError):
            layer.completed_daily_bars("AAPL", date(2026, 9, 28))
        assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "unordered",
        "missing_middle",
        "missing_first",
        "stale",
        "empty",
        "future",
        "holiday",
    ],
)
def test_DAT_01_DAT_02_daily_sequence_failures_halt(
    engine: Engine,
    calendar: MarketCalendar,
    fault: str,
) -> None:
    now = datetime(2026, 9, 29, 21, 0, tzinfo=UTC)
    first, middle, last = (
        daily_bar(day) for day in (date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29))
    )
    choices: dict[str, tuple[Bar, ...]] = {
        "duplicate": (first, middle, middle, last),
        "unordered": (middle, first, last),
        "missing_middle": (first, last),
        "missing_first": (middle, last),
        "stale": (first, middle),
        "empty": (),
        "future": (
            first,
            middle,
            last.model_copy(update={"timestamp": now + timedelta(seconds=1)}),
        ),
        "holiday": (daily_bar(date(2026, 7, 3)), last),
    }
    layer, state, _, _ = make_layer(engine, calendar, now=now, bars=choices[fault])
    with pytest.raises(SafetyError):
        layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "updates",
    [
        {"open": Decimal("0")},
        {"close": Decimal("-1")},
        {"open": None},
        {"open": Decimal("NaN")},
        {"high": Decimal("99")},
        {"low": Decimal("101")},
        {"high": Decimal("98"), "low": Decimal("99")},
        {"volume": -1},
        {"volume": True},
        {"volume": Decimal("1")},
        {"timestamp": datetime(2026, 9, 28)},
    ],
)
def test_DAT_02_each_daily_integrity_violation_halts(
    engine: Engine,
    calendar: MarketCalendar,
    updates: dict[str, Any],
) -> None:
    broken = daily_bar(date(2026, 9, 28)).model_copy(update=updates)
    layer, state, _, _ = make_layer(engine, calendar, bars=(broken,))
    with pytest.raises(SafetyError):
        layer.completed_daily_bars("AAPL", date(2026, 9, 28))
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize("opening,suspect", [("125", False), ("125.01", True)])
def test_DAT_02_gap_exact_boundary_is_suspect_and_survives_restart(
    engine: Engine,
    calendar: MarketCalendar,
    opening: str,
    suspect: bool,
) -> None:
    left = daily_bar(date(2026, 9, 25))
    right = daily_bar(
        date(2026, 9, 28),
        open=Decimal(opening),
        high=Decimal("127"),
        low=Decimal("124"),
        close=Decimal("126"),
    )
    layer, state, ledger, _ = make_layer(engine, calendar, bars=(left, right))
    layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    expected = MarketStatus.SUSPECT if suspect else MarketStatus.OK
    assert layer.latest_market("AAPL").status == expected
    restarted = DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
    assert restarted.latest_market("AAPL").status == expected
    assert state.current() == SystemState.RUNNING
    if suspect:
        with pytest.raises(DataIntegrityError):
            restarted.acknowledge_gap("AAPL", "", "checked split")
        restarted.acknowledge_gap("AAPL", "operator-test", "verified corporate action")
        again = DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
        assert again.latest_market("AAPL").status == MarketStatus.OK


def test_DAT_02_known_corporate_action_explains_gap(
    engine: Engine, calendar: MarketCalendar
) -> None:
    left = daily_bar(date(2026, 9, 25))
    right = daily_bar(
        date(2026, 9, 28),
        open=Decimal("150"),
        high=Decimal("151"),
        low=Decimal("149"),
        close=Decimal("150"),
    )
    layer, _, _, _ = make_layer(
        engine,
        calendar,
        bars=(left, right),
        corporate_actions=frozenset({("AAPL", date(2026, 9, 28))}),
    )
    layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    assert layer.latest_market("AAPL").status == MarketStatus.OK


@pytest.mark.parametrize("end_age,passes", [(120, True), (121, False)])
def test_DAT_01_intraday_endtime_age_exact_boundary(
    engine: Engine,
    calendar: MarketCalendar,
    end_age: int,
    passes: bool,
) -> None:
    layer, state, _, _ = make_layer(engine, calendar)
    bar = intraday_bar(NOW - timedelta(seconds=end_age + 60))
    if passes:
        assert layer.validate_intraday((bar,), 60) == (bar,)
    else:
        with pytest.raises(StaleDataError):
            layer.validate_intraday((bar,), 60)
        assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "fault", ["inprogress", "future", "duplicate", "unordered", "missing_interval", "weekend"]
)
def test_DAT_02_DAT_03_invalid_intraday_sequences_halt(
    engine: Engine,
    calendar: MarketCalendar,
    fault: str,
) -> None:
    layer, state, _, _ = make_layer(engine, calendar)
    a, b = intraday_bar(NOW - timedelta(minutes=2)), intraday_bar(NOW - timedelta(minutes=1))
    choices = {
        "inprogress": (intraday_bar(NOW - timedelta(seconds=30)),),
        "future": (intraday_bar(NOW + timedelta(seconds=1)),),
        "duplicate": (b, b),
        "unordered": (b, a),
        "missing_interval": (intraday_bar(NOW - timedelta(minutes=5)), b),
        "weekend": (intraday_bar(datetime(2026, 9, 26, 15, 0, tzinfo=UTC)), b),
    }
    with pytest.raises(SafetyError):
        layer.validate_intraday(choices[fault], 60)
    assert state.current() == SystemState.HALTED


def test_DAT_01_intraday_weekend_uses_friday_session_close(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    now = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
    close = calendar.session_close(date(2026, 10, 2))
    layer, state, _, _ = make_layer(engine, calendar, now=now)
    bar = intraday_bar(close - timedelta(seconds=60))
    assert layer.validate_intraday((bar,), 60) == (bar,)
    assert state.current() == SystemState.RUNNING


class StatusError(Exception):
    def __init__(self, status: int) -> None:
        self.status_code = status


def reader_fixture(
    engine: Engine,
    *,
    attempts: int = 3,
    calls_per_minute: int = 200,
) -> tuple[ResilientReader, SystemStateStore, list[float]]:
    state = SystemStateStore(engine, FrozenClock(NOW), RecordingNotifier())
    sleeps: list[float] = []
    reader = ResilientReader(
        FrozenClock(NOW),
        state,
        attempts=attempts,
        calls_per_minute=calls_per_minute,
        sleep=sleeps.append,
    )
    return reader, state, sleeps


@pytest.mark.parametrize(
    "error",
    [
        StatusError(429),
        StatusError(500),
        StatusError(503),
        TimeoutError("timeout"),
        requests.Timeout("timeout"),
    ],
)
def test_DAT_04_transient_reads_retry_with_fake_sleep_and_recover(
    engine: Engine,
    error: Exception,
) -> None:
    reader, state, sleeps = reader_fixture(engine)
    count = 0

    def operation() -> str:
        nonlocal count
        count += 1
        if count < 3:
            raise error
        return "trusted-result"

    assert reader.run(operation) == "trusted-result"
    assert count == 3 and len(sleeps) == 2
    assert all(1 <= delay <= 8 for delay in sleeps)
    assert not reader.tripped and state.current() == SystemState.RUNNING


@pytest.mark.parametrize(
    "error", [StatusError(400), StatusError(401), RuntimeError("fault"), KeyError("field")]
)
def test_DAT_04_nontransient_reads_are_never_retried(engine: Engine, error: Exception) -> None:
    reader, state, sleeps = reader_fixture(engine)
    count = 0

    def operation() -> str:
        nonlocal count
        count += 1
        raise error

    with pytest.raises(ProviderError):
        reader.run(operation)
    assert count == 1 and sleeps == []
    assert reader.tripped and state.current() == SystemState.HALTED


def test_DAT_04_retry_exhaustion_latches_circuit_and_restart_state(engine: Engine) -> None:
    reader, state, sleeps = reader_fixture(engine)
    count = 0

    def operation() -> int:
        nonlocal count
        count += 1
        raise StatusError(429)

    with pytest.raises(ProviderError):
        reader.run(operation)
    assert count == 3 and len(sleeps) == 2
    with pytest.raises(ProviderError, match="latched"):
        reader.run(operation)
    assert count == 3
    assert (
        SystemStateStore(engine, FrozenClock(NOW), RecordingNotifier()).current()
        == SystemState.HALTED
    )
    assert state.current() == SystemState.HALTED


def test_DAT_04_request_budget_counts_retries_and_blocks_before_io(engine: Engine) -> None:
    reader, state, sleeps = reader_fixture(engine, calls_per_minute=2)
    count = 0

    def operation() -> str:
        nonlocal count
        count += 1
        return "result"

    reader.run(operation)
    reader.run(operation)
    with pytest.raises(ProviderError, match="budget"):
        reader.run(operation)
    assert count == 2 and sleeps == [] and state.current() == SystemState.HALTED


def test_DAT_04_budget_exact_minute_and_backward_clock_fail_closed(engine: Engine) -> None:
    reader, state, _ = reader_fixture(engine, calls_per_minute=1)
    reader.run(lambda: "first")
    reader.clock = FrozenClock(NOW + timedelta(seconds=60))
    assert reader.run(lambda: "second") == "second"
    reader.clock = FrozenClock(NOW + timedelta(seconds=59))
    with pytest.raises(DataIntegrityError, match="backward"):
        reader.run(lambda: "must-not-run")
    assert state.current() == SystemState.HALTED


def test_DAT_04_requests_http_status_429_is_transient(engine: Engine) -> None:
    reader, state, sleeps = reader_fixture(engine, attempts=2)
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError("rate limited", response=response)
    count = 0

    def operation() -> int:
        nonlocal count
        count += 1
        if count == 1:
            raise error
        return 5

    assert reader.run(operation) == 5
    assert len(sleeps) == 1 and state.current() == SystemState.RUNNING


def fault(*args: object, **kwargs: object) -> Any:
    raise RuntimeError("injected boundary fault")


@pytest.mark.parametrize("boundary", ["calendar", "provider", "database"])
def test_R_02_DAT_02_runtime_boundary_faults_are_typed_and_halt(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar, bars=(daily_bar(date(2026, 9, 28)),))
    if boundary == "calendar":
        monkeypatch.setattr(calendar, "is_open", fault)
    elif boundary == "provider":
        monkeypatch.setattr(layer.provider, "latest_market", fault)
    else:
        monkeypatch.setattr(ledger, "append", fault)

    def operation() -> None:
        if boundary == "database":
            layer.completed_daily_bars("AAPL", date(2026, 9, 28))
        else:
            layer.latest_market("AAPL")

    with pytest.raises(SafetyError):
        operation()
    assert state.current() == SystemState.HALTED


def test_R_02_DAT_02_persisted_symbol_replay_fault_is_typed_and_halts(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar)
    ledger.append(
        SystemEvent,
        state="RUNNING",
        event_type="ESCALATE",
        operator_id=None,
        reason="DAT-02 symbol status: malformed-json",
    )
    with pytest.raises(SafetyError):
        DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
    assert state.current() == SystemState.HALTED


def test_R_02_DAT_02_gap_acknowledgment_database_fault_is_typed_and_halts(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar)
    monkeypatch.setattr(ledger, "append_in_session", fault)
    with pytest.raises(SafetyError):
        layer.acknowledge_gap("AAPL", "operator-test", "checked")
    assert state.current() == SystemState.HALTED


def raw_bar(bar: Bar) -> dict[str, object]:
    return {
        "t": bar.timestamp.isoformat(),
        "o": bar.open,
        "h": bar.high,
        "l": bar.low,
        "c": bar.close,
        "v": bar.volume,
    }


class FakeSDK:
    """Return installed alpaca-py raw_data symbol maps, without HTTP envelopes."""

    def __init__(self, bars: tuple[Bar, ...]) -> None:
        self._session = TimeoutSession(30)
        self._retry = 3
        self.bars: dict[str, Any] = {"AAPL": [raw_bar(bar) for bar in bars]}
        self.quotes: dict[str, Any] = {
            "AAPL": {
                "bp": Decimal("99.99"),
                "ap": Decimal("100.01"),
                "t": (NOW - timedelta(seconds=10)).isoformat(),
            }
        }
        self.trades: dict[str, Any] = {
            "AAPL": {"p": Decimal("100"), "t": (NOW - timedelta(seconds=5)).isoformat()}
        }
        self.requests: list[object] = []

    def get_stock_bars(self, request: StockBarsRequest) -> object:
        self.requests.append(request)
        return self.bars

    def get_stock_latest_quote(self, request: StockLatestQuoteRequest) -> object:
        self.requests.append(request)
        return self.quotes

    def get_stock_latest_trade(self, request: StockLatestTradeRequest) -> object:
        self.requests.append(request)
        return self.trades


def sdk_fixture(
    engine: Engine, calendar: MarketCalendar
) -> tuple[AlpacaMarketData, FakeSDK, SystemStateStore]:
    bars = tuple(daily_bar(day) for day in calendar.previous_sessions(NOW.date(), 20))
    client = FakeSDK(bars)
    reader, state, _ = reader_fixture(engine)
    provider = AlpacaMarketData(Settings(), reader, client=client)
    return provider, client, state


def test_DAT_03_official_sdk_symbol_shapes_and_sip_iex_request_contracts(
    engine: Engine,
    calendar: MarketCalendar,
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    assert isinstance(client._session, TimeoutSession) and client._retry == 0
    bars = provider.daily_bars("AAPL", date(2026, 8, 31), NOW.date())
    assert len(bars) == 20
    request = client.requests[-1]
    assert isinstance(request, StockBarsRequest)
    assert request.feed == DataFeed.SIP and request.adjustment == Adjustment.ALL
    # Pinned alpaca-py normalizes aware inputs to naive UTC in the request model.
    assert request.start == datetime(2026, 8, 31, 4, 0)
    assert request.end == datetime(2026, 9, 30, 4, 0)
    context = provider.latest_market("AAPL", NOW)
    assert context.last_price == Decimal("100") and context.adv20_usd == Decimal("100000")
    assert context.last_price_ts == NOW - timedelta(seconds=10)
    quote_request = next(
        item for item in client.requests if isinstance(item, StockLatestQuoteRequest)
    )
    trade_request = next(
        item for item in client.requests if isinstance(item, StockLatestTradeRequest)
    )
    assert quote_request.feed == DataFeed.IEX and trade_request.feed == DataFeed.IEX
    assert state.current() == SystemState.RUNNING


@pytest.mark.parametrize("fault_kind", ["bad_ohlc", "missing_session", "stale_tail", "float_price"])
def test_DAT_02_adv_history_must_be_valid_complete_current_and_exact(
    engine: Engine,
    calendar: MarketCalendar,
    fault_kind: str,
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    if fault_kind == "bad_ohlc":
        client.bars["AAPL"][0]["h"] = Decimal("50")
    elif fault_kind == "float_price":
        client.bars["AAPL"][0]["o"] = float("100")
    elif fault_kind == "missing_session":
        all_sessions = calendar.previous_sessions(NOW.date(), 21)
        client.bars["AAPL"] = [
            raw_bar(daily_bar(day)) for index, day in enumerate(all_sessions) if index != 10
        ]
    else:
        old = calendar.previous_sessions(date(2026, 9, 14), 20)
        client.bars["AAPL"] = [raw_bar(daily_bar(day)) for day in old]
    layer = DataLayer(
        Settings(), provider, calendar, FrozenClock(NOW), state, Ledger(engine, FrozenClock(NOW))
    )
    with pytest.raises(SafetyError):
        layer.latest_market("AAPL")
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "field,value",
    [("bp", Decimal("0")), ("ap", Decimal("99")), ("t", (NOW + timedelta(seconds=1)).isoformat())],
)
def test_DAT_02_bad_sdk_quote_cannot_become_market_context(
    engine: Engine,
    calendar: MarketCalendar,
    field: str,
    value: object,
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    client.quotes["AAPL"][field] = value
    layer = DataLayer(
        Settings(), provider, calendar, FrozenClock(NOW), state, Ledger(engine, FrozenClock(NOW))
    )
    with pytest.raises(SafetyError):
        layer.latest_market("AAPL")
    assert state.current() == SystemState.HALTED


def test_R_04_DAT_03_transport_preserves_json_decimal_before_sdk_parsing() -> None:
    response = ExactJSONResponse()
    response._content = b'{"bars":{"AAPL":[{"c":100.123456,"v":1000}]}}'
    value = response.json()
    assert value["bars"]["AAPL"][0]["c"] == Decimal("100.123456")
    assert isinstance(value["bars"]["AAPL"][0]["c"], Decimal)


@pytest.mark.parametrize("price", [100.0, "100", 100, True, None, Decimal("100.001")])
def test_R_13_DAT_02_bar_boundary_requires_exact_decimal_cents(price: object) -> None:
    with pytest.raises(ValidationError):
        daily_bar(date(2026, 9, 28), open=price)
    forged = daily_bar(date(2026, 9, 28)).model_copy(update={"open": price})
    with pytest.raises(DataIntegrityError):
        forged.validate_integrity()


def test_DAT_02_quote_helper_revalidates_forged_frozen_market() -> None:
    forged = market(NOW).model_copy(update={"last_price": Decimal("100.001")})
    with pytest.raises(DataIntegrityError):
        validate_quote(forged, NOW, Settings(), MarketCalendar())


def test_DAT_03_fake_provider_and_snapshot_payload_are_reproducible(
    engine: Engine, calendar: MarketCalendar
) -> None:
    bars = (daily_bar(date(2026, 9, 25)), daily_bar(date(2026, 9, 28)))
    provider = FakeMarketData(bars, market(NOW), "AAPL")
    assert provider.daily_bars("AAPL", date(2026, 9, 26), date(2026, 9, 28)) == bars[1:]
    assert provider.latest_market("AAPL", NOW) == market(NOW)
    with pytest.raises(DataIntegrityError, match="fixture symbol"):
        provider.latest_market("MSFT", NOW)
    with pytest.raises(DataIntegrityError, match="fixture symbol"):
        provider.latest_market("aapl", NOW)
    layer, _, _, _ = make_layer(engine, calendar, provider=provider)
    assert layer.completed_daily_bars("AAPL", date(2026, 9, 26)) == bars[1:]
    with transaction(engine) as session:
        stored = session.scalar(select(DataSnapshot))
        assert stored is not None
        encoded = json.dumps(stored.bars, sort_keys=True, separators=(",", ":"), allow_nan=False)
        assert stored.sha256 == hashlib.sha256(encoded.encode()).hexdigest()


def test_DAT_02_duplicate_inprogress_session_with_distinct_times_halts(
    engine: Engine, calendar: MarketCalendar
) -> None:
    previous = daily_bar(date(2026, 9, 28))
    current = daily_bar(date(2026, 9, 29))
    duplicate = current.model_copy(update={"timestamp": current.timestamp + timedelta(minutes=1)})
    layer, state, _, _ = make_layer(engine, calendar, bars=(previous, current, duplicate))
    with pytest.raises(DataIntegrityError, match="duplicate daily session"):
        layer.completed_daily_bars("AAPL", date(2026, 9, 28))
    assert state.current() == SystemState.HALTED


def test_DAT_02_acknowledged_gap_stays_clear_on_replay_and_new_gap_reflags(
    engine: Engine, calendar: MarketCalendar
) -> None:
    bars = (
        daily_bar(date(2026, 9, 25)),
        daily_bar(
            date(2026, 9, 28),
            open=Decimal("150"),
            high=Decimal("151"),
            low=Decimal("149"),
            close=Decimal("150"),
        ),
    )
    layer, state, ledger, _ = make_layer(engine, calendar, bars=bars)
    layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    layer.completed_daily_bars("AAPL", date(2026, 9, 25))
    layer.acknowledge_gap("AAPL", "operator-test", "verified gap")
    restarted = DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
    restarted.completed_daily_bars("AAPL", date(2026, 9, 25))
    assert restarted.latest_market("AAPL").status == MarketStatus.OK
    next_bar = daily_bar(
        date(2026, 9, 29),
        open=Decimal("225"),
        high=Decimal("226"),
        low=Decimal("224"),
        close=Decimal("225"),
    )
    later = datetime(2026, 9, 29, 21, 0, tzinfo=UTC)
    next_provider = RawProvider((*bars, next_bar), market(later))
    after = DataLayer(Settings(), next_provider, calendar, FrozenClock(later), state, ledger)
    after.completed_daily_bars("AAPL", date(2026, 9, 25))
    assert after.latest_market("AAPL").status == MarketStatus.SUSPECT


@pytest.mark.parametrize("method", ["latest_market", "completed_daily_bars"])
def test_R_02_DAT_02_invalid_symbol_is_rejected_before_provider_io(
    engine: Engine, calendar: MarketCalendar, method: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer, state, _, _ = make_layer(engine, calendar)
    monkeypatch.setattr(layer.provider, "latest_market", fault)
    monkeypatch.setattr(layer.provider, "daily_bars", fault)
    with pytest.raises(DataIntegrityError):
        if method == "latest_market":
            layer.latest_market("aapl")
        else:
            layer.completed_daily_bars("aapl", date(2026, 9, 28))
    assert not layer.reader.tripped
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize("start", [date(2026, 9, 30), datetime(2026, 9, 28, tzinfo=UTC), None])
def test_DAT_02_bad_daily_window_halts_before_io(
    engine: Engine, calendar: MarketCalendar, start: Any
) -> None:
    layer, state, _, _ = make_layer(engine, calendar)
    with pytest.raises(DataIntegrityError, match="request window"):
        layer.completed_daily_bars("AAPL", start)
    assert not layer.reader.tripped and state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "error",
    [
        ApiException(status=429),
        ApiException(status=503),
        ReadTimeoutError(HTTPConnectionPool("offline.invalid"), "/balance", "timeout"),
    ],
)
def test_DAT_04_official_plaid_transient_transport_exceptions_retry(
    engine: Engine, error: Exception
) -> None:
    reader, state, sleeps = reader_fixture(engine, attempts=2)
    count = 0

    def operation() -> str:
        nonlocal count
        count += 1
        if count == 1:
            raise error
        return "ok"

    assert reader.run(operation) == "ok"
    assert len(sleeps) == 1 and state.current() == SystemState.RUNNING


@pytest.mark.parametrize("bound", [0, 11, True, Decimal("2")])
def test_DAT_04_invalid_retry_bounds_fail_typed(engine: Engine, bound: Any) -> None:
    state = SystemStateStore(engine, FrozenClock(NOW), RecordingNotifier())
    with pytest.raises(ProviderError):
        ResilientReader(FrozenClock(NOW), state, attempts=bound)


@pytest.mark.parametrize("budget,passes", [(1, False), (2, True)])
def test_DAT_04_actual_sdk_pagination_counts_every_http_request_with_timeout(
    engine: Engine,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    budget: int,
    passes: bool,
) -> None:
    reader, state, _ = reader_fixture(engine, calls_per_minute=budget)
    client = StockHistoricalDataClient(
        api_key="offline-fixture", secret_key="offline-fixture", raw_data=True
    )
    provider = AlpacaMarketData(Settings(), reader, client=client, calendar=calendar)
    calls: list[dict[str, Any]] = []

    def http_read(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        assert method == "GET" and url.startswith("https://data.alpaca.markets/")
        calls.append(kwargs)
        first = len(calls) == 1
        day = date(2026, 9, 25) if first else date(2026, 9, 28)
        body = {
            "bars": {"AAPL": [raw_bar(daily_bar(day))]},
            "next_page_token": "offline-page-2" if first else None,
        }
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(body, default=str).encode()
        return response

    monkeypatch.setattr(requests.Session, "request", http_read)
    if passes:
        assert len(provider.daily_bars("AAPL", date(2026, 9, 25), date(2026, 9, 28))) == 2
        assert len(calls) == 2 and state.current() == SystemState.RUNNING
    else:
        with pytest.raises(ProviderError, match="budget"):
            provider.daily_bars("AAPL", date(2026, 9, 25), date(2026, 9, 28))
        assert len(calls) == 1 and reader.tripped and state.current() == SystemState.HALTED
    assert all(
        call["timeout"] == (5, 20) and call["allow_redirects"] is False and call["verify"] is True
        for call in calls
    )


@pytest.mark.parametrize("payload", [[], {"MSFT": []}, {"AAPL": [None]}, {"AAPL": [{"t": "bad"}]}])
def test_DAT_02_bad_sdk_raw_payload_halts_direct_adapter_calls(
    engine: Engine, calendar: MarketCalendar, payload: Any
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    client.bars = payload
    with pytest.raises(SafetyError):
        provider.daily_bars("AAPL", date(2026, 8, 1), NOW.date())
    assert state.current() == SystemState.HALTED


def test_R_02_DAT_02_bad_sdk_client_setup_halts(engine: Engine) -> None:
    reader, state, _ = reader_fixture(engine)
    with pytest.raises(SafetyError):
        AlpacaMarketData(Settings(), reader, client=object())
    assert state.current() == SystemState.HALTED


def test_R_02_DAT_02_copied_settings_cannot_relax_data_limits(
    engine: Engine, calendar: MarketCalendar
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar)
    forged = Settings().model_copy(update={"stale_quote_seconds": 10000})
    with pytest.raises(DataIntegrityError):
        DataLayer(forged, layer.provider, calendar, layer.clock, state, ledger)
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "bars,seconds", [((), 60), ((intraday_bar(NOW),), True), ((intraday_bar(NOW),), 0)]
)
def test_DAT_02_invalid_intraday_contract_halts(
    engine: Engine, calendar: MarketCalendar, bars: tuple[Bar, ...], seconds: Any
) -> None:
    layer, state, _, _ = make_layer(engine, calendar)
    with pytest.raises(DataIntegrityError):
        layer.validate_intraday(bars, seconds)
    assert state.current() == SystemState.HALTED


def test_DAT_02_intraday_interval_cannot_straddle_close(
    engine: Engine, calendar: MarketCalendar
) -> None:
    close = calendar.session_close(date(2026, 9, 29))
    layer, state, _, _ = make_layer(engine, calendar, now=close + timedelta(hours=1))
    with pytest.raises(DataIntegrityError, match="straddles"):
        layer.validate_intraday((intraday_bar(close - timedelta(seconds=30)),), 60)
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "fault_kind", ["next_open_missing", "prior_close_missing", "session_missing"]
)
def test_DAT_02_intraday_cross_session_missing_intervals_halt(
    engine: Engine, calendar: MarketCalendar, fault_kind: str
) -> None:
    previous_close = calendar.session_close(date(2026, 9, 25))
    today_open = calendar.session_open(date(2026, 9, 28))
    left = intraday_bar(previous_close - timedelta(seconds=60))
    right = intraday_bar(today_open)
    if fault_kind == "next_open_missing":
        right = intraday_bar(today_open + timedelta(seconds=60))
    elif fault_kind == "prior_close_missing":
        left = intraday_bar(previous_close - timedelta(seconds=120))
    else:
        left = intraday_bar(calendar.session_close(date(2026, 9, 24)) - timedelta(seconds=60))
    layer, state, _, _ = make_layer(engine, calendar, now=today_open + timedelta(seconds=120))
    with pytest.raises(DataIntegrityError, match="exchange session interval"):
        layer.validate_intraday((left, right), 60)
    assert state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "fault_kind", ["future", "duplicate_timestamp", "duplicate_session", "short"]
)
def test_DAT_02_entire_sdk_adv_sequence_is_untrusted(
    engine: Engine, calendar: MarketCalendar, fault_kind: str
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    bars = client.bars["AAPL"]
    if fault_kind == "future":
        bars.append(raw_bar(daily_bar(NOW.date(), timestamp=NOW + timedelta(seconds=1))))
    elif fault_kind == "duplicate_timestamp":
        bars.insert(1, dict(bars[0]))
    elif fault_kind == "duplicate_session":
        duplicate = dict(bars[0])
        duplicate["t"] = (
            datetime.fromisoformat(str(bars[0]["t"])) + timedelta(minutes=1)
        ).isoformat()
        bars.insert(1, duplicate)
    else:
        client.bars["AAPL"] = bars[-19:]
    with pytest.raises(SafetyError):
        provider.latest_market("AAPL", NOW)
    assert state.current() == SystemState.HALTED


def test_DAT_01_direct_sdk_stale_quote_halts_even_when_daily_adv_is_fresh(
    engine: Engine, calendar: MarketCalendar
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    client.quotes["AAPL"]["t"] = (NOW - timedelta(seconds=61)).isoformat()
    with pytest.raises(StaleDataError):
        provider.latest_market("AAPL", NOW)
    assert state.current() == SystemState.HALTED


def test_R_02_DAT_02_direct_sdk_missing_quote_fields_halts(
    engine: Engine, calendar: MarketCalendar
) -> None:
    provider, client, state = sdk_fixture(engine, calendar)
    del client.quotes["AAPL"]["t"]
    with pytest.raises(DataIntegrityError):
        provider.latest_market("AAPL", NOW)
    assert state.current() == SystemState.HALTED


def test_DAT_03_sdk_provider_completed_bars_and_no_double_request_budget(
    engine: Engine, calendar: MarketCalendar
) -> None:
    provider, _, state = sdk_fixture(engine, calendar)
    layer = DataLayer(
        Settings(), provider, calendar, FrozenClock(NOW), state, Ledger(engine, FrozenClock(NOW))
    )
    assert len(layer.completed_daily_bars("AAPL", date(2026, 8, 31))) == 20
    # This injected client performs no HTTP; only real requests consume transport budget.
    assert not provider.reader._calls and not layer.reader._calls


def test_DAT_02_future_gap_acknowledgment_event_is_unverifiable(
    engine: Engine, calendar: MarketCalendar
) -> None:
    layer, state, ledger, _ = make_layer(engine, calendar)
    layer._record_symbol_status(
        "AAPL",
        "OK",
        "operator",
        "forged future cutoff",
        acknowledged_through=date(2027, 1, 1),
    )
    with pytest.raises(DataIntegrityError, match="future gap"):
        DataLayer(Settings(), layer.provider, calendar, layer.clock, state, ledger)
    assert state.current() == SystemState.HALTED


def test_DAT_02_other_worker_suspect_and_ack_are_observed_without_restart(
    engine: Engine, calendar: MarketCalendar
) -> None:
    first, state, ledger, _ = make_layer(engine, calendar)
    other = DataLayer(Settings(), first.provider, calendar, first.clock, state, ledger)
    other._record_symbol_status("AAPL", "SUSPECT", None, "unexplained gap")
    assert first.latest_market("AAPL").status == MarketStatus.SUSPECT
    other.acknowledge_gap("AAPL", "operator", "verified gap")
    assert first.latest_market("AAPL").status == MarketStatus.OK
