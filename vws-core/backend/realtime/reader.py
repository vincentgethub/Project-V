"""RT-01..08: bound read-only adapters; all failures remain unavailable."""

import asyncio
import ssl
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any, Protocol, cast

from alpaca.data.live.news import NewsDataStream
from alpaca.data.models.news import News
from pydantic import SecretStr

from backend.core.config import RealtimeConfig, Settings
from backend.core.errors import DataIntegrityError, ProviderError
from backend.data.broker_clock import BrokerTimeVerifier
from backend.data.market_calendar import MarketCalendar
from backend.data.sec_edgar import SecEdgarProvider
from backend.domain.models import validate_symbol
from backend.net.http import make_client
from backend.ops.macro_events import MacroCalendar
from backend.ops.read_checks import ReadChecksClient
from backend.realtime import parsers
from backend.realtime.models import Feed, FeedHealth, HealthStatus, RealtimeEvent
from backend.realtime.policy import NY, clock_status
from backend.realtime.storage import RealtimeStore

Symbols = Callable[[], Awaitable[tuple[str, ...]]]


class _NewsStream(Protocol):
    def subscribe_news(
        self, handler: Callable[[object], Awaitable[None]], *symbols: str
    ) -> None: ...
    async def _start_ws(self) -> None: ...
    async def _send_subscribe_msg(self) -> None: ...
    async def _consume(self) -> bool: ...
    async def close(self) -> None: ...


