"""WZ-05/OPS-01: bounded HTTPS credential checks with no mutation routes."""

import asyncio
import json
import re
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from alpaca.trading.enums import AccountStatus
from pydantic import Field, SecretStr, model_validator

from backend.core.clock import Clock, SystemClock, ensure_utc
from backend.core.config import PAPER_BROKER_ENDPOINT, Settings
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.logging import register_secrets
from backend.domain.models import FrozenModel, Money
from backend.net.egress import EgressPolicy
from backend.net.http import make_client

if TYPE_CHECKING:
    from backend.execution.models import IntentBrokerSnapshot, IntentOrderView, IntentSnapshot


def _nonfinite(value: str) -> object:
    raise ValueError("JSON numbers must be finite")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object contains a duplicate key")
        result[key] = value
    return result


class PaperAccountCheck(FrozenModel):
    account_id: UUID
    status: AccountStatus
    buying_power: Money = Field(ge=0)
    equity: Money = Field(gt=0)
    currency: Literal["USD"]
    trading_blocked: bool = Field(strict=True)
    account_blocked: bool = Field(strict=True)
    trade_suspended_by_user: bool = Field(strict=True)


class PrivateChatCheck(FrozenModel):
    user_id: int = Field(strict=True, gt=0, le=2**63 - 1)
    chat_id: int = Field(strict=True, gt=0, le=2**63 - 1)
    display_name: str = Field(min_length=1, max_length=128, repr=False)

    @model_validator(mode="after")
    def binding(self) -> "PrivateChatCheck":
        if self.user_id != self.chat_id or not self.display_name.isprintable():
            raise ValueError("A private chat must identify the same user and chat")
        return self


