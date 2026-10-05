"""R-02/R-03/R-04/R-09/R-13/CMP-01..07: independent adversarial evidence.

Fixtures are authored here, independently of implementation test helpers. Tax
goldens use the public IRS Publication 550 partial-replacement example.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError, SafetyError
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    AssetClass,
    Instrument,
    Intent,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
)
from backend.risk.compliance import (
    ComplianceEngine,
    ExternalAccount,
    TaxLot,
    TaxStatus,
    TradeRecord,
)
from backend.risk.wash_sales import WashSaleMatcher

NOW = datetime(2026, 10, 2, 16, 0, tzinfo=UTC)
ACCOUNTS = (
    ExternalAccount(account_id="managed", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="other", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="ira", tax_status=TaxStatus.IRA),
    ExternalAccount(account_id="roth", tax_status=TaxStatus.ROTH),
)
FLAGS = AccountFlags(
    trading_blocked=False,
    account_blocked=False,
    trade_suspended_by_user=False,
    status="ACTIVE",
)


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _instant(day: date, *, hour: int = 16) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)


def _registry() -> InstrumentRegistry:
    return InstrumentRegistry(
        (
            Instrument(
                symbol=symbol,
                asset_class=AssetClass.STOCK,
                gics_sector="Information Technology",
                is_leveraged=False,
                is_inverse=False,
                tradable=True,
            )
            for symbol in ("AAPL", "MSFT", "JNJ")
        ),
        identical_groups={"OPERATOR_ATTESTED": ("AAPL", "MSFT")},
    )


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2024, 1, 2), end=date(2027, 12, 31))


@pytest.fixture
def engine(calendar: MarketCalendar) -> ComplianceEngine:
    return ComplianceEngine(Settings(), _registry(), calendar)


def _proposal(**changes: object) -> TradeProposal:
    values: dict[str, object] = {
        "proposal_id": _uuid(900),
        "signal_id": _uuid(901),
        "account_id": "managed",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("10.00"),
        "stop_price": Decimal("9.00"),
        "source": ProposalSource.SIGNAL,
        "created_at": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return TradeProposal.model_validate(values)


def _snapshot(**changes: object) -> PortfolioSnapshot:
    values: dict[str, object] = {
        "account_id": "managed",
        "account_type": AccountType.CASH,
        "as_of": NOW,
        "equity": Decimal("25000"),
        "cash": Decimal("25000"),
        "settled_cash": Decimal("25000"),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("25000"),
        "day_start_equity": Decimal("25000"),
    }
    values.update(changes)
    return PortfolioSnapshot.model_validate(values)


def _trade(
    identifier: int,
    day: date,
    *,
    side: Side = Side.BUY,
    qty: int = 10,
    price: str = "100.00",
    account: str = "managed",
    symbol: str = "AAPL",
    loss: str = "0",
    acquired_at: datetime | None = None,
    acquisition_id: UUID | None = None,
    minute: int = 0,
) -> TradeRecord:
    return TradeRecord(
        trade_id=_uuid(identifier),
        account_id=account,
        symbol=symbol,
        side=side,
        qty=qty,
        price=Decimal(price),
        ts=_instant(day) + timedelta(minutes=minute),
        realized_loss=Decimal(loss),
        holding_period_start=(
            acquired_at
            if acquired_at is not None
            else _instant(day - timedelta(days=100))
            if Decimal(loss) > 0
            else None
        ),
        acquisition_trade_id=acquisition_id,
    )


def _check(
    engine: ComplianceEngine,
    *,
    proposal: TradeProposal | None = None,
    snapshot: PortfolioSnapshot | None = None,
    history: tuple[TradeRecord, ...] = (),
    lots: tuple[TaxLot, ...] = (),
    accounts: tuple[ExternalAccount, ...] = ACCOUNTS,
    flags: AccountFlags | None = FLAGS,
    now: datetime = NOW,
) -> dict[str, RuleResult]:
    results = engine.check(
        proposal or _proposal(),
        snapshot or _snapshot(),
        lots,
        history,
        accounts,
        now,
        flags=flags,
    )
    assert [row.rule_id for row in results] == [f"CMP-0{number}" for number in range(1, 8)]
    return {row.rule_id: row for row in results}


@pytest.mark.parametrize(
    "field,value",
    [
        ("price", Decimal("100.001")),
        ("price", 100.0),
        ("qty", 1.0),
        ("qty", True),
        ("side", "UNRECOGNIZED"),
        ("ts", datetime(2026, 10, 1, 16)),
    ],
)
def test_R_02_R_13_CMP_forged_history_cannot_produce_approval(
    engine: ComplianceEngine, field: str, value: object
) -> None:
    forged = _trade(1, date(2026, 10, 1)).model_copy(update={field: value})
    evidence = _check(engine, history=(forged,))
    assert any(not row.passed and row.severity == Severity.BLOCK for row in evidence.values())


@pytest.mark.parametrize("offset", [0, -1])
def test_R_02_CMP_expiry_exact_endpoint_is_invalid(engine: ComplianceEngine, offset: int) -> None:
    expired = _proposal(
        created_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(seconds=offset)
    )
    evidence = _check(engine, proposal=expired)
    assert all(not row.passed for row in evidence.values())
    assert any(row.severity == Severity.BLOCK for row in evidence.values())


@pytest.mark.parametrize("offset", [61, 3600, 86400])
def test_R_02_CMP_stale_snapshot_is_unverifiable(engine: ComplianceEngine, offset: int) -> None:
    evidence = _check(engine, snapshot=_snapshot(as_of=NOW - timedelta(seconds=offset)))
    assert any(not row.passed and row.severity == Severity.BLOCK for row in evidence.values())


@pytest.mark.parametrize("unknown", ["account", "history_symbol", "lot_symbol", "proposal_symbol"])
def test_R_02_CMP_unknown_identity_is_fail_closed(engine: ComplianceEngine, unknown: str) -> None:
    history = (_trade(1, date(2026, 10, 1), symbol="ZZZZ"),) if unknown == "history_symbol" else ()
    lots = (
        (
            TaxLot(
                lot_id=_uuid(1),
                account_id="managed",
                symbol="ZZZZ",
                qty=1,
                acquired_at=NOW - timedelta(days=5),
                cost_basis=Decimal("100"),
            ),
        )
        if unknown == "lot_symbol"
        else ()
    )
    results = _check(
        engine,
        proposal=_proposal(symbol="ZZZZ") if unknown == "proposal_symbol" else None,
        history=history,
        lots=lots,
        accounts=() if unknown == "account" else ACCOUNTS,
    )
    assert any(not row.passed and row.severity == Severity.BLOCK for row in results.values())


def test_R_02_CMP_forged_nested_holdings_and_settings_are_revalidated(
    engine: ComplianceEngine, calendar: MarketCalendar
) -> None:
    forged_position = Position(qty=1, avg_cost=Decimal("100"), last_price=Decimal("100"))
    forged = _snapshot().model_copy(
        update={"positions": {"AAPL": forged_position.model_copy(update={"qty": 1.5})}}
    )
    assert any(not row.passed for row in _check(engine, snapshot=forged).values())
    policy = Settings().model_copy(update={"max_single_stock_weight": Decimal("0.99")})
    with pytest.raises(SafetyError):
        ComplianceEngine(policy, engine.registry, calendar)


@pytest.mark.parametrize("unknown_symbol", [False, True])
def test_R_09_CMP_valid_held_exit_only_warns_unverifiable_tax_context(
    engine: ComplianceEngine, unknown_symbol: bool
) -> None:
    symbol = "ZZZZ" if unknown_symbol else "AAPL"
    proposal = _proposal(symbol=symbol, side=Side.SELL, intent=Intent.EXIT, stop_price=None, qty=10)
    snapshot = _snapshot(
        positions={symbol: Position(qty=10, avg_cost=Decimal("100"), last_price=Decimal("100"))}
    )
    results = _check(engine, proposal=proposal, snapshot=snapshot, accounts=(), flags=None)
    assert all(row.severity == Severity.WARN for row in results.values())
    assert any(not row.passed for row in results.values())


def test_R_09_CMP_pending_sell_reservation_prevents_oversized_exit(
    engine: ComplianceEngine,
) -> None:
    proposal = _proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None, qty=10)
    snapshot = _snapshot(
        positions={"AAPL": Position(qty=10, avg_cost=Decimal("100"), last_price=Decimal("100"))},
        open_orders=(OpenOrder(symbol="AAPL", side=Side.SELL, qty=1, limit_price=Decimal("100")),),
    )
    results = _check(engine, proposal=proposal, snapshot=snapshot)
    assert any(not row.passed and row.severity == Severity.BLOCK for row in results.values())


@pytest.mark.parametrize("equity", ["2000", "5000", "25000", "100000"])
@pytest.mark.parametrize("cash,passed", [("100", True), ("99.99", False)])
def test_CMP_03_CMP_04_pending_cash_exact_cent_boundaries(
    engine: ComplianceEngine, equity: str, cash: str, passed: bool
) -> None:
    snapshot = _snapshot(
        equity=Decimal(equity),
        cash=Decimal(cash),
        settled_cash=Decimal(cash),
        open_orders=(OpenOrder(symbol="MSFT", side=Side.BUY, qty=3, limit_price=Decimal("30")),),
    )
    evidence = _check(engine, snapshot=snapshot)
    assert evidence["CMP-03"].passed is passed
    assert evidence["CMP-04"].passed is passed


@pytest.mark.parametrize(
    "trade_day,settled_day,closing_hour",
    [
        (date(2026, 3, 6), date(2026, 3, 9), 20),
        (date(2026, 11, 25), date(2026, 11, 27), 18),
        (date(2026, 11, 27), date(2026, 11, 30), 21),
    ],
)
def test_CMP_03_T1_DST_holiday_early_close_exact_credit_time(
    engine: ComplianceEngine, trade_day: date, settled_day: date, closing_hour: int
) -> None:
    sale = _trade(1, trade_day, side=Side.SELL, qty=1)
    close = _instant(settled_day, hour=closing_hour)
    assert engine.settlement_date(sale.ts) == settled_day
    assert engine.settled_cash_as_of(
        Decimal("10"), (sale,), close - timedelta(microseconds=1), account_id="managed"
    ) == Decimal("10")
    assert engine.settled_cash_as_of(
        Decimal("10"), (sale,), close, account_id="managed"
    ) == Decimal("110")


def test_CMP_02_IRS_partial_replacement_golden(engine: ComplianceEngine) -> None:
    original = _trade(1, date(2024, 9, 20), qty=100, price="50")
    first = _trade(2, date(2024, 12, 13), qty=50, price="55")
    second = _trade(3, date(2024, 12, 20), qty=25, price="45")
    sale = _trade(
        4,
        date(2025, 1, 3),
        side=Side.SELL,
        qty=100,
        price="40",
        loss="1000",
        acquired_at=original.ts,
        acquisition_id=original.trade_id,
    )
    matcher = WashSaleMatcher(engine.registry)
    matches = matcher.adjustments((original, first, second, sale), ACCOUNTS)
    assert [(row.qty, row.disallowed_loss, row.adjusted_basis) for row in matches] == [
        (50, Decimal("500"), Decimal("3250")),
        (25, Decimal("250"), Decimal("1375")),
    ]
    exported = matcher.form_8949_rows(matches)
    assert all(row.code == "W" and row.adjustment > 0 for row in exported)
    assert sum((row.proceeds for row in exported), Decimal(0)) == Decimal("3000")
    assert sum((row.cost_basis for row in exported), Decimal(0)) == Decimal("3750")
    assert sum((row.adjustment for row in exported), Decimal(0)) == Decimal("750")
    assert sum((row.gain_or_loss for row in exported), Decimal(0)) == 0
    # 105 New York calendar days tack to the December purchase. August is
    # daylight time, so its 11:00 local effective start is 15:00 UTC.
    assert matches[0].holding_period_start == datetime(2024, 8, 30, 15, 0, tzinfo=UTC)


def test_CMP_02_original_shares_sold_cannot_replace_themselves(engine: ComplianceEngine) -> None:
    buy = _trade(1, date(2026, 9, 20), qty=10)
    sale = _trade(
        2,
        date(2026, 9, 21),
        side=Side.SELL,
        qty=10,
        price="90",
        loss="100",
        acquired_at=buy.ts,
        acquisition_id=buy.trade_id,
    )
    assert WashSaleMatcher(engine.registry).adjustments((buy, sale), ACCOUNTS) == ()


def test_CMP_02_Form_8949_actual_acquisition_is_separate_from_prior_tacking(
    engine: ComplianceEngine,
) -> None:
    original = _trade(1, date(2026, 9, 20), qty=10)
    sale = _trade(
        2,
        date(2026, 9, 21),
        side=Side.SELL,
        qty=10,
        price="90",
        loss="100",
        acquired_at=_instant(date(2026, 1, 1)),
        acquisition_id=original.trade_id,
    )
    replacement = _trade(3, date(2026, 9, 22), qty=10, account="other")
    matcher = WashSaleMatcher(engine.registry)
    matches = matcher.adjustments((original, sale, replacement), ACCOUNTS)
    assert len(matches) == 1
    assert matches[0].holding_period_start == datetime(2026, 1, 2, 17, 0, tzinfo=UTC)
    assert matches[0].acquired_date == date(2026, 9, 20)
    assert matcher.form_8949_rows(matches)[0].date_acquired == date(2026, 9, 20)


def test_R_02_CMP_02_equal_timestamps_do_not_make_uuid_order_tax_evidence(
    engine: ComplianceEngine,
) -> None:
    buy = _trade(20, date(2026, 9, 20), qty=10)
    sale = _trade(
        1,
        date(2026, 9, 20),
        side=Side.SELL,
        qty=10,
        price="90",
        loss="100",
        acquired_at=buy.ts,
        acquisition_id=buy.trade_id,
    )
    assert WashSaleMatcher(engine.registry).adjustments((sale, buy), ACCOUNTS) == ()


def test_R_02_CMP_02_equal_timestamps_without_origin_fail_closed(
    engine: ComplianceEngine,
) -> None:
    buy = _trade(20, date(2026, 9, 20), qty=10)
    sale = _trade(1, date(2026, 9, 20), side=Side.SELL, qty=10, price="110")
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(engine.registry).adjustments((sale, buy), ACCOUNTS)


def test_CMP_02_disposed_cross_account_replacement_has_no_capacity(
    engine: ComplianceEngine,
) -> None:
    buy = _trade(1, date(2026, 9, 5), qty=10, symbol="MSFT", account="other")
    sold = _trade(
        2,
        date(2026, 9, 6),
        qty=10,
        symbol="MSFT",
        account="other",
        side=Side.SELL,
        price="110",
        acquired_at=buy.ts,
        acquisition_id=buy.trade_id,
    )
    loss = _trade(3, date(2026, 9, 20), side=Side.SELL, loss="100")
    assert WashSaleMatcher(engine.registry).adjustments((buy, sold, loss), ACCOUNTS) == ()


def test_CMP_01_CMP_02_overlapping_losses_share_capacity_and_exact_money(
    engine: ComplianceEngine,
) -> None:
    first = _trade(1, date(2026, 9, 10), side=Side.SELL, qty=100, loss="200")
    second = _trade(2, date(2026, 9, 11), side=Side.SELL, qty=100, loss="200")
    replacement = _trade(3, date(2026, 9, 12), qty=150, price="90", account="other")
    matcher = WashSaleMatcher(engine.registry)
    matches = matcher.adjustments((first, second, replacement), ACCOUNTS)
    assert [(row.qty, row.disallowed_loss) for row in matches] == [
        (100, Decimal("200")),
        (50, Decimal("100")),
    ]
    assert sum(row.qty for row in matches) == replacement.qty
    with localcontext() as context:
        context.prec = 2
        assert matcher.adjustments((replacement, second, first), ACCOUNTS) == matches


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_CMP_01_IRA_disallowed_loss_never_increases_retirement_basis(
    engine: ComplianceEngine, account: str
) -> None:
    loss = _trade(1, date(2026, 9, 10), side=Side.SELL, loss="100")
    replacement = _trade(2, date(2026, 9, 11), qty=5, account=account)
    matches = WashSaleMatcher(engine.registry).adjustments((loss, replacement), ACCOUNTS)
    assert len(matches) == 1
    assert matches[0].disallowed_loss == Decimal("50")
    assert matches[0].permanent_loss
    assert matches[0].adjusted_basis is None


@settings(max_examples=50, deadline=None)
@given(loss_shares=st.integers(min_value=2, max_value=200), replacement_shares=st.integers(1, 200))
def test_CMP_01_CMP_02_partial_share_allocation_never_disallows_unmatched_loss(
    loss_shares: int, replacement_shares: int
) -> None:
    loss = _trade(1, date(2026, 9, 10), side=Side.SELL, qty=loss_shares, loss=str(loss_shares))
    replacement = _trade(2, date(2026, 9, 11), qty=replacement_shares, account="other")
    matches = WashSaleMatcher(_registry()).adjustments((loss, replacement), ACCOUNTS)
    expected = min(loss_shares, replacement_shares)
    assert sum(row.qty for row in matches) == expected
    assert sum((row.disallowed_loss for row in matches), Decimal(0)) == Decimal(expected)


def test_CMP_02_forged_wash_models_cannot_bypass_public_matcher(engine: ComplianceEngine) -> None:
    forged = _trade(1, date(2026, 9, 10), side=Side.SELL, loss="100").model_copy(
        update={"price": Decimal("100.001")}
    )
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(engine.registry).adjustments((forged,), ACCOUNTS)


@pytest.mark.parametrize("equity,blocked", [("24999.99", True), ("25000", False)])
def test_CMP_05_legacy_independent_opening_orders_are_counted_before_single_close(
    calendar: MarketCalendar, equity: str, blocked: bool
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history = (
        _trade(1, date(2026, 10, 1), qty=1, minute=0),
        _trade(2, date(2026, 10, 1), qty=1, minute=1),
        _trade(3, date(2026, 10, 1), qty=1, minute=2),
        _trade(4, date(2026, 10, 1), side=Side.SELL, qty=3, price="110", minute=3),
        _trade(5, NOW.date(), side=Side.SELL, qty=1, minute=-1),
    )
    result = _check(
        engine,
        snapshot=_snapshot(account_type=AccountType.MARGIN, equity=Decimal(equity)),
        history=history,
    )["CMP-05"]
    assert not result.passed
    assert result.severity == (Severity.BLOCK if blocked else Severity.WARN)
    assert "completed=3" in result.observed


def test_CMP_05_one_opening_order_is_counted_once_across_partial_exits(
    calendar: MarketCalendar,
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history = (
        _trade(1, date(2026, 10, 1), qty=3),
        _trade(2, date(2026, 10, 1), side=Side.SELL, qty=1, price="110", minute=1),
        _trade(3, date(2026, 10, 1), side=Side.SELL, qty=1, price="110", minute=2),
        _trade(4, date(2026, 10, 1), side=Side.SELL, qty=1, price="110", minute=3),
        _trade(5, NOW.date(), side=Side.SELL, qty=1, minute=-1),
    )
    result = _check(engine, snapshot=_snapshot(account_type=AccountType.MARGIN), history=history)[
        "CMP-05"
    ]
    assert not result.passed and result.severity == Severity.WARN
    assert "completed=1" in result.observed


def test_CMP_05_partial_close_uses_conservative_possible_distinct_openings(
    calendar: MarketCalendar,
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history = (
        _trade(1, date(2026, 10, 1), qty=10),
        _trade(2, date(2026, 10, 1), qty=10, minute=1),
        _trade(3, date(2026, 10, 1), side=Side.SELL, qty=2, price="110", minute=2),
        _trade(4, NOW.date(), side=Side.SELL, qty=1, minute=-1),
    )
    result = _check(
        engine,
        snapshot=_snapshot(account_type=AccountType.MARGIN),
        history=history,
    )["CMP-05"]
    assert not result.passed and result.severity == Severity.WARN
    assert "completed=2" in result.observed


def test_CMP_05_five_sessions_include_oldest_session_but_exclude_sixth(
    calendar: MarketCalendar,
) -> None:
    engine = ComplianceEngine(Settings(day_trade_regime="LEGACY_PDT"), _registry(), calendar)
    history: list[TradeRecord] = []
    for index, day in enumerate(
        (date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30))
    ):
        history.append(_trade(index * 2 + 1, day, qty=1))
        history.append(_trade(index * 2 + 2, day, side=Side.SELL, qty=1, price="110", minute=1))
    history.append(_trade(100, NOW.date(), side=Side.SELL, qty=1, minute=-1))
    result = _check(
        engine,
        snapshot=_snapshot(account_type=AccountType.MARGIN, equity=Decimal("5000")),
        history=tuple(history),
    )["CMP-05"]
    assert not result.passed and result.severity == Severity.BLOCK
    assert "completed=3" in result.observed


def test_R_03_CMP_repeated_evaluation_does_not_mutate_input(engine: ComplianceEngine) -> None:
    proposal = _proposal()
    snapshot = _snapshot()
    before = snapshot.model_dump_json()
    first = _check(engine, proposal=proposal, snapshot=snapshot)
    second = _check(engine, proposal=proposal, snapshot=snapshot)
    assert first == second
    assert snapshot.model_dump_json() == before
    assert proposal.qty == 1


@pytest.mark.parametrize(
    "changed", ["qty", "limit", "history", "account_tax", "flags", "restriction"]
)
def test_R_03_CMP_full_input_hash_binds_proposal_tax_history_flags_and_policy(
    engine: ComplianceEngine, calendar: MarketCalendar, changed: str
) -> None:
    proposal = _proposal()
    snapshot = _snapshot()
    baseline = engine.assess(proposal, snapshot, (), (), ACCOUNTS, NOW, flags=FLAGS)
    history = (
        (_trade(1, date(2026, 9, 20), side=Side.SELL, loss="100"),) if changed == "history" else ()
    )
    accounts = (
        (ExternalAccount(account_id="managed", tax_status=TaxStatus.IRA), *ACCOUNTS[1:])
        if changed == "account_tax"
        else ACCOUNTS
    )
    if changed == "qty":
        proposal = _proposal(qty=2)
    elif changed == "limit":
        proposal = _proposal(limit_price=Decimal("11"))
    active_engine = (
        ComplianceEngine(
            Settings(), engine.registry, calendar, restricted_symbols=frozenset({"AAPL"})
        )
        if changed == "restriction"
        else engine
    )
    flags = FLAGS.model_copy(update={"trading_blocked": True}) if changed == "flags" else FLAGS
    evidence = active_engine.assess(proposal, snapshot, (), history, accounts, NOW, flags=flags)
    assert evidence.proposal_id == baseline.proposal_id
    assert evidence.config_hash == baseline.config_hash
    assert evidence.snapshot_hash == baseline.snapshot_hash
    assert evidence.evaluated_at == baseline.evaluated_at
    assert evidence.input_hash != baseline.input_hash
