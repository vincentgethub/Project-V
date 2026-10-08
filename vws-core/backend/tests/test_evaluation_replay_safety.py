"""EV-03: replay output binding and capacity checks cannot be bypassed."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.config import load_yaml_config
from backend.core.errors import DataIntegrityError
from backend.data.frozen_filings import FilingEvidence, FrozenFilings, seal_filings
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.evaluation import fixtures as fixture_module
from backend.evaluation import replay as module
from backend.evaluation.fixtures import seal_offline_fixtures
from backend.evaluation.replay import ReplayDecision, ReplayRun
from backend.tests import test_replay as golden
from backend.tests.test_fundamentals import evidence, synthetic

calendar, inputs = golden.calendar, golden.inputs


@pytest.mark.parametrize("fault", ["identity", "cancel", "duplicate", "notes", "manifest", "marks"])
def test_EV_replay_output_rejects_forged_identity_scope_and_chronology(
    inputs: tuple[FrozenHistory, FrozenFilings], calendar: MarketCalendar, fault: str
) -> None:
    value = golden.run(golden.request(), inputs, calendar)
    assert value.decisions
    first = value.decisions[0]
    changes: dict[str, Any]
    if fault == "identity":
        changed = first.outcome.model_copy(
            update={"setup": first.outcome.setup.model_copy(update={"cohort": "REPLAY_OOS"})}
        )
        with pytest.raises(ValidationError):
            ReplayDecision.model_validate(first.model_copy(update={"outcome": changed}))
        return
    if fault == "cancel":
        with pytest.raises(ValidationError):
            ReplayDecision.model_validate(
                first.model_copy(update={"entry_canceled_on": first.outcome.setup.decision_session})
            )
        return
    if fault == "duplicate":
        changes = {"decisions": (*value.decisions, first)}
    elif fault == "notes":
        changes = {"notes": ("returns guaranteed", *value.notes[1:])}
    elif fault == "manifest":
        changes = {"manifest_sha256": "f" * 64}
    else:
        changes = {"portfolio": tuple(reversed(value.portfolio))}
    with pytest.raises(ValidationError):
        ReplayRun.model_validate(value.model_copy(update=changes))


def test_EV_replay_refuses_a_single_common_session(
    inputs: tuple[FrozenHistory, FrozenFilings], calendar: MarketCalendar
) -> None:
    with pytest.raises(DataIntegrityError):
        golden.run(golden.request(start=date(2026, 10, 2), end=date(2026, 10, 4)), inputs, calendar)


def test_EV_worker_result_must_keep_frozen_provenance(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = module._worker

    def wrong(*args: Any, **kwargs: Any) -> Any:
        gates, timeline = original(*args, **kwargs)
        return gates.model_copy(update={"manifest_sha256": "f" * 64}), timeline

    monkeypatch.setattr(module, "_worker", wrong)
    with pytest.raises(DataIntegrityError):
        golden.run(golden.request(), inputs, calendar)


def test_EV_runtime_decision_bound_fails_closed_without_a_large_tape(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert module.MAX_REPLAY_DECISIONS == 100000
    monkeypatch.setattr(module, "MAX_REPLAY_DECISIONS", 0)
    with pytest.raises(DataIntegrityError):
        golden.run(golden.request(), inputs, calendar)


def test_EV_failed_framework_is_counted_as_blocked_not_approved(
    inputs: tuple[FrozenHistory, FrozenFilings],
    calendar: MarketCalendar,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = load_yaml_config

    def requiring(*args: Any, **kwargs: Any) -> Any:
        config = original(*args, **kwargs)
        return config.model_copy(
            update={"fundamentals": config.fundamentals.model_copy(update={"mode": "require"})}
        )

    monkeypatch.setattr(golden, "load_yaml_config", requiring)
    raw = synthetic()
    for row in raw["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"]:
        row["val"] = 1
    root = tmp_path / "failed-filings"
    root.mkdir()
    facts = seal_filings(
        root,
        tuple(
            FilingEvidence(symbol=symbol, payload=evidence(raw))
            for symbol in golden.request().symbols
        ),
    )
    value = golden.run(golden.request(), (inputs[0], facts), calendar)
    assert value.blocked_fundamentals > 0 and value.decisions == ()


def test_EV_offline_fixture_window_capacity_and_io_failures_are_typed(
    calendar: MarketCalendar, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(DataIntegrityError):
        seal_offline_fixtures(
            tmp_path, golden.request(start=date(2026, 10, 3), end=date(2026, 10, 4)), calendar
        )
    assert fixture_module.MAX_FIXTURE_SESSIONS == 20000
    with monkeypatch.context() as local:
        local.setattr(fixture_module, "MAX_FIXTURE_SESSIONS", 200)
        with pytest.raises(DataIntegrityError):
            seal_offline_fixtures(tmp_path, golden.request(), calendar)

    def deny(*args: Any, **kwargs: Any) -> Any:
        raise OSError("fixture write failure")

    monkeypatch.setattr(fixture_module, "seal_history", deny)
    with pytest.raises(DataIntegrityError):
        seal_offline_fixtures(tmp_path, golden.request(), calendar)
