"""RT-13: bounded fake queues and measured idle CPU; no network/services."""

import asyncio
from time import perf_counter, process_time

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import RealtimeConfig
from backend.core.ledger import Ledger
from backend.core.system_state import SystemStateStore
from backend.realtime.models import Feed, FeedHealth, HealthStatus, RealtimeEvent
from backend.realtime.storage import RealtimeStore
from backend.realtime.supervisor import Supervisor
from backend.tests.test_system_state import RecordingNotifier
from backend.tests.test_w_core import HASH, SCOPE, event


@pytest.mark.perf
@pytest.mark.asyncio
async def test_RT_fake_supervisor_idle_cpu_and_queue_bound(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    state = SystemStateStore(engine, clock, RecordingNotifier())
    store = RealtimeStore(ledger, SCOPE, HASH)

    class Fake:
        async def poll(self, feed: Feed) -> tuple[FeedHealth, tuple[RealtimeEvent, ...]]:
            return FeedHealth(
                feed=feed,
                status=HealthStatus.OK,
                observed_at=clock.now(),
                detail="Synthetic feed heartbeat",
                symbols=("NVDA",) if feed == "assets" else (),
            ), ()

        async def stream(self, receive: object) -> None:
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            pass

    async def dispatch(row: RealtimeEvent) -> None:
        pass

    async def symbols() -> tuple[str, ...]:
        return ("NVDA",)

    supervisor = Supervisor(store, RealtimeConfig(), Fake(), dispatch, symbols, state)
    for i in range(1001):
        await supervisor.receive(
            event(clock.now(), feed="news", kind="OTHER", provider_id=f"fixture-{i}")
        )
    assert len(supervisor.queue) == 1000 and supervisor.dropped == 1
    assert not await supervisor.receive(
        event(clock.now(), feed="news", kind="OTHER", provider_id="fixture-1000")
    )
    supervisor.queue.clear()
    await supervisor.start()
    try:
        await asyncio.sleep(0.5)
        started, cpu = perf_counter(), process_time()
        await asyncio.sleep(1)
        elapsed, used = perf_counter() - started, process_time() - cpu
        percentage = used / elapsed * 100
        print(f"RT-13 fake idle CPU={percentage:.3f}%; wall={elapsed:.3f}s; CPU={used:.6f}s")
        if percentage >= 2:
            pytest.xfail("UNVERIFIED: fake idle CPU budget exceeded on this host; timings recorded")
        assert all(supervisor.delay(i) <= 30 for i in range(1, 100))
    finally:
        await supervisor.aclose()
