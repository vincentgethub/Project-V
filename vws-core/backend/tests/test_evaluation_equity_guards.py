"""EV-02: independent cash, split and held-share guards for valid outcome rows."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

import pytest

from backend.core.errors import DataIntegrityError
from backend.data.history import FrozenHistory, KnownSplit
from backend.data.market_calendar import MarketCalendar
from backend.evaluation import equity as module
from backend.evaluation.costs import FeeBreakdown
from backend.evaluation.dividends import distribution_rates
from backend.evaluation.equity import build_equity_curve
from backend.evaluation.outcomes import REPLAY_NOTES, Outcome
from backend.tests import test_edge as edge_golden
from backend.tests import test_weekly_equity as golden
from backend.tests.test_outcomes_history import bundle, frozen

calendar, history, results = golden.calendar, golden.history, golden.results
edge_outcomes = edge_golden.outcomes
D = Decimal


def changed_result(item: Outcome, **changes: Any) -> Outcome:
    """Recompute exact proof after changing a fill, so portfolio checks receive valid rows."""
    row = item.model_copy(update=changes)
    assert row.entry_fill and row.exit_fill and row.entry_fees and row.exit_fees
    assert row.entry_fill.price and row.exit_fill.price and row.initial_risk_money
    with localcontext() as precision:
        precision.prec = 80
        net = (
            row.exit_fill.price * row.exit_fill.qty
            - row.entry_fill.price * row.entry_fill.qty
            - row.entry_fees.total
            - row.exit_fees.total
            + sum((credit.amount for credit in row.distributions), D(0))
        )
        multiple = (net / row.initial_risk_money).quantize(D(".000001"), rounding=ROUND_HALF_EVEN)
    return Outcome.model_validate(row.model_copy(update={"net_money": net, "r_multiple": multiple}))


@pytest.mark.parametrize(
    "fault", ["same_day_qty", "later_qty", "nonpositive", "incomplete", "bound"]
)
def test_EV_equity_never_invents_held_shares_or_borrowed_equity(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    item = results[0]
    assert item.exit_fill and item.entry_session
    initial = D(100)
    if fault in {"same_day_qty", "later_qty"}:
        values: dict[str, Any] = {
            "exit_fill": item.exit_fill.model_copy(update={"qty": 2, "requested_qty": 2})
        }
        if fault == "later_qty":
            values["exit_session"] = calendar.add_sessions(item.entry_session, 1)
        item = changed_result(item, **values)
        with pytest.raises(DataIntegrityError):
            build_equity_curve(
                edge_golden.KEY,
                (item,),
                history,
                calendar,
                initial_equity=initial,
                start=golden.START,
                end=golden.END,
            )
        return
    if fault == "nonpositive":
        item = changed_result(
            item,
            exit_fees=FeeBreakdown(
                commission=D(20), sec=D(0), taf=D(0), cat=D(0), source="MODELED"
            ),
        )
        initial = D(10)
    elif fault == "incomplete":
        item = Outcome.model_validate(
            item.model_copy(
                update={
                    "status": "INCOMPLETE",
                    "reason": "HISTORY_PENDING",
                    "exit_session": None,
                    "exit_fill": None,
                    "exit_fees": None,
                    "net_money": None,
                    "r_multiple": None,
                }
            )
        )
    else:
        assert module.MAX_EQUITY_SESSIONS == 20000
        monkeypatch.setattr(module, "MAX_EQUITY_SESSIONS", 1)
        with pytest.raises(DataIntegrityError):
            build_equity_curve(
                edge_golden.KEY,
                (item,),
                history,
                calendar,
                initial_equity=initial,
                start=golden.START,
                end=golden.END,
            )
        return
    value = build_equity_curve(
        edge_golden.KEY,
        (item,),
        history,
        calendar,
        initial_equity=initial,
        start=golden.START,
        end=golden.END,
    )
    assert value.status == "UNAVAILABLE" and value.curve is None


def test_EV_equity_refuses_fractional_held_split_and_preserves_typed_errors(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    item = results[0]
    assert item.entry_session
    exit_day = calendar.add_sessions(item.entry_session, 2)
    item = changed_result(item, exit_session=exit_day)
    assert item.entry_session
    action = KnownSplit(
        symbol="AAPL",
        effective_session=calendar.add_sessions(item.entry_session, 1),
        new_shares_per_old=D(".5"),
    )
    observed = frozen(bundle(history.bundle.for_symbol("AAPL", "RAW").bars, (action,)))
    item = item.model_copy(update={"manifest_sha256": observed.manifest.sha256})
    value = build_equity_curve(
        edge_golden.KEY,
        (item,),
        observed,
        calendar,
        initial_equity=D(100),
        start=golden.START,
        end=golden.END,
    )
    assert value.status == "UNAVAILABLE" and "fractional" in value.reason
    absent = item.model_copy(update={"setup": item.setup.model_copy(update={"symbol": "MSFT"})})
    with pytest.raises(DataIntegrityError, match="absent"):
        build_equity_curve(
            edge_golden.KEY,
            (absent,),
            observed,
            calendar,
            initial_equity=D(100),
            start=golden.START,
            end=golden.END,
        )
    with pytest.raises(DataIntegrityError, match="absent"):
        distribution_rates(observed, "MSFT")


def test_EV_equity_requires_distribution_proof_for_each_held_session(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = results[0]
    assert item.entry_session
    day = calendar.add_sessions(item.entry_session, 1)
    item = changed_result(item, exit_session=day)
    item = item.model_copy(
        update={
            "setup": item.setup.model_copy(update={"cohort": "REPLAY_IN_SAMPLE"}),
            "notes": REPLAY_NOTES,
        }
    )
    key = edge_golden.KEY.model_copy(update={"cohort": "REPLAY_IN_SAMPLE"})
    monkeypatch.setattr(module, "distribution_rates", lambda *args: {day: D(".10")})
    with pytest.raises(DataIntegrityError):
        build_equity_curve(
            key,
            (item,),
            history,
            calendar,
            initial_equity=D(100),
            start=golden.START,
            end=golden.END,
        )
