"""FA-02/09/DAT-11: public SEC evidence, exact JSON and shared request pacing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from backend.core.clock import Clock, ensure_utc
from backend.core.config import FundamentalsConfig, Settings
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError, SafetyError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.data.earnings_reports import EarningsReport
from backend.domain.models import FrozenModel, UTCDateTime, validate_symbol
from backend.net.http import GuardedAsyncClient, make_client

# VERIFY: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
_TICKERS = "https://www.sec.gov/files/company_tickers.json"
_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_MAX_BYTES = 32 * 1024 * 1024
RequestHook = Callable[[], Awaitable[None]]
ClientFactory = Callable[[RequestHook], GuardedAsyncClient]
Sleep = Callable[[float], Awaitable[None]]


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate SEC JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("nonfinite SEC JSON constant")


def exact_json(raw: bytes) -> dict[str, Any]:
    """FA-02/R-04: SEC dollar facts never pass through binary floats."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= _MAX_BYTES:
            raise ValueError("SEC response byte bound")
        result = json.loads(
            raw, parse_float=Decimal, parse_constant=_constant, object_pairs_hook=_object
        )
        if not isinstance(result, dict):
            raise ValueError("SEC object required")
        return result
    except Exception:
        raise DataIntegrityError("FA-02: SEC payload is malformed or exceeds its bounds") from None


class SecPayload(FrozenModel):
    """FA-02: immutable raw provenance; parsing returns a detached exact object."""

    kind: Literal["TICKERS", "COMPANYFACTS", "SUBMISSIONS"]
    cik: str | None = Field(default=None, pattern=r"^[0-9]{10}$")
    fetched_at: UTCDateTime
    raw: bytes = Field(strict=True, min_length=1, max_length=_MAX_BYTES, repr=False)
    data_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_provenance(self) -> Self:
        if hashlib.sha256(self.raw).hexdigest() != self.data_sha256:
            raise ValueError("SEC raw evidence differs from its SHA-256")
        payload = exact_json(self.raw)
        if self.kind == "TICKERS":
            if self.cik is not None:
                raise ValueError("ticker map has no issuer identity")
        else:
            raw_cik = payload.get("cik")
            if (
                isinstance(raw_cik, bool)
                or not isinstance(raw_cik, (int, str))
                or re.fullmatch(r"[0-9]{1,10}", str(raw_cik)) is None
                or self.cik != str(raw_cik).zfill(10)
            ):
                raise ValueError("SEC response issuer differs from the requested CIK")
        return self

    def parsed(self) -> dict[str, Any]:
        return exact_json(SecPayload.model_validate(self).raw)


class SecRequestPacer:
    """FA-02: at most eight physical HTTP requests per second, no bursts."""

    def __init__(self, clock: Clock, *, sleep: Sleep = asyncio.sleep) -> None:
        self.clock, self.sleep = clock, sleep
        self._last: datetime | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = ensure_utc(self.clock.now())
            if self._last is not None:
                if now < self._last:
                    raise DataIntegrityError("FA-02: SEC request clock moved backward")
                wait = self._last + timedelta(microseconds=125000) - now
                if wait > timedelta(0):
                    await self.sleep(wait.total_seconds())
                    now = ensure_utc(self.clock.now())
                    if now < self._last + timedelta(microseconds=125000):
                        raise DataIntegrityError("FA-02: SEC pacing clock did not advance")
            self._last = now


