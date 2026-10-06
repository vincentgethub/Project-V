"""SEC-30: sole HTTP client factory, verified HTTPS and a whole-request deadline."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import httpx
from requests import Response, Session

from backend.core.errors import ConfigurationError, ProviderError
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
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", purpose):
            raise ConfigurationError("HTTP purpose must be a short nonsecret identifier")
        self.purpose = purpose
        self.policy = policy
        self.request_hook = request_hook
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
                    await response.aread()
                    next_request = response.next_request
                    if next_request is None:
                        return response
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
) -> GuardedAsyncClient:
    """SEC-30: the one application HTTP factory; transport injection is for tests."""
    return GuardedAsyncClient(
        purpose, policy=_require_policy(policy), transport=transport, request_hook=request_hook
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
