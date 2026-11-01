"""AX-16/SEC-30: one admitted SDK attempt, never a blind retry."""

import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, TypeVar
from uuid import UUID, uuid4

from backend.core.errors import ConfigurationError, ProviderError
from backend.data.async_reader import AsyncTokenBucket

ResultT = TypeVar("ResultT")


class AttemptNotStartedError(TimeoutError):
    """A deadline expired before any physical worker was created."""


class TransportState(StrEnum):
    PENDING = "PENDING"
    ENTERED = "ENTERED"
    ABANDONED = "ABANDONED"


@dataclass(frozen=True)
class TransportRecord:
    attempt_id: UUID
    client_order_id: str | None
    state: TransportState
    reason: Literal["timeout", "cancelled"]
    kind: Literal[
        "EXECUTION_ATTEMPT_ABANDONED",
        "EXECUTION_ATTEMPT_UNCERTAIN",
        "EXECUTION_ATTEMPT_REFUSED",
        "EXECUTION_ATTEMPT_CONTRADICTION",
    ]
    never_entered_transport: bool


class TransportAttempt:
    """One lock linearizes the final enter/abandon race; neither winner changes."""

    def __init__(
        self,
        client_order_id: str | None,
        bound: bool,
        recorder: Callable[[TransportRecord], None] | None,
    ) -> None:
        self.attempt_id, self.client_order_id = uuid4(), client_order_id
        self._state = TransportState.PENDING
        self._bound, self._recorder = bound, recorder
        self._lock = threading.Lock()
        self._proof: TransportRecord | None = None
        self._refused = False
        self._vetoed = False
        self._reason: Literal["timeout", "cancelled"] = "timeout"

    def bind_boundary(self) -> None:
        with self._lock:
            self._bound = True

    def enter(self) -> None:
        with self._lock:
            if self._state == TransportState.PENDING:
                self._state = TransportState.ENTERED
                return
            if self._state == TransportState.ABANDONED:
                self._vetoed = True
                raise ProviderError("Abandoned attempt refused before physical transport")
        raise ProviderError("Attempt has already entered its one physical request")

    def abandon(self, reason: Literal["timeout", "cancelled"]) -> None:
        with self._lock:
            self._reason = reason
            if self._state == TransportState.PENDING:
                self._state = TransportState.ABANDONED
            certain = self._state == TransportState.ABANDONED and self._bound
            record = TransportRecord(
                self.attempt_id,
                self.client_order_id,
                self._state,
                reason,
                "EXECUTION_ATTEMPT_ABANDONED" if certain else "EXECUTION_ATTEMPT_UNCERTAIN",
                certain,
            )
        if self._recorder is not None:
            try:
                self._recorder(record)
            except Exception:
                # Missing/failed acknowledgement can never authorize NOT_SENT.
                return
            if certain:
                with self._lock:
                    self._proof = record

    def audit_refusal(self) -> None:
        with self._lock:
            if self._state != TransportState.ABANDONED or not self._vetoed:
                return
            record = TransportRecord(
                self.attempt_id,
                self.client_order_id,
                self._state,
                self._reason,
                "EXECUTION_ATTEMPT_REFUSED",
                True,
            )
            recorder = None if self._refused else self._recorder
            self._refused = True
        if recorder is not None:
            recorder(record)

    def proof(self, client_order_id: str) -> TransportRecord | None:
        with self._lock:
            record = self._proof
        return record if record is not None and record.client_order_id == client_order_id else None