class ReadChecksClient:
    def __init__(
        self,
        policy: EgressPolicy,
        clock: Clock | None = None,
        *,
        alpaca_request_hook: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.policy = policy
        self.clock = SystemClock() if clock is None else clock
        self._fred_requests: deque[datetime] = deque()
        self._fred_lock = asyncio.Lock()
        self._alpaca_request_hook = alpaca_request_hook

    async def _reserve_fred(self) -> None:
        # RT-07: failed requests also consume the 120/minute allowance.
        async with self._fred_lock:
            now = ensure_utc(self.clock.now())
            if self._fred_requests and now < self._fred_requests[-1]:
                raise DataIntegrityError("FRED rate-limit clock moved backward")
            while self._fred_requests and now - self._fred_requests[0] >= timedelta(minutes=1):
                self._fred_requests.popleft()
            if len(self._fred_requests) >= 120:
                raise ProviderError("FRED request allowance exhausted; wait before retrying")
            self._fred_requests.append(now)

    async def _get(
        self,
        purpose: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> object:
        async with make_client(
            purpose,
            policy=self.policy,
            allow_redirects=False,
            max_response_bytes=2_097_152,
            request_hook=self._alpaca_request_hook if purpose == "alpaca" else None,
        ) as client:
            response = await client.get(url, headers=headers, params=params)
        if response.status_code != 200:
            raise ProviderError("Read-only setup check was rejected by its provider")
        try:
            return json.loads(
                response.text,
                parse_float=Decimal,
                parse_constant=_nonfinite,
                object_pairs_hook=_unique_object,
            )
        except (ValueError, TypeError, RecursionError):
            raise DataIntegrityError("Read-only check returned malformed JSON") from None

    @staticmethod
    def _token(value: SecretStr) -> str:
        if not isinstance(value, SecretStr):
            raise ConfigurationError("Hidden credentials must remain masked")
        register_secrets(value)
        raw = value.get_secret_value()
        if (
            not raw
            or len(raw) > 4096
            or not raw.isascii()
            or any(char.isspace() or ord(char) < 32 for char in raw)
        ):
            raise ConfigurationError("Enter a nonempty valid hidden credential")
        return raw

    async def telegram(
        self,
        token: SecretStr,
        method: Literal["getMe", "getWebhookInfo", "getUpdates", "getChat"],
        *,
        chat_id: int | None = None,
    ) -> object:
        if not isinstance(method, str) or method not in {
            "getMe",
            "getWebhookInfo",
            "getUpdates",
            "getChat",
        }:
            raise ConfigurationError("Setup permits only the specified read-only Telegram methods")
        raw = self._token(token)
        if re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{20,256}", raw) is None:
            raise ConfigurationError("Telegram token format is invalid")
        params = {"timeout": "0", "limit": "100"} if method == "getUpdates" else None
        if method == "getChat":
            if type(chat_id) is not int or not 0 < chat_id <= 2**63 - 1:
                raise ConfigurationError("Private chat ID is required")
            params = {"chat_id": str(chat_id)}
        result = await self._get(
            "telegram", "https://api.telegram.org/bot" + raw + "/" + method, params=params
        )
        if not isinstance(result, dict) or result.get("ok") is not True or "result" not in result:
            raise DataIntegrityError("Telegram read-only check could not be verified")
        return result["result"]

    @staticmethod
    def broker_headers(key: SecretStr, secret: SecretStr) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": ReadChecksClient._token(key),
            "APCA-API-SECRET-KEY": ReadChecksClient._token(secret),
        }

    async def paper_account(self, key: SecretStr, secret: SecretStr) -> PaperAccountCheck:
        return await self._account(PAPER_BROKER_ENDPOINT, key, secret)

    async def open_orders(self, settings: Settings) -> object:
        """SEC-73: GET only, finite nested inventory for the panic report.

        VERIFY: https://docs.alpaca.markets/reference/getallorders-1
        A full 500-row page is not evidence of completeness.
        """
        settings = Settings.validated_copy(settings)
        if not settings.paper_trading and settings.execution_mode != "AUTO_LIVE":
            raise ConfigurationError(
                "Live order reads require the explicitly bound live configuration"
            )
        return await self._get(
            "alpaca",
            settings.broker_endpoint + "/v2/orders",
            headers=self.broker_headers(settings.broker_api_key, settings.broker_secret_key),
            params={"status": "open", "limit": "500", "nested": "true"},
        )

    async def account(
        self, settings: Settings, key: SecretStr, secret: SecretStr
    ) -> PaperAccountCheck:
        settings = Settings.validated_copy(settings)
        if settings.paper_trading:
            return await self.paper_account(key, secret)
        if not settings.paper_trading and settings.execution_mode != "AUTO_LIVE":
            raise ConfigurationError(
                "Live account reads require the explicitly bound live configuration"
            )
        return await self._account(settings.broker_endpoint, key, secret)

    async def _account(self, endpoint: str, key: SecretStr, secret: SecretStr) -> PaperAccountCheck:
        # VERIFY: https://alpaca.markets/sdks/python/api_reference/trading/account.html
        result = await self._get(
            "alpaca",
            endpoint + "/v2/account",
            headers=self.broker_headers(key, secret),
        )
        if not isinstance(result, dict):
            raise DataIntegrityError("Paper account response is unavailable")
        try:
            return PaperAccountCheck.model_validate(
                {
                    "account_id": UUID(str(result.get("id"))),
                    **{
                        name: result.get(name)
                        for name in (
                            "status",
                            "buying_power",
                            "equity",
                            "currency",
                            "trading_blocked",
                            "account_blocked",
                            "trade_suspended_by_user",
                        )
                    },
                }
            )
        except (ValueError, TypeError):
            raise DataIntegrityError("Paper account values could not be verified") from None

    async def asset(self, symbol: str, key: SecretStr, secret: SecretStr) -> None:
        if not isinstance(symbol, str) or re.fullmatch(r"[A-Z][A-Z0-9.]{0,14}", symbol) is None:
            raise ConfigurationError("Ticker format is invalid")
        result = await self._get(
            "alpaca",
            PAPER_BROKER_ENDPOINT + "/v2/assets/" + symbol,
            headers=self.broker_headers(key, secret),
        )
        if (
            not isinstance(result, dict)
            or result.get("symbol") != symbol
            or result.get("class") != "us_equity"
            or result.get("status") != "active"
            or result.get("tradable") is not True
        ):
            raise DataIntegrityError("Ticker is not an active tradable US stock or ETF")

    async def broker_clock(self, settings: Settings, key: SecretStr, secret: SecretStr) -> object:
        # VERIFY: https://alpaca.markets/sdks/python/api_reference/trading/clock.html
        settings = Settings.validated_copy(settings)
        if not settings.paper_trading and settings.execution_mode != "AUTO_LIVE":
            raise ConfigurationError(
                "Doctor reads require the matching explicitly configured endpoint"
            )
        return await self._get(
            "alpaca",
            settings.broker_endpoint + "/v2/clock",
            headers=self.broker_headers(key, secret),
        )

    async def broker_calendar(
        self, settings: Settings, key: SecretStr, secret: SecretStr, start: date, end: date
    ) -> object:
        # VERIFY: https://alpaca.markets/sdks/python/api_reference/trading/calendar.html
        settings = Settings.validated_copy(settings)
        if not settings.paper_trading and settings.execution_mode != "AUTO_LIVE":
            raise ConfigurationError(
                "Doctor reads require the matching explicitly configured endpoint"
            )
        if type(start) is date and type(end) is date and 0 <= (end - start).days <= 31:
            return await self._get(
                "alpaca",
                settings.broker_endpoint + "/v2/calendar",
                headers=self.broker_headers(key, secret),
                params={"start": start.isoformat(), "end": end.isoformat()},
            )
        raise ConfigurationError("Broker calendar request must be a bounded date window")

    async def fred(self, key: SecretStr) -> None:
        await self.fred_observations(key)

    async def fred_observations(self, key: SecretStr) -> dict[str, object]:
        raw = self._token(key)
        await self._reserve_fred()
        # VERIFY: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
        result = await self._get(
            "fred",
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": "VIXCLS",
                "file_type": "json",
                "api_key": raw,
                "limit": "1",
                "sort_order": "desc",
            },
        )
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("observations"), list)
            or len(result["observations"]) != 1
        ):
            raise DataIntegrityError("FRED credential check remains unverified")
        row = result["observations"][0]
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("date"), str)
            or not isinstance(row.get("value"), str)
        ):
            raise DataIntegrityError("FRED check response is malformed")
        try:
            date.fromisoformat(row["date"])
            value = Decimal(row["value"])
            if not value.is_finite() or value < 0:
                raise ValueError("Invalid FRED observation")
        except (ValueError, ArithmeticError):
            raise DataIntegrityError("FRED credential check remains unverified") from None
        return result


