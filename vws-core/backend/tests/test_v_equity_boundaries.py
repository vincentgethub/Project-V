"""EX/ER: delayed A exits conserve real shares and exact portfolio cash."""

from datetime import date
from decimal import Decimal

import pytest

from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.costs import FeeSchedule
from backend.evaluation.edge import EdgeKey
from backend.evaluation.equity import build_equity_curve
from backend.evaluation.outcomes import Outcome, PartialExit
from backend.tests.test_outcomes_history import bar, bundle, frozen, run, setup
from backend.tests.test_v_exits import calendar as source_calendar
from backend.tests.test_v_exits import schedule as source_schedule

calendar, schedule = source_calendar, source_schedule
D = Decimal


@pytest.mark.parametrize("case", ["open", "resolved", "oversell", "same_day_oversell"])
def test_EX_partial_cash_conservation_is_checked_against_actual_history(
    calendar: MarketCalendar, schedule: FeeSchedule, case: str
) -> None:
    tape = bundle(
        (
            bar(15),
            bar(16, high="106", closing="105"),
            bar(17, opening="105", high="107.01", low="104", closing="105"),
            bar(
                18,
                opening="105",
                high="110.01" if case == "resolved" else "107",
                low="104",
                closing="106",
            ),
        )
    )
    result = run(
        setup(variant="SPLIT_1R", qty=5), tape, calendar, schedule, exit_variant="SPLIT_1R"
    )
    assert result.partial_exits[0].session == date(2026, 9, 17)
    if case in {"oversell", "same_day_oversell"}:
        part = result.partial_exits[0]
        fill = type(part.fill).model_validate(
            part.fill.model_copy(update={"qty": 5, "requested_qty": 5})
        )
        altered = PartialExit.model_validate(
            part.model_copy(
                update={
                    "fill": fill,
                    "basis_ratio": D(2),
                    "session": date(2026, 9, 16) if case == "same_day_oversell" else part.session,
                }
            )
        )
        result = Outcome.model_validate(result.model_copy(update={"partial_exits": (altered,)}))
    key = EdgeKey(
        playbook=result.setup.playbook, variant="SPLIT_1R", cohort="PAPER", disposition="APPROVED"
    )
    if case in {"oversell", "same_day_oversell"}:
        with pytest.raises(DataIntegrityError, match="equity evidence"):
            build_equity_curve(
                key,
                (result,),
                frozen(tape),
                calendar,
                initial_equity=D(1000),
                start=date(2026, 9, 15),
                end=date(2026, 9, 18),
            )
        return
    built = build_equity_curve(
        key,
        (result,),
        frozen(tape),
        calendar,
        initial_equity=D(1000),
        start=date(2026, 9, 15),
        end=date(2026, 9, 18),
    )
    assert built.status == "AVAILABLE" and built.curve is not None
    assert result.entry_fees is not None
    if case == "resolved":
        assert result.net_money is not None
        assert built.curve.points[-1].equity == D(1000) + result.net_money
    else:
        assert (
            built.curve.points[-1].equity
            == D(1000)
            - D("100.02") * 5
            - result.entry_fees.total
            + D(107) * 2
            - result.partial_exits[0].fees.total
            + D(106) * 3
        )
