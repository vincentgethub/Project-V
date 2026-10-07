"""ER goldens from the real CM/EV pipeline, never an alternate fill model."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.agents.fundamentals import FrameworkStatus
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.fee_schedule import load_fee_schedule
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import Playbook
from backend.evaluation.costs import CostContext
from backend.evaluation.edge import (
    EdgeCard,
    EdgeKey,
    EquityCurve,
    EquityPoint,
    ScoreBand,
    edge_grade,
    summarize_edge,
)
from backend.evaluation.outcomes import Cohort, Outcome, OutcomeSetup, simulate_outcome
from backend.indicators.statistics import BootstrapEstimate
from backend.tests.test_outcomes_history import bundle, frozen

D = Decimal
KEY = EdgeKey(
    playbook=Playbook.BASE_BREAKOUT, variant="baseline", cohort="PAPER", disposition="APPROVED"
)


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2026, 9, 1), end=date(2026, 11, 30))


def october(
    day: int, *, opening: str = "7.95", high: str = "8", low: str = "7.90", closing: str = "7.95"
) -> Bar:
    return Bar(
        timestamp=datetime(2026, 10, day, 4, tzinfo=UTC),
        open=D(opening),
        high=D(high),
        low=D(low),
        close=D(closing),
        volume=10000,
    )


@pytest.fixture(scope="module")
def outcomes(calendar: MarketCalendar) -> tuple[Outcome, ...]:
    anchor = Bar(
        timestamp=datetime(2026, 9, 30, 4, tzinfo=UTC),
        open=D("7.95"),
        high=D(8),
        low=D("7.9"),
        close=D("7.95"),
        volume=10000,
    )
    observed = frozen(
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
    table = load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml")
    context = CostContext(atr14=D("0.01"), median_dollar_volume_20=D(500_000_000))
    result: list[Outcome] = []
    cases = (
        (date(2026, 9, 30), date(2026, 10, 1), "9.99", "7.5", None),
        (date(2026, 10, 1), date(2026, 10, 2), "10", "8", None),
        (date(2026, 10, 2), date(2026, 10, 5), "10", "8.5", date(2026, 10, 5)),
        (date(2026, 10, 6), date(2026, 10, 7), "10", "9", None),
        (date(2026, 10, 7), date(2026, 10, 8), "10.99", "10", None),
    )
    for index, (decision, validity, target, score, signal) in enumerate(cases, 1):
        intent = OutcomeSetup(
            alert_id=UUID(int=index),
            symbol="AAPL",
            playbook=KEY.playbook,
            variant="baseline",
            cohort="PAPER",
            disposition="APPROVED",
            fundamentals_status=FrameworkStatus.PASS,
            score=D(score),
            qty=1,
            limit=D(8),
            stop=D(7),
            target=D(target),
            decision_session=decision,
            valid_until_session=validity,
        )
        result.append(
            simulate_outcome(intent, observed, context, calendar, table, signal_exit_session=signal)
        )
    assert tuple(item.r_multiple for item in result) == (D(2), D(-1), D("0.5"), D(-1), D(3))
    return tuple(result)


def test_ER_independent_five_trade_golden_and_score_bands(
    outcomes: tuple[Outcome, ...], calendar: MarketCalendar
) -> None:
    result = summarize_edge(KEY, outcomes, calendar=calendar)
    assert result.n == result.filled == result.alerts == 5
    assert result.fill_rate == 1 and result.win_rate == D("0.6")
    with localcontext() as precision:
        precision.prec = 80
        assert result.average_win_r == result.payoff_ratio == D("5.5") / 3
    assert result.average_loss_r == -1 and result.expectancy_r == D("0.7")
    assert result.expectancy_money == D("0.7") and result.profit_factor == D("2.75")
    assert result.average_hold == D(1) and result.grade == "UNPROVEN"
    assert result.confidence is not None and result.confidence.resamples == 10000
    assert [(band.n, band.expectancy_r) for band in result.score_bands] == [
        (1, D(2)),
        (2, D("-0.25")),
        (2, D(1)),
    ]
    assert (
        result.equity_metrics_status == "UNAVAILABLE"
        and result.max_drawdown_pct is None
        and result.sharpe is None
    )
    assert EdgeCard.model_validate(result) == result


def curve_for(outcomes: tuple[Outcome, ...]) -> EquityCurve:
    days = (date(2026, 9, 30), *(date(2026, 10, day) for day in (1, 2, 5, 6, 7, 8)))
    amounts = tuple(D(value) for value in ("100", "102", "101", "101", "101.5", "100.5", "103.5"))
    return EquityCurve(
        key=KEY,
        manifest_sha256=outcomes[0].manifest_sha256,
        alert_ids=tuple(item.setup.alert_id for item in outcomes),
        exposed_sessions=6,
        points=tuple(
            EquityPoint(session=day, equity=amount)
            for day, amount in zip(days, amounts, strict=True)
        ),
    )


def test_ER_equity_drawdown_and_exposure_independent(
    outcomes: tuple[Outcome, ...], calendar: MarketCalendar
) -> None:
    result = summarize_edge(KEY, outcomes, calendar=calendar, curve=curve_for(outcomes))
    assert result.equity_metrics_status == "AVAILABLE" and result.time_exposed_pct == 100
    assert result.drawdown_duration_sessions == 4
    with localcontext() as precision:
        precision.prec = 80
        assert result.max_drawdown_pct == D("1.5") / 102 * 100
    assert result.sharpe is not None and result.sortino is not None


@pytest.mark.parametrize(
    "count,lower,factor,cohort,dsr,expected",
    [
        (49, "0.01", "2", "PAPER", None, "UNPROVEN"),
        (50, "0", "2", "PAPER", None, "UNPROVEN"),
        (50, "0.01", "1.19", "PAPER", None, "UNPROVEN"),
        (50, "0.01", "1.2", "PAPER", None, "WORKING"),
        (50, "0.01", "1.2", "LIVE", None, "WORKING"),
        (50, "0.01", "1.2", "REPLAY_OOS", None, "UNPROVEN"),
        (50, "0.01", "1.2", "REPLAY_OOS", "0.949999", "UNPROVEN"),
        (50, "0.01", "1.2", "REPLAY_OOS", "0.95", "WORKING"),
        (50, "0.01", "1.2", "REPLAY_IN_SAMPLE", "1", "UNPROVEN"),
    ],
)
def test_ER_grade_exact_thresholds(
    count: int, lower: str, factor: str, cohort: Cohort, dsr: str | None, expected: str
) -> None:
    confidence = BootstrapEstimate(
        lower=D(lower), upper=D(1), p_nonpositive=D(0), block_length=2, seed=20261006
    )
    assert (
        edge_grade(
            (D(1),) * count, confidence, D(factor), cohort, D(dsr) if dsr is not None else None
        )
        == expected
    )


def test_ER_losing_shared_condition_and_unavailable_evidence() -> None:
    confidence = BootstrapEstimate(
        lower=D(-2), upper=D(-1), p_nonpositive=D(1), block_length=2, seed=20261006
    )
    assert edge_grade((D(0),) * 30, confidence, None, "PAPER") == "LOSING"
    assert edge_grade((D(-1),) * 30, None, None, "LIVE") == "LOSING"
    assert edge_grade((D(-1),) * 29, confidence, None, "PAPER") == "UNPROVEN"
    assert edge_grade((D(1),) * 50, None, D(2), "PAPER") == "UNPROVEN"
    assert (
        edge_grade(
            (D(1),) * 50,
            BootstrapEstimate(
                lower=D("0.1"), upper=D(2), p_nonpositive=D(0), block_length=2, seed=1
            ),
            None,
            "PAPER",
        )
        == "UNPROVEN"
    )


@pytest.mark.parametrize(
    "case",
    [
        "cohort",
        "disposition",
        "variant",
        "fundamentals",
        "manifest",
        "fees",
        "duplicate",
        "mutable",
    ],
)
def test_ER_mixed_or_forged_evidence_refused(
    case: str, outcomes: tuple[Outcome, ...], calendar: MarketCalendar
) -> None:
    first = outcomes[0]
    values = outcomes
    key = KEY
    if case in {"cohort", "disposition", "variant"}:
        replacement: dict[str, Any] = {
            "cohort": "LIVE",
            "disposition": "REJECTED",
            "variant": "other",
        }
        values = (
            first.model_copy(
                update={"setup": first.setup.model_copy(update={case: replacement[case]})}
            ),
            *outcomes[1:],
        )
    elif case == "fundamentals":
        key = KEY.model_copy(update={"fundamentals_status": FrameworkStatus.FAIL})
    elif case in {"manifest", "fees"}:
        field = "manifest_sha256" if case == "manifest" else "fee_schedule_sha256"
        values = (first.model_copy(update={field: "f" * 64}), *outcomes[1:])
    elif case == "duplicate":
        values = (*outcomes, first)
    else:
        values = list(outcomes)  # type: ignore[assignment]
    with pytest.raises(DataIntegrityError):
        summarize_edge(key, values, calendar=calendar)


def test_ER_empty_and_no_loss_metrics_are_unavailable(
    outcomes: tuple[Outcome, ...], calendar: MarketCalendar
) -> None:
    empty = summarize_edge(KEY, (), calendar=calendar)
    assert empty.n == 0 and empty.fill_rate is None and empty.win_rate is None
    assert empty.manifest_sha256 is None and empty.grade == "UNPROVEN"
    winning = summarize_edge(KEY, (outcomes[0], outcomes[-1]), calendar=calendar)
    assert (
        winning.profit_factor is None
        and winning.payoff_ratio is None
        and winning.average_loss_r is None
    )
    assert winning.score_bands[1].n == 0 and winning.score_bands[1].confidence is None


def test_ER_malformed_output_cannot_claim_working(
    outcomes: tuple[Outcome, ...], calendar: MarketCalendar
) -> None:
    card = summarize_edge(KEY, outcomes, calendar=calendar)
    for change in (
        {"grade": "WORKING"},
        {"n": 6},
        {"filled": 6},
        {"win_rate": None},
        {"fill_rate": D("0.1")},
        {"score_bands": tuple(reversed(card.score_bands))},
        {"equity_metrics_status": "AVAILABLE"},
        {"sharpe": D(100)},
    ):
        with pytest.raises(ValidationError):
            EdgeCard.model_validate(card.model_copy(update=change))
    with pytest.raises(ValidationError):
        ScoreBand(label="[7,8)", n=0, expectancy_r=D(1), confidence=None)


@pytest.mark.parametrize(
    "case", ["invalid_cohort", "float_pf", "negative_pf", "bad_dsr", "nan_dsr", "bad_confidence"]
)
def test_ER_grade_input_contract(case: str) -> None:
    kwargs: dict[str, Any] = {
        "r_multiples": (D(1),),
        "confidence": None,
        "profit_factor": D(1),
        "cohort": "PAPER",
    }
    if case == "invalid_cohort":
        kwargs["cohort"] = "FAKE"
    elif case == "float_pf":
        kwargs["profit_factor"] = 1.2
    elif case == "negative_pf":
        kwargs["profit_factor"] = D(-1)
    elif case == "bad_dsr":
        kwargs["dsr"] = D("1.1")
    elif case == "nan_dsr":
        kwargs["dsr"] = D("NaN")
    else:
        kwargs["confidence"] = {"lower": D(1)}
    with pytest.raises(DataIntegrityError):
        edge_grade(**kwargs)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_ids",
        "excess_exposure",
        "order",
        "wrong_key",
        "wrong_hash",
        "missing_id",
        "gap",
        "late_start",
        "early_end",
        "weekend",
    ],
)
def test_ER_equity_must_cover_matching_evidence(
    case: str, outcomes: tuple[Outcome, ...], calendar: MarketCalendar
) -> None:
    curve = curve_for(outcomes)
    updates: dict[str, Any]
    if case == "duplicate_ids":
        updates = {"alert_ids": (*curve.alert_ids, curve.alert_ids[0])}
    elif case == "excess_exposure":
        updates = {"exposed_sessions": 99}
    elif case == "order":
        updates = {"points": tuple(reversed(curve.points))}
    elif case == "wrong_key":
        updates = {"key": KEY.model_copy(update={"cohort": "LIVE"})}
    elif case == "wrong_hash":
        updates = {"manifest_sha256": "f" * 64}
    elif case == "missing_id":
        updates = {"alert_ids": curve.alert_ids[:-1]}
    elif case == "gap":
        updates = {"points": (curve.points[0], *curve.points[2:]), "exposed_sessions": 5}
    elif case == "late_start":
        updates = {"points": curve.points[1:], "exposed_sessions": 5}
    elif case == "early_end":
        updates = {"points": curve.points[:-1], "exposed_sessions": 5}
    else:
        updates = {
            "points": (*curve.points, EquityPoint(session=date(2026, 10, 10), equity=D(104)))
        }
    with pytest.raises(DataIntegrityError):
        summarize_edge(KEY, outcomes, calendar=calendar, curve=curve.model_copy(update=updates))


def test_ER_typed_statistical_failure_propagates(
    outcomes: tuple[Outcome, ...], calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.evaluation.edge as reporting

    with pytest.raises(DataIntegrityError):
        edge_grade((True,), None, None, "PAPER")  # type: ignore[arg-type]

    def failed_estimate(*args: Any, **kwargs: Any) -> None:
        raise DataIntegrityError("synthetic statistical failure")

    monkeypatch.setattr(reporting, "circular_bootstrap", failed_estimate)
    with pytest.raises(DataIntegrityError, match="synthetic statistical failure"):
        summarize_edge(KEY, outcomes, calendar=calendar)
