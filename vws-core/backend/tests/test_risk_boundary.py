"""R-02/R-03/R-09: persisted CRO tiers, veto audit, and boundary faults."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import Clock, FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountType,
    AssetClass,
    BlackoutWindow,
    CapitalStatus,
    Decision,
    DeployableCapital,
    Instrument,
    Intent,
    MarketContext,
    MarketStatus,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    Severity,
    Side,
    TradeProposal,
    Verdict,
    snapshot_hash,
)
from backend.risk.boundary import LoggingVetoSink, RiskBoundary, VetoSink
from backend.risk.portfolio_marks import PersistedPortfolioMarks
from backend.risk.risk_cro import ChiefRiskOfficer


@pytest.mark.parametrize(
    "fault,message",
    [
        ("proposal", "R-02: risk verdict identity or rule evidence is invalid"),
        ("policy", "R-02: risk verdict identity or rule evidence is invalid"),
        ("duplicate", "R-02: risk verdict identity or rule evidence is invalid"),
        ("unknown", "R-02: risk verdict identity or rule evidence is invalid"),
        ("incomplete", "R-02: approval lacks complete bound rule evidence"),
        ("reordered", "R-02: approval lacks complete bound rule evidence"),
        ("snapshot", "R-02: approval lacks complete bound rule evidence"),
        ("daily_block", "CRO-10: approval concealed a witnessed session loss block"),
        ("reduce_only", "CRO-01: approved entry cannot recommend a restricted state"),
        ("blocking_warn", "R-02: approval has altered blocking-rule evidence"),
        ("earnings", "CRO-13: approval has invalid earnings evidence"),
        ("market_missing", "CRO-13: approval has invalid earnings evidence"),
        ("reasonless_veto", "R-02: veto lacks a blocking reason"),
    ],
)
def test_R_02_altered_approval_has_exact_auditable_refusal(
    engine: Engine, boundary_cro: ChiefRiskOfficer, fault: str, message: str
) -> None:
    from uuid import uuid4

    gate = boundary(engine, boundary_cro, VetoRecorder())
    proposal, snapshot, market = trade(), book(), quote()
    verdict = gate.evaluate(proposal, snapshot, market, deployable=capital())
    assert verdict.decision == Decision.APPROVED
    rows = list(verdict.results)
    updates: dict[str, object] = {}
    if fault == "proposal":
        updates["proposal_id"] = uuid4()
    elif fault == "policy":
        updates["config_hash"] = "0" * 64
    elif fault == "duplicate":
        rows[1] = rows[0]
    elif fault == "unknown":
        rows[1] = rows[1].model_copy(update={"rule_id": "CRO-99"})
    elif fault == "incomplete":
        rows.pop()
    elif fault == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif fault == "snapshot":
        updates["snapshot_hash"] = "0" * 64
    elif fault == "reduce_only":
        updates["recommended_state"] = SystemState.REDUCE_ONLY
    elif fault == "blocking_warn":
        rows[1] = rows[1].model_copy(update={"severity": Severity.WARN})
    elif fault == "earnings":
        rows[12] = rows[12].model_copy(update={"message": "unverified earnings called clear"})
    elif fault == "reasonless_veto":
        updates["decision"] = Decision.VETOED
    changed = verdict.model_copy(update={**updates, "results": tuple(rows)})
    with pytest.raises(DataIntegrityError) as caught:
        gate._checked(
            changed,
            proposal,
            snapshot,
            None if fault == "market_missing" else market,
            fault == "daily_block",
        )
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == message


def test_R_07_veto_sink_records_exact_safe_audit_text(caplog: pytest.LogCaptureFixture) -> None:
    sink = LoggingVetoSink()
    with caplog.at_level(logging.WARNING, logger="backend.risk.boundary"):
        sink.record("CRO-09", TRADE_ID)
    assert [(row.name, row.levelno, row.getMessage()) for row in caplog.records] == [
        (
            "backend.risk.boundary",
            logging.WARNING,
            "risk_veto rule_id=CRO-09 proposal_id=50000000-0000-0000-0000-000000000001",
        )
    ]


def test_R_02_unimplemented_audit_sink_refuses_with_exact_error() -> None:
    with pytest.raises(DataIntegrityError) as caught:
        VetoSink.record(cast(VetoSink, object()), "CRO-09", TRADE_ID)
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "R-02: veto audit sink has no implementation"


NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
TRADE_ID = UUID("50000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("50000000-0000-0000-0000-000000000002")


class NoticeRecorder:
    """R-02: local observable notifications without external services."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def notify(self, state: str, reason: str) -> None:
        self.calls.append((state, reason))