class RealtimeReader:
    def __init__(
        self,
        settings: Settings,
        config: RealtimeConfig,
        reads: ReadChecksClient,
        store: RealtimeStore,
        verifier: BrokerTimeVerifier,
        calendar: MarketCalendar,
        symbols: Symbols,
        pending_held: Symbols,
        macro: MacroCalendar,
        schedules_verified: Callable[[], bool],
        *,
        sec: SecEdgarProvider | None = None,
        fred_key: SecretStr | None = None,
        stream_factory: Callable[..., object] = NewsDataStream,
    ) -> None:
        self.settings, self.config = (
            Settings.validated_copy(settings),
            RealtimeConfig.model_validate(config),
        )
        if (
            (store.scope.environment == "PAPER") != self.settings.paper_trading
            or reads.policy.ledger.engine is not store.ledger.engine
            or verifier.state.engine is not store.ledger.engine
            or reads.clock is not store.ledger.clock
        ):
            raise DataIntegrityError(
                "RT: adapters must bind one endpoint, account ledger and clock"
            )
        self.reads, self.store, self.clock = reads, store, store.ledger.clock
        self.verifier, self.calendar, self.symbols, self.pending_held = (
            verifier,
            calendar,
            symbols,
            pending_held,
        )
        self.macro, self.schedules_verified, self.sec, self.fred_key = (
            macro,
            schedules_verified,
            sec,
            fred_key,
        )
        if sec is not None and (
            sec.ledger.engine is not store.ledger.engine or sec.clock is not self.clock
        ):
            raise DataIntegrityError(
                "RT-06: research and realtime must share the SEC provider and pacer"
            )
        self.stream_factory = stream_factory
        self._stream: _NewsStream | None = None
        self._cache: dict[Feed, tuple[FeedHealth, tuple[RealtimeEvent, ...]]] = {}
        self._ca_slots: set[tuple[str, int]] = set()
        self._fred_day: str | None = None

    async def _symbols(self, source: Symbols) -> tuple[str, ...]:
        values = await source()
        if (
            not isinstance(values, tuple)
            or not 1 <= len(values) <= 1000
            or values != tuple(sorted(set(values)))
        ):
            raise DataIntegrityError("RT: ordered unique bounded watched symbol inventory required")
        for symbol in values:
            validate_symbol(symbol)
        return values

    async def _json(self, url: str, params: dict[str, str] | None = None) -> Mapping[str, Any]:
        payload = await self.reads._get(
            "alpaca",
            url,
            headers=self.reads.broker_headers(
                self.settings.broker_api_key, self.settings.broker_secret_key
            ),
            params=params,
        )
        if not isinstance(payload, Mapping):
            raise DataIntegrityError("RT: provider response object required")
        return payload

    def _health(
        self,
        feed: Feed,
        events: tuple[RealtimeEvent, ...],
        *,
        symbols: tuple[str, ...] = (),
        status: HealthStatus = HealthStatus.OK,
        detail: str = "Verified read-only provider response",
    ) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]:
        value = (
            FeedHealth(
                feed=feed,
                status=status,
                observed_at=self.clock.now(),
                detail=detail,
                symbols=symbols,
            ),
            events,
        )
        self._cache[feed] = value
        return value

    async def poll(self, feed: Feed) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]:
        if feed == "clock":
            evidence = await self.verifier.verify()
            uncertainty = max(
                abs(evidence.timestamp - evidence.sampled_start),
                abs(evidence.timestamp - evidence.sampled_end),
            )
            milliseconds = (
                Decimal(uncertainty.days * 86400000 + uncertainty.seconds * 1000)
                + Decimal(uncertainty.microseconds) / 1000
            )
            return self._health(
                feed,
                (),
                status=clock_status(milliseconds, self.config),
                detail=f"Bounded clock skew {milliseconds} ms; calendar verified",
            )
        if feed == "news":
            symbols = await self._symbols(self.symbols)
            now = self.clock.now()
            params = {
                "symbols": ",".join(symbols),
                "start": (now - timedelta(seconds=self.config.news_stale_sec)).isoformat(),
                "end": now.isoformat(),
                "limit": "50",
                "sort": "asc",
            }
            events: list[RealtimeEvent] = []
            for _ in range(10):
                payload = await self._json("https://data.alpaca.markets/v1beta1/news", params)
                articles = payload.get("news")
                if not isinstance(articles, list) or len(articles) > 50:
                    raise DataIntegrityError("RT-02: bounded news article list required")
                for article in articles:
                    if not isinstance(article, Mapping):
                        raise DataIntegrityError("RT-02: news article object required")
                    events.extend(
                        row for row in parsers.news(article, now) if row.symbol in symbols
                    )
                token = payload.get("next_page_token")
                if token is None:
                    return self._health(feed, tuple(events))
                if not isinstance(token, str) or not 1 <= len(token) <= 2048:
                    raise DataIntegrityError("RT-02: bounded next-page token required")
                params["page_token"] = token
            raise ProviderError("RT-02: news page bound exhausted; coverage unavailable")
        if feed == "halts":
            async with make_client(
                "nasdaq-halts",
                policy=self.reads.policy,
                allow_redirects=False,
                max_response_bytes=1048576,
            ) as client:
                response = await client.get("https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts")
            if response.status_code != 200:
                raise ProviderError("RT-03: Nasdaq halt feed unavailable")
            return self._health(feed, parsers.halt_rss(response.content, self.clock.now()))
        if feed == "assets":
            symbols = await self._symbols(self.symbols)
            previous = {row.symbol: row for row in self.store.events() if row.feed == "assets"}
            events = []
            for symbol in symbols:
                payload = await self._json(self.settings.broker_endpoint + "/v2/assets/" + symbol)
                row = parsers.asset(payload, symbol, self.clock.now())
                old = previous.get(symbol)
                events.append(old if old is not None and old.kind == row.kind else row)
            return self._health(feed, tuple(events), symbols=symbols)
        if feed == "edgar":
            if self.sec is None or self.settings.sec_user_agent is None:
                raise ProviderError("RT-06: SEC_USER_AGENT must be entered through setup")
            symbols = await self.pending_held()
            if (
                not isinstance(symbols, tuple)
                or len(symbols) > 1000
                or symbols != tuple(sorted(set(symbols)))
            ):
                raise DataIntegrityError("RT-06: bounded held/pending symbols required")
            now = self.clock.now()
            rows: list[RealtimeEvent] = []
            for symbol in symbols:
                payload = await self.sec.realtime_submissions(symbol, now)
                rows.extend(
                    parsers.submissions(payload, symbol, now, since=now - timedelta(days=1))
                )
            return self._health(feed, tuple(rows))
        if feed == "fred":
            if self.fred_key is None:
                raise ProviderError("RT-07: FRED key must be entered through setup")
            now = self.clock.now()
            # Before 16 ET, use the latest completed session. After 16 ET,
            # an unpublished current close fails closed until FRED supplies it.
            expected = self.calendar.last_completed_session(now)
            day = now.astimezone(NY).date().isoformat() + ":" + expected.isoformat()
            if self._fred_day == day and feed in self._cache:
                return self._cache[feed]
            result = await self.reads.fred_observations(self.fred_key)
            row = parsers.fred(result, now, expected)
            self._fred_day = day
            return self._health(feed, (row,))
        if feed == "macro":
            self.macro.read()
            if not self.schedules_verified():
                raise ProviderError("RT-08: quarterly schedule needs manual confirmation")
            return self._health(feed, ())
        if feed == "ca":
            return await self._corporate_actions()
        raise DataIntegrityError("RT: unknown feed")

    async def _corporate_actions(self) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]:
        now = self.clock.now()
        day = now.astimezone(NY).date()
        if not self.calendar.is_session(day):
            if "ca" in self._cache:
                return self._cache["ca"]
            raise ProviderError("RT-05: no current session corporate-action poll")
        opened, closed = self.calendar.session_open(day), self.calendar.session_close(day)
        if now < opened:
            if "ca" in self._cache:
                return self._cache["ca"]
            raise ProviderError("RT-05: first session poll awaits market open")
        slot = 0 if now < opened + (closed - opened) / 2 else 1
        key = (day.isoformat(), slot)
        if key in self._ca_slots:
            return self._cache["ca"]
        symbols = await self._symbols(self.symbols)
        params = {
            "symbols": ",".join(symbols),
            "region": "us",
            "data_quality": "all",
            "start": (day - timedelta(days=7)).isoformat(),
            "end": day.isoformat(),
            "limit": "1000",
        }
        payload = await self._json("https://data.alpaca.markets/v1/corporate-actions", params)
        # A truncated response must never certify absence of a hard event.
        if payload.get("next_page_token") is not None:
            raise ProviderError("RT-05: corporate-action page bound requires a complete refresh")
        rows = parsers.corporate_actions(payload, now, symbols)
        self._ca_slots = {value for value in self._ca_slots if value[0] == day.isoformat()}
        self._ca_slots.add(key)
        return self._health(
            "ca", rows, detail="Delayed corporate-action confirmation; no freshness guarantee"
        )

    async def stream(self, receive: Callable[[RealtimeEvent], Awaitable[None]]) -> None:
        # VERIFY alpaca-py 0.44.0: run one SDK connect/auth/subscribe/consume
        # attempt. The supervisor owns the sole retry/backoff loop.
        self.reads.policy.check_url(
            "https://stream.data.alpaca.markets/v1beta1/news", purpose="alpaca-news-stream"
        )
        symbols = await self._symbols(self.symbols)

        async def received(value: object) -> None:
            if not isinstance(value, News):
                raise DataIntegrityError("RT-02: pinned SDK News payload required")
            current = await self._symbols(self.symbols)
            for row in parsers.news(value.model_dump(mode="json"), self.clock.now()):
                if row.symbol in current:
                    await receive(row)

        selected = cast(
            _NewsStream,
            self.stream_factory(
                self.reads._token(self.settings.broker_api_key),
                self.reads._token(self.settings.broker_secret_key),
                raw_data=False,
                websocket_params={
                    "ssl": ssl.create_default_context(),
                    "ping_interval": 10,
                    "ping_timeout": 20,
                    "open_timeout": 20,
                    "close_timeout": 5,
                    "max_queue": 1000,
                    "max_size": 1048576,
                },
                url_override="wss://stream.data.alpaca.markets/v1beta1/news",
                data_timeout=self.config.news_stale_sec,
            ),
        )
        self._stream = selected
        try:
            selected.subscribe_news(received, *symbols, "*")
            async with asyncio.timeout(30):
                await selected._start_ws()
                await selected._send_subscribe_msg()
            await selected._consume()
            raise ProviderError("RT-02: stream ended or became stale")
        finally:
            async with asyncio.timeout(30):
                await selected.close()
            self._stream = None

    async def aclose(self) -> None:
        if self._stream is not None:
            await self._stream.close()
