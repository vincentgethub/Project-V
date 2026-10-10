"""SEC-30: sole HTTP client factory, verified HTTPS and a whole-request deadline."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from requests import Response, Session
from telegram.request import BaseRequest, RequestData

from backend.core.errors import ConfigurationError, EgressDeniedError, ProviderError
from backend.core.execution_policy import ORDER_HTTP_PATH
from backend.net.egress import EgressPolicy

_policy: EgressPolicy | None = None
_WHOLE_REQUEST_SECONDS = 30.0
_PUBLIC_REDIRECT_HEADERS = frozenset({"accept", "accept-encoding", "user-agent"})


def configure_network(policy: EgressPolicy) -> None:
    """SEC-31: bind the validated startup policy; do not activate socket hooks."""
    global _policy
    if not isinstance(policy, EgressPolicy):
        raise ConfigurationError("network startup requires an audited egress policy")
    _policy = policy


def _require_policy(policy: EgressPolicy | None = None) -> EgressPolicy:
    selected = policy if policy is not None else _policy
    if not isinstance(selected, EgressPolicy):
        raise ConfigurationError("egress policy and ledger must be configured before HTTP I/O")
    return selected


class GuardedAsyncClient:
    """SEC-30: check each redirect and read the entire body inside 30 seconds."""

    def __init__(
        self,
        purpose: str,
        *,
        policy: EgressPolicy,
        transport: httpx.AsyncBaseTransport | None = None,
        request_hook: Callable[[], Awaitable[None]] | None = None,
        allow_redirects: bool = True,
        max_response_bytes: int = 33_554_432,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", purpose):
            raise ConfigurationError("HTTP purpose must be a short nonsecret identifier")
        if (
            type(allow_redirects) is not bool
            or type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= 33_554_432
        ):
            raise ConfigurationError("HTTP response and redirect bounds are invalid")
        self.purpose = purpose
        self.policy = policy
        self.request_hook = request_hook
        self.allow_redirects, self.max_response_bytes = allow_redirects, max_response_bytes
        self._client = httpx.AsyncClient(
            verify=True,
            trust_env=False,
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0),
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> GuardedAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """SEC-30: callers cannot override TLS, redirects, or timeouts."""
        if any(key in kwargs for key in {"timeout", "verify", "follow_redirects", "stream"}):
            raise ConfigurationError("HTTP safety controls cannot be overridden")
        self.policy.check_url(url, purpose=self.purpose)
        response: httpx.Response | None = None
        deadline = asyncio.get_running_loop().time() + _WHOLE_REQUEST_SECONDS
        try:
            async with asyncio.timeout(_WHOLE_REQUEST_SECONDS):
                request = self._client.build_request(method, url, **kwargs)
                for _redirect in range(21):
                    self.policy.check_url(str(request.url), purpose=self.purpose)
                    if self.request_hook is not None:
                        await self.request_hook()
                    response = await self._client.send(request, stream=True, follow_redirects=False)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > self.max_response_bytes:
                            raise ProviderError("HTTP response exceeds its bounded body size")
                        body.extend(chunk)
                    next_request = response.next_request
                    if next_request is None:
                        return httpx.Response(
                            response.status_code,
                            headers=response.headers,
                            content=bytes(body),
                            request=request,
                        )
                    if not self.allow_redirects:
                        self.policy.deny(
                            purpose=self.purpose, reason="authenticated API redirects prohibited"
                        )
                    self.policy.check_url(str(next_request.url), purpose=self.purpose)
                    if next_request.url.host != request.url.host:
                        if next_request.method not in {"GET", "HEAD"} or await next_request.aread():
                            self.policy.deny(
                                purpose=self.purpose,
                                reason="cross-host redirects cannot forward request bodies",
                            )
                        next_request.headers = httpx.Headers(
                            [
                                (key, value)
                                for key, value in next_request.headers.items()
                                if key.lower() in _PUBLIC_REDIRECT_HEADERS
                            ]
                        )
                    await response.aclose()
                    request = next_request
                raise ProviderError("HTTP redirect limit exceeded")
        except TimeoutError:
            raise ProviderError("HTTP whole-request deadline exceeded") from None
        except httpx.HTTPError:
            raise ProviderError("verified HTTP request failed") from None
        finally:
            if response is not None:
                try:
                    async with asyncio.timeout_at(deadline):
                        await response.aclose()
                except TimeoutError:
                    raise ProviderError("HTTP whole-request deadline exceeded") from None
                except httpx.HTTPError:
                    raise ProviderError("verified HTTP response cleanup failed") from None

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)


def make_client(
    purpose: str,
    *,
    policy: EgressPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    request_hook: Callable[[], Awaitable[None]] | None = None,
    allow_redirects: bool = True,
    max_response_bytes: int = 33_554_432,
) -> GuardedAsyncClient:
    """SEC-30: the one application HTTP factory; transport injection is for tests."""
    return GuardedAsyncClient(
        purpose,
        policy=_require_policy(policy),
        transport=transport,
        request_hook=request_hook,
        allow_redirects=allow_redirects,
        max_response_bytes=max_response_bytes,
    )


class SDKLLMClient(httpx.AsyncClient):
    """Verified openai3.24 legacy-httpx bridge; one bound POST endpoint only.

    SDK retries are disabled by the caller. Redirects are refused, the full
    decoded body is bounded and read inside the configured <=30s deadline.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int,
        policy: EgressPolicy,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise ConfigurationError("LLM timeout must be 1 through 30 seconds")
        self.policy = policy
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.deadline_seconds = timeout_seconds
        policy.check_url(self.endpoint, purpose="llm")
        super().__init__(
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(float(timeout_seconds)),
            transport=transport,
        )

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: Any = httpx.USE_CLIENT_DEFAULT,
        follow_redirects: Any = httpx.USE_CLIENT_DEFAULT,
    ) -> httpx.Response:
        self.policy.check_url(str(request.url), purpose="llm")
        if str(request.url) != self.endpoint or request.method != "POST":
            self.policy.deny(purpose="llm", reason="LLM request differs from bound endpoint")
        response: httpx.Response | None = None
        deadline = asyncio.get_running_loop().time() + self.deadline_seconds
        try:
            async with asyncio.timeout(self.deadline_seconds):
                response = await super().send(
                    request, stream=True, auth=auth, follow_redirects=False
                )
                if 300 <= response.status_code <= 399:
                    self.policy.deny(purpose="llm", reason="LLM SDK redirects are prohibited")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 2_097_152:
                        raise ProviderError("LLM response exceeds bounded body size")
                    body.extend(chunk)
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=bytes(body),
                    request=request,
                )
        except TimeoutError:
            raise httpx.ReadTimeout(
                "LLM whole-request deadline exceeded", request=request
            ) from None
        finally:
            if response is not None:
                try:
                    async with asyncio.timeout_at(deadline):
                        await response.aclose()
                except TimeoutError:
                    raise httpx.ReadTimeout(
                        "LLM response cleanup deadline exceeded", request=request
                    ) from None


