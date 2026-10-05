"""R-01/R-02/R-06/R-08/CMP-06/DAT-02: broker reads and schema drift tests.

The account JSON fixture is synthetic and representative of current documented
fields. It is not captured from a live account and contains no real credentials.
"""

import json
import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from alpaca.trading.client import TradingClient
from alpaca.trading.models import TradeAccount
from alpaca.trading.requests import GetOrdersRequest
from pydantic import SecretStr
from requests import Response, Session
from sqlalchemy.engine import Engine

import backend.data.broker_state as broker_module
from backend.core.clock import FrozenClock
from backend.core.config import LIVE_BROKER_ENDPOINT, PAPER_BROKER_ENDPOINT, Settings
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.broker_state import (
    AlpacaBrokerState,
    ExactJSONResponse,
    FakeBrokerState,
    TimeoutSession,
    configure_alpaca_transport,
    prepare_alpaca_client,
)
from backend.data.data_layer import ResilientReader
from backend.domain.models import AccountFlags

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)


def account_fixture() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "current_account.json"
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    return value


class FakeClient:
    def __init__(self) -> None:
        self._base_url = PAPER_BROKER_ENDPOINT
        self.account: Any = account_fixture()
        self.positions: Any = [
            {
                "symbol": "AAPL",
                "asset_class": "us_equity",
                "side": "long",
                "qty": "30",
                "avg_entry_price": "90",
                "current_price": "100",
            }
        ]
        self.orders: Any = [
            {
                "id": "synthetic-order",
                "symbol": "AAPL",
                "asset_class": "us_equity",
                "side": "buy",
                "type": "limit",
                "status": "partially_filled",
                "qty": "5",
                "filled_qty": "2",
                "limit_price": "101",
            }
        ]
        self.broker_clock: Any = {"timestamp": NOW.isoformat()}
        self.fault: Exception | None = None
        self.call_count = 0

    def _check(self) -> None:
        self.call_count += 1
        if self.fault:
            raise self.fault

    def get_account(self) -> object:
        self._check()
        return self.account

    def get_all_positions(self) -> object:
        self._check()
        return self.positions

    def get_orders(self, filter: GetOrdersRequest | None = None) -> object:
        self._check()
        assert filter is not None and filter.limit == 500
        return self.orders

    def get_clock(self) -> object:
        self._check()
        return self.broker_clock


def provider(client: FakeClient, **values: Any) -> AlpacaBrokerState:
    return AlpacaBrokerState(
        Settings(),
        FrozenClock(NOW),
        lambda equity, now: (Decimal("11000"), Decimal("10000")),
        client=client,
        known_symbols=frozenset({"AAPL"}),
        **values,
    )


def test_DAT_02_current_account_fixture_parses_official_sdk_and_required_projection() -> None:
    payload = account_fixture()
    account = TradeAccount.model_validate(payload)
    assert str(account.id) == payload["id"]
    assert account.equity == "10000.00"
    state = provider(FakeClient())
    snapshot = state.snapshot(NOW)
    assert snapshot.equity == Decimal("10000")
    assert snapshot.settled_cash == 0
    assert snapshot.positions["AAPL"].qty == 30
    assert snapshot.open_orders[0].qty == 3
    assert snapshot.high_water_mark == Decimal("11000")
    assert snapshot.day_start_equity == Decimal("10000")
    assert state.last_flags is not None and not state.last_flags.blocked


def test_CMP_03_settled_cash_is_only_from_injected_trusted_ledger() -> None:
    state = provider(FakeClient(), settled_cash_provider=lambda now: Decimal("5000"))
    assert state.snapshot(NOW).settled_cash == Decimal("5000")


@pytest.mark.parametrize(
    "field",
    [
        "equity",
        "cash",
        "buying_power",
        "trading_blocked",
        "account_blocked",
        "trade_suspended_by_user",
        "status",
        "currency",
        "id",
    ],
)
def test_R_02_account_schema_missing_required_field_fails_loudly(field: str) -> None:
    client = FakeClient()
    client.account.pop(field)
    with pytest.raises((DataIntegrityError, ProviderError)):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize("field", ["trading_blocked", "account_blocked", "trade_suspended_by_user"])
