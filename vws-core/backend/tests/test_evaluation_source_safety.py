"""EV-02: managed-account, cost-policy and opening-equity bindings."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.data.fee_schedule import load_fee_schedule
from backend.data.history import FrozenHistory
from backend.evaluation import ledger_source as module
from backend.evaluation.ledger_inputs import collect_tracked_setups
from backend.evaluation.ledger_source import LedgerWeeklySource, WeeklyHistory
from backend.tests import test_ledger_evaluation as ledger_golden
from backend.tests import test_weekly_equity as golden
from backend.tests.test_ledger_weekly_source import HistorySource
from backend.tests.test_swarm_and_callbacks import Harness, deliver
from backend.tests.test_swarm_and_callbacks import make_research_harness as make_research_harness

history = golden.history


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["account", "mode", "config", "baseline", "cost", "missing_history"]
)
async def test_EV_source_refuses_each_managed_policy_mismatch(
    harness: Harness, history: FrozenHistory, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    h = harness
    await deliver(h)
    tracked = collect_tracked_setups(
        h.state.ledger, h.settings, ledger_golden.scope(h), h.swarm.risk.cro.calendar
    )
    context = golden.context(
        account_id=h.request.portfolio.account_id,
        config_sha256=h.config.config_hash,
        initial_equity=None,
    )
    source = LedgerWeeklySource(
        h.state,
        h.settings,
        h.config,
        context.account_id,
        h.swarm.risk.cro.calendar,
        HistorySource(WeeklyHistory(context=context, history=history)),
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
    )
    h.clock.current += timedelta(days=15)
    if fault == "account":
        context = context.model_copy(update={"account_id": "other"})
    elif fault == "mode":
        context = context.model_copy(update={"cohort": "LIVE"})
    elif fault == "config":
        context = context.model_copy(update={"config_sha256": "f" * 64})
    elif fault == "baseline":
        context = context.model_copy(update={"initial_equity": Decimal(100)})
    elif fault == "cost":
        item = tracked[0]
        policy = h.config.cm.model_copy(update={"stop_slip_atr_frac": Decimal(".10")})
        cost = item.provenance.cost_context.model_copy(update={"policy": policy})
        rows = (
            item.model_copy(
                update={"provenance": item.provenance.model_copy(update={"cost_context": cost})}
            ),
        )
        monkeypatch.setattr(module, "collect_tracked_setups", lambda *args: rows)
    else:

        def unavailable(*args: Any, **kwargs: Any) -> Any:
            raise DataIntegrityError("fixture history is unavailable")

        monkeypatch.setattr(module, "validate_history", unavailable)
    with pytest.raises(DataIntegrityError):
        source._build(WeeklyHistory(context=context, history=history))
    with pytest.raises(ConfigurationError):
        LedgerWeeklySource(
            h.state,
            h.settings,
            h.config,
            "",
            h.swarm.risk.cro.calendar,
            source.history_source,
            source.fees,
        )


@pytest.mark.asyncio
async def test_EV_missing_or_zero_earliest_equity_remains_unavailable(
    harness: Harness, history: FrozenHistory, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    await deliver(h)
    tracked = collect_tracked_setups(
        h.state.ledger, h.settings, ledger_golden.scope(h), h.swarm.risk.cro.calendar
    )
    item = tracked[0]
    candidate = item.setup.model_copy(
        update={
            "symbol": "AAPL",
            "decision_session": golden.START,
            "valid_until_session": golden.END,
        }
    )
    row = item.model_copy(
        update={
            "setup": candidate,
            "provenance": item.provenance.model_copy(update={"initial_equity": Decimal(0)}),
        }
    )
    context = golden.context(
        account_id=h.request.portfolio.account_id,
        config_sha256=h.config.config_hash,
        initial_equity=None,
    )
    source = LedgerWeeklySource(
        h.state,
        h.settings,
        h.config,
        context.account_id,
        h.swarm.risk.cro.calendar,
        HistorySource(WeeklyHistory(context=context, history=history)),
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
    )
    h.clock.current += timedelta(days=15)
    monkeypatch.setattr(module, "collect_tracked_setups", lambda *args: ())
    empty = source._build(WeeklyHistory(context=context, history=history))
    assert empty.context.initial_equity is None and not empty.outcomes
    monkeypatch.setattr(module, "collect_tracked_setups", lambda *args: (row,))
    value = source._build(WeeklyHistory(context=context, history=history))
    assert value.context.initial_equity is None
