"""QV: sealed fixtures, fixed registration, fold causality and one-use holdout."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import ValidationConfig, load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import CapitalStatus, DeployableCapital
from backend.evaluation.fixtures import seal_offline_fixtures
from backend.evaluation.registry import (
    Registration,
    Registrations,
    Variant,
    VariantFamily,
    VariantRegistry,
    add_months,
    apply_variant,
    load_registry,
)
from backend.evaluation.replay import ReplayRequest
from backend.evaluation.walkforward import (
    Sample,
    ValidationRun,
    ValidationTrade,
    final_holdout,
    folds,
    publish,
    select_variant,
    walkforward,
)

D = Decimal
ONE = D(1)
PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2017, 1, 1), end=date(2027, 1, 1))


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory, calendar: MarketCalendar) -> FrozenHistory:
    seed = ReplayRequest(
        start=date(2019, 1, 1),
        end=date(2025, 12, 31),
        symbols=("NVDA",),
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
    frozen, _ = seal_offline_fixtures(tmp_path_factory.mktemp("qv-sealed"), seed, calendar)
    return frozen


def family(*variants: Variant) -> VariantFamily:
    return VariantFamily(name="EXITS", variants=(Variant(name="BASELINE"), *variants))


@pytest.fixture
def registration(
    engine: Engine, clock: FrozenClock, history: FrozenHistory, calendar: MarketCalendar
) -> tuple[Registrations, Registration]:
    store = Registrations(Ledger(engine, clock))
    fixed = VariantRegistry(
        families=(family(Variant(name="TIME_10", overrides={"evaluation.max_hold_sessions": 10})),)
    )
    return store, store.register(fixed, "a" * 64, history, ValidationConfig(), calendar)


def sample(
    variant: Variant, start: date, end: date, digest: str, count: int = 0, mean: Decimal = ONE
) -> Sample:
    day = start
    daily: list[tuple[date, Decimal]] = []
    while day <= end:
        if day.weekday() < 5:
            daily.append((day, D("0.001") if len(daily) % 2 == 0 else D("-0.0005")))
        day += timedelta(days=1)
    return Sample(
        variant=variant.name,
        start=start,
        end=end,
        history_sha256=digest,
        trades=tuple(
            sorted(
                (
                    ValidationTrade(
                        identity=uuid5(NAMESPACE_URL, f"{variant.name}/{start}/{end}/{i}"),
                        decision=start,
                        entry=start + timedelta(days=1),
                        exit=end,
                        r_multiple=mean,
                        net_money=mean * 10,
                    )
                    for i in range(count)
                ),
                key=lambda row: (row.exit, row.identity.hex),
            )
        ),
        daily=tuple(daily),
    )


def test_QV_01_registry_has_explicit_baselines_caps_and_valid_overrides() -> None:
    instruments = InstrumentRegistry.from_csv(PROJECT / "config")
    baseline = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=instruments.symbols)
    fixed = load_registry(PROJECT / "config/variants.yaml", baseline)
    assert sum(len(row.variants) for row in fixed.families) == 13
    assert all(row.variants[0].name == "BASELINE" for row in fixed.families)
    assert (
        apply_variant(
            baseline, Variant(name="BANDS", overrides={"sizing.confidence_mode": "bands"})
        ).sizing.confidence_mode
        == "bands"
    )
    assert baseline.sizing.confidence_mode == "off"
    with pytest.raises(ConfigurationError):
        fixed.family("UNKNOWN")
    with pytest.raises(ConfigurationError):
        apply_variant(
            baseline, Variant(name="TIME_11", overrides={"evaluation.max_hold_sessions": 11})
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "X", "overrides": {"max_risk_per_trade": "0.1"}},
        {"name": "X", "overrides": {"sizing.target_r": [1, 2]}},
        {"name": "X", "overrides": {"sizing.target_r": 2.0}},
    ],
)
def test_QV_01_generated_or_risk_overrides_refused(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Variant.model_validate(payload)


def test_QV_01_duplicate_missing_baseline_and_family_caps_refused() -> None:
    with pytest.raises(ValidationError):
        VariantFamily(name="X", variants=(Variant(name="X"),))
    with pytest.raises(ValidationError):
        VariantFamily(name="X", variants=(Variant(name="BASELINE"), Variant(name="BASELINE")))
    with pytest.raises(ValidationError):
        VariantRegistry(families=(family(), family()))
    with pytest.raises(ValidationError):
        VariantFamily(name="X", variants=(Variant(name="BASELINE"),) * 9)


def test_QV_01_cumulative_trials_survive_reregistration_and_duplicate_is_idempotent(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    store, original = registration
    assert store.latest() == original
    assert (
        store.register(
            original.registry, original.file_sha256, history, ValidationConfig(), calendar
        )
        == original
    )
    updated = VariantRegistry(
        families=(
            family(
                Variant(name="TIME_10", overrides={"evaluation.max_hold_sessions": 10}),
                Variant(name="TIME_30", overrides={"evaluation.max_hold_sessions": 30}),
            ),
        )
    )
    new = store.register(updated, "b" * 64, history, ValidationConfig(), calendar)
    assert dict(new.cumulative_trials)["EXITS"] == 5
    assert (new.holdout_start, new.holdout_end) == (original.holdout_start, original.holdout_end)
    assert Registration.recorded(new.model_dump(mode="json")) == new


def test_QV_02_holdout_windows_are_refused(
    registration: tuple[Registrations, Registration],
) -> None:
    store, proof = registration
    assert (
        store.check_window(proof.history_sha256, proof.training_start, proof.training_end) == proof
    )
    for start, end in (
        (proof.training_start, proof.holdout_start),
        (proof.holdout_start, proof.holdout_end),
    ):
        with pytest.raises(ConfigurationError, match="holdout"):
            store.check_window(proof.history_sha256, start, end)
    with pytest.raises(ConfigurationError):
        store.check_window("b" * 64, proof.training_start, proof.training_end)


def test_QV_03_anchored_fold_goldens(
    registration: tuple[Registrations, Registration], history: FrozenHistory
) -> None:
    _, proof = registration
    sessions = history.bundle.for_symbol("NVDA", "RAW").sessions
    plan = folds(sessions, proof, ValidationConfig())
    assert plan[0].train_start == sessions[200]
    assert all(
        row.train_start == plan[0].train_start and row.test_end < proof.holdout_start
        for row in plan
    )
    assert all(
        a.test_end < b.test_start and a.train_end < b.train_end
        for a, b in zip(plan, plan[1:], strict=False)
    )
    assert add_months(date(2024, 8, 31), 6) == date(2025, 2, 28)


@pytest.mark.parametrize(
    "count, extra_mean, expected",
    [(49, D(2), "BASELINE"), (50, D(1), "BASELINE"), (50, D(2), "TIME_10")],
)
def test_QV_03_selection_shortfalls_ties_and_highest_train_lower_bound(
    registration: tuple[Registrations, Registration], count: int, extra_mean: Decimal, expected: str
) -> None:
    _, proof = registration
    fixed = proof.registry.family("EXITS")
    rows = (
        sample(
            fixed.variants[0], proof.training_start, proof.training_end, proof.history_sha256, count
        ),
        sample(
            fixed.variants[1],
            proof.training_start,
            proof.training_end,
            proof.history_sha256,
            count,
            extra_mean,
        ),
    )
    assert select_variant(rows, fixed, ValidationConfig()) == expected


def test_QV_04_07_oos_is_insufficient_deterministic_and_published_byte_identically(
    registration: tuple[Registrations, Registration], history: FrozenHistory, tmp_path: Path
) -> None:
    _, proof = registration

    def evaluate(variant: Variant, start: date, end: date) -> Sample:
        assert end < proof.holdout_start
        return sample(variant, start, end, proof.history_sha256)

    args = (
        proof,
        "EXITS",
        history.bundle.for_symbol("NVDA", "RAW").sessions,
        ValidationConfig(),
        evaluate,
    )
    first, second = walkforward(*args), walkforward(*args)
    assert first == second and first.sha256 == second.sha256
    assert all(row.status == "INSUFFICIENT" and row.grade == "UNPROVEN" for row in first.results)
    assert ValidationRun.recorded(first.model_dump(mode="json")) == first
    paths = publish(first, tmp_path)
    before = tuple(path.read_bytes() for path in paths)
    assert (
        publish(second, tmp_path) == paths and tuple(path.read_bytes() for path in paths) == before
    )
    paths[0].write_text("altered")
    with pytest.raises(DataIntegrityError):
        publish(first, tmp_path)


def test_QV_02_final_consumed_once_and_redisplayed_without_evaluation(
    registration: tuple[Registrations, Registration],
) -> None:
    store, proof = registration
    calls = []

    def evaluate(variant: Variant, start: date, end: date) -> Sample:
        calls.append((variant.name, start, end))
        return sample(variant, start, end, proof.history_sha256)

    with pytest.raises(ConfigurationError, match="confirmation"):
        final_holdout(store.ledger, proof, "EXITS", ValidationConfig(), evaluate, "wrong")
    assert calls == []
    first = final_holdout(
        store.ledger, proof, "EXITS", ValidationConfig(), evaluate, "RUN HOLDOUT EXITS"
    )
    assert len(calls) == 4 and first.kind == "HOLDOUT"
    second = final_holdout(store.ledger, proof, "EXITS", ValidationConfig(), evaluate, "")
    assert second == first and len(calls) == 4


def test_QV_02_failed_final_is_not_retried(
    registration: tuple[Registrations, Registration],
) -> None:
    store, proof = registration

    def failed(variant: Variant, start: date, end: date) -> Sample:
        raise DataIntegrityError("offline interruption")

    with pytest.raises(DataIntegrityError):
        final_holdout(store.ledger, proof, "EXITS", ValidationConfig(), failed, "RUN HOLDOUT EXITS")
    with pytest.raises(ConfigurationError, match="consumed"):
        final_holdout(store.ledger, proof, "EXITS", ValidationConfig(), failed, "RUN HOLDOUT EXITS")