class SecEdgarProvider:
    """FA-02/09: contact required; seven-day map and 24-hour raw evidence cache.

    Cache entries are immutable bytes scoped to this running provider. Restart
    fetches public evidence again; no mutable cache file is implicitly trusted.
    Facts are filtered against the research as-of instant by pure computation.
    """

    def __init__(
        self,
        settings: Settings,
        ledger: Ledger,
        *,
        config: FundamentalsConfig | None = None,
        client_factory: ClientFactory | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        try:
            payload = settings.model_dump()
            if (
                not settings.telegram_allowed_user_ids
                and "telegram_allowed_user_ids" not in settings.model_fields_set
            ):
                payload.pop("telegram_allowed_user_ids")
            checked = Settings.model_validate(payload)
            if checked.sec_user_agent is None:
                raise ValueError("SEC contact required")
            self.user_agent = checked.sec_user_agent
            self.config = FundamentalsConfig.model_validate(config or FundamentalsConfig())
            self.ledger, self.clock = ledger, ledger.clock
            self.state = SystemStateStore(ledger.engine, ledger.clock, ConsoleNotifier())
            self.pacer = SecRequestPacer(self.clock, sleep=sleep)
            self.sleep = sleep
            self._factory = client_factory or (
                lambda hook: make_client("sec-edgar", request_hook=hook)
            )
            self._cache: dict[tuple[str, str | None], SecPayload] = {}
            self._lock = asyncio.Lock()
        except Exception:
            raise ConfigurationError(
                "SEC provider needs a valid descriptive SEC_USER_AGENT"
            ) from None

    async def _read(
        self,
        kind: Literal["TICKERS", "COMPANYFACTS", "SUBMISSIONS"],
        cik: str | None,
        *,
        fresh: bool = False,
    ) -> SecPayload:
        try:
            async with asyncio.timeout(30):
                return await self._read_bounded(kind, cik, fresh=fresh)
        except TimeoutError:
            raise ProviderError(
                "FA-02: SEC evidence read exceeded its whole-operation deadline"
            ) from None

    async def _read_bounded(
        self,
        kind: Literal["TICKERS", "COMPANYFACTS", "SUBMISSIONS"],
        cik: str | None,
        *,
        fresh: bool = False,
    ) -> SecPayload:
        key = (kind, cik)
        ttl = timedelta(days=7) if kind == "TICKERS" else timedelta(hours=self.config.cache_hours)
        async with self._lock:
            now = ensure_utc(self.clock.now())
            try:
                cached = self._cache.get(key)
                if cached is not None:
                    cached = SecPayload.model_validate(cached)
                    if cached.fetched_at > now:
                        raise DataIntegrityError("FA-02: SEC cache is future evidence")
                    if not fresh and now - cached.fetched_at < ttl:
                        return cached
                url = (
                    _TICKERS
                    if kind == "TICKERS"
                    else (_FACTS if kind == "COMPANYFACTS" else _SUBMISSIONS).format(cik=cik)
                )
                for attempt in range(3):
                    async with self._factory(self.pacer.acquire) as client:
                        response = await client.get(
                            url,
                            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                        )
                    if response.status_code == 200:
                        result = SecPayload(
                            kind=kind,
                            cik=cik,
                            fetched_at=ensure_utc(self.clock.now()),
                            raw=response.content,
                            data_sha256=hashlib.sha256(response.content).hexdigest(),
                        )
                        await asyncio.to_thread(
                            self.ledger.append,
                            SecurityEvent,
                            kind="SEC_EVIDENCE_FETCHED",
                            detail={"kind": kind, "cik": cik, "data_sha256": result.data_sha256},
                        )
                        self._cache[key] = result
                        return result
                    if response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                        raise ProviderError(
                            "FA-02: SEC read unavailable; no filing evidence supplied"
                        )
                    delay = response.headers.get("Retry-After", str(2**attempt))
                    if not delay.isdecimal() or not 0 <= int(delay) <= 30:
                        raise ProviderError(
                            "FA-02: SEC Retry-After is outside the bounded read deadline"
                        )
                    await self.sleep(max(1, int(delay)))
                raise ProviderError("FA-02: SEC read retries exhausted")
            except ProviderError:
                raise
            except Exception as error:
                await asyncio.to_thread(self.state.halt_for_error, error)
                if isinstance(error, SafetyError):
                    raise error from None
                raise DataIntegrityError("FA-02: SEC evidence cannot be verified; HALTED") from None

    async def cik_for(self, symbol: str) -> str:
        validate_symbol(symbol)
        payload = (await self._read("TICKERS", None)).parsed()
        if len(payload) > 30000:
            raise DataIntegrityError("FA-02: SEC ticker inventory is unbounded")
        matches: set[str] = set()
        try:
            for row in payload.values():
                if not isinstance(row, Mapping):
                    raise ValueError("ticker row must be an object")
                ticker = row.get("ticker")
                number = row.get("cik_str")
                if (
                    not isinstance(ticker, str)
                    or isinstance(number, bool)
                    or not isinstance(number, int)
                    or not 0 < number < 10**10
                ):
                    raise ValueError("ticker identity must be exact")
                if ticker == symbol:
                    matches.add(str(number).zfill(10))
            if len(matches) != 1:
                raise ProviderError("FA-02: requested ticker has no unique SEC issuer mapping")
            return matches.pop()
        except ProviderError:
            raise
        except Exception as error:
            await asyncio.to_thread(self.state.halt_for_error, error)
            raise DataIntegrityError("FA-02: SEC ticker map is malformed; HALTED") from None

    async def companyfacts(self, symbol: str) -> SecPayload:
        return await self._read("COMPANYFACTS", await self.cik_for(symbol))

    async def submissions(self, symbol: str, as_of: datetime) -> Mapping[str, object]:
        ensure_utc(as_of)
        return (await self._read("SUBMISSIONS", await self.cik_for(symbol))).parsed()

    async def realtime_submissions(self, symbol: str, as_of: datetime) -> Mapping[str, object]:
        """RT-06: bypass the 24-hour cache, retaining the same aggregate SEC pacer."""
        ensure_utc(as_of)
        return (await self._read("SUBMISSIONS", await self.cik_for(symbol), fresh=True)).parsed()

    async def earnings_reports(self, symbol: str, as_of: datetime) -> tuple[EarningsReport, ...]:
        from backend.data.earnings_reports import sec_reports

        return sec_reports(symbol, await self.submissions(symbol, as_of), as_of)
