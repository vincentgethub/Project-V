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
)
from backend.risk.boundary import LoggingVetoSink, RiskBoundary, VetoSink
from backend.risk.risk_cro import ChiefRiskOfficer

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
        Settings(),
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


def test_R_03_CRO_13_warn_approval_does_not_log_veto(
    engine: Engine, boundary_cro: ChiefRiskOfficer
) -> None:
    sink = VetoRecorder()
    gate = boundary(engine, boundary_cro, sink)
    result = gate.evaluate(trade(), book(), quote(), deployable=capital())
    assert result.decision == Decision.APPROVED
    assert len(result.results) == 13
    assert not result.results[-1].passed and result.results[-1].severity == Severity.WARN
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
