"""QV: fixed variant and sealed-window boundaries, never generated parameters."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.core.config import ValidationConfig, load_yaml_config
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.data.history import FrozenHistory, HistoryBundle, HistorySeries
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.evaluation import walkforward as validation_module
from backend.evaluation.registry import (
    Registration,
    Registrations,
    Variant,
    VariantFamily,
    VariantRegistry,
    add_months,
    apply_variant,
    load_registry,
    refuse_registered_holdout,
)
from backend.evaluation.walkforward import (
    Fold,
    OOSResult,
    Sample,
    ValidationRun,
    ValidationTrade,
    _join,
    _results,
    final_holdout,
    folds,
    select_variant,
    walkforward,
)
from backend.tests.query_faults import selects_kind
from backend.tests.test_outcomes_history import frozen
from backend.tests.test_v_validation import calendar as source_calendar
from backend.tests.test_v_validation import history as source_history
from backend.tests.test_v_validation import registration as source_registration
from backend.tests.test_v_validation import sample

calendar, history, registration = source_calendar, source_history, source_registration
ROOT = Path(__file__).resolve().parents[2]
D = Decimal


@pytest.mark.parametrize(
    "value", [None, "EARNINGS_GAP", (), ("EARNINGS_GAP", "EARNINGS_GAP"), ("UNKNOWN",)]
)
def test_QV_enabled_playbooks_are_one_explicit_valid_set(value: Any) -> None:
    with pytest.raises(ValidationError):
        Variant(name="FIXED", overrides={"playbooks.enabled": value})


def test_QV_nonbaseline_requires_a_real_explicit_override() -> None:
    with pytest.raises(ValidationError, match="nonbaseline"):
        VariantFamily(name="EXITS", variants=(Variant(name="BASELINE"), Variant(name="EMPTY")))


def test_QV_unknown_family_and_invalid_fixed_policy_refused(
    registration: tuple[Registrations, Registration], tmp_path: Path
) -> None:
    _, proof = registration
    assert proof.registry.sha256 == proof.registry.sha256 and len(proof.registry.sha256) == 64
    with pytest.raises(ConfigurationError, match="unknown"):
        proof.registry.family("UNREGISTERED")
    registry = InstrumentRegistry.from_csv(ROOT / "config")
    config = load_yaml_config(ROOT / "config/config.yaml", allowed_symbols=registry.symbols)
    with pytest.raises(ConfigurationError):
        apply_variant(config, Variant(name="BAD", overrides={"evaluation.max_hold_sessions": 15}))
    with pytest.raises(ConfigurationError):
        load_registry(tmp_path / "absent.yaml", config)
    assert Variant(name="EXACT", overrides={"rs.min_stock_percentile": D(50)}).model_dump(
        mode="json"
    )["overrides"] == {"rs.min_stock_percentile": "50"}


@pytest.mark.parametrize(
    "day, count", [("2026-01-01", 1), (date(2026, 1, 1), True), (date(2026, 1, 1), 1201)]
)
def test_QV_calendar_month_boundary_is_typed_and_bounded(day: Any, count: Any) -> None:
    with pytest.raises(DataIntegrityError):
        add_months(day, count)


@pytest.mark.parametrize(
    "change", [{"cumulative_trials": (("EXITS", 0),)}, {"cumulative_trials": (("OTHER", 2),)}]
)
def test_QV_registration_rejects_relabelled_or_reset_trials(
    registration: tuple[Registrations, Registration], change: dict[str, Any]
) -> None:
    _, proof = registration
    with pytest.raises(ValidationError):
        Registration.model_validate(proof.model_copy(update=change))


@pytest.mark.parametrize("case", ["configured_cap", "short", "holdout", "bound", "future"])
def test_QV_registration_needs_adequate_fixed_history_and_bounded_past_inventory(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    store, proof = registration
    policy = (
        ValidationConfig(max_variants_per_family=1)
        if case == "configured_cap"
        else ValidationConfig()
    )
    if case in {"short", "holdout"}:
        count = 200 if case == "short" else 400
        history = frozen(
            HistoryBundle(
                series=tuple(
                    HistorySeries(
                        symbol=row.symbol, adjustment=row.adjustment, bars=row.bars[:count]
                    )
                    for row in history.bundle.series
                )
            )
        )
        # A first registration over another independent empty ledger cannot take
        # the prior-registration mismatch path instead of the history gate.
        from backend.core.database import create_database, create_schema
        from backend.core.ledger import Ledger

        engine = create_database("sqlite+pysqlite:///:memory:")
        create_schema(engine)
        store = Registrations(Ledger(engine, store.ledger.clock))
    elif case in {"bound", "future"}:
        store.ledger.verify_chain()
        monkeypatch.setattr(store.ledger, "verify_chain", lambda: {})
        monkeypatch.setattr(store.ledger, "_verify_in_session", lambda *args: {})
        original = Session.scalars

        def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
            found = original(session, statement, *args, **kwargs)
            if not selects_kind(statement, "VARIANTS_REGISTERED"):
                return found
            projected = [SimpleNamespace(**vars(row)) for row in found]
            if case == "bound":
                return projected * 1001
            projected[0].created_at = store.ledger.clock.now() + timedelta(seconds=1)
            return projected

        monkeypatch.setattr(Session, "scalars", scalars)
    try:
        with pytest.raises((ConfigurationError, DataIntegrityError)):
            store.register(proof.registry, "c" * 64, history, policy, calendar)
    finally:
        if case in {"short", "holdout"}:
            store.ledger.engine.dispose()


@pytest.mark.parametrize("case", ["list", "unordered", "short", "no_fold"])
def test_QV_fold_inputs_do_not_invent_training_or_test_windows(
    registration: tuple[Registrations, Registration], history: FrozenHistory, case: str
) -> None:
    _, proof = registration
    sessions: Any = history.manifest.entries[0].sessions
    if case == "list":
        sessions = list(sessions)
    elif case == "unordered":
        sessions = (sessions[1], sessions[0], *sessions[2:])
    else:
        sessions = sessions[: 200 if case == "short" else 203]
    with pytest.raises((DataIntegrityError, ConfigurationError)):
        folds(sessions, proof, ValidationConfig())


def test_QV_fold_and_trade_order_are_causal(
    registration: tuple[Registrations, Registration],
) -> None:
    _, proof = registration
    row = sample(
        Variant(name="BASELINE"), proof.training_start, proof.training_end, proof.history_sha256, 1
    )
    with pytest.raises(ValidationError):
        ValidationTrade.model_validate(
            row.trades[0].model_copy(update={"entry": row.trades[0].decision})
        )
    with pytest.raises(ValidationError):
        Fold(
            train_start=proof.training_start,
            train_end=proof.training_end,
            test_start=proof.training_end,
            test_end=proof.holdout_start,
        )
    with pytest.raises(ValidationError):
        Sample.model_validate(row.model_copy(update={"trades": (*row.trades, *row.trades)}))


def test_QV_last_complete_fold_ends_at_the_holdout_boundary(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    _, proof = registration
    sessions = history.manifest.entries[0].sessions
    boundary = add_months(sessions[200], 12)
    proof = Registration.model_validate(
        proof.model_copy(
            update={
                "holdout_start": boundary,
                "training_end": calendar.previous_sessions(boundary, 1)[0],
            }
        )
    )
    rows = folds(sessions, proof, ValidationConfig())
    assert len(rows) == 1 and rows[-1].test_end < boundary


def test_QV_selection_needs_the_registered_order_and_same_training_window(
    registration: tuple[Registrations, Registration],
) -> None:
    _, proof = registration
    family = proof.registry.family("EXITS")
    rows = tuple(
        sample(variant, proof.training_start, proof.training_end, proof.history_sha256)
        for variant in family.variants
    )
    for wrong in (
        tuple(reversed(rows)),
        (rows[0], rows[1].model_copy(update={"history_sha256": "f" * 64})),
    ):
        with pytest.raises(DataIntegrityError):
            select_variant(wrong, family, ValidationConfig())
    assert select_variant(rows, family, ValidationConfig()) == "BASELINE"


def test_QV_join_and_statistics_cannot_mix_overlaps_or_calendar_dates(
    registration: tuple[Registrations, Registration],
) -> None:
    _, proof = registration
    row = sample(
        Variant(name="BASELINE"), proof.training_start, proof.training_end, proof.history_sha256
    )
    with pytest.raises(ConfigurationError):
        _join("SELECTED", ())
    with pytest.raises(DataIntegrityError):
        _join("SELECTED", (row, row))
    changed = Sample.model_validate(
        row.model_copy(update={"variant": "OTHER", "daily": row.daily[:-1]})
    )
    with pytest.raises(DataIntegrityError):
        _results((row.model_copy(update={"variant": "SELECTED"}), changed), 2, ValidationConfig())


def test_QV_unregistered_ordinary_window_cannot_reveal_holdout(
    registration: tuple[Registrations, Registration],
) -> None:
    store, proof = registration
    with pytest.raises(ConfigurationError):
        store.check_window("f" * 64, proof.training_start, proof.training_end)
    with pytest.raises(ConfigurationError):
        refuse_registered_holdout(store.ledger, proof.training_end, proof.training_start)


def test_QV_duplicate_family_and_malformed_result_cannot_be_registered_or_reported(
    registration: tuple[Registrations, Registration],
) -> None:
    _, proof = registration
    family = proof.registry.family("EXITS")
    with pytest.raises(ValidationError, match="unique families"):
        VariantRegistry(families=(family, family))
    empty = sample(
        Variant(name="BASELINE"), proof.training_start, proof.training_end, proof.history_sha256
    )
    results = _results(
        (empty.model_copy(update={"variant": "SELECTED"}), empty), 2, ValidationConfig()
    )
    with pytest.raises(ValidationError, match="OOS count"):
        OOSResult.model_validate(results[1].model_copy(update={"n": 1}))
    with pytest.raises(ValidationError, match="result identity"):
        ValidationRun(
            registration_sha256=proof.sha256,
            history_sha256=proof.history_sha256,
            family="EXITS",
            kind="HOLDOUT",
            selections=(),
            results=tuple(reversed(results)),
        )


def test_QV_changed_frozen_history_is_not_a_new_parameter_trial(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    tmp_path: Path,
) -> None:
    from backend.data.history import seal_history

    store, proof = registration
    first = history.bundle.series[0]
    altered = first.model_copy(
        update={
            "bars": (
                first.bars[0].model_copy(update={"volume": first.bars[0].volume + 1}),
                *first.bars[1:],
            )
        }
    )
    changed = seal_history(
        tmp_path, HistoryBundle(series=(altered, *history.bundle.series[1:])), calendar
    )
    with pytest.raises(ConfigurationError, match="cannot be replaced"):
        store.register(proof.registry, "c" * 64, changed, ValidationConfig(), calendar)


@pytest.mark.parametrize("case", ["unavailable_statistic", "holdout_fold", "wrong_sample"])
def test_QV_selection_fails_closed_on_unavailable_stats_or_unbound_evaluator(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    _, proof = registration
    family = proof.registry.family("EXITS")
    if case == "unavailable_statistic":
        rows = tuple(
            sample(row, proof.training_start, proof.training_end, proof.history_sha256, 50)
            for row in family.variants
        )
        monkeypatch.setattr(validation_module, "circular_bootstrap", lambda *a, **k: None)
        assert select_variant(rows, family, ValidationConfig()) == "BASELINE"
        return
    if case == "holdout_fold":
        fold = Fold(
            train_start=proof.training_start,
            train_end=proof.holdout_start,
            test_start=proof.holdout_start + timedelta(days=1),
            test_end=proof.holdout_start + timedelta(days=2),
        )
        monkeypatch.setattr(validation_module, "folds", lambda *a: (fold,))

    def evaluate(variant: Variant, start: date, end: date) -> Sample:
        return sample(
            variant, start, end, "f" * 64 if case == "wrong_sample" else proof.history_sha256
        )

    with pytest.raises((ConfigurationError, DataIntegrityError), match="holdout|identity"):
        walkforward(
            proof, "EXITS", history.manifest.entries[0].sessions, ValidationConfig(), evaluate
        )


@pytest.mark.parametrize(
    "case", ["latest", "bound", "future", "duplicate", "proof", "training", "test"]
)
def test_QV_holdout_one_use_survives_every_fault_boundary(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    store, proof = registration

    def evaluate(variant: Variant, start: date, end: date) -> Sample:
        result = sample(variant, start, end, proof.history_sha256)
        if (
            case == "training"
            and end == proof.training_end
            or case == "test"
            and start == proof.holdout_start
        ):
            return Sample.model_validate(result.model_copy(update={"history_sha256": "f" * 64}))
        return result

    if case == "latest":
        store.register(proof.registry, "c" * 64, history, ValidationConfig(), calendar)
    elif case in {"duplicate", "proof"}:
        final_holdout(
            store.ledger, proof, "EXITS", ValidationConfig(), evaluate, "RUN HOLDOUT EXITS"
        )
    if case in {"bound", "future", "duplicate", "proof"}:
        store.ledger.verify_chain()
        monkeypatch.setattr(store.ledger, "verify_chain", lambda: {})
        monkeypatch.setattr(store.ledger, "_verify_in_session", lambda *args: {})
        original = Session.scalars

        def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
            found = original(session, statement, *args, **kwargs)
            if not selects_kind(statement, "VALIDATION_FINAL_RESULT"):
                return found
            if case in {"bound", "future"}:
                row = SimpleNamespace(
                    created_at=store.ledger.clock.now() + timedelta(seconds=int(case == "future"))
                )
                return [row] * (2001 if case == "bound" else 1)
            projected = [SimpleNamespace(**vars(row)) for row in found]
            if case == "duplicate":
                return projected * 2
            for row in projected:
                if row.kind == "VALIDATION_FINAL_RESULT":
                    row.detail = {**row.detail, "result_sha256": "f" * 64}
            return projected

        monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises((ConfigurationError, DataIntegrityError)):
        final_holdout(
            store.ledger, proof, "EXITS", ValidationConfig(), evaluate, "RUN HOLDOUT EXITS"
        )
    if case in {"training", "test"}:
        with pytest.raises(ConfigurationError, match="consumed"):
            final_holdout(
                store.ledger, proof, "EXITS", ValidationConfig(), evaluate, "RUN HOLDOUT EXITS"
            )
