"""DAT-09/SEC-60..62: bounded public news and immutable citation identities."""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from collections.abc import Callable, Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from functools import partial
from typing import Any, Protocol, Self, TypeVar
from urllib.parse import urlsplit

import feedparser  # type: ignore[import-untyped]
import httpx
from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
from pydantic import Field, SecretStr, model_validator
from sqlalchemy import select

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.content import (
    headline_digest,
    headline_stable_id,
    injection_suspect,
    sanitize_text,
)
from backend.core.database import NewsHeadlineRecord, SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError, SafetyError
from backend.core.ledger import Ledger
from backend.core.logging import register_secrets
from backend.data.async_reader import AsyncReadExecutor
from backend.data.broker_state import configure_alpaca_transport
from backend.domain.models import FrozenModel, ProviderStatus, Symbol, UTCDateTime, validate_symbol
from backend.net.egress import EgressPolicy
from backend.net.http import GuardedAsyncClient, make_client

MAX_HEADLINES = 50
_MAX_BODY_BYTES = 1_000_000
_MAX_RSS_ENTRIES = 500
_STORE_DEADLINE_SECONDS = 30
_NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"
LocalT = TypeVar("LocalT")


class ReadOnlyNewsClient(Protocol):
    def get_news(self, request_params: NewsRequest) -> object:
        """Return only public news; no trading/account capability is exposed."""
        ...


class NewsProviderName(StrEnum):
    ALPACA = "ALPACA"
    RSS = "RSS"
    NEWSAPI = "NEWSAPI"
    FAKE = "FAKE"


