"""OPS-03: success-only guarded pings; failures remain durable, never green."""

from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import JobRun
from backend.core.errors import ProviderError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import GuardedAsyncClient, make_client
from backend.ops import job_health as module
from backend.ops.job_health import JobHealth
from backend.ops.watchdog import Watchdog


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,status,ping",
    [
        ("PASS", 204, True),
        ("FAIL", 204, False),
        ("SKIPPED", 204, False),
        ("PASS", 302, True),
        ("PASS", 503, True),
        ("PASS", 204, False),
    ],
)
async def test_OPS_03_only_actual_success_ping_and_no_redirects(
    engine: Engine,
    clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    status: int,
    ping: bool,
) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    called: list[str] = []

    async def notify(_text: str) -> None:
        called.append("watchdog_notice")

    url = SecretStr("https://healthchecks.io/ping/TEST_ONLY_NOT_A_CREDENTIAL" if ping else "")
    policy = EgressPolicy(
        build_allowlist(healthcheck_url=url.get_secret_value() or None), state.ledger
    )
    watchdog = Watchdog(state, MarketCalendar(), clock, notify)

    async def check() -> None:
        called.append("watchdog")

    monkeypatch.setattr(watchdog, "check", check)

    def handler(request: httpx.Request) -> httpx.Response:
        called.append("GET")
        assert request.method == "GET"
        return httpx.Response(status, headers={"location": "https://untrusted.invalid/"})

    def factory(purpose: str, **kwargs: Any) -> GuardedAsyncClient:
        assert kwargs["allow_redirects"] is False and kwargs["max_response_bytes"] == 4096
        return make_client(purpose, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module, "make_client", factory)
    run = state.ledger.append(
        JobRun,
        job="position_monitor",
        started_at=clock.now(),
        finished_at=clock.now(),
        outcome=outcome,
        counts={},
        duration_ms=0,
    )
    hook = JobHealth(watchdog, policy, url)
    if status >= 300 and outcome == "PASS" and ping:
        with pytest.raises(ProviderError):
            await hook(run)
        assert called == ["GET"]
    else:
        await hook(run)
        assert called == (["GET", "watchdog"] if outcome == "PASS" and ping else ["watchdog"])
    with Session(engine) as session:
        assert session.scalar(select(JobRun.outcome)) == outcome
