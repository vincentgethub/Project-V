"""AX-40/41: live unlock proofs in scratch ledgers only; no broker/executor."""

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from backend.core.config import Settings
from backend.core.database import AutoJobRun, JobRun, SecurityEvent
from backend.core.errors import ConfigurationError, ExecutionDisabledError
from backend.core.system_state import SystemState
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.outcomes import Outcome
from backend.execution.control_evidence import JobBinding
from backend.execution.live_guard import LIVE_PHRASE, LiveGuard
from backend.execution.modes import ModeStore
from backend.tests import test_weekly_publication as weekly
from backend.tests.test_execution_controls import live_settings
from backend.tests.test_weekly_publication import composition

calendar = weekly.calendar
history = weekly.history
results = weekly.results
edge_outcomes = weekly.edge_outcomes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [None, "sessions", "report", "halt", "accounting", "drill", "ready", "feeds", "security"],
)
async def test_AX_40_each_missing_unlock_proof_is_named_and_refuses(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    fault: str | None,
) -> None:
    publisher, _, _ = composition(engine, tmp_path, calendar, history, results)
    state = publisher.state
    settings = live_settings()
    paper_settings = Settings(
        _env_file=None, broker_account_type="CASH", execution_mode="AUTO_PAPER"
    )
    days = calendar.previous_sessions(state.clock.now().date(), 20)
    for day in days[:19] if fault == "sessions" else days:
        opened = calendar.session_open(day) + timedelta(minutes=10)
        state.ledger.append(
            AutoJobRun,
            job="auto_entry",
            account_id="paper-test",
            environment="PAPER",
            config_hash=paper_settings.config_hash,
            started_at=opened,
            finished_at=opened,
            duration_ms=0,
            outcome="PASS",
            counts={"submitted": 0},
        )
        closed = calendar.session_close(day) + timedelta(minutes=30)
        run = state.ledger.append(
            JobRun,
            job="daily_scan",
            started_at=closed,
            finished_at=closed,
            duration_ms=0,
            outcome="PASS",
            counts={},
        )
        binding = JobBinding(
            job_run_id=run.id,
            account_id="paper-test",
            environment="PAPER",
            config_hash=paper_settings.config_hash,
        )
        state.ledger.append(
            SecurityEvent, kind="DESK_JOB_BINDING", detail=binding.model_dump(mode="json")
        )
    if fault != "report":
        await publisher()
    if fault == "halt":
        state.escalate(SystemState.HALTED, "synthetic reconciliation mismatch")
    if fault != "accounting":
        state.ledger.append(
            SecurityEvent,
            kind="HOST_ACCOUNTING_READY",
            detail={
                "account_id": "live-scratch",
                "environment": "LIVE",
                "config_hash": settings.config_hash,
            },
        )
    state.ledger.append(
        SecurityEvent,
        kind="KILL_SWITCH_DRILL_PASSED",
        detail={"scratch": True},
        ts=state.clock.now() - timedelta(days=46 if fault == "drill" else 1),
    )
    effective = ["e" * 64]
    guard = LiveGuard(
        settings,
        state,
        calendar,
        "live-scratch",
        lambda: effective[0],
        drill_ready=lambda: fault != "drill",
        validation_ready=lambda: fault != "ready",
        feeds_healthy=lambda: fault != "feeds",
        security_reasons=None if fault == "security" else lambda: (),
    )
    with pytest.raises(ConfigurationError, match="phrase"):
        guard.enable(operator="Owner", phrase="not the required phrase")
    findings = guard.reasons(require_unlock=False)
    if fault is not None:
        fragment = {
            "sessions": "20 successful",
            "report": "Stage G report",
            "halt": "HALT occurred",
            "accounting": "Stage J",
            "drill": "within 45 days",
            "ready": "READY verdict",
            "feeds": "five sessions",
            "security": "section 10",
        }[fault]
        assert any(fragment in reason for reason in findings)
        with pytest.raises(ExecutionDisabledError):
            guard.enable(operator="Owner", phrase=LIVE_PHRASE)
    else:
        assert findings == ()
        with pytest.raises(ExecutionDisabledError, match="enable-live"):
            guard.assert_ready()
        guard.enable(operator="Owner", phrase=LIVE_PHRASE)
        guard.assert_ready()
        modes = ModeStore(settings, state, "live-scratch")
        assert str(modes.effective) == "AUTO_LIVE"
        effective[0] = "f" * 64
        with pytest.raises(ExecutionDisabledError, match="configuration binding changed"):
            guard.assert_ready()
        state.ledger.append(SecurityEvent, kind="LIVE_DISABLED", detail={"operator": "Owner"})
        assert modes.effective == "MANUAL" and not modes.entries_enabled
        modes.resume(operator="Owner", phrase="RESUME")
        assert modes.effective == "MANUAL", (
            "A global live disable requires another complete host unlock"
        )
        with pytest.raises(ExecutionDisabledError, match="enable-live"):
            guard.assert_ready()
    state.ledger.verify_chain()
