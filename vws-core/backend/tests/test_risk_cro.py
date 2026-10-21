"""CRO-01..13/R-01..05/R-09/R-13: exact boundaries, exits and sizing properties."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import (
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from typing import Any, cast
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState
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
    OpenOrder,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    ProtectiveStop,
    RuleResult,
    Severity,
    Side,
    TradeProposal,
)
from backend.risk.risk_cro import ChiefRiskOfficer


@pytest.fixture(autouse=True)
def advisory_work_budget(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy sizing examples must also yield rather than hang on a broken policy."""
    if not request.node.name.startswith("test_CRO_03_to_08_max_qty_is_largest_whole_share"):
        return
    original = ChiefRiskOfficer.evaluate
    calls = 0

    def evaluate(officer: ChiefRiskOfficer, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls > 64:
            raise AssertionError("Advisory sizing exhausted the protective-work budget")
        return original(officer, *args, **kwargs)

    monkeypatch.setattr(ChiefRiskOfficer, "evaluate", evaluate)


@pytest.mark.parametrize(
    "day,expected", [(2, False), (3, False), (5, False), (6, False), (7, True), (10, True)]
)
def test_CRO_13_confirmed_event_audit_keeps_inclusive_session_boundaries(
    clock: FrozenClock, risk_calendar: MarketCalendar, day: int, expected: bool
) -> None:
    clock = FrozenClock(datetime(2026, 10, 2, 16, tzinfo=UTC))
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", earnings_blackout_sessions=2),
        _registry(),
        risk_calendar,
    )
    event = date(2026, 10, day)
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock, next_earnings_date=event),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    row = verdict.results[12]
    assert (row.rule_id, row.passed, row.severity, row.observed, row.limit, row.message) == (
        "CRO-13",
        expected,
        Severity.BLOCK,
        event.isoformat(),
        "outside 2 XNYS sessions",
        "known earnings within inclusive blackout or unresolved past date blocks",
    )
    assert verdict.decision == (Decision.APPROVED if expected else Decision.VETOED)


@pytest.mark.parametrize(
    "start,end,blackout,overlap",
    [
        (2, 5, 0, True),
        (5, 8, 0, False),
        (5, 8, 2, True),
        (3, 5, 2, True),
        (10, 12, 2, False),
        (1, 1, 2, False),
    ],
)
def test_CRO_13_estimated_window_retains_exact_warning_and_never_claims_known_clearance(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    start: int,
    end: int,
    blackout: int,
    overlap: bool,
) -> None:
    from backend.domain.models import EarningsInfo, EarningsStatus

    clock = FrozenClock(datetime(2026, 10, 2, 16, tzinfo=UTC))
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", earnings_blackout_sessions=blackout),
        _registry(),
        risk_calendar,
    )
    evidence = EarningsInfo(
        status=EarningsStatus.ESTIMATED,
        source="offline filing interval",
        window_start=date(2026, 10, start),
        window_end=date(2026, 10, end),
    )
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock, earnings=evidence),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    row = verdict.results[12]
    message = (
        "estimated earnings window overlaps the blackout; operator review required"
        if overlap
        else "earnings window is estimated; next confirmed date remains unavailable"
    )
    assert (row.rule_id, row.passed, row.severity, row.observed, row.limit, row.message) == (
        "CRO-13",
        False,
        Severity.WARN,
        f"estimated 2026-10-{start:02d}..2026-10-{end:02d}",
        "verified earnings date",
        message,
    )
    assert verdict.decision == Decision.APPROVED


