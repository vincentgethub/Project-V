"""EV-02: independent cash/mark goldens, report numbers, cohorts and file safety."""

import csv
import hashlib
import io
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.config import CostModelConfig
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.fee_schedule import load_fee_schedule
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries
from backend.data.market_calendar import MarketCalendar
from backend.domain.tax_profile import TaxProfile
from backend.evaluation.costs import CostContext
from backend.evaluation.equity import EquityBuild, build_equity_curve
from backend.evaluation.outcomes import REPLAY_NOTES, Outcome, simulate_outcome
from backend.evaluation.weekly import (
    DISCLAIMER,
    SURVIVORSHIP_NOTICE,
    ReportContext,
    WeeklyReport,
    build_weekly_report,
    render_weekly,
    report_csv,
    save_report,
)
from backend.tests.test_edge import KEY, october
from backend.tests.test_edge import outcomes as edge_outcomes  # noqa: F401
from backend.tests.test_outcomes_history import bar, bundle, frozen, setup

D = Decimal
START, END = date(2026, 9, 30), date(2026, 10, 8)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 9, 1), end=date(2026, 11, 30))


@pytest.fixture(scope="module")
def history() -> FrozenHistory:
    anchor = Bar(
        timestamp=datetime(2026, 9, 30, 4, tzinfo=UTC),
        open=D("7.95"),
        high=D(8),
        low=D("7.9"),
        close=D("7.95"),
        volume=10000,
    )
    return frozen(
        bundle(
            (
                anchor,
                october(1, high="10"),
                october(2, low="6.99"),
                october(5),
                october(6, opening="8.50", high="8.51", low="8.49", closing="8.50"),
                october(7, low="6.99"),
                october(8, high="11"),
            )
        )
    )


@pytest.fixture(scope="module")
def results(edge_outcomes: tuple[Outcome, ...]) -> tuple[Outcome, ...]:  # noqa: F811
    return edge_outcomes


def context(**values: Any) -> ReportContext:
    return ReportContext.model_validate(
        {
            "account_id": "paper-test",
            "cohort": "PAPER",
            "start": START,
            "end": END,
            "config_sha256": "a" * 64,
            "initial_equity": D(100),
            **values,
        }
    )


def weekly(
    rows: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    *,
    ctx: ReportContext | None = None,
    profile: TaxProfile | None = None,
) -> WeeklyReport:
    return build_weekly_report(
        ctx or context(),
        rows,
        history,
        calendar,
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
        CostModelConfig(),
        profile or TaxProfile(),
    )


