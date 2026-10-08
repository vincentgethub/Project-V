"""OPS-04: nightly authenticated backups; prune only verified owned archives."""

import asyncio
import re
from datetime import timedelta
from pathlib import Path

from backend.agents.orchestrator import JobCounts
from backend.core.clock import ensure_utc
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.ops.anchors import controlled_path
from backend.ops.backups import MAX_BACKUP_BYTES, BackupService

_NAME = re.compile(r"^vws-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.vwsbak$")


class NightlyMaintenance:
    def __init__(self, backups: BackupService, retention_days: int = 30) -> None:
        if type(retention_days) is not int or not 1 <= retention_days <= 365:
            raise ConfigurationError("Backup retention must be 1 through 365 days")
        self.backups, self.retention_days = backups, retention_days

    def run(self) -> JobCounts:
        try:
            # A failed create/restore never triggers retention deletion.
            latest = self.backups.create()
            self.backups.restore_test(latest.path)
            cutoff = ensure_utc(self.backups.clock.now()) - timedelta(days=self.retention_days)
            paths = tuple(self.backups.directory.iterdir())
            if len(paths) > 10_000:
                raise DataIntegrityError("Backup directory exceeds the bounded inventory")
            expired: list[Path] = []
            for path in paths:
                if not _NAME.fullmatch(path.name):
                    continue
                path = controlled_path(path)
                if not path.is_file() or path.stat().st_size > MAX_BACKUP_BYTES * 2:
                    raise DataIntegrityError("Backup retention inventory cannot be verified")
                header, _ = self.backups.decrypt_bytes(path.read_bytes())
                if header.created_at <= cutoff and path != latest.path:
                    expired.append(path)
            for path in expired:
                controlled_path(path).unlink()
            self.backups.ledger.append(
                SecurityEvent,
                kind="NIGHTLY_BACKUP_VERIFIED",
                detail={"sha256": latest.header.plaintext_sha256, "expired_files": len(expired)},
            )
            return JobCounts(counts={"backup_verified": 1, "expired_backups": len(expired)})
        except Exception:
            raise DataIntegrityError(
                "Nightly backup/restore/retention failed; review the backup alert"
            ) from None

    async def __call__(self) -> JobCounts:
        return await asyncio.to_thread(self.run)
