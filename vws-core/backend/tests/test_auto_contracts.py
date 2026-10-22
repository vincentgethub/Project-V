"""AX-03/21/22/28/30: real protocol wiring with fake broker and Telegram I/O."""

import asyncio
import copy
import re
import ssl
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import ApprovalEvent, AutoJobRun, ExecutionFillRecord, TradeTicket
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    ExecutionDisabledError,
    ProviderError,
    ReconciliationError,
)
from backend.core.system_state import SystemState
from backend.domain.models import MarketStatus
from backend.execution.alpaca_executor import ExactTakeProfit, ManagedTradingStream
from backend.execution.jobs import AutoJobs
from backend.execution.models import Submission
from backend.execution.modes import ModeStore
from backend.net.egress import EgressPolicy, build_allowlist
from backend.notifications.callbacks import CallbackClick
from backend.tests.test_auto_execution import (
    AUTO,
    FakeTradingClient,
    executor,
    fill_entry,
    journal_existing_partial_repair,
)
from backend.tests.test_swarm_and_callbacks import Harness, click, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.parametrize(
    "status", [None, "new", "held", "suspended", "pending_cancel", "canceled", "filled"]
)
def test_EX_05_durable_repair_guard_requires_live_broker_confirmation(
    clock: FrozenClock, status: str | None
) -> None:
    from backend.execution.alpaca_executor import _require_active_durable_repair, parse_order

    broker = (
        None
        if status is None
        else parse_order(
            {
                "id": str(uuid4()),
                "client_order_id": "offline-durable-stop",
                "symbol": "NVDA",
                "side": "sell",
                "type": "stop",
                "order_class": "simple",
                "time_in_force": "gtc",
                "qty": "1",
                "filled_qty": "1" if status == "filled" else "0",
                "status": status,
                "stop_price": "99.12",
                "limit_price": None,
                "submitted_at": clock.now().isoformat(),
                "legs": None,
            }
        )
    )
    if status == "new":
        _require_active_durable_repair(broker)
    else:
        with pytest.raises(ReconciliationError) as refused:
            _require_active_durable_repair(broker)
        assert type(refused.value) is ReconciliationError
        assert str(refused.value) == "EX-05: durable repair cannot be repeated"


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_28_generated_child_update_is_bound_from_fresh_parent_before_reconciliation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any

    from backend.core.database import ExecutionOrderRecord

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    original_submit = client._submit_paper

    def incomplete_response(request: Any) -> dict[str, Any]:
        raw = original_submit(request)
        return {**raw, "legs": None}

    monkeypatch.setattr(client, "_submit_paper", incomplete_response)
    built = executor(harness, client)
    stream = None
    captured: list[str] = []

    async def capture() -> None:
        captured.append("canonical activities")

    try:
        await built.enter(alert.proposal_id)
        assert len(built._instructions()) == 1
        parent = next(iter(client.orders.values()))
        child = next(row for row in parent["legs"] if row["type"] == "stop")
        stream = ManagedTradingStream(
            built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger), capture
        )
        message = {"stream": "trade_updates", "data": {"event": "new", "order": child}}
        await stream._update(message)
        await stream._update(message)
        assert captured == ["canonical activities", "canonical activities"]
        with Session(harness.state.engine) as session:
            assert len(tuple(session.scalars(select(ExecutionOrderRecord)))) == 3
        assert len(client.posts) == 1
        assert parent["status"] == "new" and all(row["status"] == "held" for row in parent["legs"])
        assert harness.state.current() == SystemState.RUNNING
        harness.state.ledger.verify_chain()
    finally:
        if stream is not None:
            await stream.aclose()
        await built.close()