def test_CMP_06_exact_broker_flags_remain_visible_for_halt(field: str) -> None:
    client = FakeClient()
    client.account[field] = True
    state = provider(client)
    state.snapshot(NOW)
    assert state.last_flags is not None and state.last_flags.blocked
    client.account[field] = "false"
    with pytest.raises(DataIntegrityError):
        state.snapshot(NOW)
    assert state.last_flags is None


@pytest.mark.parametrize("value", ["0.5", "-1", "0", "NaN", None])
def test_R_01_broker_positions_are_whole_long_shares(value: Any) -> None:
    client = FakeClient()
    client.positions[0]["qty"] = value
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("side", "short"),
        ("symbol", "UNKNOWN"),
        ("asset_class", "crypto"),
        ("current_price", "0"),
        ("avg_entry_price", float("90")),
    ],
)
def test_R_02_invalid_position_data_cannot_reach_snapshot(field: str, value: Any) -> None:
    client = FakeClient()
    client.positions[0][field] = value
    with pytest.raises((DataIntegrityError, ProviderError)):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "market"),
        ("qty", "5.5"),
        ("filled_qty", "5"),
        ("limit_price", None),
        ("side", "invalid"),
        ("status", "filled"),
    ],
)
def test_R_01_pending_orders_are_verifiable_remaining_limit_quantities(
    field: str, value: Any
) -> None:
    client = FakeClient()
    client.orders[0][field] = value
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


def test_R_02_duplicate_and_truncated_broker_lists_fail_closed() -> None:
    client = FakeClient()
    client.positions.append(dict(client.positions[0]))
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)
    client = FakeClient()
    client.orders *= 500
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize("seconds,passed", [(2, True), (3, False), (-2, True), (-3, False)])
def test_DAT_02_clock_skew_exact_boundary(seconds: int, passed: bool) -> None:
    client = FakeClient()
    client.broker_clock["timestamp"] = (NOW + timedelta(seconds=seconds)).isoformat()
    if passed:
        provider(client).snapshot(NOW)
    else:
        with pytest.raises(DataIntegrityError):
            provider(client).snapshot(NOW)


def test_R_02_unexpected_broker_exception_is_typed_and_no_flags_survive() -> None:
    client = FakeClient()
    client.fault = RuntimeError("synthetic provider fault")
    state = provider(client)
    with pytest.raises(ProviderError):
        state.snapshot(NOW)
    assert state.last_flags is None


def test_R_06_injected_client_endpoint_must_match_paper_mode() -> None:
    client = FakeClient()
    client._base_url = LIVE_BROKER_ENDPOINT
    with pytest.raises(ConfigurationError):
        provider(client)
    assert client.call_count == 0


def test_R_08_timeout_transport_rejects_writes_and_fails_sdk_drift() -> None:
    with pytest.raises(ProviderError):
        TimeoutSession(30).request("POST", "https://paper-api.alpaca.markets")
    with pytest.raises(ConfigurationError):
        configure_alpaca_transport(object())
    with pytest.raises(ConfigurationError):
        TimeoutSession(0)


def test_R_04_alpaca_transport_json_numbers_become_decimal() -> None:
    response = ExactJSONResponse()
    response._content = b'{"price": 123.456789, "qty": 5}'
    value = response.json()
    assert value["price"] == Decimal("123.456789")
    assert isinstance(value["price"], Decimal)


def test_DAT_04_timeout_is_explicit_on_actual_session_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_request(self: Session, method: str, url: str, *args: Any, **kwargs: Any) -> Response:
        observed.update(kwargs)
        response = Response()
        response._content = b'{"price":100.01}'
        response.status_code = 200
        return response

    monkeypatch.setattr(Session, "request", fake_request)
    response = TimeoutSession(30).request("GET", "https://paper-api.alpaca.markets")
    assert observed["timeout"] == 30
    assert response.json()["price"] == Decimal("100.01")


