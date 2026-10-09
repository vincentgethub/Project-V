"""AX-16/SEC-30: one admitted SDK attempt, never a blind retry."""

import asyncio
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from backend.core.errors import ProviderError
from backend.data.async_reader import AsyncTokenBucket

ResultT = TypeVar("ResultT")


class SingleAttemptWorker:
    def __init__(self, bucket: AsyncTokenBucket, *, deadline_seconds: int = 30) -> None:
        if type(deadline_seconds) is not int or not 1 <= deadline_seconds <= 30:
            raise ProviderError("Order worker requires a deadline of at most 30 seconds")
        self.bucket, self.deadline_seconds = bucket, deadline_seconds
        self._local = threading.local()
        self._workers: set[asyncio.Task[Any]] = set()
        self._closed = False

    def before_request(self) -> None:
        """Only one physical HTTP call may consume the already admitted token."""
        if not getattr(self._local, "admitted", False):
            raise ProviderError("SDK request has no one-attempt admission")
        self._local.admitted = False
        guard = self._local.guard
        guard()

    def _completed(self, worker: asyncio.Task[Any]) -> None:
        self._workers.discard(worker)
        if not worker.cancelled():
            worker.exception()

    async def attempt(
        self, operation: Callable[[], ResultT], *, guard: Callable[[], None] = lambda: None
    ) -> ResultT:
        if self._closed or len(self._workers) >= 2:
            raise ProviderError("Order worker is closed or has two unresolved physical attempts")
        async with asyncio.timeout(self.deadline_seconds):
            await self.bucket.acquire()

            def work() -> ResultT:
                self._local.admitted, self._local.guard = True, guard
                try:
                    guard()
                    return operation()
                finally:
                    del self._local.admitted, self._local.guard

            worker = asyncio.create_task(asyncio.to_thread(work))
            self._workers.add(worker)
            worker.add_done_callback(self._completed)
            # Cancel/timeout leaves the physical worker tracked until it exits.
            # The caller must look up the durable client ID and must not retry.
            return await asyncio.shield(worker)

    @property
    def has_pending_attempts(self) -> bool:
        return bool(self._workers)

    async def aclose(self) -> None:
        self._closed = True
        if self._workers:
            async with asyncio.timeout(35):
                await asyncio.shield(asyncio.gather(*tuple(self._workers), return_exceptions=True))
