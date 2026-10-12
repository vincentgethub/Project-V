"""EX-06: actual grading, immutable registration inputs and entry availability."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from backend.core.config import Settings, YamlConfig, load_yaml_config
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.evaluation.availability import GradePublication, GradeStore
from backend.evaluation.registry import (
    Registration,
    Registrations,
    Variant,
    VariantFamily,
    VariantRegistry,
)
from backend.evaluation.validation_runner import RegistrationContext
from backend.evaluation.walkforward import Sample, ValidationRun, walkforward
from backend.tests.test_replay import request
from backend.tests.test_v_validation import calendar as validation_calendar
from backend.tests.test_v_validation import history as validation_history
from backend.tests.test_v_validation import registration as validation_registration
from backend.tests.test_v_validation import sample

calendar = validation_calendar
history = validation_history
registration = validation_registration

D = Decimal
PROJECT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "isolated,synthetic,losing",
    [
        (True, False, False),
        (False, False, False),
        (True, True, False),
        (True, False, True),
    ],
)
def test_EG_working_requires_its_own_registered_nonsynthetic_OOS_grade(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    isolated: bool,
    synthetic: bool,
    losing: bool,
) -> None:
    enabled = (
        ("EARNINGS_GAP",)
        if isolated
        else ("TREND_50EMA", "BASE_BREAKOUT", "ANCHORED_VWAP_RECLAIM", "EARNINGS_GAP")
    )
    gates, record = publication(
        registration,
        history,
        calendar,
        earnings_variant=enabled,
        synthetic=synthetic,
        losing=losing,
    )
    gates.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    assert not gates.earnings_working()  # Still off in the current baseline.
    values = gates.config.model_dump()
    values["playbooks"]["enabled"] = [
        "TREND_50EMA",
        "BASE_BREAKOUT",
        "ANCHORED_VWAP_RECLAIM",
        "EARNINGS_GAP",
    ]
    selected = GradeStore(gates.ledger, gates.settings, YamlConfig.model_validate(values))
    assert selected.earnings_working() is (isolated and not synthetic and not losing)


def publication(
    registered: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    *,
    synthetic: bool = False,
    losing: bool = False,
    earnings_variant: tuple[str, ...] | None = None,
) -> tuple[GradeStore, GradePublication]:
    store, original = registered
    registry = InstrumentRegistry.from_csv(PROJECT / "config")
    config = load_yaml_config(PROJECT / "config/config.yaml", allowed_symbols=registry.symbols)
    settings = Settings()
    inputs = RegistrationContext(
        settings=settings.config_hash,
        config=config.config_hash,
        filings="b" * 64,
        fees="c" * 64,
        symbols=("NVDA",),
        initial_equity="10000",
        funding=request().funding,
        synthetic=synthetic,
        instruments=tuple(registry.get(symbol) for symbol in sorted(registry.symbols)),
    )
    fixed = (
        original.registry
        if earnings_variant is None
        else VariantRegistry(
            families=(
                VariantFamily(
                    name="PLAYBOOK",
                    variants=(
                        Variant(name="BASELINE"),
                        Variant(
                            name="EARNINGS_GAP", overrides={"playbooks.enabled": earnings_variant}
                        ),
                    ),
                ),
            )
        )
    )
    proof = store.register(
        fixed,
        original.file_sha256,
        history,
        config.qv,
        calendar,
        context_sha256=inputs.sha256,
    )

    def evaluate(variant: Variant, start: date, end: date) -> Sample:
        value = sample(variant, start, end, history.manifest.sha256, 50)
        trades = tuple(
            type(row).model_validate(
                {
                    **row.model_dump(),
                    "r_multiple": D(-1) if losing or i % 10 == 0 else D(1),
                    "net_money": D(-10) if losing or i % 10 == 0 else D(10),
                }
            )
            for i, row in enumerate(value.trades)
        )
        return Sample.model_validate({**value.model_dump(), "trades": trades})

    run = walkforward(
        proof,
        "EXITS" if earnings_variant is None else "PLAYBOOK",
        history.bundle.for_symbol("NVDA", "RAW").sessions,
        config.qv,
        evaluate,
    )
    record = GradePublication(
        registration_sha256=proof.sha256,
        family=run.family,
        kind=run.kind,
        result_sha256=run.sha256,
        settings_sha256=settings.config_hash,
        baseline=config,
        result=run,
        inputs=inputs,
    )
    assert GradePublication.recorded(record.model_dump(mode="json")) == record
    return GradeStore(store.ledger, settings, config), record


@pytest.mark.parametrize(
    "synthetic,losing,allowed", [(False, False, True), (True, False, False), (False, True, False)]
)
def test_EX_06_recomputed_registered_grade_and_fake_evidence_refusal(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    synthetic: bool,
    losing: bool,
    allowed: bool,
) -> None:
    gates, record = publication(registration, history, calendar, synthetic=synthetic, losing=losing)
    assert not gates.exit_working()
    gates.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    assert gates.exit_working() is allowed
    assert gates.exit_working() is allowed  # immutable statistical cache retains the same binding
    values = record.baseline.model_dump()
    values["evaluation"]["max_hold_sessions"] = 10
    chosen = GradeStore(gates.ledger, gates.settings, YamlConfig.model_validate(values))
    assert chosen.exit_working() is allowed
    values["evaluation"]["max_hold_sessions"] = 30
    assert not GradeStore(
        gates.ledger, gates.settings, YamlConfig.model_validate(values)
    ).exit_working()


def test_EX_06_forged_working_string_is_not_authority(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    gates, record = publication(registration, history, calendar, losing=True)
    results = tuple(
        type(row).model_validate(row.model_copy(update={"grade": "WORKING"}))
        for row in record.result.results
    )
    forged = ValidationRun.model_validate(record.result.model_copy(update={"results": results}))
    payload = GradePublication.model_validate(
        record.model_copy(update={"result": forged, "result_sha256": forged.sha256})
    )
    gates.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=payload.model_dump(mode="json")
    )
    with pytest.raises(DataIntegrityError, match="statistics"):
        gates.exit_working()


def test_EX_06_settings_change_and_hash_only_report_never_admit(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    gates, record = publication(registration, history, calendar)
    gates.ledger.append(
        SecurityEvent,
        kind="VALIDATION_REPORT",
        detail={
            "registration_sha256": record.registration_sha256,
            "family": "EXITS",
            "kind": "WALKFORWARD",
            "result_sha256": record.result_sha256,
        },
    )
    assert not gates.exit_working()
    gates.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    changed = Settings.validated_copy(gates.settings.model_copy(update={"max_open_positions": 1}))
    assert not GradeStore(gates.ledger, changed, gates.config).exit_working()
