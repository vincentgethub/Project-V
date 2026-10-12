"""QV/GV host boundaries: immutable dates and explicitly labeled tracker fallback."""

from datetime import timedelta

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import VerdictConfig
from backend.core.errors import ConfigurationError
from backend.core.ledger import Ledger
from backend.evaluation.registry import Registration, Registrations, refuse_registered_holdout
from backend.evaluation.verdict import latest_ready, record
from backend.tests import test_v_validation as validation
from backend.tests.test_v_verdict_quality import inputs

calendar = validation.calendar
history = validation.history
registration = validation.registration


def test_QV_ordinary_run_and_report_refuse_any_overlap(
    registration: tuple[Registrations, Registration],
) -> None:
    store, proof = registration
    refuse_registered_holdout(store.ledger, proof.training_start, proof.training_end)
    refuse_registered_holdout(
        store.ledger, proof.holdout_end + timedelta(days=1), proof.holdout_end + timedelta(days=2)
    )
    for start, end in (
        (proof.training_start, proof.holdout_start),
        (proof.holdout_start, proof.holdout_end),
        (proof.training_start, proof.holdout_end + timedelta(days=1)),
    ):
        with pytest.raises(ConfigurationError, match="one-use final"):
            refuse_registered_holdout(store.ledger, start, end)


def test_QV_unregistered_run_is_in_sample_and_has_no_holdout(
    engine: Engine, clock: FrozenClock
) -> None:
    refuse_registered_holdout(
        Ledger(engine, clock), clock.now().date() - timedelta(days=30), clock.now().date()
    )


def test_GV_fallback_has_the_amendments_source_label_and_same_thresholds(
    engine: Engine, clock: FrozenClock
) -> None:
    data = inputs(clock, source="EV_01_HYPOTHETICAL")
    verdict = record(Ledger(engine, clock), data, VerdictConfig())
    assert verdict.status == "READY"
    assert "Hypothetical alert tracker" in verdict.text()
    assert latest_ready(Ledger(engine, clock), data.scope.account_id, data.config_sha256)