@pytest.mark.parametrize("timeout", [True, False, 1.0, "30", -1, 0, 61, None])
def test_DAT_04_transport_timeout_is_strict_bounded_integer(timeout: Any) -> None:
    with pytest.raises(ConfigurationError):
        TimeoutSession(timeout)


def test_DAT_04_transport_counts_http_calls_and_disables_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def before_request() -> None:
        calls.append("budget")

    def fake_request(self: Session, method: Any, url: Any, *args: Any, **kwargs: Any) -> Response:
        calls.append("HTTP")
        assert kwargs["timeout"] == 12
        assert kwargs["allow_redirects"] is False
        response = Response()
        response.status_code = 200
        return response

    monkeypatch.setattr(Session, "request", fake_request)
    TimeoutSession(12, before_request=before_request).request(
        b"GET", "https://data.alpaca.markets", timeout=None, allow_redirects=True
    )
    assert calls == ["budget", "HTTP"]


def test_DAT_04_transport_budget_fault_prevents_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def before_request() -> None:
        raise ProviderError("synthetic exhausted budget")

    def unexpected_request(*args: Any, **kwargs: Any) -> Response:
        pytest.fail("exhausted request budget must prevent I/O")

    monkeypatch.setattr(Session, "request", unexpected_request)
    with pytest.raises(ProviderError):
        TimeoutSession(12, before_request=before_request).request(
            "GET", "https://data.alpaca.markets"
        )


@pytest.mark.parametrize("code", [300, 301, 302, 307, 308, 399])
def test_R_06_transport_redirect_cannot_expose_account_headers(
    code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_request(*args: Any, **kwargs: Any) -> Response:
        response = Response()
        response.status_code = code
        return response

    monkeypatch.setattr(Session, "request", fake_request)
    with pytest.raises(ProviderError, match="redirect"):
        TimeoutSession(10).request("GET", "https://paper-api.alpaca.markets")


def test_DAT_04_verified_sdk_transport_replaces_session_and_disables_inner_retry() -> None:
    sdk = TradingClient("synthetic-key", "synthetic-secret", paper=True, raw_data=True)
    previous = sdk._session
    prepare_alpaca_client(sdk, Settings())
    assert sdk._session is not previous
    assert isinstance(sdk._session, TimeoutSession)
    assert sdk._retry == 0


def test_R_06_transport_fails_unverifiable_or_wrong_endpoint() -> None:
    class NoEndpoint:
        _base_url = 42

    with pytest.raises(ConfigurationError, match="endpoint"):
        prepare_alpaca_client(NoEndpoint(), Settings())  # type: ignore[arg-type]
    sdk = TradingClient("synthetic-key", "synthetic-secret", paper=False, raw_data=True)
    with pytest.raises(ConfigurationError):
        prepare_alpaca_client(sdk, Settings())


def test_R_06_settings_forgery_rejected_and_original_policy_detached() -> None:
    client = FakeClient()
    config = Settings()
    state = AlpacaBrokerState(
        config,
        FrozenClock(NOW),
        lambda equity, now: (equity, equity),
        client=client,
        known_symbols=frozenset({"AAPL"}),
    )
    object.__setattr__(config, "max_clock_skew_seconds", 9)
    client.broker_clock["timestamp"] = (NOW + timedelta(seconds=3)).isoformat()
    with pytest.raises(DataIntegrityError):
        state.snapshot(NOW)
    forged = Settings().model_copy(update={"paper_trading": False})
    with pytest.raises(ConfigurationError):
        AlpacaBrokerState(
            forged, FrozenClock(NOW), lambda equity, now: (equity, equity), client=client
        )
    assert client.call_count == 4


@pytest.mark.parametrize("symbols", [set(), ["AAPL"], frozenset({""}), frozenset({1})])
def test_R_02_broker_allowlist_is_immutable_and_explicit(symbols: Any) -> None:
    client = FakeClient()
    with pytest.raises(ConfigurationError):
        AlpacaBrokerState(
            Settings(),
            FrozenClock(NOW),
            lambda equity, now: (equity, equity),
            client=client,
            known_symbols=symbols,
        )
    assert client.call_count == 0


def test_R_02_empty_allowlist_requires_empty_account_holdings() -> None:
    client = FakeClient()
    state = AlpacaBrokerState(
        Settings(),
        FrozenClock(NOW),
        lambda equity, now: (equity, equity),
        client=client,
    )
    with pytest.raises(DataIntegrityError):
        state.snapshot(NOW)
    client.positions = []
    client.orders = []
    assert state.snapshot(NOW).positions == {}


@pytest.mark.parametrize("offset", [-3, 3])
def test_DAT_02_caller_time_must_match_injected_clock_before_any_read(offset: int) -> None:
    client = FakeClient()
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW + timedelta(seconds=offset))
    assert client.call_count == 0


