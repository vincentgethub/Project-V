"""XK-03..06: exact boundary goldens and persistent account separation."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import PlaybookKillConfig, RampConfig, RegimeFilterConfig
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemState, SystemStateStore
from backend.domain.models import Playbook
from backend.ops.macro_events import MacroCalendar
from backend.ops.trading_controls import (
    ControlScope,
    RampObservation,
    RampState,
    TradingControls,
    advance_ramp,
    reduced_quantity,
    regime_multiplier,
)
from backend.tests.test_system_state import RecordingNotifier

LIVE = ControlScope(account_id="scratch-live", environment="LIVE")
PAPER = ControlScope(account_id="scratch-paper", environment="PAPER")


@pytest.mark.parametrize(
    "action,multiplier", [("annotate", "1"), ("half_size", ".5"), ("no_new_entries", "0")]
)
@pytest.mark.parametrize("close", [Decimal("99.99"), Decimal(100), Decimal("100.01")])
def test_XK_03_regime_boundary_reduces_only(action: str, multiplier: str, close: Decimal) -> None:
    policy = RegimeFilterConfig.model_validate({"auto": action})
    result = regime_multiplier(close, Decimal(100), policy, auto=True)
    assert result == (Decimal(multiplier) if close < 100 else Decimal(1))
    assert regime_multiplier(close, Decimal(100), policy, auto=False) == 1
    assert 0 <= reduced_quantity(9, (result,)) <= 9


def test_XK_03_unknown_regime_refuses_auto_but_manual_can_annotate() -> None:
    with pytest.raises(DataIntegrityError):
        regime_multiplier(None, None, RegimeFilterConfig(), auto=True)
    assert regime_multiplier(None, None, RegimeFilterConfig(), auto=False) == 1
    assert reduced_quantity(9, (Decimal(".5"), Decimal(".25"))) == 1
    with pytest.raises(DataIntegrityError):
        reduced_quantity(9, (Decimal("1.0001"),))


@pytest.mark.parametrize(
    "day,expected",
    [("2026-01-09", "2026-01-09T13:30:00+00:00"), ("2026-07-02", "2026-07-02T12:30:00+00:00")],
)
def test_XK_04_macro_blackout_is_dst_correct(tmp_path: Path, day: str, expected: str) -> None:
    path = tmp_path / "macro_events.csv"
    path.write_text(
        f"date,et_time,event,source\n{day},08:30,NFP,https://www.bls.gov/schedule/\n",
        encoding="utf-8",
    )
    event = MacroCalendar(path).read()[0]
    assert event.release_at == datetime.fromisoformat(expected)
    assert event.window().start.hour == (5 if day.startswith("2026-01") else 4)
    assert event.window().end == event.release_at + timedelta(minutes=30)


@pytest.mark.parametrize(
    "row",
    [
        "2026-03-08,02:30,CPI,https://www.bls.gov/schedule/",
        "2026-11-01,01:30,CPI,https://www.bls.gov/schedule/",
        "2026-01-09,08:30,OTHER,https://www.bls.gov/schedule/",
        "2026-01-09,08:30,NFP,//www.bls.gov/schedule/",
        "2026-01-09,08:30,NFP,https://unknown.invalid/",
        "2026-01-09,08:30,NFP,https://www.bls.gov/schedule/,extra",
    ],
)
def test_XK_04_invalid_calendar_fails_closed(tmp_path: Path, row: str) -> None:
    path = tmp_path / "macro_events.csv"
    path.write_text("date,et_time,event,source\n" + row + "\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        MacroCalendar(path).read()


def test_XK_04_empty_calendar_and_90_day_warning(tmp_path: Path) -> None:
    path = tmp_path / "macro_events.csv"
    path.write_text("date,et_time,event,source\n", encoding="utf-8")
    now = datetime(2026, 10, 9, tzinfo=UTC)
    calendar = MacroCalendar(path)
    assert calendar.read() == ()
    stamp = (now - timedelta(days=90)).timestamp()
    os.utime(path, (stamp, stamp))
    assert calendar.warnings(now) == ()
    os.utime(path, (stamp - 1, stamp - 1))
    assert "90 days" in calendar.warnings(now)[0]


@pytest.mark.parametrize(
    "n,total,paused", [(29, "-1", False), (30, "0", False), (30, "-0.000001", True)]
)
def test_XK_05_kill_threshold_and_restart(
    engine: Engine, clock: FrozenClock, n: int, total: str, paused: bool
) -> None:
    controls = TradingControls(Ledger(engine, clock), PAPER)
    sample = (Decimal(total),) + (Decimal(0),) * (n - 1)
    assert controls.evaluate_playbook(Playbook.TREND_50EMA, sample) is paused
    assert TradingControls(controls.ledger, PAPER).paused(Playbook.TREND_50EMA) is paused
    assert not TradingControls(controls.ledger, LIVE).paused(Playbook.TREND_50EMA)
    if paused:
        controls.enable_playbook(Playbook.TREND_50EMA, "Offline owner")
        assert not controls.evaluate_playbook(Playbook.TREND_50EMA, sample)
        assert controls.evaluate_playbook(Playbook.TREND_50EMA, (*sample, Decimal(-1)))
    controls.ledger.verify_chain()


@pytest.mark.parametrize("n,step", [(9, 0), (10, 1), (29, 1), (30, 2)])
def test_XK_06_ramp_trade_boundaries_and_restart(
    engine: Engine, clock: FrozenClock, n: int, step: int
) -> None:
    controls = TradingControls(Ledger(engine, clock), LIVE)
    controls.observe_ramp(min(n, 10), Decimal(".049999"))
    result, _ = controls.observe_ramp(n, Decimal(".049999"))
    assert result.step == step and result.multiplier <= 1
    assert TradingControls(controls.ledger, LIVE).ramp() == result


def test_XK_06_fault_and_drawdown_consumed_once(engine: Engine, clock: FrozenClock) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    controls = TradingControls(state.ledger, LIVE)
    controls.observe_ramp(10, Decimal(0))
    controls.observe_ramp(30, Decimal(0))
    state.escalate(SystemState.REDUCE_ONLY, "synthetic risk event")
    assert controls.observe_ramp(30, Decimal(0))[0].step == 1
    assert controls.observe_ramp(30, Decimal(0))[0].step == 1
    assert controls.observe_ramp(30, Decimal(".05"))[0].step == 0
    assert controls.observe_ramp(90, Decimal(".05"))[0].step == 0
    assert controls.observe_ramp(90, Decimal(".049999"))[0].step == 0
    state.operator_reset("Offline owner", "audited synthetic recovery")
    assert controls.observe_ramp(100, Decimal(".049999"))[0].step == 1
    with pytest.raises(DataIntegrityError):
        advance_ramp(
            RampState(scope=LIVE, step=1, resolved_baseline=30, last_fault_seq=5),
            RampObservation(scope=PAPER, resolved=31, drawdown=Decimal(0), fault_seq=5),
        )


@pytest.mark.parametrize(
    "kind,value",
    [("minimum", 29), ("minimum", True), ("ramp", [".5", ".5", "1"]), ("ramp", [0.25, 0.5, 1.0])],
)
def test_XK_controls_reject_optimization(kind: str, value: object) -> None:
    with pytest.raises((ValidationError, DataIntegrityError)):
        if kind == "minimum":
            PlaybookKillConfig.model_validate({"min_trades": value})
        else:
            RampConfig.model_validate({"steps": value})