def test_CRO_audit_contains_the_hand_calculated_one_share_paper_example(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    """$10k equity, one $100 share, $95 stop: $5 risk + $0.20 slippage."""
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.APPROVED
    assert verdict.recommended_state == SystemState.RUNNING
    assert [
        (r.rule_id, r.passed, r.severity.value, r.observed, r.limit, r.message)
        for r in verdict.results
    ] == [
        (
            "CRO-01",
            True,
            "BLOCK",
            "RUNNING",
            "RUNNING, or permitted reduction/exit",
            "system operating state permits proposal",
        ),
        (
            "CRO-02",
            True,
            "BLOCK",
            "AAPL",
            "valid long-only allowlisted instrument",
            "entry/add intent, stop, expiry, account, inventory and market are verified",
        ),
        ("CRO-03", True, "BLOCK", "100.00", "1000.00", "post-trade single-name value fits cap"),
        (
            "CRO-04",
            True,
            "BLOCK",
            "5.20000",
            "100.00",
            "reserved stop risk plus slippage fits budget",
        ),
        (
            "CRO-05",
            True,
            "BLOCK",
            "sectors=[('Information Technology', Decimal('100.00'))]; themes=[]",
            "configured sector/theme fractions",
            "sector look-through and theme caps fit",
        ),
        (
            "CRO-06",
            True,
            "BLOCK",
            "gross=100.00; positions=1; cash=9900.00",
            "gross<=10000.00; positions<=15; cash>=500.00",
            "gross exposure, number of names, and cash buffer all fit",
        ),
        (
            "CRO-07",
            True,
            "BLOCK",
            "price=100.00; reference=100.00; age=0:00:00",
            "collar=0.03; min=5.00; age<=60s",
            "limit price and calendar-aware quote freshness are sane",
        ),
        ("CRO-08", True, "BLOCK", "100.00", "10000.00", "notional fits average-volume cap"),
        ("CRO-09", True, "BLOCK", "0", "0.08", "persisted drawdown below reduce-only tier"),
        (
            "CRO-10",
            True,
            "BLOCK",
            "0",
            "0.02",
            "loss below session entry limit; baseline rolls at next XNYS open",
        ),
        (
            "CRO-11",
            True,
            "BLOCK",
            "clear",
            "outside all applicable UTC blackouts",
            "scheduled blackout includes both endpoint instants",
        ),
        (
            "CRO-12",
            True,
            "BLOCK",
            "OK",
            "OK",
            "checking buffer and funding reading must be available",
        ),
        (
            "CRO-13",
            False,
            "WARN",
            "unknown",
            "verified earnings date",
            "earnings unavailable; operator must review unknown event risk",
        ),
        (
            "CRO-14",
            True,
            "BLOCK",
            "5.00",
            "400.00",
            "total held, pending and new stop risk fits the portfolio cap",
        ),
    ]


@pytest.mark.parametrize(
    "fault", ["market_missing", "bad_daily_block", "proposal_qty", "snapshot_equity"]
)
def test_CRO_invalid_entry_emits_fourteen_exact_fail_closed_audit_rows(
    clock: FrozenClock, risk_calendar: MarketCalendar, fault: str
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    proposal, snapshot, market = _proposal(clock), _snapshot(clock), _market(clock)
    if fault == "proposal_qty":
        proposal = proposal.model_copy(update={"qty": 0})
    if fault == "snapshot_equity":
        snapshot = snapshot.model_copy(update={"equity": "not-money"})
    verdict = cro.evaluate(
        proposal,
        snapshot,
        None if fault == "market_missing" else market,
        SystemState.RUNNING,
        clock.now(),
        daily_loss_blocked=cast(Any, 1 if fault == "bad_daily_block" else False),
    )
    assert verdict.decision == Decision.VETOED and verdict.recommended_state == SystemState.HALTED
    assert verdict.snapshot_hash == "0" * 64
    assert verdict.evaluated_at == clock.now()
    assert verdict.proposal_id == proposal.proposal_id
    error = (
        "DataIntegrityError"
        if fault in {"market_missing", "bad_daily_block"}
        else "ValidationError"
    )
    assert [
        (row.rule_id, row.passed, row.severity, row.observed, row.limit, row.message)
        for row in verdict.results
    ] == [
        (
            f"CRO-{i:02d}",
            False,
            Severity.BLOCK,
            error,
            "verifiable inputs",
            "input or policy evaluation failed closed",
        )
        for i in range(1, 15)
    ]


@pytest.mark.parametrize("fault", ["registry", "calendar", "policy"])
def test_CRO_bad_policy_is_an_exact_typed_configuration_refusal(
    risk_calendar: MarketCalendar, fault: str
) -> None:
    settings = Settings(broker_account_type="CASH")
    if fault == "policy":
        settings = settings.model_copy(update={"max_open_positions": 0})
    with pytest.raises(ConfigurationError) as caught:
        ChiefRiskOfficer(
            settings,
            cast(Any, None) if fault == "registry" else _registry(),
            cast(Any, None) if fault == "calendar" else risk_calendar,
        )
    assert type(caught.value) is ConfigurationError
    assert str(caught.value) == "CRO-01..13: cannot verify immutable risk policy"


@pytest.mark.parametrize(
    "requested,cash,expected", [(1, "10000", 1), (2, "10000", 2), (10000, "10000", 10), (1, "0", 0)]
)
def test_CRO_03_advisory_size_returns_with_bounded_risk_work(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    requested: int,
    cash: str,
    expected: int,
) -> None:
    """One advisory request cannot monopolize the broker's protective work loop."""
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    evaluate = cro.evaluate
    calls = 0

    def bounded(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls > 64:
            raise AssertionError("Advisory sizing exhausted the protective-work budget")
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(cro, "evaluate", bounded)
    snapshot = _snapshot(clock, cash=Decimal(cash))
    assert (
        cro.max_allowed_qty(_proposal(clock, qty=requested), snapshot, _market(clock), clock.now())
        == expected
    )
    assert calls <= 64


@pytest.fixture(scope="module")
def risk_calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def _instrument(symbol: str, **changes: Any) -> Instrument:
    fields: dict[str, Any] = {
        "symbol": symbol,
        "asset_class": AssetClass.STOCK,
        "gics_sector": "Information Technology",
        "themes": (),
        "is_leveraged": False,
        "is_inverse": False,
        "tradable": True,
    }
    fields.update(changes)
    return Instrument(**fields)


def _registry(*additional: Instrument, **kwargs: Any) -> InstrumentRegistry:
    return InstrumentRegistry(
        (_instrument("AAPL"), _instrument("MSFT"), _instrument("IBM"), *additional), **kwargs
    )


def _proposal(clock: FrozenClock, **changes: Any) -> TradeProposal:
    fields: dict[str, Any] = {
        "proposal_id": UUID(int=1),
        "signal_id": UUID(int=2),
        "account_id": "paper-account",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("100"),
        "stop_price": Decimal("95"),
        "source": ProposalSource.SIGNAL,
        "created_at": clock.now(),
        "expires_at": clock.now() + timedelta(days=1),
    }
    fields.update(changes)
    return TradeProposal(**fields)


def _snapshot(clock: FrozenClock, **changes: Any) -> PortfolioSnapshot:
    fields: dict[str, Any] = {
        "account_id": "paper-account",
        "account_type": AccountType.CASH,
        "as_of": clock.now(),
        "equity": Decimal("10000"),
        "cash": Decimal("10000"),
        "settled_cash": Decimal("10000"),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("10000"),
        "day_start_equity": Decimal("10000"),
    }
    fields.update(changes)
    return PortfolioSnapshot(**fields)


def _market(clock: FrozenClock, **changes: Any) -> MarketContext:
    fields: dict[str, Any] = {
        "last_price": Decimal("100"),
        "last_price_ts": clock.now(),
        "adv20_usd": Decimal("1000000"),
        "status": MarketStatus.OK,
    }
    fields.update(changes)
    return MarketContext(**fields)


def _capital(status: CapitalStatus = CapitalStatus.OK) -> DeployableCapital:
    return DeployableCapital(
        checking_used=Decimal("5000"),
        buffer=Decimal("1500"),
        reserved=Decimal("100"),
        deployable=Decimal("3400") if status == CapitalStatus.OK else Decimal(0),
        status=status,
    )


def _position(qty: int, price: Decimal = Decimal("100")) -> Position:
    return Position(qty=qty, avg_cost=price, last_price=price)


def _rule(
    cro: ChiefRiskOfficer,
    clock: FrozenClock,
    rule_id: str,
    proposal: TradeProposal | None = None,
    snapshot: PortfolioSnapshot | None = None,
    market: MarketContext | None = None,
    **kwargs: Any,
) -> RuleResult:
    verdict = cro.evaluate(
        proposal or _proposal(clock),
        snapshot or _snapshot(clock),
        market or _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
        **kwargs,
    )
    assert len(verdict.results) == 14
    return next(result for result in verdict.results if result.rule_id == rule_id)


def test_CRO_01_to_12_R_03_approval_is_complete_exact_and_deterministic(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    proposal, snapshot, market = _proposal(clock), _snapshot(clock), _market(clock)
    first = cro.evaluate(
        proposal, snapshot, market, SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    assert first.decision == Decision.APPROVED
    assert first == cro.evaluate(
        proposal, snapshot, market, SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    assert [rule.rule_id for rule in first.results] == [
        f"CRO-{number:02d}" for number in range(1, 15)
    ]
    assert all(rule.passed for rule in first.results if rule.severity == Severity.BLOCK)
    assert first.results[12].severity == Severity.WARN
    assert not first.results[12].passed
    assert first.results[13].passed and first.results[13].severity == Severity.BLOCK


@pytest.mark.parametrize(
    "state,source,intent,allowed",
    [
        (SystemState.RUNNING, ProposalSource.SIGNAL, Intent.ENTRY, True),
        (SystemState.REDUCE_ONLY, ProposalSource.SIGNAL, Intent.ENTRY, False),
        (SystemState.HALTED, ProposalSource.SIGNAL, Intent.ENTRY, False),
        (SystemState.REDUCE_ONLY, ProposalSource.SIGNAL, Intent.EXIT, True),
        (SystemState.HALTED, ProposalSource.SIGNAL, Intent.EXIT, False),
        (SystemState.HALTED, ProposalSource.MANUAL, Intent.REDUCE, True),
        (SystemState.HALTED, ProposalSource.MANUAL, Intent.EXIT, True),
    ],
)
def test_CRO_01_R_09_state_gate_and_manual_escape(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    state: SystemState,
    source: ProposalSource,
    intent: Intent,
    allowed: bool,
) -> None:
    changes: dict[str, Any] = {"intent": intent, "source": source}
    if intent in {Intent.EXIT, Intent.REDUCE}:
        changes.update(side=Side.SELL, stop_price=None)
    proposal = _proposal(clock, **changes)
    snapshot = _snapshot(
        clock, positions={"AAPL": _position(1)} if intent in {Intent.EXIT, Intent.REDUCE} else {}
    )
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    verdict = cro.evaluate(
        proposal, snapshot, _market(clock), state, clock.now(), deployable=_capital()
    )
    assert (verdict.decision == Decision.APPROVED) == allowed
    if not allowed:
        assert [rule.rule_id for rule in verdict.results] == ["CRO-01"]


def test_CRO_02_R_09_exit_ignores_missing_market_unknown_instrument_and_all_other_rules(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    proposal = _proposal(
        clock,
        symbol="UNKNOWN",
        side=Side.SELL,
        intent=Intent.EXIT,
        stop_price=None,
        limit_price=Decimal("1"),
    )
    snapshot = _snapshot(
        clock,
        equity=Decimal("1"),
        cash=Decimal(0),
        positions={"UNKNOWN": _position(1)},
        high_water_mark=Decimal("100000"),
        day_start_equity=Decimal("100000"),
    )
    verdict = cro.evaluate(proposal, snapshot, None, SystemState.RUNNING, clock.now())
    assert verdict.decision == Decision.APPROVED
    assert len(verdict.results) == 2


def test_CRO_02_R_02_entry_missing_market_vetoes(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        None,
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert len(verdict.results) == 14


@pytest.mark.parametrize(
    "qty,reserved,held,passed",
    [(2, 0, 2, True), (3, 0, 2, False), (1, 1, 2, True), (2, 1, 2, False), (1, 0, 0, False)],
)
def test_CRO_02_R_01_held_share_boundary_and_pending_sell_reservations(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    qty: int,
    reserved: int,
    held: int,
    passed: bool,
) -> None:
    pending = (
        ()
        if reserved == 0
        else (OpenOrder(symbol="AAPL", side=Side.SELL, qty=reserved, limit_price=Decimal("100")),)
    )
    snapshot = _snapshot(
        clock, positions={"AAPL": _position(held)} if held else {}, open_orders=pending
    )
    proposal = _proposal(clock, side=Side.SELL, intent=Intent.REDUCE, stop_price=None, qty=qty)
    verdict = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    ).evaluate(proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now())
    assert verdict.results[1].passed == passed


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "other"},
        {"created_at": datetime(2099, 1, 1, tzinfo=UTC)},
        {"qty": True},
        {"qty": 0},
        {"limit_price": Decimal("NaN")},
        {"limit_price": Decimal(0)},
        {"stop_price": None},
        {"stop_price": Decimal("100")},
        {"side": Side.SELL},
    ],
)
def test_CRO_02_R_02_defensive_shape_veto_even_if_model_validation_bypassed(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    changes: dict[str, Any],
) -> None:
    proposal = _proposal(clock).model_copy(update=changes)
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    verdict = cro.evaluate(
        proposal,
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert not next(rule for rule in verdict.results if rule.rule_id == "CRO-02").passed


@pytest.mark.parametrize(
    "metadata", [{"tradable": False}, {"is_leveraged": True}, {"is_inverse": True}]
)
def test_CRO_02_R_01_instrument_safety(
    clock: FrozenClock, risk_calendar: MarketCalendar, metadata: dict[str, Any]
) -> None:
    registry = InstrumentRegistry((_instrument("AAPL", **metadata),))
    assert not _rule(
        ChiefRiskOfficer(
            Settings(
                broker_account_type="CASH",
            ),
            registry,
            risk_calendar,
        ),
        clock,
        "CRO-02",
    ).passed


def test_CRO_02_R_02_unknown_suspect_future_snapshot_nonpositive_equity(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    for proposal, snapshot, market in (
        (_proposal(clock, symbol="UNKNOWN"), _snapshot(clock), _market(clock)),
        (_proposal(clock), _snapshot(clock), _market(clock, status=MarketStatus.SUSPECT)),
        (
            _proposal(clock),
            _snapshot(clock, as_of=clock.now() + timedelta(seconds=1)),
            _market(clock),
        ),
        (_proposal(clock), _snapshot(clock, equity=Decimal(0)), _market(clock)),
        (_proposal(clock), _snapshot(clock, equity=Decimal("-1")), _market(clock)),
    ):
        verdict = cro.evaluate(
            proposal, snapshot, market, SystemState.RUNNING, clock.now(), deployable=_capital()
        )
        assert verdict.decision == Decision.VETOED
        assert not next(rule for rule in verdict.results if rule.rule_id == "CRO-02").passed


@pytest.mark.parametrize(
    "equity", [Decimal("2000"), Decimal("5000"), Decimal("25000"), Decimal("100000")]
)
@pytest.mark.parametrize("extra,passed", [(-1, True), (0, True), (1, False)])
def test_CRO_03_single_stock_exact_boundary_and_one_share(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    equity: Decimal,
    extra: int,
    passed: bool,
) -> None:
    snapshot = _snapshot(
        clock,
        equity=equity,
        cash=equity,
        settled_cash=equity,
        high_water_mark=equity,
        day_start_equity=equity,
    )
    qty = int(equity * Decimal("0.10") / Decimal("100")) + extra
    result = _rule(
        ChiefRiskOfficer(
            Settings(
                broker_account_type="CASH",
            ),
            _registry(),
            risk_calendar,
        ),
        clock,
        "CRO-03",
        proposal=_proposal(clock, qty=qty),
        snapshot=snapshot,
    )
    assert result.passed == passed


def test_CRO_03_pending_buy_counts_and_ETF_cap(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(_instrument("SPY", asset_class=AssetClass.BROAD_ETF)),
        risk_calendar,
    )
    assert _rule(cro, clock, "CRO-03", proposal=_proposal(clock, symbol="SPY", qty=40)).passed
    assert not _rule(cro, clock, "CRO-03", proposal=_proposal(clock, symbol="SPY", qty=41)).passed
    snapshot = _snapshot(
        clock,
        positions={"AAPL": _position(8)},
        open_orders=(
            OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal("100")),
            OpenOrder(symbol="AAPL", side=Side.SELL, qty=1, limit_price=Decimal("100")),
        ),
    )
    assert _rule(cro, clock, "CRO-03", snapshot=snapshot).passed
    assert not _rule(
        cro, clock, "CRO-03", proposal=_proposal(clock, qty=2), snapshot=snapshot
    ).passed


@pytest.mark.parametrize(
    "equity", [Decimal("2000"), Decimal("5000"), Decimal("25000"), Decimal("100000")]
)
def test_CRO_04_exact_risk_budget_and_one_cent_over(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    equity: Decimal,
) -> None:
    snapshot = _snapshot(
        clock, equity=equity, cash=equity, high_water_mark=equity, day_start_equity=equity
    )
    qty = int(equity / Decimal("1000"))
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert _rule(
        cro,
        clock,
        "CRO-04",
        proposal=_proposal(clock, qty=qty, stop_price=Decimal("90.2")),
        snapshot=snapshot,
    ).passed
    # R-13: the next representable stop is one cent lower at the module boundary.
    stop = Decimal("90.19")
    assert not _rule(
        cro, clock, "CRO-04", proposal=_proposal(clock, qty=qty, stop_price=stop), snapshot=snapshot
    ).passed


def test_CRO_04_ADD_includes_existing_last_to_new_stop(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    snapshot = _snapshot(clock, positions={"AAPL": _position(20)})
    assert not _rule(
        cro, clock, "CRO-04", proposal=_proposal(clock, intent=Intent.ADD), snapshot=snapshot
    ).passed
    below_stop = _snapshot(clock, positions={"AAPL": _position(20, Decimal("90"))})
    assert _rule(
        cro, clock, "CRO-04", proposal=_proposal(clock, intent=Intent.ADD), snapshot=below_stop
    ).passed
    assert _rule(cro, clock, "CRO-04", proposal=_proposal(clock, intent=Intent.ADD)).passed


@pytest.mark.parametrize("existing,passed", [(33, True), (34, True), (35, False)])
def test_CRO_05_sector_cap_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, existing: int, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert (
        _rule(
            cro, clock, "CRO-05", snapshot=_snapshot(clock, positions={"MSFT": _position(existing)})
        ).passed
        == passed
    )


def test_CRO_05_themes_unknown_sectors_and_ETF_lookthrough(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    themes = InstrumentRegistry(
        (_instrument("AAPL", themes=("AI_SEMIS",)), _instrument("MSFT", themes=("AI_SEMIS",)))
    )
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        themes,
        risk_calendar,
    )
    assert _rule(
        cro, clock, "CRO-05", snapshot=_snapshot(clock, positions={"MSFT": _position(24)})
    ).passed
    assert not _rule(
        cro, clock, "CRO-05", snapshot=_snapshot(clock, positions={"MSFT": _position(25)})
    ).passed
    unknown_theme = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        InstrumentRegistry((_instrument("AAPL", themes=("UNLISTED",)),)),
        risk_calendar,
    )
    assert not _rule(unknown_theme, clock, "CRO-05").passed
    unknown_sector = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        InstrumentRegistry((_instrument("AAPL", gics_sector="UNKNOWN"),)),
        risk_calendar,
    )
    assert not _rule(unknown_sector, clock, "CRO-05").passed
    financials = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        InstrumentRegistry((_instrument("AAPL", gics_sector="Financials"),)),
        risk_calendar,
    )
    assert _rule(financials, clock, "CRO-05").passed
    registry = _registry(
        _instrument("SPY", asset_class=AssetClass.BROAD_ETF),
        etf_weights={
            "SPY": {"Information Technology": Decimal("0.5"), "Financials": Decimal("0.5")}
        },
    )
    lookthrough = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        registry,
        risk_calendar,
    )
    snapshot = _snapshot(clock, positions={"AAPL": _position(20)})
    assert _rule(
        lookthrough,
        clock,
        "CRO-05",
        proposal=_proposal(clock, symbol="SPY", qty=30),
        snapshot=snapshot,
    ).passed
    assert not _rule(
        lookthrough,
        clock,
        "CRO-05",
        proposal=_proposal(clock, symbol="SPY", qty=31),
        snapshot=snapshot,
    ).passed


@pytest.mark.parametrize("existing,passed", [(48, True), (49, True), (50, False)])
def test_CRO_06_gross_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, existing: int, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", max_gross_exposure=Decimal("0.50")),
        _registry(),
        risk_calendar,
    )
    assert (
        _rule(
            cro, clock, "CRO-06", snapshot=_snapshot(clock, positions={"MSFT": _position(existing)})
        ).passed
        == passed
    )


@pytest.mark.parametrize(
    "cash,passed", [(Decimal("700.01"), True), (Decimal("700"), True), (Decimal("699.99"), False)]
)
def test_CRO_06_cash_buffer_pending_notional_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, cash: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    snapshot = _snapshot(
        clock,
        cash=cash,
        open_orders=(OpenOrder(symbol="MSFT", side=Side.BUY, qty=1, limit_price=Decimal("100")),),
    )
    assert _rule(cro, clock, "CRO-06", snapshot=snapshot).passed == passed


def test_CRO_06_position_count_boundary_and_zero_holdings(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", max_open_positions=2), _registry(), risk_calendar
    )
    assert _rule(
        cro,
        clock,
        "CRO-06",
        snapshot=_snapshot(clock, positions={"MSFT": _position(1), "IBM": _position(0)}),
    ).passed
    assert not _rule(
        cro,
        clock,
        "CRO-06",
        snapshot=_snapshot(clock, positions={"MSFT": _position(1), "IBM": _position(1)}),
    ).passed


@pytest.mark.parametrize(
    "limit,passed",
    [
        (Decimal("97"), True),
        (Decimal("103"), True),
        (Decimal("103.01"), False),
        (Decimal("96.99"), False),
    ],
)
def test_CRO_07_price_collar_exact_and_cent_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, limit: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert (
        _rule(cro, clock, "CRO-07", proposal=_proposal(clock, limit_price=limit)).passed == passed
    )


@pytest.mark.parametrize("seconds,passed", [(59, True), (60, True), (61, False), (-1, False)])
def test_CRO_07_quote_age_boundary_and_future(
    clock: FrozenClock, risk_calendar: MarketCalendar, seconds: int, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert (
        _rule(
            cro,
            clock,
            "CRO-07",
            market=_market(clock, last_price_ts=clock.now() - timedelta(seconds=seconds)),
        ).passed
        == passed
    )


@pytest.mark.parametrize(
    "price,passed", [(Decimal("5.01"), True), (Decimal("5"), True), (Decimal("4.99"), False)]
)
def test_CRO_07_minimum_price_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, price: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert (
        _rule(
            cro,
            clock,
            "CRO-07",
            proposal=_proposal(clock, limit_price=price, stop_price=Decimal("4")),
            market=_market(clock, last_price=price),
        ).passed
        == passed
    )


def test_CRO_07_DAT_01_weekend_quote_uses_last_close(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    weekend = FrozenClock(datetime(2026, 10, 4, 15, 0, tzinfo=UTC))
    close = risk_calendar.session_close(date(2026, 10, 2))
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert _rule(cro, weekend, "CRO-07", market=_market(weekend, last_price_ts=close)).passed
    assert not _rule(
        cro, weekend, "CRO-07", market=_market(weekend, last_price_ts=close - timedelta(seconds=61))
    ).passed


@pytest.mark.parametrize(
    "adv,passed",
    [
        (Decimal("10001"), True),
        (Decimal("10000"), True),
        (Decimal("9999"), False),
        (Decimal(0), False),
    ],
)
def test_CRO_08_ADV_exact_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, adv: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert _rule(cro, clock, "CRO-08", market=_market(clock, adv20_usd=adv)).passed == passed


@pytest.mark.parametrize(
    "equity,passed",
    [
        (Decimal("9200.01"), True),
        (Decimal("9200"), False),
        (Decimal("9199.99"), False),
        (Decimal("8800"), False),
    ],
)
def test_CRO_09_drawdown_inclusive_tiers(
    clock: FrozenClock, risk_calendar: MarketCalendar, equity: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert _rule(cro, clock, "CRO-09", snapshot=_snapshot(clock, equity=equity)).passed == passed


@pytest.mark.parametrize(
    "equity,passed",
    [(Decimal("9800.01"), True), (Decimal("9800"), False), (Decimal("9799.99"), False)],
)
def test_CRO_10_daily_loss_inclusive_boundary(
    clock: FrozenClock, risk_calendar: MarketCalendar, equity: Decimal, passed: bool
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert _rule(cro, clock, "CRO-10", snapshot=_snapshot(clock, equity=equity)).passed == passed


def test_CRO_10_explicit_session_block_survives_recovery_and_never_blocks_exit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    entry = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
        daily_loss_blocked=True,
    )
    assert entry.decision == Decision.VETOED
    assert entry.recommended_state == SystemState.RUNNING
    assert not next(row for row in entry.results if row.rule_id == "CRO-10").passed
    sold = cro.evaluate(
        _proposal(clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None),
        _snapshot(clock, positions={"AAPL": _position(1)}),
        None,
        SystemState.RUNNING,
        clock.now(),
        daily_loss_blocked=True,
    )
    assert sold.decision == Decision.APPROVED
    batch = cro.evaluate_batch(
        (_proposal(clock),),
        _snapshot(clock),
        {"AAPL": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
        daily_loss_blocked=True,
    )
    assert batch[0].decision == Decision.VETOED
    assert batch[0].recommended_state == SystemState.RUNNING


@pytest.mark.parametrize("bad", [None, 0, "false"])
def test_R_02_CRO_10_session_block_evidence_is_strict_boolean(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    bad: Any,
) -> None:
    result = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    ).evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
        daily_loss_blocked=bad,
    )
    assert result.decision == Decision.VETOED
    assert result.recommended_state == SystemState.HALTED


def test_CRO_09_CRO_10_first_baselines_zero_and_nonpositive_equity(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    fresh = _snapshot(clock, high_water_mark=Decimal(0), day_start_equity=Decimal(0))
    assert not _rule(cro, clock, "CRO-09", snapshot=fresh).passed
    assert not _rule(cro, clock, "CRO-10", snapshot=fresh).passed
    bad = _snapshot(
        clock, equity=Decimal(0), high_water_mark=Decimal(0), day_start_equity=Decimal(0)
    )
    assert not _rule(cro, clock, "CRO-09", snapshot=bad).passed
    assert not _rule(cro, clock, "CRO-10", snapshot=bad).passed


@pytest.mark.parametrize(
    "offset,symbol,passed",
    [
        (-1, "AAPL", False),
        (0, "AAPL", False),
        (1, "AAPL", True),
        (0, None, False),
        (0, "MSFT", True),
    ],
)
def test_CRO_11_blackout_start_end_and_symbol_boundaries(
    clock: FrozenClock, risk_calendar: MarketCalendar, offset: int, symbol: str | None, passed: bool
) -> None:
    window = BlackoutWindow(
        start=clock.now() + timedelta(seconds=offset),
        end=clock.now() + timedelta(seconds=offset + 1),
        symbol=symbol,
        reason="fixture",
    )
    registry = _registry(blackout_windows=(window,))
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        registry,
        risk_calendar,
    )
    assert _rule(cro, clock, "CRO-11").passed == passed
    if offset == -1:
        explicit = ChiefRiskOfficer(
            Settings(
                broker_account_type="CASH",
            ),
            _registry(),
            risk_calendar,
            blackout_windows=(window,),
        )
        assert not _rule(explicit, clock, "CRO-11").passed


@pytest.mark.parametrize("status", list(CapitalStatus))
def test_CRO_12_funding_all_statuses(
    clock: FrozenClock, risk_calendar: MarketCalendar, status: CapitalStatus
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(status),
    )
    assert next(rule for rule in verdict.results if rule.rule_id == "CRO-12").passed == (
        status == CapitalStatus.OK
    )
    missing = cro.evaluate(
        _proposal(clock), _snapshot(clock), _market(clock), SystemState.RUNNING, clock.now()
    )
    assert not next(rule for rule in missing.results if rule.rule_id == "CRO-12").passed


def test_CRO_02_R_02_faults_produce_veto_or_typed_error(
    clock: FrozenClock, risk_calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )

    def broken_calendar(now: datetime) -> bool:
        raise RuntimeError("injected calendar fault")

    monkeypatch.setattr(risk_calendar, "is_open", broken_calendar)
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert len(verdict.results) == 14
    with pytest.raises(DataIntegrityError):
        cro.evaluate(
            _proposal(clock).model_copy(update={"proposal_id": "bad"}),
            _snapshot(clock),
            _market(clock),
            SystemState.RUNNING,
            clock.now(),
        )
    with pytest.raises(DataIntegrityError):
        cro.evaluate(
            _proposal(clock),
            _snapshot(clock),
            _market(clock),
            SystemState.RUNNING,
            clock.now().replace(tzinfo=None),
        )


@pytest.mark.parametrize(
    "equity", [Decimal("2000"), Decimal("5000"), Decimal("25000"), Decimal("100000")]
)
def test_CRO_03_to_08_max_qty_is_largest_whole_share(
    clock: FrozenClock, risk_calendar: MarketCalendar, equity: Decimal
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    snapshot = _snapshot(
        clock, equity=equity, cash=equity, high_water_mark=equity, day_start_equity=equity
    )
    proposal = _proposal(clock, qty=10000, stop_price=Decimal("90.2"))
    largest = cro.max_allowed_qty(proposal, snapshot, _market(clock), clock.now())
    assert largest == int(equity * Decimal("0.10") / Decimal("100"))
    yes = cro.evaluate(
        proposal.model_copy(update={"qty": largest}),
        snapshot,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    no = cro.evaluate(
        proposal.model_copy(update={"qty": largest + 1}),
        snapshot,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert yes.decision == Decision.APPROVED
    assert no.decision == Decision.VETOED


def test_CRO_03_to_08_sizing_fail_closed_and_sell_zero(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    exit_proposal = _proposal(clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None)
    assert cro.max_allowed_qty(exit_proposal, _snapshot(clock), _market(clock), clock.now()) == 0
    assert (
        cro.max_allowed_qty(
            _proposal(clock), _snapshot(clock, cash=Decimal(0)), _market(clock), clock.now()
        )
        == 0
    )
    assert (
        cro.max_allowed_qty(
            _proposal(clock, symbol="UNKNOWN"), _snapshot(clock), _market(clock), clock.now()
        )
        == 0
    )
    with pytest.raises(DataIntegrityError):
        cro.max_allowed_qty(
            _proposal(clock).model_copy(update={"limit_price": Decimal(0)}),
            _snapshot(clock),
            _market(clock),
            clock.now(),
        )
    with pytest.raises(DataIntegrityError):
        cro.max_allowed_qty(
            _proposal(clock), cast(PortfolioSnapshot, None), _market(clock), clock.now()
        )


def test_CRO_03_CRO_06_batch_reserves_approved_buys_and_sells(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    buy = _proposal(clock, qty=6, stop_price=Decimal("99"))
    verdicts = cro.evaluate_batch(
        (buy, buy),
        _snapshot(clock),
        {"AAPL": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert [verdict.decision for verdict in verdicts] == [Decision.APPROVED, Decision.VETOED]
    sell = _proposal(clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None, qty=1)
    snapshot = _snapshot(clock, positions={"AAPL": _position(1)})
    exits = cro.evaluate_batch(
        (sell, sell), snapshot, {"AAPL": _market(clock)}, SystemState.RUNNING, clock.now()
    )
    assert [verdict.decision for verdict in exits] == [Decision.APPROVED, Decision.VETOED]
    missing = cro.evaluate_batch((buy,), _snapshot(clock), {}, SystemState.RUNNING, clock.now())
    assert missing[0].decision == Decision.VETOED


@hypothesis_settings(max_examples=75, deadline=None)
@given(
    equity=st.integers(min_value=2000, max_value=100000),
    qty=st.integers(min_value=1, max_value=1000),
)
def test_CRO_03_CRO_04_R_03_property_no_overweight_or_overrisk(equity: int, qty: int) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))
    calendar = MarketCalendar(start=date(2026, 9, 1), end=date(2026, 10, 31))
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        calendar,
    )
    capital = Decimal(equity)
    snapshot = _snapshot(
        clock, equity=capital, cash=capital, high_water_mark=capital, day_start_equity=capital
    )
    proposal = _proposal(clock, qty=qty, stop_price=Decimal("90.2"))
    verdict = cro.evaluate(
        proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    assert verdict == cro.evaluate(
        proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    if verdict.decision == Decision.APPROVED:
        assert qty * Decimal("100") <= capital * Decimal("0.10")
        assert qty * Decimal("10") <= capital * Decimal("0.01")


@hypothesis_settings(max_examples=50, deadline=None)
@given(
    held=st.integers(min_value=0, max_value=1000), extra=st.integers(min_value=1, max_value=1000)
)
def test_CRO_02_R_01_property_never_oversells(held: int, extra: int) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        MarketCalendar(start=date(2026, 9, 1), end=date(2026, 10, 31)),
    )
    proposal = _proposal(
        clock, side=Side.SELL, intent=Intent.REDUCE, qty=held + extra, stop_price=None
    )
    snapshot = _snapshot(clock, positions={"AAPL": _position(held)})
    assert (
        cro.evaluate(proposal, snapshot, _market(clock), SystemState.RUNNING, clock.now()).decision
        == Decision.VETOED
    )


@hypothesis_settings(max_examples=25, deadline=None)
@given(
    qty=st.integers(min_value=1, max_value=1000),
    state=st.sampled_from([SystemState.REDUCE_ONLY, SystemState.HALTED]),
)
def test_CRO_01_property_never_enters_nonrunning(qty: int, state: SystemState) -> None:
    clock = FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        MarketCalendar(start=date(2026, 9, 1), end=date(2026, 10, 31)),
    )
    assert (
        cro.evaluate(
            _proposal(clock, qty=qty),
            _snapshot(clock),
            _market(clock),
            state,
            clock.now(),
            deployable=_capital(),
        ).decision
        == Decision.VETOED
    )


@pytest.mark.parametrize("invalid_dependency", ["registry", "calendar"])
def test_CRO_02_R_02_constructor_requires_verified_dependencies(
    risk_calendar: MarketCalendar,
    invalid_dependency: str,
) -> None:
    registry = cast(InstrumentRegistry, None) if invalid_dependency == "registry" else _registry()
    calendar = cast(MarketCalendar, None) if invalid_dependency == "calendar" else risk_calendar
    with pytest.raises(ConfigurationError):
        ChiefRiskOfficer(
            Settings(
                broker_account_type="CASH",
            ),
            registry,
            calendar,
        )


def test_CRO_02_R_07_explicit_telegram_allowlist_preserved(
    risk_calendar: MarketCalendar,
) -> None:
    config = Settings(broker_account_type="CASH", telegram_allowed_user_ids=(123,))
    cro = ChiefRiskOfficer(config, _registry(), risk_calendar)
    assert cro.config.telegram_allowed_user_ids == (123,)
    assert cro.config.config_hash == config.config_hash


def test_CRO_04_R_02_protection_fault_never_becomes_zero_risk(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    forged = _proposal(clock).model_copy(update={"stop_price": None})
    with pytest.raises(DataIntegrityError):
        cro._risk(forged, _snapshot(clock))


@pytest.mark.parametrize(
    "earnings,passed",
    [(date(2026, 9, 28), False), (date(2026, 9, 29), False), (date(2026, 9, 30), True)],
)
def test_CRO_13_zero_sessions_blocks_same_day_and_unresolved_past(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    earnings: date,
    passed: bool,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", earnings_blackout_sessions=0),
        _registry(),
        risk_calendar,
    )
    rule = _rule(cro, clock, "CRO-13", market=_market(clock, next_earnings_date=earnings))
    assert rule.passed == passed
    assert rule.severity == Severity.BLOCK


def test_CRO_13_uses_exchange_date_after_UTC_midnight(
    risk_calendar: MarketCalendar,
) -> None:
    clock = FrozenClock(datetime(2026, 9, 30, 0, 30, tzinfo=UTC))
    close = risk_calendar.session_close(date(2026, 9, 29))
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", earnings_blackout_sessions=0),
        _registry(),
        risk_calendar,
    )
    rule = _rule(
        cro,
        clock,
        "CRO-13",
        market=_market(clock, last_price_ts=close, next_earnings_date=date(2026, 9, 30)),
    )
    assert rule.passed


@pytest.mark.parametrize(
    "equity,expected",
    [
        (Decimal("10000"), SystemState.RUNNING),
        (Decimal("9800"), SystemState.RUNNING),
        (Decimal("9200"), SystemState.REDUCE_ONLY),
        (Decimal("8800"), SystemState.HALTED),
        (Decimal("0"), SystemState.HALTED),
    ],
)
def test_CRO_09_CRO_10_recommendations_are_pure_and_do_not_trap_exits(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    equity: Decimal,
    expected: SystemState,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    snapshot = _snapshot(clock, equity=equity, positions={"AAPL": _position(1)})
    exit_proposal = _proposal(clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None)
    verdict = cro.evaluate(exit_proposal, snapshot, None, SystemState.RUNNING, clock.now())
    assert verdict.decision == Decision.APPROVED
    assert verdict.recommended_state == expected
    assert [result.rule_id for result in verdict.results] == ["CRO-01", "CRO-02"]


def test_CRO_03_to_08_advisory_sizing_never_increases_requested_qty(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    assert (
        cro.max_allowed_qty(_proposal(clock, qty=2), _snapshot(clock), _market(clock), clock.now())
        == 2
    )


def test_CRO_03_CRO_06_batch_iteration_fault_is_typed(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    class BrokenBatch:
        def __iter__(self) -> Any:
            raise RuntimeError("batch source unavailable")

    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    with pytest.raises(DataIntegrityError):
        cro.evaluate_batch(BrokenBatch(), _snapshot(clock), {}, SystemState.RUNNING, clock.now())


def test_CRO_01_R_02_batch_unverifiable_market_latches_local_halt(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    bad = _proposal(clock, symbol="MSFT")
    good = _proposal(clock)
    verdicts = cro.evaluate_batch(
        (bad, good),
        _snapshot(clock),
        {"AAPL": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdicts[0].recommended_state == SystemState.HALTED
    assert verdicts[1].decision == Decision.VETOED
    assert [result.rule_id for result in verdicts[1].results] == ["CRO-01"]


def test_CRO_04_batch_approved_but_unsubmitted_stop_risk_is_reserved(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    )
    first = _proposal(clock, qty=4, stop_price=Decimal("80"))
    second = _proposal(clock, proposal_id=UUID(int=3), intent=Intent.ADD, stop_price=Decimal("80"))
    verdicts = cro.evaluate_batch(
        (first, second),
        _snapshot(clock),
        {"AAPL": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdicts[0].decision == Decision.APPROVED
    assert verdicts[1].decision == Decision.VETOED
    assert next(result for result in verdicts[1].results if result.rule_id == "CRO-02").passed
    risk = next(result for result in verdicts[1].results if result.rule_id == "CRO-04")
    assert not risk.passed
    assert Decimal(risk.observed) == Decimal("101.00")


@pytest.mark.parametrize("unknown_inventory", ["zero_position", "pending_sell", "protective_stop"])
def test_R_02_CRO_02_unknown_inventory_is_not_ignored_for_new_entries(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    unknown_inventory: str,
) -> None:
    changes: dict[str, Any] = (
        {"positions": {"UNKNOWN": _position(0)}}
        if unknown_inventory == "zero_position"
        else {
            "protective_stops": (ProtectiveStop(symbol="UNKNOWN", qty=1, stop_price=Decimal("95")),)
        }
        if unknown_inventory == "protective_stop"
        else {
            "open_orders": (
                OpenOrder(symbol="UNKNOWN", side=Side.SELL, qty=1, limit_price=Decimal("100")),
            )
        }
    )
    verdict = ChiefRiskOfficer(
        Settings(
            broker_account_type="CASH",
        ),
        _registry(),
        risk_calendar,
    ).evaluate(
        _proposal(clock),
        _snapshot(clock, **changes),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.VETOED
    assert verdict.recommended_state == SystemState.HALTED


def test_CRO_02_registered_protective_inventory_keeps_other_entries_available(
    clock: FrozenClock, risk_calendar: MarketCalendar
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    snapshot = _snapshot(
        clock,
        positions={"MSFT": _position(1)},
        protective_stops=(ProtectiveStop(symbol="MSFT", qty=1, stop_price=Decimal("95")),),
    )
    assert _rule(cro, clock, "CRO-02", snapshot=snapshot).passed


@pytest.mark.parametrize(
    "requested,cash,equity,stop,expected",
    [
        (1, "1000", "1000", "95", 1),
        (3, "1000", "1000", "95", 1),
        (10000, "10000", "10000", "90.2", 10),
        (1, "0", "10000", "95", 0),
        (1, "99.99", "10000", "95", 0),
    ],
)
def test_CRO_03_exact_whole_share_advisory_respects_cash_and_name_cap(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    requested: int,
    cash: str,
    equity: str,
    stop: str,
    expected: int,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    book = _snapshot(
        clock,
        cash=Decimal(cash),
        settled_cash=Decimal(cash),
        equity=Decimal(equity),
        high_water_mark=Decimal(equity),
        day_start_equity=Decimal(equity),
    )
    result = cro.max_allowed_qty(
        _proposal(clock, qty=requested, stop_price=Decimal(stop)), book, _market(clock), clock.now()
    )
    assert type(result) is int and result == expected
    if result:
        verdict = cro.evaluate(
            _proposal(clock, qty=result, stop_price=Decimal(stop)),
            book,
            _market(clock),
            SystemState.RUNNING,
            clock.now(),
            deployable=_capital(),
        )
        assert verdict.decision == Decision.APPROVED


@pytest.mark.parametrize("fault", ["proposal", "snapshot", "market", "time", "price"])
def test_CRO_03_unverifiable_advisory_has_exact_typed_refusal(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    fault: str,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(clock)
    book = _snapshot(clock)
    quote = _market(clock)
    instant = clock.now()
    if fault == "proposal":
        order = cast(TradeProposal, None)
    elif fault == "snapshot":
        book = cast(PortfolioSnapshot, None)
    elif fault == "market":
        quote = cast(MarketContext, None)
    elif fault == "time":
        instant = instant.replace(tzinfo=None)
    else:
        order = order.model_copy(update={"limit_price": Decimal(0)})
    with pytest.raises(DataIntegrityError) as refused:
        cro.max_allowed_qty(order, book, quote, instant)
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "CRO-03..08: deterministic sizing failed closed"


@pytest.mark.parametrize(
    "pending_stop,expected,passed",
    [
        (Decimal(90), Decimal("50.84"), True),
        (None, Decimal("230.84"), False),
    ],
)
def test_CRO_04_add_reserves_existing_and_pending_shares_at_the_worse_stop(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    pending_stop: Decimal | None,
    expected: Decimal,
    passed: bool,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(clock, intent=Intent.ADD)
    book = _snapshot(
        clock,
        positions={"AAPL": _position(1)},
        open_orders=(
            OpenOrder(
                symbol="AAPL",
                side=Side.BUY,
                qty=2,
                limit_price=Decimal(110),
                stop_price=pending_stop,
            ),
        ),
    )
    row = next(
        r
        for r in cro.evaluate(
            order, book, _market(clock), SystemState.RUNNING, clock.now(), deployable=_capital()
        ).results
        if r.rule_id == "CRO-04"
    )
    assert row.passed is passed and row.severity == Severity.BLOCK
    assert Decimal(row.observed) == expected and Decimal(row.limit) == Decimal(100)
    assert row.message == "reserved stop risk plus slippage fits budget"


def test_CRO_04_unverified_buy_stop_has_exact_audit_error(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    malformed = _proposal(clock).model_copy(update={"stop_price": None})
    with pytest.raises(DataIntegrityError) as refused:
        cro._risk(malformed, _snapshot(clock))
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "CRO-04: buy protection cannot be verified"


@pytest.mark.parametrize("missing", ["registry", "calendar"])
def test_CRO_02_missing_policy_dependencies_preserve_the_exact_fault_chain(
    risk_calendar: MarketCalendar,
    missing: str,
) -> None:
    with pytest.raises(ConfigurationError) as refused:
        ChiefRiskOfficer(
            Settings(broker_account_type="CASH"),
            cast(InstrumentRegistry, None) if missing == "registry" else _registry(),
            cast(MarketCalendar, None) if missing == "calendar" else risk_calendar,
        )
    assert type(refused.value) is ConfigurationError
    assert str(refused.value) == "CRO-01..13: cannot verify immutable risk policy"
    assert type(refused.value.__cause__) is DataIntegrityError
    assert str(refused.value.__cause__) == "CRO-02: registry and bounded calendar are required"


def test_CRO_01_explicit_empty_operator_allowlist_is_not_reinterpreted_as_default(
    risk_calendar: MarketCalendar,
) -> None:
    invalid = Settings(broker_account_type="CASH").model_copy(
        update={"telegram_allowed_user_ids": ()}
    )
    with pytest.raises(ConfigurationError) as refused:
        ChiefRiskOfficer(invalid, _registry(), risk_calendar)
    assert type(refused.value) is ConfigurationError
    assert str(refused.value) == "CRO-01..13: cannot verify immutable risk policy"


@pytest.mark.parametrize(
    "instant,start,end,blackout,overlap",
    [
        (datetime(2026, 10, 1, 16, tzinfo=UTC), 4, 5, 0, False),
        (datetime(2026, 10, 2, 16, tzinfo=UTC), 4, 5, 0, True),
        (datetime(2026, 9, 30, 16, tzinfo=UTC), 4, 5, 2, True),
        (datetime(2026, 10, 1, 16, tzinfo=UTC), 4, 5, 2, True),
        (datetime(2026, 10, 2, 16, tzinfo=UTC), 5, 5, 0, False),
        (datetime(2026, 10, 5, 0, 30, tzinfo=UTC), 2, 4, 0, True),
        (datetime(2026, 10, 4, 4, 30, tzinfo=UTC), 4, 4, 0, True),
    ],
)
def test_CRO_13_estimated_weekend_window_uses_exchange_dates_and_inclusive_end(
    risk_calendar: MarketCalendar,
    instant: datetime,
    start: int,
    end: int,
    blackout: int,
    overlap: bool,
) -> None:
    from backend.domain.models import EarningsInfo, EarningsStatus
    from backend.risk.risk_cro import earnings_rule

    fixed = FrozenClock(instant)
    evidence = EarningsInfo(
        status=EarningsStatus.ESTIMATED,
        source="offline weekend filing interval",
        window_start=date(2026, 10, start),
        window_end=date(2026, 10, end),
    )
    row = earnings_rule(
        _market(fixed, earnings=evidence),
        instant,
        Settings(broker_account_type="CASH", earnings_blackout_sessions=blackout),
        risk_calendar,
    )
    assert row.rule_id == "CRO-13" and not row.passed and row.severity == Severity.WARN
    assert row.observed == f"estimated 2026-10-{start:02d}..2026-10-{end:02d}"
    assert row.limit == "verified earnings date"
    assert row.message == (
        "estimated earnings window overlaps the blackout; operator review required"
        if overlap
        else "earnings window is estimated; next confirmed date remains unavailable"
    )


@pytest.mark.parametrize(
    "today,event,blackout,blocked",
    [
        (datetime(2026, 10, 1, 16, tzinfo=UTC), date(2026, 10, 4), 0, False),
        (datetime(2026, 10, 2, 16, tzinfo=UTC), date(2026, 10, 4), 0, True),
        (datetime(2026, 9, 30, 16, tzinfo=UTC), date(2026, 10, 4), 2, True),
        (datetime(2026, 10, 1, 16, tzinfo=UTC), date(2026, 10, 4), 2, True),
        (datetime(2026, 10, 2, 16, tzinfo=UTC), date(2026, 10, 2), 0, True),
    ],
)
def test_CRO_13_confirmed_evidence_without_legacy_date_retains_weekend_blackout(
    risk_calendar: MarketCalendar,
    today: datetime,
    event: date,
    blackout: int,
    blocked: bool,
) -> None:
    from backend.domain.models import EarningsInfo, EarningsStatus
    from backend.risk.risk_cro import earnings_rule

    evidence = EarningsInfo(
        status=EarningsStatus.KNOWN, date=event, source="offline confirmed filing"
    )
    row = earnings_rule(
        _market(FrozenClock(today), earnings=evidence),
        today,
        Settings(broker_account_type="CASH", earnings_blackout_sessions=blackout),
        risk_calendar,
    )
    assert (row.rule_id, row.passed, row.severity, row.observed, row.limit, row.message) == (
        "CRO-13",
        not blocked,
        Severity.BLOCK,
        event.isoformat(),
        f"outside {blackout} XNYS sessions",
        "known earnings within inclusive blackout or unresolved past date blocks",
    )


@pytest.mark.parametrize("extended_policy,decimal_places", [(False, 80), (True, 122)])
def test_CRO_09_and_10_keep_the_exact_recurring_fraction_in_the_audit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    extended_policy: bool,
    decimal_places: int,
) -> None:
    # A $10,000 loss from $30,000 is exactly one third. The stored audit text
    # must retain the established digits, including under exact extended policy.
    config = Settings(
        broker_account_type="CASH",
        max_single_stock_weight=(
            Decimal("0.10" + "0" * 80) if extended_policy else Decimal("0.10")
        ),
    )
    cro = ChiefRiskOfficer(config, _registry(), risk_calendar)
    book = _snapshot(
        clock,
        equity=Decimal(20000),
        cash=Decimal(20000),
        settled_cash=Decimal(20000),
        high_water_mark=Decimal(30000),
        day_start_equity=Decimal(30000),
    )
    verdict = cro.evaluate(
        _proposal(clock),
        book,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    rows = {row.rule_id: row for row in verdict.results}
    assert rows["CRO-09"].observed == "0." + "3" * decimal_places
    assert rows["CRO-10"].observed == "0." + "3" * decimal_places
    assert not rows["CRO-09"].passed and not rows["CRO-10"].passed
    assert verdict.decision == Decision.VETOED and verdict.recommended_state == SystemState.HALTED


@pytest.mark.parametrize(
    "field,value",
    [
        ("high_water_mark", Decimal(0)),
        ("high_water_mark", Decimal("0.5")),
        ("day_start_equity", Decimal(0)),
        ("day_start_equity", Decimal("0.5")),
    ],
)
def test_CRO_09_and_10_small_or_missing_baselines_retain_exact_audit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    field: str,
    value: Decimal,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    baselines = {"high_water_mark": Decimal(1), "day_start_equity": Decimal(1), field: value}
    book = _snapshot(
        clock,
        equity=Decimal("0.25"),
        cash=Decimal("0.25"),
        settled_cash=Decimal("0.25"),
        **baselines,
    )
    verdict = cro.evaluate(
        _proposal(clock),
        book,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    rule = "CRO-09" if field == "high_water_mark" else "CRO-10"
    row = next(row for row in verdict.results if row.rule_id == rule)
    assert row.observed == ("0" if value == 0 else "0.5")
    assert not row.passed and verdict.decision == Decision.VETOED


@pytest.mark.parametrize("field", ["high_water_mark", "day_start_equity"])
def test_CRO_09_and_10_accept_a_positive_half_dollar_baseline_without_loss(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    field: str,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    values = {"high_water_mark": Decimal("0.5"), "day_start_equity": Decimal("0.5")}
    book = _snapshot(
        clock, equity=Decimal("0.5"), cash=Decimal("0.5"), settled_cash=Decimal("0.5"), **values
    )
    verdict = cro.evaluate(
        _proposal(clock),
        book,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    row = next(
        row
        for row in verdict.results
        if row.rule_id == ("CRO-09" if field == "high_water_mark" else "CRO-10")
    )
    assert row.passed and row.observed == "0" and verdict.recommended_state == SystemState.RUNNING


@pytest.mark.parametrize(
    "age,expired,held,passed",
    [
        (30, False, True, True),
        (30, True, True, False),
        (31, False, True, False),
        (0, False, False, False),
    ],
)
def test_CRO_02_exact_exit_expiry_freshness_and_held_quantity_audit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    age: int,
    expired: bool,
    held: bool,
    passed: bool,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", stale_quote_seconds=30), _registry(), risk_calendar
    )
    order = _proposal(
        clock,
        side=Side.SELL,
        intent=Intent.EXIT,
        stop_price=None,
        created_at=clock.now() - timedelta(minutes=1),
        expires_at=clock.now() if expired else clock.now() + timedelta(minutes=1),
    )
    book = _snapshot(
        clock,
        as_of=clock.now() - timedelta(seconds=age),
        positions={"AAPL": _position(1)} if held else {},
    )
    result = cro.evaluate(order, book, None, SystemState.RUNNING, clock.now())
    row = result.results[1]
    assert (row.rule_id, row.passed, row.severity, row.observed, row.limit, row.message) == (
        "CRO-02",
        passed,
        Severity.BLOCK,
        "1",
        "1" if held else "0",
        "reduction fits fresh held unreserved shares",
    )
    assert result.decision == (Decision.APPROVED if passed else Decision.VETOED)
    assert result.recommended_state == SystemState.RUNNING


@pytest.mark.parametrize(
    "inventory", ["other_buy", "same_sell", "one_share", "zero_position", "pending_one"]
)
def test_CRO_02_and_04_only_same_name_buys_reserve_entry_protection(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    inventory: str,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    positions = (
        {"AAPL": _position(1)}
        if inventory in {"one_share", "same_sell"}
        else ({"AAPL": _position(0)} if inventory == "zero_position" else {})
    )
    orders = (
        ()
        if inventory in {"one_share", "zero_position"}
        else (
            OpenOrder(
                symbol="MSFT" if inventory == "other_buy" else "AAPL",
                side=Side.SELL if inventory == "same_sell" else Side.BUY,
                qty=1,
                limit_price=Decimal(100),
                stop_price=Decimal(90),
            ),
        )
    )
    book = _snapshot(clock, positions=positions, open_orders=orders)
    order = _proposal(
        clock,
        intent=Intent.ADD
        if inventory in {"one_share", "same_sell", "pending_one"}
        else Intent.ENTRY,
    )
    result = cro.evaluate(
        order, book, _market(clock), SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    rows = {row.rule_id: row for row in result.results}
    assert rows["CRO-02"].passed
    assert Decimal(rows["CRO-04"].observed) == (
        Decimal("10.40")
        if inventory in {"one_share", "same_sell"}
        else Decimal("15.40")
        if inventory == "pending_one"
        else Decimal("5.20")
    )
    assert rows["CRO-04"].passed and result.recommended_state == SystemState.RUNNING


@pytest.mark.parametrize("constraint", ["sector", "unconfigured_theme"])
def test_CRO_05_configured_sector_and_unconfigured_theme_caps_veto_without_fault(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    constraint: str,
) -> None:
    registry = _registry(_instrument("NVDA", themes=("offline-risk-theme",)))
    config = (
        Settings(
            broker_account_type="CASH", sector_caps={"Information Technology": Decimal("0.005")}
        )
        if constraint == "sector"
        else Settings(broker_account_type="CASH")
    )
    cro = ChiefRiskOfficer(config, registry, risk_calendar)
    result = cro.evaluate(
        _proposal(clock, symbol="AAPL" if constraint == "sector" else "NVDA"),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    row = next(row for row in result.results if row.rule_id == "CRO-05")
    assert not row.passed and row.severity == Severity.BLOCK
    assert (
        row.limit == "configured sector/theme fractions"
        and row.message == "sector look-through and theme caps fit"
    )
    assert result.decision == Decision.VETOED and result.recommended_state == SystemState.RUNNING


def test_CRO_01_batch_manual_exit_does_not_reset_a_latched_halt_for_the_next_entry(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    exit_order = _proposal(
        clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None, source=ProposalSource.MANUAL
    )
    entry = _proposal(clock, proposal_id=UUID(int=17), symbol="MSFT")
    results = cro.evaluate_batch(
        (exit_order, entry),
        _snapshot(clock, positions={"AAPL": _position(1)}),
        {"MSFT": _market(clock)},
        SystemState.HALTED,
        clock.now(),
        deployable=_capital(),
    )
    assert results[0].decision == Decision.APPROVED
    assert results[1].decision == Decision.VETOED and len(results[1].results) == 1
    assert results[1].results[0].rule_id == "CRO-01" and not results[1].results[0].passed


def test_CRO_03_batch_unavailable_proposal_stream_has_exact_typed_refusal(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    class Unavailable:
        def __iter__(self) -> Any:
            raise RuntimeError("offline proposal stream unavailable")

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    with pytest.raises(DataIntegrityError) as refused:
        cro.evaluate_batch(Unavailable(), _snapshot(clock), {}, SystemState.RUNNING, clock.now())
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "CRO-03/CRO-06: batch inputs cannot be verified"
    assert type(refused.value.__cause__) is RuntimeError
    assert str(refused.value.__cause__) == "offline proposal stream unavailable"


@pytest.mark.parametrize("identity", [None, "unverifiable-id", 7])
def test_CRO_02_unbound_proposal_cannot_create_a_verdict_and_keeps_exact_fault_chain(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    identity: object,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    damaged = _proposal(clock).model_copy(update={"proposal_id": identity})
    with pytest.raises(DataIntegrityError) as refused:
        cro.evaluate(
            damaged,
            _snapshot(clock),
            _market(clock),
            SystemState.RUNNING,
            clock.now(),
            deployable=_capital(),
        )
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "CRO-02: cannot construct an auditable veto"
    assert type(refused.value.__cause__) is DataIntegrityError
    assert str(refused.value.__cause__) == "CRO-02: invalid proposal identity"


def test_CRO_02_positive_fractional_equity_keeps_valid_shape_even_when_size_is_vetoed(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    book = _snapshot(
        clock,
        equity=Decimal("0.5"),
        cash=Decimal("0.5"),
        settled_cash=Decimal("0.5"),
        high_water_mark=Decimal("0.5"),
        day_start_equity=Decimal("0.5"),
    )
    result = cro.evaluate(
        _proposal(clock),
        book,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    shape = result.results[1]
    assert shape.rule_id == "CRO-02" and shape.passed
    assert result.decision == Decision.VETOED and result.recommended_state == SystemState.RUNNING
    assert not next(row for row in result.results if row.rule_id == "CRO-03").passed


def test_CRO_03_two_pending_buys_in_one_name_reserve_both_notionals(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    book = _snapshot(
        clock,
        open_orders=(
            OpenOrder(
                symbol="AAPL",
                side=Side.BUY,
                qty=4,
                limit_price=Decimal(100),
                stop_price=Decimal(95),
            ),
            OpenOrder(
                symbol="AAPL",
                side=Side.BUY,
                qty=6,
                limit_price=Decimal(100),
                stop_price=Decimal(95),
            ),
        ),
    )
    result = cro.evaluate(
        _proposal(clock, intent=Intent.ADD),
        book,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    row = next(row for row in result.results if row.rule_id == "CRO-03")
    assert (
        not row.passed
        and Decimal(row.observed) == Decimal(1100)
        and Decimal(row.limit) == Decimal(1000)
    )
    assert result.decision == Decision.VETOED and result.recommended_state == SystemState.RUNNING


def test_CRO_13_estimate_ending_yesterday_is_clear_at_exchange_midnight(
    risk_calendar: MarketCalendar,
) -> None:
    from backend.domain.models import EarningsInfo, EarningsStatus
    from backend.risk.risk_cro import earnings_rule

    instant = datetime(2026, 10, 4, 4, 30, tzinfo=UTC)
    evidence = EarningsInfo(
        status=EarningsStatus.ESTIMATED,
        source="offline dated filing",
        window_start=date(2026, 10, 2),
        window_end=date(2026, 10, 3),
    )
    row = earnings_rule(
        _market(FrozenClock(instant), earnings=evidence),
        instant,
        Settings(broker_account_type="CASH", earnings_blackout_sessions=0),
        risk_calendar,
    )
    assert row.message == "earnings window is estimated; next confirmed date remains unavailable"
    assert row.observed == "estimated 2026-10-02..2026-10-03" and row.severity == Severity.WARN


def test_CRO_14_two_shares_at_the_exact_portfolio_stop_risk_cap_are_allowed(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", portfolio_max_open_risk=Decimal("0.001")),
        _registry(),
        risk_calendar,
    )
    result = cro.evaluate(
        _proposal(clock, qty=2),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    row = next(row for row in result.results if row.rule_id == "CRO-14")
    assert row.passed and row.severity == Severity.BLOCK
    assert Decimal(row.observed) == Decimal(10) and Decimal(row.limit) == Decimal(10)
    assert row.message == "total held, pending and new stop risk fits the portfolio cap"
    assert result.decision == Decision.APPROVED and result.recommended_state == SystemState.RUNNING


def test_CRO_14_independent_guard_refuses_missing_protection_after_a_faulty_risk_check(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    earlier = cro._risk(_proposal(clock), _snapshot(clock))
    monkeypatch.setattr(cro, "_risk", lambda *args: earlier)
    unprotected = _proposal(clock).model_copy(update={"stop_price": None})
    with pytest.raises(DataIntegrityError) as refused:
        cro._rules(unprotected, _snapshot(clock), _market(clock), clock.now(), None, False)
    assert type(refused.value) is DataIntegrityError
    assert str(refused.value) == "CRO-14: entry protection is unavailable"


def test_CRO_09_oversized_proposal_keeps_full_exact_loss_audit_while_refusing_size(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    book = _snapshot(
        clock,
        equity=Decimal(20000),
        cash=Decimal(20000),
        settled_cash=Decimal(20000),
        high_water_mark=Decimal(30000),
        day_start_equity=Decimal(30000),
    )
    result = cro.evaluate(
        _proposal(clock, qty=10**50 + 1),
        book,
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    rows = {row.rule_id: row for row in result.results}
    assert rows["CRO-09"].observed == "0." + "3" * 91
    assert rows["CRO-10"].observed == "0." + "3" * 91
    assert not rows["CRO-03"].passed and result.decision == Decision.VETOED


def test_CRO_13_today_earnings_block_at_first_verified_session_without_prior_history() -> None:
    from backend.risk.risk_cro import earnings_rule

    calendar = MarketCalendar(start=date(2026, 10, 2), end=date(2026, 10, 8))
    instant = datetime(2026, 10, 2, 16, tzinfo=UTC)
    row = earnings_rule(
        _market(FrozenClock(instant), next_earnings_date=date(2026, 10, 2)),
        instant,
        Settings(broker_account_type="CASH", earnings_blackout_sessions=2),
        calendar,
    )
    assert not row.passed and row.severity == Severity.BLOCK and row.observed == "2026-10-02"
    assert row.message == "known earnings within inclusive blackout or unresolved past date blocks"


@pytest.mark.parametrize("quantity,passed", [(20, True), (21, False)])
def test_CRO_14_nonpaper_observation_cannot_expand_the_locked_manual_risk_ceiling(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    quantity: int,
    passed: bool,
) -> None:
    policy = Settings(
        broker_account_type="CASH",
        portfolio_max_open_risk=Decimal("0.04"),
        live_max_open_risk=Decimal("0.01"),
    )
    cro = ChiefRiskOfficer(policy, _registry(), risk_calendar)
    # A fault-injected non-paper observation must tighten this pure risk rule.
    # The host execution mode and live unlock remain disabled; no broker exists.
    observed = policy.model_copy(update={"paper_trading": False})
    assert observed.execution_mode == "MANUAL" and not observed.live_trading_enabled
    monkeypatch.setattr(cro, "config", observed)
    result = cro.evaluate(
        _proposal(clock, qty=quantity),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    row = next(row for row in result.results if row.rule_id == "CRO-14")
    assert row.passed is passed and row.severity == Severity.BLOCK
    assert Decimal(row.observed) == Decimal(100 if quantity == 20 else 105)
    assert Decimal(row.limit) == Decimal(100)
    assert row.message == "total held, pending and new stop risk fits the portfolio cap"
    assert result.decision == Decision.VETOED


def test_CRO_03_unaffordable_high_price_yields_zero_under_bounded_decimal_exponents(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    from decimal import localcontext

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(
        clock, qty=1, limit_price=Decimal("1000000000"), stop_price=Decimal("900000000")
    )
    book = _snapshot(
        clock,
        cash=Decimal("1000000000"),
        settled_cash=Decimal("1000000000"),
        equity=Decimal("1000000000"),
        high_water_mark=Decimal("1000000000"),
        day_start_equity=Decimal("1000000000"),
    )
    quote = _market(clock, last_price=Decimal("1000000000"), adv20_usd=Decimal("1000000000"))
    with localcontext() as context:
        context.Emax = 15
        result = cro.max_allowed_qty(order, book, quote, clock.now())
    assert type(result) is int and result == 0


def test_CRO_03_strict_rounding_trap_has_an_exact_deterministic_sizing_refusal(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An actual arithmetic fault, rather than a caller trap, refuses all sizing."""
    from decimal import Rounded, localcontext

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    book = _snapshot(clock, cash=Decimal("1000." + "0" * 81), settled_cash=Decimal(1000))
    probes: list[int] = []
    risk = cro._risk

    def fault(proposal: TradeProposal, snapshot: PortfolioSnapshot) -> RuleResult:
        probes.append(proposal.qty)
        if proposal.qty == 4:
            raise Rounded("Injected arithmetic fault")
        return risk(proposal, snapshot)

    monkeypatch.setattr(cro, "_risk", fault)
    with localcontext() as context:
        context.traps[Rounded] = True
        assert cro.max_allowed_qty(_proposal(clock, qty=8), book, _market(clock), clock.now()) == 0
        assert context.traps[Rounded] is True
    assert probes == [4]
    assert "risk_sizing_fault reason=Rounded" in caplog.text


def test_CRO_12_missing_funding_reading_has_an_exact_blocking_audit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    result = cro.evaluate(
        _proposal(clock), _snapshot(clock), _market(clock), SystemState.RUNNING, clock.now()
    )
    row = next(row for row in result.results if row.rule_id == "CRO-12")
    assert (row.passed, row.severity, row.observed, row.limit, row.message) == (
        False,
        Severity.BLOCK,
        "missing",
        str(CapitalStatus.OK),
        "checking buffer and funding reading must be available",
    )
    assert result.decision == Decision.VETOED and result.recommended_state == SystemState.RUNNING


@pytest.mark.parametrize(
    "price,stop,expected",
    # 1% of $9T ADV is $90B: 900M $100 shares, below the name/risk caps.
    [(Decimal(100), Decimal(95), 900000000), (Decimal("0.02"), Decimal("0.01"), 0)],
)
def test_CRO_03_largest_money_domain_fits_the_existing_advisory_work_bound(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    price: Decimal,
    stop: Decimal,
    expected: int,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    book = _snapshot(
        clock,
        cash=Decimal("9000000000000"),
        settled_cash=Decimal("9000000000000"),
        equity=Decimal("9000000000000"),
        high_water_mark=Decimal("9000000000000"),
        day_start_equity=Decimal("9000000000000"),
    )
    result = cro.max_allowed_qty(
        _proposal(clock, qty=10**50 + 1, limit_price=price, stop_price=stop),
        book,
        _market(clock, last_price=price, adv20_usd=Decimal("9000000000000")),
        clock.now(),
    )
    assert type(result) is int and result == expected


def test_CRO_01_batch_financial_escalation_still_allows_a_manual_held_exit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    first = _proposal(clock, symbol="MSFT")
    held_exit = _proposal(
        clock,
        proposal_id=UUID(int=17),
        side=Side.SELL,
        intent=Intent.EXIT,
        stop_price=None,
        source=ProposalSource.MANUAL,
    )
    book = _snapshot(clock, equity=Decimal(9000), positions={"AAPL": _position(1)})
    result = cro.evaluate_batch(
        (first, held_exit),
        book,
        {"MSFT": _market(clock)},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert (
        result[0].decision == Decision.VETOED
        and result[0].recommended_state == SystemState.REDUCE_ONLY
    )
    assert result[1].decision == Decision.APPROVED
    assert [row.rule_id for row in result[1].results] == ["CRO-01", "CRO-02"]
    assert result[1].results[1].message == "reduction fits fresh held unreserved shares"


def test_CRO_02_bad_exit_identity_data_does_not_discard_a_later_valid_held_exit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    first = _proposal(
        clock, side=Side.SELL, intent=Intent.EXIT, stop_price=None, source=ProposalSource.MANUAL
    ).model_copy(update={"symbol": []})
    held_exit = _proposal(
        clock,
        proposal_id=UUID(int=17),
        side=Side.SELL,
        intent=Intent.EXIT,
        stop_price=None,
        source=ProposalSource.MANUAL,
    )
    result = cro.evaluate_batch(
        (first, held_exit),
        _snapshot(clock, positions={"AAPL": _position(1)}),
        {},
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert (
        result[0].decision == Decision.VETOED and result[0].recommended_state == SystemState.HALTED
    )
    assert result[0].proposal_id == first.proposal_id
    assert result[1].decision == Decision.APPROVED and result[1].results[1].passed


@pytest.mark.parametrize("case", ["zero_equity_drawdown", "zero_high_water", "zero_equity_daily"])
def test_CRO_09_10_invalid_financial_baselines_keep_exact_rule_audits_under_strict_rounding(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    case: str,
) -> None:
    from decimal import Rounded, localcontext

    options: dict[str, Any] = {"broker_account_type": "CASH"}
    values: dict[str, Any] = {
        "equity": Decimal(0),
        "high_water_mark": Decimal(1000),
        "day_start_equity": Decimal(1000),
    }
    long_baseline = Decimal("1000." + "0" * 76)
    if case == "zero_equity_drawdown":
        options["dd_reduce_only"] = Decimal("0.10" + "0" * 48)
        values["high_water_mark"] = long_baseline
    elif case == "zero_equity_daily":
        options["daily_loss_limit"] = Decimal("0.02" + "0" * 48)
        values["day_start_equity"] = long_baseline
    else:
        values.update(equity=Decimal(1), high_water_mark=Decimal("0E-10000"))
    cro = ChiefRiskOfficer(Settings(**options), _registry(), risk_calendar)
    book = _snapshot(clock, **values)
    with localcontext() as context:
        context.traps[Rounded] = True
        result = cro.evaluate(
            _proposal(clock),
            book,
            _market(clock),
            SystemState.RUNNING,
            clock.now(),
            deployable=_capital(),
        )
    rows = {row.rule_id: row for row in result.results}
    assert rows["CRO-09"].observed == ("0" if case == "zero_high_water" else "1")
    assert rows["CRO-10"].observed == ("0.999" if case == "zero_high_water" else "1")
    assert not rows["CRO-09"].passed and not rows["CRO-10"].passed
    assert result.decision == Decision.VETOED and result.recommended_state == SystemState.HALTED


def test_CRO_03_advisory_keeps_an_already_approved_quantity_under_subnormal_traps(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    """A failed smaller probe cannot invalidate this fully approved eight-share order."""
    from decimal import Subnormal, localcontext

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(clock, qty=8)
    book = _snapshot(clock)
    quote = _market(clock)
    with localcontext() as context:
        context.Emin = 0
        context.traps[Subnormal] = True
        approved = cro.evaluate(
            order, book, quote, SystemState.RUNNING, clock.now(), deployable=_capital()
        )
        assert approved.decision == Decision.APPROVED
        assert cro.max_allowed_qty(order, book, quote, clock.now()) == 8


@pytest.mark.parametrize("precision", [6, 28, 80])
@pytest.mark.parametrize(
    "rounding", ["ROUND_HALF_EVEN", "ROUND_DOWN", "ROUND_UP", "ROUND_FLOOR", "ROUND_CEILING"]
)
@pytest.mark.parametrize("exponents", [(0, 0), (0, 999999), (-999999, 999999)])
def test_owned_context_preserves_eight_share_approval_and_caller_state(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    precision: int,
    rounding: str,
    exponents: tuple[int, int],
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order, book, market = _proposal(clock, qty=8), _snapshot(clock), _market(clock)
    capital = _capital()
    with localcontext() as caller:
        caller.prec, caller.rounding = precision, rounding
        caller.Emin, caller.Emax = exponents
        for signal in [Subnormal, Rounded, Inexact, Overflow, DivisionByZero]:
            caller.traps[signal] = True
        caller.clear_flags()
        before = (str(caller), dict(caller.flags), dict(caller.traps))
        verdict = cro.evaluate(
            order, book, market, SystemState.RUNNING, clock.now(), deployable=capital
        )
        assert verdict.decision == Decision.APPROVED
        assert cro.max_allowed_qty(order, book, market, clock.now()) == 8
        assert (str(caller), dict(caller.flags), dict(caller.traps)) == before


@pytest.mark.parametrize(
    "requested,expected", [(1, 1), (4, 4), (5, 5), (8, 8), (9, 9), (10, 10), (11, 10)]
)
def test_owned_context_risk_budget_boundary_and_whole_shares(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    requested: int,
    expected: int,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(clock, qty=requested, stop_price=Decimal("90.20"))
    with localcontext() as caller:
        caller.Emin = 0
        caller.traps[Subnormal] = True
        result = cro.max_allowed_qty(order, _snapshot(clock), _market(clock), clock.now())
    assert type(result) is int and result == expected


@pytest.mark.parametrize("signal", [DivisionByZero, Overflow, Inexact])
def test_owned_context_arithmetic_fault_never_searches_past_unverified_probe(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    signal: type[DecimalException],
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    probes: list[int] = []
    risk = cro._risk

    def fail(proposal: TradeProposal, snapshot: PortfolioSnapshot) -> RuleResult:
        probes.append(proposal.qty)
        if proposal.qty == 4:
            raise signal("Injected exact four-share arithmetic fault")
        return risk(proposal, snapshot)

    monkeypatch.setattr(cro, "_risk", fail)
    assert (
        cro.max_allowed_qty(_proposal(clock, qty=8), _snapshot(clock), _market(clock), clock.now())
        == 0
    )
    assert probes == [4]
    assert f"risk_sizing_fault reason={signal.__name__}" in caplog.text


@pytest.mark.parametrize("kind", ["raised", "empty_verdict"])
def test_owned_context_unverifiable_evaluator_never_becomes_a_sizing_boundary(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    kind: str,
) -> None:
    from backend.domain.models import Verdict

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(clock, qty=8)
    probes: list[int] = []
    evaluate = cro.evaluate

    def fault(candidate: TradeProposal, *args: Any, **kwargs: Any) -> Verdict:
        probes.append(candidate.qty)
        if candidate.qty != 4:
            return evaluate(candidate, *args, **kwargs)
        if kind == "raised":
            raise Overflow("Injected sizing fault")
        return Verdict(
            proposal_id=order.proposal_id,
            decision=Decision.VETOED,
            results=(),
            config_hash=cro.config.config_hash,
            snapshot_hash="0" * 64,
            evaluated_at=clock.now(),
            recommended_state=SystemState.HALTED,
        )

    monkeypatch.setattr(cro, "evaluate", fault)
    assert cro.max_allowed_qty(order, _snapshot(clock), _market(clock), clock.now()) == 0
    assert probes == [4]
    reason = "Overflow" if kind == "raised" else "unverifiable evidence"
    assert f"risk_sizing_fault reason={reason}" in caplog.text


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("daily_loss", "CRO-10: session entry-block evidence must be boolean"),
        ("market", "CRO-02: entry requires verified market context"),
    ],
)
def test_CRO_fault_audit_keeps_exact_integrity_exception_and_fail_closed_verdict(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    expected: str,
) -> None:
    from backend.risk import risk_cro

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    errors: list[DataIntegrityError] = []

    def observe_error(message: object) -> DataIntegrityError:
        error = DataIntegrityError(cast(str, message))
        errors.append(error)
        return error

    monkeypatch.setattr(risk_cro, "DataIntegrityError", observe_error)
    options: dict[str, Any] = {"daily_loss_blocked": None} if fault == "daily_loss" else {}
    verdict = cro.evaluate(
        _proposal(clock),
        _snapshot(clock),
        None if fault == "market" else _market(clock),
        SystemState.RUNNING,
        clock.now(),
        **options,
    )
    assert len(errors) == 1 and type(errors[0]) is DataIntegrityError
    assert str(errors[0]) == expected
    assert verdict.decision == Decision.VETOED
    assert verdict.recommended_state == SystemState.HALTED
    assert verdict.snapshot_hash == "0" * 64
    assert [(row.rule_id, row.passed, row.observed) for row in verdict.results] == [
        (f"CRO-{number:02d}", False, "DataIntegrityError") for number in range(1, 15)
    ]


def test_CRO_reconstructed_policy_preserves_exact_risk_budget_and_cap_audit(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    settings = Settings(
        broker_account_type="CASH",
        max_risk_per_trade=Decimal("0.010000000000000000000000000001"),
        sector_caps={"Information Technology": Decimal("0.350000000000000000000000000001")},
    )
    cro = ChiefRiskOfficer(settings, _registry(), risk_calendar)
    assert cro.config is not settings
    assert cro.config.max_risk_per_trade == Decimal("0.010000000000000000000000000001")
    assert cro.config.config_hash == settings.config_hash
    assert cro.config.sector_caps["Information Technology"] == Decimal(
        "0.350000000000000000000000000001"
    )
    verdict = cro.evaluate(
        _proposal(clock, qty=8),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert verdict.decision == Decision.APPROVED
    assert verdict.config_hash == settings.config_hash
    risk = next(row for row in verdict.results if row.rule_id == "CRO-04")
    assert Decimal(risk.limit) == Decimal("100.00000000000000000000000001000000")


def test_CRO_policy_import_keeps_decimal_budget_before_json_export_formatting(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    from pydantic import SerializationInfo, field_serializer

    class ExportablePolicy(Settings):
        @field_serializer("max_risk_per_trade")
        def export_budget(self, value: Decimal, info: SerializationInfo) -> Decimal | float:
            return value if info.mode == "python" else float(value)

    # A Python policy snapshot must retain its exact budget even when an
    # external JSON export uses ordinary numeric formatting.
    policy = ExportablePolicy(broker_account_type="CASH")
    officer = ChiefRiskOfficer(policy, _registry(), risk_calendar)
    assert type(officer.config.max_risk_per_trade) is Decimal
    assert officer.config.max_risk_per_trade == Decimal("0.01")
    assert officer.config.config_hash == Settings(broker_account_type="CASH").config_hash
    result = officer.evaluate(
        _proposal(clock, qty=8),
        _snapshot(clock),
        _market(clock),
        SystemState.RUNNING,
        clock.now(),
        deployable=_capital(),
    )
    assert result.decision == Decision.APPROVED


@pytest.mark.parametrize("fault", ["missing", "duplicate", "warning"])
def test_CRO_incomplete_sizing_evidence_stops_without_guessing_a_lower_quantity(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fault: str,
) -> None:
    from backend.domain.models import Verdict

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    evaluate = cro.evaluate
    probes: list[int] = []

    def incomplete(candidate: TradeProposal, *args: Any, **kwargs: Any) -> Verdict:
        probes.append(candidate.qty)
        verdict = evaluate(candidate, *args, **kwargs)
        if candidate.qty != 4:
            return verdict
        rows = list(verdict.results)
        if fault == "missing":
            rows = [row for row in rows if row.rule_id != "CRO-05"]
        elif fault == "duplicate":
            rows = [row if row.rule_id != "CRO-05" else rows[3] for row in rows]
        else:
            rows = [
                row.model_copy(update={"severity": Severity.WARN})
                if row.rule_id == "CRO-05"
                else row
                for row in rows
            ]
        return verdict.model_copy(update={"results": tuple(rows)})

    monkeypatch.setattr(cro, "evaluate", incomplete)
    assert (
        cro.max_allowed_qty(_proposal(clock, qty=8), _snapshot(clock), _market(clock), clock.now())
        == 0
    )
    assert probes == [4]
    assert "risk_sizing_fault reason=incomplete sizing evidence" in caplog.text


@pytest.mark.parametrize("cash", ["0", "99.99", "499.99", "500", "749.99", "750"])
def test_CRO_empty_pending_book_never_spends_cash_reserves_or_rounds_shares_up(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    cash: str,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(clock, qty=8)
    book = _snapshot(clock, cash=Decimal(cash), settled_cash=Decimal(cash))
    # $500 must remain untouched; share costs are $100, including fractional
    # cash boundaries where rounding up would break the reserve.
    expected = 0 if cash in {"0", "99.99", "499.99", "500"} else 2
    assert cro.max_allowed_qty(order, book, _market(clock), clock.now()) == expected
    verdict = cro.evaluate(
        order, book, _market(clock), SystemState.RUNNING, clock.now(), deployable=_capital()
    )
    row = next(row for row in verdict.results if row.rule_id == "CRO-06")
    assert row.observed == f"gross=800.00; positions=1; cash={Decimal(cash) - Decimal(800):.2f}"


def test_CRO_zero_cash_refusal_is_not_misreported_as_an_instrument_evaluation_fault(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order = _proposal(clock, symbol="ZZZZ", qty=8)
    book = _snapshot(clock, cash=Decimal(0), settled_cash=Decimal(0))
    assert cro.max_allowed_qty(order, book, _market(clock), clock.now()) == 0
    assert caplog.records == []


def test_owned_context_ignores_poisoned_process_defaults_and_preserves_caller(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
) -> None:
    from decimal import DefaultContext, getcontext

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    order, book, market, capital = (
        _proposal(clock, qty=8),
        _snapshot(clock),
        _market(clock),
        _capital(),
    )
    tiny_budget = ChiefRiskOfficer(
        Settings(broker_account_type="CASH", max_risk_per_trade=Decimal("1E-100")),
        _registry(),
        risk_calendar,
    )
    saved = DefaultContext.copy()
    caller = str(getcontext())
    try:
        DefaultContext.prec = 6
        DefaultContext.rounding = "ROUND_DOWN"
        DefaultContext.Emin = DefaultContext.Emax = 0
        DefaultContext.capitals = 0
        DefaultContext.clamp = 1
        for signal in DefaultContext.traps:
            DefaultContext.traps[signal] = True
        result = cro.evaluate(
            order, book, market, SystemState.RUNNING, clock.now(), deployable=capital
        )
        assert result.decision == Decision.APPROVED
        assert cro.max_allowed_qty(order, book, market, clock.now()) == 8
        refused = tiny_budget.evaluate(
            order, book, market, SystemState.RUNNING, clock.now(), deployable=capital
        )
        assert refused.decision == Decision.VETOED
        assert next(row for row in refused.results if row.rule_id == "CRO-04").limit == "1.0000E-96"
        assert str(getcontext()) == caller
    finally:
        DefaultContext.prec = saved.prec
        DefaultContext.rounding = saved.rounding
        DefaultContext.Emin = saved.Emin
        DefaultContext.Emax = saved.Emax
        DefaultContext.capitals = saved.capitals
        DefaultContext.clamp = saved.clamp
        DefaultContext.flags.update(saved.flags)
        DefaultContext.traps.update(saved.traps)


@pytest.mark.parametrize(
    "context_case",
    [
        *[
            (rounding, precision, -999999, None)
            for rounding in [
                "ROUND_HALF_EVEN",
                "ROUND_DOWN",
                "ROUND_UP",
                "ROUND_FLOOR",
                "ROUND_CEILING",
            ]
            for precision in [6, 28]
        ],
        *[
            ("ROUND_HALF_EVEN", 28, emin, Subnormal if trap else None)
            for emin in [0, -1, -2]
            for trap in [False, True]
        ],
        *[("ROUND_HALF_EVEN", 28, -999999, signal) for signal in [Rounded, Inexact, Underflow]],
    ],
)
@pytest.mark.parametrize("scenario", ["base", "equity2000", "cash500", "equity9999"])
@pytest.mark.parametrize("stop", ["95", "90.2", "99.99"])
def test_owned_context_7296_case_matrix_matches_exhaustive_maximum(
    clock: FrozenClock,
    risk_calendar: MarketCalendar,
    context_case: tuple[str, int, int, type[DecimalException] | None],
    scenario: str,
    stop: str,
) -> None:
    """19 contexts x 4 books x 3 stops x 32 requests; no oversizing or holes."""
    from backend.risk.risk_cro import SIZING_RULES

    cro = ChiefRiskOfficer(Settings(broker_account_type="CASH"), _registry(), risk_calendar)
    values: dict[str, Any] = {}
    if scenario in {"equity2000", "equity9999"}:
        equity = Decimal(scenario.removeprefix("equity"))
        values.update(equity=equity, cash=equity, high_water_mark=equity, day_start_equity=equity)
    elif scenario == "cash500":
        values["cash"] = Decimal(500)
    book, market, capital = _snapshot(clock, **values), _market(clock), _capital()
    order = _proposal(clock, qty=32, stop_price=Decimal(stop))
    eligible: list[int] = []
    with localcontext() as caller:
        caller.rounding, caller.prec, caller.Emin = context_case[:3]
        caller.Emax = 999999
        if context_case[3] is not None:
            caller.traps[context_case[3]] = True
        seen_failure = False
        for qty in range(1, 33):
            candidate = order.model_copy(update={"qty": qty})
            verdict = cro.evaluate(
                candidate, book, market, SystemState.RUNNING, clock.now(), deployable=capital
            )
            evidence = [row for row in verdict.results if row.rule_id in SIZING_RULES]
            passed = len(evidence) == len(SIZING_RULES) and all(row.passed for row in evidence)
            if passed:
                assert not seen_failure, "Pinned sizing eligibility must be monotonic"
                eligible.append(qty)
            else:
                seen_failure = True
            expected = max(eligible, default=0)
            actual = cro.max_allowed_qty(candidate, book, market, clock.now())
            assert type(actual) is int and actual == expected
            assert 0 <= actual <= qty
            assert actual == 0 or actual in eligible
