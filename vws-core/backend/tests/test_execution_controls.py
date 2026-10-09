"""AX-40/41/44 and Amendment 03: durable control and named security evidence."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import AutoJobRun, JobRun, SecurityEvent
from backend.core.errors import LedgerIntegrityError
from backend.core.system_state import SystemStateStore
from backend.execution.control_evidence import JobBinding
from backend.execution.live_security import LiveSecurityGuard
from backend.ops.anchors import LedgerAnchors
from backend.ops.dependency_audit import active_pins, audit
from backend.ops.doctor import Check, DoctorResult
from backend.ops.security import ACCOUNT_ITEMS, SecurityOps
from backend.security.secrets import RotationService
from backend.tests.test_security_cli import MemorySecrets
from backend.tests.test_system_state import RecordingNotifier


def live_settings() -> Settings:
    return Settings(
        _env_file=None,
        broker_account_type="CASH",
        execution_mode="AUTO_LIVE",
        paper_trading=False,
        live_trading_enabled=True,
        live_trading_confirm="I_ACCEPT_REAL_MONEY_RISK",
        broker_api_key=SecretStr("TEST_ONLY_LIVE_ID"),
        broker_secret_key=SecretStr("TEST_ONLY_LIVE_SECRET"),
        live_max_order_notional="500",
        live_max_daily_orders=2,
        live_max_open_positions=3,
        live_max_gross_exposure_pct="0.30",
        live_max_risk_per_trade="0.005",
        live_daily_loss_limit="0.01",
    )


@pytest.mark.parametrize(
    "missing",
    [
        None,
        "keyring",
        "age",
        "attest",
        "permissions",
        "restore",
        "anchor",
        "audit",
        "telegram",
        "admin",
        "egress",
    ],
)
def test_SEC_live_each_missing_security_condition_has_named_reason(
    engine: Engine, clock: FrozenClock, tmp_path: Path, missing: str | None
) -> None:
    settings = live_settings()
    state = SystemStateStore(engine, clock, RecordingNotifier())
    store = MemorySecrets()
    for name, value in (
        ("ALPACA_LIVE_KEY_ID", settings.broker_api_key),
        ("ALPACA_LIVE_SECRET", settings.broker_secret_key),
    ):
        store.set(name, value)
        if missing != "age":
            RotationService(store, clock, state.ledger, {name: lambda value: None}).rotate(
                name, value
            )
    if missing == "keyring":
        store.delete("ALPACA_LIVE_SECRET")
    if missing != "attest":
        ops = SecurityOps(state.ledger, state, clock)
        for item in ACCOUNT_ITEMS[:7]:
            ops.attest(item, "Owner")
    if missing != "restore":
        state.ledger.append(
            SecurityEvent, kind="RESTORE_TEST_PASSED", detail={"plaintext_sha256": "a" * 64}
        )
    if missing != "anchor":
        anchors = LedgerAnchors(state.ledger, clock)
        anchor = anchors.create()
        anchors.verify(anchor.seq, anchor.digest)
    project = Path(__file__).resolve().parents[2]
    if missing != "audit":

        def runner(path: Path) -> bytes:
            return json.dumps(
                {
                    "dependencies": [
                        {"name": name, "version": version, "vulns": []}
                        for name, version in active_pins(path).items()
                    ]
                }
            ).encode()

        audit(project, state.ledger, "Owner", runner=runner)
    observations = DoctorResult(
        checks=tuple(
            Check(
                name=name,
                status="WARN" if missing == fault else "PASS",
                required=True,
                message="Synthetic verified observation",
                fix="Synthetic fix",
            )
            for name, fault in (("telegram_private", "telegram"), ("host_administrator", "admin"))
        )
    )
    guard = LiveSecurityGuard(
        settings,
        state,
        store,
        project,
        permissions_pass=lambda: missing != "permissions",
        observations=lambda: (clock.now(), observations),
        egress_active=lambda: missing != "egress",
    )
    reasons = guard.reasons()
    identifiers = {
        "keyring": "SEC-10",
        "age": "SEC-13",
        "attest": "SEC-01",
        "permissions": "SEC-12",
        "restore": "SEC-40",
        "anchor": "SEC-42",
        "audit": "SEC-22",
        "telegram": "SEC-50/51",
        "admin": "SEC-71",
        "egress": "SEC-31/32",
    }
    if missing is None:
        assert reasons == ()
        stale = LiveSecurityGuard(
            settings,
            state,
            store,
            project,
            permissions_pass=lambda: True,
            observations=lambda: (clock.now() - timedelta(minutes=5, microseconds=1), observations),
            egress_active=lambda: True,
        ).reasons()
        assert any(row.startswith("SEC-50/51") for row in stale)
        assert any(row.startswith("SEC-71") for row in stale)
    else:
        assert any(row.startswith(identifiers[missing] + ":") for row in reasons)
    state.ledger.verify_chain()


@pytest.mark.parametrize(
    "kind,detail",
    [
        ("LIVE_DISABLED", {"operator": " "}),
        ("LIVE_DISABLED", {"operator": "Owner", "extra": "untrusted"}),
        ("LIVE_ENABLED", {"operator": "Owner"}),
        (
            "HOST_ACCOUNTING_READY",
            {"account_id": " ", "environment": "PAPER", "config_hash": "a" * 64},
        ),
        (
            "EXECUTION_MODE_OVERRIDE",
            {
                "account_id": "owner",
                "environment": "PAPER",
                "mode": "AUTO_LIVE",
                "paused": False,
                "action": "RESUME",
                "actor": "Owner",
                "config_hash": "a" * 64,
            },
        ),
        (
            "DESK_JOB_BINDING",
            {
                "job_run_id": str(uuid4()),
                "account_id": "owner",
                "environment": "PAPER",
                "config_hash": "a" * 64,
            },
        ),
    ],
)
def test_AX_40_control_events_revalidate_on_append(
    engine: Engine, clock: FrozenClock, kind: str, detail: dict[str, Any]
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    with pytest.raises(LedgerIntegrityError):
        state.ledger.append(SecurityEvent, kind=kind, detail=detail)
    state.ledger.verify_chain()


def test_AX_40_desk_job_binding_requires_one_existing_run(
    engine: Engine, clock: FrozenClock
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    run = state.ledger.append(
        JobRun,
        job="daily_scan",
        started_at=clock.now(),
        finished_at=clock.now(),
        outcome="PASS",
        counts={},
        duration_ms=0,
    )
    proof = JobBinding(
        job_run_id=run.id, account_id="paper-owner", environment="PAPER", config_hash="a" * 64
    )
    state.ledger.append(
        SecurityEvent, kind="DESK_JOB_BINDING", detail=proof.model_dump(mode="json")
    )
    with pytest.raises(LedgerIntegrityError):
        state.ledger.append(
            SecurityEvent, kind="DESK_JOB_BINDING", detail=proof.model_dump(mode="json")
        )
    state.ledger.verify_chain()


@pytest.mark.parametrize(
    "updates",
    [
        {"account_id": " "},
        {"account_id": "owner\n"},
        {"environment": "UNKNOWN"},
        {"config_hash": "bad"},
    ],
)
def test_AX_44_auto_job_cohort_and_identity_cannot_be_forged(
    engine: Engine, clock: FrozenClock, updates: dict[str, Any]
) -> None:
    state = SystemStateStore(engine, clock, RecordingNotifier())
    values = dict(
        job="auto_entry",
        account_id="paper-owner",
        environment="PAPER",
        config_hash="a" * 64,
        started_at=clock.now(),
        finished_at=clock.now(),
        outcome="PASS",
        counts={},
        duration_ms=0,
    )
    values.update(updates)
    with pytest.raises(LedgerIntegrityError):
        state.ledger.append(AutoJobRun, **values)
    state.ledger.verify_chain()
