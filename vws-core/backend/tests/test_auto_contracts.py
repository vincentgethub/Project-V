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
