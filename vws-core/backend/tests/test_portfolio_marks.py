"""CRO-09/CRO-10/R-02/R-05: persisted session baselines and loss blocks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.config import Settings
from backend.core.database import PortfolioState, SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import PortfolioSnapshot
from backend.risk.portfolio_marks import PersistedPortfolioMarks

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)


class MovingClock:
    """R-05: explicitly advanced clock; no wall-clock reads."""

    def __init__(self, instant: datetime = NOW) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


def snapshot(now: datetime, equity: str = "10000", **updates: Any) -> PortfolioSnapshot:
    """CRO-09/CRO-10: caller-attested initial marks with complete balances."""
    fields: dict[str, Any] = {
        "account_id": "marks-paper",
        "account_type": "CASH",
        "as_of": now,
        "equity": Decimal(equity),
        "cash": Decimal(equity),
        "settled_cash": Decimal(equity),
        "positions": {},
        "open_orders": (),
        "high_water_mark": Decimal("10000"),
        "day_start_equity": Decimal("10000"),
    }
    fields.update(updates)
    return PortfolioSnapshot.model_validate(fields)


def marks(engine: Engine, clock: MovingClock) -> PersistedPortfolioMarks:
    """CRO-10: real append-only SQLite evidence with a fake clock."""
    return PersistedPortfolioMarks(
        Ledger(engine, clock), "marks-paper", MarketCalendar(), Settings(broker_account_type="CASH")
    )


@pytest.mark.parametrize(
    "component,bad",
    [
        ("ledger", None),
        ("calendar", None),
        ("account", ""),
        ("account", " x"),
        ("account", "x" * 129),
        ("account", 7),
        ("config", None),
    ],
)
def test_R_02_CRO_10_marks_constructor_requires_explicit_validated_policy(
    engine: Engine,
    component: str,
    bad: Any,
) -> None:
    values: dict[str, Any] = {
        "ledger": Ledger(engine, MovingClock()),
        "calendar": MarketCalendar(),
        "account_id": "marks-paper",
        "config": Settings(broker_account_type="CASH"),
    }
    values["account_id" if component == "account" else component] = bad
    with pytest.raises(ConfigurationError):
        PersistedPortfolioMarks(**values)


def test_CRO_09_CRO_10_callback_initializes_current_equity_without_writing(engine: Engine) -> None:
    reader = marks(engine, MovingClock())
    assert reader(Decimal("12000"), NOW) == (Decimal("12000"), Decimal("12000"))
    assert not reader.daily_loss_blocked(NOW)
    with transaction(engine) as session:
        assert session.scalar(select(PortfolioState)) is None


def test_CRO_09_CRO_10_bootstrap_preserves_attested_marks_and_new_highs(engine: Engine) -> None:
    clock = MovingClock()
    reader = marks(engine, clock)
    initial = reader.observe(snapshot(NOW, high_water_mark=Decimal("11000")))
    assert initial.high_water_mark == Decimal("11000")
    assert initial.day_start_equity == Decimal("10000")
    clock.instant += timedelta(minutes=1)
    later = reader.observe(snapshot(clock.now(), "12000"))
    assert later.high_water_mark == Decimal("12000")
    assert later.day_start_equity == Decimal("10000")
    assert reader(Decimal("11500"), clock.now()) == (Decimal("12000"), Decimal("10000"))
    reader.ledger.verify_chain()
    with transaction(engine) as session:
        rows = session.scalars(select(PortfolioState).order_by(PortfolioState.seq)).all()
        assert len(rows) == 2
        assert rows[0].equity == Decimal("10000")
        assert rows[1].equity == Decimal("12000")


@pytest.mark.parametrize(
    "start,premarket,next_open",
    [
        (
            datetime(2026, 10, 2, 16, tzinfo=UTC),
            datetime(2026, 10, 5, 13, 29, 59, tzinfo=UTC),
            datetime(2026, 10, 5, 13, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 7, 2, 19, tzinfo=UTC),
            datetime(2026, 7, 6, 13, 29, 59, tzinfo=UTC),
            datetime(2026, 7, 6, 13, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 11, 27, 17, tzinfo=UTC),
            datetime(2026, 11, 30, 14, 29, 59, tzinfo=UTC),
            datetime(2026, 11, 30, 14, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 3, 6, 20, tzinfo=UTC),
            datetime(2026, 3, 9, 13, 29, 59, tzinfo=UTC),
            datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
        ),
    ],
)
def test_CRO_10_next_open_rollover_handles_weekend_holiday_earlyclose_and_DST(
    engine: Engine,
    start: datetime,
    premarket: datetime,
    next_open: datetime,
) -> None:
    clock = MovingClock(start)
    reader = marks(engine, clock)
    reader.observe(snapshot(start))
    clock.instant += timedelta(minutes=1)
    breached = reader.observe(snapshot(clock.now(), "9800"))
    assert breached.day_start_equity == Decimal("10000")
    assert reader.daily_loss_blocked(clock.now())
    clock.instant += timedelta(minutes=1)
    reader.observe(snapshot(clock.now()))
    assert reader.daily_loss_blocked(clock.now()), "recovery does not erase witnessed breach"
    restarted = PersistedPortfolioMarks(
        reader.ledger, "marks-paper", reader.calendar, reader.config
    )
    assert restarted.daily_loss_blocked(clock.now())
    clock.instant = premarket
    before = restarted.observe(snapshot(premarket, "9900"))
    assert before.day_start_equity == Decimal("10000")
    assert restarted.daily_loss_blocked(premarket)
    clock.instant = next_open
    after = restarted.observe(snapshot(next_open, "9900"))
    assert after.day_start_equity == Decimal("9900")
    assert after.high_water_mark == Decimal("10000")
    assert not restarted.daily_loss_blocked(next_open)
    restarted.ledger.verify_chain()


@pytest.mark.parametrize("age,allowed", [(60, True), (61, False), (-1, False)])
def test_R_05_CRO_10_mark_read_age_exact_boundary(engine: Engine, age: int, allowed: bool) -> None:
    reader = marks(engine, MovingClock())
    observed = NOW - timedelta(seconds=age)
    if allowed:
        assert reader(Decimal("10000"), observed) == (Decimal("10000"), Decimal("10000"))
    else:
        with pytest.raises(DataIntegrityError):
            reader(Decimal("10000"), observed)


@pytest.mark.parametrize("bad", [None, True, 10000, "10000", Decimal("NaN")])
def test_R_04_CRO_09_equity_callback_rejects_inexact_or_invalid_money(
    engine: Engine, bad: Any
) -> None:
    with pytest.raises(DataIntegrityError):
        marks(engine, MovingClock())(bad, NOW)


@pytest.mark.parametrize(
    "updates",
    [
        {"account_id": "other"},
        {"account_type": "MARGIN"},
        {"as_of": NOW + timedelta(seconds=1)},
        {"as_of": NOW - timedelta(seconds=61)},
    ],
)
def test_R_02_CRO_10_observation_binds_account_policy_and_time(
    engine: Engine, updates: dict[str, Any]
) -> None:
    reader = marks(engine, MovingClock())
    with pytest.raises(DataIntegrityError):
        reader.observe(snapshot(NOW, **updates))


def test_R_02_CRO_10_forged_snapshot_and_backwards_observation_fail_closed(engine: Engine) -> None:
    reader = marks(engine, MovingClock())
    with pytest.raises(DataIntegrityError):
        reader.observe(snapshot(NOW).model_copy(update={"equity": None}))
    reader.observe(snapshot(NOW))
    with pytest.raises(DataIntegrityError):
        reader(Decimal("10000"), NOW - timedelta(seconds=1))
    with pytest.raises(DataIntegrityError):
        reader.observe(snapshot(NOW - timedelta(seconds=1)))
    with pytest.raises(DataIntegrityError):
        reader.daily_loss_blocked(NOW - timedelta(seconds=1))


@pytest.mark.parametrize("operation", ["callback", "observe", "block"])
def test_R_02_CRO_10_unexpected_ledger_fault_is_typed_and_suppresses_details(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    reader = marks(engine, MovingClock())

    def fail() -> None:
        raise RuntimeError("untrusted provider secret")

    monkeypatch.setattr(reader.ledger, "verify_chain", fail)
    with pytest.raises(DataIntegrityError) as result:
        if operation == "callback":
            reader(Decimal("10000"), NOW)
        elif operation == "observe":
            reader.observe(snapshot(NOW))
        else:
            reader.daily_loss_blocked(NOW)
    assert "untrusted provider secret" not in str(result.value)
    assert result.value.__suppress_context__


@pytest.mark.parametrize("equity,baseline", [("0", "10000"), ("10000", "0")])
def test_R_02_CRO_10_invalid_baseline_or_equity_is_entry_blocked(
    engine: Engine, equity: str, baseline: str
) -> None:
    reader = marks(engine, MovingClock())
    reader.observe(snapshot(NOW, equity, day_start_equity=Decimal(baseline)))
    assert reader.daily_loss_blocked(NOW)


def test_CRO_09_CRO_10_observed_cash_flow_scales_both_marks_exactly(engine: Engine) -> None:
    clock = MovingClock()
    reader = marks(engine, clock)
    reader.observe(snapshot(NOW))
    clock.instant += timedelta(minutes=1)
    reader.ledger.record_cash_flow("marks-paper", Decimal("1000"), clock.now(), Decimal("10000"))
    with localcontext() as context:
        context.prec = 2
        assert reader(Decimal("11000"), clock.now()) == (Decimal("11000"), Decimal("11000"))
        assert not reader.daily_loss_blocked(clock.now())


def test_R_02_CRO_10_config_revalidation_preserves_explicit_telegram_allowlist(
    engine: Engine,
) -> None:
    config = Settings(broker_account_type="CASH", telegram_allowed_user_ids=(123,))
    reader = PersistedPortfolioMarks(
        Ledger(engine, MovingClock()), "marks-paper", MarketCalendar(), config
    )
    assert reader.config.telegram_allowed_user_ids == (123,)
    with pytest.raises(ConfigurationError):
        PersistedPortfolioMarks(
            reader.ledger,
            "marks-paper",
            reader.calendar,
            config.model_copy(update={"daily_loss_limit": Decimal("0.10")}),
        )


def test_CRO_10_witnessed_breach_survives_looser_and_tighter_limit_and_restart(
    engine: Engine,
) -> None:
    clock = MovingClock()
    reader = marks(engine, clock)
    reader.observe(snapshot(NOW))
    clock.instant += timedelta(minutes=1)
    reader.observe(snapshot(clock.now(), "9800"))
    for limit in (Decimal("0.03"), Decimal("0.01"), Decimal("0.05")):
        reader = PersistedPortfolioMarks(
            reader.ledger,
            reader.account_id,
            reader.calendar,
            Settings(broker_account_type="CASH", daily_loss_limit=limit),
        )
        clock.instant += timedelta(minutes=1)
        reader.observe(snapshot(clock.now()))
        assert reader.daily_loss_blocked(clock.now())
    with transaction(engine) as session:
        events = session.scalars(
            select(SecurityEvent).where(SecurityEvent.kind == "DAILY_LOSS_BREACH")
        ).all()
        assert len(events) == 1
        assert events[0].detail["limit"] == "0.02"
        assert events[0].detail["session"] == "2026-10-02"
    clock.instant = reader.calendar.session_open(datetime(2026, 10, 5).date())
    reader.observe(snapshot(clock.now()))
    assert not reader.daily_loss_blocked(clock.now())


def test_CRO_10_tightened_limit_records_existing_session_evidence_before_recovery_can_clear_it(
    engine: Engine,
) -> None:
    clock = MovingClock()
    reader = marks(engine, clock)
    reader.observe(snapshot(NOW))
    clock.instant += timedelta(minutes=1)
    reader.observe(snapshot(clock.now(), "9900"))
    assert not reader.daily_loss_blocked(clock.now())
    tightened = PersistedPortfolioMarks(
        reader.ledger,
        reader.account_id,
        reader.calendar,
        Settings(broker_account_type="CASH", daily_loss_limit=Decimal("0.01")),
    )
    assert tightened.daily_loss_blocked(clock.now()), "legacy observations replay conservatively"
    clock.instant += timedelta(minutes=1)
    tightened.observe(snapshot(clock.now()))
    loosened = PersistedPortfolioMarks(
        reader.ledger,
        reader.account_id,
        reader.calendar,
        Settings(broker_account_type="CASH", daily_loss_limit=Decimal("0.03")),
    )
    assert loosened.daily_loss_blocked(clock.now())


def test_CRO_10_breach_events_are_bound_to_managed_account(engine: Engine) -> None:
    reader = marks(engine, MovingClock())
    other = PersistedPortfolioMarks(reader.ledger, "other-paper", reader.calendar, reader.config)
    other.observe(snapshot(NOW, "9800", account_id="other-paper"))
    reader.observe(snapshot(NOW))
    assert other.daily_loss_blocked(NOW)
    assert not reader.daily_loss_blocked(NOW)


@pytest.mark.parametrize("limit", [Decimal("0"), Decimal("0.05")])
def test_CRO_10_recorded_limit_zero_and_ceiling_remain_exact(
    engine: Engine, limit: Decimal
) -> None:
    reader = marks(engine, MovingClock())
    reader = PersistedPortfolioMarks(
        reader.ledger,
        reader.account_id,
        reader.calendar,
        Settings(broker_account_type="CASH", daily_loss_limit=limit),
    )
    reader.observe(snapshot(NOW, "9500" if limit else "10000"))
    assert reader.daily_loss_blocked(NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": "not permitted"},
        {"portfolio_seq": True},
        {"portfolio_seq": 999},
        {"session": 1},
        {"session": "2026-10-05"},
        {"config_hash": []},
        {"config_hash": "0" * 63},
        {"config_hash": "g" * 64},
        {"limit": "-0.01"},
        {"limit": "0.06"},
        {"limit": "NaN"},
    ],
)
def test_R_02_CRO_10_planted_malformed_breach_events_fail_closed(
    engine: Engine, changes: dict[str, Any]
) -> None:
    reader = marks(engine, MovingClock())
    reader.observe(snapshot(NOW, "9800"))
    detail = {
        "account_id": "marks-paper",
        "session": "2026-10-02",
        "portfolio_seq": 1,
        "limit": "0.02",
        "config_hash": reader.config.config_hash,
        **changes,
    }
    reader.ledger.append(
        SecurityEvent, kind="DAILY_LOSS_BREACH", telegram_user_id=None, detail=detail, ts=NOW
    )
    with pytest.raises(DataIntegrityError):
        reader.daily_loss_blocked(NOW)


@pytest.mark.parametrize("offset", [-1, 1, 86400])
def test_R_05_CRO_10_planted_breach_time_cannot_be_future_before_source_or_wrong_session(
    engine: Engine, offset: int
) -> None:
    reader = marks(engine, MovingClock())
    reader.observe(snapshot(NOW, "9800"))
    reader.ledger.append(
        SecurityEvent,
        kind="DAILY_LOSS_BREACH",
        telegram_user_id=None,
        detail={
            "account_id": "marks-paper",
            "session": "2026-10-02",
            "portfolio_seq": 1,
            "limit": "0.02",
            "config_hash": reader.config.config_hash,
        },
        ts=NOW + timedelta(seconds=offset),
    )
    with pytest.raises(DataIntegrityError):
        reader.daily_loss_blocked(NOW)


def test_R_02_CRO_10_planted_event_cannot_precede_its_source_or_claim_unbreached_balance(
    engine: Engine,
) -> None:
    reader = marks(engine, MovingClock())
    reader.ledger.append(
        SecurityEvent,
        kind="DAILY_LOSS_BREACH",
        telegram_user_id=None,
        detail={
            "account_id": "marks-paper",
            "session": "2026-10-02",
            "portfolio_seq": 2,
            "limit": "0.02",
            "config_hash": reader.config.config_hash,
        },
        ts=NOW,
    )
    with pytest.raises(DataIntegrityError):
        reader.observe(snapshot(NOW, "9800"))
    with transaction(engine) as session:
        assert session.scalar(select(PortfolioState)) is None, (
            "invalid evidence rolls back the observation"
        )


def test_R_02_CRO_10_breach_requires_a_real_threshold_crossing(engine: Engine) -> None:
    reader = marks(engine, MovingClock())
    reader.observe(snapshot(NOW))
    reader.ledger.append(
        SecurityEvent,
        kind="DAILY_LOSS_BREACH",
        telegram_user_id=None,
        detail={
            "account_id": "marks-paper",
            "session": "2026-10-02",
            "portfolio_seq": 1,
            "limit": "0.02",
            "config_hash": reader.config.config_hash,
        },
        ts=NOW,
    )
    with pytest.raises(DataIntegrityError):
        reader.daily_loss_blocked(NOW)
