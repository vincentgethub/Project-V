"""R-02/R-06/R-08/CMP-06/DAT-02: read-only broker state projection."""

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

import structlog
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest
from pydantic import BaseModel, ValidationError
from requests import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings, assert_broker_endpoint
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError, SafetyError
from backend.core.money import MoneyInput, decimal_money, validate_cent_price
from backend.domain.models import AccountFlags, PortfolioSnapshot
from backend.net.http import ExactJSONResponse as ExactJSONResponse
from backend.net.http import TimeoutSession as TimeoutSession

MarksProvider = Callable[[Decimal, datetime], tuple[Decimal, Decimal]]
SettledCashProvider = Callable[[datetime], Decimal]
ReadT = TypeVar("ReadT")


class ReadExecutor(Protocol):
    """DAT-04: inject the durable retry/circuit boundary without import cycles."""

    def run(self, operation: Callable[[], ReadT], *, budget_request: bool = True) -> ReadT:
        """DAT-04: count and execute one external request or latch HALTED."""
        raise NotImplementedError("read executor must supply run")


class BrokerStateProvider(Protocol):
    """R-08: a state source has no order or money-movement capability."""

    last_flags: AccountFlags | None

    def snapshot(self, now: datetime) -> PortfolioSnapshot:
        """R-03/R-05: read and project a snapshot using injected time."""
        raise NotImplementedError("BrokerStateProvider must supply snapshot")


class ReadOnlyTradingClient(Protocol):
    """R-08: expose only the four supported account-state reads."""

    def get_account(self) -> object:
        """CMP-06: read current account balances and restriction flags."""
        raise NotImplementedError("client must supply get_account")

    def get_all_positions(self) -> object:
        """R-01: read all current positions."""
        raise NotImplementedError("client must supply get_all_positions")

    def get_orders(self, filter: GetOrdersRequest | None = None) -> object:
        """CRO-03: read pending orders for exposure accounting."""
        raise NotImplementedError("client must supply get_orders")

    def get_clock(self) -> object:
        """DAT-02: read the broker clock for skew validation."""
        raise NotImplementedError("client must supply get_clock")


def configure_alpaca_transport(
    client: object,
    timeout_seconds: int = 30,
    *,
    before_request: Callable[[], None] | None = None,
) -> None:
    """R-08/DAT-04: configure bounded GET-only SDK transport and no inner retry."""
    # VERIFY: https://github.com/alpacahq/alpaca-py/blob/master/alpaca/common/rest.py
    try:
        old_session = getattr(client, "_session", None)
        if not isinstance(old_session, Session) or not hasattr(client, "_retry"):
            raise ConfigurationError("Alpaca SDK transport contract has changed")
        session = TimeoutSession(timeout_seconds, before_request=before_request)
        old_session.close()
        transport = cast(Any, client)
        transport._session = session
        transport._retry = 0
    except SafetyError as exc:
        raise exc from None
    except Exception:
        raise ConfigurationError("Alpaca SDK transport could not be safely configured") from None


def prepare_alpaca_client(client: TradingClient, config: Settings) -> None:
    """R-06/DAT-04: bind verified SDK internals to bounded read-only transport.

    alpaca-py currently has no public timeout argument. Private attributes are
    inspected against the pinned source and guarded here; SDK drift fails loudly.
    Provider retries belong to the injected outer circuit-breaker boundary.
    """
    # VERIFY: https://github.com/alpacahq/alpaca-py/blob/master/alpaca/common/rest.py
    try:
        base = getattr(client, "_base_url", None)
        endpoint = getattr(base, "value", base)
        if not isinstance(endpoint, str):
            raise ConfigurationError("Alpaca client resolved endpoint is unavailable")
        assert_broker_endpoint(config, endpoint)
        configure_alpaca_transport(client, config.request_timeout_seconds)
    except SafetyError as exc:
        raise exc from None
    except Exception:
        raise ConfigurationError("Alpaca client endpoint could not be safely verified") from None


