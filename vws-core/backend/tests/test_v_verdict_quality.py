"""GV/XA/DQ: readiness boundaries, cost increases and same-vendor warnings."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import VerdictConfig
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.feed_crosscheck import flagged
from backend.data.feed_crosscheck import record as crosscheck
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import MarketStatus, Side
from backend.evaluation.fill_quality import FillQuality, edge_drift, monthly
from backend.evaluation.verdict import VerdictInputs, evaluate, latest_ready, record
from backend.ops.trading_controls import ControlScope
from backend.tests.test_outcomes_history import bar

D = Decimal


def inputs(clock: FrozenClock, **changes: Any) -> VerdictInputs:
    days = tuple(date(2026, 6, 1) + timedelta(days=i) for i in range(60))
    return VerdictInputs.model_validate(
        {
            "scope": ControlScope(account_id="offline-paper", environment="PAPER"),
            "as_of": clock.now(),
            "source": "AUTO_PAPER",
            "evidence_sha256": "a" * 64,
            "config_sha256": "b" * 64,
            "r_multiples": (D(1),) * 45 + (D(-1),) * 5,
            "sessions": days,
            "drawdown": D("0.10"),
            "reduce_only_hit": False,
            "sharpe": D(0),
            "spy_total_return_sharpe": D("0.2"),
            "recent_fault_free_sessions": 20,
            "drill_at": clock.now() - timedelta(days=31),
            "security_green": True,
            "playbook_grades": (("TREND_50EMA", "WORKING"),),
            "edge_drift": False,
            "unresolved_reconciliation": False,
            "panic_this_month": False,
            "circuit_breaker_halts_this_month": 0,
            **changes,
        }
    )


def test_GV_02_READY_boundaries_and_plain_english_disclaimer(clock: FrozenClock) -> None:
    result = evaluate(inputs(clock), VerdictConfig())
    assert result.status == "READY" and result.unmet == ()
    assert (
        "Actual AUTO_PAPER" in result.text() and "not indicative of future returns" in result.text()
    )
    assert type(result).recorded(result.model_dump(mode="json")) == result


@pytest.mark.parametrize(
    "field, value",
    [
        ("r_multiples", (D(1),) * 49),
        ("sessions", tuple(date(2026, 6, 1) + timedelta(days=i) for i in range(59))),
        ("r_multiples", (D(0),) * 50),
        ("drawdown", D("0.100001")),
        ("drawdown", None),
        ("reduce_only_hit", True),
        ("sharpe", D("-0.000001")),
        ("spy_total_return_sharpe", None),
        ("recent_fault_free_sessions", 19),
        ("security_green", False),
        ("playbook_grades", (("TREND_50EMA", "LOSING"),)),
        ("edge_drift", True),
        ("unresolved_reconciliation", None),
        ("panic_this_month", None),
        ("source", "UNAVAILABLE"),
        ("playbook_grades", ()),
        ("drill_at", None),
    ],
)
def test_GV_02_every_missing_prerequisite_stays_NOT_YET(
    clock: FrozenClock, field: str, value: Any
) -> None:
    result = evaluate(inputs(clock, **{field: value}), VerdictConfig())
    assert result.status == "NOT_YET" and result.unmet


def test_GV_02_drill_age_exact_boundary(clock: FrozenClock) -> None:
    assert (
        evaluate(
            inputs(clock, drill_at=clock.now() - timedelta(days=31, microseconds=1)),
            VerdictConfig(),
        ).status
        == "NOT_YET"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("r_multiples", (D(-1),) * 30),
        ("drawdown", D("0.12")),
        ("unresolved_reconciliation", True),
        ("panic_this_month", True),
        ("circuit_breaker_halts_this_month", 2),
    ],
)
def test_GV_03_each_STOP_trigger(clock: FrozenClock, field: str, value: Any) -> None:
    result = evaluate(inputs(clock, **{field: value}), VerdictConfig())
    assert result.status == "STOP" and result.stop_reasons


def test_GV_03_loss_count_boundary_and_missing_metrics_do_not_fabricate_STOP(
    clock: FrozenClock,
) -> None:
    assert evaluate(inputs(clock, r_multiples=(D(-1),) * 29), VerdictConfig()).status == "NOT_YET"


def test_GV_05_fresh_READY_bound_account_config_latest_and_age(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    assert not latest_ready(ledger, "offline-paper", "b" * 64)
    record(ledger, inputs(clock), VerdictConfig())
    assert latest_ready(ledger, "offline-paper", "b" * 64)
    assert not latest_ready(ledger, "different-paper", "b" * 64)
    assert not latest_ready(ledger, "offline-paper", "c" * 64)
    future = Ledger(engine, FrozenClock(clock.now() + timedelta(days=35, microseconds=1)))
    assert not latest_ready(future, "offline-paper", "b" * 64)
    record(ledger, inputs(clock, security_green=False), VerdictConfig())
    assert not latest_ready(ledger, "offline-paper", "b" * 64)


@pytest.mark.parametrize(
    "field,value",
    [
        ("reduce_only_hit", "false"),
        ("edge_drift", "no"),
        ("drawdown", float("nan")),
        ("sessions", (date(2027, 1, 1),)),
    ],
)
def test_GV_02_invalid_evidence_is_rejected(clock: FrozenClock, field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        inputs(clock, **{field: value})


def quality(clock: FrozenClock, identity: int, **changes: Any) -> FillQuality:
    return FillQuality.model_validate(
        {
            "scope": ControlScope(account_id="offline-paper", environment="PAPER"),
            "fill_id": UUID(int=identity),
            "symbol": "AAPL",
            "side": Side.BUY,
            "filled_at": clock.now(),
            "qty": 1,
            "fill_price": D("100.10"),
            "decision_price": D(100),
            "limit_price": D(101),
            "arrival_price": D(100),
            "arrival_at": clock.now() - timedelta(seconds=1),
            "modeled_price": D("100.02"),
            "model_half_spread_bps": D(2),
            "bucket": "HIGH",
            "is_stop": False,
            "unavailable_reason": None,
            **changes,
        }
    )


def test_XA_01_actual_slippage_and_monthly_calibration_only_raise_costs(clock: FrozenClock) -> None:
    rows = tuple(quality(clock, i + 1) for i in range(20))
    assert rows[0].arrival_slippage_bps == 10
    assert rows[0].model_slippage_bps == D("7.998400")
    report = monthly(rows[0].scope, "2026-09", "HIGH", rows, D(2))
    assert report.n == 20 and report.p50_bps == 10 and report.p90_bps == 10
    assert report.calibrated_half_spread_bps == 10
    assert (
        monthly(rows[0].scope, "2026-09", "HIGH", rows[:19], D(2)).calibrated_half_spread_bps == 2
    )
    assert monthly(rows[0].scope, "2026-09", "HIGH", rows, D(15)).calibrated_half_spread_bps == 15
    assert (
        monthly(
            rows[0].scope,
            "2026-09",
            "HIGH",
            tuple(quality(clock, i + 100, fill_price=D("100.04")) for i in range(20)),
            D(2),
        ).calibrated_half_spread_bps
        == 2
    )


def test_XA_01_unknown_arrival_is_UNVERIFIED_and_never_calibrates(clock: FrozenClock) -> None:
    row = quality(
        clock,
        1,
        arrival_price=None,
        arrival_at=None,
        unavailable_reason="Arrival quote unavailable",
    )
    result = monthly(row.scope, "2026-09", "HIGH", (row,), D(2))
    assert (
        result.n == 0
        and result.unavailable == 1
        and result.p50_bps is None
        and result.calibrated_half_spread_bps == 2
    )
    with pytest.raises(ValidationError):
        quality(clock, 2, arrival_at=clock.now() + timedelta(seconds=1))
    with pytest.raises(DataIntegrityError):
        monthly(row.scope, "2026-09", "HIGH", (row, row), D(2))


def test_XA_02_exact_fifth_percentile_boundary() -> None:
    assert edge_drift((D(1),) * 30, (D(1),) * 50) is False
    assert edge_drift((D("0.999999"),) * 30, (D(1),) * 50) is True
    assert edge_drift((D(0),) * 29, (D(1),) * 50) is None
    assert edge_drift((D(0),) * 30, ()) is None


@pytest.mark.parametrize(
    "sip,iex,atr,expected",
    [
        ("101", "100", "1", False),
        ("101.01", "100", "1", True),
        ("100", "99", "4", False),
        ("100", "98", "4", True),
    ],
)
def test_DQ_02_price_threshold_golden(sip: str, iex: str, atr: str, expected: bool) -> None:
    assert (
        flagged(
            bar(25, high=sip, low=sip, opening=sip, closing=sip),
            bar(25, high=iex, low=iex, opening=iex, closing=iex),
            D(atr),
        )
        is expected
    )


def test_DQ_02_volume_flag_three_consecutive_sessions_and_restart(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    calendar = MarketCalendar(start=date(2026, 1, 1), end=date(2027, 1, 1))
    for index, day in enumerate((24, 25, 28), 1):
        sip, iex = bar(day, volume=100), bar(day, volume=101)
        row = crosscheck(ledger, calendar, "AAPL", sip, iex, D(1))
        assert row.consecutive == index
        assert row.status == (MarketStatus.SUSPECT if index == 3 else MarketStatus.OK)
        assert "not independent" in row.notice
        assert crosscheck(Ledger(engine, clock), calendar, "AAPL", sip, iex, D(1)) == row
    with pytest.raises(DataIntegrityError):
        crosscheck(ledger, calendar, "AAPL", bar(25), bar(25), D(1))
    with pytest.raises(DataIntegrityError):
        crosscheck(ledger, calendar, "AAPL", bar(29), bar(29), D(1))
