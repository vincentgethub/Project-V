"""R-02/CMP-06/CRO-12/DAT-01: provider faults and identity never reach approval."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import Clock, FrozenClock
from backend.core.config import Settings
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    LiquidityUnavailable,
    StaleDataError,
)
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.boundary import ReadBoundary
from backend.data.liquidity import (
    BalanceReading,
    FakeLiquiditySource,
    LiquidityGate,
    LiquiditySource,
)
from backend.domain.models import AccountFlags, CapitalStatus, DeployableCapital, PortfolioSnapshot

NOW = datetime(2026, 10, 4, 15, tzinfo=UTC)


def snapshot(**updates: object) -> PortfolioSnapshot:
    """R-02: synthetic managed account used only in offline safety tests."""
    values: dict[str, object] = {
        "account_id": "managed-test",
        "account_type": "CASH",
        "as_of": NOW,
        "equity": Decimal("25000"),
        "cash": Decimal("25000"),
        "settled_cash": Decimal("25000"),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("25000"),
        "day_start_equity": Decimal("25000"),
    }
    values.update(updates)
    return PortfolioSnapshot.model_validate(values)


class Broker:
    """R-08: injectable read-only provider with explicit account flags."""

    def __init__(self, value: PortfolioSnapshot | None = None, *, blocked: bool = False) -> None:
        self.value = snapshot() if value is None else value
        self.last_flags: AccountFlags | None = AccountFlags(
            trading_blocked=blocked,
            account_blocked=False,
            trade_suspended_by_user=False,
            status="ACTIVE",
        )

    def snapshot(self, now: datetime) -> PortfolioSnapshot:
        """R-05: return an injected immutable account reading."""
        return self.value


class FaultSource:
    """R-02: reproducible unexpected and expected liquidity failures."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def read(self) -> BalanceReading:
        """CRO-12: raise instead of manufacturing bank capacity."""
        raise self.error


def boundary(
    engine: Engine,
    *,
    broker: Broker | None = None,
    source: LiquiditySource | None = None,
    clock: Clock | None = None,
    config: Settings | None = None,
) -> ReadBoundary:
    """R-02: real SQLite state boundary with network-free injected providers."""
    local_clock = FrozenClock(NOW) if clock is None else clock
    policy = (
        Settings(
            broker_account_type="CASH",
        )
        if config is None
        else config
    )
    bank = (
        FakeLiquiditySource(
            BalanceReading(
                available=Decimal("3000"),
                current=Decimal("4000"),
                currency="USD",
                as_of=NOW,
            )
        )
        if source is None
        else source
    )
    return ReadBoundary(
        policy,
        SystemStateStore(engine, local_clock, ConsoleNotifier()),
        local_clock,
        Broker() if broker is None else broker,
        LiquidityGate(policy, bank, local_clock),
        account_id="managed-test",
    )


def test_R_08_reads_do_not_authorize_trades_and_halts_survive_reads(engine: Engine) -> None:
    reads = boundary(engine)
    assert reads.portfolio().snapshot.account_id == "managed-test"
    assert reads.funding().deployable == Decimal("1500")
    assert reads.state.current() == SystemState.RUNNING
    reads.state.escalate(SystemState.HALTED, "operator investigation")
    assert reads.portfolio().snapshot.cash == Decimal("25000")
    assert reads.state.current() == SystemState.HALTED


@pytest.mark.parametrize("account_id", ["", " managed-test", None, 1])
def test_R_02_managed_account_must_be_explicit_and_unambiguous(
    engine: Engine, account_id: object
) -> None:
    reads = boundary(engine)
    with pytest.raises(ConfigurationError):
        ReadBoundary(
            reads.config,
            reads.state,
            reads.clock,
            reads.broker,
            reads.liquidity,
            account_id=cast(str, account_id),
        )


def test_CRO_10_monitor_read_records_breach_through_recovery(engine: Engine) -> None:
    """CRO-10: no risk evaluation is needed to remember a witnessed loss."""
    broker = Broker(snapshot(equity=Decimal("24500")))
    reads = boundary(engine, broker=broker)
    assert reads.portfolio().snapshot.equity == Decimal("24500")
    assert reads.state.current() == SystemState.RUNNING
    broker.value = snapshot(equity=Decimal("25000"))
    assert reads.portfolio().snapshot.equity == Decimal("25000")
    assert reads.marks.daily_loss_blocked(NOW)


def test_CRO_09_CRO_10_read_boundary_refuses_marks_for_other_account(engine: Engine) -> None:
    """R-02: a supplied marks callback cannot cross the managed account binding."""
    reads = boundary(engine)
    reads.marks.account_id = "other"
    with pytest.raises(ConfigurationError, match="marks differ"):
        ReadBoundary(
            reads.config,
            reads.state,
            reads.clock,
            reads.broker,
            reads.liquidity,
            account_id="managed-test",
            marks=reads.marks,
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"account_id": "other"},
        {"account_type": "MARGIN"},
        {"as_of": NOW - timedelta(seconds=1)},
        {"as_of": NOW + timedelta(seconds=1)},
    ],
)
def test_R_02_DAT_02_snapshot_must_bind_account_type_identity_and_read_time(
    engine: Engine, updates: dict[str, object]
) -> None:
    reads = boundary(engine, broker=Broker(snapshot(**updates)))
    with pytest.raises(DataIntegrityError):
        reads.portfolio()
    assert reads.state.current() == SystemState.HALTED
    restarted = SystemStateStore(engine, FrozenClock(NOW), ConsoleNotifier())
    assert restarted.current() == SystemState.HALTED


