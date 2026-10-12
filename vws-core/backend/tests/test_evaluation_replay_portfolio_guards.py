"""EV-03: portfolio conservation remains mandatory after per-outcome validation."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.data_layer import Bar
from backend.data.frozen_filings import FrozenFilings
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries, KnownSplit
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import Decision, Verdict
from backend.evaluation import replay as module
from backend.evaluation.costs import FeeBreakdown
from backend.evaluation.outcomes import Outcome
from backend.evaluation.outcomes import _simulate as simulate_outcome
from backend.risk.risk_cro import ChiefRiskOfficer
from backend.tests import test_replay as golden
from backend.tests.test_evaluation_equity_guards import changed_result
from backend.tests.test_outcomes_history import frozen

calendar, inputs = golden.calendar, golden.inputs
D = Decimal


def not_filled(item: Outcome) -> Outcome:
    return Outcome.model_validate(
        item.model_copy(
            update={
                "status": "NOT_FILLED",
                "reason": "ALERT_UNFILLED",
                "entry_session": None,
                "exit_session": None,
                "entry_fill": None,
                "exit_fill": None,
                "entry_fees": None,
                "exit_fees": None,
                "entry_basis_ratio": None,
                "initial_risk_money": None,
                "net_money": None,
                "r_multiple": None,
                "mae_money": None,
                "mfe_money": None,
                "sessions_held": 0,
                "distributions": (),
            }
        )
    )


@pytest.mark.parametrize("fault", ["cash", "exit_qty", "nonpositive", "expired"])
def test_EV_replay_cash_and_held_share_conservation_are_independent_guards(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    original = simulate_outcome

    def corrupted(*args: Any, **kwargs: Any) -> Outcome:
        item = original(*args, **kwargs)
        if fault == "expired":
            return not_filled(item)
        assert item.entry_fill and item.exit_fill
        if fault == "cash":
            return changed_result(
                item, entry_fill=item.entry_fill.model_copy(update={"price": D(20000)})
            )
        if fault == "exit_qty":
            return changed_result(
                item,
                exit_fill=item.exit_fill.model_copy(
                    update={"qty": item.exit_fill.qty + 1, "requested_qty": item.exit_fill.qty + 1}
                ),
            )
        return changed_result(
            item,
            exit_fees=FeeBreakdown(
                commission=D(20000), sec=D(0), taf=D(0), cat=D(0), source="MODELED"
            ),
        )

    monkeypatch.setattr(module, "_simulate", corrupted)
    if fault == "expired":
        value = golden.run(golden.request(), inputs, calendar)
        assert value.decisions and all(row.outcome.entry_fill is None for row in value.decisions)
        assert all(point.equity == D(10000) for point in value.portfolio)
    else:
        message = {
            "cash": "entry exceeds",
            "exit_qty": "exit exceeds",
            "nonpositive": "equity is nonpositive",
        }[fault]
        with pytest.raises(DataIntegrityError, match=message):
            golden.run(golden.request(), inputs, calendar)


def test_EV_final_cro_authority_escalates_replay_state(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluate = ChiefRiskOfficer.evaluate

    def halted(*args: Any, **kwargs: Any) -> Verdict:
        actual = evaluate(*args, **kwargs)
        return Verdict.model_validate(
            actual.model_copy(
                update={"decision": Decision.VETOED, "recommended_state": SystemState.HALTED}
            )
        )

    monkeypatch.setattr(ChiefRiskOfficer, "evaluate", halted)
    value = golden.run(golden.request(), inputs, calendar)
    assert value.final_state == SystemState.HALTED
    assert value.decisions and all(
        row.verdict.decision == Decision.VETOED for row in value.decisions
    )
    assert all(point.equity == D(10000) for point in value.portfolio)


@pytest.mark.parametrize("fault", ["pending_integer", "pending_fractional", "held_fractional"])
def test_EV_split_reservations_and_held_shares_use_whole_native_units(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    baseline = golden.run(golden.request(), inputs, calendar).decisions[0].outcome
    day = date(2026, 10, 1) if fault == "held_fractional" else date(2026, 9, 30)
    ratio = D(2) if fault == "pending_integer" else D(".01")
    action = KnownSplit(symbol="NVDA", effective_session=day, new_shares_per_old=ratio)
    series: list[HistorySeries] = []
    for symbol in (*golden.request().symbols, "SPY"):
        native = inputs[0].bundle.for_symbol(symbol, "RAW")
        adjusted = tuple(
            Bar.model_validate(
                row.model_copy(
                    update={
                        "open": row.open * ratio,
                        "high": row.high * ratio,
                        "low": row.low * ratio,
                        "close": row.close * ratio,
                    }
                )
            )
            if symbol == "NVDA" and row.session_date >= day
            else row
            for row in native.bars
        )
        series.extend(
            (
                native,
                HistorySeries(symbol=symbol, adjustment="SPLIT", bars=adjusted),
                HistorySeries(symbol=symbol, adjustment="ALL", bars=adjusted),
            )
        )
    observed = frozen(HistoryBundle(series=tuple(series), splits=(action,)))
    worker = module._worker

    def available(*args: Any, **kwargs: Any) -> Any:
        gates, timeline = worker(*args, **kwargs)
        first = next(row for row in gates.days if row.session == baseline.setup.decision_session)
        # A fake scanner continues examining the pending symbol on subsequent
        # closes, allowing the actual reservation boundary to validate the split.
        rows = tuple(
            row.model_copy(update={"evidence": first.evidence}) if row.session >= day else row
            for row in gates.days
        )
        return gates.model_copy(update={"days": rows}), timeline

    def pending(*args: Any, **kwargs: Any) -> Outcome:
        template = baseline.model_copy(
            update={"setup": args[0], "manifest_sha256": observed.manifest.sha256}
        )
        if fault == "held_fractional":
            return changed_result(template, exit_session=date(2026, 10, 2))
        return not_filled(template)

    monkeypatch.setattr(module, "_worker", available)
    monkeypatch.setattr(module, "_simulate", pending)
    settings = Settings(proposal_ttl_sessions=3)
    if fault == "pending_integer":
        value = golden.run(golden.request(), (observed, inputs[1]), calendar, settings=settings)
        assert value.decisions and all(row.outcome.entry_fill is None for row in value.decisions)
    else:
        message = "held split" if fault == "held_fractional" else "pending split"
        with pytest.raises(DataIntegrityError, match=message):
            golden.run(golden.request(), (observed, inputs[1]), calendar, settings=settings)
