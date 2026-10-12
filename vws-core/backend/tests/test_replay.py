"""EV-03: actual frozen replay, deterministic merge and date-bound accounting."""

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.core.config import Settings, load_yaml_config
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.data_layer import AsyncAlpacaMarketData, Bar
from backend.data.fee_schedule import load_fee_schedule
from backend.data.frozen_filings import FilingEvidence, FrozenFilings, seal_filings
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries, seal_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import CapitalStatus, Decision, DeployableCapital
from backend.evaluation.replay import ReplayRequest, ReplayRun, replay
from backend.tests.test_fundamentals import evidence, synthetic

D = Decimal
PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


@pytest.fixture
def inputs(tmp_path: Path, calendar: MarketCalendar) -> tuple[FrozenHistory, FrozenFilings]:
    raw = json.loads((PROJECT / "backend/tests/fixtures/offline_nvda.json").read_text())
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in raw["bars"])
    # A real hunter candidate on Sep29, followed by a trade-through target day.
    first = calendar.add_sessions(bars[-1].session_date, 1)
    tail = tuple(
        Bar(
            timestamp=calendar.session_open(calendar.add_sessions(first, i))
            - timedelta(hours=5, minutes=30),
            open=D(100),
            high=D(120),
            low=D(99),
            close=D(101),
            volume=500000,
        )
        for i in range(6)
    )
    symbols = ("MSFT", "NVDA")
    history = seal_history(
        tmp_path,
        HistoryBundle(
            series=tuple(
                HistorySeries(symbol=symbol, adjustment=adj, bars=(*bars, *tail))
                for symbol in (*symbols, "SPY")
                for adj in ("ALL", "RAW", "SPLIT")
            )
        ),
        calendar,
    )
    filings = seal_filings(
        tmp_path,
        tuple(FilingEvidence(symbol=symbol, payload=evidence(synthetic())) for symbol in symbols),
    )
    return history, filings


def request(**values: object) -> ReplayRequest:
    return ReplayRequest.model_validate(
        {
            "start": date(2026, 9, 29),
            "end": date(2026, 10, 5),
            "symbols": ("MSFT", "NVDA"),
            "initial_equity": D(10000),
            "funding": DeployableCapital(
                checking_used=D(11500),
                buffer=D(1500),
                reserved=D(0),
                deployable=D(10000),
                status=CapitalStatus.OK,
            ),
            **values,
        }
    )


def run(
    seed: ReplayRequest,
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    *,
    workers: int = 1,
    settings: Settings | None = None,
) -> ReplayRun:
    registry = InstrumentRegistry.from_csv(PROJECT / "config")
    config = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    return replay(
        seed,
        *inputs,
        settings or Settings(),
        config,
        registry,
        calendar,
        load_fee_schedule(PROJECT / "config/fees.yaml"),
        workers=workers,
    )


def test_EV_03_frozen_actual_replay_has_costs_cro_evidence_and_closed_portfolio(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
) -> None:
    result = run(request(), inputs, calendar)
    assert result.decisions and any(
        item.verdict.decision == Decision.APPROVED for item in result.decisions
    )
    assert result.manifest_sha256 == inputs[0].manifest.sha256
    assert result.filings_manifest_sha256 == inputs[1].manifest.sha256
    assert result.portfolio[0].equity == D(10000)
    approved = tuple(
        item.outcome for item in result.decisions if item.verdict.decision == Decision.APPROVED
    )
    assert all(item.exit_session is not None for item in approved)
    assert result.portfolio[-1].equity == D(10000) + sum(
        (item.net_money or D(0) for item in approved), D(0)
    )
    assert result.report.context.cohort == "REPLAY_IN_SAMPLE"
    assert result.sha256 == run(request(), inputs, calendar).sha256


def test_PF_03_real_process_pool_merge_matches_one_worker(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
) -> None:
    assert (
        run(request(), inputs, calendar, workers=2).sha256
        == run(request(), inputs, calendar).sha256
    )


def test_EV_03_end_date_cannot_resolve_from_later_stored_bars(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
) -> None:
    result = run(request(end=date(2026, 9, 30)), inputs, calendar)
    assert all(
        item.outcome.exit_session is None or item.outcome.exit_session <= date(2026, 9, 30)
        for item in result.decisions
    )
    assert result.report.context.end == date(2026, 9, 30)


