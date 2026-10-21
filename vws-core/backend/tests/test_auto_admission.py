"""AX-25/31/42: actual admission and monitor boundary faults, no network."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.core.config import Settings
from backend.core.database import Order
from backend.core.errors import ExecutionDisabledError
from backend.core.system_state import SystemState
from backend.domain.compliance_models import TradeRecord
from backend.domain.models import PortfolioSnapshot, Position, Side
from backend.execution.policy import live_ceiling_reasons
from backend.tests.test_auto_execution import (
    AUTO,
    FakeTradingClient,
    executor,
    fill_entry,
    journal_existing_partial_repair,
)
from backend.tests.test_domain import proposal as make_proposal
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_final_cro_keeps_registry_and_additional_blackout_policy_on_a_clear_entry(
    harness: Harness,
) -> None:
    from backend.domain.instruments import InstrumentRegistry
    from backend.domain.models import BlackoutWindow
    from backend.risk.risk_cro import ChiefRiskOfficer

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    original = built.risk.cro.registry
    registry_window = BlackoutWindow(
        start=harness.clock.now() + timedelta(days=1),
        end=harness.clock.now() + timedelta(days=2),
        reason="offline registry window",
    )
    explicit_window = registry_window.model_copy(update={"reason": "offline explicit window"})
    groups = {
        tuple(sorted(original.identical_group(symbol)))
        for symbol in original.symbols
        if len(original.identical_group(symbol)) > 1
    }
    registry = InstrumentRegistry(
        [original.get(symbol) for symbol in original.symbols],
        etf_weights=original._weights,
        identical_groups={f"group-{index}": group for index, group in enumerate(sorted(groups))},
        blackout_windows=(registry_window,),
    )
    built.risk.cro = ChiefRiskOfficer(
        built.risk.cro.config,
        registry,
        built.risk.cro.calendar,
        blackout_windows=(explicit_window,),
    )
    built.risk.additional_blackouts = lambda: ()
    try:
        await built.enter(alert.proposal_id)
        assert len(client.posts) == 1 and client.posts[0]["side"] == "buy"
        assert harness.state.current() == SystemState.RUNNING
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("persisted_marks", [False, True])
async def test_final_pure_cro_approval_has_no_database_io_before_broker_submit(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    persisted_marks: bool,
) -> None:
    from typing import Any

    from sqlalchemy import event

    from backend.domain.models import Decision, TradeProposal, Verdict
    from backend.execution.alpaca_executor import ExactLimit, ExactStop
    from backend.risk.risk_cro import ChiefRiskOfficer

    alert = await deliver(harness)
    cro_calls = 0
    armed = False
    submitted = False
    evaluate = ChiefRiskOfficer.evaluate

    def observed_evaluate(
        officer: ChiefRiskOfficer, proposal: TradeProposal, *args: Any, **kwargs: Any
    ) -> Verdict:
        nonlocal cro_calls, armed
        verdict = evaluate(officer, proposal, *args, **kwargs)
        if proposal.proposal_id == alert.proposal_id:
            cro_calls += 1
            if cro_calls == 2:
                assert verdict.decision == Decision.APPROVED
                armed = True
        return verdict

    def reject_intervening_io(*args: Any, **kwargs: Any) -> None:
        assert not armed, "Database I/O occurred between final pure CRO approval and broker submit"

    class GuardedPaperBroker(FakeTradingClient):
        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            nonlocal armed, submitted
            assert armed and cro_calls == 2
            armed, submitted = False, True
            return super()._submit_paper(order_data)

    client = GuardedPaperBroker(harness)
    built = executor(harness, client)
    if not persisted_marks:
        built.risk.marks = None
    monkeypatch.setattr(ChiefRiskOfficer, "evaluate", observed_evaluate)
    event.listen(harness.state.engine, "before_cursor_execute", reject_intervening_io)
    try:
        await built.enter(alert.proposal_id)
        assert submitted and len(client.posts) == 1 and cro_calls == 2
        harness.state.ledger.verify_chain()
    finally:
        armed = False
        event.remove(harness.state.engine, "before_cursor_execute", reject_intervening_io)
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["mutable_windows", "excess_windows", "missing_stop"])
async def test_final_cro_refuses_changed_unverifiable_policy_or_request_before_send(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    from typing import Any, cast

    from backend.core.errors import ProviderError
    from backend.domain.models import BlackoutWindow, TradeProposal
    from backend.execution.alpaca_executor import ExactLimit

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    changed = False
    original_lookup = built._lookup
    window = BlackoutWindow(
        start=harness.clock.now() + timedelta(days=1),
        end=harness.clock.now() + timedelta(days=2),
        reason="offline dynamic evidence",
    )

    def windows() -> tuple[BlackoutWindow, ...]:
        if not changed:
            return ()
        return (
            cast(tuple[BlackoutWindow, ...], []) if fault == "mutable_windows" else (window,) * 501
        )

    async def late_change(client_id: str) -> Any:
        nonlocal changed
        changed = True
        return await original_lookup(client_id)

    if fault == "missing_stop":
        original_requests = built._entry_requests

        def incomplete_request(proposal: TradeProposal) -> tuple[ExactLimit, ...]:
            return tuple(
                request.model_copy(update={"stop_loss": None})
                for request in original_requests(proposal)
            )

        monkeypatch.setattr(built, "_entry_requests", incomplete_request)
    else:
        built.risk.additional_blackouts = windows
    monkeypatch.setattr(built, "_lookup", late_change)
    try:
        with pytest.raises(ProviderError) as refusal:
            await built.enter(alert.proposal_id)
        assert type(refusal.value) is ProviderError
        assert str(refusal.value) == "Automatic entry failed closed; inspect persisted intent"
        assert client.posts == []
        assert harness.state.current() == SystemState.HALTED
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


def test_physical_submit_guard_has_no_await_or_io_after_approval() -> None:
    """The final synchronous guard hands control directly to physical submit."""
    import ast
    import inspect
    import textwrap

    from backend.execution.alpaca_executor import AlpacaExecutor
    from backend.execution.worker import SingleAttemptWorker

    enter = ast.parse(textwrap.dedent(inspect.getsource(AlpacaExecutor.enter)))
    guard = next(
        node
        for node in ast.walk(enter)
        if isinstance(node, ast.FunctionDef) and node.name == "submit_guard"
    )
    assert not any(
        isinstance(node, (ast.Await, ast.AsyncWith, ast.AsyncFor)) for node in ast.walk(guard)
    )
    final = guard.body[-1]
    assert isinstance(final, ast.If)
    evaluation = next(
        index
        for index, node in enumerate(final.body)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "evaluate"
    )
    # Only pure verdict validation and the veto-only branch follow the final
    # evaluation; durable observations have already finished.
    following = final.body[evaluation + 1 :]
    assert len(following) == 2 and isinstance(following[0], ast.Assign)
    checked = following[0].value
    assert isinstance(checked, ast.Call) and isinstance(checked.func, ast.Attribute)
    assert checked.func.attr == "_checked" and isinstance(following[1], ast.If)
    worker = ast.parse(textwrap.dedent(inspect.getsource(SingleAttemptWorker.attempt)))
    work = next(
        node
        for node in ast.walk(worker)
        if isinstance(node, ast.FunctionDef) and node.name == "work"
    )
    assert not any(isinstance(node, ast.Await) for node in ast.walk(work))
    guarded = next(node for node in work.body if isinstance(node, ast.Try))
    assert len(guarded.body) == 2
    assert isinstance(guarded.body[0], ast.Expr) and isinstance(guarded.body[0].value, ast.Call)
    assert (
        isinstance(guarded.body[0].value.func, ast.Name)
        and guarded.body[0].value.func.id == "guard"
    )
    assert isinstance(guarded.body[1], ast.Return) and isinstance(guarded.body[1].value, ast.Call)
    assert (
        isinstance(guarded.body[1].value.func, ast.Name)
        and guarded.body[1].value.func.id == "operation"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "blocker", ["CRO-01", "CRO-09", "CRO-10", "CRO-11", "CRO-12", "CRO-13", "clear"]
)
async def test_final_full_cro_rechecks_after_last_await_before_sending(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    blocker: str,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent
    from backend.core.errors import EntryAdmissionRevoked
    from backend.domain.models import BlackoutWindow, CapitalStatus, Decision, TradeProposal
    from backend.execution.models import BrokerOrder
    from backend.notifications.callbacks import FreshInputs
    from backend.risk.risk_cro import ChiefRiskOfficer

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    _, _, final = built._loaded(alert.proposal_id, None)
    final = final.model_copy(update={"qty": 8})

    async def reduce_to_eight(proposal: TradeProposal, inputs: FreshInputs) -> int:
        return 8

    built.size_entry = reduce_to_eight
    window = BlackoutWindow(
        start=harness.clock.now() + timedelta(seconds=1),
        end=harness.clock.now() + timedelta(seconds=30),
        reason="offline timing regression",
    )
    if blocker == "CRO-11":
        built.risk.additional_blackouts = lambda: (window,)
    original_lookup = built._lookup
    changed = False

    if blocker == "CRO-01":
        assert built.risk.marks is not None
        observe = built.risk.marks.observe

        def halt_during_final_observation(snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
            observed = observe(snapshot)
            if changed:
                harness.state.escalate(
                    SystemState.HALTED, "Offline host HALT during final observation"
                )
            return observed

        monkeypatch.setattr(built.risk.marks, "observe", halt_during_final_observation)

    async def transition_before_send(client_id: str) -> BrokerOrder | None:
        nonlocal changed
        if not changed:
            changed = True
            harness.clock.current += timedelta(seconds=2)
            inputs = harness.source.inputs
            if blocker in {"CRO-09", "CRO-10"}:
                equity = Decimal(9000 if blocker == "CRO-09" else 9700)
                harness.source.inputs = inputs.model_copy(
                    update={"portfolio": inputs.portfolio.model_copy(update={"equity": equity})}
                )
            elif blocker == "CRO-12":
                assert inputs.capital is not None
                harness.source.inputs = inputs.model_copy(
                    update={
                        "capital": inputs.capital.model_copy(
                            update={"status": CapitalStatus.BUFFER_BREACH, "deployable": Decimal(0)}
                        )
                    }
                )
            elif blocker == "CRO-13":
                harness.source.inputs = inputs.model_copy(
                    update={
                        "market": inputs.market.model_copy(
                            update={"next_earnings_date": harness.clock.now().date()}
                        )
                    }
                )
        return await original_lookup(client_id)

    monkeypatch.setattr(built, "_lookup", transition_before_send)
    try:
        if blocker == "clear":
            await built.enter(alert.proposal_id)
            assert len(client.posts) == 1
            assert client.posts[0]["qty"] == "8" and client.posts[0]["side"] == "buy"
        else:
            with pytest.raises(ExecutionDisabledError) as refusal:
                await built.enter(alert.proposal_id)
            assert type(refusal.value) in {ExecutionDisabledError, EntryAdmissionRevoked}
            assert client.posts == []
            officer = ChiefRiskOfficer(
                built.risk.cro.config,
                built.risk.cro.registry,
                built.risk.cro.calendar,
                blackout_windows=(window,) if blocker == "CRO-11" else (),
            )
            inputs = harness.source.inputs
            assert (
                officer.max_allowed_qty(final, inputs.portfolio, inputs.market, harness.clock.now())
                == 8
            )
            verdict = officer.evaluate(
                final,
                inputs.portfolio,
                inputs.market,
                SystemState.HALTED if blocker == "CRO-01" else SystemState.RUNNING,
                harness.clock.now(),
                deployable=inputs.capital,
                daily_loss_blocked=blocker == "CRO-10",
            )
            assert verdict.decision == Decision.VETOED
            assert any(row.rule_id == blocker and not row.passed for row in verdict.results)
            expected_message = (
                "Final full CRO blocks entry: CRO-09,CRO-10"
                if blocker == "CRO-09"
                else f"Final full CRO blocks entry: {blocker}"
            )
            assert type(refusal.value) is EntryAdmissionRevoked
            assert str(refusal.value) == expected_message
            assert f"risk_veto rule_id={blocker}" in caplog.text
            with Session(harness.state.engine) as session:
                refusals = tuple(
                    session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "AUTO_ENTRY_BLOCKED")
                    )
                )
                assert len(refusals) == 1
                assert refusals[0].detail == {
                    "proposal_id": str(alert.proposal_id),
                    "reason": expected_message,
                }
        assert changed
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_42_ceiling_refuses_configuration_drift_before_any_durable_entry(
    harness: Harness,
) -> None:
    order = recorded_imported_card(harness, "valid")
    harness.source.inputs = harness.source.inputs.model_copy(
        update={
            "market": harness.source.inputs.market.model_copy(update={"last_price": Decimal(100)})
        }
    )
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    calls = 0

    async def changed_configuration(proposal_id: object) -> None:
        nonlocal calls
        assert proposal_id == order.proposal_id
        calls += 1
        if calls == 2:
            # A refusal-only policy snapshot. No live guard is acquired, no
            # host setting is saved, and every broker object remains a paper fake.
            built.settings = Settings.validated_copy(
                harness.settings.model_copy(
                    update={
                        "execution_mode": "AUTO_LIVE",
                        "paper_trading": False,
                        "live_trading_enabled": True,
                        "live_trading_confirm": "I_ACCEPT_REAL_MONEY_RISK",
                        "live_max_order_notional": Decimal(1),
                        "live_max_daily_orders": 5,
                        "live_max_open_positions": 3,
                        "live_max_gross_exposure_pct": Decimal(1),
                        "live_max_risk_per_trade": Decimal("0.01"),
                        "live_daily_loss_limit": Decimal("0.02"),
                    }
                )
            )

    built.realtime_entry = changed_configuration
    try:
        with pytest.raises(ExecutionDisabledError) as caught:
            await built.enter(order.proposal_id)
        assert type(caught.value) is ExecutionDisabledError
        assert str(caught.value) == "AX-42 live ceilings block entry"
        assert calls == 2 and client.posts == []
        assert built._instructions() == ()
        assert built.live_guard is None
        assert harness.settings.execution_mode == "AUTO_PAPER" and harness.settings.paper_trading
        harness.state.ledger.verify_chain()
    finally:
        built.settings = harness.settings
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_25_halt_between_preflight_and_serialized_admission_never_submits(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from backend.core.database import transaction
    from backend.execution import alpaca_executor

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)

    @contextmanager
    def halt_before_serialization(engine: Engine) -> Iterator[Session]:
        harness.state.escalate(SystemState.HALTED, "Owner halted during admission")
        with transaction(engine) as session:
            yield session

    monkeypatch.setattr(alpaca_executor, "transaction", halt_before_serialization)
    with pytest.raises(ExecutionDisabledError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == "Serialized state or mode check blocks entry"
    assert client.posts == []
    assert built._instructions() == ()
    assert harness.state.current() == SystemState.HALTED
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO, {**AUTO, "auto_max_entries_per_day": 1}], indirect=True)
async def test_AX_25_second_research_card_cannot_bypass_daily_or_pending_entry_limits(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    harness.clock.current += timedelta(seconds=1)
    harness.request = harness.request.model_copy(
        update={
            "candidate": harness.request.candidate.model_copy(update={"as_of": harness.clock.now()})
        }
    )
    second = await deliver(harness)
    assert second.proposal_id != alert.proposal_id
    with pytest.raises(ExecutionDisabledError) as caught:
        await built.enter(second.proposal_id)
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == (
        "AX-25 daily entry cap reached"
        if harness.settings.auto_max_entries_per_day == 1
        else "AX-25 persisted position or pending intent blocks duplicate entry"
    )
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


def recorded_imported_card(
    harness: Harness, fault: str, *, stop: Decimal = Decimal(95), symbol: str = "NVDA"
) -> Order:
    from typing import cast

    from backend.core.clock import FrozenClock
    from backend.core.database import (
        Alert,
        AlertEvent,
        ApprovalEvent,
        ResearchReport,
        RiskDecision,
        RiskRuleResult,
        Signal,
    )
    from backend.tests.test_ledger import _order, _snapshot

    ledger = harness.state.ledger
    extra: dict[str, object] = {}
    if fault in {"no_target", "valid"}:
        snapshot_id = (
            harness.request.data_snapshot_id
            if fault == "valid"
            else _snapshot(ledger, cast(FrozenClock, harness.clock)).id
        )
        signal = ledger.append(
            Signal,
            agent_name="offline_manual_research",
            symbol=symbol if fault == "valid" else "AAPL",
            direction="BUY",
            confidence=Decimal("0.8"),
            structured_thesis={"setup": {}},
            invalidation="below stop",
            data_snapshot_id=snapshot_id,
            prompt_hash=None,
        )
        extra["signal_id"] = signal.id
        if fault == "valid":
            extra["symbol"] = symbol
    order = _order(
        ledger,
        cast(FrozenClock, harness.clock),
        account_id="offline-paper",
        stop_price=stop,
        target_price=None if fault == "no_target" else Decimal(105),
        **extra,
    )
    for decision_number in range(2):
        failed = fault == "blocked" and decision_number == 1
        decision = ledger.append(
            RiskDecision,
            proposal_id=order.proposal_id,
            decision="VETOED" if failed else "APPROVED",
            config_hash="0" * 64
            if fault == "config" and decision_number == 1
            else harness.settings.config_hash,
            snapshot_hash="a" * 64,
            evaluated_at=harness.clock.now(),
        )
        rules = range(1, 14) if fault == "missing_rule" and decision_number == 1 else range(1, 15)
        for rule in rules:
            ledger.append(
                RiskRuleResult,
                risk_decision_id=decision.id,
                rule_id=f"CRO-{rule:02d}",
                passed=0 if failed and rule == 1 else 1,
                severity="BLOCK",
                observed={"source": "offline imported proof"},
                limit={},
                message="offline research decision",
            )
    alert = ledger.append(
        Alert,
        proposal_id=order.proposal_id,
        signal_id=order.signal_id,
        symbol=order.symbol,
        playbook="BASE_BREAKOUT",
        score=Decimal(5) if fault == "low_score" else Decimal("8.5"),
        card_text="Offline imported research card",
        config_hash=harness.settings.config_hash,
        expires_at=harness.clock.now() + timedelta(hours=1),
    )
    ledger.append(
        ResearchReport,
        alert_id=alert.id,
        agent_name="desk_policy",
        status="OK",
        payload={"yaml_hash": "0" * 64 if fault == "wrong_yaml" else harness.config.config_hash},
    )
    if fault != "undelivered":
        ledger.append(
            AlertEvent,
            alert_id=alert.id,
            state="SENT",
            telegram_chat_id=123,
            telegram_message_id=456,
            reason="offline imported card delivery",
        )
    if fault == "consumed":
        ledger.append(
            ApprovalEvent,
            alert_id=alert.id,
            action="USER_VETOED",
            telegram_user_id=123,
            ts=harness.clock.now(),
            reasons=[],
        )
    return order


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault", ["position", "open_order", "stop", "client_collision", "stop_distance"]
)
async def test_AX_25_fresh_broker_reservations_and_price_boundary_refuse_another_entry(
    harness: Harness, fault: str
) -> None:
    from backend.core.errors import ProviderError, ReconciliationError
    from backend.domain.models import OpenOrder, ProtectiveStop

    order = recorded_imported_card(
        harness, "valid", stop=Decimal("99.99") if fault == "stop_distance" else Decimal(95)
    )
    market = harness.source.inputs.market.model_copy(
        update={"last_price": Decimal("99.99") if fault == "stop_distance" else Decimal(100)}
    )
    portfolio = harness.source.inputs.portfolio
    if fault == "position":
        portfolio = portfolio.model_copy(
            update={
                "positions": {
                    "NVDA": Position(qty=1, avg_cost=Decimal(100), last_price=Decimal(100))
                }
            }
        )
    elif fault == "open_order":
        portfolio = portfolio.model_copy(
            update={
                "open_orders": (
                    OpenOrder(
                        symbol="NVDA",
                        side=Side.BUY,
                        qty=1,
                        limit_price=Decimal(100),
                        stop_price=Decimal(95),
                    ),
                )
            }
        )
    elif fault == "stop":
        portfolio = portfolio.model_copy(
            update={
                "protective_stops": (ProtectiveStop(symbol="NVDA", qty=1, stop_price=Decimal(95)),)
            }
        )
    harness.source.inputs = harness.source.inputs.model_copy(
        update={"market": market, "portfolio": portfolio}
    )
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    if fault == "client_collision":
        client.orders["vws-" + order.proposal_id.hex] = {
            "id": str(uuid4()),
            "client_order_id": "vws-" + order.proposal_id.hex,
            "symbol": "NVDA",
            "side": "buy",
            "type": "limit",
            "order_class": "simple",
            "time_in_force": "gtc",
            "qty": "2",
            "filled_qty": "0",
            "status": "new",
            "limit_price": "100.00",
            "stop_price": None,
            "submitted_at": harness.clock.now().isoformat(),
            "legs": None,
        }
    error_type = ProviderError if fault == "client_collision" else ExecutionDisabledError
    with pytest.raises(error_type) as caught:
        await built.enter(order.proposal_id)
    assert type(caught.value) is error_type
    assert str(caught.value) == (
        "Automatic entry failed closed; inspect persisted intent"
        if fault == "client_collision"
        else "Bracket stop lacks Alpaca's one-cent base-price distance"
        if fault == "stop_distance"
        else "Fresh CRO or compliance blocks entry"
        if fault in {"position", "open_order"}
        else "AX-25 existing position or pending order blocks duplicate entry"
    )
    if fault == "client_collision":
        assert type(caught.value.__context__) is ReconciliationError
        assert (
            str(caught.value.__context__)
            == "An unrecorded order already uses this proposal client ID"
        )
    assert client.posts == []
    assert built._instructions() == ()
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "blocked",
        "config",
        "missing_rule",
        "low_score",
        "wrong_yaml",
        "undelivered",
        "consumed",
        "no_target",
    ],
)
async def test_AX_20_imported_research_proof_must_be_complete_current_and_single_use(
    harness: Harness, fault: str
) -> None:
    order = recorded_imported_card(harness, fault)
    ledger = harness.state.ledger
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        with pytest.raises(ExecutionDisabledError) as caught:
            await built.enter(order.proposal_id)
        assert type(caught.value) is ExecutionDisabledError
        expected = (
            "Recorded research CRO evidence is incomplete or blocked"
            if fault in {"blocked", "config", "missing_rule"}
            else "Auto entry requires one long entry bracket"
            if fault == "no_target"
            else "Research policy, delivered candidate or single-use decision differs"
        )
        assert str(caught.value) == expected
        assert client.posts == [] and client.lookups == []
        ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_20_delivered_card_without_both_research_cro_checks_cannot_enter(
    harness: Harness,
) -> None:
    from typing import cast

    from backend.core.clock import FrozenClock
    from backend.core.database import Alert, AlertEvent, ResearchReport
    from backend.tests.test_ledger import _order

    order = _order(
        harness.state.ledger,
        cast(FrozenClock, harness.clock),
        account_id="offline-paper",
        target_price=Decimal(105),
    )
    alert = harness.state.ledger.append(
        Alert,
        proposal_id=order.proposal_id,
        signal_id=order.signal_id,
        symbol=order.symbol,
        playbook="BASE_BREAKOUT",
        score=Decimal("8.5"),
        card_text="Offline delivered card without CRO proof",
        config_hash=harness.settings.config_hash,
        expires_at=harness.clock.now() + timedelta(hours=1),
    )
    harness.state.ledger.append(
        ResearchReport,
        alert_id=alert.id,
        agent_name="desk_policy",
        status="OK",
        payload={"yaml_hash": harness.config.config_hash},
    )
    harness.state.ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=123,
        telegram_message_id=456,
        reason="offline delivery without research CRO decisions",
    )
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    try:
        with pytest.raises(ExecutionDisabledError) as caught:
            await built.enter(order.proposal_id)
        assert type(caught.value) is ExecutionDisabledError
        assert str(caught.value) == "AX-20 requires both recorded research CRO checks"
        assert client.posts == [] and client.lookups == []
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("veto_at", [None, 1, 2])
async def test_XA_01_entry_rechecks_realtime_evidence_before_and_after_refresh(
    harness: Harness, veto_at: int | None
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    calls: list[object] = []

    async def evidence(proposal_id: object) -> None:
        calls.append(proposal_id)
        if len(calls) == veto_at:
            raise ExecutionDisabledError("Paper realtime evidence revoked")

    built.realtime_entry = evidence
    try:
        if veto_at is None:
            await built.enter(alert.proposal_id)
            assert calls == [alert.proposal_id, alert.proposal_id]
            assert len(client.posts) == 1
        else:
            with pytest.raises(ExecutionDisabledError) as caught:
                await built.enter(alert.proposal_id)
            assert type(caught.value) is ExecutionDisabledError
            assert str(caught.value) == "Paper realtime evidence revoked"
            assert calls == [alert.proposal_id] * veto_at
            assert client.posts == []
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_EX_01_single_share_overlay_cannot_create_two_entry_legs(harness: Harness) -> None:
    from backend.tests.test_v_execution import variant

    variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)

    async def one_share(proposal: object, inputs: object) -> int:
        return 1

    built.size_entry = one_share
    try:
        with pytest.raises(ExecutionDisabledError) as caught:
            await built.enter(alert.proposal_id)
        assert type(caught.value) is ExecutionDisabledError
        assert str(caught.value) == "EX-01: split entry requires at least two shares"
        assert client.posts == []
        harness.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.parametrize("harness", [AUTO], indirect=True)
def test_EX_01_entry_without_target_cannot_be_serialized_for_broker(harness: Harness) -> None:
    from backend.core.errors import DataIntegrityError

    client = FakeTradingClient(harness)
    built = executor(harness, client)
    candidate = make_proposal()
    assert candidate.target_price is None
    with pytest.raises(DataIntegrityError) as caught:
        built._entry_requests(candidate)
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "EX: ordered entry levels required"
    assert client.posts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["account", "filing_issuer", "filing_future"])
async def test_AX_20_fresh_account_and_filing_provenance_fail_closed_before_submit(
    harness: Harness, fault: str
) -> None:
    import hashlib

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SystemEvent
    from backend.core.errors import ProviderError
    from backend.data.sec_edgar import SecPayload

    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    inputs = harness.source.inputs
    if fault == "account":
        harness.source.inputs = inputs.model_copy(
            update={
                "portfolio": inputs.portfolio.model_copy(
                    update={"account_id": "another-paper-account"}
                )
            }
        )
    else:
        raw = b'{"cik":1045810}'
        payload = SecPayload(
            kind="COMPANYFACTS",
            cik="0001045810",
            fetched_at=harness.clock.now()
            + (timedelta(seconds=1) if fault == "filing_future" else timedelta()),
            raw=raw,
            data_sha256=hashlib.sha256(raw).hexdigest(),
        )
        harness.source.inputs = inputs.model_copy(
            update={
                "filings": payload,
                "expected_cik": "0000789019" if fault == "filing_issuer" else payload.cik,
            }
        )
    with pytest.raises(ProviderError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is ProviderError
    assert str(caught.value) == "Automatic entry failed closed; inspect persisted intent"
    assert client.posts == []
    assert harness.state.current() == SystemState.HALTED
    with Session(harness.state.engine) as session:
        halt = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()))
        assert halt is not None
        assert halt.reason == (
            "fault: ReconciliationError" if fault == "account" else "fault: DataIntegrityError"
        )
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_FA_08_fresh_missing_fundamentals_cannot_reuse_research_pass(
    harness: Harness,
) -> None:
    import hashlib
    import json

    from backend.agents.fundamentals import FrameworkStatus, compute_fundamentals
    from backend.core.config import YamlConfig
    from backend.data.sec_edgar import SecPayload
    from backend.tests.test_fundamentals import synthetic

    values = harness.config.model_dump(mode="python")
    values["fundamentals"]["mode"] = "require"
    harness.config = YamlConfig.model_validate(values)
    harness.swarm.config = harness.config
    data = synthetic()
    data["cik"] = 1045810
    raw = json.dumps(data).encode()
    payload = SecPayload(
        kind="COMPANYFACTS",
        cik="0001045810",
        fetched_at=harness.clock.now(),
        raw=raw,
        data_sha256=hashlib.sha256(raw).hexdigest(),
    )

    class PaperFilings:
        async def cik_for(self, symbol: str) -> str:
            assert symbol == "NVDA"
            return "0001045810"

        async def companyfacts(self, symbol: str) -> SecPayload:
            assert symbol == "NVDA"
            return payload

    harness.swarm.fundamentals = PaperFilings()
    report = compute_fundamentals(
        harness.gate.risk.cro.registry.get("NVDA"),
        payload,
        harness.clock.now(),
        harness.config.fundamentals,
    )
    assert report.framework_status == FrameworkStatus.PASS
    alert = await deliver(harness)
    assert harness.source.inputs.filings is None
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    with pytest.raises(ExecutionDisabledError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == "FA-08 fresh fundamental framework blocks entry"
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "harness", [AUTO, {**AUTO, "day_trade_regime": "LEGACY_PDT"}], indirect=True
)
async def test_AX_25_actual_submit_refuses_settled_cash_or_two_legacy_day_trades(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    if h.settings.day_trade_regime == "LEGACY_PDT":
        history = tuple(
            TradeRecord(
                trade_id=uuid4(),
                account_id="offline-paper",
                symbol="NVDA",
                side=side,
                qty=1,
                price=Decimal(100),
                ts=h.clock.now() - timedelta(days=1, minutes=minute),
            )
            for minute, side in ((4, Side.BUY), (3, Side.SELL), (2, Side.BUY), (1, Side.SELL))
        )
        h.source.inputs = h.source.inputs.model_copy(update={"history": history})
    else:
        h.source.inputs = h.source.inputs.model_copy(
            update={
                "portfolio": h.source.inputs.portfolio.model_copy(
                    update={"settled_cash": Decimal(0)}
                )
            }
        )
    with pytest.raises(ExecutionDisabledError):
        await built.enter(alert.proposal_id)
    assert not client.posts
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "equity,state",
    [
        ("9800", SystemState.RUNNING),
        ("9000", SystemState.REDUCE_ONLY),
        ("8500", SystemState.HALTED),
    ],
)
async def test_AX_30_daily_loss_and_drawdown_cancel_remainder_but_preserve_stop(
    harness: Harness, equity: str, state: SystemState
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)
    journal_existing_partial_repair(built)

    async def portfolio() -> PortfolioSnapshot:
        return h.source.inputs.portfolio.model_copy(
            update={
                "equity": Decimal(equity),
                "cash": Decimal(equity) - Decimal(100),
                "settled_cash": Decimal(equity) - Decimal(100),
                "positions": {
                    "NVDA": Position(qty=1, avg_cost=Decimal(100), last_price=Decimal(100))
                },
            }
        )

    built.portfolio = portfolio
    await built.monitor()
    assert h.state.current() == state
    assert parent["status"] == "canceled" and len(client.posts) == 2
    assert client.posts[-1]["type"] == "stop" and client.posts[-1]["qty"] == "1"
    if state == SystemState.RUNNING:
        assert built.risk.marks is not None and built.risk.marks.daily_loss_blocked(h.clock.now())
    with pytest.raises(ExecutionDisabledError):
        await built.enter(uuid4())
    assert len(client.posts) == 2
    h.state.ledger.verify_chain()


@pytest.mark.parametrize("boundary", ["notional", "daily", "positions", "gross", "risk", "loss"])
def test_AX_42_exact_live_ceiling_boundary_and_first_excess(
    harness: Harness, boundary: str
) -> None:
    h = harness
    proposal = make_proposal(
        stop_price=Decimal(99), target_price=Decimal(103), account_id="offline-paper"
    )
    portfolio = h.request.portfolio
    values = {
        "live_max_order_notional": Decimal(1000),
        "live_max_daily_orders": 5,
        "live_max_open_positions": 3,
        "live_max_gross_exposure_pct": Decimal(1),
        "live_max_risk_per_trade": Decimal("0.01"),
        "live_daily_loss_limit": Decimal("0.02"),
    }
    daily = 0
    if boundary == "notional":
        values["live_max_order_notional"] = Decimal(100)
    elif boundary == "daily":
        daily = 4
    elif boundary == "positions":
        values["live_max_open_positions"] = 1
    elif boundary == "gross":
        values["live_max_gross_exposure_pct"] = Decimal("0.01")
    elif boundary == "risk":
        values["live_max_risk_per_trade"] = (
            Decimal(1) + Decimal(100) * h.settings.stop_slippage_buffer
        ) / portfolio.equity
    elif boundary == "loss":
        # The daily loss cutoff itself blocks; the nearest cent above permits entry.
        portfolio = portfolio.model_copy(update={"equity": Decimal("9800.01")})
    settings = Settings.validated_copy(h.settings.model_copy(update=values))
    assert not live_ceiling_reasons(settings, proposal, portfolio, daily)
    if boundary in {"notional", "gross"}:
        proposal = proposal.model_copy(update={"limit_price": Decimal("100.01")})
    elif boundary == "daily":
        daily += 1
    elif boundary == "positions":
        portfolio = portfolio.model_copy(
            update={
                "positions": {"NVDA": Position(qty=1, avg_cost=Decimal(1), last_price=Decimal(1))}
            }
        )
    elif boundary == "risk":
        proposal = proposal.model_copy(update={"stop_price": Decimal("98.99")})
    else:
        portfolio = portfolio.model_copy(update={"equity": Decimal(9800)})
    reasons = live_ceiling_reasons(settings, proposal, portfolio, daily)
    expected = {
        "notional": "notional",
        "daily": "daily entry",
        "positions": "open-position",
        "gross": "gross-exposure",
        "risk": "per-trade risk",
        "loss": "daily loss",
    }[boundary]
    assert len(reasons) == 1 and expected in reasons[0]
