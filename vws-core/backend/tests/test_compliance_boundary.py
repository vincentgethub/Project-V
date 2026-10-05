"""R-02/R-03/R-09/CMP-06: durable compliance audit and provider faults."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    AssetClass,
    Instrument,
    Intent,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    Severity,
    Side,
    TradeProposal,
)
from backend.risk.compliance import (
    ComplianceAssessment,
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TaxStatus,
)
from backend.risk.compliance_boundary import (
    ComplianceBoundary,
    ComplianceFindingSink,
    LoggingComplianceFindingSink,
)

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
PROPOSAL_ID = UUID("60000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("60000000-0000-0000-0000-000000000002")
LOT_ID = UUID("60000000-0000-0000-0000-000000000003")
ACCOUNTS = (ExternalAccount(account_id="boundary-paper", tax_status=TaxStatus.TAXABLE),)
FLAGS = AccountFlags(
    trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
)


class LocalNotifier:
    """R-02: observable notifications without an external service."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def notify(self, state: str, reason: str) -> None:
        self.calls.append((state, reason))


class FindingRecorder:
    """R-02: deterministic audit failure injection."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, UUID, Severity]] = []

    def record(self, rule_id: str, proposal_id: UUID, severity: Severity) -> None:
        self.calls.append((rule_id, proposal_id, severity))
        if self.fail:
            raise RuntimeError("compliance audit unavailable")


class FailedClock:
    """R-05: time failure cannot become a guessed timestamp."""

    def now(self) -> datetime:
        raise RuntimeError("clock failure")


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def policy(calendar: MarketCalendar) -> ComplianceEngine:
    instrument = Instrument(
        symbol="AAPL",
        asset_class=AssetClass.STOCK,
        gics_sector="Information Technology",
        themes=(),
        is_leveraged=False,
        is_inverse=False,
        tradable=True,
    )
    return ComplianceEngine(Settings(), InstrumentRegistry((instrument,)), calendar)


def proposal(*, selling: bool = False) -> TradeProposal:
    return TradeProposal(
        proposal_id=PROPOSAL_ID,
        signal_id=SIGNAL_ID,
        account_id="boundary-paper",
        symbol="AAPL",
        side=Side.SELL if selling else Side.BUY,
        intent=Intent.EXIT if selling else Intent.ENTRY,
        qty=1,
        limit_price=Decimal("100.00"),
        stop_price=None if selling else Decimal("95.00"),
        source=ProposalSource.SIGNAL,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def snapshot(*, selling: bool = False, settled: str = "10000") -> PortfolioSnapshot:
    return PortfolioSnapshot(
        account_id="boundary-paper",
        account_type=AccountType.CASH,
        as_of=NOW,
        equity=Decimal("10000"),
        cash=Decimal("10000"),
        settled_cash=Decimal(settled),
        positions={
            "AAPL": Position(qty=1, avg_cost=Decimal("110.00"), last_price=Decimal("100.00"))
        }
        if selling
        else {},
        open_orders=(),
        high_water_mark=Decimal("10000"),
        day_start_equity=Decimal("10000"),
    )


def lots() -> tuple[TaxLot, ...]:
    return (
        TaxLot(
            lot_id=LOT_ID,
            account_id="boundary-paper",
            symbol="AAPL",
            qty=1,
            acquired_at=NOW - timedelta(days=100),
            cost_basis=Decimal("110.00"),
            funding_settlement_date=date(2026, 10, 1),
        ),
    )


def boundary(
    engine: Engine, calendar: MarketCalendar, sink: ComplianceFindingSink | None = None
) -> ComplianceBoundary:
    clock = FrozenClock(NOW)
    return ComplianceBoundary(
        policy(calendar), SystemStateStore(engine, clock, LocalNotifier()), clock, finding_sink=sink
    )


def test_R_03_CMP_01_07_complete_pure_evidence(engine: Engine, calendar: MarketCalendar) -> None:
    recorder = FindingRecorder()
    gate = boundary(engine, calendar, recorder)
    result = gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)
    assert len(result.results) == 7 and all(row.passed for row in result.results)
    assert result.proposal_id == PROPOSAL_ID and result.evaluated_at == NOW
    assert gate.state.current() == SystemState.RUNNING and recorder.calls == []


def test_CMP_03_ordinary_cash_failure_logs_without_halt(
    engine: Engine, calendar: MarketCalendar
) -> None:
    recorder = FindingRecorder()
    gate = boundary(engine, calendar, recorder)
    result = gate.evaluate(proposal(), snapshot(settled="99.99"), (), (), ACCOUNTS, flags=FLAGS)
    assert not result.results[2].passed and result.results[2].severity == Severity.BLOCK
    assert recorder.calls == [("CMP-03", PROPOSAL_ID, Severity.BLOCK)]
    assert gate.state.current() == SystemState.RUNNING


@pytest.mark.parametrize("missing", [False, True])
def test_CMP_06_broker_flags_halt_and_survive_restart(
    engine: Engine, calendar: MarketCalendar, missing: bool
) -> None:
    gate = boundary(engine, calendar)
    flags = None if missing else FLAGS.model_copy(update={"account_blocked": True})
    result = gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=flags)
    assert not result.results[5].passed and result.recommended_state == SystemState.HALTED
    assert (
        SystemStateStore(engine, FrozenClock(NOW), LocalNotifier()).current() == SystemState.HALTED
    )


def test_R_09_CMP_06_valid_exit_warns_while_persisting_halt(
    engine: Engine, calendar: MarketCalendar
) -> None:
    recorder = FindingRecorder()
    gate = boundary(engine, calendar, recorder)
    result = gate.evaluate(
        proposal(selling=True), snapshot(selling=True), lots(), (), ACCOUNTS, flags=None
    )
    assert all(row.severity == Severity.WARN for row in result.results)
    assert not result.results[5].passed and gate.state.current() == SystemState.HALTED
    assert ("CMP-06", PROPOSAL_ID, Severity.WARN) in recorder.calls


@pytest.mark.parametrize("fault", ["clock", "database", "engine", "audit"])
def test_R_02_boundary_provider_faults_halt(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    gate = boundary(engine, calendar, FindingRecorder(fail=fault == "audit"))

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected failure")

    if fault == "clock":
        gate.clock = FailedClock()
    elif fault == "database":
        monkeypatch.setattr(gate.state.ledger, "verify_chain", fail)
    elif fault == "engine":
        monkeypatch.setattr(gate.engine, "assess", fail)
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(proposal(), snapshot(settled="99.99"), (), (), ACCOUNTS, flags=FLAGS)
    assert gate.state.current() == SystemState.HALTED


def test_R_02_failed_halt_persistence_remains_typed(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    gate.clock = FailedClock()

    def fail(error: Exception) -> SystemState:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(gate.state, "halt_for_error", fail)
    with pytest.raises(DataIntegrityError, match="HALT persistence unavailable"):
        gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)


@pytest.mark.parametrize(
    "attack",
    [
        "id",
        "config",
        "time",
        "missing",
        "duplicate",
        "snapshot",
        "severity",
        "broker_halt",
        "concealed_flags",
        "exit_block",
        "input_hash",
        "wash_severity",
    ],
)
def test_R_02_forged_compliance_assessment_fails_closed(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    gate = boundary(engine, calendar)
    selling = attack == "exit_block"
    trade = proposal(selling=selling)
    book = snapshot(selling=selling)
    inventory = lots() if selling else ()
    legitimate = gate.engine.assess(trade, book, inventory, (), ACCOUNTS, NOW, flags=FLAGS)
    actual_flags = (
        FLAGS.model_copy(update={"trading_blocked": True}) if attack == "concealed_flags" else FLAGS
    )
    fields: dict[str, object] = {}
    if attack == "id":
        fields["proposal_id"] = SIGNAL_ID
    elif attack == "config":
        fields["config_hash"] = "f" * 64
    elif attack == "time":
        fields["evaluated_at"] = NOW - timedelta(seconds=1)
    elif attack == "missing":
        fields["results"] = legitimate.results[:-1]
    elif attack == "duplicate":
        fields["results"] = (*legitimate.results[:-1], legitimate.results[0])
    elif attack == "snapshot":
        fields["snapshot_hash"] = "f" * 64
    elif attack == "input_hash":
        fields["input_hash"] = "f" * 64
    elif attack == "wash_severity":
        fields["results"] = (
            legitimate.results[0].model_copy(update={"passed": False, "severity": Severity.WARN}),
            *legitimate.results[1:],
        )
    elif attack in {"severity", "exit_block"}:
        replacement = legitimate.results[2].model_copy(
            update={"severity": Severity.BLOCK if selling else Severity.WARN}
        )
        fields["results"] = (*legitimate.results[:2], replacement, *legitimate.results[3:])
    elif attack == "broker_halt":
        fields["results"] = (
            *legitimate.results[:5],
            legitimate.results[5].model_copy(update={"passed": False}),
            legitimate.results[6],
        )
        fields["recommended_state"] = SystemState.RUNNING
    elif attack == "concealed_flags":
        fields["input_hash"] = gate.engine.input_hash(
            trade, book, inventory, (), ACCOUNTS, actual_flags
        )
    forged = legitimate.model_copy(update=fields)

    def returning(*args: object, **kwargs: object) -> ComplianceAssessment:
        return forged

    monkeypatch.setattr(gate.engine, "assess", returning)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(trade, book, inventory, (), ACCOUNTS, flags=actual_flags)
    assert gate.state.current() == SystemState.HALTED


def test_R_02_audit_sink_contract_and_log_ids(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(DataIntegrityError, match="no implementation"):
        ComplianceFindingSink.record(
            cast(ComplianceFindingSink, object()), "CMP-06", PROPOSAL_ID, Severity.BLOCK
        )
    LoggingComplianceFindingSink().record("CMP-06", PROPOSAL_ID, Severity.WARN)
    assert f"proposal_id={PROPOSAL_ID}" in caplog.text and "rule_id=CMP-06" in caplog.text


def test_R_02_logging_failure_does_not_skip_halt(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    gate.clock = FailedClock()

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("logging failure")

    monkeypatch.setattr(logging.getLogger("backend.risk.compliance_boundary"), "error", fail)
    with pytest.raises(DataIntegrityError, match="latched HALTED"):
        gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)
    assert gate.state.current() == SystemState.HALTED


def test_R_09_corrupt_tax_context_warns_and_halts_for_valid_exit(
    engine: Engine, calendar: MarketCalendar
) -> None:
    gate = boundary(engine, calendar)
    invalid_flags = FLAGS.model_copy(update={"account_blocked": "unknown"})
    result = gate.evaluate(
        proposal(selling=True), snapshot(selling=True), lots(), (), ACCOUNTS, flags=invalid_flags
    )
    assert result.input_hash == "0" * 64
    assert all(not row.passed and row.severity == Severity.WARN for row in result.results)
    assert gate.state.current() == SystemState.HALTED


@pytest.mark.parametrize("fault", ["oversell", "stale", "no_holding"])
def test_R_09_unverifiable_exit_is_not_a_valid_exit_exception(
    engine: Engine, calendar: MarketCalendar, fault: str
) -> None:
    gate = boundary(engine, calendar)
    trade = proposal(selling=True)
    book = snapshot(selling=True)
    if fault == "oversell":
        trade = trade.model_copy(update={"qty": 2})
    elif fault == "stale":
        book = book.model_copy(update={"as_of": NOW - timedelta(seconds=61)})
    else:
        book = book.model_copy(update={"positions": {}})
    result = gate.evaluate(trade, book, lots(), (), ACCOUNTS, flags=FLAGS)
    assert all(not row.passed and row.severity == Severity.BLOCK for row in result.results)
    assert gate.state.current() == SystemState.HALTED


def test_R_03_cached_assessment_cannot_authorize_changed_quantity(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    book = snapshot(settled="100")
    previous = gate.engine.assess(proposal(), book, (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert all(row.passed for row in previous.results)

    def cached(*args: object, **kwargs: object) -> ComplianceAssessment:
        return previous

    monkeypatch.setattr(gate.engine, "assess", cached)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(proposal().model_copy(update={"qty": 2}), book, (), (), ACCOUNTS, flags=FLAGS)
    assert gate.state.current() == SystemState.HALTED


def test_R_02_unhashed_maximal_failure_can_only_halt(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = boundary(engine, calendar)
    result = gate.engine.assess(proposal(), snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)
    failed = result.model_copy(
        update={
            "snapshot_hash": "0" * 64,
            "recommended_state": SystemState.HALTED,
            "results": tuple(
                row.model_copy(update={"passed": False, "severity": Severity.BLOCK})
                for row in result.results
            ),
        }
    )

    def returning(*args: object, **kwargs: object) -> ComplianceAssessment:
        return failed

    monkeypatch.setattr(gate.engine, "assess", returning)
    assessment = gate.evaluate(proposal(), snapshot(), (), (), ACCOUNTS, flags=FLAGS)
    assert all(not row.passed for row in assessment.results)
    assert gate.state.current() == SystemState.HALTED