def make_llm_sdk_client(
    base_url: str,
    timeout_seconds: int,
    *,
    policy: EgressPolicy,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SDKLLMClient:
    """All SDK HTTP construction stays in this sole, audited factory module."""
    return SDKLLMClient(base_url, timeout_seconds, _require_policy(policy), transport)


class ExactJSONResponse(Response):
    """R-04: preserve financial JSON decimals before alpaca-py sees them."""

    def json(self, **kwargs: Any) -> Any:
        kwargs["parse_float"] = Decimal
        return super().json(**kwargs)


class TimeoutSession(Session):
    """SEC-30/R-08: centrally constructed GET-only Alpaca SDK transport.

    SDK requests do not follow redirects. Their connect/read timeouts are
    bounded, and the application retry boundary supplies its request budget.
    Application HTTP uses make_client for the whole-body 30-second deadline.
    """

    def __init__(
        self,
        timeout_seconds: int,
        *,
        before_request: Callable[[], None] | None = None,
        policy: EgressPolicy | None = None,
    ) -> None:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
            raise ConfigurationError("request timeout must be 1 through 60 seconds")
        super().__init__()
        self._timeout_seconds = timeout_seconds
        self._before_request = before_request
        self._policy = policy
        self.trust_env = False

    def request(self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any) -> Response:
        if method.upper() not in {"GET", b"GET"}:
            raise ProviderError("read-only Alpaca transport rejects non-GET requests")
        if isinstance(url, bytes):
            try:
                url = url.decode("ascii")
            except UnicodeError:
                _require_policy(self._policy).deny(
                    purpose="alpaca", reason="invalid HTTPS destination"
                )
        policy = _require_policy(self._policy)
        policy.check_url(url, purpose="alpaca")
        kwargs["timeout"] = (min(5, self._timeout_seconds), min(20, self._timeout_seconds))
        kwargs["allow_redirects"] = False
        kwargs["verify"] = True
        if self._before_request is not None:
            self._before_request()
        response = super().request(method, url, *args, **kwargs)
        if 300 <= response.status_code <= 399:
            response.close()
            policy.deny(purpose="alpaca", reason="SDK redirects are prohibited")
        exact = ExactJSONResponse()
        exact.__dict__.update(response.__dict__)
        return exact


class OrderSession(TimeoutSession):
    """AX-12/SEC-30: exact bound order transport, available only to the executor.

    One physical request, verified TLS, no redirects/proxies or implicit retries.
    POST is only the bracket/exit/repair order route; DELETE is only one UUID.
    GET remains available for account and reconciliation reads. No money route.
    """

    def __init__(
        self,
        endpoint: str,
        timeout_seconds: int,
        *,
        policy: EgressPolicy,
        before_request: Callable[[], None] | None = None,
    ) -> None:
        if endpoint not in {"https://paper-api.alpaca.markets", "https://api.alpaca.markets"}:
            raise ConfigurationError("Order transport requires the exact Alpaca endpoint")
        self.endpoint = endpoint
        super().__init__(timeout_seconds, before_request=before_request, policy=policy)

    def request(self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any) -> Response:
        if not isinstance(method, str) or not isinstance(url, str):
            raise ProviderError("Order transport requires canonical text method and URL")
        method = method.upper()
        parts = urlsplit(url)
        origin = parts.scheme + "://" + parts.netloc
        if origin != self.endpoint or parts.fragment or parts.username or parts.password:
            raise ProviderError("Order destination differs from the bound account endpoint")
        allowed = method == "GET" and parts.path in {
            "/v2/account",
            "/v2/positions",
            ORDER_HTTP_PATH,
            ORDER_HTTP_PATH + ":by_client_order_id",
        }
        if (
            method in {"GET", "DELETE"}
            and parts.path.startswith(ORDER_HTTP_PATH + "/")
            and not parts.query
        ):
            suffix = parts.path[len(ORDER_HTTP_PATH) + 1 :]
            try:
                allowed = str(UUID(suffix)) == suffix
            except ValueError:
                allowed = False
        if method == "POST":
            allowed = parts.path == ORDER_HTTP_PATH and not parts.query
        if method == "DELETE" and parts.path.startswith(ORDER_HTTP_PATH + "/") and not parts.query:
            suffix = parts.path[len(ORDER_HTTP_PATH) + 1 :]
            try:
                allowed = str(UUID(suffix)) == suffix
            except ValueError:
                allowed = False
        if not allowed:
            raise ProviderError("Order transport refuses this method or route")
        # Pinned SDK sets params=None on a DELETE. Permit precisely that empty
        # shape, while refusing a query or payload that could change its target.
        if method == "DELETE" and kwargs.get("params") is None:
            kwargs.pop("params", None)
        forbidden = {"files", "data", "stream", "proxies", "auth", "cert"}
        if method != "GET":
            forbidden.add("params")
        if args or any(key in kwargs for key in forbidden):
            raise ProviderError("Order request cannot override transport or payload controls")
        policy = _require_policy(self._policy)
        policy.check_url(url, purpose="alpaca-order")
        kwargs["timeout"] = (min(5, self._timeout_seconds), min(20, self._timeout_seconds))
        kwargs["allow_redirects"], kwargs["verify"], kwargs["stream"] = False, True, True
        if self._before_request is not None:
            self._before_request()
        deadline = time.monotonic() + min(30, self._timeout_seconds)
        response = Session.request(self, method, url, **kwargs)
        try:
            if 300 <= response.status_code <= 399:
                policy.deny(purpose="alpaca-order", reason="Order redirects are prohibited")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if time.monotonic() > deadline or len(body) + len(chunk) > 1048576:
                    raise ProviderError("Order response exceeds its deadline or body bound")
                body.extend(chunk)
            if time.monotonic() > deadline:
                raise ProviderError("Order response exceeded its whole-request deadline")
            exact = ExactJSONResponse()
            exact.__dict__.update(response.__dict__)
            exact._content = bytes(body)
            exact.__dict__["_content_consumed"] = True
            return exact
        finally:
            response.close()


def make_order_session(
    endpoint: str,
    timeout_seconds: int,
    *,
    policy: EgressPolicy,
    before_request: Callable[[], None] | None = None,
) -> OrderSession:
    """AX-10: the AST grants this capability only to alpaca_executor.py."""
    return OrderSession(endpoint, timeout_seconds, policy=policy, before_request=before_request)


_TELEGRAM_METHODS = frozenset(
    {
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "deleteWebhook",
        "sendMessage",
        "editMessageText",
        "editMessageReplyMarkup",
        "answerCallbackQuery",
        "leaveChat",
        "getChat",
        "sendDocument",
    }
)


class TelegramRequest(BaseRequest):
    """Pinned PTB BaseRequest adapter: TLS, no proxy/redirects, bounded body.

    Telegram performs POSTs even for read-only API operations. The inventory is
    limited to polling and private alert UX; files and webhooks cannot be sent.
    """

    def __init__(
        self,
        token: str,
        policy: EgressPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        document_chats: tuple[int, ...] = (),
    ) -> None:
        super().__init__()
        if not token.strip() or policy.ledger is None:
            raise ConfigurationError("GD-05: Telegram needs a token and audited egress policy")
        self._prefix = "https://api.telegram.org/bot" + token + "/"
        self.policy = policy
        if not isinstance(document_chats, tuple) or any(
            type(chat) is not int or chat <= 0 for chat in document_chats
        ):
            raise ConfigurationError("XK-08: private document recipients required")
        self.document_chats = document_chats
        self._client = httpx.AsyncClient(
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(connect=5, read=25, write=20, pool=5),
            transport=transport,
        )

    @property
    def read_timeout(self) -> float:
        return 25.0

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        await self._client.aclose()

    async def do_request(
        self,
        url: str,
        method: str,
        request_data: RequestData | None = None,
        read_timeout: Any = None,
        write_timeout: Any = None,
        connect_timeout: Any = None,
        pool_timeout: Any = None,
    ) -> tuple[int, bytes]:
        self.policy.check_url(url, purpose="telegram_api")
        if (
            not url.startswith(self._prefix)
            or url[len(self._prefix) :] not in _TELEGRAM_METHODS
            or method not in {"GET", "POST"}
            or (
                request_data is not None
                and request_data.multipart_data
                and not url.endswith("sendDocument")
            )
        ):
            self.policy.deny(purpose="telegram_api", reason="Telegram method/path/files prohibited")
        data = None if request_data is None else request_data.json_parameters
        files = None
        if url.endswith("sendDocument"):
            from backend.ops.html_report import validate_report

            uploads = {} if request_data is None else request_data.multipart_data
            if (
                data is None
                or len(uploads) != 1
                or set(data) - {"chat_id", "document", "disable_content_type_detection"}
            ):
                self.policy.deny(
                    purpose="telegram_api",
                    reason="only generated private HTML reports may be uploaded",
                )
            try:
                upload_part, content = next(iter(uploads.items()))
                filename, payload, mime = content
                if (
                    filename != "latest.html"
                    or mime != "text/html"
                    or not isinstance(payload, bytes)
                    or not (
                        (upload_part == "document" and "document" not in data)
                        or data.get("document") == "attach://" + upload_part
                    )
                    or str(int(data["chat_id"])) != data["chat_id"]
                    or int(data["chat_id"]) not in self.document_chats
                ):
                    raise ValueError("document shape or recipient differs")
                validate_report(payload)
                files = uploads
            except Exception:
                self.policy.deny(
                    purpose="telegram_api", reason="document bytes or recipient are not approved"
                )
        # PTB bootstrap clears an already-empty webhook, with no update loss.
        if url.endswith("deleteWebhook") and data and data.get("drop_pending_updates") == "true":
            self.policy.deny(purpose="telegram_api", reason="cannot discard pending owner updates")
        try:
            async with asyncio.timeout(30):
                async with self._client.stream(
                    method, url, data=data, files=files, follow_redirects=False
                ) as response:
                    if 300 <= response.status_code < 400:
                        self.policy.deny(
                            purpose="telegram_api", reason="Telegram redirects prohibited"
                        )
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 2 * 1024 * 1024:
                            raise ProviderError("GD-05: Telegram response exceeds its boundary")
                    return response.status_code, bytes(body)
        except EgressDeniedError:
            raise
        except Exception:
            raise ProviderError("GD-05: Telegram request failed or exceeded its deadline") from None