def test_CMP_06_broker_restrictions_latch_halt_but_holdings_remain_readable(engine: Engine) -> None:
    reads = boundary(engine, broker=Broker(blocked=True))
    assert reads.portfolio().flags.blocked
    assert reads.state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "equity,state",
    [
        (Decimal("24500"), SystemState.RUNNING),
        (Decimal("23000"), SystemState.REDUCE_ONLY),
        (Decimal("22000"), SystemState.HALTED),
    ],
)
def test_CRO_09_CRO_10_reads_latch_financial_tiers(
    engine: Engine, equity: Decimal, state: SystemState
) -> None:
    reads = boundary(engine, broker=Broker(snapshot(equity=equity)))
    assert reads.portfolio().snapshot.equity == equity
    assert reads.state.current() == state


@pytest.mark.parametrize(
    "flags",
    [
        None,
        AccountFlags.model_construct(
            trading_blocked="false",
            account_blocked=False,
            trade_suspended_by_user=False,
            status="ACTIVE",
        ),
    ],
)
def test_CMP_06_missing_or_forged_flags_halt(engine: Engine, flags: AccountFlags | None) -> None:
    broker = Broker()
    broker.last_flags = flags
    reads = boundary(engine, broker=broker)
    with pytest.raises(DataIntegrityError):
        reads.portfolio()
    assert reads.state.current() == SystemState.HALTED


@pytest.mark.parametrize("fault", [RuntimeError("transport"), DataIntegrityError("invalid")])
def test_R_02_unexpected_bank_faults_halt_and_invalidate_funding(
    engine: Engine, fault: Exception
) -> None:
    reads = boundary(engine, source=FaultSource(fault))
    with pytest.raises(DataIntegrityError):
        reads.funding(refresh=True)
    assert reads.state.current() == SystemState.HALTED


def test_CRO_12_expected_unavailable_balance_vetoes_without_manufacturing_funds(
    engine: Engine,
) -> None:
    reads = boundary(engine, source=FaultSource(LiquidityUnavailable("login needed")))
    assert reads.funding().status == CapitalStatus.UNAVAILABLE
    assert reads.funding().deployable == 0
    assert reads.state.current() == SystemState.RUNNING


def test_CRO_12_forged_gate_output_cannot_change_funding_policy(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = boundary(engine)
    altered = DeployableCapital(
        checking_used=Decimal("3000"),
        buffer=Decimal("0"),
        reserved=Decimal("0"),
        deployable=Decimal("3000"),
        status=CapitalStatus.OK,
    )
    monkeypatch.setattr(reads.liquidity, "evaluate", lambda **kwargs: altered)
    with pytest.raises(DataIntegrityError, match="policy"):
        reads.funding()
    assert reads.state.current() == SystemState.HALTED


class SequenceClock:
    """DAT-02: model time moving during a slow provider operation."""

    def __init__(self, delta: int) -> None:
        self.delta = delta
        self.calls = 0

    def now(self) -> datetime:
        """R-05: injected deterministic progression, no wall clock."""
        self.calls += 1
        return NOW if self.calls == 1 else NOW + timedelta(seconds=self.delta)


@pytest.mark.parametrize("delta,expected", [(-1, DataIntegrityError), (61, StaleDataError)])
def test_DAT_01_DAT_02_slow_read_or_backwards_clock_halts(
    engine: Engine, delta: int, expected: type[Exception]
) -> None:
    reads = boundary(engine)
    reads.clock = SequenceClock(delta)
    with pytest.raises(expected):
        reads.portfolio()
    assert reads.state.current() == SystemState.HALTED


@pytest.mark.parametrize("operation", ["portfolio", "funding"])
def test_R_02_database_faults_latch_process_halt(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    reads = boundary(engine)

    def broken() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(reads.state.ledger, "verify_chain", broken)
    with pytest.raises(DataIntegrityError):
        if operation == "portfolio":
            reads.portfolio()
        else:
            reads.funding()
    assert reads.state.current() == SystemState.HALTED


def test_R_02_audit_faults_still_attempt_durable_halt(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.data.boundary as module

    reads = boundary(engine, source=FaultSource(RuntimeError("bank failed")))

    class BrokenAudit:
        def error(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("audit unavailable")

    monkeypatch.setattr(module, "logging", SimpleNamespace(getLogger=lambda *args: BrokenAudit()))
    with pytest.raises(DataIntegrityError):
        reads.funding()
    assert reads.state.current() == SystemState.HALTED
