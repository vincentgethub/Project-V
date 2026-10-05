"""R-02/R-03/R-09/R-13: independent attacks on the Stage B risk boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast
from uuid import UUID

import pytest

from backend.core.config import Settings
from backend.core.errors import SafetyError
from backend.core.system_state import SystemState
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
    OpenOrder,
    PortfolioSnapshot,
    Position,
    ProposalSource,
    RuleResult,
    Side,
    TradeProposal,
    Verdict,
)
from backend.risk.risk_cro import ChiefRiskOfficer

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
PROPOSAL_ID = UUID("40000000-0000-0000-0000-000000000001")
SIGNAL_ID = UUID("40000000-0000-0000-0000-000000000002")


@pytest.fixture(scope="module")
def adversarial_calendar() -> MarketCalendar:
    """CRO-13: fixed exchange sessions, with no provider or wall-clock access."""
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def registry() -> InstrumentRegistry:
    """CRO-02/CRO-05: minimal explicit metadata for independent fixtures."""
    return InstrumentRegistry(
        (
            Instrument(
                symbol="AAPL",
                asset_class=AssetClass.STOCK,
                gics_sector="Information Technology",
                themes=(),
                is_leveraged=False,
                is_inverse=False,
                tradable=True,
            ),
        )
    )


def proposal(now: datetime = NOW, **changes: object) -> TradeProposal:
    """R-01/R-05/R-13: an otherwise eligible cent-priced proposal."""
    fields: dict[str, object] = {
        "proposal_id": PROPOSAL_ID,
        "signal_id": SIGNAL_ID,
        "account_id": "adversarial-paper",
        "symbol": "AAPL",
        "side": Side.BUY,
        "intent": Intent.ENTRY,
        "qty": 1,
        "limit_price": Decimal("100.00"),
        "stop_price": Decimal("95.00"),
        "target_price": Decimal("110.00"),
        "source": ProposalSource.SIGNAL,
        "created_at": now,
        "expires_at": now + timedelta(hours=1),
    }
    fields.update(changes)
    return TradeProposal.model_validate(fields)


def position(qty: int = 1) -> Position:
    """CRO-02/CRO-04: whole-share, cent-priced held inventory."""
    return Position(qty=qty, avg_cost=Decimal("95.00"), last_price=Decimal("100.00"))


def snapshot(now: datetime = NOW, **changes: object) -> PortfolioSnapshot:
    """CRO-09/CRO-10: explicit positive persisted baselines."""
    fields: dict[str, object] = {
        "account_id": "adversarial-paper",
        "account_type": AccountType.CASH,
        "as_of": now,
        "equity": Decimal("10000"),
        "cash": Decimal("10000"),
        "settled_cash": Decimal("10000"),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("10000"),
        "day_start_equity": Decimal("10000"),
    }
    fields.update(changes)
    return PortfolioSnapshot.model_validate(fields)


def market(now: datetime = NOW, **changes: object) -> MarketContext:
    """CRO-07/CRO-13: fresh quote; no guessed upcoming earnings date."""
    fields: dict[str, object] = {
        "last_price": Decimal("100.00"),
        "last_price_ts": now,
        "adv20_usd": Decimal("1000000"),
        "next_earnings_date": None,
        "status": MarketStatus.OK,
    }
    fields.update(changes)
    return MarketContext.model_validate(fields)


def funding() -> DeployableCapital:
    """CRO-12: exact independent buffer arithmetic, with no bank access."""
    return DeployableCapital(
        checking_used=Decimal("5000"),
        buffer=Decimal("1500"),
        reserved=Decimal("0"),
        deployable=Decimal("3500"),
        status=CapitalStatus.OK,
    )


def verdict(
    cro: ChiefRiskOfficer,
    trade: TradeProposal | None = None,
    book: PortfolioSnapshot | None = None,
    context: MarketContext | None = None,
    now: datetime = NOW,
) -> Verdict:
    """R-03: call the public pure gate with detached deterministic fixtures."""
    return cro.evaluate(
        trade or proposal(now),
        book or snapshot(now),
        context or market(now),
        SystemState.RUNNING,
        now,
        deployable=funding(),
    )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("qty", True),
        ("qty", Decimal("1")),
        ("limit_price", Decimal("100.001")),
        ("limit_price", 100.0),
        ("stop_price", Decimal("100.00")),
        ("intent", "UNRECOGNIZED"),
        ("source", "UNRECOGNIZED"),
        ("signal_id", None),
    ],
)
def test_R_02_R_13_forged_frozen_proposal_is_revalidated(
    adversarial_calendar: MarketCalendar, field: str, bad: object
) -> None:
    """R-02: frozen is no substitute for validation at a risk boundary."""
    # Deliberately mutate instance storage without invoking Pydantic validation.
    forged = proposal()
    forged.__dict__[field] = bad
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, trade=forged).decision == Decision.VETOED


@pytest.mark.parametrize("nested", ["position", "pending"])
def test_R_02_nested_instances_cannot_smuggle_invalid_inventory(
    adversarial_calendar: MarketCalendar, nested: str
) -> None:
    """R-02/CRO-02/CRO-06: revalidation reaches nested frozen instances."""
    if nested == "position":
        held = position()
        held.__dict__["qty"] = Decimal("1.5")
        book = snapshot()
        book.__dict__["positions"] = {"AAPL": held}
    else:
        pending = OpenOrder(symbol="AAPL", side=Side.BUY, qty=1, limit_price=Decimal("100.00"))
        pending.__dict__["qty"] = -1
        book = snapshot()
        book.__dict__["open_orders"] = (pending,)
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, book=book).decision == Decision.VETOED


def test_R_02_hard_ceiling_cannot_be_bypassed_by_forged_settings(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-02: CRO construction rejects an unvalidated policy object."""
    config = Settings()
    config.__dict__["max_single_stock_weight"] = Decimal("1.00")
    with pytest.raises(SafetyError):
        ChiefRiskOfficer(config, registry(), adversarial_calendar)