class SingleAttemptWorker:
    def __init__(self, bucket: AsyncTokenBucket, *, deadline_seconds: int = 30) -> None:
        if type(deadline_seconds) is not int or not 1 <= deadline_seconds <= 30:
            raise ProviderError("Order worker requires a deadline of at most 30 seconds")
        self.bucket, self.deadline_seconds = bucket, deadline_seconds
        self._local = threading.local()
        self._workers: set[asyncio.Task[Any]] = set()
        self._closed = False
        self._transport_bound = False
        self._recorder: Callable[[TransportRecord], None] | None = None
        self._refusal_error: Callable[[Exception], object] | None = None
        self._client_id: ContextVar[str | None] = ContextVar("attempt-client-id", default=None)
        self._attempt: ContextVar[TransportAttempt | None] = ContextVar(
            "transport-attempt", default=None
        )

    def set_transport_recorder(
        self,
        recorder: Callable[[TransportRecord], None],
        *,
        on_refusal_error: Callable[[Exception], object],
    ) -> None:
        if on_refusal_error is None:
            raise ConfigurationError("Order worker requires a refusal-error HALT callback")
        self._recorder = recorder
        self._refusal_error = on_refusal_error

    @contextmanager
    def order_context(self, client_order_id: str) -> Iterator[None]:
        token = self._client_id.set(client_order_id)
        try:
            yield
        finally:
            self._client_id.reset(token)

    def durable_abandonment(self, client_order_id: str) -> TransportRecord | None:
        attempt = self._attempt.get()
        return None if attempt is None else attempt.proof(client_order_id)

    def before_request(self) -> None:
        """Only one physical HTTP call may consume the already admitted token."""
        if self._refusal_error is None:
            raise ConfigurationError("Order worker requires a refusal-error HALT callback")
        if not getattr(self._local, "admitted", False):
            raise ProviderError("SDK request has no one-attempt admission")
        self._local.admitted = False
        attempt: TransportAttempt = self._local.attempt
        self._transport_bound = True
        attempt.bind_boundary()
        guard = self._local.guard
        guard()
        attempt.enter()

    def _completed(self, worker: asyncio.Task[Any]) -> None:
        self._workers.discard(worker)
        if not worker.cancelled():
            worker.exception()

    async def attempt(
        self, operation: Callable[[], ResultT], *, guard: Callable[[], None] = lambda: None
    ) -> ResultT:
        self._attempt.set(None)
        if self._closed or len(self._workers) >= 2:
            raise ProviderError("Order worker is closed or has two unresolved physical attempts")
        worker: asyncio.Task[ResultT] | None = None
        attempt = TransportAttempt(self._client_id.get(), self._transport_bound, self._recorder)
        self._attempt.set(attempt)
        deadline = asyncio.timeout(self.deadline_seconds)
        try:
            async with deadline:
                await self.bucket.acquire()
                # No await may be added between admission returning and create_task:
                # otherwise NOT_SENT below would no longer prove zero workers.

                def work() -> ResultT:
                    self._local.admitted, self._local.guard = True, guard
                    self._local.attempt = attempt
                    try:
                        guard()
                        return operation()
                    except Exception as original:
                        try:
                            attempt.audit_refusal()
                        except Exception as audit_error:
                            original.add_note(f"Refusal audit failed: {type(audit_error).__name__}")
                            if self._refusal_error is not None:
                                try:
                                    self._refusal_error(audit_error)
                                except Exception as halt_error:
                                    original.add_note(
                                        f"Refusal HALT notification failed: {type(halt_error).__name__}"
                                    )
                        raise
                    finally:
                        for name in ("admitted", "guard", "attempt"):
                            self._local.__dict__.pop(name, None)

                worker = asyncio.create_task(asyncio.to_thread(work))
                self._workers.add(worker)
                worker.add_done_callback(self._completed)
                # Cancel/timeout leaves the physical worker tracked until it exits.
                # The caller must look up the durable client ID and must not retry.
                return await asyncio.shield(worker)
        except TimeoutError:
            if worker is None:
                raise AttemptNotStartedError(
                    "Order attempt timed out before physical worker creation; no request sent"
                ) from None
            if deadline.expired():
                attempt.abandon("timeout")
            raise
        except asyncio.CancelledError:
            if worker is not None and not worker.done():
                attempt.abandon("cancelled")
            raise

    @property
    def has_pending_attempts(self) -> bool:
        return bool(self._workers)

    async def aclose(self) -> None:
        self._closed = True
        if self._workers:
            async with asyncio.timeout(35):
                await asyncio.shield(asyncio.gather(*tuple(self._workers), return_exceptions=True))
