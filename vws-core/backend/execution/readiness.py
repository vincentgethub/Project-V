"""AX-43: authenticated backup proof for the bound host, without SDK imports."""

import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.database import SecurityEvent
from backend.core.errors import ExecutionDisabledError
from backend.execution.models import AutoPrerequisites
from backend.execution.modes import ModeStore
from backend.ops.anchors import controlled_path
from backend.ops.backups import MAX_BACKUP_BYTES, BackupService
from backend.ops.doctor import DoctorResult

_BACKUP = re.compile(r"vws-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.vwsbak\Z")


def verified_backup(service: BackupService) -> datetime:
    service.ledger.verify_chain()
    with Session(service.ledger.engine) as session:
        latest = session.scalar(
            select(SecurityEvent)
            .where(SecurityEvent.kind == "BACKUP_CREATED")
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if latest is None:
            raise ExecutionDisabledError("AX-43: no authenticated backup is recorded")
        name, digest = latest.detail.get("filename"), latest.detail.get("sha256")
        if not isinstance(name, str) or _BACKUP.fullmatch(name) is None:
            raise ExecutionDisabledError("AX-43: backup file binding is invalid")
        path = controlled_path(service.directory / name)
        if not path.is_file() or path.stat().st_size > MAX_BACKUP_BYTES * 2:
            raise ExecutionDisabledError("AX-43: recorded encrypted backup is unavailable")
        header, _ = service.decrypt_bytes(path.read_bytes())
        if header.plaintext_sha256 != digest or header.created_at != latest.ts:
            raise ExecutionDisabledError("AX-43: backup identity differs from its ledger event")
        restored = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "RESTORE_TEST_PASSED",
                SecurityEvent.detail["plaintext_sha256"].as_string() == header.plaintext_sha256,
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
    if (
        not timedelta(0)
        <= ensure_utc(service.clock.now()) - header.created_at
        < timedelta(hours=26)
    ):
        raise ExecutionDisabledError("AX-43: authenticated backup is at least 26 hours old")
    if restored is None:
        service.restore_test(path)
    return header.created_at


class HostPrerequisites:
    def __init__(self, modes: ModeStore, doctor: DoctorResult, backups: BackupService) -> None:
        self.modes, self.doctor, self.backups = modes, DoctorResult.model_validate(doctor), backups
        self.telegram_verified_at = self.clock_verified_at = ensure_utc(modes.state.clock.now())

    async def refresh(self, read: Callable[[], Awaitable[DoctorResult]]) -> None:
        now = ensure_utc(self.modes.state.clock.now())
        if timedelta(0) <= now - self.clock_verified_at < timedelta(minutes=4):
            return
        self.doctor = DoctorResult.model_validate(await read())
        self.telegram_verified_at = self.clock_verified_at = ensure_utc(
            self.modes.state.clock.now()
        )

    def __call__(self) -> AutoPrerequisites:
        return AutoPrerequisites(
            account_id=self.modes.account_id,
            environment=self.modes.environment,
            config_hash=self.modes.settings.config_hash,
            doctor_fully_green=self.doctor.fully_green,
            watchdog_enabled=True,
            backup_chain_verified=True,
            backup_verified_at=verified_backup(self.backups),
            telegram_verified_at=self.telegram_verified_at,
            clock_verified_at=self.clock_verified_at,
        )
