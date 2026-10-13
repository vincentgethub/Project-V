"""RT-13/AC-02: one bounded async supervisor, durable critical outbox."""

import asyncio
import random
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import ValidationError

from backend.core.config import RealtimeConfig
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.system_state import SystemStateStore
from backend.realtime.models import Feed, FeedHealth, HealthStatus, RealtimeEvent
from backend.realtime.policy import health_at
from backend.realtime.storage import RealtimeStore

QUEUE_CAP = 1000
Sleep = Callable[[float], Awaitable[None]]


class FeedReader(Protocol):
    async def poll(self, feed: Feed) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]: ...
    async def stream(self, receive: Callable[[RealtimeEvent], Awaitable[None]]) -> None: ...
    async def aclose(self) -> None: ...


class Supervisor:
    def __init__(
        self,
        store: RealtimeStore,
        config: RealtimeConfig,
        reader: FeedReader,
        dispatch: Callable[[RealtimeEvent], Awaitable[None]],
        symbols: Callable[[], Awaitable[tuple[str, ...]]],
        state: SystemStateStore,
        *,
        sleep: Sleep = asyncio.sleep,
        seed: int = 20261006,
    ) -> None:
        self.store, self.config = store, RealtimeConfig.model_validate(config)
        self.reader, self.dispatch, self.symbols, self.sleep = reader, dispatch, symbols, sleep
        self.state = state
        if state.engine is not store.ledger.engine or state.clock is not store.ledger.clock:
            raise DataIntegrityError("RT: halt state must bind the supervisor ledger and clock")
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise DataIntegrityError("RT-13: bounded reconnect seed required")
        # Public reconnect jitter only; identities and tokens use secure sources.
        self.random = random.Random(seed)  # nosec B311
        self.queue: deque[RealtimeEvent] = deque(maxlen=QUEUE_CAP)
        self.dropped = 0
        self.tasks: tuple[asyncio.Task[None], ...] = ()
        self.stopping = False
        self._drain_lock = asyncio.Lock()
        self._receive_lock = asyncio.Lock()
        self._recent: dict[str, None] = {}

    def delay(self, attempt: int) -> float:
        if type(attempt) is not int or not 1 <= attempt <= 1000000:
            raise DataIntegrityError("RT-13: bounded reconnect attempt required")
        ceiling = min(30, 2 ** min(attempt - 1, 5))
        return float(min(30.0, ceiling * self.random.uniform(0.75, 1.0)))

    async def receive(self, value: RealtimeEvent) -> bool:
        event = RealtimeEvent.model_validate(value)
        if self.stopping:
            raise ProviderError("RT: supervisor is stopping; receive is unavailable")
        async with self._receive_lock:
            key = self.store.key(event)
            # Critical evidence is durable before queue admission. Noncritical
            # news may drop before storage; it has no entry/exit authority.
            if event.critical:
                if not await asyncio.to_thread(self.store.receive, event):
                    return False
            elif key in self._recent:
                return False
            self._recent[key] = None
            if len(self._recent) > 10000:
                del self._recent[next(iter(self._recent))]
            if len(self.queue) == QUEUE_CAP:
                oldest = next((row for row in self.queue if not row.critical), self.queue[0])
                self.queue.remove(oldest)
                if not oldest.critical:
                    self.dropped += 1
                # A dropped critical item remains in the durable pending outbox.
            self.queue.append(event)
            return True

    async def drain(self) -> None:
        async with self._drain_lock:
            pending = await asyncio.to_thread(self.store.events, pending_only=True)
            queued = tuple(self.queue)
            self.queue.clear()
            durable = {self.store.key(row) for row in pending}
            combined = {self.store.key(row): row for row in (*pending, *queued)}
            for row in combined.values():
                if not row.critical and self.store.key(row) not in durable:
                    if not await asyncio.to_thread(self.store.receive, row):
                        continue
                await self.dispatch(row)
                await asyncio.to_thread(self.store.complete, row)

    async def once(self, feed: Feed) -> bool:
        try:
            async with asyncio.timeout(30):
                health, events = await self.reader.poll(feed)
            checked = FeedHealth.model_validate(health)
            if checked.feed != feed or not isinstance(events, tuple) or len(events) > 10000:
                raise DataIntegrityError("RT: provider returned an unbound batch")
            for row in events:
                event = RealtimeEvent.model_validate(row)
                if event.feed != feed:
                    raise DataIntegrityError("RT: event belongs to another feed")
                await self.receive(event)
            await asyncio.to_thread(self.store.mark, checked)
            return checked.status == HealthStatus.OK
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if isinstance(error, ValidationError):
                error = DataIntegrityError("RT: invalid typed provider evidence")
            if (
                feed == "news"
                and not isinstance(error, DataIntegrityError)
                and await self._news_transport_failed("REST")
            ):
                return False
            await asyncio.to_thread(
                self.store.mark,
                FeedHealth(
                    feed=feed,
                    status=HealthStatus.UNAVAILABLE,
                    observed_at=self.store.ledger.clock.now(),
                    detail="Feed unavailable: " + type(error).__name__,
                ),
            )
            if isinstance(error, DataIntegrityError):
                await asyncio.to_thread(self.state.halt_for_error, error)
            return False

    async def _poll(self, feed: Feed, interval: int) -> None:
        failures = 0
        while not self.stopping:
            started = self.store.ledger.clock.now()
            success = await self.once(feed)
            failures = 0 if success else min(failures + 1, 1000000)
            # Nasdaq is never polled more than once a minute, even on failure.
            duration = (self.store.ledger.clock.now() - started).total_seconds()
            if duration < 0:
                await asyncio.to_thread(
                    self.state.halt_for_error, DataIntegrityError("RT: poll clock moved backward")
                )
                duration = 0
            # Starts are separated by the configured interval. Sleeping a full
            # interval after IO would make a 60-second asset heartbeat stale.
            wait = (
                max(0.01, interval - duration)
                if success or feed == "halts"
                else self.delay(failures)
            )
            await self.sleep(float(wait))

    async def _news_transport_failed(self, channel: str) -> bool:
        """REST and stream share a heartbeat; one failed transport is not both."""
        await asyncio.to_thread(
            self.store.ledger.append,
            SecurityEvent,
            kind="REALTIME_NEWS_TRANSPORT_FAILED",
            detail={"scope": self.store.scope.model_dump(mode="json"), "channel": channel},
        )
        rows = await asyncio.to_thread(self.store.health)
        return any(
            row.feed == "news"
            and health_at(row, self.store.ledger.clock.now(), self.config) == HealthStatus.OK
            for row in rows
        )

    async def _stream(self) -> None:
        failures = 0
        while not self.stopping:
            try:
                await self.reader.stream(self.receive_stream)
                if not self.stopping:
                    raise ProviderError("RT: news stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failures = min(failures + 1, 1000000)
                if isinstance(error, ValidationError):
                    error = DataIntegrityError("RT-02: invalid typed stream evidence")
                if not isinstance(error, DataIntegrityError) and await self._news_transport_failed(
                    "STREAM"
                ):
                    await self.sleep(self.delay(failures))
                    continue
                await asyncio.to_thread(
                    self.store.mark,
                    FeedHealth(
                        feed="news",
                        status=HealthStatus.UNAVAILABLE,
                        observed_at=self.store.ledger.clock.now(),
                        detail="News stream unavailable",
                    ),
                )
                if isinstance(error, DataIntegrityError):
                    await asyncio.to_thread(self.state.halt_for_error, error)
                await self.sleep(self.delay(failures))

    async def receive_stream(self, event: RealtimeEvent) -> None:
        row = RealtimeEvent.model_validate(event)
        if row.feed != "news":
            raise DataIntegrityError("RT-02: news stream returned another feed")
        await self.receive(row)
        await asyncio.to_thread(
            self.store.mark,
            FeedHealth(
                feed="news",
                status=HealthStatus.OK,
                observed_at=self.store.ledger.clock.now(),
                detail="Verified news stream event received",
            ),
        )

    async def _work(self) -> None:
        while not self.stopping:
            try:
                await self.drain()
                symbols = tuple(sorted(set(await self.symbols())))
                if symbols:
                    await asyncio.to_thread(self.store.sample, symbols)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await asyncio.to_thread(self.state.halt_for_error, error)
            await self.sleep(15.0)

    async def start(self) -> None:
        if self.tasks or self.stopping:
            raise ProviderError("RT: supervisor cannot start twice")
        intervals: dict[Feed, int] = {
            "clock": 30,
            "halts": self.config.halt_poll_sec,
            "news": min(60, self.config.news_stale_sec),
            "assets": self.config.asset_poll_sec,
            "ca": 60,
            "edgar": 60,
            "fred": 60,
            "macro": 3600,
        }
        self.tasks = tuple(
            asyncio.create_task(self._poll(feed, interval)) for feed, interval in intervals.items()
        ) + (
            asyncio.create_task(self._stream()),
            asyncio.create_task(self._work()),
        )

    async def aclose(self) -> None:
        self.stopping = True
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        async with asyncio.timeout(30):
            await self.reader.aclose()
