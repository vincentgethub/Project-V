"""Amendment 03 section 10: named live security gates, with no executor import."""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import SecurityEvent
from backend.core.system_state import SystemStateStore
from backend.execution.modes import assert_auto_binding
from backend.ops.anchors import LedgerAnchors
from backend.ops.dependency_audit import active_pins, lock_hashes
from backend.ops.doctor import DoctorResult
from backend.ops.security import ACCOUNT_ITEMS, SecurityOps
from backend.security.secrets import RotationService, SecretStore


class LiveSecurityGuard:
    def __init__(
        self,
        settings: Settings,
        state: SystemStateStore,
        store: SecretStore,
        project: Path,
        *,
        permissions_pass: Callable[[], bool],
        observations: Callable[[], tuple[datetime, DoctorResult]],
        egress_active: Callable[[], bool],
    ) -> None:
        self.settings, self.state, self.store, self.project = (
            Settings.validated_copy(settings),
            state,
            store,
            project,
        )
        self.permissions_pass, self.observations, self.egress_active = (
            permissions_pass,
            observations,
            egress_active,
        )

    def reasons(self) -> tuple[str, ...]:
        self.state.ledger.verify_chain()
        now = ensure_utc(self.state.clock.now())
        with Session(self.state.engine) as session:
            events = tuple(session.scalars(select(SecurityEvent).order_by(SecurityEvent.seq)))
        findings: list[str] = []

        def gate(reason: str, action: Callable[[], bool]) -> None:
            try:
                passed = action() is True
            except Exception:
                passed = False
            if not passed:
                findings.append(reason)

        def keyring() -> bool:
            assert_auto_binding(self.settings, self.store)
            return self.settings.execution_mode == "AUTO_LIVE"

        def recent(kind: str, days: int) -> SecurityEvent | None:
            latest = next((row for row in reversed(events) if row.kind == kind), None)
            if latest is None or not timedelta(0) <= now - latest.ts <= timedelta(days=days):
                return None
            return latest

        def key_age() -> bool:
            rotation = RotationService(self.store, self.state.clock, self.state.ledger, {})
            for name in ("ALPACA_LIVE_KEY_ID", "ALPACA_LIVE_SECRET"):
                proof = next(
                    (
                        row
                        for row in reversed(events)
                        if row.kind == "SECRET_ROTATED" and row.detail.get("name") == name
                    ),
                    None,
                )
                value = self.store.get(name)
                if (
                    proof is None
                    or value is None
                    or not timedelta(0)
                    <= now - proof.ts
                    <= timedelta(days=self.settings.secret_max_age_days)
                    or proof.detail.get("fingerprint") != rotation.fingerprint(name, value)
                ):
                    return False
            return True

        def attestations() -> bool:
            evidence = SecurityOps(self.state.ledger, self.state, self.state.clock).attestations()
            return all(
                item.recorded_at is not None
                and timedelta(0) <= now - item.recorded_at <= timedelta(days=365)
                for item in evidence
                if item.item in ACCOUNT_ITEMS[:7]
            )

        def anchor() -> bool:
            proof = recent("ANCHOR_VERIFIED", 31)
            if proof is None:
                return False
            seq = proof.detail.get("seq")
            if type(seq) is not int or not 0 < seq < proof.seq:
                return False
            return LedgerAnchors(self.state.ledger, self.state.clock).create(
                seq
            ).digest == proof.detail.get("digest")

        def audit() -> bool:
            latest = next(
                (
                    row
                    for row in reversed(events)
                    if row.kind in {"PIP_AUDIT_PASSED", "PIP_AUDIT_FAILED"}
                ),
                None,
            )
            if (
                latest is None
                or latest.kind != "PIP_AUDIT_PASSED"
                or not timedelta(0) <= now - latest.ts <= timedelta(days=7)
            ):
                return False
            hashes = lock_hashes(self.project)
            counts = {name: len(active_pins(self.project / name)) for name in hashes}
            return (
                latest.detail.get("lock_hashes") == hashes and latest.detail.get("counts") == counts
            )

        def observed(name: str) -> bool:
            instant, raw = self.observations()
            result = DoctorResult.model_validate(raw)
            if not timedelta(0) <= now - ensure_utc(instant) <= timedelta(minutes=5):
                return False
            rows = [row for row in result.checks if row.name == name]
            return len(rows) == 1 and rows[0].status == "PASS"

        gate("SEC-10: the complete live keyring binding is required", keyring)
        gate(
            "SEC-13: both current live keys need verified rotation within SECRET_MAX_AGE_DAYS",
            key_age,
        )
        gate("SEC-01: account checklist items 1-7 need attestations within 365 days", attestations)
        gate("SEC-12: all filesystem permissions must pass", self.permissions_pass)
        gate(
            "SEC-40: a successful authenticated restore-test within 30 days is required",
            lambda: recent("RESTORE_TEST_PASSED", 30) is not None,
        )
        gate("SEC-42: an intact anchor verify within 31 days is required", anchor)
        gate("SEC-22: both current dependency locks need a clean pip-audit within 7 days", audit)
        gate(
            "SEC-50/51: current private bot, empty webhook and group settings must pass",
            lambda: observed("telegram_private"),
        )
        gate(
            "SEC-71: a current non-admin/non-root observation must pass",
            lambda: observed("host_administrator"),
        )
        gate("SEC-31/32: the allowlisted HTTPS SDK egress guard must be active", self.egress_active)
        return tuple(findings)
