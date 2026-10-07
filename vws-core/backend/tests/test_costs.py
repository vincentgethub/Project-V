"""CM goldens: independent arithmetic, exact boundaries and forged ingress."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.core.config import CostModelConfig, SpreadFloorsConfig
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.fee_schedule import load_fee_schedule
from backend.domain.models import Side
from backend.domain.tax_profile import TaxProfile
from backend.evaluation.costs import (
    CostContext,
    CostOrder,
    FeeBreakdown,
    FeeSchedule,
    FillResult,
    ObservedFees,
    after_tax_year,
    estimate_fill,
    fees,
    half_spread,
)

D = Decimal
FILL_DAY = date(2026, 9, 16)
DECISION_DAY = date(2026, 9, 15)
ENTRY_LEVEL = D(101)


def bar(**values: Any) -> Bar:
    return Bar.model_validate(
        {
            "timestamp": datetime(2026, 9, 16, 4, tzinfo=UTC),
            "open": D(100),
            "high": D(120),
            "low": D(90),
            "close": D(100),
            "volume": 10000,
            **values,
        }
    )


def context(**values: Any) -> CostContext:
    return CostContext.model_validate(
        {"median_dollar_volume_20": D(500_000_000), "atr14": D(2), **values}
    )


def order(kind: str = "ENTRY", level: Decimal | None = ENTRY_LEVEL, **values: Any) -> CostOrder:
    return CostOrder.model_validate(
        {
            "side": Side.BUY if kind == "ENTRY" else Side.SELL,
            "kind": kind,
            "qty": 100,
            "level": level,
            "decision_session": DECISION_DAY,
            **values,
        }
    )


@pytest.fixture
def schedule() -> FeeSchedule:
    return load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")


def test_CM_exact_arithmetic_independent_of_ambient_context(schedule: FeeSchedule) -> None:
    with localcontext() as precision:
        precision.prec = 2
        checked = context(atr14=D("1000.01"))
        result = fees(Side.SELL, 100, D(100), FILL_DAY, schedule=schedule)
        assert checked.atr14 == D("1000.01") and result.total == D("0.24")
    row = schedule.rows[0].model_copy(update={"cat_per_share": D("0.0001" + "0" * 115 + "1")})
    exact = schedule.model_copy(update={"rows": (row,)})
    # A positive increment beyond ordinary Decimal precision still rounds UP.
    assert fees(Side.BUY, 100, D(100), FILL_DAY, schedule=exact).cat == D("0.02")
    for unsupported in (D("1e-129"), D("0." + "1" * 129)):
        with pytest.raises(ValidationError):
            CostContext(
                median_dollar_volume_20=D(1), atr14=D(1), measured_half_spread_bps=unsupported
            )


@pytest.mark.parametrize(
    "volume,floor",
    [
        (D(500_000_000), D(2)),
        (D("499999999.99"), D(5)),
        (D(50_000_000), D(5)),
        (D("49999999.99"), D(15)),
        (D(0), D(15)),
        (None, D(15)),
    ],
)
def test_CM_01_exact_liquidity_boundaries_and_unknown(
    volume: Decimal | None, floor: Decimal
) -> None:
    spread, notes = half_spread(context(median_dollar_volume_20=volume))
    assert spread == floor and bool(notes) == (volume is None)
    assert half_spread(context(median_dollar_volume_20=volume, measured_half_spread_bps=D(20)))[
        0
    ] == D(20)


@pytest.mark.parametrize(
    "opening,limit,low,expected,reason",
    [
        ("100", "101", "99", "100.02", "OPEN_WITH_SPREAD"),
        ("100.99", "101", "100.98", "101", "OPEN_WITH_SPREAD"),
        ("101", "101", "100", "101", "OPEN_WITH_SPREAD"),
        ("102", "101", "101", None, "NOT_TOUCHED"),
        ("102", "101", "100.99", "101", "TRADE_THROUGH"),
        ("102", "101", "101.01", None, "NOT_TOUCHED"),
    ],
)
def test_CM_02_touch_vs_one_cent_trade_through(
    opening: str,
    limit: str,
    low: str,
    expected: str | None,
    reason: str,
) -> None:
    result = estimate_fill(
        order(level=D(limit)), bar(open=D(opening), low=D(low), close=D(opening)), context()
    )
    assert result.price == (None if expected is None else D(expected))
    assert result.qty == (0 if expected is None else 100) and result.reason == reason


@pytest.mark.parametrize(
    "volume,qty,status",
    [(99, 0, "NOT_FILLED"), (100, 1, "PARTIAL"), (9999, 99, "PARTIAL"), (10000, 100, "FILLED")],
)
def test_CM_02_whole_share_participation_cap(volume: int, qty: int, status: str) -> None:
    result = estimate_fill(order(), bar(volume=volume), context())
    assert (result.status, result.qty) == (status, qty)
    assert result.price == (D("100.02") if qty else None)


@pytest.mark.parametrize(
    "kind,level,opening,high,low,expected,reason",
    [
        ("STOP", "95", "100", "101", "95", "94.88", "STOP"),
        ("STOP", "95", "90", "96", "89", "89.98", "GAP_STOP"),
        ("STOP", "95", "95", "96", "94", "94.88", "STOP"),
        ("STOP", "95", "100", "101", "95.01", None, "NOT_TOUCHED"),
        ("TARGET", "110", "100", "110", "99", None, "NOT_TOUCHED"),
        ("TARGET", "110", "100", "110.01", "99", "110", "TARGET"),
        ("TIME", None, "100", "101", "99", "99.98", "TIME"),
        ("SIGNAL", None, "100", "101", "99", "99.98", "SIGNAL"),
    ],
)
def test_CM_03_conservative_stop_target_and_next_open_exit(
    kind: str,
    level: str | None,
    opening: str,
    high: str,
    low: str,
    expected: str | None,
    reason: str,
) -> None:
    result = estimate_fill(
        order(kind, None if level is None else D(level)),
        bar(open=D(opening), high=D(high), low=D(low), close=D(opening)),
        context(),
    )
    assert result.price == (None if expected is None else D(expected)) and result.reason == reason


@pytest.mark.parametrize(
    "kind,level", [("ENTRY", D(101)), ("TIME", None), ("SIGNAL", None), ("STOP", D(95))]
)
def test_CM_QV_06_no_look_ahead_or_same_session_close_fills(
    kind: str, level: Decimal | None
) -> None:
    checked = order(kind, level, decision_session=FILL_DAY if kind != "STOP" else date(2026, 9, 17))
    with pytest.raises(DataIntegrityError, match="next session"):
        estimate_fill(checked, bar(), context())


@pytest.mark.parametrize("fault", ["volume", "ohlc", "context", "order", "nonpositive_exit"])
def test_CM_DQ_03_malformed_or_impossible_prices_never_become_outcomes(fault: str) -> None:
    sample, facts, intent = bar(), context(), order()
    if fault == "volume":
        sample = sample.model_copy(update={"volume": 0})
    elif fault == "ohlc":
        sample = sample.model_copy(update={"high": D(1)})
    elif fault == "context":
        facts = facts.model_copy(update={"atr14": 2.0})
    elif fault == "order":
        intent = intent.model_copy(update={"qty": True})
    else:
        facts = context(measured_half_spread_bps=D(10000))
        intent = order("STOP", D(95))
    with pytest.raises(DataIntegrityError):
        estimate_fill(intent, sample, facts)


@pytest.mark.parametrize("values", [{"side": Side.SELL}, {"level": None}])
def test_CM_long_only_contract_requires_exact_entry_level(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        order(**values)


def test_CM_result_contract_rejects_oversized_or_inconsistent_fill() -> None:
    result = estimate_fill(order(), bar(), context())
    for values in ({"qty": 101}, {"status": "PARTIAL"}, {"price": None}):
        with pytest.raises(ValidationError):
            FillResult.model_validate(result.model_copy(update=values))
    with pytest.raises(ValidationError):
        context(atr14=D("2.001"))


@pytest.mark.parametrize(
    "side,day,total,taf",
    [
        (Side.SELL, date(2026, 9, 15), "0.14", "0.02"),
        (Side.SELL, date(2026, 9, 30), "0.14", "0.02"),
        (Side.SELL, date(2026, 10, 1), "0.12", "0"),
        (Side.SELL, date(2026, 10, 15), "0.12", "0"),
        (Side.SELL, date(2026, 12, 31), "0.12", "0"),
        (Side.SELL, date(2027, 1, 1), "0.14", "0.02"),
        (Side.BUY, date(2026, 9, 15), "0.01", "0"),
    ],
)
def test_CM_04_hand_computed_dated_fees(
    schedule: FeeSchedule, side: Side, day: date, total: str, taf: str
) -> None:
    result = fees(side, 100, D(50), day, schedule=schedule)
    assert result.total == D(total) and result.taf == D(taf)
    assert result.sec == (D("0.11") if side == Side.SELL else 0) and result.cat == D("0.01")
    assert result.source == "MODELED" and "unverified" in result.notes[0]


def test_CM_04_cap_approximate_old_dates_review_and_deterministic_hash(
    schedule: FeeSchedule,
) -> None:
    result = fees(Side.SELL, 100000, D(50), DECISION_DAY, schedule=schedule)
    assert (result.taf, result.sec, result.cat, result.total) == (
        D("9.79"),
        D(103),
        D("0.30"),
        D("113.09"),
    )
    early = fees(Side.SELL, 100, D(50), date(2020, 1, 2), schedule=schedule)
    assert early.total == D("0.14") and any("predates" in note for note in early.notes)
    late = fees(Side.SELL, 100, D(50), date(2027, 1, 1), schedule=schedule)
    assert any("overdue" in note for note in late.notes)
    assert schedule.sha256 == FeeSchedule.model_validate(schedule).sha256
    assert schedule.sha256 != schedule.model_copy(update={"review_due": date(2027, 1, 2)}).sha256


@pytest.mark.parametrize(
    "which,value",
    [
        ("side", "SELL"),
        ("qty", 100.0),
        ("qty", True),
        ("qty", 0),
        ("price", D("50.001")),
        ("date", datetime(2026, 9, 15, tzinfo=UTC)),
    ],
)
def test_CM_04_invalid_fee_input_fails_closed(
    schedule: FeeSchedule, which: str, value: Any
) -> None:
    inputs: dict[str, Any] = {
        "side": Side.SELL,
        "qty": 100,
        "price": D(50),
        "trade_date": DECISION_DAY,
    }
    inputs["trade_date" if which == "date" else which] = value
    with pytest.raises(DataIntegrityError):
        fees(**inputs, schedule=schedule)


def test_CM_04_bad_schedule_and_unrounded_actual_fees_are_rejected(
    schedule: FeeSchedule, tmp_path: Path
) -> None:
    for values in (
        {"rows": (schedule.rows[1], schedule.rows[0])},
        {"review_due": date(2020, 1, 1)},
    ):
        with pytest.raises(DataIntegrityError):
            fees(Side.SELL, 100, D(50), DECISION_DAY, schedule=schedule.model_copy(update=values))
    with pytest.raises(ValidationError):
        FeeBreakdown(commission=D(0), sec=D("0.001"), taf=D(0), cat=D(0), source="BROKER")
    bad = tmp_path / "fees.yaml"
    bad.write_text("rows: []\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_fee_schedule(bad)


def test_CM_04_observed_fees_replace_only_same_account_mode_and_trade(
    schedule: FeeSchedule,
) -> None:
    account = uuid4()
    actual = ObservedFees(
        account_id=account,
        mode="PAPER",
        side=Side.SELL,
        qty=100,
        price=D(50),
        trade_date=DECISION_DAY,
        activity_ids=("synthetic-fee-1",),
        breakdown=FeeBreakdown(
            commission=D(0), sec=D("0.10"), taf=D("0.01"), cat=D("0.01"), source="BROKER"
        ),
    )
    result = fees(
        Side.SELL,
        100,
        D(50),
        DECISION_DAY,
        schedule=schedule,
        observed=actual,
        account_id=account,
        mode="PAPER",
    )
    assert result.total == D("0.12") and result.source == "BROKER"
    for values in (
        {"account_id": uuid4()},
        {"mode": "LIVE"},
        {"qty": 99},
        {"price": D(49)},
        {"trade_date": FILL_DAY},
        {"side": Side.BUY},
    ):
        with pytest.raises(DataIntegrityError):
            fees(
                Side.SELL,
                100,
                D(50),
                DECISION_DAY,
                schedule=schedule,
                observed=actual.model_copy(update=values),
                account_id=account,
                mode="PAPER",
            )
    for proof_values in (
        {"activity_ids": ("dup", "dup")},
        {"breakdown": actual.breakdown.model_copy(update={"source": "MODELED"})},
    ):
        with pytest.raises(DataIntegrityError):
            fees(
                Side.SELL,
                100,
                D(50),
                DECISION_DAY,
                schedule=schedule,
                observed=actual.model_copy(update=proof_values),
                account_id=account,
                mode="PAPER",
            )


def test_CM_05_after_tax_requires_all_rates_and_never_assumes_a_loss_credit() -> None:
    assert after_tax_year(D(1000), TaxProfile()) is None
    profile = TaxProfile(federal_st_rate=D("0.24"), federal_lt_rate=D("0.15"))
    assert after_tax_year(D(1000), profile) == D(760)
    assert after_tax_year(D(-1000), profile) == D(-760)
    assert after_tax_year(D(0), profile) == 0
    with pytest.raises(DataIntegrityError):
        after_tax_year(D(1000), profile.model_copy(update={"state_rate": D(1)}))
    with pytest.raises(DataIntegrityError):
        after_tax_year(D(1000), profile.model_copy(update={"federal_st_rate": 0.24}))


@pytest.mark.parametrize(
    "values",
    [
        {"max_participation": D("0.010001")},
        {"max_participation": D(0)},
        {"stop_slip_atr_frac": D("0.049999")},
        {"stop_slip_atr_frac": 0.05},
    ],
)
def test_CM_config_cannot_reduce_cost_or_raise_participation(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CostModelConfig.model_validate(values)


def test_CM_spread_floors_cannot_be_reduced_or_misordered() -> None:
    for values in (
        {"high": D("1.99")},
        {"mid": D("4.99")},
        {"low": D("14.99")},
        {"high": D(6), "mid": D(5)},
        {"low": D(1001)},
    ):
        with pytest.raises(ValidationError):
            SpreadFloorsConfig.model_validate(values)