@pytest.mark.parametrize(
    "known_order,confirmed_absence", [(False, False), (False, True), (True, False)]
)
def test_AX_27_unknown_sell_guard_retains_exact_integrity_failure(
    clock: FrozenClock, known_order: bool, confirmed_absence: bool
) -> None:
    from uuid import uuid4

    from backend.core.errors import ReconciliationError
    from backend.execution.alpaca_executor import _require_known_sell_outcome, parse_order

    broker = (
        parse_order(
            {
                "id": str(uuid4()),
                "client_order_id": "offline-known-stop",
                "symbol": "NVDA",
                "side": "sell",
                "type": "stop",
                "order_class": "simple",
                "time_in_force": "gtc",
                "qty": "1",
                "filled_qty": "0",
                "status": "new",
                "stop_price": "99.12",
                "limit_price": None,
                "submitted_at": clock.now().isoformat(),
                "legs": None,
            }
        )
        if known_order
        else None
    )
    if not known_order and not confirmed_absence:
        with pytest.raises(ReconciliationError) as refused:
            _require_known_sell_outcome(broker, confirmed_absence)
        assert type(refused.value) is ReconciliationError
        assert (
            str(refused.value)
            == "An unknown sell outcome prevents a conflicting stop or replacement"
        )
    else:
        _require_known_sell_outcome(broker, confirmed_absence)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_unfilled_sibling_cannot_arm_a_trailing_stop(harness: Harness) -> None:
    from backend.core.database import ExecutionOrderRecord
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R_TRAIL")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)

    async def unreachable_observation(*args: object) -> object:
        raise AssertionError("Unfilled shares have no completed held observation")

    built.held_exit_observation = unreachable_observation  # type: ignore[assignment]
    await built.enter(alert.proposal_id)
    with Session(harness.state.engine) as session:
        entries = tuple(
            session.scalars(
                select(ExecutionOrderRecord)
                .where(ExecutionOrderRecord.role == "ENTRY")
                .order_by(ExecutionOrderRecord.seq)
            )
        )
    assert len(entries) == 2
    assert built._split_profit_taken(entries[1]) is False
    assert len(client.posts) == 2
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_05_manual_trailing_suggestion_is_single_and_never_submits(
    harness: Harness,
) -> None:
    from backend.core.database import SecurityEvent
    from backend.execution.exit_variants import StopRaiseApproval
    from backend.tests.test_v_stop_raises import entered, target_filled

    built, client, entry = await entered(harness)
    assert entry.stop_price is not None
    await target_filled(harness, built, client)
    built.modes.downgrade("MANUAL", actor="offline owner")
    await built.monitor()
    await built.monitor()
    with Session(harness.state.engine) as session:
        rows = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "STOP_RAISE_SUGGESTED")
            )
        )
        assert len(rows) == 1
        suggested = StopRaiseApproval.recorded(rows[0].detail)
        assert suggested.entry_id == entry.id and suggested.qty == entry.qty
        assert suggested.old_stop == entry.stop_price
        assert suggested.new_stop == entry.stop_price + Decimal(4)
        assert (
            tuple(
                session.scalars(
                    select(SecurityEvent).where(
                        SecurityEvent.kind.in_(("STOP_RAISE_APPROVAL", "STOP_MOVED"))
                    )
                )
            )
            == ()
        )
    assert len(client.posts) == 2
    assert built.modes.effective == "MANUAL"
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["host", "ledger", "sdk_endpoint"])
async def test_AX_28_stream_refuses_cross_account_or_unbound_paper_transport(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from types import SimpleNamespace
    from typing import Any, cast

    from alpaca.trading.stream import TradingStream

    client = FakeTradingClient(harness)
    built = executor(harness, client)
    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger)
    if fault == "host":
        policy = EgressPolicy(frozenset({"data.alpaca.markets"}), harness.state.ledger)
    elif fault == "ledger":
        policy = EgressPolicy(policy.hosts, cast(Any, SimpleNamespace(engine=object())))
    else:
        original = TradingStream.__init__

        def changed_endpoint(self: TradingStream, **kwargs: Any) -> None:
            assert kwargs["paper"] is True and kwargs["raw_data"] is True
            original(self, **kwargs)
            self._endpoint = "wss://unbound.invalid/stream"

        monkeypatch.setattr(TradingStream, "__init__", changed_endpoint)

    async def capture() -> None:
        raise AssertionError("Unbound stream cannot capture account activity")

    with pytest.raises(ConfigurationError) as caught:
        ManagedTradingStream(built, policy, capture)
    assert type(caught.value) is ConfigurationError
    assert str(caught.value) == (
        "Trade stream endpoint differs from its bound account"
        if fault == "sdk_endpoint"
        else "Trade stream account or egress policy differs"
    )
    assert client.posts == [] and client.lookups == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["start_cancel", "consume_cancel", "clean_stop"])
async def test_AX_28_stream_cancellation_and_requested_stop_never_reconnect(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    calls: list[str] = []

    async def capture() -> None:
        raise AssertionError("No update was received")

    stream = ManagedTradingStream(
        built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger), capture
    )

    async def connect() -> None:
        calls.append("connect")
        if fault == "start_cancel":
            raise asyncio.CancelledError("Paper stream task canceled")

    async def consume() -> None:
        calls.append("consume")
        if fault == "consume_cancel":
            raise asyncio.CancelledError("Paper stream task canceled")
        stream._should_run = False

    monkeypatch.setattr(stream, "_start_ws", connect)
    monkeypatch.setattr(stream, "_consume", consume)
    if fault == "clean_stop":
        await stream._run_forever()
    else:
        with pytest.raises(asyncio.CancelledError) as caught:
            await stream._run_forever()
        assert type(caught.value) is asyncio.CancelledError
        assert str(caught.value) == "Paper stream task canceled"
    assert calls == (["connect"] if fault == "start_cancel" else ["connect", "consume"])
    assert harness.state.current() == SystemState.RUNNING
    assert client.posts == [] and client.lookups == []
    await stream.aclose()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("failure", ["authentication", "disconnect"])
