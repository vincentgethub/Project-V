"""AX-11/16/20..26/31: offline physical-attempt and admission regressions."""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alpaca.common.exceptions import APIError
from pydantic import SecretStr
from requests import HTTPError, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import Settings
from backend.core.database import ExecutionOrderRecord, OrderEvent
from backend.core.errors import (
    ExecutionDisabledError,
    OrderRejectedError,
    ProviderError,
    ReconciliationError,
)
from backend.core.system_state import SystemState
from backend.data.async_reader import AsyncTokenBucket
from backend.data.fill_polling import ObservedFill
from backend.domain.models import Side
from backend.execution.alpaca_executor import (
    AlpacaExecutor,
    ExactLimit,
    ExactStop,
)
from backend.execution.models import AutoPrerequisites
from backend.execution.modes import ModeStore
from backend.execution.worker import SingleAttemptWorker
from backend.net.egress import EgressPolicy, build_allowlist
from backend.tests.test_security_cli import MemorySecrets
from backend.tests.test_swarm_and_callbacks import Harness, click, deliver, make_research_harness

harness = make_research_harness
AUTO = {
    "execution_mode": "AUTO_PAPER",
    "auto_min_score": Decimal("7.5"),
    "broker_api_key": SecretStr("TEST_ONLY_PAPER_ID"),
    "broker_secret_key": SecretStr("TEST_ONLY_PAPER_SECRET"),
    "healthcheck_ping_url": SecretStr("https://hc-ping.com/test-only"),
}


def api_error(status: int) -> APIError:
    response = Response()
    response.status_code = status
    return cast(Callable[..., APIError], APIError)(
        '{"code":0,"message":"synthetic"}', HTTPError(response=response)
    )


class FakeTradingClient:
    """Pinned interface fake; no SDK transport or sockets are created."""

    _base_url = "https://paper-api.alpaca.markets"

    def __init__(self, h: Harness) -> None:
        self.h = h
        self.posts: list[dict[str, Any]] = []
        self.lookups: list[str] = []
        self.orders: dict[str, dict[str, Any]] = {}
        self.failure: str | None = None
        self.raise_fault: str | None = None
        self.positions: list[dict[str, Any]] = []

    def get_account(self) -> dict[str, Any]:
        return {
            "id": "offline-paper",
            "status": "ACTIVE",
            "currency": "USD",
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }

    def get_order_by_client_id(self, client_id: str) -> dict[str, Any]:
        self.lookups.append(client_id)
        if client_id not in self.orders:
            raise api_error(404)
        return self.orders[client_id]

    def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
        fields = order_data.to_request_fields()
        if fields["client_order_id"].startswith("vws-m-"):
            self.failure = None
            if self.raise_fault == "reject-once":
                self.failure, self.raise_fault = "reject", None
            elif self.raise_fault == "reject-both":
                self.failure = "reject"
            elif self.raise_fault in {"accepted-timeout", "ambiguous-missing"}:
                self.failure = self.raise_fault
        self.posts.append(fields)
        if self.failure == "reject":
            raise api_error(422)
        if self.failure == "ambiguous-missing":
            raise TimeoutError("synthetic timeout")
        raw = {
            **fields,
            "id": str(uuid4()),
            "filled_qty": "0",
            "status": "new",
            "submitted_at": self.h.clock.now().isoformat(),
            "legs": None,
        }
        if fields.get("order_class") == "oco":
            raw["limit_price"] = fields["take_profit"]["limit_price"]
        if "stop_loss" in fields:
            specifications = (
                (("limit", fields["take_profit"]), ("stop", fields["stop_loss"]))
                if "take_profit" in fields and fields["order_class"] != "oco"
                else (("stop", fields["stop_loss"]),)
            )
            raw["legs"] = [
                {
                    "id": str(uuid4()),
                    "client_order_id": "generated-" + uuid4().hex,
                    "symbol": fields["symbol"],
                    "side": "sell",
                    "type": kind,
                    "qty": fields["qty"],
                    "filled_qty": "0",
                    "status": "new" if fields["order_class"] == "oco" else "held",
                    "time_in_force": "gtc",
                    "order_class": "simple",
                    "legs": None,
                    "submitted_at": raw["submitted_at"],
                    **price,
                }
                for kind, price in specifications
            ]
        self.orders[fields["client_order_id"]] = raw
        if self.failure == "accepted-timeout":
            raise TimeoutError("synthetic server accepted; response lost")
        return raw

    def cancel_order_by_id(self, order_id: UUID | str) -> None:
        if self.raise_fault == "cancel":
            raise TimeoutError("offline unconfirmed cancellation")
        for raw in self.orders.values():
            if raw["id"] == str(order_id):
                raw["status"] = "canceled"
                for child in raw["legs"] or ():
                    child["status"] = "canceled"
                return
            for child in raw["legs"] or ():
                if child["id"] == str(order_id):
                    for leg in raw["legs"]:
                        leg["status"] = "canceled"
                    return
        raise api_error(404)

    def get_order_by_id(self, order_id: UUID | str, filter: object = None) -> dict[str, Any]:
        for raw in self.orders.values():
            if raw["id"] == str(order_id):
                return raw
            for leg in raw["legs"] or ():
                if leg["id"] == str(order_id):
                    return cast(dict[str, Any], leg)
        raise api_error(404)

    def get_orders(self, filter: object = None) -> list[dict[str, Any]]:
        return list(self.orders.values())

    def get_all_positions(self) -> list[dict[str, Any]]:
        return self.positions


