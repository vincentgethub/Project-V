"""QV/EX/XA: admission inventory, binding and OOS provenance fault controls."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.core.config import Settings, YamlConfig, load_yaml_config
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import Playbook
from backend.evaluation import calibrated_costs
from backend.evaluation.availability import GradePublication, GradeStore
from backend.evaluation.calibrated_costs import CostCalibration
from backend.evaluation.registry import Registration, Registrations
from backend.evaluation.universe import PIT_NOTICE, HistoricalUniverse, Membership
from backend.evaluation.walkforward import ValidationRun
from backend.evaluation.weekly import DISCLAIMER
from backend.ops.trading_controls import ControlScope
from backend.tests.query_faults import selects_kind
from backend.tests.test_v_availability import PROJECT, publication
from backend.tests.test_v_validation import calendar as source_calendar
from backend.tests.test_v_validation import history as source_history
from backend.tests.test_v_validation import registration as source_registration

calendar, history, registration = source_calendar, source_history, source_registration
D = Decimal


def test_QV_recorded_grade_preserves_point_in_time_and_calibrated_context(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    gate, record = publication(registration, history, calendar)
    universe = HistoricalUniverse(
        file_sha256="e" * 64,
        rows=(Membership(symbol="NVDA", date_added=history.manifest.entries[0].sessions[0]),),
    )
    calibration = CostCalibration(
        scope=ControlScope(account_id="offline-paper", environment="PAPER"),
        source_ids=(UUID(int=1),),
        high=D(4),
        observed_at=gate.ledger.clock.now(),
    )
    run = ValidationRun.model_validate(
        record.result.model_copy(
            update={"universe_sha256": universe.file_sha256, "notices": (DISCLAIMER, PIT_NOTICE)}
        )
    )
    changed = GradePublication.model_validate(
        record.model_copy(
            update={
                "result": run,
                "result_sha256": run.sha256,
                "inputs": record.inputs.model_copy(
                    update={"universe": universe, "calibration": calibration}
                ),
            }
        )
    )
    decoded = GradePublication.recorded(changed.model_dump(mode="json"))
    assert decoded == changed and decoded.inputs.sha256 != record.inputs.sha256


def test_EG_registered_exit_family_never_certifies_earnings(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    gate, record = publication(registration, history, calendar)
    gate.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    values = gate.config.model_dump()
    values["playbooks"]["enabled"].append("EARNINGS_GAP")
    assert not GradeStore(
        gate.ledger, gate.settings, YamlConfig.model_validate(values)
    ).earnings_working()


def test_EX_registered_playbook_family_never_certifies_exits(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
) -> None:
    gate, record = publication(registration, history, calendar, earnings_variant=("EARNINGS_GAP",))
    gate.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    assert not gate.exit_working()


@pytest.mark.parametrize("method", ["exit_working", "earnings_working", "oos_by_playbook"])
def test_EX_unregistered_evidence_cannot_admit(
    method: str, registration: tuple[Registrations, Registration]
) -> None:
    store, _ = registration
    # A separate empty ledger proves that a missing registration is unavailable.
    from backend.core.database import create_database

    engine = create_database("sqlite+pysqlite:///:memory:")
    from backend.core.database import create_schema

    create_schema(engine)
    registry = InstrumentRegistry.from_csv(PROJECT / "config")
    values = load_yaml_config(
        PROJECT / "config/config.yaml", allowed_symbols=registry.symbols
    ).model_dump()
    values["playbooks"]["enabled"] = ["EARNINGS_GAP"]
    config = YamlConfig.model_validate(values)
    gate = GradeStore(Ledger(engine, store.ledger.clock), Settings(), config)
    try:
        checks = {
            "exit_working": gate.exit_working,
            "earnings_working": gate.earnings_working,
            "oos_by_playbook": gate.oos_by_playbook,
        }
        assert checks[method]() == ({} if method == "oos_by_playbook" else False)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "field", ["family", "kind", "settings_sha256", "result_sha256", "registration_sha256"]
)
def test_QV_grade_publication_fields_cannot_relabel_result(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    field: str,
) -> None:
    _, record = publication(registration, history, calendar)
    value = "PLAYBOOK" if field == "family" else "HOLDOUT" if field == "kind" else "f" * 64
    with pytest.raises(ValidationError, match="registered result"):
        GradePublication.model_validate(record.model_copy(update={field: value}))
    with pytest.raises(DataIntegrityError, match="unverifiable"):
        GradePublication.recorded({"broken": True})


@pytest.mark.parametrize(
    "case",
    [
        "context",
        "history",
        "family_variants",
        "holdout",
        "fold",
        "costs",
        "older_registration",
        "holdout_kind",
        "cached_binding",
    ],
)
def test_EX_stored_publication_cannot_bypass_current_registration(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    gate, record = publication(registration, history, calendar)
    run = record.result
    if case == "context":
        record = GradePublication.model_validate(
            record.model_copy(
                update={"inputs": record.inputs.model_copy(update={"initial_equity": "12000"})}
            )
        )
    elif case == "history":
        results = tuple(
            type(row).model_validate(
                row.model_copy(
                    update={"sample": row.sample.model_copy(update={"history_sha256": "f" * 64})}
                )
            )
            for row in run.results
        )
        run = ValidationRun.model_validate(
            run.model_copy(update={"history_sha256": "f" * 64, "results": results})
        )
    elif case == "family_variants":
        run = ValidationRun.model_validate(run.model_copy(update={"results": run.results[:2]}))
    elif case == "holdout":
        proof = Registrations(gate.ledger).latest()
        results = tuple(
            type(row).model_validate(
                row.model_copy(
                    update={"sample": row.sample.model_copy(update={"end": proof.holdout_start})}
                )
            )
            for row in run.results
        )
        run = ValidationRun.model_validate(run.model_copy(update={"results": results}))
    elif case == "fold":
        first = run.selections[0]
        selection = type(first).model_validate(
            first.model_copy(
                update={
                    "fold": first.fold.model_copy(
                        update={"train_start": first.fold.train_start + timedelta(days=1)}
                    )
                }
            )
        )
        run = ValidationRun.model_validate(
            run.model_copy(update={"selections": (selection, *run.selections[1:])})
        )
    elif case == "costs":
        higher = CostCalibration(
            scope=ControlScope(account_id="offline-paper", environment="PAPER"),
            source_ids=(UUID(int=1),),
            high=D(4),
            observed_at=gate.ledger.clock.now(),
        )
        monkeypatch.setattr(calibrated_costs, "snapshot", lambda *args, **kwargs: higher)
    elif case == "older_registration":
        run = ValidationRun.model_validate(run.model_copy(update={"registration_sha256": "f" * 64}))
        record = record.model_copy(update={"registration_sha256": "f" * 64})
    elif case == "holdout_kind":
        run = ValidationRun.model_validate(
            run.model_copy(update={"kind": "HOLDOUT", "selections": ()})
        )
        record = record.model_copy(update={"kind": "HOLDOUT"})
    elif case == "cached_binding":
        gate._verified[record.result_sha256] = GradePublication.model_validate(
            record.model_copy(
                update={"inputs": record.inputs.model_copy(update={"initial_equity": "12000"})}
            )
        )
    record = GradePublication.model_validate(
        record.model_copy(update={"result": run, "result_sha256": run.sha256})
    )
    gate.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    if case in {"costs", "older_registration", "holdout_kind"}:
        assert not gate.exit_working()
    else:
        with pytest.raises(DataIntegrityError):
            gate.exit_working()


@pytest.mark.parametrize("case", ["bound", "future"])
def test_EX_query_inventory_bounds_checked_independently(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    gate, record = publication(registration, history, calendar)
    gate.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    original = Session.scalars

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        found = original(session, statement, *args, **kwargs)
        if not selects_kind(statement, "VALIDATION_REPORT"):
            return found
        rows = [SimpleNamespace(**vars(row)) for row in found]
        if case == "bound":
            return rows * 1001
        rows[0].created_at = gate.ledger.clock.now() + timedelta(seconds=1)
        return rows

    monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises(DataIntegrityError, match="bound|future"):
        gate.exit_working()


@pytest.mark.parametrize(
    "case", ["legacy", "current", "changed_policy", "deduplicated", "conflict"]
)
def test_XA_OOS_samples_are_current_separate_and_deduplicated(
    registration: tuple[Registrations, Registration],
    history: FrozenHistory,
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    gate, record = publication(registration, history, calendar)
    run = record.result
    if case != "legacy":
        results = tuple(
            type(row).model_validate(
                row.model_copy(
                    update={
                        "sample": row.sample.model_copy(
                            update={
                                "trades": tuple(
                                    type(trade).model_validate(
                                        trade.model_copy(update={"playbook": Playbook.TREND_50EMA})
                                    )
                                    for trade in row.sample.trades
                                )
                            }
                        )
                    }
                )
            )
            for row in run.results
        )
        run = ValidationRun.model_validate(run.model_copy(update={"results": results}))
        record = GradePublication.model_validate(
            record.model_copy(update={"result": run, "result_sha256": run.sha256})
        )
    gate.ledger.append(
        SecurityEvent, kind="VALIDATION_REPORT", detail=record.model_dump(mode="json")
    )
    if case == "changed_policy":
        values = gate.config.model_dump()
        values["evaluation"]["max_hold_sessions"] = 30
        gate = GradeStore(gate.ledger, gate.settings, YamlConfig.model_validate(values))
    if case in {"deduplicated", "conflict"}:
        duplicate = record
        if case == "conflict":
            result = run.results[1]
            trade = result.sample.trades[0]
            changed = type(trade).model_validate(
                trade.model_copy(update={"net_money": trade.net_money + 1})
            )
            sample = type(result.sample).model_validate(
                result.sample.model_copy(update={"trades": (changed, *result.sample.trades[1:])})
            )
            result = type(result).model_validate(result.model_copy(update={"sample": sample}))
            different = ValidationRun.model_validate(
                run.model_copy(update={"results": (run.results[0], result, *run.results[2:])})
            )
            duplicate = GradePublication.model_validate(
                record.model_copy(update={"result": different, "result_sha256": different.sha256})
            )
        monkeypatch.setattr(gate, "_publications", lambda: (record, duplicate))
    if case == "conflict":
        with pytest.raises(DataIntegrityError, match="duplicate OOS"):
            gate.oos_by_playbook()
    else:
        rows = gate.oos_by_playbook()
        assert bool(rows) is (case in {"current", "deduplicated"})
        if rows:
            assert len(rows[Playbook.TREND_50EMA]) == len(run.results[1].sample.trades)