def test_EV_03_drawdown_cancels_pending_entries_and_still_records_held_stop(
    tmp_path: Path,
    calendar: MarketCalendar,
) -> None:
    original = json.loads((PROJECT / "backend/tests/fixtures/offline_nvda.json").read_text())
    prefix = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in original["bars"])
    series: list[HistorySeries] = []
    for symbol in ("AMZN", "NVDA"):
        tail: list[Bar] = []
        for i in range(5):
            day = calendar.add_sessions(prefix[-1].session_date, i + 1)
            o, h, low, c = (
                (("101.50", "101.70", "101.50", "101.50") if i == 0 else ("5", "6", "4", "5"))
                if symbol == "AMZN"
                else (("102", "103", "101.76", "102") if i < 2 else ("100", "120", "99", "100"))
            )
            tail.append(
                Bar(
                    timestamp=calendar.session_open(day) - timedelta(hours=5, minutes=30),
                    open=D(o),
                    high=D(h),
                    low=D(low),
                    close=D(c),
                    volume=500000,
                )
            )
        series.extend(
            HistorySeries(symbol=symbol, adjustment=adj, bars=(*prefix, *tail))
            for adj in ("ALL", "RAW", "SPLIT")
        )
    spy = tuple(
        Bar(
            timestamp=bar.timestamp,
            open=D(100),
            high=D(101),
            low=D(99),
            close=D(100),
            volume=10000000,
        )
        for bar in series[0].bars
    )
    series.extend(
        HistorySeries(symbol="SPY", adjustment=adj, bars=spy) for adj in ("ALL", "RAW", "SPLIT")
    )
    frozen = seal_history(tmp_path, HistoryBundle(series=tuple(series)), calendar)
    facts = seal_filings(
        tmp_path,
        tuple(
            FilingEvidence(symbol=symbol, payload=evidence(synthetic()))
            for symbol in ("AMZN", "NVDA")
        ),
    )
    result = run(
        request(symbols=("AMZN", "NVDA")),
        (frozen, facts),
        calendar,
        settings=Settings(proposal_ttl_sessions=3),
    )
    canceled = tuple(item for item in result.decisions if item.entry_canceled_on is not None)
    assert canceled, (
        result.final_state,
        tuple(
            (
                item.outcome.setup.symbol,
                item.outcome.setup.limit,
                item.outcome.setup.qty,
                item.outcome.setup.stop,
                item.outcome.reason,
                item.outcome.entry_session,
                item.outcome.exit_session,
                item.outcome.setup.disposition,
            )
            for item in result.decisions
        ),
    )
    assert all(
        item.outcome.entry_fill is None and item.outcome.reason == "ENTRY_HALTED"
        for item in canceled
    )
    assert any(
        item.outcome.setup.symbol == "NVDA" and item.entry_canceled_on == date(2026, 10, 1)
        for item in canceled
    )
    assert any(
        item.outcome.setup.symbol == "AMZN"
        and item.outcome.reason == "GAP_STOP"
        and item.outcome.exit_session == date(2026, 10, 1)
        for item in result.decisions
    )
    assert result.final_state in {SystemState.REDUCE_ONLY, SystemState.HALTED}
    assert result.portfolio[-1].equity == D(10000) + sum(
        (
            item.outcome.net_money or D(0)
            for item in result.decisions
            if item.verdict.decision == Decision.APPROVED
        ),
        D(0),
    )


def test_EV_03_missing_fundamentals_are_skipped_never_counted_as_pass(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run(request(), (inputs[0], seal_filings(empty, ())), calendar)
    assert result.unavailable_fundamentals > 0 and result.decisions == ()
    assert all(point.equity == D(10000) for point in result.portfolio)


def test_EV_03_buffer_breach_is_an_actual_cro_shadow_not_a_fake_approval(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
) -> None:
    seed = request(
        funding=DeployableCapital(
            checking_used=D(1),
            buffer=D(1500),
            reserved=D(0),
            deployable=D(0),
            status=CapitalStatus.BUFFER_BREACH,
        )
    )
    result = run(seed, inputs, calendar)
    assert result.decisions and all(
        item.outcome.setup.disposition == "CRO_VETO" for item in result.decisions
    )
    assert all(point.equity == D(10000) for point in result.portfolio)
    assert all(
        any(rule.rule_id == "CRO-12" and not rule.passed for rule in item.verdict.results)
        for item in result.decisions
    )


@pytest.mark.parametrize(
    "fault", ["unknown_symbol", "missing_history", "window", "workers", "config_hash"]
)
def test_EV_03_unverified_replay_inputs_are_refused(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    fault: str,
) -> None:
    seed = request(
        symbols=("FAKE",)
        if fault == "unknown_symbol"
        else ("AAPL",)
        if fault == "missing_history"
        else ("MSFT", "NVDA")
    )
    if fault == "window":
        seed = request(start=date(2026, 10, 5), end=date(2026, 10, 6))
        seed = seed.model_copy(update={"start": date(2026, 10, 6)})
    data = inputs
    if fault == "config_hash":
        data = (
            inputs[0].model_copy(
                update={"manifest": inputs[0].manifest.model_copy(update={"splits": ({},)})}
            ),
            inputs[1],
        )
    with pytest.raises(DataIntegrityError):
        run(seed, data, calendar, workers=0 if fault == "workers" else 1)