def test_DAT_02_local_clock_moving_backward_during_read_rejected() -> None:
    class SequenceClock:
        def __init__(self) -> None:
            self.calls = 0

        def now(self) -> datetime:
            self.calls += 1
            return NOW if self.calls == 1 else NOW - timedelta(seconds=1)

    state = AlpacaBrokerState(
        Settings(),
        SequenceClock(),
        lambda equity, now: (equity, equity),
        client=FakeClient(),
        known_symbols=frozenset({"AAPL"}),
    )
    with pytest.raises(DataIntegrityError, match="backward"):
        state.snapshot(NOW)
    assert state.last_flags is None


@pytest.mark.parametrize("endpoint", [None, 1, LIVE_BROKER_ENDPOINT])
def test_R_06_resolved_endpoint_rechecked_before_each_snapshot(endpoint: Any) -> None:
    client = FakeClient()
    state = provider(client)
    client._base_url = endpoint
    with pytest.raises(ConfigurationError):
        state.snapshot(NOW)
    assert client.call_count == 0


def test_R_02_client_endpoint_property_fault_is_typed_at_startup() -> None:
    class FaultClient(FakeClient):
        def __getattribute__(self, name: str) -> Any:
            if name == "_base_url":
                raise RuntimeError("synthetic endpoint fault")
            return super().__getattribute__(name)

    with pytest.raises(ConfigurationError):
        provider(FaultClient())


def test_DAT_02_official_sdk_account_model_uuid_parses_current_fields() -> None:
    client = FakeClient()
    client.account = TradeAccount.model_validate(account_fixture())
    client.orders[0]["id"] = UUID("cf3c3e94-a8a8-4c1b-b48a-b664e717d5ae")
    state = provider(client)
    assert state.snapshot(NOW).account_id == account_fixture()["id"]
    assert state.last_flags is not None and state.last_flags.status == "ACTIVE"


@pytest.mark.parametrize("value", [None, 1, [], "account"])
def test_DAT_02_broker_payload_objects_are_required(value: Any) -> None:
    client = FakeClient()
    client.account = value
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize("value", ["", "   ", 1, None])
def test_DAT_02_account_identity_required(value: Any) -> None:
    client = FakeClient()
    client.account["id"] = value
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize("payload", [None, {}, (), "positions"])
def test_DAT_02_positions_must_be_complete_list(payload: Any) -> None:
    client = FakeClient()
    client.positions = payload
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize("field", ["avg_entry_price", "current_price"])
@pytest.mark.parametrize(
    "value", ["100.001", Decimal("100.001"), True, float("100"), "-1", "0", "Infinity", "NaN"]
)
def test_R_13_broker_prices_are_finite_positive_exact_cents(field: str, value: Any) -> None:
    client = FakeClient()
    client.positions[0][field] = value
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize("payload", [None, {}, (), "orders"])
def test_DAT_02_orders_must_be_complete_list(payload: Any) -> None:
    client = FakeClient()
    client.orders = payload
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize("value", ["", "   ", 1, None])
def test_DAT_02_order_identity_required(value: Any) -> None:
    client = FakeClient()
    client.orders[0]["id"] = value
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