def test_R_02_CRO_05_low_precision_cannot_accept_incomplete_etf_weights() -> None:
    """CRO-05: rounded weight sums cannot erase uncovered ETF exposure."""
    etf = Instrument(
        symbol="SPY",
        asset_class=AssetClass.BROAD_ETF,
        gics_sector="Information Technology",
        themes=(),
        is_leveraged=False,
        is_inverse=False,
        tradable=True,
    )
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(SafetyError):
            InstrumentRegistry(
                (etf,),
                {
                    "SPY": {
                        "Information Technology": Decimal("0.335"),
                        "Financials": Decimal("0.664"),
                    }
                },
            )


@pytest.mark.parametrize("seconds", [0, 1])
def test_R_02_proposal_expiry_is_exclusive_at_exact_equality(
    adversarial_calendar: MarketCalendar, seconds: int
) -> None:
    """R-02/R-14: expiration equality never permits an approval."""
    trade = proposal(
        created_at=NOW - timedelta(hours=1), expires_at=NOW - timedelta(seconds=seconds)
    )
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, trade=trade).decision == Decision.VETOED


def test_R_02_future_creation_and_inventory_cannot_be_approved(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-02/R-05: an aware UTC timestamp can still be unverifiable future data."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert (
        verdict(cro, trade=proposal(created_at=NOW + timedelta(seconds=1))).decision
        == Decision.VETOED
    )
    assert verdict(cro, book=snapshot(as_of=NOW + timedelta(seconds=1))).decision == Decision.VETOED