def _identifier(value: object) -> str | None:
    """Vendor identifiers are public, bounded and never interpreted as instructions."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise DataIntegrityError("DAT-09: provider identifier is malformed")
    if len(value) > 100_000 or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value
    ):
        raise DataIntegrityError("DAT-09: provider identifier exceeds its boundary")
    # URLs remain evidence identities, never display links or credential-bearing text.
    if len(value) > 280 or "://" in value:
        return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
    return value


class NewsInput(FrozenModel):
    """Public vendor evidence before display sanitization; article bodies are absent."""

    provider_id: str | None = Field(default=None, strict=True, max_length=280)
    headline: str = Field(strict=True, min_length=1, max_length=100_000)
    published_at: UTCDateTime
    symbols: tuple[Symbol, ...] = Field(default=(), max_length=MAX_HEADLINES)

    @model_validator(mode="after")
    def valid_input(self) -> Self:
        if self.provider_id != _identifier(self.provider_id):
            raise ValueError("provider identifier must already be bounded")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("news symbols must be unique")
        return self


class NewsHeadline(FrozenModel):
    """Finite frozen public facts; summary eligibility does not confer trade authority."""

    stable_id: str = Field(strict=True, pattern=r"^[a-f0-9]{64}$")
    provider: NewsProviderName
    provider_id: str | None = Field(default=None, strict=True, max_length=280)
    headline: str = Field(strict=True, min_length=1, max_length=280)
    headline_sha256: str = Field(strict=True, pattern=r"^[a-f0-9]{64}$")
    published_at: UTCDateTime
    symbols: tuple[Symbol, ...] = Field(default=(), max_length=MAX_HEADLINES)
    summary_allowed: bool = Field(strict=True)

    @model_validator(mode="after")
    def valid_evidence(self) -> Self:
        if self.headline != sanitize_text(self.headline):
            raise ValueError("headline must be sanitized public text")
        if self.headline_sha256 != headline_digest(self.headline):
            raise ValueError("headline digest does not match public text")
        if self.provider_id != _identifier(self.provider_id):
            raise ValueError("provider identifier must already be bounded")
        if self.stable_id != headline_stable_id(
            self.provider.value, self.provider_id, self.headline_sha256
        ):
            raise ValueError("headline citation is not bound to its identity")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("news symbols must be unique")
        if self.summary_allowed and injection_suspect(self.headline, frozenset()):
            raise ValueError("flagged instructions cannot be summarized")
        return self


class NewsResult(FrozenModel):
    provider: NewsProviderName
    status: ProviderStatus
    as_of: UTCDateTime
    headlines: tuple[NewsHeadline, ...] = Field(default=(), max_length=MAX_HEADLINES)
    reason: str = Field(strict=True, min_length=1, max_length=280)

    @model_validator(mode="after")
    def valid_result(self) -> Self:
        if self.status != ProviderStatus.OK and self.headlines:
            raise ValueError("unavailable news cannot carry verified headlines")
        if len({item.stable_id for item in self.headlines}) != len(self.headlines):
            raise ValueError("news result contains duplicate citations")
        if any(item.published_at > self.as_of for item in self.headlines):
            raise ValueError("news result contains future evidence")
        return self


class NewsProvider(Protocol):
    async def fetch(self, symbols: tuple[str, ...], start: datetime, end: datetime) -> NewsResult:
        """Read public evidence only; unavailable news is explicit."""
        ...


def _stored(record: NewsHeadlineRecord) -> NewsHeadline:
    return NewsHeadline(
        stable_id=record.stable_id,
        provider=NewsProviderName(record.provider),
        provider_id=record.provider_id,
        headline=record.headline,
        headline_sha256=record.headline_sha256,
        published_at=record.published_at,
        symbols=tuple(record.details["symbols"]),
        summary_allowed=record.details["summary_allowed"],
    )


class NewsStore:
    """DAT-09: deduplicate inside the serialized append transaction, across restarts."""

    def __init__(self, ledger: Ledger, *, allowed_hosts: frozenset[str] = frozenset()) -> None:
        if not isinstance(allowed_hosts, frozenset) or any(
            not isinstance(host, str) for host in allowed_hosts
        ):
            raise ConfigurationError("news text hosts must be an explicit immutable inventory")
        self.ledger = ledger
        self.clock = ledger.clock
        self.allowed_hosts = allowed_hosts
        self._write_gate = asyncio.Semaphore(1)
        self._writers: set[asyncio.Task[Any]] = set()

    def _write_finished(self, worker: asyncio.Task[Any]) -> None:
        self._writers.discard(worker)
        self._write_gate.release()
        if not worker.cancelled():
            worker.exception()

    async def ingest_async(
        self,
        provider: NewsProviderName,
        items: tuple[NewsInput, ...],
        *,
        reader: AsyncReadExecutor | None = None,
    ) -> tuple[NewsHeadline, ...]:
        """DAT-08: persistence never blocks the loop; late workers retain their slot."""
        if reader is not None:
            return await reader.run(lambda: self.ingest(provider, items), budget_request=False)
        return await self._local_worker(lambda: self.ingest(provider, items))

    async def _local_worker(self, operation: Callable[[], LocalT]) -> LocalT:
        """Bound bytes-only parsing and persistence without releasing late worker slots."""
        try:
            async with asyncio.timeout(_STORE_DEADLINE_SECONDS):
                await self._write_gate.acquire()
                worker = asyncio.create_task(asyncio.to_thread(operation))
                self._writers.add(worker)
                worker.add_done_callback(self._write_finished)
                return await asyncio.shield(worker)
        except TimeoutError:
            raise ProviderError("DAT-09: public news worker deadline exceeded") from None

    def ingest(
        self, provider: NewsProviderName, items: tuple[NewsInput, ...]
    ) -> tuple[NewsHeadline, ...]:
        """Validate the full batch, then append headlines and injection audits atomically."""
        try:
            if not isinstance(provider, NewsProviderName) or not isinstance(items, tuple):
                raise DataIntegrityError("DAT-09: immutable provider batch is required")
            if len(items) > MAX_HEADLINES:
                raise DataIntegrityError("DAT-09: headline batch exceeds its boundary")
            now = ensure_utc(self.clock.now())
            prepared: list[tuple[NewsHeadline, str | None]] = []
            for original in items:
                item = NewsInput.model_validate(original)
                if item.published_at > now:
                    raise DataIntegrityError("DAT-09: future public news is unverifiable")
                safe = sanitize_text(item.headline)
                digest = headline_digest(safe)
                flagged = injection_suspect(item.headline, self.allowed_hosts)
                headline = NewsHeadline(
                    stable_id=headline_stable_id(provider.value, item.provider_id, digest),
                    provider=provider,
                    provider_id=item.provider_id,
                    headline=safe,
                    headline_sha256=digest,
                    published_at=item.published_at,
                    symbols=item.symbols,
                    summary_allowed=not flagged,
                )
                prepared.append(
                    (
                        headline,
                        hashlib.sha256(item.headline.encode()).hexdigest() if flagged else None,
                    )
                )
            self.ledger.verify_chain()
            output: dict[str, NewsHeadline] = {}
            with transaction(self.ledger.engine) as session:
                for headline, injection_hash in prepared:
                    if injection_hash is not None:
                        self.ledger.append_in_session(
                            session,
                            SecurityEvent,
                            kind="PROMPT_INJECTION_SUSPECT",
                            detail={"headline_sha256": injection_hash},
                        )
                    existing = None
                    if headline.provider_id is not None:
                        existing = session.scalar(
                            select(NewsHeadlineRecord).where(
                                NewsHeadlineRecord.provider == provider.value,
                                NewsHeadlineRecord.provider_id == headline.provider_id,
                            )
                        )
                    if existing is None:
                        existing = session.scalar(
                            select(NewsHeadlineRecord).where(
                                NewsHeadlineRecord.headline_sha256 == headline.headline_sha256
                            )
                        )
                    if existing is None:
                        existing = self.ledger.append_in_session(
                            session,
                            NewsHeadlineRecord,
                            stable_id=headline.stable_id,
                            provider=provider.value,
                            provider_id=headline.provider_id,
                            headline=headline.headline,
                            headline_sha256=headline.headline_sha256,
                            published_at=headline.published_at,
                            details={
                                "symbols": list(headline.symbols),
                                "summary_allowed": headline.summary_allowed,
                            },
                        )
                        session.flush()  # Subsequent rows in this batch see this identity.
                    canonical = _stored(existing)
                    previous = output.get(canonical.stable_id)
                    if injection_hash is not None or (
                        previous is not None and not previous.summary_allowed
                    ):
                        canonical = NewsHeadline.model_validate(
                            {**canonical.model_dump(), "summary_allowed": False}
                        )
                    output[canonical.stable_id] = canonical
            return tuple(output.values())
        except (DataIntegrityError, ConfigurationError):
            raise
        except Exception as exc:
            if isinstance(exc, SafetyError):
                raise exc from None
            raise DataIntegrityError(
                "DAT-09: news evidence failed validation or persistence"
            ) from None


def _query(
    symbols: tuple[str, ...], start: datetime, end: datetime, clock: Clock
) -> tuple[datetime, datetime]:
    try:
        if not isinstance(symbols, tuple) or not 1 <= len(symbols) <= MAX_HEADLINES:
            raise ValueError("bounded immutable symbols required")
        for symbol in symbols:
            validate_symbol(symbol)
        if len(set(symbols)) != len(symbols):
            raise ValueError("duplicate symbols")
        first, last = ensure_utc(start), ensure_utc(end)
        if first > last or last > ensure_utc(clock.now()):
            raise ValueError("future or reversed news interval")
        return first, last
    except Exception:
        raise DataIntegrityError("DAT-09: invalid public news request") from None


def _timestamp(value: object) -> datetime:
    try:
        if isinstance(value, datetime):
            return ensure_utc(value)
        if not isinstance(value, str) or not 1 <= len(value) <= 80:
            raise ValueError("explicit timestamp required")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(value)
        return ensure_utc(parsed)
    except Exception:
        raise DataIntegrityError("DAT-09: public publication timestamp is unverifiable") from None


def _mentions(headline: str, symbols: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        symbol
        for symbol in symbols
        if re.search(r"(?<![A-Z0-9.])" + re.escape(symbol) + r"(?![A-Z0-9.])", headline)
    )


async def _result(
    store: NewsStore,
    provider: NewsProviderName,
    items: tuple[NewsInput, ...],
    *,
    reader: AsyncReadExecutor | None = None,
) -> NewsResult:
    headlines = await store.ingest_async(provider, items, reader=reader)
    return NewsResult(
        provider=provider,
        status=ProviderStatus.OK,
        as_of=ensure_utc(store.clock.now()),
        headlines=headlines,
        reason="Public headlines verified; news remains advisory",
    )


def _unavailable(store: NewsStore, provider: NewsProviderName, reason: str) -> NewsResult:
    return NewsResult(
        provider=provider,
        status=ProviderStatus.UNAVAILABLE,
        as_of=ensure_utc(store.clock.now()),
        reason=reason,
    )


class AlpacaNewsProvider:
    """DAT-09: default SDK provider, using the same data bucket as bars/actions."""

    def __init__(
        self,
        settings: Settings,
        reader: AsyncReadExecutor,
        store: NewsStore,
        *,
        client: ReadOnlyNewsClient | None = None,
    ) -> None:
        reader.bind_policy(settings, store.ledger)
        payload = settings.model_dump()
        if (
            not settings.telegram_allowed_user_ids
            and "telegram_allowed_user_ids" not in settings.model_fields_set
        ):
            payload.pop("telegram_allowed_user_ids")
        checked = Settings.model_validate(payload)
        self.reader, self.store = reader, store
        try:
            self.client: ReadOnlyNewsClient = (
                client
                if client is not None
                else NewsClient(
                    api_key=checked.broker_api_key.get_secret_value(),
                    secret_key=checked.broker_secret_key.get_secret_value(),
                    raw_data=True,
                )
            )
            configure_alpaca_transport(
                self.client,
                checked.request_timeout_seconds,
                before_request=reader.before_request,
            )
        except SafetyError:
            raise
        except Exception:
            raise ProviderError("DAT-09: public news SDK could not be safely initialized") from None

    async def fetch(self, symbols: tuple[str, ...], start: datetime, end: datetime) -> NewsResult:
        first, last = _query(symbols, start, end, self.store.clock)
        # VERIFY: pinned alpaca-py 0.44.0 NewsRequest, symbols is a comma-separated string.
        request = NewsRequest(
            symbols=",".join(symbols),
            start=first,
            end=last,
            limit=MAX_HEADLINES,
            include_content=False,
        )
        try:
            raw = await self.reader.run(lambda: self.client.get_news(request), budget_request=False)
        except ProviderError:
            return _unavailable(self.store, NewsProviderName.ALPACA, "Alpaca news unavailable")
        items = await self.reader.run(lambda: self._parse(raw, first, last), budget_request=False)
        return await _result(self.store, NewsProviderName.ALPACA, items, reader=self.reader)

    def _parse(self, raw: object, first: datetime, last: datetime) -> tuple[NewsInput, ...]:
        if (
            not isinstance(raw, Mapping)
            or not isinstance(raw.get("news"), list)
            or len(raw["news"]) > MAX_HEADLINES
        ):
            raise DataIntegrityError("DAT-09: Alpaca news response is malformed or unbounded")
        items: list[NewsInput] = []
        for row in raw["news"]:
            if not isinstance(row, Mapping) or type(row.get("id")) is not int or row["id"] < 0:
                raise DataIntegrityError("DAT-09: Alpaca news identifier is unverifiable")
            published = _timestamp(row.get("created_at"))
            if not first <= published <= last:
                raise DataIntegrityError("DAT-09: Alpaca news is outside the requested interval")
            if (
                row.get("updated_at") is not None
                and _timestamp(row["updated_at"]) > self.store.clock.now()
            ):
                raise DataIntegrityError("DAT-09: Alpaca news update is from the future")
            raw_symbols = row.get("symbols")
            raw_headline = row.get("headline")
            if not isinstance(raw_symbols, list) or not isinstance(raw_headline, str):
                raise DataIntegrityError("DAT-09: Alpaca news lacks explicit symbol metadata")
            try:
                items.append(
                    NewsInput(
                        provider_id=str(row["id"]),
                        headline=raw_headline,
                        published_at=published,
                        symbols=tuple(raw_symbols),
                    )
                )
            except Exception:
                raise DataIntegrityError("DAT-09: invalid Alpaca public headline") from None
        return tuple(items)


async def _http_read(
    client: GuardedAsyncClient,
    url: str,
    *,
    sleep: Callable[[float], Any] = asyncio.sleep,
    **kwargs: Any,
) -> bytes:
    for attempt in range(3):
        try:
            response = await client.get(url, **kwargs)
        except ProviderError:
            if attempt == 2:
                raise
        else:
            if response.status_code == 200:
                if len(response.content) > _MAX_BODY_BYTES:
                    raise DataIntegrityError("DAT-09: public news body exceeds its boundary")
                return response.content
            if response.status_code != 429 and not 500 <= response.status_code <= 599:
                raise ProviderError("public news request was refused")
            if attempt == 2:
                raise ProviderError("public news retries exhausted")
        await sleep(float(2**attempt))
    raise ProviderError("public news unavailable")


class RssNewsProvider:
    """DAT-09: configured HTTPS feeds only; parser gets bytes and cannot fetch URLs."""

    def __init__(
        self,
        urls: tuple[str, ...],
        store: NewsStore,
        *,
        policy: EgressPolicy,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        if not isinstance(urls, tuple) or not 1 <= len(urls) <= 10 or len(set(urls)) != len(urls):
            raise ConfigurationError("RSS requires 1..10 distinct explicitly configured feeds")
        for url in urls:
            policy.check_url(url, purpose="rss")
        self.urls, self.store, self.policy, self.transport, self.sleep = (
            urls,
            store,
            policy,
            transport,
            sleep,
        )

    async def fetch(self, symbols: tuple[str, ...], start: datetime, end: datetime) -> NewsResult:
        first, last = _query(symbols, start, end, self.store.clock)
        items: list[NewsInput] = []
        async with make_client("rss", policy=self.policy, transport=self.transport) as client:
            for url in self.urls:
                try:
                    body = await _http_read(client, url, sleep=self.sleep)
                except ProviderError:
                    return _unavailable(
                        self.store, NewsProviderName.RSS, "Configured RSS news unavailable"
                    )
                if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                    raise DataIntegrityError("DAT-09: RSS document declarations are untrusted")
                # VERIFY: pinned feedparser 6.0.14 disables external SAX entity downloads.
                # Reject declarations too; the parser receives bytes, never a path/URL.
                parsed = await self.store._local_worker(partial(feedparser.parse, body))
                if (
                    parsed.get("bozo")
                    or not isinstance(parsed.get("entries"), list)
                    or len(parsed["entries"]) > _MAX_RSS_ENTRIES
                ):
                    raise DataIntegrityError("DAT-09: RSS document is malformed or unbounded")
                for entry in parsed["entries"]:
                    if not isinstance(entry, Mapping) or not isinstance(entry.get("title"), str):
                        raise DataIntegrityError("DAT-09: RSS headline is unverifiable")
                    publication = entry.get("published")
                    if publication is None:
                        publication = entry["updated"] if "updated" in entry else None
                    published = _timestamp(publication)
                    if published > self.store.clock.now():
                        raise DataIntegrityError("DAT-09: RSS news is from the future")
                    if not first <= published <= last:
                        continue
                    try:
                        items.append(
                            NewsInput(
                                provider_id=_identifier(entry.get("id", entry.get("link"))),
                                headline=entry["title"],
                                published_at=published,
                                symbols=_mentions(sanitize_text(entry["title"]), symbols),
                            )
                        )
                    except Exception:
                        raise DataIntegrityError("DAT-09: invalid RSS public headline") from None
        items.sort(
            key=lambda item: (item.published_at, headline_digest(item.headline)), reverse=True
        )
        return await _result(self.store, NewsProviderName.RSS, tuple(items[:MAX_HEADLINES]))


class NewsApiProvider:
    """DAT-09: opt-in production-entitled API; keys remain in a header, never a URL."""

    def __init__(
        self,
        store: NewsStore,
        *,
        api_key: SecretStr | None = None,
        enabled: bool = False,
        terms_verified: bool = False,
        policy: EgressPolicy,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        api_key = SecretStr("") if api_key is None else api_key
        if (
            type(enabled) is not bool
            or type(terms_verified) is not bool
            or not isinstance(api_key, SecretStr)
        ):
            raise ConfigurationError("NewsAPI enablement, terms and key must be explicit")
        if enabled and (not terms_verified or not api_key.get_secret_value().strip()):
            raise ConfigurationError("NewsAPI requires verified production terms and a key")
        if len(api_key.get_secret_value()) > 4096:
            raise ConfigurationError("NewsAPI key exceeds its boundary")
        self.store, self.key, self.enabled = store, api_key, enabled
        self.policy, self.transport, self.sleep = policy, transport, sleep
        register_secrets(api_key)
        if enabled:
            policy.check_url(_NEWSAPI_ENDPOINT, purpose="newsapi")

    async def fetch(self, symbols: tuple[str, ...], start: datetime, end: datetime) -> NewsResult:
        first, last = _query(symbols, start, end, self.store.clock)
        if not self.enabled:
            return _unavailable(
                self.store,
                NewsProviderName.NEWSAPI,
                "NewsAPI disabled; production terms unverified",
            )
        query = " OR ".join(symbols)
        if len(query) > 500:
            raise DataIntegrityError("DAT-09: NewsAPI query exceeds the verified endpoint boundary")
        async with make_client("newsapi", policy=self.policy, transport=self.transport) as client:
            try:
                body = await _http_read(
                    client,
                    _NEWSAPI_ENDPOINT,
                    sleep=self.sleep,
                    headers={"X-Api-Key": self.key.get_secret_value()},
                    params={
                        "q": query,
                        "from": first.isoformat(),
                        "to": last.isoformat(),
                        "pageSize": MAX_HEADLINES,
                        "page": 1,
                        "sortBy": "publishedAt",
                    },
                )
            except ProviderError:
                return _unavailable(
                    self.store, NewsProviderName.NEWSAPI, "Opt-in NewsAPI unavailable"
                )
        try:
            import json

            payload = json.loads(body)
            if (
                not isinstance(payload, Mapping)
                or payload.get("status") != "ok"
                or not isinstance(payload.get("articles"), list)
                or len(payload["articles"]) > MAX_HEADLINES
            ):
                raise ValueError("bounded article array required")
            items: list[NewsInput] = []
            for row in payload["articles"]:
                if not isinstance(row, Mapping):
                    raise ValueError("article object required")
                published = _timestamp(row.get("publishedAt"))
                if not first <= published <= last:
                    raise ValueError("article outside request interval")
                headline = row.get("title")
                if not isinstance(headline, str):
                    raise ValueError("public title required")
                url = row.get("url")
                if url is not None:
                    parsed_url = urlsplit(url)
                    if (
                        parsed_url.scheme != "https"
                        or parsed_url.hostname is None
                        or parsed_url.username is not None
                        or parsed_url.password is not None
                    ):
                        raise ValueError("article identity is not public HTTPS")
                items.append(
                    NewsInput(
                        provider_id=_identifier(url),
                        headline=headline,
                        published_at=published,
                        symbols=_mentions(sanitize_text(headline), symbols),
                    )
                )
        except Exception:
            raise DataIntegrityError("DAT-09: invalid NewsAPI public evidence") from None
        return await _result(self.store, NewsProviderName.NEWSAPI, tuple(items))


class FakeNewsProvider:
    """DAT-09: explicit deterministic public fixtures, with real validation/storage."""

    def __init__(
        self, store: NewsStore, items: tuple[NewsInput, ...] = (), *, available: bool = True
    ) -> None:
        if (
            type(available) is not bool
            or not isinstance(items, tuple)
            or len(items) > MAX_HEADLINES
        ):
            raise ConfigurationError("fake news requires a bounded immutable fixture")
        self.store, self.items, self.available = store, items, available

    async def fetch(self, symbols: tuple[str, ...], start: datetime, end: datetime) -> NewsResult:
        first, last = _query(symbols, start, end, self.store.clock)
        if not self.available:
            return _unavailable(self.store, NewsProviderName.FAKE, "Synthetic news unavailable")
        checked = tuple(NewsInput.model_validate(item) for item in self.items)
        if any(item.published_at > self.store.clock.now() for item in checked):
            raise DataIntegrityError("DAT-09: synthetic news contains future evidence")
        matching = tuple(
            item
            for item in checked
            if first <= item.published_at <= last
            and (not item.symbols or set(item.symbols).intersection(symbols))
        )
        return await _result(self.store, NewsProviderName.FAKE, matching)
