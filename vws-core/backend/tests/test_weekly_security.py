"""SEC: actual immutable events, masked IDs, dated checks and old anchor proof."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from backend.core.config import CostModelConfig, Settings
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.fee_schedule import load_fee_schedule
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.domain.tax_profile import TaxProfile
from backend.evaluation.outcomes import Outcome
from backend.evaluation.security_summary import render_security, weekly_security
from backend.evaluation.weekly import WeeklyReport, build_weekly_report, render_weekly, report_csv
from backend.ops.anchors import LedgerAnchors
from backend.tests import test_edge as edge_golden
from backend.tests import test_weekly_equity as golden
from backend.tests.test_swarm_and_callbacks import MovingClock

calendar, history, results = golden.calendar, golden.history, golden.results
edge_outcomes = edge_golden.outcomes
context = golden.context


def test_SEC_72_weekly_security_uses_saved_events_only_and_keeps_failed_latest_check(
    engine: Engine,
) -> None:
    start = datetime(2026, 10, 1, 4, tzinfo=UTC)
    clock = MovingClock(start - timedelta(days=1))
    ledger = Ledger(engine, clock)
    ledger.append(SecurityEvent, kind="TELEGRAM_STRANGER", detail={"user_id": 456})
    clock.current = start
    ledger.append(SecurityEvent, kind="TELEGRAM_STRANGER", detail={"user_id": 456})
    ledger.append(SecurityEvent, kind="TELEGRAM_STRANGER", detail={"user_id": 123})
    ledger.append(
        SecurityEvent,
        kind="SECRET_ROTATED",
        detail={"name": "TELEGRAM_BOT_TOKEN", "fingerprint": "a" * 64},
    )
    ledger.append(SecurityEvent, kind="PIP_AUDIT_PASSED", detail={})
    clock.current += timedelta(days=1)
    ledger.append(SecurityEvent, kind="PIP_AUDIT_FAILED", detail={})
    anchor = LedgerAnchors(ledger, clock).record()
    clock.current += timedelta(days=90)
    summary = weekly_security(ledger, Settings(), start)
    assert summary.new_ids == (123,)
    assert dict((row.kind, row.count) for row in summary.events)["TELEGRAM_STRANGER"] == 2
    ages = {row.name: row for row in summary.credentials}
    assert ages["TELEGRAM_BOT_TOKEN"].age_days == 91
    assert ages["TELEGRAM_BOT_TOKEN"].status == "WARN"
    assert ages["ALPACA_PAPER_KEY_ID"].status == "UNKNOWN"
    assert summary.latest_anchor == anchor
    checks = {row.check: row for row in summary.checks}
    assert checks["pip_audit"].status == "FAIL" and checks["drill"].status == "UNVERIFIED"
    assert "123" not in "\n".join(render_security(summary, masked=True))
    assert "New IDs: 123" in "\n".join(render_security(summary, masked=False))
    assert "CDT" in "\n".join(render_security(summary, masked=False))
    assert "unavailable" in "\n".join(render_security(None, masked=False))


@pytest.mark.parametrize("fault", ["future", "id", "anchor"])
def test_SEC_72_bad_saved_security_evidence_is_not_passed(engine: Engine, fault: str) -> None:
    clock = MovingClock(datetime(2026, 10, 8, 21, tzinfo=UTC))
    ledger = Ledger(engine, clock)
    if fault == "future":
        ledger.append(
            SecurityEvent,
            kind="SECRET_ROTATED",
            detail={"name": "TELEGRAM_BOT_TOKEN"},
            ts=clock.now() + timedelta(seconds=1),
        )
    elif fault == "id":
        ledger.append(SecurityEvent, kind="TELEGRAM_STRANGER", detail={"user_id": True})
    else:
        ledger.append(SecurityEvent, kind="LEDGER_ANCHOR", detail={"seq": 0, "digest": "f" * 64})
    with pytest.raises(DataIntegrityError):
        weekly_security(ledger, Settings(), clock.now() - timedelta(days=7))


def test_SEC_72_weekly_report_roundtrip_contains_proof_without_secret_values(
    engine: Engine,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
) -> None:  # noqa: F811
    clock = MovingClock(datetime(2026, 10, 8, 22, tzinfo=UTC))
    ledger = Ledger(engine, clock)
    ledger.append(SecurityEvent, kind="RESTORE_TEST_PASSED", detail={})
    ledger.append(
        SecurityEvent,
        kind="SECRET_ROTATED",
        detail={"name": "TELEGRAM_BOT_TOKEN", "fingerprint": "e" * 64},
    )
    LedgerAnchors(ledger, clock).record()
    report = build_weekly_report(
        context(),
        results,
        history,
        calendar,
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
        CostModelConfig(),
        TaxProfile(federal_st_rate=Decimal(".24")),
        security=weekly_security(ledger, Settings(), datetime(2026, 9, 30, 4, tzinfo=UTC)),
    )
    assert WeeklyReport.from_recorded(report.model_dump(mode="json")) == report
    text = render_weekly(report)
    assert "Last restore test: PASS" in text and "Last drill: UNVERIFIED" in text
    assert "Credential age TELEGRAM_BOT_TOKEN: PASS (0 days)" in text
    assert "fingerprint" not in text and "e" * 64 not in text
    assert b"Last restore test: PASS" in report_csv(report)
