"""AX-03/21/22/28/30: real protocol wiring with fake broker and Telegram I/O."""

import asyncio
import ssl
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ApprovalEvent, AutoJobRun, ExecutionFillRecord, TradeTicket
from backend.core.errors import (
    ConfigurationError,
    ExecutionDisabledError,
    ProviderError,
    ReconciliationError,
)
from backend.core.system_state import SystemState
from backend.domain.models import MarketStatus
from backend.execution.alpaca_executor import ManagedTradingStream
from backend.execution.jobs import AutoJobs
from backend.execution.models import Submission
from backend.execution.modes import ModeStore
from backend.net.egress import EgressPolicy, build_allowlist
from backend.notifications.callbacks import CallbackClick
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, click, deliver, make_research_harness

harness = make_research_harness


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