class VetoRecorder:
    """R-02: injectable audit sink, including a reproducible sink failure."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, UUID]] = []
        self.fail = fail

    def record(self, rule_id: str, proposal_id: UUID) -> None:
        self.calls.append((rule_id, proposal_id))
        if self.fail:
            raise RuntimeError("audit unavailable")


class BrokenClock:
    """R-05/R-02: time failure is never converted into current time."""

    def now(self) -> datetime:
        raise RuntimeError("clock unavailable")


@pytest.fixture(scope="module")
def boundary_cro() -> ChiefRiskOfficer:
    """CRO-01..13: pure policy with explicitly bounded exchange sessions."""
    instrument = Instrument(
        symbol="AAPL",
        asset_class=AssetClass.STOCK,
        gics_sector="Information Technology",
        themes=(),
        is_leveraged=False,
        is_inverse=False,
        tradable=True,
    )
    return ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        InstrumentRegistry((instrument,)),
        MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31)),
    )


def trade(*, exit_: bool = False, manual: bool = False) -> TradeProposal:
    """R-01/R-05: exact local proposal with explicit lifetime."""
    return TradeProposal(
        proposal_id=TRADE_ID,
        signal_id=SIGNAL_ID,
        account_id="boundary-paper",
        symbol="AAPL",
        side=Side.SELL if exit_ else Side.BUY,
        intent=Intent.EXIT if exit_ else Intent.ENTRY,
        qty=1,
        limit_price=Decimal("100.00"),
        stop_price=None if exit_ else Decimal("95.00"),
        source=ProposalSource.MANUAL if manual else ProposalSource.SIGNAL,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def book(*, equity: str = "10000", held: bool = False) -> PortfolioSnapshot:
    """CRO-09/CRO-10: baselines represent previously persisted marks."""
    return PortfolioSnapshot(
        account_id="boundary-paper",
        account_type=AccountType.CASH,
        as_of=NOW,
        equity=Decimal(equity),
        cash=Decimal(equity),
        settled_cash=Decimal(equity),
        positions={"AAPL": Position(qty=1, avg_cost=Decimal("95.00"), last_price=Decimal("100.00"))}
        if held
        else {},
        open_orders=(),
        high_water_mark=Decimal("10000"),
        day_start_equity=Decimal(equity),
    )


def quote() -> MarketContext:
    """CRO-07/CRO-13: fresh quote and explicit unknown earnings."""
    return MarketContext(
        last_price=Decimal("100.00"),
        last_price_ts=NOW,
        adv20_usd=Decimal("1000000"),
        status=MarketStatus.OK,
    )


def capital() -> DeployableCapital:
    """CRO-12: no bank calls; exact advisory funds."""
    return DeployableCapital(
        checking_used=Decimal("5000"),
        buffer=Decimal("1500"),
        reserved=Decimal(0),
        deployable=Decimal("3500"),
        status=CapitalStatus.OK,
    )


def boundary(engine: Engine, cro: ChiefRiskOfficer, sink: VetoSink | None = None) -> RiskBoundary:
    """R-02/R-05: isolated SQLite state and injected fixed clock."""
    clock = FrozenClock(NOW)
    return RiskBoundary(
        cro, SystemStateStore(engine, clock, NoticeRecorder()), clock, veto_sink=sink
    )


@pytest.mark.parametrize("manual_exit", [False, True])
@pytest.mark.parametrize("funding", ["OK", "missing", "BUFFER_BREACH"])
def test_concurrent_halt_keeps_entry_veto_and_valid_manual_exit_for_all_funding_states(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
    manual_exit: bool,
    funding: str,
) -> None:
    gate = boundary(engine, boundary_cro)
    original = gate.state.escalate
    raced = False

    def host_halt(target: SystemState, reason: str) -> SystemState:
        nonlocal raced
        if not raced:
            raced = True
            original(SystemState.HALTED, "Offline host HALT at final tier commit")
        return original(target, reason)

    monkeypatch.setattr(gate.state, "escalate", host_halt)
    supplied = None if funding == "missing" else capital()
    if funding == "BUFFER_BREACH":
        assert supplied is not None
        supplied = supplied.model_copy(
            update={"status": CapitalStatus.BUFFER_BREACH, "deployable": Decimal(0)}
        )
    verdict = gate.evaluate(
        trade(exit_=manual_exit, manual=manual_exit),
        book(held=manual_exit),
        quote(),
        deployable=supplied,
    )
    assert raced and gate.state.current() == SystemState.HALTED
    if manual_exit:
        assert verdict.decision == Decision.APPROVED
        assert [(row.rule_id, row.passed) for row in verdict.results] == [
            ("CRO-01", True),
            ("CRO-02", True),
        ]
    else:
        assert verdict.decision == Decision.VETOED
        assert [(row.rule_id, row.passed, row.observed) for row in verdict.results] == [
            ("CRO-01", False, "HALTED")
        ]
    gate.state.ledger.verify_chain()


def test_R_03_CRO_13_warn_approval_does_not_log_veto(
    engine: Engine, boundary_cro: ChiefRiskOfficer
) -> None:
    sink = VetoRecorder()
    gate = boundary(engine, boundary_cro, sink)
    result = gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert result.decision == Decision.APPROVED
    assert len(result.results) == 14
    assert not result.results[12].passed and result.results[12].severity == Severity.WARN
    assert sink.calls == []
    assert gate.state.current() == SystemState.RUNNING


@pytest.mark.parametrize(
    ("equity", "tier"), [("9200", SystemState.REDUCE_ONLY), ("8800", SystemState.HALTED)]
)
def test_CRO_09_tier_veto_persists_restart(
    engine: Engine, boundary_cro: ChiefRiskOfficer, equity: str, tier: SystemState
) -> None:
    sink = VetoRecorder()
    gate = boundary(engine, boundary_cro, sink)
    result = gate.evaluate(trade(), book(equity=equity), quote(), deployable=capital())
    assert result.decision == Decision.VETOED
    assert gate.state.current() == tier
    assert SystemStateStore(engine, FrozenClock(NOW), NoticeRecorder()).current() == tier
    assert sink.calls == [
        (row.rule_id, TRADE_ID)
        for row in result.results
        if not row.passed and row.severity == Severity.BLOCK
    ]


def test_R_09_exit_detects_halt_without_trapping_held_exit(
    engine: Engine, boundary_cro: ChiefRiskOfficer
) -> None:
    gate = boundary(engine, boundary_cro)
    snapshot = book(equity="8800", held=True)
    assert gate.evaluate(trade(exit_=True), snapshot, None).decision == Decision.APPROVED
    assert gate.state.current() == SystemState.HALTED
    assert gate.evaluate(trade(exit_=True), snapshot, None).decision == Decision.VETOED
    assert (
        gate.evaluate(trade(exit_=True, manual=True), snapshot, None).decision == Decision.APPROVED
    )


def test_CRO_01_concurrent_halt_rechecks_state(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, boundary_cro, VetoRecorder())
    original = gate.state.current
    calls = 0

    def changing_state() -> SystemState:
        nonlocal calls
        calls += 1
        if calls == 2:
            gate.state.escalate(SystemState.HALTED, "concurrent provider failure")
        return original()

    monkeypatch.setattr(gate.state, "current", changing_state)
    result = gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert result.decision == Decision.VETOED
    assert result.results[0].rule_id == "CRO-01"


@pytest.mark.parametrize("failure", ["clock", "cro", "database", "audit"])
def test_R_02_every_boundary_failure_halts(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    # Construct a private CRO so patched providers never contaminate other tests.
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro, VetoRecorder(fail=failure == "audit"))

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected boundary fault")

    if failure == "clock":
        gate.clock = cast(Clock, BrokenClock())
    elif failure == "cro":
        monkeypatch.setattr(cro, "evaluate", fail)
    elif failure == "database":
        monkeypatch.setattr(gate.state.ledger, "verify_chain", fail)
    else:
        gate.state.escalate(SystemState.REDUCE_ONLY, "test audit fault")
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert gate.state.current() == SystemState.HALTED


def test_R_02_failed_halt_storage_surfaces_typed_error(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, boundary_cro)
    gate.clock = BrokenClock()

    def fail(error: Exception) -> SystemState:
        raise RuntimeError("halt storage unavailable")

    monkeypatch.setattr(gate.state, "halt_for_error", fail)
    with pytest.raises(DataIntegrityError, match="HALT persistence unavailable"):
        gate.evaluate(trade(), book(), quote())


@pytest.mark.parametrize(
    "alteration",
    ["id", "config", "empty", "duplicate", "unknown", "incomplete", "snapshot", "veto", "time"],
)
def test_R_02_forged_verdict_cannot_approve(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, alteration: str
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    legitimate = cro.evaluate(
        trade(), book(), quote(), SystemState.RUNNING, NOW, deployable=capital()
    )
    updates: dict[str, object] = {}
    if alteration == "id":
        updates["proposal_id"] = SIGNAL_ID
    elif alteration == "config":
        updates["config_hash"] = "f" * 64
    elif alteration == "empty":
        updates["results"] = ()
    elif alteration == "duplicate":
        updates["results"] = (*legitimate.results, legitimate.results[0])
    elif alteration == "unknown":
        updates["results"] = (legitimate.results[0].model_copy(update={"rule_id": "FAKE"}),)
    elif alteration == "incomplete":
        updates["results"] = legitimate.results[:1]
    elif alteration == "snapshot":
        updates["snapshot_hash"] = "f" * 64
    elif alteration == "veto":
        updates["decision"] = Decision.VETOED
    else:
        updates["evaluated_at"] = NOW - timedelta(seconds=1)
    forged = legitimate.model_copy(update=updates)

    def returning(*args: object, **kwargs: object) -> Verdict:
        return forged

    monkeypatch.setattr(cro, "evaluate", returning)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert gate.state.current() == SystemState.HALTED


def test_R_02_veto_sink_contract_fails_closed() -> None:
    with pytest.raises(DataIntegrityError, match="no implementation"):
        VetoSink.record(cast(VetoSink, object()), "CRO-01", TRADE_ID)


def test_R_02_veto_log_contains_required_identities(caplog: pytest.LogCaptureFixture) -> None:
    LoggingVetoSink().record("CRO-01", TRADE_ID)
    assert "rule_id=CRO-01" in caplog.text
    assert f"proposal_id={TRADE_ID}" in caplog.text


def test_CRO_13_known_distant_earnings_pass(engine: Engine, boundary_cro: ChiefRiskOfficer) -> None:
    context = quote().model_copy(update={"next_earnings_date": date(2026, 10, 9)})
    result = boundary(engine, boundary_cro).evaluate(trade(), book(), context, deployable=capital())
    assert result.decision == Decision.APPROVED
    assert result.results[-1].passed and result.results[-1].severity == Severity.BLOCK


@pytest.mark.parametrize(
    "attack", ["warn_block", "earnings_warn", "halt", "reduce", "restricted_entry"]
)
def test_R_02_severity_and_financial_recommendation_attacks(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    snapshot = book(
        equity="8800" if attack == "halt" else "9200" if attack == "reduce" else "10000",
        held=attack in {"halt", "reduce"},
    )
    proposal = trade(exit_=attack in {"halt", "reduce"})
    result = cro.evaluate(
        proposal, snapshot, quote(), SystemState.RUNNING, NOW, deployable=capital()
    )
    if attack == "warn_block":
        result = result.model_copy(
            update={
                "results": (
                    result.results[0].model_copy(
                        update={"passed": False, "severity": Severity.WARN}
                    ),
                    *result.results[1:],
                )
            }
        )
    elif attack == "earnings_warn":
        # A known earnings date cannot borrow the unknown-date warning exception.
        result = result.model_copy(
            update={
                "results": (
                    *result.results[:-1],
                    result.results[-1].model_copy(
                        update={"passed": True, "severity": Severity.WARN}
                    ),
                )
            }
        )
    else:
        result = result.model_copy(
            update={
                "recommended_state": SystemState.HALTED
                if attack == "restricted_entry"
                else SystemState.RUNNING
            }
        )

    def returning(*args: object, **kwargs: object) -> Verdict:
        return result

    monkeypatch.setattr(cro, "evaluate", returning)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(proposal, snapshot, quote(), deployable=capital())
    assert gate.state.current() == SystemState.HALTED


@pytest.mark.parametrize("bad_time", [False, True])
def test_CRO_01_halt_arriving_at_escalation_is_rechecked(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, bad_time: bool
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    escalate = gate.state.escalate
    evaluate = cro.evaluate
    calls = 0

    def concurrent(target: SystemState, reason: str) -> SystemState:
        nonlocal calls
        calls += 1
        if calls == 1:
            escalate(SystemState.HALTED, "concurrent failure at commit")
        return escalate(target, reason)

    def injected(*args: object, **kwargs: object) -> Verdict:
        result = evaluate(*args, **kwargs)  # type: ignore[arg-type]
        if bad_time and args[3] == SystemState.HALTED:
            return result.model_copy(update={"evaluated_at": NOW - timedelta(seconds=1)})
        return result

    monkeypatch.setattr(gate.state, "escalate", concurrent)
    monkeypatch.setattr(cro, "evaluate", injected)
    if bad_time:
        with pytest.raises(DataIntegrityError):
            gate.evaluate(trade(), book(), quote(), deployable=capital())
    else:
        assert (
            gate.evaluate(trade(), book(), quote(), deployable=capital()).decision
            == Decision.VETOED
        )
    assert gate.state.current() == SystemState.HALTED


def test_R_02_fault_logger_failure_still_halts(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, boundary_cro)
    gate.clock = BrokenClock()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("logging unavailable")

    monkeypatch.setattr(logging.getLogger("backend.risk.boundary"), "error", fail)
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(trade(), book(), quote())
    assert gate.state.current() == SystemState.HALTED


def test_CRO_10_session_breach_and_recovery_veto_without_state_latch(
    engine: Engine, boundary_cro: ChiefRiskOfficer
) -> None:
    gate = boundary(engine, boundary_cro)
    gate.marks = PersistedPortfolioMarks(
        gate.state.ledger, "boundary-paper", boundary_cro.calendar, boundary_cro.config
    )
    assert (
        gate.evaluate(trade(), book(), quote(), deployable=capital()).decision == Decision.APPROVED
    )
    loss = book(equity="9800", held=True).model_copy(update={"day_start_equity": Decimal("10000")})
    result = gate.evaluate(trade(), loss, quote(), deployable=capital())
    assert result.decision == Decision.VETOED
    assert next(row for row in result.results if row.rule_id == "CRO-10").passed is False
    assert gate.state.current() == SystemState.RUNNING
    restarted = RiskBoundary(
        boundary_cro,
        SystemStateStore(engine, gate.clock, NoticeRecorder()),
        gate.clock,
        marks=PersistedPortfolioMarks(
            gate.state.ledger, "boundary-paper", boundary_cro.calendar, boundary_cro.config
        ),
    )
    assert (
        restarted.evaluate(trade(), book(), quote(), deployable=capital()).decision
        == Decision.VETOED
    )
    assert (
        restarted.evaluate(trade(exit_=True), book(held=True), None).decision == Decision.APPROVED
    )
    assert restarted.state.current() == SystemState.RUNNING
    next_open = boundary_cro.calendar.session_open(date(2026, 10, 5))
    next_clock = FrozenClock(next_open)
    restarted.clock = next_clock
    restarted.state.clock = next_clock
    restarted.state.ledger.clock = next_clock
    assert restarted.marks is not None
    restarted.marks.ledger.clock = next_clock
    next_trade = trade().model_copy(
        update={"created_at": next_open, "expires_at": next_open + timedelta(hours=1)}
    )
    next_book = book(equity="9800").model_copy(update={"as_of": next_open})
    next_quote = quote().model_copy(update={"last_price_ts": next_open})
    result = restarted.evaluate(next_trade, next_book, next_quote, deployable=capital())
    assert result.decision == Decision.APPROVED
    assert result.recommended_state == SystemState.RUNNING
    assert restarted.state.current() == SystemState.RUNNING


@pytest.mark.parametrize("fault", ["policy", "database"])
def test_R_02_CRO_10_persisted_marks_must_share_risk_policy_and_ledger(
    engine: Engine, boundary_cro: ChiefRiskOfficer, fault: str
) -> None:
    from backend.core.database import create_database
    from backend.core.ledger import Ledger

    other = create_database("sqlite://")
    gate = boundary(engine, boundary_cro)
    config = (
        boundary_cro.config.model_copy(update={"daily_loss_limit": Decimal("0.03")})
        if fault == "policy"
        else boundary_cro.config
    )
    marks = PersistedPortfolioMarks(
        Ledger(other if fault == "database" else engine, gate.clock),
        "boundary-paper",
        boundary_cro.calendar,
        config,
    )
    try:
        with pytest.raises(DataIntegrityError):
            RiskBoundary(boundary_cro, gate.state, gate.clock, marks=marks)
    finally:
        other.dispose()


def test_R_02_CRO_10_forged_approval_cannot_hide_persisted_session_breach(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    gate.marks = PersistedPortfolioMarks(
        gate.state.ledger, "boundary-paper", cro.calendar, cro.config
    )
    gate.marks.observe(
        book(equity="9800").model_copy(update={"day_start_equity": Decimal("10000")})
    )
    forged = cro.evaluate(trade(), book(), quote(), SystemState.RUNNING, NOW, deployable=capital())
    monkeypatch.setattr(cro, "evaluate", lambda *args, **kwargs: forged)
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert gate.state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "size,mutable", [(0, False), (1, False), (500, False), (501, False), (0, True)]
)
def test_CRO_11_operator_window_supplier_obeys_exact_bounds_and_audit(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    caplog: pytest.LogCaptureFixture,
    size: int,
    mutable: bool,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SystemEvent

    gate = boundary(engine, boundary_cro)
    future = BlackoutWindow(
        start=NOW + timedelta(days=1),
        end=NOW + timedelta(days=1, hours=1),
        reason="offline future operator window",
    )
    windows: object = [future] * size if mutable else (future,) * size
    gate.additional_blackouts = lambda: cast(tuple[BlackoutWindow, ...], windows)
    if size > 500 or mutable:
        with pytest.raises(DataIntegrityError) as refused:
            gate.evaluate(trade(), book(), quote(), deployable=capital())
        assert type(refused.value) is DataIntegrityError
        assert str(refused.value) == "R-02: risk boundary failed and latched HALTED"
        assert type(refused.value.__cause__) is DataIntegrityError
        assert str(refused.value.__cause__) == "CRO-11: bounded immutable extra windows required"
        records = [
            r
            for r in caplog.records
            if r.name == "backend.risk.boundary" and r.levelno == logging.ERROR
        ]
        assert (
            len(records) == 1
            and records[0].getMessage() == "risk_boundary_fault error_type=DataIntegrityError"
        )
        with Session(engine) as session:
            event = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()))
            assert event is not None and event.reason == "fault: DataIntegrityError"
        assert gate.state.current() == SystemState.HALTED
    else:
        result = gate.evaluate(trade(), book(), quote(), deployable=capital())
        assert result.decision == Decision.APPROVED
        row = next(r for r in result.results if r.rule_id == "CRO-11")
        assert row.passed and row.observed == "clear"
        assert row.message == "scheduled blackout includes both endpoint instants"
        assert gate.state.current() == SystemState.RUNNING
    gate.state.ledger.verify_chain()


@pytest.mark.parametrize("origin", ["constructor", "supplier"])
def test_CRO_11_extra_windows_preserve_original_operator_blackout(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    origin: str,
) -> None:
    active = BlackoutWindow(
        start=NOW,
        end=NOW + timedelta(hours=1),
        symbol="AAPL",
        reason="offline active operator window",
    )
    cro = ChiefRiskOfficer(
        boundary_cro.config,
        boundary_cro.registry,
        boundary_cro.calendar,
        blackout_windows=(active,) if origin == "constructor" else (),
    )
    original = boundary(engine, cro)
    gate = RiskBoundary(
        cro,
        original.state,
        original.clock,
        additional_blackouts=lambda: (active,) if origin == "supplier" else (),
    )
    result = gate.evaluate(trade(), book(), quote(), deployable=capital())
    row = next(r for r in result.results if r.rule_id == "CRO-11")
    assert result.decision == Decision.VETOED and not row.passed
    assert (row.observed, row.limit, row.message) == (
        "in blackout",
        "outside all applicable UTC blackouts",
        "scheduled blackout includes both endpoint instants",
    )
    assert gate.state.current() == SystemState.RUNNING
    gate.state.ledger.verify_chain()


def test_CRO_01_attributed_reset_during_evaluation_requires_a_fresh_full_approval(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    gate.state.escalate(SystemState.HALTED, "offline prior fault")
    evaluate = cro.evaluate
    reset = False

    def host_reset(*args: object, **kwargs: object) -> Verdict:
        nonlocal reset
        result = evaluate(*args, **kwargs)  # type: ignore[arg-type]
        if not reset:
            reset = True
            gate.state.operator_reset("offline owner", "offline attributed concurrent reset")
        return result

    monkeypatch.setattr(cro, "evaluate", host_reset)
    result = gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert reset and result.decision == Decision.APPROVED
    assert [r.rule_id for r in result.results] == [f"CRO-{i:02d}" for i in range(1, 15)]
    assert result.snapshot_hash == snapshot_hash(book()) and result.evaluated_at == NOW
    assert gate.state.current() == SystemState.RUNNING
    gate.state.ledger.verify_chain()


@pytest.mark.parametrize(
    "equity,expected", [("9000", SystemState.REDUCE_ONLY), ("8000", SystemState.HALTED)]
)
def test_CRO_09_drawdown_escalation_retains_exact_durable_audit_reason(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    equity: str,
    expected: SystemState,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SystemEvent

    gate = boundary(engine, boundary_cro)
    result = gate.evaluate(trade(), book(equity=equity), quote(), deployable=capital())
    assert result.decision == Decision.VETOED and result.recommended_state == expected
    assert gate.state.current() == expected
    with Session(engine) as session:
        event = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()))
        assert event is not None and event.reason == "CRO-09 drawdown risk evaluation"
    gate.state.ledger.verify_chain()


def test_CRO_09_reset_between_latch_and_recheck_does_not_erase_current_drawdown(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.database import SystemEvent

    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    escalate = gate.state.escalate
    evaluate = cro.evaluate
    fault = False
    reset = False

    def concurrent(target: SystemState, reason: str) -> SystemState:
        nonlocal fault
        if not fault:
            fault = True
            escalate(SystemState.HALTED, "offline concurrent host fault")
        return escalate(target, reason)

    def host_reset(*args: object, **kwargs: object) -> Verdict:
        nonlocal reset
        result = evaluate(*args, **kwargs)  # type: ignore[arg-type]
        if args[3] == SystemState.HALTED:
            gate.state.operator_reset(
                "offline owner", "offline reset before final financial recheck"
            )
            reset = True
        return result

    monkeypatch.setattr(gate.state, "escalate", concurrent)
    monkeypatch.setattr(cro, "evaluate", host_reset)
    result = gate.evaluate(trade(), book(equity="9000"), quote(), deployable=capital())
    assert reset and result.decision == Decision.VETOED
    assert gate.state.current() == SystemState.REDUCE_ONLY
    with Session(engine) as session:
        event = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()))
        assert event is not None and event.reason == "CRO-09 concurrent state recheck"
    gate.state.ledger.verify_chain()


@pytest.mark.parametrize("failure", ["logger", "halt_storage"])
def test_R_02_fault_audit_or_halt_storage_failure_keeps_exact_error_provenance(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    gate = boundary(engine, boundary_cro)
    gate.additional_blackouts = lambda: cast(tuple[BlackoutWindow, ...], [])

    def unavailable(*args: object, **kwargs: object) -> None:
        raise RuntimeError("offline fault dependency unavailable")

    if failure == "logger":
        monkeypatch.setattr(logging.getLogger("backend.risk.boundary"), "error", unavailable)
    else:
        monkeypatch.setattr(gate.state, "halt_for_error", unavailable)
    with pytest.raises(DataIntegrityError) as refused:
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert type(refused.value) is DataIntegrityError
    if failure == "logger":
        assert str(refused.value) == "R-02: risk boundary failed and latched HALTED"
        assert type(refused.value.__cause__) is DataIntegrityError
        assert str(refused.value.__cause__) == "R-02: risk fault audit unavailable (RuntimeError)"
        assert gate.state.current() == SystemState.HALTED
    else:
        assert str(refused.value) == "R-02: risk boundary failed; HALT persistence unavailable"
        assert type(refused.value.__cause__) is RuntimeError
        assert str(refused.value.__cause__) == "offline fault dependency unavailable"


def test_R_02_CRO_10_changed_persisted_mark_policy_has_exact_integrity_refusal(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
) -> None:
    original = boundary(engine, boundary_cro)
    changed = boundary_cro.config.model_copy(update={"daily_loss_limit": Decimal("0.03")})
    marks = PersistedPortfolioMarks(
        original.state.ledger, "boundary-paper", boundary_cro.calendar, changed
    )
    with pytest.raises(DataIntegrityError) as refused:
        RiskBoundary(boundary_cro, original.state, original.clock, marks=marks)
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "CRO-09/CRO-10: persisted marks differ from risk policy"


def test_R_02_approval_without_a_session_loss_witness_is_not_given_one_by_default(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
) -> None:
    gate = boundary(engine, boundary_cro)
    original = boundary_cro.evaluate(
        trade(), book(), quote(), SystemState.RUNNING, NOW, deployable=capital()
    )
    assert original.decision == Decision.APPROVED
    assert gate._checked(original, trade(), book(), quote()) == original
    assert gate.state.current() == SystemState.RUNNING


@pytest.mark.parametrize("equity", ["9000", "8000"])
def test_CRO_09_concealed_financial_tier_keeps_exact_integrity_cause(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
    equity: str,
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    source = cro.evaluate(
        trade(), book(equity=equity), quote(), SystemState.RUNNING, NOW, deployable=capital()
    )
    forged = source.model_copy(update={"recommended_state": SystemState.RUNNING})
    monkeypatch.setattr(cro, "evaluate", lambda *args, **kwargs: forged)
    with pytest.raises(DataIntegrityError) as refused:
        gate.evaluate(trade(), book(equity=equity), quote(), deployable=capital())
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "R-02: risk boundary failed and latched HALTED"
    assert type(refused.value.__cause__) is DataIntegrityError
    assert (
        str(refused.value.__cause__)
        == "CRO-09: verdict concealed required drawdown state escalation"
    )
    assert gate.state.current() == SystemState.HALTED
    gate.state.ledger.verify_chain()


def test_R_05_concurrent_tier_recheck_with_stale_verdict_keeps_exact_time_error(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    escalate = gate.state.escalate
    evaluate = cro.evaluate
    fired = False

    def concurrent(target: SystemState, reason: str) -> SystemState:
        nonlocal fired
        if not fired:
            fired = True
            escalate(SystemState.HALTED, "offline concurrent host fault")
        return escalate(target, reason)

    def stale_on_halt(*args: object, **kwargs: object) -> Verdict:
        result = evaluate(*args, **kwargs)  # type: ignore[arg-type]
        return (
            result.model_copy(update={"evaluated_at": NOW - timedelta(microseconds=1)})
            if args[3] == SystemState.HALTED
            else result
        )

    monkeypatch.setattr(gate.state, "escalate", concurrent)
    monkeypatch.setattr(cro, "evaluate", stale_on_halt)
    with pytest.raises(DataIntegrityError) as refused:
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "R-02: risk boundary failed and latched HALTED"
    assert type(refused.value.__cause__) is DataIntegrityError
    assert str(refused.value.__cause__) == "R-05: rechecked verdict time differs from clock"
    assert gate.state.current() == SystemState.HALTED
    gate.state.ledger.verify_chain()


def test_R_05_initial_stale_verdict_keeps_exact_injected_clock_refusal(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    fresh = cro.evaluate(trade(), book(), quote(), SystemState.RUNNING, NOW, deployable=capital())
    stale = fresh.model_copy(update={"evaluated_at": NOW - timedelta(microseconds=1)})
    monkeypatch.setattr(cro, "evaluate", lambda *args, **kwargs: stale)
    with pytest.raises(DataIntegrityError) as refused:
        gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "R-02: risk boundary failed and latched HALTED"
    assert type(refused.value.__cause__) is DataIntegrityError
    assert str(refused.value.__cause__) == "R-05: verdict time does not match injected clock"
    assert gate.state.current() == SystemState.HALTED


@pytest.mark.parametrize("faulty_approval", [False, True])
def test_CRO_10_concurrent_host_reset_preserves_the_persisted_session_entry_block(
    engine: Engine,
    boundary_cro: ChiefRiskOfficer,
    monkeypatch: pytest.MonkeyPatch,
    faulty_approval: bool,
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    marks = PersistedPortfolioMarks(gate.state.ledger, "boundary-paper", cro.calendar, cro.config)
    marks.observe(book())
    marks.observe(book(equity="9800"))
    assert marks.daily_loss_blocked(NOW)
    gate.marks = marks
    honest = cro.evaluate
    unwitnessed = honest(trade(), book(), quote(), SystemState.RUNNING, NOW, deployable=capital())
    assert unwitnessed.decision == Decision.APPROVED
    gate.state.escalate(SystemState.HALTED, "offline independent host fault")
    reset = False

    def concurrent(*args: object, **kwargs: object) -> Verdict:
        nonlocal reset
        result = honest(*args, **kwargs)  # type: ignore[arg-type]
        if not reset:
            reset = True
            gate.state.operator_reset(
                "offline owner", "offline attributed reset during session loss block"
            )
        elif faulty_approval:
            return unwitnessed
        return result

    monkeypatch.setattr(cro, "evaluate", concurrent)
    if faulty_approval:
        with pytest.raises(DataIntegrityError) as refused:
            gate.evaluate(trade(), book(), quote(), deployable=capital())
        assert type(refused.value) is DataIntegrityError
        assert str(refused.value) == "R-02: risk boundary failed and latched HALTED"
        assert type(refused.value.__cause__) is DataIntegrityError
        assert (
            str(refused.value.__cause__)
            == "CRO-10: approval concealed a witnessed session loss block"
        )
        assert gate.state.current() == SystemState.HALTED
    else:
        result = gate.evaluate(trade(), book(), quote(), deployable=capital())
        assert (
            result.decision == Decision.VETOED
            and not next(row for row in result.results if row.rule_id == "CRO-10").passed
        )
        assert gate.state.current() == SystemState.RUNNING
    assert reset and marks.daily_loss_blocked(NOW)
    gate.state.ledger.verify_chain()