def test_DAT_02_duplicate_order_identity_rejected() -> None:
    client = FakeClient()
    client.orders.append(dict(client.orders[0]))
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


@pytest.mark.parametrize(
    "timestamp", [None, "bad-clock", NOW.replace(tzinfo=None), "2026-10-04T15:00:00"]
)
def test_R_05_DAT_02_clock_requires_aware_iso8601(timestamp: Any) -> None:
    client = FakeClient()
    client.broker_clock["timestamp"] = timestamp
    with pytest.raises(DataIntegrityError):
        provider(client).snapshot(NOW)


def test_DAT_02_clock_accepts_aware_datetime() -> None:
    client = FakeClient()
    client.broker_clock["timestamp"] = NOW
    assert provider(client).snapshot(NOW).as_of == NOW


def test_DAT_04_each_broker_request_uses_shared_resilience_boundary(engine: Engine) -> None:
    state = SystemStateStore(engine, FrozenClock(NOW), ConsoleNotifier())
    reader = ResilientReader(
        FrozenClock(NOW), state, calls_per_minute=4, sleep=lambda seconds: None
    )
    client = FakeClient()
    broker = provider(client, reader=reader)
    broker.snapshot(NOW)
    assert client.call_count == 4
    with pytest.raises(ProviderError):
        broker.snapshot(NOW)
    assert client.call_count == 4
    assert state.current() == SystemState.HALTED
    assert broker.last_flags is None


def test_DAT_04_transient_broker_request_retried_before_next_account_read(engine: Engine) -> None:
    import requests

    class OnceTimeout(FakeClient):
        def get_account(self) -> object:
            self._check()
            if self.call_count == 1:
                raise requests.Timeout("synthetic timeout")
            return self.account

    state = SystemStateStore(engine, FrozenClock(NOW), ConsoleNotifier())
    delays: list[float] = []
    reader = ResilientReader(FrozenClock(NOW), state, sleep=delays.append)
    client = OnceTimeout()
    assert provider(client, reader=reader).snapshot(NOW).cash == Decimal("7000")
    assert client.call_count == 5
    assert len(delays) == 1
    assert state.current() == SystemState.RUNNING


def test_DAT_04_real_sdk_construction_requires_retry_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_sdk(*args: Any, **kwargs: Any) -> TradingClient:
        pytest.fail("no SDK constructor is permitted without a retry boundary")

    monkeypatch.setattr(broker_module, "TradingClient", unexpected_sdk)
    with pytest.raises(ConfigurationError, match="retry/circuit"):
        AlpacaBrokerState(Settings(), FrozenClock(NOW), lambda equity, now: (equity, equity))


