"""Enumerate real panic-root broker calls at the shared sync/async choke point."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.core.system_state import SystemState
from backend.execution.alpaca_executor import ExactLimit, ExactStop
from backend.net.http import make_client
from backend.ops import quiescence
from backend.ops.quiescence import BrokerActor, current_actor
from backend.tests import test_panic_flag_roots as roots
from backend.tests.broker_flag_fakes import FakeFlagAdapter
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_broker_coordination import CountedBroker, FakeSlots
from backend.tests.test_security_cli import MemorySecrets, make_security_context
from backend.tests.test_security_cli import no_native_keyring as no_native_keyring
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from vws import security_cli

harness = make_research_harness
context = make_security_context


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("path", ["panic", "panic-partial", "panic-completed", "manual"])
@pytest.mark.parametrize("with_flag", [False, True])
async def test_F2_every_worker_recovery_cancel_and_stop_call_has_common_hook(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    with_flag: bool,
) -> None:
    events: list[tuple[str, object]] = []
    slots, flag = FakeSlots(), FakeFlagAdapter()
    monkeypatch.setattr(quiescence, "OSSlots", lambda _directory: slots)
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: flag)
    original = BrokerActor.before_broker_call

    def hook(self: BrokerActor) -> Any:
        permit = original(self)
        if self.kind == "panic":
            events.append(("hook", self.identity))
        return permit

    class EnumeratedBroker(CountedBroker):
        def observe(self, kind: str) -> None:
            actor = current_actor()
            if actor is not None:
                assert events and events[-1] == ("hook", actor.identity)
                events.append((kind, actor.identity))

        def get_account(self) -> dict[str, Any]:
            self.observe("account")
            return super().get_account()

        def get_order_by_client_id(self, client_id: str) -> dict[str, Any]:
            self.observe("client-lookup")
            return super().get_order_by_client_id(client_id)

        def get_order_by_id(self, order_id: Any, filter: object = None) -> dict[str, Any]:
            self.observe("order-read")
            return super().get_order_by_id(order_id, filter)

        def get_orders(self, filter: object = None) -> list[dict[str, Any]]:
            self.observe("orders")
            return super().get_orders(filter)

        def get_all_positions(self) -> list[dict[str, Any]]:
            self.observe("positions")
            return super().get_all_positions()

        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            self.observe("stop-submit")
            self.counts["submit"] += 1
            self.submit_calls += 1
            return self._submit_paper(order_data)

        def cancel_order_by_id(self, order_id: Any) -> None:
            self.observe("cancel")
            self.counts["cancel"] += 1
            self._cancel_paper(order_id)

    monkeypatch.setattr(BrokerActor, "before_broker_call", hook)
    monkeypatch.setattr(roots, "CountedBroker", EnumeratedBroker)
    await roots.test_Q1_Q5_Q6_Q16_real_panic_roots_preserve_baseline_counts(
        harness,
        tmp_path,
        monkeypatch,
        (slots, flag),
        path,
        with_flag,
    )
    broker_events = [event for event in events if event[0] != "hook"]
    if path == "manual":
        assert not broker_events
    else:
        assert broker_events
    if path == "panic-partial":
        assert sum(kind == "stop-submit" for kind, _ in broker_events) == 1


@pytest.mark.asyncio
async def test_F2_activity_account_pages_and_order_reads_share_common_hook(
    context: security_cli.SecurityContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.data import fill_polling
    from backend.ops import read_checks
    from backend.tests.test_panic_callbacks import bound

    bound(context, monkeypatch)
    context.state.escalate(SystemState.HALTED, "offline full panic reader")
    slots, flag = FakeSlots(), FakeFlagAdapter()
    slots.held.update(f"slot-{index}" for index in range(8))
    monkeypatch.setattr(quiescence, "OSSlots", lambda _directory: slots)
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: flag)
    events: list[str] = []
    routes: list[str] = []
    original_hook = BrokerActor.before_broker_call

    def hook(self: BrokerActor) -> Any:
        permit = original_hook(self)
        events.append("hook")
        return permit

    def respond(request: httpx.Request) -> httpx.Response:
        assert events[-1] == "hook" and flag.signaled
        events.append("broker")
        routes.append(request.url.path)
        assert request.method == "GET"
        if request.url.path == "/v2/account":
            return httpx.Response(
                200,
                json={
                    "id": "00000000-0000-0000-0000-000000000001",
                    "status": "ACTIVE",
                    "currency": "USD",
                    "buying_power": "10000.00",
                    "equity": "10000.00",
                    "trading_blocked": False,
                    "account_blocked": False,
                    "trade_suspended_by_user": False,
                },
            )
        assert request.url.path in {"/v2/account/activities", "/v2/orders"}
        return httpx.Response(200, json=[])

    original_factory = make_client

    def offline(purpose: str, **kwargs: Any) -> Any:
        kwargs["transport"] = httpx.MockTransport(respond)
        return original_factory(purpose, **kwargs)

    monkeypatch.setattr(BrokerActor, "before_broker_call", hook)
    monkeypatch.setattr(read_checks, "make_client", offline)
    monkeypatch.setattr(fill_polling, "make_client", offline)
    with quiescence.actor_scope(tmp_path, "panic"):
        result = await security_cli.panic_activities(
            context,
            MemorySecrets(),
            context.ledger.clock.now() - timedelta(days=30),
        )
    assert result
    assert routes == ["/v2/account", "/v2/account", "/v2/account/activities", "/v2/orders"]
    assert events == ["hook", "broker"] * 4
    assert flag.signals == 4 and flag.waits == 0