def test_R_02_R_09_stale_inventory_does_not_prove_a_valid_exit(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-09: only verified held inventory establishes the valid-exit exception."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None, target_price=None)
    book = snapshot(as_of=NOW - timedelta(seconds=61), positions={"AAPL": position()})
    assert verdict(cro, trade=trade, book=book).decision == Decision.VETOED


@pytest.mark.parametrize("field", ["high_water_mark", "day_start_equity"])
def test_R_02_CRO_09_CRO_10_zero_baseline_never_resets_risk(
    adversarial_calendar: MarketCalendar, field: str
) -> None:
    """CRO-09/CRO-10: first-run baselines must be initialized outside the rules."""
    book = snapshot()
    book.__dict__[field] = Decimal("0")
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert verdict(cro, book=book).decision == Decision.VETOED


def test_CRO_04_pending_same_symbol_buys_reserve_stop_risk(
    adversarial_calendar: MarketCalendar,
) -> None:
    """CRO-04: pending additions cannot spend the same stop-risk budget twice."""
    cro = ChiefRiskOfficer(
        Settings(max_single_stock_weight=Decimal("0.20")), registry(), adversarial_calendar
    )
    trade = proposal(intent=Intent.ADD, stop_price=Decimal("90.00"))
    clear = snapshot(positions={"AAPL": position()})
    clear_result = next(
        result
        for result in verdict(cro, trade=trade, book=clear).results
        if result.rule_id == "CRO-04"
    )
    assert clear_result.passed
    reserved = snapshot(
        positions={"AAPL": position()},
        open_orders=(
            OpenOrder(symbol="AAPL", side=Side.BUY, qty=8, limit_price=Decimal("100.00")),
        ),
    )
    result = verdict(cro, trade=trade, book=reserved)
    risk = next(item for item in result.results if item.rule_id == "CRO-04")
    assert not risk.passed
    assert result.decision == Decision.VETOED


def test_CRO_03_to_08_sizing_requires_complete_rule_evidence(
    adversarial_calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-02: all(empty) must never turn missing sizing evidence into capacity."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)

    def missing_rules(*args: object, **kwargs: object) -> tuple[RuleResult, ...]:
        return ()

    monkeypatch.setattr(cro, "_rules", missing_rules)
    assert cro.max_allowed_qty(proposal(), snapshot(), market(), NOW) == 0


@pytest.mark.parametrize(
    "earnings,blocked",
    [
        (date(2026, 11, 26), True),
        (date(2026, 11, 27), True),
        (date(2026, 11, 30), True),
        (date(2026, 12, 1), False),
    ],
)
def test_CRO_13_earnings_uses_sessions_across_holiday_and_early_close(
    adversarial_calendar: MarketCalendar, earnings: date, blocked: bool
) -> None:
    """CRO-13: Thanksgiving and the shortened Friday do not count as extra days."""
    now = datetime(2026, 11, 25, 16, tzinfo=UTC)
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    result = verdict(cro, context=market(now, next_earnings_date=earnings), now=now)
    earnings_result = next(item for item in result.results if item.rule_id == "CRO-13")
    assert earnings_result.passed == (not blocked)
    assert adversarial_calendar.session_close(date(2026, 11, 27)).hour == 18


def test_R_02_CRO_13_out_of_range_earnings_calendar_fails_closed(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-02/CRO-13: an unverifiable session distance is never favorable evidence."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    assert (
        verdict(cro, context=market(next_earnings_date=date(2035, 1, 2))).decision
        == Decision.VETOED
    )


def test_R_09_manual_exit_ignores_irrelevant_entry_provider_inputs(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-09: bad bank/market inputs cannot trap a verified manual liquidation."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(
        symbol="UNKNOWN",
        side=Side.SELL,
        intent=Intent.EXIT,
        stop_price=None,
        target_price=None,
        source=ProposalSource.MANUAL,
    )
    book = snapshot(positions={"UNKNOWN": position()})
    result = cro.evaluate(
        trade,
        book,
        cast(MarketContext, object()),
        SystemState.HALTED,
        NOW,
        deployable=cast(DeployableCapital, object()),
    )
    assert result.decision == Decision.APPROVED
    assert tuple(item.rule_id for item in result.results) == ("CRO-01", "CRO-02")


def test_R_09_batch_exit_does_not_require_a_market_mapping(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-09: the batch helper preserves the same valid-exit contract."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(side=Side.SELL, intent=Intent.EXIT, stop_price=None, target_price=None)
    results = cro.evaluate_batch(
        (trade,), snapshot(positions={"AAPL": position()}), {}, SystemState.RUNNING, NOW
    )
    assert results[0].decision == Decision.APPROVED


def test_R_03_R_04_ambient_decimal_precision_does_not_change_risk(
    adversarial_calendar: MarketCalendar,
) -> None:
    """R-03/R-04: unrelated caller math cannot round a boundary into approval."""
    cro = ChiefRiskOfficer(Settings(), registry(), adversarial_calendar)
    trade = proposal(qty=10, stop_price=Decimal("90.20"))
    exact = verdict(cro, trade=trade)
    with localcontext() as context:
        context.prec = 2
        limited = verdict(cro, trade=trade)
    assert limited == exact
    assert exact.decision == Decision.APPROVED
