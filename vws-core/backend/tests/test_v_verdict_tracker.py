"""GV: actual immutable weekly fallback, complete benchmark and unavailable evidence."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from backend.core.clock import FrozenClock
from backend.core.config import YamlConfig
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.outcomes import Outcome, OutcomeSetup
from backend.evaluation.verdict import VerdictInputs, evaluate
from backend.evaluation.verdict_source import collect
from backend.ops.trading_controls import ControlScope
from backend.tests.test_outcomes_history import frozen
from backend.tests.test_weekly_publication import calendar as source_calendar
from backend.tests.test_weekly_publication import composition, edge_outcomes
from backend.tests.test_weekly_publication import history as source_history
from backend.tests.test_weekly_publication import results as source_results

calendar, history, results = source_calendar, source_history, source_results
__all__ = ["edge_outcomes"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "complete",
        "no_history",
        "no_spy",
        "stale",
        "changed_policy",
        "shadow_only",
        "incidents",
        "future_history",
        "current_variant",
        "missing_spy_date",
        "unavailable_equity",
    ],
)
async def test_GV_recorded_hypothetical_fallback_never_invents_missing_inputs(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    case: str,
) -> None:
    if case != "no_spy":
        history = frozen(
            HistoryBundle(
                series=(
                    *history.bundle.series,
                    *(
                        HistorySeries(symbol="SPY", adjustment=row.adjustment, bars=row.bars)
                        for row in history.bundle.series
                        if row.symbol == "AAPL"
                    ),
                )
            )
        )
    if case == "missing_spy_date":
        history = frozen(
            HistoryBundle(
                series=tuple(
                    row.model_copy(update={"bars": row.bars[1:]}) if row.symbol == "SPY" else row
                    for row in history.bundle.series
                )
            )
        )
    outcomes = tuple(
        Outcome.model_validate(
            {
                **row.model_dump(),
                "manifest_sha256": history.manifest.sha256,
                "setup": OutcomeSetup.model_validate(
                    {**row.setup.model_dump(), "disposition": "CRO_VETO"}
                )
                if case == "shadow_only"
                else row.setup,
            }
        )
        for row in results
    )
    publisher, source, _ = composition(engine, tmp_path, calendar, history, outcomes)
    if case == "current_variant":
        from backend.evaluation.publication import WeeklyInputs

        values = publisher.config.model_dump()
        values["exits"]["variant"] = "TRAIL_EMA20"
        publisher.config = YamlConfig.model_validate(values)
        source.values = WeeklyInputs.model_validate(
            source.values.model_copy(
                update={
                    "context": source.values.context.model_copy(
                        update={"config_sha256": publisher.config.config_hash}
                    ),
                    "outcomes": tuple(
                        Outcome.model_validate(
                            row.model_copy(
                                update={
                                    "setup": row.setup.model_copy(update={"variant": "TRAIL_EMA20"})
                                }
                            )
                        )
                        for row in outcomes
                    ),
                }
            )
        )
    elif case == "unavailable_equity":
        from backend.evaluation.publication import WeeklyInputs

        source.values = WeeklyInputs.model_validate(
            source.values.model_copy(
                update={
                    "context": source.values.context.model_copy(
                        update={"initial_equity": Decimal("0.01")}
                    )
                }
            )
        )
    await publisher()
    settings, config, ledger = publisher.settings, publisher.config, publisher.state.ledger
    if case == "changed_policy":
        config = YamlConfig.model_validate(
            {**config.model_dump(), "exits": {"variant": "TRAIL_EMA20"}}
        )
    elif case == "stale":
        ledger.clock = FrozenClock(ledger.clock.now() + timedelta(days=1))
    elif case == "future_history":
        future = calendar.add_sessions(history.manifest.entries[0].sessions[-1], 1)
        history = frozen(
            HistoryBundle(
                series=tuple(
                    HistorySeries(
                        symbol=row.symbol,
                        adjustment=row.adjustment,
                        bars=(
                            *row.bars,
                            row.bars[-1].model_copy(
                                update={
                                    "timestamp": calendar.session_open(future)
                                    - timedelta(hours=5, minutes=30)
                                }
                            ),
                        ),
                    )
                    for row in history.bundle.series
                )
            )
        )
    elif case == "incidents":
        publisher.state.escalate(SystemState.HALTED, "reconciliation mismatch")
        ledger.append(SecurityEvent, kind="PANIC", detail={"source": "offline test"})
        for _ in range(2):
            ledger.append(SecurityEvent, kind="CIRCUIT_BREAKER_HALTED", detail={"provider": "FAKE"})

    def read() -> VerdictInputs:
        return collect(
            ledger,
            settings,
            config,
            ControlScope(account_id="paper-test", environment="PAPER"),
            calendar,
            source.values.fees,
            history=None if case == "no_history" else history,
            effective_hash=config.config_hash,
        )

    if case == "future_history":
        with pytest.raises(DataIntegrityError, match="future|incident"):
            read()
        return
    inputs = read()
    verdict = evaluate(inputs, config.gv)
    if case in {"stale", "changed_policy", "shadow_only"}:
        assert inputs.source == "UNAVAILABLE" and inputs.r_multiples == ()
    else:
        assert inputs.source == "EV_01_HYPOTHETICAL" and len(inputs.r_multiples) == 5
        assert "Hypothetical alert tracker" in verdict.text()
    if case in {"no_history", "no_spy"}:
        assert inputs.spy_total_return_sharpe is None
    if case == "no_history":
        assert inputs.drawdown is None and inputs.sessions == ()
    elif case in {"complete", "no_spy", "incidents", "current_variant", "missing_spy_date"}:
        assert inputs.drawdown is not None and len(inputs.sessions) == 6
    if case == "incidents":
        assert verdict.status == "STOP" and len(verdict.stop_reasons) >= 3
    else:
        assert verdict.status == "NOT_YET"
    assert not inputs.security_green and inputs.recent_fault_free_sessions in {0, None}
    assert "LIVE_ENABLED" not in verdict.text()
