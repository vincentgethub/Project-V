"""DAT-06/08: shared integer-clock budgets and bounded blocking SDK workers."""

from __future__ import annotations

import asyncio
import math
import threading
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, TypeVar

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, ProviderError, SafetyError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.data_layer import _checked_settings, _transient

ReadT = TypeVar("ReadT")
AsyncSleep = Callable[[float], Awaitable[None]]
_TOKEN = 60_000_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PLANS = {"BASIC": 180, "ALGO_TRADER_PLUS": 9000}


class AsyncReadExecutor(Protocol):
    """DAT-06/08: shared bounded-worker and physical-request admission contract."""

    async def run(self, operation: Callable[[], ReadT], *, budget_request: bool = False) -> ReadT:
        """Admit synchronous work without blocking the event loop."""
        ...

    def before_request(self) -> None:
        """Charge every physical SDK GET, including pagination."""
        ...

    def bind_policy(self, settings: Settings, ledger: Ledger) -> None:
        """Keep the worker bound to one validated plan and ledger/account policy."""
        ...


def _instant(clock: Clock) -> int:
    delta = ensure_utc(clock.now()) - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


class AsyncTokenBucket:
    """DAT-06: one shared plan budget, refilled with integer microseconds."""

    def __init__(
        self, clock: Clock, *, plan: str = "BASIC", sleep: AsyncSleep = asyncio.sleep
    ) -> None:
        if plan not in _PLANS:
            raise DataIntegrityError("DAT-06: unknown Alpaca data plan")
        self.clock, self.sleep = clock, sleep
        self.plan = plan
        self.capacity = _PLANS[plan]
        self._credits = self.capacity * _TOKEN
        self._updated = _instant(clock)
        self._blocked_until = self._updated
        self._lock = asyncio.Lock()

    @property
    def available(self) -> int:
        return self._credits // _TOKEN

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = _instant(self.clock)
                if now < self._updated:
                    raise DataIntegrityError("DAT-06: rate clock moved backward")
                elapsed = now - max(self._updated, self._blocked_until)
                if elapsed > 0:
                    self._credits = min(
                        self.capacity * _TOKEN, self._credits + elapsed * self.capacity
                    )
                self._updated = now
                if now >= self._blocked_until and self._credits >= _TOKEN:
                    self._credits -= _TOKEN
                    return
                wait_us = max(
                    self._blocked_until - now,
                    (_TOKEN - self._credits + self.capacity - 1) // self.capacity,
                    1,
                )
            await self.sleep(wait_us / 1_000_000)

    async def drain(self, retry_after: str | None) -> None:
        """DAT-06: every 429 drains this bucket and honors the server delay."""
        delay = 1_000_000
        if retry_after is not None:
            try:
                if retry_after.isdecimal():
                    seconds = int(retry_after)
                    if not 0 <= seconds <= 86400:
                        raise ValueError("unbounded retry delay")
                    delay = max(delay, seconds * 1_000_000)
                else:
                    until = ensure_utc(parsedate_to_datetime(retry_after))
                    delta = until - ensure_utc(self.clock.now())
                    delay = max(
                        delay, (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
                    )
                    if delay > 86400 * 1_000_000:
                        raise ValueError("unbounded retry delay")
            except Exception:
                raise ProviderError("DAT-06: invalid Retry-After delay") from None
        async with self._lock:
            now = _instant(self.clock)
            if now < self._updated:
                raise DataIntegrityError("DAT-06: rate clock moved backward")
            self._credits = 0
            self._updated = now
            self._blocked_until = max(self._blocked_until, now + delay)


class AsyncAlpacaReader:
    """DAT-08: late SDK results are discarded; workers retain admission slots."""

    def __init__(
        self,
        clock: Clock,
        state: SystemStateStore,
        *,
        plan: str = "BASIC",
        max_inflight: int = 4,
        deadline_seconds: float = 30,
        attempts: int = 3,
        sleep: AsyncSleep = asyncio.sleep,
    ) -> None:
        if (
            type(max_inflight) is not int
            or not 1 <= max_inflight <= 20
            or isinstance(deadline_seconds, bool)
            or not math.isfinite(deadline_seconds)
            or not 0 < deadline_seconds <= 60
            or type(attempts) is not int
            or not 1 <= attempts <= 10
        ):
            raise DataIntegrityError("DAT-08: invalid asynchronous read bounds")
        self.clock, self.state, self.sleep = clock, state, sleep
        self.bucket = AsyncTokenBucket(clock, plan=plan, sleep=sleep)
        self.deadline_seconds, self.attempts = deadline_seconds, attempts
        self.tripped = False
        self._semaphore = asyncio.Semaphore(max_inflight)
        self._local = threading.local()
        self._workers: set[asyncio.Task[Any]] = set()
        self._bound_policy: tuple[str, str, str, str] | None = None
        self._halt_task: asyncio.Task[SystemState] | None = None

    def bind_policy(self, settings: Settings, ledger: Ledger) -> None:
        """DAT-06/R-06: one reader stays bound to its plan and account policy."""
        try:
            settings = _checked_settings(settings)
            policy = (
                settings.alpaca_data_plan,
                settings.broker_endpoint,
                settings.broker_account_type,
                settings.execution_mode,
            )
            if (
                self.bucket.plan != settings.alpaca_data_plan
                or self.bucket.capacity != _PLANS[settings.alpaca_data_plan]
                or self.state.engine is not ledger.engine
                or self.state.clock is not self.clock
                or ledger.clock is not self.clock
                or (self._bound_policy is not None and self._bound_policy != policy)
            ):
                raise DataIntegrityError("DAT-06/R-06: async reader policy or ledger differs")
            self._bound_policy = policy
        except Exception as error:
            self.tripped = True
            self.state.halt_for_error(error)
            if isinstance(error, SafetyError):
                raise error from None
            raise DataIntegrityError("DAT-06/R-06: async reader binding is unverifiable") from None

    def ensure_active(self) -> None:
        """DAT-08: pending workers cannot publish after timeout/circuit failure."""
        loop = getattr(self._local, "loop", None)
        deadline = getattr(self._local, "deadline", None)
        if loop is None or deadline is None:
            raise ProviderError("DAT-08: SDK request requires an admitted async worker")
        remaining = deadline - loop.time()
        if remaining <= 0 or self.tripped:
            raise ProviderError("DAT-08: SDK worker deadline or circuit prevents further requests")

    def before_request(self) -> None:
        """DAT-06: invoked in the SDK thread for every physical GET/page."""
        self.ensure_active()
        loop = self._local.loop
        remaining = self._local.deadline - loop.time()
        future = asyncio.run_coroutine_threadsafe(self.bucket.acquire(), loop)
        try:
            future.result(timeout=remaining)
        except Exception:
            future.cancel()
            raise ProviderError("DAT-08: physical SDK request admission failed") from None
        self.ensure_active()

    async def halt(self, error: Exception) -> None:
        """DAT-08/R-02: the one durable fault write also keeps the loop responsive."""
        self.tripped = True
        if self._halt_task is None:

            def persist_fault() -> SystemState:
                result = self.state.halt_for_error(error)
                self.state.ledger.append(
                    SecurityEvent, kind="CIRCUIT_BREAKER_HALTED", detail={"provider": "SDK_ASYNC"}
                )
                return result

            self._halt_task = asyncio.create_task(asyncio.to_thread(persist_fault))
        await asyncio.shield(self._halt_task)

    def _completed(self, worker: asyncio.Task[Any]) -> None:
        self._workers.discard(worker)
        self._semaphore.release()
        if not worker.cancelled():
            worker.exception()

    async def aclose(self) -> None:
        """Refuse new reads and await admitted threads before closing clients."""
        self.tripped = True
        workers = tuple(self._workers)
        if workers:
            async with asyncio.timeout(self.deadline_seconds + 1):
                await asyncio.shield(asyncio.gather(*workers, return_exceptions=True))
        if self._halt_task is not None:
            await asyncio.shield(self._halt_task)

    async def run(self, operation: Callable[[], ReadT], *, budget_request: bool = False) -> ReadT:
        """DAT-04/08: preserve one deadline across retries and all SDK pages."""
        if self.tripped:
            raise ProviderError("DAT-08: async circuit breaker is latched")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.deadline_seconds
        try:
            async with asyncio.timeout_at(deadline):
                for attempt in range(self.attempts):
                    await self._semaphore.acquire()

                    def work() -> ReadT:
                        self._local.loop, self._local.deadline = loop, deadline
                        try:
                            if budget_request:
                                self.before_request()
                            return operation()
                        finally:
                            del self._local.loop, self._local.deadline

                    worker = asyncio.create_task(asyncio.to_thread(work))
                    self._workers.add(worker)
                    worker.add_done_callback(self._completed)
                    try:
                        return await asyncio.shield(worker)
                    except Exception as error:
                        response = getattr(error, "response", None)
                        status = getattr(error, "status_code", None)
                        if status is None and response is not None:
                            status = getattr(response, "status_code", None)
                        if status == 429:
                            headers = getattr(response, "headers", {})
                            delay = headers.get("Retry-After") if hasattr(headers, "get") else None
                            await self.bucket.drain(delay)
                        if not _transient(error) or attempt + 1 == self.attempts:
                            raise
                        await self.sleep(min(2**attempt, 8))
                raise ProviderError("DAT-08: retry attempts exhausted")
        except asyncio.CancelledError:
            await self.halt(ProviderError("DAT-08: SDK operation canceled with worker pending"))
            raise
        except Exception as error:
            await self.halt(error)
            if isinstance(error, SafetyError):
                raise error from None
            raise ProviderError("DAT-08: SDK read failed or exceeded deadline; HALTED") from None
