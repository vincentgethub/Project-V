"""CMP-01..07/R-02/R-09: exact boundaries, cross-account matching and faults."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    Intent,
    OpenOrder,
    Position,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
    snapshot_hash,
)
from backend.risk.compliance import (
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TaxStatus,
    TradeRecord,
)
from backend.tests.test_domain import NOW, instrument, proposal, snapshot

ACCOUNTS = (
    ExternalAccount(account_id="paper", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="other", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="ira", tax_status=TaxStatus.IRA),
    ExternalAccount(account_id="roth", tax_status=TaxStatus.ROTH),
)
FLAGS = AccountFlags(
    trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
)


def uid(value: int) -> UUID:
    return UUID(int=value)


def trade(
    value: int,
    *,
    side: Side = Side.BUY,
    days: int = -1,
    qty: int = 10,
    loss: str = "0",
    account: str = "paper",
    symbol: str = "AAPL",
    ts: datetime | None = None,
    price: str = "100",
) -> TradeRecord:
    return TradeRecord(
        trade_id=uid(value),
        account_id=account,
        symbol=symbol,
        side=side,
        qty=qty,
        price=Decimal(price),
        ts=ts if ts is not None else NOW + timedelta(days=days),
        realized_loss=Decimal(loss),
        holding_period_start=NOW - timedelta(days=100) if Decimal(loss) > 0 else None,
    )


def lot(
    value: int = 1,
    *,
    qty: int = 1,
    basis: str = "110",
    days: int = -100,
    funding: date | None = None,
) -> TaxLot:
    return TaxLot(
        lot_id=uid(value),
        account_id="paper",
        symbol="AAPL",
        qty=qty,
        acquired_at=NOW + timedelta(days=days),
        cost_basis=Decimal(basis),
        funding_settlement_date=funding,
    )


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2027, 12, 31))


@pytest.fixture
def engine(calendar: MarketCalendar) -> ComplianceEngine:
    registry = InstrumentRegistry(
        [instrument(), instrument("MSFT")],
        identical_groups={"TEST_OPERATOR_GROUP": ("AAPL", "MSFT")},
    )
    return ComplianceEngine(Settings(), registry, calendar)


def check(
    engine: ComplianceEngine,
    *,
    selling: bool = False,
    history: tuple[TradeRecord, ...] = (),
    lots: tuple[TaxLot, ...] = (),
    state_changes: dict[str, object] | None = None,
    proposal_changes: dict[str, object] | None = None,
    flags: AccountFlags | None = FLAGS,
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS,
) -> dict[str, RuleResult]:
    changes: dict[str, object] = (
        {"side": Side.SELL, "intent": Intent.EXIT, "stop_price": None} if selling else {}
    )
    changes.update(proposal_changes or {})
    return {
        row.rule_id: row
        for row in engine.check(
            proposal(**changes),
            snapshot(**(state_changes or {})),
            lots,
            history,
            accounts,
            NOW,
            flags=flags,
        )
    }


@pytest.mark.parametrize("days,expected", [(-30, False), (-31, True), (-1, False), (0, False)])
def test_CMP_01_forward_day30_inclusive_day31_excluded(
    engine: ComplianceEngine, days: int, expected: bool
) -> None:
    result = check(engine, history=(trade(1, side=Side.SELL, days=days, loss="100"),))["CMP-01"]
    assert result.passed is expected
    assert result.severity == Severity.BLOCK
    assert Decimal(result.observed) == (Decimal(0) if expected else Decimal("10"))


def test_CMP_01_warn_mode_and_forward_ira_permanent_loss(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    warning = ComplianceEngine(Settings(wash_sale_mode="WARN"), engine.registry, calendar)
    result = check(warning, history=(trade(1, side=Side.SELL, account="other", loss="100"),))[
        "CMP-01"
    ]
    assert not result.passed and result.severity == Severity.WARN
    candidate = proposal(account_id="ira")
    state = snapshot(account_id="ira")
    results = engine.check(
        candidate, state, (), (trade(2, side=Side.SELL, loss="100"),), ACCOUNTS, NOW, flags=FLAGS
    )
    forward = next(row for row in results if row.rule_id == "CMP-01")
    assert "permanent loss" in forward.message and not forward.passed


@pytest.mark.parametrize("days,expected", [(-30, False), (-31, True), (-1, False), (0, False)])
def test_CMP_02_backward_cross_account_substantially_identical_day_boundary(
    engine: ComplianceEngine, days: int, expected: bool
) -> None:
    result = check(
        engine,
        selling=True,
        lots=(lot(),),
        history=(trade(1, days=days, symbol="MSFT", account="other", qty=1),),
    )["CMP-02"]
    assert result.passed is expected and result.severity == Severity.WARN
    assert Decimal(result.observed) == (Decimal(0) if expected else Decimal("10"))


def test_CMP_02_backward_sale_profit_and_ira_loss_are_warn_only(engine: ComplianceEngine) -> None:
    profitable = check(engine, selling=True, lots=(lot(basis="90"),), history=(trade(1),))["CMP-02"]
    assert profitable.passed
    permanent = check(engine, selling=True, lots=(lot(),), history=(trade(1, account="ira"),))[
        "CMP-02"
    ]
    assert not permanent.passed and "permanent" in permanent.message
    assert all(
        row.severity == Severity.WARN
        for row in check(
            engine, selling=True, lots=(lot(),), history=(trade(1, account="ira"),)
        ).values()
    )


def test_CMP_01_CMP_02_share_capacity_is_shared_across_multiple_loss_sales(
    engine: ComplianceEngine,
) -> None:
    losses = (
        trade(1, side=Side.SELL, days=-2, qty=5, loss="50"),
        trade(2, side=Side.SELL, days=-1, qty=5, loss="100"),
    )
    replacement = trade(3, days=0, qty=6, account="other")
    rows = engine.wash_adjustments((*losses, replacement), ACCOUNTS)
    assert [row.qty for row in rows] == [5, 1]
    assert [row.disallowed_loss for row in rows] == [Decimal("50"), Decimal("20")]
    assert sum(row.qty for row in rows) == replacement.qty
    assert sum((row.disallowed_loss for row in rows), Decimal(0)) == Decimal("70")


def test_CMP_02_61_day_window_partial_lots_basis_tacking_and_8949(engine: ComplianceEngine) -> None:
    sale = trade(1, side=Side.SELL, days=0, qty=10, loss="100", price="90")
    records = (
        trade(2, days=-30, qty=2, price="95"),
        sale,
        trade(3, days=30, qty=3, price="80"),
        trade(4, days=31, qty=10),
    )
    rows = engine.wash_adjustments(records, ACCOUNTS)
    assert [row.qty for row in rows] == [2, 3]
    assert [row.disallowed_loss for row in rows] == [Decimal("20"), Decimal("30")]
    assert [row.adjusted_basis for row in rows] == [Decimal("210"), Decimal("270")]
    assert rows[0].holding_period_start == records[0].ts - timedelta(days=100)
    # Holding periods count exchange-local calendar days across November DST.
    assert rows[1].holding_period_start == datetime(2026, 7, 24, 15, tzinfo=UTC)
    assert rows[1].holding_period_start.astimezone(ZoneInfo("America/New_York")).date() == date(
        2026, 7, 24
    )
    exported = engine.form_8949_rows(rows)
    assert [row.code for row in exported] == ["W", "W"]
    assert [row.adjustment for row in exported] == [Decimal("20"), Decimal("30")]
    assert [row.proceeds for row in exported] == [Decimal("180"), Decimal("270")]
    assert all(row.gain_or_loss == 0 for row in exported)


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_CMP_01_ira_roth_replacement_does_not_adjust_retirement_basis(
    engine: ComplianceEngine, account: str
) -> None:
    rows = engine.wash_adjustments(
        (trade(1, side=Side.SELL, loss="100"), trade(2, days=0, qty=2, account=account)), ACCOUNTS
    )
    assert rows[0].permanent_loss and rows[0].adjusted_basis is None
    assert rows[0].disallowed_loss == Decimal("20")


def test_CMP_02_fractional_loss_allocation_reconciles_exact_total(engine: ComplianceEngine) -> None:
    rows = engine.wash_adjustments(
        (
            trade(1, side=Side.SELL, qty=3, loss="1"),
            trade(2, days=0, qty=1),
            trade(3, days=0, qty=2),
        ),
        ACCOUNTS,
    )
    assert [row.disallowed_loss for row in rows] == [Decimal("0.333333"), Decimal("0.666667")]
    assert sum((row.disallowed_loss for row in rows), Decimal(0)) == Decimal(1)


@pytest.mark.parametrize("cash,expected", [("100", True), ("99.99", False), ("100.01", True)])
def test_CMP_03_settled_cash_exact_notional_boundary(
    engine: ComplianceEngine, cash: str, expected: bool
) -> None:
    assert check(engine, state_changes={"settled_cash": Decimal(cash)})["CMP-03"].passed is expected


def test_CMP_03_pending_buys_reserve_settled_cash_and_margin_is_exempt(
    engine: ComplianceEngine,
) -> None:
    pending = OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal("100"))
    assert not check(
        engine, state_changes={"settled_cash": Decimal("199.99"), "open_orders": (pending,)}
    )["CMP-03"].passed
    assert check(
        engine, state_changes={"account_type": AccountType.MARGIN, "settled_cash": Decimal(0)}
    )["CMP-03"].passed


@pytest.mark.parametrize(
    "funding,expected",
    [
        (date(2026, 10, 1), True),
        (date(2026, 10, 2), False),
        (date(2026, 10, 5), False),
        (None, False),
    ],
)
def test_CMP_03_good_faith_sale_only_warns_at_settlement_boundary(
    engine: ComplianceEngine, funding: date | None, expected: bool
) -> None:
    row = check(engine, selling=True, lots=(lot(funding=funding),))["CMP-03"]
    assert row.passed is expected and row.severity == Severity.WARN


@pytest.mark.parametrize(
    "ts,expected",
    [
        (datetime(2026, 7, 3, 0, 30, tzinfo=UTC), date(2026, 7, 6)),
        (datetime(2025, 11, 27, 0, 30, tzinfo=UTC), date(2025, 11, 28)),
        (datetime(2026, 12, 24, 17, tzinfo=UTC), date(2026, 12, 28)),
    ],
)
def test_CMP_03_T_plus_one_uses_new_york_trade_date_with_holidays(
    engine: ComplianceEngine, ts: datetime, expected: date
) -> None:
    assert engine.settlement_date(ts) == expected


def test_CMP_03_settled_cash_reconstruction_does_not_credit_unsettled_sales(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    executed = datetime(2026, 7, 2, 16, tzinfo=UTC)
    rows = (
        trade(1, side=Side.SELL, ts=executed, qty=2),
        trade(2, side=Side.BUY, ts=executed, qty=1),
        trade(3, side=Side.SELL, ts=executed, account="other"),
    )
    closed = calendar.session_close(date(2026, 7, 6))
    assert engine.settled_cash_as_of(
        Decimal("500"), rows, closed - timedelta(microseconds=1), account_id="paper"
    ) == Decimal("400")
    assert engine.settled_cash_as_of(Decimal("500"), rows, closed, account_id="paper") == Decimal(
        "600"
    )


@pytest.mark.parametrize("cash,expected", [("100", True), ("99.99", False), ("100.01", True)])
def test_CMP_04_no_borrowing_exact_cash_boundary(
    engine: ComplianceEngine, cash: str, expected: bool
) -> None:
    assert check(engine, state_changes={"cash": Decimal(cash)})["CMP-04"].passed is expected


@pytest.mark.parametrize("equity,expected", [("2000", True), ("1999.99", False), ("2000.01", True)])
def test_CMP_04_margin_minimum_equity_operator_guard_boundary(
    engine: ComplianceEngine, equity: str, expected: bool
) -> None:
    assert (
        check(
            engine, state_changes={"account_type": AccountType.MARGIN, "equity": Decimal(equity)}
        )["CMP-04"].passed
        is expected
    )


def legacy_history() -> tuple[TradeRecord, ...]:
    rows: list[TradeRecord] = []
    for index, day in enumerate((28, 29, 30)):
        opened = datetime(2026, 9, day, 14, tzinfo=UTC)
        rows.extend(
            (
                trade(index * 2 + 1, ts=opened),
                trade(index * 2 + 2, side=Side.SELL, ts=opened + timedelta(hours=1)),
            )
        )
    rows.append(trade(20, side=Side.SELL, ts=NOW - timedelta(hours=1)))
    return tuple(rows)


@pytest.mark.parametrize(
    "regime,equity,severity",
    [
        ("INTRADAY_MARGIN", "24999.99", Severity.WARN),
        ("LEGACY_PDT", "24999.99", Severity.BLOCK),
        ("LEGACY_PDT", "25000", Severity.WARN),
        ("LEGACY_PDT", "25000.01", Severity.WARN),
    ],
)
def test_CMP_05_both_regimes_and_25000_exact_legacy_boundary(
    engine: ComplianceEngine, calendar: MarketCalendar, regime: str, equity: str, severity: Severity
) -> None:
    guarded = ComplianceEngine(
        Settings.model_validate({"day_trade_regime": regime}), engine.registry, calendar
    )
    row = check(
        guarded,
        history=legacy_history(),
        state_changes={"account_type": AccountType.MARGIN, "equity": Decimal(equity)},
    )["CMP-05"]
    assert not row.passed and row.severity == severity
    assert "completed=3" in row.observed


def test_CMP_05_legacy_three_count_and_cash_account_boundary(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    guarded = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), engine.registry, calendar)
    for history in (legacy_history()[2:], legacy_history()):
        row = check(guarded, history=history)["CMP-05"]
        assert row.severity == Severity.WARN
    assert check(guarded)["CMP-05"].passed
    exit_result = check(
        guarded, selling=True, lots=(lot(),), history=(*legacy_history()[:-1], trade(30, days=0))
    )["CMP-05"]
    assert not exit_result.passed and exit_result.severity == Severity.WARN


@pytest.mark.parametrize(
    "field", ["trading_blocked", "account_blocked", "trade_suspended_by_user", "status", "missing"]
)
def test_CMP_06_each_exact_current_broker_flag_requires_halt(
    engine: ComplianceEngine, field: str
) -> None:
    flags = (
        None
        if field == "missing"
        else FLAGS.model_copy(update={field: "ACCOUNT_UPDATED" if field == "status" else True})
    )
    row = check(engine, flags=flags)["CMP-06"]
    assert not row.passed and row.severity == Severity.BLOCK and "HALTED required" in row.message
    assert (
        check(engine, selling=True, lots=(lot(),), flags=flags)["CMP-06"].severity == Severity.WARN
    )


def test_CMP_07_allowlist_restricted_leveraged_inverse_and_unknown_names(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    assert check(engine)["CMP-07"].passed
    restricted = ComplianceEngine(
        Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
    )
    assert not check(restricted)["CMP-07"].passed
    registry = InstrumentRegistry.from_csv(Path(__file__).resolve().parents[2] / "config")
    sample = ComplianceEngine(Settings(), registry, calendar)
    for symbol in ("TQQQ", "SH", "UNKNOWN"):
        row = check(sample, proposal_changes={"symbol": symbol})["CMP-07"]
        assert not row.passed and row.severity == Severity.BLOCK


@pytest.mark.parametrize(
    "fault",
    [
        "account",
        "future_snapshot",
        "future_proposal",
        "missing_account",
        "future_trade",
        "unknown_trade_account",
        "future_lot",
        "unknown_lot_account",
        "duplicate_trade",
        "duplicate_lot",
        "duplicate_account",
        "executed_proposal",
    ],
)
def test_R_02_compliance_corrupt_state_warns_only_verifiable_exits(
    engine: ComplianceEngine, fault: str
) -> None:
    states: dict[str, object] = {}
    proposed: dict[str, object] = {}
    rows: tuple[TradeRecord, ...] = ()
    lots: tuple[TaxLot, ...] = (lot(),)
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS
    if fault == "account":
        states["account_id"] = "mismatch"
    elif fault == "future_snapshot":
        states["as_of"] = NOW + timedelta(seconds=1)
    elif fault == "future_proposal":
        proposed["created_at"] = NOW + timedelta(seconds=1)
    elif fault == "missing_account":
        accounts = ACCOUNTS[1:]
    elif fault == "future_trade":
        rows = (trade(1, days=1),)
    elif fault == "unknown_trade_account":
        rows = (trade(1, account="unknown"),)
    elif fault == "future_lot":
        lots = (lot(days=1),)
    elif fault == "unknown_lot_account":
        lots = (lot().model_copy(update={"account_id": "unknown"}),)
    elif fault == "duplicate_trade":
        rows = (trade(1), trade(1))
    elif fault == "duplicate_lot":
        lots = (lot(), lot())
    elif fault == "duplicate_account":
        accounts = (*ACCOUNTS, ACCOUNTS[0])
    else:
        rows = (trade(1).model_copy(update={"trade_id": proposal().proposal_id}),)
    for selling in (False, True):
        results = check(
            engine,
            selling=selling,
            state_changes=states,
            proposal_changes=proposed,
            history=rows,
            lots=lots,
            accounts=accounts,
        )
        assert len(results) == 7
        assert all(not row.passed for row in results.values())
        valid_exit = selling and fault not in {"account", "future_snapshot", "future_proposal"}
        assert all(
            row.severity == (Severity.WARN if valid_exit else Severity.BLOCK)
            for row in results.values()
        )


def test_R_02_calendar_provider_fault_is_block_for_entry_warning_for_exit(
    engine: ComplianceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(day: date) -> bool:
        del day
        raise RuntimeError("calendar failed")

    monkeypatch.setattr(engine.calendar, "is_session", broken)
    assert not check(engine)["CMP-05"].passed
    assert check(engine)["CMP-05"].severity == Severity.BLOCK
    assert check(engine, selling=True, lots=(lot(),))["CMP-05"].severity == Severity.WARN


def test_R_02_wash_helper_duplicate_unknown_and_missing_holding_period_fail_typed(
    engine: ComplianceEngine,
) -> None:
    bad = trade(1, side=Side.SELL, loss="100").model_copy(update={"holding_period_start": None})
    for rows in ((trade(1), trade(1)), (trade(1, account="unknown"),), (bad,)):
        with pytest.raises(DataIntegrityError):
            engine.wash_adjustments(rows, ACCOUNTS)
    with pytest.raises(DataIntegrityError):
        engine.wash_adjustments(
            (trade(1, side=Side.SELL, qty=3, loss="0.000001"), trade(2, days=0, qty=1)), ACCOUNTS
        )


def test_CMP_02_loss_sale_requires_holding_metadata_and_no_future_start() -> None:
    with pytest.raises(ValidationError):
        trade(1, side=Side.BUY, loss="100")
    with pytest.raises(ValidationError):
        TradeRecord.model_validate(
            {**trade(1, side=Side.SELL, loss="100").model_dump(), "holding_period_start": None}
        )
    with pytest.raises(ValidationError):
        trade(1).model_copy(
            update={"holding_period_start": NOW + timedelta(days=1)}
        ).model_validate({**trade(1).model_dump(), "holding_period_start": NOW + timedelta(days=1)})


def test_R_02_none_proposal_is_never_success(engine: ComplianceEngine) -> None:
    results = engine.check(cast(object, None), snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)  # type: ignore[arg-type]
    assert len(results) == 7 and all(
        not row.passed and row.severity == Severity.BLOCK for row in results
    )


def test_R_03_compliance_is_deterministic(engine: ComplianceEngine) -> None:
    rows = (trade(1, side=Side.SELL, loss="100"),)
    first = engine.check(proposal(), snapshot(), (), rows, ACCOUNTS, NOW, flags=FLAGS)
    second = engine.check(proposal(), snapshot(), (), rows, ACCOUNTS, NOW, flags=FLAGS)
    assert first == second and len(first) == 7


def test_CMP_02_exhausted_replacement_shares_are_not_reused(engine: ComplianceEngine) -> None:
    rows = engine.wash_adjustments(
        (
            trade(1, side=Side.SELL, days=-2, qty=5, loss="50"),
            trade(2, side=Side.SELL, days=-1, qty=5, loss="100"),
            trade(3, days=0, qty=5),
            trade(4, days=0, qty=1),
        ),
        ACCOUNTS,
    )
    assert [(row.loss_trade_id, row.replacement_trade_id, row.qty) for row in rows] == [
        (uid(1), uid(3), 5),
        (uid(2), uid(4), 1),
    ]


@pytest.mark.parametrize("fault", ["missing_lots", "oversell", "no_position"])
def test_R_09_CMP_02_only_held_exit_with_incomplete_lots_is_warning_only(
    engine: ComplianceEngine, fault: str
) -> None:
    changes: dict[str, object] = {"qty": 2} if fault == "oversell" else {}
    states: dict[str, object] = {"positions": {}} if fault == "no_position" else {}
    lots = () if fault == "missing_lots" else (lot(),)
    results = check(engine, selling=True, lots=lots, state_changes=states, proposal_changes=changes)
    assert not results["CMP-02"].passed
    expected = Severity.WARN if fault == "missing_lots" else Severity.BLOCK
    assert all(row.severity == expected for row in results.values())


def test_CMP_02_fifo_sale_stops_before_unselected_lot(engine: ComplianceEngine) -> None:
    held = Position(qty=2, avg_cost=Decimal("110"), last_price=Decimal("100"))
    results = check(
        engine,
        selling=True,
        lots=(lot(1), lot(2, basis="999", days=-90)),
        state_changes={"positions": {"AAPL": held}},
        history=(trade(3, days=-1, qty=1),),
    )
    assert results["CMP-02"].observed == "10"


@pytest.mark.parametrize("equity", ["2000", "5000", "25000", "100000"])
@pytest.mark.parametrize("cash", ["99.99", "100.00", "100.01"])
def test_CMP_03_CMP_04_cash_cent_boundary_at_each_equity(
    engine: ComplianceEngine, equity: str, cash: str
) -> None:
    rows = check(
        engine,
        state_changes={
            "equity": Decimal(equity),
            "cash": Decimal(cash),
            "settled_cash": Decimal(cash),
        },
    )
    expected = Decimal(cash) >= Decimal(100)
    assert rows["CMP-03"].passed is expected
    assert rows["CMP-04"].passed is expected


@pytest.mark.parametrize("fault", ["config", "calendar", "registry", "restricted", "telegram"])
def test_R_02_compliance_constructor_revalidates_detached_policy(
    engine: ComplianceEngine, calendar: MarketCalendar, fault: str
) -> None:
    policy = Settings()
    registry = engine.registry
    clock_calendar = calendar
    restricted = frozenset[str]()
    if fault == "config":
        policy = policy.model_copy(update={"max_risk_per_trade": Decimal("0.03")})
    elif fault == "calendar":
        clock_calendar = cast(MarketCalendar, None)
    elif fault == "registry":
        registry = cast(InstrumentRegistry, None)
    elif fault == "restricted":
        restricted = frozenset({"UNKNOWN"})
    else:
        policy = policy.model_copy(update={"telegram_allowed_user_ids": ()})
    with pytest.raises(ConfigurationError):
        ComplianceEngine(policy, registry, clock_calendar, restricted_symbols=restricted)


def test_R_02_compliance_constructor_accepts_configured_telegram_and_copies_restrictions(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    blocked = {"AAPL"}
    copied = ComplianceEngine(
        Settings(telegram_allowed_user_ids=(42,)),
        engine.registry,
        calendar,
        restricted_symbols=cast(frozenset[str], blocked),
    )
    blocked.clear()
    assert copied.config.telegram_allowed_user_ids == (42,)
    assert not check(copied)["CMP-07"].passed


def test_CMP_01_CMP_07_normal_failures_do_not_request_halt(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    restricted = ComplianceEngine(
        Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
    )
    assessment = restricted.assess(
        proposal(),
        snapshot(cash=Decimal("99.99"), settled_cash=Decimal("99.99")),
        (),
        (trade(1, side=Side.SELL, loss="100"),),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert assessment.recommended_state == SystemState.RUNNING
    assert {row.rule_id for row in assessment.results if not row.passed} == {
        "CMP-01",
        "CMP-03",
        "CMP-04",
        "CMP-07",
    }
    assert assessment.proposal_id == proposal().proposal_id
    assert assessment.config_hash == restricted.config.config_hash
    assert assessment.snapshot_hash == snapshot_hash(
        snapshot(cash=Decimal("99.99"), settled_cash=Decimal("99.99"))
    )
    assert assessment.evaluated_at == NOW


def test_CMP_06_failed_flags_and_calendar_fault_request_halt(
    engine: ComplianceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = engine.assess(proposal(), snapshot(), (), (), ACCOUNTS, NOW)
    assert blocked.recommended_state == SystemState.HALTED
    assert blocked.snapshot_hash == snapshot_hash(snapshot())

    def fail(day: date) -> bool:
        del day
        raise RuntimeError("untrusted failure detail")

    monkeypatch.setattr(engine.calendar, "is_session", fail)
    failed = engine.assess(proposal(), snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert failed.recommended_state == SystemState.HALTED
    assert failed.results[4].rule_id == "CMP-05" and not failed.results[4].passed
    assert "untrusted failure detail" not in str(failed)


@pytest.mark.parametrize("seconds,expected", [(60, True), (60.000001, False), (-0.000001, False)])
def test_R_05_snapshot_freshness_exact_inclusive_boundary(
    engine: ComplianceEngine, seconds: float, expected: bool
) -> None:
    assessment = engine.assess(
        proposal(),
        snapshot(as_of=NOW - timedelta(seconds=seconds)),
        (),
        (),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert all(row.passed for row in assessment.results) is expected
    assert assessment.recommended_state == (SystemState.RUNNING if expected else SystemState.HALTED)


@pytest.mark.parametrize("offset,expected", [(-1, False), (0, False), (1, True)])
def test_R_05_proposal_expiry_is_exclusive_at_exact_timestamp(
    engine: ComplianceEngine, offset: int, expected: bool
) -> None:
    candidate = proposal(
        created_at=NOW - timedelta(seconds=2), expires_at=NOW + timedelta(seconds=offset)
    )
    results = engine.check(candidate, snapshot(), (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert all(row.passed for row in results) is expected


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "missing_id",
        "subcent",
        "fractional_qty",
        "position",
        "order",
        "lot",
        "trade",
        "account",
        "list",
        "unknown_history",
        "unknown_lot",
        "zero_equity",
    ],
)
def test_R_02_forged_or_unverifiable_inputs_have_seven_failed_rules_and_halt(
    engine: ComplianceEngine, fault: str
) -> None:
    candidate = proposal()
    state = snapshot()
    lots: tuple[TaxLot, ...] = ()
    history: tuple[TradeRecord, ...] = ()
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS
    if fault == "none":
        candidate = cast(TradeProposal, None)
    elif fault == "missing_id":
        candidate = TradeProposal.model_construct()
    elif fault == "subcent":
        candidate = candidate.model_copy(update={"limit_price": Decimal("100.001")})
    elif fault == "fractional_qty":
        candidate = candidate.model_copy(update={"qty": 1.0})
    elif fault == "position":
        state = state.model_copy(update={"positions": {"AAPL": Position.model_construct(qty=1.1)}})
    elif fault == "order":
        state = state.model_copy(update={"open_orders": (OpenOrder.model_construct(qty=1.0),)})
    elif fault == "lot":
        lots = (lot().model_copy(update={"qty": 1.0}),)
    elif fault == "trade":
        history = (trade(1).model_copy(update={"price": 100.0}),)
    elif fault == "account":
        accounts = (ACCOUNTS[0].model_copy(update={"tax_status": "UNKNOWN"}),)
    elif fault == "list":
        history = cast(tuple[TradeRecord, ...], [])
    elif fault == "unknown_history":
        history = (trade(1, symbol="UNKNOWN"),)
    elif fault == "unknown_lot":
        lots = (lot().model_copy(update={"symbol": "UNKNOWN"}),)
    else:
        state = snapshot(equity=Decimal(0))
    assessment = engine.assess(candidate, state, lots, history, accounts, NOW, flags=FLAGS)
    assert [row.rule_id for row in assessment.results] == [f"CMP-{n:02d}" for n in range(1, 8)]
    assert all(not row.passed and row.severity == Severity.BLOCK for row in assessment.results)
    assert assessment.recommended_state == SystemState.HALTED
    if fault in {"position", "order"}:
        assert assessment.snapshot_hash == "0" * 64
    if fault in {"none", "missing_id"}:
        assert assessment.proposal_id is None


def test_R_05_invalid_evaluation_time_is_a_typed_error(engine: ComplianceEngine) -> None:
    with pytest.raises(DataIntegrityError):
        engine.check(
            proposal(), snapshot(), (), (), ACCOUNTS, NOW.replace(tzinfo=None), flags=FLAGS
        )


@pytest.mark.parametrize(
    "fault", ["float_baseline", "blank_account", "duplicate", "future", "unknown", "forged"]
)
def test_CMP_03_cash_reconstruction_invalid_evidence_raises_typed_error(
    engine: ComplianceEngine, fault: str
) -> None:
    initial = Decimal(500)
    account = "paper"
    records: tuple[TradeRecord, ...] = (trade(1),)
    if fault == "float_baseline":
        initial = cast(Decimal, 500.0)
    elif fault == "blank_account":
        account = " "
    elif fault == "duplicate":
        records = (trade(1), trade(1))
    elif fault == "future":
        records = (trade(1, days=1),)
    elif fault == "unknown":
        records = (trade(1, symbol="UNKNOWN"),)
    else:
        records = (trade(1).model_copy(update={"qty": 1.5}),)
    with pytest.raises(DataIntegrityError):
        engine.settled_cash_as_of(initial, records, NOW, account_id=account)


def test_CMP_03_settlement_calendar_fault_is_typed(
    engine: ComplianceEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(day: date, count: int) -> date:
        del day, count
        raise RuntimeError("calendar failure")

    monkeypatch.setattr(engine.calendar, "add_sessions", broken)
    with pytest.raises(DataIntegrityError):
        engine.settlement_date(NOW)


def test_CMP_05_multiple_opening_orders_and_partial_closes_are_counted_conservatively(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    configured = ComplianceEngine(
        Settings(day_trade_regime="LEGACY_PDT"), engine.registry, calendar
    )
    started = NOW - timedelta(hours=2)
    records = tuple(trade(i + 1, ts=started + timedelta(minutes=i), qty=1) for i in range(3))
    records += (trade(5, side=Side.SELL, ts=NOW - timedelta(minutes=1), qty=3),)
    row = check(
        configured,
        history=records,
        state_changes={"account_type": AccountType.MARGIN, "equity": Decimal("24999.99")},
    )["CMP-05"]
    assert not row.passed and row.severity == Severity.BLOCK
    assert "completed=3" in row.observed
    partial = (
        trade(10, ts=started, qty=10),
        trade(11, side=Side.SELL, ts=started + timedelta(minutes=1), qty=1),
        trade(12, side=Side.SELL, ts=started + timedelta(minutes=2), qty=9),
    )
    assert "completed=1" in check(configured, history=partial)["CMP-05"].observed


def test_R_09_pending_sells_reserve_held_inventory(engine: ComplianceEngine) -> None:
    pending = OpenOrder(symbol="AAPL", side=Side.SELL, qty=1, limit_price=Decimal(100))
    assessment = engine.assess(
        proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
        snapshot(open_orders=(pending,)),
        (lot(),),
        (),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert assessment.recommended_state == SystemState.HALTED
    assert all(not row.passed and row.severity == Severity.BLOCK for row in assessment.results)


@given(
    qty=st.integers(min_value=1, max_value=100),
    cash_cents=st.integers(min_value=0, max_value=1_100_000),
)
@settings(max_examples=70, deadline=None)
def test_CMP_03_CMP_04_property_never_pass_when_proposed_cash_exceeds_available(
    calendar: MarketCalendar, qty: int, cash_cents: int
) -> None:
    guarded = ComplianceEngine(Settings(), InstrumentRegistry([instrument()]), calendar)
    cash = Decimal(cash_cents) / 100
    state = snapshot(cash=cash, settled_cash=cash)
    candidate = proposal(qty=qty)
    one = guarded.assess(candidate, state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    two = guarded.assess(candidate, state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert one == two
    for number in (2, 3):
        assert one.results[number].passed is (qty * Decimal(100) <= cash)


def test_R_04_low_decimal_context_does_not_change_rule_decision(engine: ComplianceEngine) -> None:
    state = snapshot(
        cash=Decimal("199.99"),
        settled_cash=Decimal("199.99"),
        open_orders=(OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal(100)),),
    )
    normal = engine.assess(proposal(), state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    with localcontext() as context:
        context.prec = 2
        reduced = engine.assess(proposal(), state, (), (), ACCOUNTS, NOW, flags=FLAGS)
    assert reduced == normal


def test_R_03_compliance_input_hash_binds_all_evidence_and_policy(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    original = engine.input_hash(
        proposal(), snapshot(), (lot(funding=date(2026, 10, 1)),), (trade(1),), ACCOUNTS, FLAGS
    )
    changes = (
        engine.input_hash(
            proposal(qty=2),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1),),
            ACCOUNTS,
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(basis="111", funding=date(2026, 10, 1)),),
            (trade(1),),
            ACCOUNTS,
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1, qty=11),),
            ACCOUNTS,
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1),),
            (ACCOUNTS[0],),
            FLAGS,
        ),
        engine.input_hash(
            proposal(),
            snapshot(),
            (lot(funding=date(2026, 10, 1)),),
            (trade(1),),
            ACCOUNTS,
            FLAGS.model_copy(update={"trading_blocked": True}),
        ),
    )
    assert all(value != original and len(value) == 64 for value in changes)
    restricted = ComplianceEngine(
        Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
    )
    assert (
        restricted.input_hash(
            proposal(), snapshot(), (lot(funding=date(2026, 10, 1)),), (trade(1),), ACCOUNTS, FLAGS
        )
        != original
    )
    different_groups = ComplianceEngine(
        Settings(), InstrumentRegistry([instrument(), instrument("MSFT")]), calendar
    )
    assert (
        different_groups.input_hash(
            proposal(), snapshot(), (lot(funding=date(2026, 10, 1)),), (trade(1),), ACCOUNTS, FLAGS
        )
        != original
    )


def test_R_02_compliance_input_hash_malformed_tuples_raises_typed(engine: ComplianceEngine) -> None:
    with pytest.raises(DataIntegrityError):
        engine.input_hash(proposal(), snapshot(), cast(tuple[TaxLot, ...], []), (), ACCOUNTS, FLAGS)


def test_CMP_03_good_faith_funding_on_today_requires_session_close_confirmation(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    closed = calendar.session_close(date(2026, 10, 2))
    for offset, expected in ((-1, False), (0, True), (1, True)):
        instant = closed + timedelta(microseconds=offset)
        rows = engine.check(
            proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
            snapshot(as_of=instant),
            (lot(funding=date(2026, 10, 2)),),
            (),
            ACCOUNTS,
            instant,
            flags=FLAGS,
        )
        assert rows[2].passed is expected and rows[2].severity == Severity.WARN


def test_CMP_03_invalid_funding_session_requests_halt_with_exit_warnings(
    engine: ComplianceEngine,
) -> None:
    assessed = engine.assess(
        proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
        snapshot(),
        (lot(funding=date(2026, 10, 3)),),
        (),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert not assessed.results[2].passed and assessed.results[2].severity == Severity.WARN
    assert assessed.recommended_state == SystemState.HALTED


def test_CMP_05_equal_execution_times_are_conservatively_ordered(engine: ComplianceEngine) -> None:
    records = (
        trade(1, side=Side.SELL, ts=NOW, qty=3),
        trade(2, ts=NOW, qty=1),
        trade(3, ts=NOW, qty=1),
        trade(4, ts=NOW, qty=1),
    )
    assert "completed=3" in check(engine, history=records)["CMP-05"].observed


def test_CMP_05_unknown_broker_share_allocation_counts_max_plausible_opening_orders(
    engine: ComplianceEngine,
) -> None:
    started = NOW - timedelta(hours=1)
    records = (
        trade(1, qty=10, ts=started),
        trade(2, qty=10, ts=started + timedelta(minutes=1)),
        trade(3, side=Side.SELL, qty=2, ts=started + timedelta(minutes=2)),
    )
    assert "completed=2" in check(engine, history=records)["CMP-05"].observed
    limited = (*records[:2], records[2].model_copy(update={"qty": 1}))
    assert "completed=1" in check(engine, history=limited)["CMP-05"].observed


def test_CMP_02_prior_tacked_lot_preserves_holding_period_and_actual_acquisition(
    engine: ComplianceEngine,
) -> None:
    purchase = trade(1, days=-10, qty=1)
    replacement = trade(2, days=-1, qty=1, account="other")
    held_lot = lot(days=-10, funding=date(2026, 10, 1)).model_copy(
        update={"holding_period_start": NOW - timedelta(days=100), "acquisition_trade_id": uid(1)}
    )
    assessed = engine.assess(
        proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None),
        snapshot(),
        (held_lot,),
        (purchase, replacement),
        ACCOUNTS,
        NOW,
        flags=FLAGS,
    )
    assert assessed.recommended_state == SystemState.RUNNING
    assert assessed.results[1].observed == "10" and assessed.results[1].severity == Severity.WARN


@pytest.mark.parametrize(
    "fault", ["missing", "sell", "account", "symbol", "timestamp", "qty", "aggregate_qty"]
)
def test_CMP_02_tax_lot_acquisition_lineage_requires_matching_original_buy(
    engine: ComplianceEngine, fault: str
) -> None:
    original = trade(1, days=-10, qty=1)
    held_lot = lot(days=-10).model_copy(update={"acquisition_trade_id": uid(1)})
    history: tuple[TradeRecord, ...] = (original,)
    lots: tuple[TaxLot, ...] = (held_lot,)
    if fault == "missing":
        history = ()
    elif fault == "sell":
        history = (original.model_copy(update={"side": Side.SELL}),)
    elif fault == "account":
        history = (original.model_copy(update={"account_id": "other"}),)
    elif fault == "symbol":
        history = (original.model_copy(update={"symbol": "MSFT"}),)
    elif fault == "timestamp":
        history = (original.model_copy(update={"ts": NOW - timedelta(days=11)}),)
    elif fault == "qty":
        lots = (held_lot.model_copy(update={"qty": 2}),)
    else:
        lots = (held_lot, held_lot.model_copy(update={"lot_id": uid(2)}))
    assessed = engine.assess(proposal(), snapshot(), lots, history, ACCOUNTS, NOW, flags=FLAGS)
    assert assessed.recommended_state == SystemState.HALTED
    assert all(not row.passed and row.severity == Severity.BLOCK for row in assessed.results)
