"""SEC-15/SEC-40: encrypted byte-identical backups and adversarial restore drills."""

import base64
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.ops.backups import MAGIC, MAX_BACKUP_BYTES, BackupService


class MemorySecrets:
    """SEC-11: tests never discover or write a real operating-system keyring."""

    def __init__(self) -> None:
        self.values: dict[str, SecretStr] = {}
        self.retain = True

    def get(self, name: str) -> SecretStr | None:
        return self.values.get(name)

    def set(self, name: str, value: SecretStr) -> None:
        if self.retain:
            self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def _service(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> tuple[BackupService, MemorySecrets]:
    store = MemorySecrets()
    ledger = Ledger(engine, clock)
    ledger.append(SecurityEvent, kind="BACKUP_FIXTURE", detail={"identity": "synthetic"})
    return BackupService(ledger, clock, store, tmp_path / "backups"), store


def _event_count(engine: Engine, kind: str) -> int:
    with transaction(engine) as session:
        return len(list(session.scalars(select(SecurityEvent).where(SecurityEvent.kind == kind))))


def test_SEC_40_encrypted_roundtrip_is_byte_identical_and_no_plaintext_file_survives(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, store = _service(engine, clock, tmp_path)
    original = service.snapshot_bytes()
    header, encrypted = service.encrypt_bytes(original)
    checked, restored = service.decrypt_bytes(encrypted)
    assert restored == original
    assert checked == header
    assert header.plaintext_sha256 == hashlib.sha256(original).hexdigest()
    assert original[:16] == b"SQLite format 3\x00"
    assert b"SQLite format 3" not in encrypted
    assert store.get("VWS_BACKUP_KEY") is not None
    saved = service.create()
    assert saved.path.suffix == ".vwsbak"
    assert tuple(service.directory.iterdir()) == (saved.path,)
    assert _event_count(engine, "BACKUP_CREATED") == 1
    assert service.decrypt_bytes(saved.path.read_bytes())[0] == saved.header


def test_SEC_40_restore_test_verifies_chain_and_removes_private_scratch(
    engine: Engine, clock: FrozenClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    saved = service.create()
    scratch_paths: list[Path] = []
    actual_directory = tempfile.TemporaryDirectory

    def scratch(*, prefix: str) -> Any:
        directory = actual_directory(prefix=prefix, dir=tmp_path)
        scratch_paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(tempfile, "TemporaryDirectory", scratch)
    result = service.restore_test(saved.path)
    assert result.plaintext_sha256 == saved.header.plaintext_sha256
    assert result.seq == 1  # The BACKUP_CREATED event was written after the saved snapshot.
    assert len(result.anchor_digest) == 64
    assert scratch_paths and all(not path.exists() for path in scratch_paths)
    assert _event_count(engine, "RESTORE_TEST_PASSED") == 1


@pytest.mark.parametrize("where", ["magic", "header", "cipher", "trailing", "truncation"])
def test_SEC_40_any_flipped_or_appended_backup_bytes_refuse(
    engine: Engine, clock: FrozenClock, tmp_path: Path, where: str
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    _, encrypted = service.encrypt_bytes(service.snapshot_bytes())
    if where == "magic":
        tampered = b"X" + encrypted[1:]
    elif where == "header":
        tampered = encrypted.replace(b'"version":1', b'"version":2', 1)
    elif where == "cipher":
        index = encrypted.rfind(b"\n") + 20
        tampered = encrypted[:index] + bytes((encrypted[index] ^ 1,)) + encrypted[index + 1 :]
    elif where == "trailing":
        tampered = encrypted + b"\n"
    else:
        tampered = encrypted[:-3]
    with pytest.raises(DataIntegrityError, match="authentication"):
        service.decrypt_bytes(tampered)
    assert not _event_count(engine, "RESTORE_TEST_PASSED")


def test_SEC_40_wrong_key_and_missing_key_refuse(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, store = _service(engine, clock, tmp_path)
    _, encrypted = service.encrypt_bytes(service.snapshot_bytes())
    store.set("VWS_BACKUP_KEY", SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(DataIntegrityError):
        service.decrypt_bytes(encrypted)
    store.delete("VWS_BACKUP_KEY")
    with pytest.raises(DataIntegrityError):
        service.decrypt_bytes(encrypted)


@pytest.mark.parametrize("corruption", ["sha256", "length", "outside_header", "future_time"])
def test_SEC_40_authenticated_inconsistent_metadata_refuses(
    engine: Engine, clock: FrozenClock, tmp_path: Path, corruption: str
) -> None:
    service, store = _service(engine, clock, tmp_path)
    header, _ = service.encrypt_bytes(service.snapshot_bytes())
    image = service.snapshot_bytes()
    data = json.loads(header.model_dump_json())
    if corruption in {"sha256", "outside_header"}:
        data["plaintext_sha256"] = "f" * 64
    elif corruption == "length":
        data["plaintext_bytes"] += 1
    elif corruption == "future_time":
        data["created_at"] = "2099-01-01T00:00:00Z"
    encoded = json.dumps(data, separators=(",", ":")).encode()
    inside = header.model_dump_json().encode() if corruption == "outside_header" else encoded
    key = store.get("VWS_BACKUP_KEY")
    assert key is not None
    token = Fernet(key.get_secret_value().encode()).encrypt(inside + b"\n" + image)
    with pytest.raises(DataIntegrityError):
        service.decrypt_bytes(MAGIC + encoded + b"\n" + token)


def test_SEC_40_oversized_header_refuses(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    with pytest.raises(DataIntegrityError):
        service.decrypt_bytes(MAGIC + b"x" * 2049 + b"\n" + b"fake")


@pytest.mark.parametrize("image", [b"", "plaintext", bytearray(b"contents"), None])
def test_SEC_40_invalid_image_type_or_size_is_typed(
    engine: Engine, clock: FrozenClock, tmp_path: Path, image: object
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    with pytest.raises(DataIntegrityError):
        service.encrypt_bytes(cast(Any, image))


def test_SEC_40_unretained_or_malformed_key_fails_closed(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, store = _service(engine, clock, tmp_path)
    store.retain = False
    with pytest.raises(DataIntegrityError):
        service.encrypt_bytes(service.snapshot_bytes())
    store.retain = True
    store.set("VWS_BACKUP_KEY", SecretStr("invalid-fake-key"))
    with pytest.raises(DataIntegrityError):
        service.encrypt_bytes(service.snapshot_bytes())


def test_SEC_40_restore_rejects_consistent_cipher_with_tampered_ledger(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_security_events_update")
        connection.exec_driver_sql("UPDATE security_events SET detail='{}'")
    # Encrypting arbitrary bytes is insufficient: restore still verifies ledger integrity.
    raw = service.ledger.engine.raw_connection()
    try:
        image = cast(sqlite3.Connection, raw.driver_connection).serialize()
    finally:
        raw.close()
    _, encrypted = service.encrypt_bytes(image)
    path = tmp_path / "tampered.vwsbak"
    path.write_bytes(encrypted)
    with pytest.raises(DataIntegrityError, match="restore"):
        service.restore_test(path)
    assert not _event_count(engine, "RESTORE_TEST_PASSED")


def test_SEC_40_missing_and_oversized_backup_refuses(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    path = tmp_path / "missing.vwsbak"
    with pytest.raises(DataIntegrityError):
        service.restore_test(path)
    with path.open("wb") as handle:
        handle.truncate(MAX_BACKUP_BYTES * 2 + 1)
    with pytest.raises(DataIntegrityError):
        service.restore_test(path)


def test_SEC_15_recovery_key_can_be_shown_once_with_dated_evidence(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, store = _service(engine, clock, tmp_path)
    key = service.show_key_once()
    assert key == store.get("VWS_BACKUP_KEY")
    assert _event_count(engine, "BACKUP_KEY_SHOWN") == 1
    with pytest.raises(DataIntegrityError):
        service.show_key_once()
    with transaction(engine) as session:
        evidence = session.scalar(
            select(SecurityEvent).where(SecurityEvent.kind == "BACKUP_KEY_SHOWN")
        )
        assert evidence is not None
        assert evidence.detail == {} and evidence.ts == clock.now()
        assert key.get_secret_value() not in str(evidence.detail)


def test_SEC_15_keyring_shown_marker_prevents_second_export_after_ledger_restore(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, store = _service(engine, clock, tmp_path)
    store.set("VWS_BACKUP_KEY_SHOWN", SecretStr("shown"))
    with pytest.raises(DataIntegrityError):
        service.show_key_once()


def test_SEC_40_corruption_before_backup_refuses_and_leaves_no_plaintext_backup(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_security_events_update")
        connection.exec_driver_sql("UPDATE security_events SET detail='{}'")
    with pytest.raises(DataIntegrityError):
        service.create()
    assert tuple(service.directory.iterdir()) == ()


@pytest.mark.parametrize("encoded", [b"{}", b"null", b"[]", b'{"created_at":123}'])
def test_SEC_40_malformed_header_timestamp_is_typed(
    engine: Engine, clock: FrozenClock, tmp_path: Path, encoded: bytes
) -> None:
    service, store = _service(engine, clock, tmp_path)
    store.set("VWS_BACKUP_KEY", SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(DataIntegrityError):
        service.decrypt_bytes(MAGIC + encoded + b"\n" + b"Zg==")


def test_SEC_40_noncanonical_cipher_encoding_refuses(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    _, encrypted = service.encrypt_bytes(service.snapshot_bytes())
    encoded, token = encrypted[len(MAGIC) :].split(b"\n", 1)
    different = base64.b64encode(base64.urlsafe_b64decode(token))
    assert different != token
    with pytest.raises(DataIntegrityError):
        service.decrypt_bytes(MAGIC + encoded + b"\n" + different)


def test_SEC_40_snapshot_size_is_bounded(
    engine: Engine, clock: FrozenClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.ops.backups as backups

    service, _ = _service(engine, clock, tmp_path)
    monkeypatch.setattr(backups, "MAX_BACKUP_BYTES", 1024)
    with pytest.raises(DataIntegrityError):
        service.snapshot_bytes()


def test_SEC_40_unverified_sqlite_transport_is_refused(
    engine: Engine, clock: FrozenClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    closes: list[bool] = []
    fake = SimpleNamespace(driver_connection=object(), close=lambda: closes.append(True))
    # Isolate the transport check after independently verified ledger evidence.
    monkeypatch.setattr(service.ledger, "verify_chain", lambda: None)
    monkeypatch.setattr(engine, "raw_connection", lambda: fake)
    with pytest.raises(DataIntegrityError):
        service.snapshot_bytes()
    assert closes == [True]


def test_SEC_40_postgres_is_explicitly_unavailable_for_sqlite_backup_service(
    engine: Engine, clock: FrozenClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = _service(engine, clock, tmp_path)
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    with pytest.raises(DataIntegrityError):
        service.snapshot_bytes()
