"""DAT-06/08: fake-clock rates, physical pages, deadlines and retained workers."""

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import requests
from sqlalchemy import Engine

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader, AsyncTokenBucket
from backend.data.data_layer import ResilientReader


@dataclass
class MovingClock:
    current: datetime

    def now(self) -> datetime:
        return ensure_utc(self.current)

    async def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("plan,capacity", [("BASIC", 180), ("ALGO_TRADER_PLUS", 9000)])
async def test_DAT_06_shared_burst_uses_integer_refill(plan: str, capacity: int) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    bucket = AsyncTokenBucket(clock, plan=plan, sleep=clock.sleep)
    start = clock.now()
    for _ in range(capacity):
        await bucket.acquire()
    assert clock.now() == start and bucket.available == 0
    await bucket.acquire()
    elapsed = clock.now() - start
    assert elapsed >= timedelta(microseconds=(60_000_000 + capacity - 1) // capacity)
    assert bucket.available == 0


@pytest.mark.asyncio
async def test_DAT_06_429_drains_and_waits_http_date() -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    bucket = AsyncTokenBucket(clock, sleep=clock.sleep)
    await bucket.drain("Tue, 29 Sep 2026 15:00:03 GMT")
    assert bucket.available == 0
    await bucket.acquire()
    assert clock.now() >= datetime(2026, 9, 29, 15, 0, 3, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["bad", "99999999", "Wed, 29 Sep 2099 15:00:00 GMT"])
async def test_DAT_06_invalid_retry_delay_fails_typed(header: str) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    with pytest.raises(ProviderError):
        await AsyncTokenBucket(clock).drain(header)


@pytest.mark.asyncio
async def test_DAT_06_backward_clock_refuses() -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    bucket = AsyncTokenBucket(clock)
    clock.current -= timedelta(microseconds=1)
    with pytest.raises(DataIntegrityError):
        await bucket.acquire()


@pytest.mark.asyncio
async def test_DAT_08_sdk_pages_are_counted_without_blocking_loop(engine: Engine) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state, sleep=clock.sleep)
    main_thread = threading.get_ident()

    def operation() -> int:
        assert threading.get_ident() != main_thread
        reader.before_request()
        reader.before_request()
        return 2

    assert await reader.run(operation) == 2
    assert reader.bucket.available == 178 and state.current() == SystemState.RUNNING
    with pytest.raises(ProviderError):
        reader.before_request()


@pytest.mark.asyncio
async def test_DAT_06_429_retry_shares_drained_physical_bucket(engine: Engine) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state, sleep=clock.sleep)
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "3"
            raise requests.HTTPError("synthetic rate response", response=response)
        return "ok"

    assert await reader.run(operation, budget_request=True) == "ok"
    assert calls == 2 and clock.now() >= datetime(2026, 9, 29, 15, 0, 3, tzinfo=UTC)
    assert state.current() == SystemState.RUNNING


@pytest.mark.asyncio
async def test_DAT_08_timeout_retains_slot_and_discards_late_result(engine: Engine) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state, max_inflight=1, deadline_seconds=0.04)
    release = threading.Event()
    finished = threading.Event()

    def slow() -> str:
        release.wait(2)
        try:
            reader.before_request()
        except ProviderError:
            finished.set()
        return "untrusted late result"

    try:
        with pytest.raises(ProviderError, match="deadline"):
            await reader.run(slow)
        assert reader._semaphore._value == 0
        assert state.current() == SystemState.HALTED and reader.tripped
        with pytest.raises(ProviderError, match="latched"):
            await reader.run(lambda: "must not run")
    finally:
        release.set()
        for _ in range(100):
            if not reader._workers:
                break
            await asyncio.sleep(0.005)
    assert finished.is_set() and reader._semaphore._value == 1


@pytest.mark.asyncio
async def test_DAT_08_nontemporary_fault_is_redacted_and_halts(engine: Engine) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state)

    def bad() -> None:
        raise RuntimeError("synthetic credential must never be displayed")

    with pytest.raises(ProviderError) as caught:
        await reader.run(bad)
    assert "credential" not in str(caught.value) and state.current() == SystemState.HALTED


@pytest.mark.parametrize("mismatch", ["plan", "clock", "capacity", "account"])
def test_DAT_06_reader_cannot_rebind_plan_or_account_policy(engine: Engine, mismatch: str) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state)
    ledger = Ledger(engine, clock)
    reader.bind_policy(Settings(), ledger)
    reader.bind_policy(Settings(), ledger)
    settings = Settings()
    if mismatch == "plan":
        settings = Settings(alpaca_data_plan="ALGO_TRADER_PLUS")
    elif mismatch == "clock":
        ledger = Ledger(engine, MovingClock(clock.now()))
    elif mismatch == "capacity":
        reader.bucket.capacity = 9000
    else:
        settings = Settings(broker_account_type="MARGIN")
    with pytest.raises(DataIntegrityError, match="policy or ledger"):
        reader.bind_policy(settings, ledger)
    assert reader.tripped and state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_DAT_08_canceled_worker_retains_admission_and_durably_halts(engine: Engine) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state, max_inflight=1)
    started, release = threading.Event(), threading.Event()

    def pending() -> str:
        started.set()
        release.wait(2)
        return "late"

    task = asyncio.create_task(reader.run(pending))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reader._semaphore._value == 0
        assert state.current() == SystemState.HALTED and reader.tripped
    finally:
        release.set()
        for _ in range(100):
            if not reader._workers:
                break
            await asyncio.sleep(0.005)
    assert reader._semaphore._value == 1


def test_DAT_06_legacy_read_defaults_follow_selected_plan(engine: Engine) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    assert ResilientReader(clock, state).calls_per_minute == 180
    assert ResilientReader(clock, state, plan="ALGO_TRADER_PLUS").calls_per_minute == 9000
    with pytest.raises(ProviderError):
        ResilientReader(clock, state, calls_per_minute=181)


@pytest.mark.asyncio
async def test_OPS_02_close_drains_blocking_read_and_refuses_new_work(engine: Engine) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 15, tzinfo=UTC))
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reader = AsyncAlpacaReader(clock, state)
    begun, release = threading.Event(), threading.Event()

    def operation() -> str:
        begun.set()
        release.wait(2)
        return "Synthetic completed worker"

    task = asyncio.create_task(reader.run(operation))
    for _ in range(100):
        if begun.is_set():
            break
        await asyncio.sleep(0.005)
    assert begun.is_set()
    closing = asyncio.create_task(reader.aclose())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    assert await task == "Synthetic completed worker"
    assert not reader._workers and reader.tripped
    with pytest.raises(ProviderError):
        await reader.run(lambda: "must not run")
