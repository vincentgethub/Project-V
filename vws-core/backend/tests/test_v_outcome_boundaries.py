"""EX: altered leg and stop evidence cannot create a valid economic outcome."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.core.config import EvaluationConfig
from backend.core.errors import DataIntegrityError
from backend.data.history import KnownSplit
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.costs import CostContext, FeeSchedule
from backend.evaluation.outcomes import ExitVariant, Outcome, PartialExit, StopMove, _simulate
from backend.tests.test_outcomes_history import bar, bundle, frozen, run, setup
from backend.tests.test_v_exits import calendar as source_calendar
from backend.tests.test_v_exits import schedule as source_schedule
from backend.tests.test_v_exits import warm

calendar, schedule = source_calendar, source_schedule


def test_EX_queued_raise_is_rebased_before_a_split_session(
    calendar: MarketCalendar, schedule: FeeSchedule
) -> None:
    action = KnownSplit(
        symbol="AAPL", effective_session=date(2026, 9, 17), new_shares_per_old=Decimal(2)
    )
    history = frozen(
        bundle(
            warm(calendar)
            + (
                bar(16, high="107.02", closing="107"),
                bar(17, opening="50.50", high="54", low="50", closing="53"),
            ),
            splits=(action,),
        )
    )
    result = _simulate(
        setup(variant="SPLIT_1R_TRAIL", qty=5),
        history,
        CostContext(atr14=Decimal(2)),
        schedule,
        EvaluationConfig(),
        None,
        exit_variant="SPLIT_1R_TRAIL",
        close_trail_atr={date(2026, 9, 15): Decimal(2), date(2026, 9, 16): Decimal(2)},
    )
    assert result.status == "RESOLVED" and result.reason == "STOP"
    assert result.exit_fill is not None and result.exit_fill.qty == 6
    move = result.stop_moves[0]
    assert (move.old_stop, move.new_stop, move.basis_ratio) == (
        Decimal("47.50"),
        Decimal("50.50"),
        Decimal(2),
    )
    from backend.evaluation.replay import _Held, _protective_stop

    actions = {("AAPL", date(2026, 9, 17)): Decimal(2)}
    before = _protective_stop(_Held(result, 3, Decimal(300)), date(2026, 9, 16), actions)
    after = _protective_stop(_Held(result, 6, Decimal(300)), date(2026, 9, 17), actions)
    assert (before.qty, before.stop_price) == (3, Decimal(95))
    assert (after.qty, after.stop_price) == (6, Decimal("50.50"))


def test_EV_pending_split_reserves_whole_shares_and_refuses_fractional_shares() -> None:
    from backend.evaluation.replay import _pending_reservation

    actions = {("AAPL", date(2026, 9, 17)): Decimal("1.5")}
    intent = setup(qty=2, limit=Decimal(99), stop=Decimal(96), target=Decimal(105))
    observed = _pending_reservation(intent, date(2026, 9, 17), actions)
    assert (observed.qty, observed.limit_price, observed.stop_price) == (
        3,
        Decimal(66),
        Decimal(64),
    )
    with pytest.raises(DataIntegrityError, match="fractional shares"):
        _pending_reservation(intent.model_copy(update={"qty": 3}), date(2026, 9, 17), actions)


def test_EX_split_A_cannot_become_fractional_even_when_total_shares_are_whole(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    action = KnownSplit(
        symbol="AAPL",
        effective_session=date(2026, 9, 17),
        new_shares_per_old=Decimal("1.5"),
    )
    history = frozen(
        bundle(
            (
                bar(15, opening="99", high="100.50", low="97.50", closing="99"),
                bar(16, opening="99", high="100.50", low="97.50", closing="99"),
                bar(17, opening="66", high="67", low="65", closing="66"),
            ),
            splits=(action,),
        )
    )
    result = _simulate(
        setup(variant="SPLIT_1R", qty=6, limit=Decimal(99), stop=Decimal(96), target=Decimal(105)),
        history,
        CostContext(atr14=Decimal(3)),
        schedule,
        EvaluationConfig(),
        None,
        exit_variant="SPLIT_1R",
    )
    assert result.status == "INCOMPLETE" and result.reason == "FRACTIONAL_SPLIT"


def test_EX_trailing_ema_time_exit_waits_for_next_open(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    days = tuple(calendar.add_sessions(date(2026, 9, 15), i) for i in range(1, 13))
    tape = tuple(
        bar(16, high="107.01", closing="106").model_copy(
            update={"timestamp": calendar.session_open(day) - timedelta(hours=5, minutes=30)}
        )
        for day in days
    )
    history = frozen(bundle(warm(calendar) + tape))
    average: dict[date, Decimal | None] = {
        row.session_date: Decimal(100) for row in history.bundle.for_symbol("AAPL", "RAW").bars
    }
    result = _simulate(
        setup(variant="TRAIL_EMA20", qty=5),
        history,
        CostContext(atr14=Decimal(2)),
        schedule,
        EvaluationConfig(max_hold_sessions=10),
        None,
        exit_variant="TRAIL_EMA20",
        close_exit_ema=average,
    )
    assert result.status == "RESOLVED" and result.reason == "TIME"
    assert result.exit_session == days[10]


def test_EX_noncent_trailing_stop_never_becomes_effective(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
) -> None:
    history = frozen(
        bundle(
            warm(calendar)
            + (
                bar(16, high="107.01", closing="107"),
                bar(17, opening="105", high="108", low="104", closing="107"),
            )
        )
    )
    values: dict[date, Decimal | None] = {
        date(2026, 9, 15): Decimal(2),
        date(2026, 9, 16): Decimal("0.33333"),
    }
    result = _simulate(
        setup(variant="SPLIT_1R_TRAIL", qty=5),
        history,
        CostContext(atr14=Decimal(2)),
        schedule,
        EvaluationConfig(),
        None,
        exit_variant="SPLIT_1R_TRAIL",
        close_trail_atr=values,
    )
    assert result.status == "INCOMPLETE" and result.reason == "SUBCENT_SPLIT"
    assert not result.stop_moves


@pytest.mark.parametrize("case", ["one_share", "decision_atr", "close_atr", "close_ema"])
def test_EX_unavailable_leg_or_close_evidence_never_infers_an_exit(
    calendar: MarketCalendar,
    schedule: FeeSchedule,
    case: str,
) -> None:
    variant: ExitVariant = "TRAIL_EMA20" if case == "close_ema" else "SPLIT_1R_TRAIL"
    history = frozen(
        bundle(
            warm(calendar)
            + (
                bar(16, high="107.01", closing="107"),
                bar(17, opening="105", high="108", low="104", closing="107"),
            )
        )
    )
    ema: dict[date, Decimal | None] | None = (
        {date(2026, 9, 15): Decimal(100)} if case == "close_ema" else None
    )
    atr: dict[date, Decimal | None] | None = (
        None
        if case == "close_ema"
        else {}
        if case == "decision_atr"
        else {date(2026, 9, 15): Decimal(2)}
    )
    if case == "one_share":
        with pytest.raises(DataIntegrityError, match="two shares"):
            _simulate(
                setup(variant=variant, qty=1),
                history,
                CostContext(atr14=Decimal(2)),
                schedule,
                EvaluationConfig(),
                None,
                exit_variant=variant,
                close_exit_ema=ema,
                close_trail_atr=atr,
            )
    else:
        result = _simulate(
            setup(variant=variant, qty=5),
            history,
            CostContext(atr14=Decimal(2)),
            schedule,
            EvaluationConfig(),
            None,
            exit_variant=variant,
            close_exit_ema=ema,
            close_trail_atr=atr,
        )
        assert result.status == "INCOMPLETE" and result.reason == "HISTORY_PENDING"


@pytest.fixture
def resolved(calendar: MarketCalendar, schedule: FeeSchedule) -> Outcome:
    result = run(
        setup(variant="SPLIT_1R_TRAIL", qty=5),
        bundle(
            warm(calendar)
            + (
                bar(16, high="107.01", closing="107"),
                bar(17, opening="98", high="100", low="97", closing="99"),
            )
        ),
        calendar,
        schedule,
        exit_variant="SPLIT_1R_TRAIL",
    )
    assert result.status == "RESOLVED" and result.partial_exits and result.stop_moves
    return result


@pytest.mark.parametrize(
    "case",
    [
        "variant",
        "early_partial",
        "late_partial",
        "early_move",
        "late_move",
        "no_A",
        "A_after_raise",
        "A_oversell",
        "exit_oversell",
    ],
)
def test_EX_altered_evidence_cannot_claim_valid_cashflows(resolved: Outcome, case: str) -> None:
    values = resolved.model_dump()
    partial, move = resolved.partial_exits[0], resolved.stop_moves[0]
    assert resolved.entry_fill is not None and resolved.exit_fill is not None
    if case == "variant":
        values["setup"] = resolved.setup.model_copy(update={"variant": "baseline"})
    elif case in {"early_partial", "late_partial", "A_after_raise"}:
        session = (
            date(2026, 9, 15)
            if case == "early_partial"
            else date(2026, 9, 18)
            if case == "late_partial"
            else date(2026, 9, 17)
        )
        values["partial_exits"] = (
            PartialExit.model_validate(partial.model_copy(update={"session": session})),
        )
    elif case in {"early_move", "late_move"}:
        change = (
            {"decided_session": date(2026, 9, 15)}
            if case == "early_move"
            else {"effective_session": date(2026, 9, 18)}
        )
        values["stop_moves"] = (StopMove.model_validate(move.model_copy(update=change)),)
    elif case == "no_A":
        values["partial_exits"] = ()
    elif case == "A_oversell":
        filled = type(partial.fill).model_validate(
            partial.fill.model_copy(
                update={"qty": resolved.entry_fill.qty, "requested_qty": resolved.entry_fill.qty}
            )
        )
        values["partial_exits"] = (
            PartialExit.model_validate(partial.model_copy(update={"fill": filled})),
        )
    else:
        values["exit_fill"] = resolved.exit_fill.model_copy(
            update={"qty": resolved.exit_fill.qty + 1, "requested_qty": resolved.exit_fill.qty + 1}
        )
    with pytest.raises(ValidationError, match="EX"):
        Outcome.model_validate(values)


def test_EX_A_requires_target_fill_and_stop_raise_requires_later_session(resolved: Outcome) -> None:
    partial, move = resolved.partial_exits[0], resolved.stop_moves[0]
    with pytest.raises(ValidationError, match="complete target"):
        PartialExit.model_validate(
            partial.model_copy(update={"fill": partial.fill.model_copy(update={"reason": "STOP"})})
        )
    with pytest.raises(ValidationError, match="upward stop"):
        StopMove.model_validate(move.model_copy(update={"new_stop": move.old_stop}))
    with pytest.raises(ValidationError, match="upward stop"):
        StopMove.model_validate(move.model_copy(update={"decided_session": move.effective_session}))
