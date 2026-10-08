"""SEC-22: fake audit output; proof matches complete current platform locks."""

import json
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.ops.dependency_audit import LOCKS, active_pins, audit, lock_hashes


@pytest.fixture
def audit_project(tmp_path: Path) -> Path:
    project = Path(__file__).resolve().parents[2]
    for name in LOCKS:
        shutil.copyfile(project / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize(
    "fault",
    [
        "",
        "unavailable",
        "partial",
        "vulnerability",
        "duplicate",
        "wrong_version",
        "bad_json",
        "changed",
    ],
)
def test_SEC_22_only_complete_current_pins_can_record_clean_audit(
    audit_project: Path, engine: Engine, clock: FrozenClock, fault: str
) -> None:
    ledger, calls = Ledger(engine, clock), []

    def runner(path: Path) -> bytes:
        calls.append(path.name)
        if fault == "unavailable":
            raise ProviderError("Synthetic unavailable auditor")
        rows: list[dict[str, object]] = [
            {"name": name, "version": version, "vulns": []}
            for name, version in active_pins(path).items()
        ]
        if fault == "partial":
            rows.pop()
        if fault == "vulnerability":
            rows[0]["vulns"] = [{"id": "SYNTHETIC-CVE"}]
        if fault == "duplicate":
            rows[-1] = rows[0]
        if fault == "wrong_version":
            rows[0]["version"] = "0.0.0"
        if fault == "bad_json":
            return b"not json"
        if fault == "changed" and path.name == LOCKS[-1]:
            path.write_text(path.read_text() + "\n# Synthetic concurrent host edit\n")
        return json.dumps({"dependencies": rows, "fixes": []}).encode()

    if fault:
        with pytest.raises((DataIntegrityError, ProviderError)):
            audit(audit_project, ledger, "Synthetic operator", runner=runner)
    else:
        expected = {name: len(active_pins(audit_project / name)) for name in LOCKS}
        assert audit(audit_project, ledger, "Synthetic operator", runner=runner) == expected
        assert calls == list(LOCKS)
    with Session(engine) as session:
        row = session.scalar(select(SecurityEvent).order_by(SecurityEvent.seq.desc()))
        assert row is not None
        assert row.kind == ("PIP_AUDIT_FAILED" if fault else "PIP_AUDIT_PASSED")
        assert row.detail["operator"] == "Synthetic operator"
        if not fault:
            assert row.detail["lock_hashes"] == lock_hashes(audit_project)
    ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["", "old", "changed", "failed"])
async def test_SEC_22_doctor_audit_status_is_bound_to_current_locks(
    audit_project: Path, engine: Engine, fault: str
) -> None:
    from backend.data.market_calendar import MarketCalendar
    from backend.tests.test_doctor import make

    doctor = make(engine, MarketCalendar(), audit_project)
    detail = {"lock_hashes": lock_hashes(audit_project)}
    doctor.state.ledger.append(
        SecurityEvent,
        kind="PIP_AUDIT_FAILED" if fault == "failed" else "PIP_AUDIT_PASSED",
        detail=detail,
    )
    if fault == "old":
        from backend.tests.test_broker_clock import MovingClock

        assert isinstance(doctor.clock, MovingClock)
        doctor.clock.current += timedelta(days=8)
    if fault == "changed":
        path = audit_project / LOCKS[0]
        path.write_text(path.read_text() + "\n# Synthetic change\n")
    result = await doctor.run()
    checked = next(row for row in result.checks if row.name == "last_dependency_audit")
    assert checked.status == ("PASS" if not fault else "WARN")