async def test_AX_28_retry_budget_is_finite_and_audited(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A broken paper feed must yield to REST protection after three attempts."""
    from backend.core.database import SecurityEvent

    h = harness
    client = FakeTradingClient(h)
    built = executor(h, client)
    attempts: list[str] = []
    delays: list[float] = []
    notices: list[tuple[str, bool]] = []

    async def capture() -> object:
        raise AssertionError("An unauthenticated feed cannot publish fills")

    async def notice(text: str, urgent: bool) -> None:
        notices.append((text, urgent))

    built.notify = notice
    stream = ManagedTradingStream(
        built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger), capture
    )

    async def connect() -> None:
        attempts.append("connect")
        if len(attempts) > 3:
            # A fake broker refuses further work; never let a planted retry loop hang.
            raise asyncio.CancelledError("Paper fake exhausted its three-connection budget")
        if failure == "authentication":
            raise ProviderError("Paper authentication refused")

    async def consume() -> None:
        return None

    async def delay(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(stream, "_start_ws", connect)
    monkeypatch.setattr(stream, "_consume", consume)
    monkeypatch.setattr(asyncio, "sleep", delay)
    await stream.start()
    assert stream._runner is not None
    await stream._runner
    with pytest.raises(ConfigurationError) as caught:
        await stream.start()
    assert type(caught.value) is ConfigurationError
    assert str(caught.value) == "A trade stream cannot be started twice"
    assert attempts == ["connect", "connect", "connect"]
    assert delays == [1, 2]
    with Session(h.state.engine) as session:
        failures = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "TRADE_STREAM_FAILED")
                .order_by(SecurityEvent.seq)
            )
        )
    assert [row.detail for row in failures] == [
        {
            "account_id": "offline-paper",
            "environment": "PAPER",
            "error_type": "ProviderError",
            "attempt": n,
        }
        for n in (1, 2, 3)
    ]
    assert h.state.current() == SystemState.HALTED
    assert notices == [
        ("PAPER · HALTED: trade stream unavailable; REST stop monitoring continues.", True)
    ]
    assert client.posts == []
    await stream.aclose()
    await built.close()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "findings,message",
    [
        (None, "EX-06: live paper-raise and OCO/OTO integration evidence unavailable"),
        ([], "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (("",), "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (("x" * 501,), "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (("missing",) * 51, "EX-06: typed paper-raise evidence is UNVERIFIED"),
        (
            ("OCO unproved", "29 paper raises"),
            "EX-06: live stop raises locked: OCO unproved; 29 paper raises",
        ),
    ],
)
async def test_EX_06_live_raise_refusal_keeps_exact_audit_reason(
    harness: Harness, findings: object, message: str
) -> None:
    from typing import Any, cast

    client = FakeTradingClient(harness)
    built = executor(harness, client)
    if findings is not None:
        built.stop_raise_readiness = cast(Any, lambda: findings)
    with pytest.raises(ExecutionDisabledError) as caught:
        built._assert_live_raises()
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == message
    assert client.posts == [] and client.lookups == []
    assert built.environment == "PAPER"
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_06_empty_verified_raise_findings_allow_only_the_guard(harness: Harness) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    built.stop_raise_readiness = lambda: ()
    built._assert_live_raises()
    assert built.environment == "PAPER" and client.posts == []
    await built.close()


@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault", [None, "manual", "endpoint_type", "session_type", "missing_retry"]
)
def test_AX_15_paper_transport_binding_is_atomic_and_closes_old_session(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    from types import SimpleNamespace
    from typing import Any, cast

    from alpaca.trading.client import TradingClient

    from backend.execution.alpaca_executor import configure_execution_client

    h = harness
    closed: list[bool] = []
    session = TradingClient(
        api_key="TEST_ONLY_PAPER_ID", secret_key="TEST_ONLY_PAPER_SECRET", paper=True, raw_data=True
    )._session
    monkeypatch.setattr(session, "close", lambda: closed.append(True))
    client = SimpleNamespace(
        _base_url="https://paper-api.alpaca.markets",
        _session=session,
        _retry=10,
        _use_raw_data=False,
    )
    settings = h.settings
    if fault == "manual":
        settings = settings.model_copy(update={"execution_mode": "MANUAL"})
    elif fault == "endpoint_type":
        client._base_url = None
    elif fault == "session_type":
        client._session = object()
    elif fault == "missing_retry":
        del client._retry
    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger)
    if fault:
        expected = (
            "MANUAL cannot acquire an order transport"
            if fault == "manual"
            else "Pinned Alpaca SDK transport contract changed"
        )
        with pytest.raises(ConfigurationError) as caught:
            configure_execution_client(
                cast(Any, client), settings, policy, before_request=lambda: None
            )
        assert str(caught.value) == expected
        assert type(caught.value) is ConfigurationError
        assert closed == []
    else:
        configure_execution_client(cast(Any, client), settings, policy, before_request=lambda: None)
        assert closed == [True]
        assert client._session is not session
        assert client._retry == 0 and client._use_raw_data is True
        assert client._session.trust_env is False
        client._session.close()


@pytest.mark.parametrize("harness", [AUTO], indirect=True)
def test_AX_15_factory_closes_paper_session_when_endpoint_binding_fails(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import backend.execution.alpaca_executor as implementation

    closed: list[bool] = []
    client = SimpleNamespace(
        _base_url=None, _session=SimpleNamespace(close=lambda: closed.append(True)), _retry=0
    )

    def paper_client(**kwargs: object) -> object:
        assert kwargs["paper"] is True and kwargs["raw_data"] is True
        return client

    monkeypatch.setattr(implementation, "TradingClient", paper_client)
    with pytest.raises(ConfigurationError) as caught:
        implementation.make_execution_client(
            harness.settings,
            EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger),
            before_request=lambda: None,
        )
    assert type(caught.value) is ConfigurationError
    assert str(caught.value) == "Pinned Alpaca SDK transport contract changed"
    assert closed == [True]


@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("manual", [False, True])
def test_AX_15_client_factory_never_constructs_manual_or_nonpaper_transport(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, manual: bool
) -> None:
    from typing import Any

    from alpaca.trading.client import TradingClient

    import backend.execution.alpaca_executor as implementation

    calls: list[dict[str, Any]] = []
    original = TradingClient

    def paper_client(**kwargs: Any) -> TradingClient:
        assert kwargs == {
            "api_key": "TEST_ONLY_PAPER_ID",
            "secret_key": "TEST_ONLY_PAPER_SECRET",
            "paper": True,
            "raw_data": True,
        }
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(implementation, "TradingClient", paper_client)
    settings = (
        harness.settings.model_copy(update={"execution_mode": "MANUAL"})
        if manual
        else harness.settings
    )
    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger)
    if manual:
        with pytest.raises(ConfigurationError) as caught:
            implementation.make_execution_client(settings, policy, before_request=lambda: None)
        assert str(caught.value) == "MANUAL cannot create an execution client"
        assert type(caught.value) is ConfigurationError
        assert calls == []
    else:
        client = implementation.make_execution_client(settings, policy, before_request=lambda: None)
        assert len(calls) == 1
        assert (
            getattr(client._base_url, "value", client._base_url)
            == "https://paper-api.alpaca.markets"
        )
        assert client._retry == 0 and client._use_raw_data is True
        client._session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "same_root",
        "manual",
        "status",
        "currency",
        "id",
        "trading_blocked",
        "account_blocked",
        "trade_suspended_by_user",
        "oto_status",
        "oco_status",
        "stop_status",
        "changed_child",
        "wrong_root",
    ],
)
async def test_EX_06_paper_cancel_inspection_uses_only_fresh_bound_gets(
    harness: Harness, fault: str | None
) -> None:
    from typing import Any
    from uuid import UUID

    from backend.core.errors import DataIntegrityError
    from backend.execution.alpaca_executor import inspect_paper_cancel_semantics

    h = harness
    root_ids = (UUID(int=710), UUID(int=720))
    stop_ids = (UUID(int=711), UUID(int=721))
    records: dict[UUID, dict[str, Any]] = {}
    reads: list[tuple[UUID, object]] = []
    for root_id, stop_id, side, kind in zip(
        root_ids, stop_ids, ("buy", "sell"), ("oto", "oco"), strict=True
    ):
        stop = {
            "id": str(stop_id),
            "client_order_id": "paper-stop-" + str(stop_id),
            "symbol": "NVDA",
            "side": "sell",
            "type": "stop",
            "order_class": "simple",
            "qty": "1",
            "filled_qty": "0",
            "status": "canceled",
            "time_in_force": "gtc",
            "stop_price": "90.00",
            "submitted_at": h.clock.now().isoformat(),
            "legs": None,
        }
        records[stop_id] = stop
        records[root_id] = {
            **stop,
            "id": str(root_id),
            "client_order_id": "paper-root-" + str(root_id),
            "side": side,
            "type": "limit",
            "order_class": kind,
            "limit_price": "100.00",
            "stop_price": None,
            "legs": [dict(stop)],
        }
    account = FakeTradingClient(h).get_account()
    if fault in {
        "status",
        "currency",
        "id",
        "trading_blocked",
        "account_blocked",
        "trade_suspended_by_user",
    }:
        account[fault] = {"status": "INACTIVE", "currency": "CAD", "id": 1}.get(fault, True)
    elif fault == "oto_status":
        records[root_ids[0]]["status"] = "new"
    elif fault == "oco_status":
        records[root_ids[1]]["status"] = "new"
    elif fault == "stop_status":
        records[stop_ids[0]]["status"] = "new"
        records[root_ids[0]]["legs"][0]["status"] = "new"
    elif fault == "changed_child":
        records[stop_ids[0]]["stop_price"] = "91.00"
    elif fault == "wrong_root":
        records[root_ids[0]]["id"] = str(uuid4())

    class PaperReader:
        async def run(self, operation: Any) -> Any:
            return operation()

    class PaperBroker:
        _base_url = "https://paper-api.alpaca.markets"

        def get_account(self) -> dict[str, Any]:
            return account

        def get_order_by_id(self, identity: UUID, filter: object = None) -> object:
            reads.append((identity, filter))
            return records[identity]

    settings = (
        h.settings.model_copy(update={"execution_mode": "MANUAL"})
        if fault == "manual"
        else h.settings
    )
    second = root_ids[0] if fault == "same_root" else root_ids[1]
    if fault:
        error_type: type[Exception]
        if fault in {"manual", "same_root"}:
            error_type, message = (
                ExecutionDisabledError,
                "EX-06: two distinct explicit AUTO_PAPER roots required",
            )
        elif fault in {
            "status",
            "currency",
            "id",
            "trading_blocked",
            "account_blocked",
            "trade_suspended_by_user",
        }:
            error_type, message = (
                ReconciliationError,
                "EX-06: bound active USD paper account unavailable",
            )
        elif fault == "wrong_root":
            error_type, message = (
                DataIntegrityError,
                "EX-06: root must expose its one actual stop leg",
            )
        elif fault in {"stop_status", "changed_child"}:
            error_type, message = (
                DataIntegrityError,
                "EX-06: fresh generated stop cancellation differs",
            )
        else:
            error_type, message = (
                DataIntegrityError,
                "EX-06: OTO stop and OCO siblings not proved canceled",
            )
        with pytest.raises(error_type) as caught:
            await inspect_paper_cancel_semantics(
                settings, PaperReader(), PaperBroker(), root_ids[0], second
            )
        assert str(caught.value) == message
        assert type(caught.value) is error_type
    else:
        oto, oco = await inspect_paper_cancel_semantics(
            settings, PaperReader(), PaperBroker(), *root_ids
        )
        assert (oto.order_id, oco.order_id) == root_ids
        assert (oto.legs[0].order_id, oco.legs[0].order_id) == stop_ids
        assert [identity for identity, _ in reads] == [
            root_ids[0],
            stop_ids[0],
            root_ids[1],
            stop_ids[1],
        ]
        assert [getattr(options, "nested", None) for _, options in reads] == [
            True,
            None,
            True,
            None,
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_21_parallel_veto_during_refresh_preserves_the_human_decision(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)

    def veto() -> None:
        h.state.ledger.append(
            ApprovalEvent, alert_id=alert.id, action="USER_VETOED", telegram_user_id=123, reasons=[]
        )
        h.source.inputs = h.source.inputs.model_copy(
            update={
                "market": h.source.inputs.market.model_copy(update={"status": MarketStatus.SUSPECT})
            }
        )

    h.source.hook = veto

    async def ack(text: str) -> None:
        assert text == "Re-checking…"

    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "FAILED" and h.state.ledger.current_alert_status(alert.id) == "REJECTED"
    assert not client.posts
    assert h.state.current() == SystemState.RUNNING
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_21_missing_lifecycle_on_refusal_is_a_durable_fault(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import UUID

    from sqlalchemy.orm import Session

    h = harness
    await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)

    def missing(session: Session, alert_id: UUID) -> None:
        return None

    async def refused(proposal_id: UUID, *, click: CallbackClick | None = None) -> Submission:
        monkeypatch.setattr(h.state.ledger, "_latest_alert_event", missing)
        raise ExecutionDisabledError("Synthetic missing lifecycle at refusal boundary")

    monkeypatch.setattr(built, "enter", refused)

    async def ack(text: str) -> None:
        assert text == "Re-checking…"

    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "FAILED" and h.state.current() == SystemState.HALTED
    assert not client.posts


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "auto_min_score": Decimal("10")}], indirect=True)
@pytest.mark.parametrize("failure", ["fresh_veto", "broker_rejection"])
async def test_AX_21_refused_hybrid_click_is_consumed_without_retry(
    harness: Harness, failure: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)
    if failure == "fresh_veto":
        built.modes.downgrade("PAUSE", actor="offline owner")
    else:
        client.failure = "reject"

    async def ack(text: str) -> None:
        assert text == "Re-checking…"

    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "FAILED"
    assert h.state.ledger.current_alert_status(alert.id) == (
        "REVALIDATION_FAILED" if failure == "fresh_veto" else "AUTO_APPROVED"
    )
    duplicate = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert duplicate.status == "HANDLED"
    assert len(client.posts) == (0 if failure == "fresh_veto" else 1)
    with Session(h.state.engine) as session:
        approvals = tuple(session.scalars(select(ApprovalEvent)))
        assert len(approvals) == (1 if failure == "fresh_veto" else 0)
        assert session.scalar(select(TradeTicket)) is None
    assert h.state.current() == SystemState.RUNNING
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "telegram_mask_amounts": True}], indirect=True)
async def test_SEC_53_hybrid_acknowledgement_masks_share_count(harness: Harness) -> None:
    h = harness
    await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)

    async def ack(text: str) -> None:
        assert text == "Re-checking…"

    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "AUTO_SUBMITTED" and result.text is not None
    assert "Submitted ••• NVDA BUY LIMIT" in result.text
    assert f"Submitted {h.request.candidate.qty} " not in result.text
    assert len(client.posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "binding", ["missing_modes", "missing_executor", "rebound", "wrong_policy"]
)
async def test_AX_11_invalid_approval_binding_never_places_order(
    harness: Harness, binding: str
) -> None:
    h = harness
    await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    if binding == "wrong_policy":
        changed = h.settings.model_copy(update={"auto_min_score": Decimal("10")})
        with pytest.raises(ConfigurationError, match="binding differs"):
            h.gate.bind_auto(built, ModeStore(changed, h.state, "offline-paper"))
    elif binding == "rebound":
        h.gate.bind_auto(built, built.modes)
        with pytest.raises(ConfigurationError, match="binding differs"):
            h.gate.bind_auto(built, built.modes)
    else:
        if binding == "missing_executor":
            h.gate.modes = built.modes

        async def ack(text: str) -> None:
            assert text == "Re-checking…"

        result = await h.gate.handle(click(h, "A"), acknowledge=ack)
        assert result.status == "FAILED" and h.state.current() == SystemState.HALTED
    assert not client.posts


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_28_stream_stops_after_three_auth_failures_and_rest_monitor_survives(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    client = FakeTradingClient(h)
    built = executor(h, client)
    attempts = []

    async def sync() -> object:
        raise AssertionError("Failed authentication cannot publish fills")

    stream = ManagedTradingStream(
        built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger), sync
    )

    async def refused() -> None:
        attempts.append("auth")
        if len(attempts) > 3:
            raise asyncio.CancelledError("Paper fake exhausted its three-connection budget")
        raise ProviderError("Synthetic stream authentication refusal")

    async def no_delay(seconds: float) -> None:
        assert seconds in {1, 2}

    monkeypatch.setattr(stream, "_start_ws", refused)
    monkeypatch.setattr(asyncio, "sleep", no_delay)
    await stream._run_forever()
    assert attempts == ["auth"] * 3 and h.state.current() == SystemState.HALTED
    assert not client.posts
    # REST still performs bounded reconciliation after stream failure.
    await built.monitor()
    await stream.aclose()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_21_real_approval_gate_submits_once_and_never_creates_ticket(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)
    acknowledged = []

    async def ack(text: str) -> None:
        acknowledged.append(text)

    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "AUTO_SUBMITTED" and result.text is not None
    assert "PAPER" in result.text and "LIMIT" in result.text
    assert acknowledged == ["Re-checking…"] and len(client.posts) == 1
    assert h.state.ledger.current_alert_status(alert.id) == "AUTO_APPROVED"
    duplicate = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert duplicate.status == "HANDLED" and len(client.posts) == 1
    with Session(h.state.engine) as session:
        assert session.scalar(select(TradeTicket)) is None
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_03_persisted_manual_downgrade_returns_ticket_without_order(
    harness: Harness,
) -> None:
    h = harness
    await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)
    built.modes.downgrade("MANUAL", actor="offline owner")

    async def ack(text: str) -> None:
        pass

    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "TICKET" and len(client.posts) == 0
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_22_scheduled_double_tick_has_one_bound_session_run(harness: Harness) -> None:
    h = harness
    await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    captures = []

    async def sync() -> object:
        captures.append("activity")
        return None

    jobs = AutoJobs(h.settings, built.modes, built.calendar, built, sync)
    await asyncio.gather(jobs.tick("auto_entry"), jobs.tick("auto_entry"))
    assert len(client.posts) == 1 and len(captures) == 1
    with Session(h.state.engine) as session:
        rows = tuple(session.scalars(select(AutoJobRun)))
        assert len(rows) == 1 and rows[0].outcome == "PASS"
        assert rows[0].account_id == "offline-paper" and rows[0].environment == "PAPER"
        assert rows[0].counts == {"submitted": 1, "refused": 0}
    assert not jobs.due("auto_entry", h.clock.now() + timedelta(minutes=1))
    assert jobs.due(
        "auto_poll", built.calendar.session_close(h.clock.now().date()) + timedelta(minutes=1)
    )
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_30_poll_capture_failure_does_not_suppress_stop_repair(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    journal_existing_partial_repair(built)

    async def sync() -> object:
        h.state.halt_for_error(ProviderError("synthetic poll fault"))
        raise ProviderError("synthetic poll fault")

    jobs = AutoJobs(h.settings, built.modes, built.calendar, built, sync)
    await jobs.tick("auto_poll")
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
    with Session(h.state.engine) as session:
        run = session.scalar(select(AutoJobRun))
        assert run is not None and run.outcome == "FAIL"
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_28_stream_reuses_canonical_capture_and_reconciles_duplicate_notification(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built)
    calls = []

    async def sync() -> object:
        calls.append("canonical activities")
        return None

    stream = ManagedTradingStream(
        built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger), sync
    )
    context = stream._websocket_params["ssl"]
    assert (
        isinstance(context, ssl.SSLContext)
        and context.verify_mode == ssl.CERT_REQUIRED
        and context.check_hostname
    )
    assert (
        stream._websocket_params["max_queue"] == 64
        and stream._websocket_params["max_size"] == 1_048_576
    )
    message = {"stream": "trade_updates", "data": {"event": "fill", "order": parent}}
    await stream._update(message)
    await stream._update(message)
    assert len(calls) == 2 and len(client.posts) == 1
    with Session(h.state.engine) as session:
        assert len(tuple(session.scalars(select(ExecutionFillRecord)))) == 1
    await stream.aclose()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["envelope", "event", "foreign_order"])
async def test_AX_28_stream_unknown_evidence_halts_without_order(
    harness: Harness, fault: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent = next(iter(client.orders.values()))
    message: object = {"stream": "trade_updates", "data": {"event": "new", "order": parent}}
    if fault == "envelope":
        message = {"stream": "unknown"}
    elif fault == "event":
        message = {"stream": "trade_updates", "data": {"event": "untrusted", "order": parent}}
    else:
        message = {
            "stream": "trade_updates",
            "data": {
                "event": "new",
                "order": {**parent, "id": str(uuid4()), "client_order_id": "foreign-manual"},
            },
        }

    async def sync() -> object:
        raise AssertionError("Invalid evidence must not reach canonical capture")

    stream = ManagedTradingStream(
        built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger), sync
    )
    with pytest.raises(ReconciliationError):
        await stream._update(message)
    assert h.state.current() == SystemState.HALTED and len(client.posts) == 1
    await stream.aclose()
    h.state.ledger.verify_chain()


def test_AX_take_profit_serializes_whole_dollars_with_exact_cents() -> None:
    assert ExactTakeProfit(limit_price=Decimal("105")).to_request_fields() == {
        "limit_price": "105.00"
    }


@pytest.mark.parametrize(
    "harness",
    [{**AUTO, "telegram_mask_amounts": True}, {**AUTO, "telegram_mask_amounts": False}],
    indirect=True,
)
def test_AX_trade_notice_quantity_obeys_the_amount_mask(harness: Harness) -> None:
    built = executor(harness, FakeTradingClient(harness))
    assert built._quantity(9) == ("•" * 3 if harness.settings.telegram_mask_amounts else "9")


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_stale_exit_snapshot_has_exact_refusal_and_keeps_existing_orders(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    try:
        await built.enter(alert.proposal_id)
        entry = built._instructions()[0]
        before = copy.deepcopy(client.orders)
        h.source.inputs = h.source.inputs.model_copy(
            update={
                "portfolio": h.source.inputs.portfolio.model_copy(
                    update={
                        "as_of": h.clock.now()
                        - timedelta(seconds=h.settings.stale_quote_seconds + 1)
                    }
                )
            }
        )
        message = "A fresh bound IEX quote and broker snapshot are required for an exit limit"
        with pytest.raises(ExecutionDisabledError, match=re.escape(message)) as caught:
            await built._fresh_exit_inputs(entry)
        assert type(caught.value) is ExecutionDisabledError and str(caught.value) == message
        assert client.orders == before and len(client.posts) == 1
        h.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_foreign_manual_broker_order_has_exact_reconciliation_refusal(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    try:
        await built.enter(alert.proposal_id)
        parent = next(iter(client.orders.values()))
        foreign = {
            **parent,
            "id": str(uuid4()),
            "client_order_id": "unbound-manual-order",
            "legs": None,
        }
        client.orders[foreign["id"]] = foreign
        message = "Unknown broker order; manual trading belongs in a different account"
        with pytest.raises(ReconciliationError, match=re.escape(message)) as caught:
            await built._reconcile()
        with pytest.raises(
            ReconciliationError, match=re.escape("Broker reconciliation failed closed")
        ):
            await built.reconcile()
        assert type(caught.value) is ReconciliationError and str(caught.value) == message
        assert h.state.current() == SystemState.HALTED and len(client.posts) == 1
        h.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("event", ["partial_fill", "canceled", "rejected"])
async def test_AX_trade_stream_accepts_each_real_entry_event_without_false_halt(
    harness: Harness, event: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    stream = None
    captures: list[Any] = []
    try:
        await built.enter(alert.proposal_id)
        if event == "partial_fill":
            parent, _ = await fill_entry(h, client, built, partial=True)
            parent = copy.deepcopy(parent)
            journal_existing_partial_repair(built)
            await built.monitor()
        else:
            parent = next(iter(client.orders.values()))
            parent["status"] = event

        async def capture() -> None:
            captures.append(event)

        stream = ManagedTradingStream(
            built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger), capture
        )
        await stream._update({"stream": "trade_updates", "data": {"event": event, "order": parent}})
        assert captures == [event] and h.state.current() == SystemState.RUNNING
        assert len(client.posts) == (2 if event == "partial_fill" else 1)
        assert sum(row["side"] == "buy" for row in client.posts) == 1
        h.state.ledger.verify_chain()
    finally:
        if stream is not None:
            await stream.aclose()
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_unknown_stream_event_keeps_the_exact_integrity_fault(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    client = FakeTradingClient(h)
    built = executor(h, client)
    stream = None
    errors: list[Any] = []
    halt = h.state.halt_for_error

    def record(error: Exception) -> None:
        errors.append(error)
        halt(error)

    monkeypatch.setattr(h.state, "halt_for_error", record)

    async def capture() -> None:
        raise AssertionError("Unknown events must not capture fills")

    try:
        stream = ManagedTradingStream(
            built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger), capture
        )
        with pytest.raises(ReconciliationError, match=re.escape("Trade update failed closed")):
            await stream._update({"stream": "trade_updates", "data": {"event": "unknown"}})
        assert len(errors) == 1 and type(errors[0]) is DataIntegrityError
        assert str(errors[0]) == "Trade update event is unknown"
        assert h.state.current() == SystemState.HALTED and client.posts == []
        h.state.ledger.verify_chain()
    finally:
        if stream is not None:
            await stream.aclose()
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_monitor_cross_account_snapshot_records_the_exact_fault(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    client = FakeTradingClient(h)
    built = executor(h, client)
    errors: list[Any] = []
    halt = h.state.halt_for_error

    async def wrong_account() -> Any:
        return h.source.inputs.portfolio.model_copy(update={"account_id": "another-paper-account"})

    def record(error: Exception) -> None:
        errors.append(error)
        halt(error)

    built.portfolio = wrong_account
    monkeypatch.setattr(h.state, "halt_for_error", record)
    try:
        await built.monitor()
        assert len(errors) == 1 and type(errors[0]) is ReconciliationError
        assert str(errors[0]) == "Monitor snapshot account differs"
        assert h.state.current() == SystemState.HALTED and (not built.modes.entries_enabled)
        assert client.posts == []
        h.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_stream_constructor_binds_both_paper_credentials_and_keepalive(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpaca.trading.stream import TradingStream

    h = harness
    built = executor(h, FakeTradingClient(h))
    recorded: list[Any] = []
    original = TradingStream.__init__
    stream = None

    def record(self: Any, **kwargs: Any) -> None:
        recorded.append(kwargs)
        original(self, **kwargs)

    monkeypatch.setattr(TradingStream, "__init__", record)

    async def capture() -> None:
        return None

    try:
        assert h.settings.broker_api_key is not None and h.settings.broker_secret_key is not None
        stream = ManagedTradingStream(
            built, EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger), capture
        )
        assert len(recorded) == 1
        assert recorded[0]["api_key"] == h.settings.broker_api_key.get_secret_value()
        assert recorded[0]["secret_key"] == h.settings.broker_secret_key.get_secret_value()
        assert recorded[0]["paper"] is True and recorded[0]["raw_data"] is True
        assert recorded[0]["websocket_params"]["ping_interval"] == 10
        assert recorded[0]["websocket_params"]["ping_timeout"] == 20
    finally:
        if stream is not None:
            await stream.aclose()
        await built.close()


@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["user", "chat_type", "chat", "message", "wire"])
@pytest.mark.asyncio
async def test_AX_hybrid_approval_refuses_each_bad_binding_with_exact_message(
    harness: Harness, fault: str
) -> None:
    from backend.tests.test_swarm_and_callbacks import click

    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    changes: dict[str, dict[str, Any]] = {
        "user": {"user_id": 999},
        "chat_type": {"chat_type": "group"},
        "chat": {"chat_id": 999},
        "message": {"message_id": 999},
        "wire": {"data": "invalid-wire"},
    }
    try:
        message = "Hybrid approval is not privately authenticated and message-bound"
        with pytest.raises(ExecutionDisabledError, match=re.escape(message)) as caught:
            built._loaded(alert.proposal_id, click(h, "A", **changes[fault]))
        assert type(caught.value) is ExecutionDisabledError and str(caught.value) == message
        assert client.posts == []
        h.state.ledger.verify_chain()
    finally:
        await built.close()
