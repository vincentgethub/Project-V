"""PF-04: frozen history is validated once per evaluator, by full content hash."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.data.history import FrozenHistory, HistoryBundle, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import CapitalStatus, DeployableCapital
from backend.evaluation import history_cache
from backend.evaluation.fixtures import seal_offline_fixtures
from backend.evaluation.history_cache import ValidatedHistories
from backend.evaluation.registry import Variant
from backend.evaluation.replay import ReplayRequest
from backend.evaluation.validation_runner import ReplayEvaluator
from backend.tests.test_v_runner_boundaries import runner_args
from backend.tests.test_v_validation import calendar as source_calendar
from backend.tests.test_v_validation import history as source_history

calendar, history, runner_args = source_calendar, source_history, runner_args
D = Decimal


@pytest.fixture(scope="module")
def other(tmp_path_factory: pytest.TempPathFactory, calendar: MarketCalendar) -> FrozenHistory:
    seed = ReplayRequest(
        start=date(2023, 1, 3),
        end=date(2024, 12, 31),
        symbols=("AAPL",),
        initial_equity=D(10000),
        funding=DeployableCapital(
            checking_used=D(11500),
            buffer=D(1500),
            reserved=D(0),
            deployable=D(10000),
            status=CapitalStatus.OK,
        ),
        synthetic=True,
    )
    frozen, _ = seal_offline_fixtures(tmp_path_factory.mktemp("pf04-other"), seed, calendar)
    return frozen


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[HistoryBundle]:
    seen: list[HistoryBundle] = []

    def counted(bundle: HistoryBundle, cal: MarketCalendar) -> HistoryBundle:
        seen.append(bundle)
        return validate_history(bundle, cal)

    monkeypatch.setattr(history_cache, "validate_history", counted)
    return seen


def test_PF04_same_content_is_validated_once_and_returns_the_validated_object(
    history: FrozenHistory, calendar: MarketCalendar, calls: list[HistoryBundle]
) -> None:
    cache = ValidatedHistories(calendar)
    first = cache.validated(history, calendar)
    # A separate object with identical content hits by content, not identity.
    twin = FrozenHistory.model_validate(history.model_dump())
    assert twin is not history
    assert cache.validated(twin, calendar) is first
    assert cache.validated(history, calendar) is first
    assert first == history and len(calls) == 1 and len(cache) == 1


def test_PF04_a_different_bundle_is_fully_revalidated(
    history: FrozenHistory,
    other: FrozenHistory,
    calendar: MarketCalendar,
    calls: list[HistoryBundle],
) -> None:
    cache = ValidatedHistories(calendar)
    cache.validated(history, calendar)
    second = cache.validated(other, calendar)
    assert second == other and second != history
    assert len(calls) == 2 and len(cache) == 2


def test_PF04_a_failing_bundle_is_rejected_every_time_and_never_cached(
    history: FrozenHistory,
    other: FrozenHistory,
    calendar: MarketCalendar,
    calls: list[HistoryBundle],
) -> None:
    cache = ValidatedHistories(calendar)
    cache.validated(history, calendar)
    # Manifest of one history over the bundle of another: DQ-04 binding fails.
    forged = history.model_copy(update={"bundle": other.bundle})
    for _ in range(3):
        with pytest.raises(ValidationError):
            cache.validated(forged, calendar)
    # DQ-03: a calendar that cannot prove the sessions fails in validate_history.
    narrow = MarketCalendar(start=date(2024, 1, 1), end=date(2027, 1, 1))
    strict = ValidatedHistories(narrow)
    for _ in range(3):
        with pytest.raises(DataIntegrityError, match="DQ-03"):
            strict.validated(history, narrow)
    assert len(strict) == 0 and len(cache) == 1
    assert len(calls) == 1 + 3


def test_PF04_mutating_a_validated_bundle_is_refused_or_forces_revalidation(
    history: FrozenHistory,
    other: FrozenHistory,
    calendar: MarketCalendar,
    calls: list[HistoryBundle],
) -> None:
    cache = ValidatedHistories(calendar)
    checked = cache.validated(FrozenHistory.model_validate(history.model_dump()), calendar)
    bar = checked.bundle.series[0].bars[0]
    assert bar is not history.bundle.series[0].bars[0]
    # Ordinary mutation is refused: the models are frozen.
    for target, field, value in ((checked, "bundle", other.bundle), (bar, "close", D("1.00"))):
        with pytest.raises(ValidationError):
            setattr(target, field, value)
    assert cache.validated(history, calendar) is checked and len(calls) == 1
    # A copy with changed content has a new hash: fully revalidated, and refused.
    changed = bar.model_copy(update={"volume": bar.volume + 1})
    series = checked.bundle.series[0].model_copy(
        update={"bars": (changed, *checked.bundle.series[0].bars[1:])}
    )
    tampered = checked.model_copy(
        update={
            "bundle": checked.bundle.model_copy(
                update={"series": (series, *checked.bundle.series[1:])}
            )
        }
    )
    with pytest.raises(ValidationError):
        cache.validated(tampered, calendar)
    assert len(calls) == 1 and len(cache) == 1
    # Forcing an in-place change past the frozen guard changes the cached
    # entry's hash: it is evicted, never served, and the input is revalidated.
    object.__setattr__(bar, "volume", bar.volume + 1)
    again = cache.validated(history, calendar)
    assert again is not checked and again == history
    assert len(calls) == 2 and len(cache) == 1
    with pytest.raises(ValidationError):
        cache.validated(checked, calendar)
    assert len(calls) == 2


@pytest.mark.parametrize("case", ["calendar", "type", "unhashable", "full"])
def test_PF04_cache_bypass_validates_without_caching(
    history: FrozenHistory,
    calendar: MarketCalendar,
    calls: list[HistoryBundle],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    cache = ValidatedHistories(calendar)
    value: Any = history
    used = calendar
    if case == "calendar":
        used = MarketCalendar(start=date(2017, 1, 1), end=date(2027, 1, 1))
    elif case == "type":
        value = history.model_dump()
    elif case == "unhashable":

        def broken(model: object) -> bytes:
            raise ValueError("cannot hash")

        monkeypatch.setattr(history_cache, "canonical_bytes", broken)
    else:
        monkeypatch.setattr(history_cache, "MAX_ENTRIES", 0)
    for _ in range(2):
        assert cache.validated(value, used) == history
    assert len(calls) == 2 and len(cache) == 0


def test_PF04_evaluator_owns_one_cache_and_validates_once_across_windows(
    runner_args: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    counts: list[str] = []
    for name in ("history_cache", "replay", "weekly", "equity"):
        module = __import__(f"backend.evaluation.{name}", fromlist=["validate_history"])
        original: Callable[[HistoryBundle, MarketCalendar], HistoryBundle] = module.validate_history

        def counted(
            bundle: HistoryBundle,
            cal: MarketCalendar,
            _name: str = name,
            _original: Callable[[HistoryBundle, MarketCalendar], HistoryBundle] = original,
        ) -> HistoryBundle:
            counts.append(_name)
            return _original(bundle, cal)

        monkeypatch.setattr(module, "validate_history", counted)
    runner = ReplayEvaluator(*runner_args)
    other = ReplayEvaluator(*runner_args)
    assert runner.histories is not other.histories and len(other.histories) == 0
    start = runner.proof.training_start
    for weeks in (20, 40):
        end = runner.calendar.add_sessions(start, weeks * 5)
        runner(Variant(name="BASELINE"), start, end)
    assert counts == ["history_cache"] and len(runner.histories) == 1