def test_DAT_04_real_sdk_configuration_is_readonly_raw_paper_and_uses_reader(
    monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    observed: dict[str, Any] = {}

    class FakeSdkClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self._session = Session()
            self._retry = 3

    client = FakeSdkClient()

    def fake_sdk(**kwargs: Any) -> Any:
        observed.update(kwargs)
        return client

    monkeypatch.setattr(broker_module, "TradingClient", fake_sdk)
    state = SystemStateStore(engine, FrozenClock(NOW), ConsoleNotifier())
    reader = ResilientReader(FrozenClock(NOW), state, sleep=lambda seconds: None)
    broker = AlpacaBrokerState(
        Settings(
            broker_api_key=SecretStr("synthetic-key"),
            broker_secret_key=SecretStr("synthetic-secret"),
        ),
        FrozenClock(NOW),
        lambda equity, now: (equity, equity),
        reader=reader,
        known_symbols=frozenset({"AAPL"}),
    )
    assert observed["raw_data"] is True and observed["paper"] is True
    assert isinstance(client._session, TimeoutSession)
    assert client._retry == 0
    broker.snapshot(NOW)


def test_R_02_fake_broker_is_frozen_detached_and_revalidates_every_read() -> None:
    original = provider(FakeClient()).snapshot(NOW)
    flags = AccountFlags(
        trading_blocked=False,
        account_blocked=False,
        trade_suspended_by_user=False,
        status="ACTIVE",
    )
    fake = FakeBrokerState(original, flags)
    object.__setattr__(original, "equity", Decimal("0"))
    object.__setattr__(flags, "status", "BLOCKED")
    assert fake.snapshot(NOW).equity == Decimal("10000")
    assert fake.last_flags is not None and fake.last_flags.status == "ACTIVE"
    object.__setattr__(fake._snapshot, "equity", float("10000"))
    with pytest.raises(DataIntegrityError):
        fake.snapshot(NOW)
    assert fake.last_flags is None


def test_R_06_injected_broker_endpoint_must_exist_before_reads() -> None:
    client = FakeClient()
    client._base_url = None  # type: ignore[assignment]
    with pytest.raises(ConfigurationError, match="endpoint"):
        provider(client)
    assert client.call_count == 0


def test_DAT_04_injected_real_sdk_still_requires_retry_and_timeout_boundary(engine: Engine) -> None:
    sdk = TradingClient("synthetic-key", "synthetic-secret", paper=True, raw_data=True)
    with pytest.raises(ConfigurationError, match="retry/circuit"):
        AlpacaBrokerState(
            Settings(),
            FrozenClock(NOW),
            lambda equity, now: (equity, equity),
            client=sdk,
        )
    state = SystemStateStore(engine, FrozenClock(NOW), ConsoleNotifier())
    reader = ResilientReader(FrozenClock(NOW), state, sleep=lambda seconds: None)
    AlpacaBrokerState(
        Settings(),
        FrozenClock(NOW),
        lambda equity, now: (equity, equity),
        client=sdk,
        reader=reader,
    )
    assert isinstance(sdk._session, TimeoutSession)
    assert sdk._retry == 0


@pytest.mark.parametrize("fault_read", ["account", "positions", "orders", "clock"])
def test_DAT_04_each_broker_provider_fault_latches_shared_circuit(
    fault_read: str, engine: Engine
) -> None:
    class FaultClient(FakeClient):
        def get_account(self) -> object:
            if fault_read == "account":
                raise RuntimeError("synthetic account read fault")
            return super().get_account()

        def get_all_positions(self) -> object:
            if fault_read == "positions":
                raise RuntimeError("synthetic positions read fault")
            return super().get_all_positions()

        def get_orders(self, filter: GetOrdersRequest | None = None) -> object:
            if fault_read == "orders":
                raise RuntimeError("synthetic orders read fault")
            return super().get_orders(filter=filter)

        def get_clock(self) -> object:
            if fault_read == "clock":
                raise RuntimeError("synthetic clock read fault")
            return super().get_clock()

    state = SystemStateStore(engine, FrozenClock(NOW), ConsoleNotifier())
    reader = ResilientReader(FrozenClock(NOW), state, sleep=lambda seconds: None)
    broker = provider(FaultClient(), reader=reader)
    with pytest.raises(ProviderError):
        broker.snapshot(NOW)
    assert state.current() == SystemState.HALTED
    assert broker.last_flags is None


@pytest.mark.parametrize("fault", [RuntimeError, ValueError, TypeError, ArithmeticError])
def test_R_02_financial_mark_provider_faults_cannot_publish_snapshot(
    fault: type[Exception],
) -> None:
    def failing_marks(equity: Decimal, now: datetime) -> tuple[Decimal, Decimal]:
        raise fault("synthetic mark failure")

    broker = AlpacaBrokerState(
        Settings(),
        FrozenClock(NOW),
        failing_marks,
        client=FakeClient(),
        known_symbols=frozenset({"AAPL"}),
    )
    with pytest.raises((DataIntegrityError, ProviderError)):
        broker.snapshot(NOW)
    assert broker.last_flags is None


def test_R_02_settled_cash_provider_unexpected_fault_cannot_publish_snapshot() -> None:
    def failing_settled(now: datetime) -> Decimal:
        raise RuntimeError("synthetic trusted cash ledger fault")

    broker = provider(FakeClient(), settled_cash_provider=failing_settled)
    with pytest.raises(ProviderError):
        broker.snapshot(NOW)
    assert broker.last_flags is None


def test_R_02_broker_fault_audit_failure_remains_typed_and_no_flags_survive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenLogger:
        def error(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(
        broker_module, "structlog", SimpleNamespace(get_logger=lambda: BrokenLogger())
    )
    client = FakeClient()
    client.fault = RuntimeError("synthetic broker failure")
    broker = provider(client)
    with pytest.raises(DataIntegrityError, match="audit"):
        broker.snapshot(NOW)
    assert broker.last_flags is None


@pytest.mark.parametrize("typed", [False, True])
def test_R_07_broker_exception_traceback_suppresses_untrusted_sdk_bodies(typed: bool) -> None:
    secret = "synthetic SDK body credential never render"
    client = FakeClient()
    original = RuntimeError(secret)
    if typed:
        outer = ProviderError("static circuit failure")
        outer.__cause__ = original
        client.fault = outer
    else:
        client.fault = original
    try:
        provider(client).snapshot(NOW)
    except ProviderError as error:
        rendered = "".join(traceback.format_exception(error))
        assert secret not in rendered
        assert error.__cause__ is None and error.__suppress_context__
    else:
        pytest.fail("untrusted provider error must fail closed")


def test_R_07_broker_constructor_exception_traceback_suppresses_untrusted_sdk_detail() -> None:
    secret = "synthetic startup credential never render"

    class FaultClient(FakeClient):
        def __getattribute__(self, name: str) -> Any:
            if name == "_base_url":
                raise RuntimeError(secret)
            return super().__getattribute__(name)

    with pytest.raises(ConfigurationError) as captured:
        provider(FaultClient())
    assert secret not in "".join(traceback.format_exception(captured.value))


def test_R_07_transport_contract_failure_has_static_error_without_sdk_details() -> None:
    class BrokenSession(Session):
        def close(self) -> None:
            raise RuntimeError("synthetic session credential never render")

    client = SimpleNamespace(_session=BrokenSession(), _retry=3)
    with pytest.raises(ConfigurationError) as captured:
        configure_alpaca_transport(client)
    assert "synthetic session credential" not in "".join(traceback.format_exception(captured.value))


def test_R_07_endpoint_contract_failure_has_static_error_without_sdk_details() -> None:
    class BrokenEndpoint:
        @property
        def _base_url(self) -> str:
            raise RuntimeError("synthetic endpoint credential never render")

    with pytest.raises(ConfigurationError) as captured:
        prepare_alpaca_client(BrokenEndpoint(), Settings())  # type: ignore[arg-type]
    assert "synthetic endpoint credential" not in "".join(
        traceback.format_exception(captured.value)
    )


def test_R_02_fake_broker_rejects_forged_constructor_and_future_snapshot() -> None:
    snapshot = provider(FakeClient()).snapshot(NOW)
    flags = AccountFlags(
        trading_blocked=False,
        account_blocked=False,
        trade_suspended_by_user=False,
        status="ACTIVE",
    )
    with pytest.raises(DataIntegrityError):
        FakeBrokerState(snapshot.model_copy(update={"cash": float("100")}), flags)
    with pytest.raises(DataIntegrityError):
        FakeBrokerState(snapshot, flags.model_copy(update={"account_blocked": "false"}))
    fake = FakeBrokerState(snapshot, flags)
    with pytest.raises(DataIntegrityError):
        fake.snapshot(NOW - timedelta(seconds=1))
    assert fake.last_flags is None