def test_EV_02_daily_mark_to_market_and_closed_trade_totals_independent(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    built = build_equity_curve(
        KEY, results, history, calendar, initial_equity=D(100), start=START, end=END
    )
    assert built.curve is not None and built.status == "AVAILABLE"
    assert tuple(point.equity for point in built.curve.points) == tuple(
        D(value) for value in ("100", "102", "101", "100.98", "101.5", "100.5", "103.5")
    )
    assert built.curve.exposed_sessions == 6
    assert EquityBuild.model_validate(built) == built
    report = weekly(
        results,
        history,
        calendar,
        profile=TaxProfile(federal_st_rate=D(".24"), federal_lt_rate=D(".15")),
    )
    assert len(report.cards) == 2
    for card in report.cards:
        assert card.n == 5 and card.expectancy_r == D(".7") and card.expectancy_money == D(".7")
        assert card.fill_rate == 1 and card.win_rate == D(".6") and card.profit_factor == D("2.75")
        assert (
            card.grade == "UNPROVEN"
            and card.drawdown_duration_sessions == 4
            and card.time_exposed_pct == 100
        )
        with localcontext() as precision:
            precision.prec = 80
            assert card.max_drawdown_pct == D("1.5") / 102 * 100
    assert all(
        row.net_gains == D("3.5") and row.rough_after_tax == D("2.66") for row in report.tax_years
    )
    assert (
        report.sha256
        == weekly(
            tuple(reversed(results)),
            history,
            calendar,
            profile=TaxProfile(federal_st_rate=D(".24"), federal_lt_rate=D(".15")),
        ).sha256
    )
    text = render_weekly(report)
    assert "too few trades to judge" in text and DISCLAIMER in text and "$0.70" in text
    assert "$2.66" in text and "paper/live labels" in text and "Dividends" not in text
    masked = render_weekly(report, mask_amounts=True)
    assert "$0.70" not in masked and "$2.66" not in masked and "$•••" in masked


def test_EV_02_csv_recomputable_metrics_and_write_once_proof(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar, tmp_path: Path
) -> None:
    report = weekly(results, history, calendar)
    rows = tuple(csv.DictReader(io.StringIO(report_csv(report).decode())))
    overall = next(
        row for row in rows if row["record_type"] == "edge" and row["fundamentals_status"] == "n/a"
    )
    assert overall["n"] == "5" and D(overall["expectancy_r"]) == D(".7")
    assert (
        D(overall["profit_factor"]) == D("2.75")
        and overall["manifest_sha256"] == history.manifest.sha256
    )
    assert all(row["rough_after_tax"] == "n/a" for row in rows if row["record_type"] == "tax")
    paths = save_report(tmp_path, report)
    assert paths == save_report(tmp_path, report)
    assert paths[1].read_bytes() == report_csv(report)
    assert hashlib.sha256(paths[0].read_bytes()).hexdigest() == report.sha256
    paths[1].write_bytes(b"tampered")
    with pytest.raises(DataIntegrityError):
        save_report(tmp_path, report)
    assert paths[1].read_bytes() == b"tampered"
    with pytest.raises(DataIntegrityError):
        save_report(tmp_path / "missing", report)
    injected = weekly(results, history, calendar, ctx=context(account_id="=unsafe"))
    assert "'=unsafe" in report_csv(injected).decode()


def test_EV_02_missing_equity_and_empty_report_never_invent_zero_metrics(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    report = weekly(results, history, calendar, ctx=context(initial_equity=None))
    assert all(card.equity_metrics_status == "UNAVAILABLE" for card in report.cards)
    assert report.spy_buy_hold_pct is None
    assert "SPY ALL buy-and-hold: n/a" in render_weekly(report)
    assert "Initial equity unavailable" in render_weekly(report)
    empty = weekly((), history, calendar)
    assert empty.cards == () and "No eligible recorded outcomes" in render_weekly(empty)
    assert "Dividends ignored" not in render_weekly(
        empty
    )  # exact source notice stays explicit below
    assert "Strategy dividends ignored" in render_weekly(empty)


@pytest.mark.parametrize(
    "change",
    [
        {"cohort": "LIVE"},
        {"start": date(2026, 10, 1)},
        {"end": date(2026, 10, 7)},
        {"end": date(2026, 10, 10)},
    ],
)
def test_EV_02_wrong_scope_or_period_is_refused(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    change: dict[str, Any],
) -> None:
    with pytest.raises(DataIntegrityError):
        weekly(results, history, calendar, ctx=context(**change))


def test_EV_02_report_metadata_revalidates_and_policy_binding_is_required(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    report = weekly(results, history, calendar)
    for change in (
        {"notes": report.notes[1:]},
        {"cards": tuple(reversed(report.cards))},
        {"context": context(cohort="LIVE")},
        {"equity_notes": ()},
    ):
        with pytest.raises(ValidationError):
            WeeklyReport.model_validate(report.model_copy(update=change))
    with pytest.raises(DataIntegrityError):
        render_weekly(report, mask_amounts="yes")  # type: ignore[arg-type]
    with pytest.raises(DataIntegrityError):
        weekly((*results, results[0]), history, calendar)
    forged = results[0].model_copy(update={"cost_policy_sha256": "f" * 64})
    with pytest.raises(DataIntegrityError):
        weekly((forged, *results[1:]), history, calendar)
    with pytest.raises(ValidationError):
        context(end=START)
    built = build_equity_curve(
        KEY, results, history, calendar, initial_equity=D(100), start=START, end=END
    )
    with pytest.raises(ValidationError):
        EquityBuild.model_validate(built.model_copy(update={"curve": None}))


@pytest.mark.parametrize(
    "initial,start,end",
    [
        (100.0, START, END),
        (D(0), START, END),
        (D("100.001"), START, END),
        (D(100), END, START),
        (D(100), date(2026, 10, 3), END),
    ],
)
def test_EV_02_bad_equity_inputs_refused(
    results: tuple[Outcome, ...],
    history: FrozenHistory,
    calendar: MarketCalendar,
    initial: Any,
    start: date,
    end: date,
) -> None:
    with pytest.raises(DataIntegrityError):
        build_equity_curve(
            KEY, results, history, calendar, initial_equity=initial, start=start, end=end
        )


def test_EV_02_unfunded_or_incomplete_outcomes_make_equity_unavailable(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    built = build_equity_curve(
        KEY, results, history, calendar, initial_equity=D(1), start=START, end=END
    )
    assert built.status == "UNAVAILABLE" and "available cash" in built.reason
    table = load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")
    short = frozen(bundle((bar(15), bar(16))))
    pending = simulate_outcome(setup(qty=1), short, CostContext(atr14=D(1)), calendar, table)
    assert pending.status == "OPEN"
    built = build_equity_curve(
        KEY,
        (pending,),
        short,
        calendar,
        initial_equity=D(1000),
        start=date(2026, 9, 15),
        end=date(2026, 9, 16),
    )
    assert built.curve is not None and built.curve.points[-1].equity < D(1000)


def test_EV_02_spy_all_and_filter_comparisons_use_shared_fills(
    results: tuple[Outcome, ...], history: FrozenHistory, calendar: MarketCalendar
) -> None:
    spy_raw = tuple(
        Bar(
            timestamp=bar.timestamp, open=D(100), high=D(101), low=D(99), close=D(100), volume=10000
        )
        for bar in history.bundle.for_symbol("AAPL", "RAW").bars
    )
    spy_all = (
        *spy_raw[:-1],
        spy_raw[-1].model_copy(
            update={"open": D(110), "high": D(111), "low": D(109), "close": D(110)}
        ),
    )
    added = frozen(
        HistoryBundle(
            series=(
                *history.bundle.series,
                HistorySeries(symbol="SPY", adjustment="RAW", bars=spy_raw),
                HistorySeries(symbol="SPY", adjustment="SPLIT", bars=spy_raw),
                HistorySeries(symbol="SPY", adjustment="ALL", bars=spy_all),
            )
        )
    )
    table = load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")
    rows: list[Outcome] = []
    for index, source in enumerate(results):
        intent = source.setup.model_copy(
            update={"disposition": "CRO_VETO" if index == 1 else "APPROVED"}
        )
        rows.append(
            simulate_outcome(
                intent,
                added,
                CostContext(atr14=D(".01"), median_dollar_volume_20=D(500_000_000)),
                calendar,
                table,
                signal_exit_session=date(2026, 10, 5) if source.reason == "SIGNAL" else None,
            )
        )
    report = weekly(tuple(rows), added, calendar)
    assert report.spy_buy_hold_pct == D(10)
    assert len(report.filters) == 1
    comparison = report.filters[0]
    assert comparison.taken_n == 4 and comparison.filtered_n == 1
    assert comparison.taken_expectancy_r == D("1.125") and comparison.filtered_expectancy_r == -1
    assert "Filter CRO_VETO" in render_weekly(report)
    replay_rows = tuple(
        row.model_copy(
            update={
                "setup": row.setup.model_copy(update={"cohort": "REPLAY_IN_SAMPLE"}),
                "notes": REPLAY_NOTES,
            }
        )
        for row in rows
    )
    replay = weekly(replay_rows, added, calendar, ctx=context(cohort="REPLAY_IN_SAMPLE"))
    assert SURVIVORSHIP_NOTICE in render_weekly(replay)