def executor(
    h: Harness,
    client: FakeTradingClient,
    settings: Settings | None = None,
    *,
    constructor: type[AlpacaExecutor] = AlpacaExecutor,
) -> AlpacaExecutor:
    settings = settings or h.settings
    store = MemorySecrets()
    store.set("ALPACA_PAPER_KEY_ID", settings.broker_api_key)
    store.set("ALPACA_PAPER_SECRET", settings.broker_secret_key)
    modes = ModeStore(settings, h.state, "offline-paper")
    proof = AutoPrerequisites(
        account_id=modes.account_id,
        environment="PAPER",
        config_hash=settings.config_hash,
        doctor_fully_green=True,
        watchdog_enabled=True,
        backup_chain_verified=True,
        backup_verified_at=h.clock.now(),
        telegram_verified_at=h.clock.now(),
        clock_verified_at=h.clock.now(),
    )

    async def notify(message: str, urgent: bool) -> None:
        assert message.startswith("PAPER")

    return constructor(
        settings,
        h.config,
        h.state,
        modes,
        h.source,
        h.gate.risk,
        h.gate.compliance,
        h.gate.risk.cro.calendar,
        SingleAttemptWorker(AsyncTokenBucket(h.clock)),
        store,
        proof,
        policy=EgressPolicy(build_allowlist(mode=settings.execution_mode), h.state.ledger),
        notify=notify,
        client=client,
        entry_variant_allowed=lambda: True,  # Explicit offline fixture; never production admission.
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("timeout", [False, True])
async def test_AX_16_double_trigger_and_accepted_timeout_never_duplicate(
    harness: Harness, timeout: bool
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    client.failure = "accepted-timeout" if timeout else None
    first, second = executor(h, client), executor(h, client)
    results = await asyncio.gather(first.enter(alert.proposal_id), second.enter(alert.proposal_id))
    assert len(client.posts) == 1
    assert results[0].broker_order.order_id == results[1].broker_order.order_id
    assert results[0].recovered_after_ambiguity is timeout
    assert h.state.ledger.current_alert_status(alert.id) == "AUTO_APPROVED"
    assert not h.state.ledger.alert_is_actionable(alert.id)
    with Session(h.state.engine) as session:
        rows = tuple(session.scalars(select(ExecutionOrderRecord)))
        assert len(rows) == 3 and rows[0].qty == h.request.candidate.qty
        assert {row.role for row in rows} == {"ENTRY", "TARGET", "STOP"}
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_16_ambiguous_missing_order_halts_without_retry(harness: Harness) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    client.failure = "ambiguous-missing"
    with pytest.raises(ProviderError):
        await executor(harness, client).enter(alert.proposal_id)
    assert len(client.posts) == 1 and len(client.lookups) == 2
    assert harness.state.current() == SystemState.HALTED
    harness.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_confirmed_rejection_records_rejected_without_immediate_halt(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    client.failure = "reject"
    with pytest.raises(OrderRejectedError):
        await executor(harness, client).enter(alert.proposal_id)
    assert len(client.posts) == 1 and harness.state.current() == SystemState.RUNNING
    with Session(harness.state.engine) as session:
        latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()))
        assert latest is not None and latest.state == "REJECTED"
    harness.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_11_downgraded_constructor_refuses_before_client_calls(harness: Harness) -> None:
    h = harness
    ModeStore(h.settings, h.state, "offline-paper").downgrade("MANUAL", actor="owner")
    client = FakeTradingClient(h)
    with pytest.raises(ExecutionDisabledError, match="effective"):
        executor(h, client)
    assert not client.posts and not client.lookups


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "auto_min_score": Decimal("10")}], indirect=True)
async def test_AX_21_lower_score_requires_private_hybrid_click(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    engine = executor(h, client)
    with pytest.raises(ExecutionDisabledError, match="hybrid"):
        await engine.enter(alert.proposal_id)
    with pytest.raises(ExecutionDisabledError, match="authenticated"):
        await engine.enter(alert.proposal_id, click=click(h, "A", user_id=999))
    result = await engine.enter(alert.proposal_id, click=click(h, "A"))
    assert result.proposal_id == alert.proposal_id and len(client.posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_43_stale_backup_refuses_before_client_calls(harness: Harness) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    harness.clock.current += timedelta(hours=26)
    with pytest.raises(ExecutionDisabledError, match="prerequisites"):
        await built.enter(uuid4())
    assert not client.posts and not client.lookups


async def fill_entry(
    h: Harness, client: FakeTradingClient, built: AlpacaExecutor, *, partial: bool = False
) -> tuple[dict[str, Any], ObservedFill]:
    raw = next(row for row in client.orders.values() if row["side"] == "buy")
    qty = 1 if partial else int(raw["qty"])
    raw["filled_qty"], raw["status"] = str(qty), "partially_filled" if partial else "filled"
    for leg in raw["legs"]:
        leg["status"] = "held" if partial else "new"
    client.positions = [
        {"symbol": raw["symbol"], "qty": str(qty), "side": "long", "asset_class": "us_equity"}
    ]
    await built.prepare_fills((raw["symbol"],))
    observed = ObservedFill(
        account_id="offline-paper",
        broker_fill_id="fixture-" + uuid4().hex,
        broker_order_id=UUID(raw["id"]),
        symbol=raw["symbol"],
        side=Side.BUY,
        qty=qty,
        price=Decimal(raw["limit_price"]) - Decimal("0.01"),
        filled_at=h.clock.now(),
    )
    built.observe_fill(observed)
    return raw, observed


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_26_27_known_fill_is_idempotent_and_active_bracket_stop_is_retained(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client, built = FakeTradingClient(h), None
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    _, observed = await fill_entry(h, client, built)
    first, second = built.observe_fill(observed), built.observe_fill(observed)
    assert first.id == second.id
    await built.reconcile()
    await built.monitor()
    assert len(client.posts) == 1
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("state", ["RUNNING", "HALTED", "REDUCE_ONLY", "PAUSE", "MANUAL"])
async def test_AX_24_27_30_partial_parent_canceled_then_stop_repairs_even_when_entries_blocked(
    harness: Harness, state: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)
    if state in {"HALTED", "REDUCE_ONLY"}:
        h.state.escalate(SystemState(state), "fixture state")
    elif state in {"PAUSE", "MANUAL"}:
        built.modes.downgrade("PAUSE" if state == "PAUSE" else "MANUAL", actor="fixture owner")
    await built.monitor()
    assert parent["status"] == "canceled"
    assert len(client.posts) == 2
    assert client.posts[1]["type"] == "stop" and client.posts[1]["qty"] == "1"
    assert client.posts[1]["time_in_force"] == "gtc"
    await built.monitor()
    assert len(client.posts) == 2, "An already confirmed stop must never be duplicated"
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_failed_stop_repair_latches_halt(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    client.failure = "reject"
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == 2 and client.posts[1]["type"] == "stop"
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["position", "order", "qty", "fill-side", "fill-limit"])
async def test_AX_31_reconciliation_faults_and_bad_fills_halt(harness: Harness, fault: str) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    raw, fill = await fill_entry(h, client, built)
    if fault == "fill-side":
        with pytest.raises(ReconciliationError):
            built.observe_fill(
                fill.model_copy(update={"broker_fill_id": "bad-side", "side": Side.SELL})
            )
    elif fault == "fill-limit":
        with pytest.raises(ReconciliationError):
            built.observe_fill(
                fill.model_copy(
                    update={
                        "broker_fill_id": "bad-limit",
                        "price": Decimal(raw["limit_price"]) + Decimal("0.01"),
                    }
                )
            )
    else:
        if fault == "position":
            client.positions.append(
                {"symbol": "AAPL", "qty": "1", "side": "long", "asset_class": "us_equity"}
            )
        elif fault == "qty":
            client.positions[0]["qty"] = str(int(client.positions[0]["qty"]) + 1)
        else:
            unknown = {
                **raw,
                "id": str(uuid4()),
                "client_order_id": "foreign-manual",
                "legs": None,
                "status": "new",
                "filled_qty": "0",
            }
            client.orders["foreign-manual"] = unknown
        with pytest.raises(ReconciliationError):
            await built.reconcile()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == 1
    h.state.ledger.verify_chain()
