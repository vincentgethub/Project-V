"""SEC-15/SEC-40: authenticated encrypted SQLite backups and restore drills."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr
from sqlalchemy import select

from backend.core.clock import Clock, ensure_utc
from backend.core.database import SecurityEvent, create_database, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, UTCDateTime
from backend.ops.anchors import LedgerAnchors, controlled_path
from backend.security.secrets import SecretStore

MAGIC = b"VWSBAK1\n"
MAX_BACKUP_BYTES = 256 * 1024 * 1024


class BackupHeader(FrozenModel):
    """SEC-40: plaintext metadata is repeated inside authenticated ciphertext."""

    version: Literal[1] = 1
    created_at: UTCDateTime
    plaintext_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plaintext_bytes: int = Field(strict=True, gt=0, le=MAX_BACKUP_BYTES)


class BackupResult(FrozenModel):
    """SEC-40: encrypted-file identity, never a plaintext backup path."""

    path: Path
    header: BackupHeader


class RestoreResult(FrozenModel):
    """SEC-40/SEC-42: a temporary restore verified its bytes and every chain."""

    plaintext_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seq: int = Field(strict=True, ge=0)
    anchor_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackupService:
    """SEC-40: only .vwsbak outputs survive; restore scratch files are removed.

    The online SQLite backup API copies a consistent image to RAM. Fernet needs
    the whole image in memory, so images above 256 MiB fail with a typed error.
    PostgreSQL backup tooling belongs to Stage H and is not guessed here.
    """

    def __init__(self, ledger: Ledger, clock: Clock, store: SecretStore, directory: Path) -> None:
        self.ledger = ledger
        self.clock = clock
        self.store = store
        self.directory = directory

    def _key(self, *, create: bool = False) -> SecretStr:
        key = self.store.get("VWS_BACKUP_KEY")
        if key is None and create:
            # VERIFY: https://cryptography.io/en/stable/fernet/
            key = SecretStr(Fernet.generate_key().decode("ascii"))
            self.store.set("VWS_BACKUP_KEY", key)
            if self.store.get("VWS_BACKUP_KEY") != key:
                raise DataIntegrityError("SEC-40: backup key was not retained by secret storage")
        if not isinstance(key, SecretStr):
            raise DataIntegrityError("SEC-40: backup key is unavailable")
        Fernet(key.get_secret_value().encode("ascii"))
        return key

    def show_key_once(self) -> SecretStr:
        """SEC-15: the owner can copy the recovery key once, never through logs."""
        try:
            with transaction(self.ledger.engine) as session:
                prior = session.scalar(
                    select(SecurityEvent).where(SecurityEvent.kind == "BACKUP_KEY_SHOWN").limit(1)
                )
                if prior is not None or self.store.get("VWS_BACKUP_KEY_SHOWN") is not None:
                    raise DataIntegrityError("SEC-15: backup key was already shown")
                key = self._key(create=True)
                self.store.set("VWS_BACKUP_KEY_SHOWN", SecretStr("shown"))
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="BACKUP_KEY_SHOWN",
                    telegram_user_id=None,
                    detail={},
                    ts=ensure_utc(self.clock.now()),
                )
                return key
        except Exception:
            raise DataIntegrityError("SEC-15: backup recovery key cannot be shown") from None

    def snapshot_bytes(self) -> bytes:
        try:
            if self.ledger.engine.dialect.name != "sqlite":
                raise ValueError("online backup only supports SQLite")
            self.ledger.verify_chain()
            source = self.ledger.engine.raw_connection()
            try:
                driver = source.driver_connection
                if not isinstance(driver, sqlite3.Connection):
                    raise ValueError("unverified SQLite transport")
                target = sqlite3.connect(":memory:")
                try:
                    # VERIFY: https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup
                    driver.backup(target)
                    # VERIFY: https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.serialize
                    image = target.serialize()
                finally:
                    target.close()
            finally:
                source.close()
            if not image or len(image) > MAX_BACKUP_BYTES:
                raise ValueError("backup image size exceeds supported bound")
            return image
        except Exception:
            raise DataIntegrityError("SEC-40: consistent SQLite backup could not be read") from None

    def encrypt_bytes(self, image: bytes) -> tuple[BackupHeader, bytes]:
        try:
            if type(image) is not bytes:
                raise ValueError("backup image must be bytes")
            header = BackupHeader(
                created_at=ensure_utc(self.clock.now()),
                plaintext_sha256=hashlib.sha256(image).hexdigest(),
                plaintext_bytes=len(image),
            )
            encoded = header.model_dump_json().encode("utf-8")
            cipher = Fernet(self._key(create=True).get_secret_value().encode("ascii"))
            token = cipher.encrypt_at_time(
                encoded + b"\n" + image, int(header.created_at.timestamp())
            )
            return header, MAGIC + encoded + b"\n" + token
        except Exception:
            raise DataIntegrityError("SEC-40: backup encryption failed") from None

    def decrypt_bytes(self, payload: bytes) -> tuple[BackupHeader, bytes]:
        try:
            if (
                type(payload) is not bytes
                or len(payload) > MAX_BACKUP_BYTES * 2
                or not payload.startswith(MAGIC)
            ):
                raise ValueError("invalid encrypted backup format")
            encoded, token = payload[len(MAGIC) :].split(b"\n", 1)
            if len(encoded) > 2048:
                raise ValueError("backup header too large")
            decoded = base64.b64decode(token, altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(decoded) != token:
                raise ValueError("backup ciphertext encoding is noncanonical")
            values = json.loads(encoded)
            if not isinstance(values, dict) or not isinstance(values.get("created_at"), str):
                raise ValueError("backup header timestamp missing")
            values["created_at"] = datetime.fromisoformat(values["created_at"])
            header = BackupHeader.model_validate(values)
            if header.created_at > ensure_utc(self.clock.now()):
                raise ValueError("backup timestamp is future")
            cipher = Fernet(self._key().get_secret_value().encode("ascii"))
            authenticated = cipher.decrypt(token)
            inside, image = authenticated.split(b"\n", 1)
            if (
                inside != encoded
                or len(image) != header.plaintext_bytes
                or hashlib.sha256(image).hexdigest() != header.plaintext_sha256
            ):
                raise ValueError("backup metadata or plaintext digest mismatch")
            return header, image
        except Exception:
            raise DataIntegrityError("SEC-40: encrypted backup authentication failed") from None

    def create(self) -> BackupResult:
        try:
            directory = controlled_path(self.directory)
            directory.mkdir(exist_ok=True, mode=0o700)
            name = f"vws-{ensure_utc(self.clock.now()).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex}.vwsbak"
            destination = controlled_path(self.directory / name)
            header, payload = self.encrypt_bytes(self.snapshot_bytes())
            with destination.open("xb") as handle:
                os.chmod(destination, 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self.ledger.append(
                SecurityEvent,
                kind="BACKUP_CREATED",
                telegram_user_id=None,
                detail={"sha256": header.plaintext_sha256, "filename": name},
                ts=header.created_at,
            )
            return BackupResult(path=destination, header=header)
        except Exception:
            raise DataIntegrityError("SEC-40: encrypted backup could not be created") from None

    def restore_test(self, path: Path) -> RestoreResult:
        try:
            if path.stat().st_size > MAX_BACKUP_BYTES * 2:
                raise ValueError("backup too large")
            header, image = self.decrypt_bytes(path.read_bytes())
            with tempfile.TemporaryDirectory(prefix="vws-restore-") as scratch:
                os.chmod(scratch, 0o700)
                database_path = Path(scratch) / "restored.sqlite3"
                descriptor = os.open(database_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(image)
                restored = create_database(f"sqlite:///{database_path.as_posix()}")
                try:
                    from backend.ops.migrations import prepare_verification_copy

                    prepare_verification_copy(restored)
                    ledger = Ledger(restored, self.clock)
                    ledger.verify_chain()
                    anchor = LedgerAnchors(ledger, self.clock).create()
                finally:
                    restored.dispose()
            result = RestoreResult(
                plaintext_sha256=header.plaintext_sha256,
                seq=anchor.seq,
                anchor_digest=anchor.digest,
            )
            self.ledger.append(
                SecurityEvent,
                kind="RESTORE_TEST_PASSED",
                telegram_user_id=None,
                detail=result.model_dump(mode="json"),
                ts=ensure_utc(self.clock.now()),
            )
            return result
        except Exception:
            raise DataIntegrityError("SEC-40: backup restore verification failed") from None