class AlpacaBrokerState:
    """R-08/CMP-06: read account, positions, orders, and clock via alpaca-py.

    Account type is an explicit operator configuration, not inferred from buying
    power. Settled cash defaults to zero because the current account endpoint
    does not expose a verifiable settled-cash balance. Persistent drawdown marks
    and any trusted settled cash must come from injected ledger-backed providers.
    """

    def __init__(
        self,
        config: Settings,
        clock: Clock,
        marks_provider: MarksProvider,
        settled_cash_provider: SettledCashProvider | None = None,
        client: ReadOnlyTradingClient | None = None,
        *,
        known_symbols: frozenset[str] | None = None,
        reader: ReadExecutor | None = None,
    ) -> None:
        """R-06/R-08: verify the resolved endpoint before enabling reads."""
        self.last_flags: AccountFlags | None = None
        try:
            policy = config.model_dump(mode="python")
            if (
                not config.telegram_allowed_user_ids
                and "telegram_allowed_user_ids" not in config.model_fields_set
            ):
                del policy["telegram_allowed_user_ids"]
            self._config = Settings.model_validate(policy)
            self._clock = clock
            self._marks = marks_provider
            self._settled = settled_cash_provider
            self._reader = reader
            if known_symbols is not None and (
                not isinstance(known_symbols, frozenset)
                or any(
                    not isinstance(symbol, str) or not symbol.strip() for symbol in known_symbols
                )
            ):
                raise ConfigurationError(
                    "broker instrument allowlist must be an immutable symbol set"
                )
            self._known = frozenset() if known_symbols is None else known_symbols
            if client is None:
                if reader is None:
                    raise ConfigurationError(
                        "real broker reads require a durable retry/circuit boundary"
                    )
                # VERIFY: https://alpaca.markets/sdks/python/api_reference/trading_api.html
                sdk = TradingClient(
                    api_key=self._config.broker_api_key.get_secret_value(),
                    secret_key=self._config.broker_secret_key.get_secret_value(),
                    paper=self._config.paper_trading,
                    raw_data=True,
                )
                prepare_alpaca_client(sdk, self._config)
                self._client = cast(ReadOnlyTradingClient, sdk)
            else:
                base = getattr(client, "_base_url", None)
                endpoint = getattr(base, "value", base)
                if not isinstance(endpoint, str):
                    raise ConfigurationError("injected broker endpoint is unverifiable")
                assert_broker_endpoint(self._config, endpoint)
                if isinstance(client, TradingClient):
                    if reader is None:
                        raise ConfigurationError(
                            "real broker reads require a durable retry/circuit boundary"
                        )
                    prepare_alpaca_client(client, self._config)
                self._client = client
        except SafetyError as exc:
            raise exc from None
        except Exception:
            raise ConfigurationError("broker client could not be safely initialized") from None

    def snapshot(self, now: datetime) -> PortfolioSnapshot:
        """R-02/CMP-06/DAT-02/DAT-04: validate every field before exposing state.

        Every broker call passes independently through the injected request
        reader. The snapshot retains its read-start timestamp; a slow read cannot
        present old balances as newly observed. The surrounding ReadBoundary
        audits output freshness, financial limits, and account flags.
        """
        self.last_flags = None
        try:
            instant = ensure_utc(now)
            local_start = ensure_utc(self._clock.now())
            self._validate_skew(instant, local_start)
            base = getattr(self._client, "_base_url", None)
            endpoint = getattr(base, "value", base)
            if not isinstance(endpoint, str):
                raise ConfigurationError("broker endpoint became unverifiable")
            assert_broker_endpoint(self._config, endpoint)
            # VERIFY: https://alpaca.markets/sdks/python/api_reference/trading/account.html
            account = _mapping(self._read(self._client.get_account), "account")
            positions_raw = self._read(self._client.get_all_positions)
            # VERIFY: https://alpaca.markets/sdks/python/api_reference/trading/orders.html
            orders_raw = self._read(
                lambda: self._client.get_orders(
                    filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500),
                ),
            )
            # VERIFY: https://alpaca.markets/sdks/python/api_reference/trading/clock.html
            clock = _mapping(self._read(self._client.get_clock), "clock")
            server_time = _timestamp(clock.get("timestamp"))
            local_end = ensure_utc(self._clock.now())
            if local_end < local_start:
                raise DataIntegrityError("local clock moved backward during broker reads")
            self._validate_skew(server_time, local_end)
            if account.get("currency") != "USD":
                raise DataIntegrityError("broker account currency must be USD")
            account_id = account.get("id")
            if isinstance(account_id, UUID):
                account_id = str(account_id)
            if not isinstance(account_id, str) or not account_id.strip():
                raise DataIntegrityError("broker account ID is required")
            flags = AccountFlags.model_validate(
                {
                    "status": account.get("status"),
                    "trading_blocked": account.get("trading_blocked"),
                    "account_blocked": account.get("account_blocked"),
                    "trade_suspended_by_user": account.get("trade_suspended_by_user"),
                }
            )
            equity = _money(account.get("equity"))
            cash = _money(account.get("cash"))
            _money(account.get("buying_power"))
            positions = self._positions(positions_raw)
            orders = self._orders(orders_raw)
            high_water_mark, day_start_equity = self._marks(equity, instant)
            settled = Decimal("0") if self._settled is None else _money(self._settled(instant))
            snapshot = PortfolioSnapshot.model_validate(
                {
                    "account_id": account_id,
                    "account_type": self._config.broker_account_type,
                    "as_of": instant,
                    "equity": equity,
                    "cash": cash,
                    "settled_cash": settled,
                    "positions": positions,
                    "open_orders": orders,
                    "high_water_mark": _money(high_water_mark),
                    "day_start_equity": _money(day_start_equity),
                }
            )
            self.last_flags = flags
            return snapshot
        except SafetyError as exc:
            raise exc from None
        except (ValidationError, ValueError, TypeError):
            raise DataIntegrityError("broker state response failed schema validation") from None
        except Exception as exc:
            try:
                structlog.get_logger().error(
                    "broker_state_read_failed", error_type=type(exc).__name__
                )
            except Exception:
                raise DataIntegrityError("broker state fault audit failed") from None
            raise ProviderError("broker state cannot be verified") from None

    def _read(self, operation: Callable[[], ReadT]) -> ReadT:
        """DAT-04: official SDK I/O must use the external circuit boundary."""
        return operation() if self._reader is None else self._reader.run(operation)

    def _validate_skew(self, observed: datetime, local: datetime) -> None:
        """DAT-02/R-05: caller and broker clocks share the same skew bound."""
        if abs(observed - local) > timedelta(seconds=self._config.max_clock_skew_seconds):
            raise DataIntegrityError("broker clock skew exceeds the configured limit")

    def _positions(self, raw: object) -> dict[str, dict[str, object]]:
        """R-01/R-02: reject fractional, short, unknown, or duplicate positions."""
        if not isinstance(raw, list):
            raise DataIntegrityError("broker positions must be a complete list")
        result: dict[str, dict[str, object]] = {}
        for item in raw:
            position = _mapping(item, "position")
            symbol = self._symbol(position.get("symbol"))
            if symbol in result:
                raise DataIntegrityError("broker returned duplicate position symbols")
            if position.get("side") != "long" or position.get("asset_class") != "us_equity":
                raise DataIntegrityError("broker position must be a long US equity")
            result[symbol] = {
                "qty": _whole_qty(position.get("qty")),
                "avg_cost": _price(position.get("avg_entry_price")),
                "last_price": _price(position.get("current_price")),
            }
        return result

    def _orders(self, raw: object) -> list[dict[str, object]]:
        """R-01/CRO-03: count unfilled LIMIT quantities and reject truncation."""
        if not isinstance(raw, list) or len(raw) >= 500:
            raise DataIntegrityError("open-order list is invalid or possibly truncated")
        result: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in raw:
            order = _mapping(item, "order")
            symbol = self._symbol(order.get("symbol"))
            order_id = order.get("id")
            if isinstance(order_id, UUID):
                order_id = str(order_id)
            if not isinstance(order_id, str) or not order_id.strip() or order_id in seen:
                raise DataIntegrityError("open orders require distinct IDs")
            seen.add(order_id)
            if order.get("type") != "limit" or order.get("asset_class") != "us_equity":
                raise DataIntegrityError("open order must be a US-equity LIMIT order")
            if order.get("status") not in {
                "new",
                "accepted",
                "pending_new",
                "partially_filled",
                "pending_cancel",
                "pending_replace",
                "held",
                "accepted_for_bidding",
                "stopped",
                "suspended",
            }:
                raise DataIntegrityError("open order status is not verifiably pending")
            side = order.get("side")
            if side not in {"buy", "sell"}:
                raise DataIntegrityError("open order side is unknown")
            qty = _whole_qty(order.get("qty"))
            filled = _whole_qty(order.get("filled_qty"), allow_zero=True)
            if filled >= qty:
                raise DataIntegrityError("open order remaining quantity must be positive")
            result.append(
                {
                    "symbol": symbol,
                    "side": str(side).upper(),
                    "qty": qty - filled,
                    "limit_price": _price(order.get("limit_price")),
                }
            )
        return result

    def _symbol(self, value: object) -> str:
        """R-02: account holdings must resolve to the configured instrument set."""
        if not isinstance(value, str) or value not in self._known:
            raise DataIntegrityError("broker symbol is unknown to the instrument allowlist")
        return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    """R-02: normalize raw or official SDK model responses at the boundary."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, BaseModel):
        return value.model_dump()
    raise DataIntegrityError(f"broker {label} response is not an object")


def _money(value: object) -> Decimal:
    """R-04: Alpaca financial fields are decimal strings, never floats."""
    return decimal_money(cast(MoneyInput, value))


def _price(value: object) -> Decimal:
    """R-04/R-13: parse exact vendor text then reject sub-cent prices."""
    return validate_cent_price(_money(value))


def _whole_qty(value: object, *, allow_zero: bool = False) -> int:
    """R-01/R-04: refuse fractional or nonpositive share quantities."""
    quantity = _money(value)
    if (
        quantity != quantity.to_integral_value()
        or quantity < 0
        or (quantity == 0 and not allow_zero)
    ):
        raise DataIntegrityError("broker quantity must be positive whole shares")
    return int(quantity)


def _timestamp(value: object) -> datetime:
    """R-05/DAT-02: parse the broker's aware ISO8601 clock timestamp."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise DataIntegrityError("broker clock timestamp is malformed") from exc
    return ensure_utc(cast(datetime, value))


class FakeBrokerState:
    """R-08: immutable, network-free broker fixture source."""

    def __init__(self, snapshot: PortfolioSnapshot, flags: AccountFlags) -> None:
        """R-03: require explicit account flags rather than assume unrestricted."""
        try:
            self._snapshot = PortfolioSnapshot.model_validate(snapshot)
            self._flags = AccountFlags.model_validate(flags)
            self.last_flags: AccountFlags | None = self._flags
        except Exception:
            raise DataIntegrityError("fake broker fixture failed schema validation") from None

    def snapshot(self, now: datetime) -> PortfolioSnapshot:
        """R-05/DAT-02: return injected state only when its time is verifiable."""
        self.last_flags = None
        try:
            snapshot = PortfolioSnapshot.model_validate(self._snapshot)
            flags = AccountFlags.model_validate(self._flags)
            if snapshot.as_of > ensure_utc(now):
                raise DataIntegrityError("fake snapshot is in the future")
            self.last_flags = flags
            return snapshot
        except SafetyError as exc:
            raise exc from None
        except Exception:
            raise DataIntegrityError("fake broker fixture failed schema validation") from None
