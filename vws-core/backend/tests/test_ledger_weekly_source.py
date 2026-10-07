"""EV: actual research rows, saved quote costs and the real weekly publisher."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from backend.agents.anchors import select_anchor
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.data_layer import AsyncAlpacaMarketData, Bar
from backend.data.fee_schedule import load_fee_schedule
from backend.data.historical_spread import SpreadMeasurement, _result
from backend.data.history import HistoryBundle, HistorySeries, seal_history
from backend.domain.models import ProviderStatus
from backend.evaluation.ledger_inputs import collect_tracked_setups
from backend.evaluation.ledger_source import LedgerWeeklySource, WeeklyHistory
from backend.evaluation.publication import WeeklyPublisher
from backend.evaluation.weekly import ReportContext
from backend.tests.test_swarm_and_callbacks import (  # noqa: F401
    Harness,
    make_research_harness,
)
from backend.tests.test_weekly_publication import Notices

D = Decimal


class HistorySource:
    def __init__(self, value: WeeklyHistory) -> None:
        self.value = value

    async def weekly_history(self) -> WeeklyHistory:
        return self.value


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{"proposal_ttl_sessions": 3}], indirect=True)
async def test_EV_actual_ledger_weekly_source_retains_decision_costs(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    cal = h.swarm.risk.cro.calendar
    day = h.clock.now().date()
    evidence_day = cal.previous_sessions(day, 1)[0]
    spread = _result("NVDA", evidence_day, h.clock.now(), (D(25),), "fixed observed SIP fixture")
    request = h.request.model_copy(update={"spread_measurement": spread})
    assert (await h.swarm.run(request)).status == "ALERT"
    with h.state.engine.connect() as connection:
        from sqlalchemy import select

        from backend.core.database import DataSnapshot

        payload = connection.execute(select(DataSnapshot.bars)).scalar_one()
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in payload)
    # This later range must not be used to recompute the original ATR/spread.
    tail = tuple(
        Bar(
            timestamp=cal.session_open(cal.add_sessions(evidence_day, i))
            - timedelta(hours=5, minutes=30),
            open=D("101.50"),
            high=D(1000),
            low=D(100),
            close=D("101.50"),
            volume=1000000,
        )
        for i in (1, 2, 3)
    )
    frozen = seal_history(
        tmp_path,
        HistoryBundle(
            series=tuple(
                HistorySeries(symbol="NVDA", adjustment=adj, bars=(*bars, *tail))
                for adj in ("ALL", "RAW", "SPLIT")
            )
        ),
        cal,
    )
    context = ReportContext(
        account_id=h.request.portfolio.account_id,
        cohort="PAPER",
        start=day,
        end=tail[1].session_date,
        config_sha256=h.config.config_hash,
    )
    fees = load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")
    source = LedgerWeeklySource(
        h.state,
        h.settings,
        h.config,
        context.account_id,
        cal,
        HistorySource(WeeklyHistory(context=context, history=frozen)),
        fees,
    )
    h.clock.current = datetime(2026, 10, 5, 22, tzinfo=UTC)
    bound = await source.weekly_inputs()
    tracked = collect_tracked_setups(h.state.ledger, h.settings, context, cal)
    assert len(tracked) == len(bound.outcomes) == 1
    proof = tracked[0].provenance
    assert proof.spread_measurement == spread
    assert proof.cost_context.measured_half_spread_bps == D(25)
    original_atr = h.swarm.hunter.memo.calculate("NVDA", bars, select_anchor(bars)[0]).atr14[-1]
    assert proof.cost_context.atr14 == original_atr
    assert bound.context.initial_equity == D(10000)
    outcome = bound.outcomes[0]
    assert outcome.entry_fill is not None and outcome.entry_fill.half_spread_bps == D(25)
    assert outcome.exit_session is not None and outcome.exit_session <= context.end
    notices = Notices()
    publisher = WeeklyPublisher(
        h.state, h.settings, h.config, context.account_id, cal, tmp_path, source, notices.notify
    )
    counts = await publisher()
    assert counts.counts["resolved"] == 1 and notices.calls
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["issuer", "session", "future"])
async def test_CM_01_research_rejects_unbound_quote_measurement(
    harness: Harness, fault: str
) -> None:
    h = harness
    day = h.swarm.risk.cro.calendar.previous_sessions(h.clock.now().date(), 1)[0]
    values: dict[str, Any] = _result(
        "NVDA", day, h.clock.now(), (D(25),), "fixed SIP fixture"
    ).model_dump()
    if fault == "issuer":
        values["symbol"] = "MSFT"
    elif fault == "session":
        values = _result(
            "NVDA",
            h.swarm.risk.cro.calendar.previous_sessions(day, 1)[0],
            h.clock.now(),
            (D(25),),
            "old quote fixture",
        ).model_dump()
    else:
        values["fetched_at"] = h.clock.now() + timedelta(seconds=1)
    measurement = SpreadMeasurement.model_validate(values)
    with pytest.raises(DataIntegrityError):
        await h.swarm.run(h.request.model_copy(update={"spread_measurement": measurement}))
    assert h.state.current() == SystemState.HALTED


def test_CM_01_unavailable_measurement_cannot_claim_observed_spread(harness: Harness) -> None:
    spread = _result("NVDA", harness.clock.now().date(), harness.clock.now(), (), "no quotes")
    assert spread.status == ProviderStatus.UNAVAILABLE and spread.half_spread_bps is None