class IntentReadClient:
    """Fix G-a: GET-only surface; canonical HTTP and egress policy unchanged."""

    def __init__(
        self, settings: Settings, account: str, policy: EgressPolicy, clock: Clock
    ) -> None:
        from backend.execution.intent_resolution import IntentRefusal

        if not settings.paper_trading or settings.broker_endpoint != PAPER_BROKER_ENDPOINT:
            raise IntentRefusal("FIX_G_PAPER_ONLY")
        self.settings, self.account, self.policy, self.clock = settings, account, policy, clock

    async def _fetch(
        self, path: str, *, params: dict[str, str] | None = None, absence: bool = False
    ) -> object:
        from backend.execution.intent_resolution import IntentRefusal

        try:
            async with make_client(
                "alpaca", policy=self.policy, allow_redirects=False, max_response_bytes=2_097_152
            ) as client:
                response = await client.get(
                    self.settings.broker_endpoint + path,
                    headers=ReadChecksClient.broker_headers(
                        self.settings.broker_api_key, self.settings.broker_secret_key
                    ),
                    params=params,
                )
            if absence and response.status_code == 404:
                return None
            if response.status_code != 200:
                raise ValueError("Unverified response")
            return json.loads(
                response.text,
                parse_float=Decimal,
                parse_constant=_nonfinite,
                object_pairs_hook=_unique_object,
            )
        except Exception:
            raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED") from None

    async def _account(self) -> None:
        from backend.execution.intent_resolution import IntentRefusal

        raw = await self._fetch("/v2/account")
        if not isinstance(raw, dict) or raw.get("id") != self.account:
            raise IntentRefusal("FIX_G_ACCOUNT_MISMATCH")

    @staticmethod
    def _whole(value: object) -> int:
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError("Whole shares required")
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError("Whole shares required")
        return int(number)

    @staticmethod
    def _order(raw: object) -> "IntentOrderView":
        from backend.execution.models import IntentOrderView

        if not isinstance(raw, dict):
            raise ValueError("Order mapping required")
        return IntentOrderView.model_validate(
            {
                "order_id": raw["id"],
                "client_order_id": raw["client_order_id"],
                "symbol": raw["symbol"],
                "side": raw["side"],
                "qty": IntentReadClient._whole(raw["qty"]),
                "filled_qty": IntentReadClient._whole(raw["filled_qty"]),
                "status": raw["status"],
            }
        )

    async def open_orders(self) -> tuple["IntentOrderView", ...]:
        from backend.core.execution_policy import ORDER_HTTP_PATH
        from backend.execution.intent_resolution import IntentRefusal

        try:
            await self._account()
            raw = await self._fetch(
                ORDER_HTTP_PATH, params={"status": "open", "limit": "500", "nested": "true"}
            )
            if not isinstance(raw, list) or len(raw) >= 500:
                raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
            rows = []
            for root in raw:
                rows.append(self._order(root))
                legs = root.get("legs") or []
                if not isinstance(legs, list) or len(legs) > 2:
                    raise ValueError("Bounded nested orders required")
                rows.extend(self._order(leg) for leg in legs)
            if len({row.order_id for row in rows}) != len(rows):
                raise ValueError("Duplicate open orders")
            return tuple(rows)
        except IntentRefusal:
            raise
        except Exception:
            raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED") from None

    async def snapshot(self, intent: "IntentSnapshot") -> "IntentBrokerSnapshot":
        from backend.core.execution_policy import ORDER_HTTP_PATH
        from backend.execution.intent_resolution import IntentRefusal
        from backend.execution.models import IntentBrokerSnapshot, payload_instant

        try:
            await self._account()
            raw = await self._fetch(
                ORDER_HTTP_PATH + ":by_client_order_id",
                params={"client_order_id": intent.client_order_id},
                absence=True,
            )
            order = None if raw is None else self._order(raw)
            if order is not None and (
                order.client_order_id != intent.client_order_id
                or (order.symbol, order.side, order.qty) != (intent.symbol, intent.side, intent.qty)
            ):
                raise ValueError("Order identity differs")
            if intent.broker_order_id is not None:
                by_id = await self._fetch(
                    ORDER_HTTP_PATH + "/" + str(intent.broker_order_id), absence=True
                )
                if by_id is None or order is None:
                    raise IntentRefusal("FIX_G_CONTRADICTION")
                if self._order(by_id) != order or order.order_id != intent.broker_order_id:
                    raise ValueError("Bound identities differ")
            positions = await self._fetch("/v2/positions")
            if not isinstance(positions, list) or len(positions) >= 500:
                raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
            quantities: dict[str, int] = {}
            for position in positions:
                if (
                    not isinstance(position, dict)
                    or not isinstance(position.get("symbol"), str)
                    or position["symbol"] in quantities
                    or position.get("side") != "long"
                ):
                    raise ValueError("Unverified positions")
                quantities[position["symbol"]] = self._whole(position["qty"])
            end = self.clock.now()
            activities = await self._fetch(
                "/v2/account/activities",
                params={
                    "after": intent.submitted_at.isoformat(),
                    "until": end.isoformat(),
                    "direction": "asc",
                    "page_size": "100",
                },
            )
            if not isinstance(activities, list) or len(activities) >= 100:
                raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
            identities: list[str] = []
            filled = 0
            for activity in activities:
                if (
                    not isinstance(activity, dict)
                    or not isinstance(activity.get("id"), str)
                    or not 1 <= len(activity["id"]) <= 128
                    or activity["id"] in identities
                ):
                    raise ValueError("Unverified activities")
                identities.append(activity["id"])
                if activity.get("activity_type") == "FILL":
                    occurred = payload_instant(activity["transaction_time"])
                    if not intent.submitted_at <= occurred <= end:
                        raise ValueError("Activity outside intent lifetime")
                    activity_order = UUID(activity["order_id"])
                    if (order is not None and activity_order == order.order_id) or (
                        order is None and activity.get("symbol") == intent.symbol
                    ):
                        filled += self._whole(activity["qty"])
            opened = await self.open_orders()
            return IntentBrokerSnapshot(
                observed_at=self.clock.now(),
                order=order,
                not_found=raw is None,
                position_qty=quantities.get(intent.symbol, 0),
                fill_qty=filled,
                activity_ids=tuple(sorted(identities)),
                complete=True,
                open_orders=opened,
            )
        except IntentRefusal:
            raise
        except Exception:
            raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED") from None
