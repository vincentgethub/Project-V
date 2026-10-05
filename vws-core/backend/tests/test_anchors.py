"""SEC-42: off-box anchors bind the full global ledger prefix, not one table head."""

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import ConfigSnapshot, SecurityEvent, transaction
from backend.core.errors import DataIntegrityError, LedgerIntegrityError
from backend.core.ledger import Ledger, row_digest
from backend.ops.anchors import LedgerAnchor, LedgerAnchors, controlled_path


def _event(ledger: Ledger, text: str = "original") -> SecurityEvent:
    return ledger.append(SecurityEvent, kind="TEST_EVIDENCE", detail={"text": text})


def _events(engine: Engine, kind: str) -> list[SecurityEvent]:
    with transaction(engine) as session:
        return list(session.scalars(select(SecurityEvent).where(SecurityEvent.kind == kind)))


def test_SEC_42_empty_prefix_has_domain_separated_digest(
    engine: Engine, clock: FrozenClock
) -> None:
    anchors = LedgerAnchors(Ledger(engine, clock), clock)
    anchor = anchors.create()
    assert anchor.seq == 0
    assert anchor.digest == hashlib.sha256(b"vws-global-ledger-prefix-v1\n").hexdigest()
    assert anchor.created_at == clock.now()
    assert anchor.message() == f"🔗 Ledger anchor · seq 0 · {anchor.digest[:16]}"


def test_SEC_42_digest_covers_every_ordered_table_row(engine: Engine, clock: FrozenClock) -> None:
    ledger = Ledger(engine, clock)
    first = _event(ledger)
    second = ledger.append(ConfigSnapshot, config_hash="a" * 64, settings={"policy": "fixed"})
    third = _event(ledger, "later")
    expected = hashlib.sha256(b"vws-global-ledger-prefix-v1\n")
    for record in (first, second, third):
        expected.update(
            json.dumps(
                [record.seq, record.__tablename__, record.row_hash], separators=(",", ":")
            ).encode()
            + b"\n"
        )
    assert LedgerAnchors(ledger, clock).create().digest == expected.hexdigest()


def test_SEC_42_old_anchor_survives_new_appends_and_verification_is_audited(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    _event(ledger)
    anchors = LedgerAnchors(ledger, clock)
    original = anchors.create()
    _event(ledger, "later")
    assert anchors.verify(original.seq, original.digest).digest == original.digest
    assert anchors.verify(original.seq, original.digest[:16]).digest == original.digest
    verified = _events(engine, "ANCHOR_VERIFIED")
    assert len(verified) == 2
    assert verified[-1].detail == {"seq": original.seq, "digest": original.digest}
    assert verified[-1].ts == clock.now()


@pytest.mark.parametrize("seq", [-1, True, 0.5, "1", 100])
def test_SEC_42_invalid_sequence_is_typed(engine: Engine, clock: FrozenClock, seq: object) -> None:
    with pytest.raises(LedgerIntegrityError, match="anchor"):
        LedgerAnchors(Ledger(engine, clock), clock).create(cast(Any, seq))


@pytest.mark.parametrize("digest", ["", "a" * 15, "a" * 17, "A" * 64, "g" * 64, 123, None])
def test_SEC_42_invalid_digest_is_typed(engine: Engine, clock: FrozenClock, digest: object) -> None:
    with pytest.raises(LedgerIntegrityError):
        LedgerAnchors(Ledger(engine, clock), clock).verify(0, cast(Any, digest))


def test_SEC_42_valid_shaped_wrong_digest_refuses_without_pass_event(
    engine: Engine, clock: FrozenClock
) -> None:
    anchors = LedgerAnchors(Ledger(engine, clock), clock)
    with pytest.raises(LedgerIntegrityError, match="mismatch at seq 0"):
        anchors.verify(0, "f" * 64)
    assert not _events(engine, "ANCHOR_VERIFIED")


@pytest.mark.parametrize("rewrite_hash", [False, True])
def test_SEC_42_tampered_earlier_table_row_fails_even_with_recomputed_local_chain(
    engine: Engine, clock: FrozenClock, rewrite_hash: bool
) -> None:
    ledger = Ledger(engine, clock)
    first = _event(ledger)
    ledger.append(ConfigSnapshot, config_hash="a" * 64, settings={"policy": "fixed"})
    anchors = LedgerAnchors(ledger, clock)
    saved = anchors.create()
    # Simulate a host owner bypassing immutable triggers. Production has no mutation API.
    first.detail = {"text": "tampered"}
    new_hash = row_digest(first) if rewrite_hash else first.row_hash
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER vws_security_events_update")
        connection.exec_driver_sql(
            "UPDATE security_events SET detail=?, row_hash=? WHERE seq=?",
            (json.dumps(first.detail), new_hash, first.seq),
        )
    if rewrite_hash:
        ledger.verify_chain()  # A per-table hash verifier alone cannot detect this rewrite.
    with pytest.raises(LedgerIntegrityError):
        anchors.verify(saved.seq, saved.digest)


def test_SEC_42_record_and_file_verification(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    ledger = Ledger(engine, clock)
    _event(ledger)
    path = tmp_path / "offbox.anchors"
    anchors = LedgerAnchors(ledger, clock, path)
    messages: list[str] = []
    first = anchors.record(send=messages.append)
    second = anchors.record(path=path, send=messages.append)
    assert tuple(item.digest for item in anchors.verify_file(path)) == (first.digest, second.digest)
    assert messages == [first.message(), second.message()]
    assert len(_events(engine, "LEDGER_ANCHOR")) == 2


@pytest.mark.parametrize("content", ["", "{}", "not json", '{"seq": -1}'])
def test_SEC_42_invalid_file_is_typed(
    engine: Engine, clock: FrozenClock, tmp_path: Path, content: str
) -> None:
    path = tmp_path / "invalid.anchors"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LedgerIntegrityError):
        LedgerAnchors(Ledger(engine, clock), clock).verify_file(path)


def test_SEC_42_missing_and_oversized_files_refuse(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    anchors = LedgerAnchors(Ledger(engine, clock), clock)
    path = tmp_path / "missing.anchors"
    with pytest.raises(LedgerIntegrityError):
        anchors.verify_file(path)
    with path.open("wb") as handle:
        handle.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(LedgerIntegrityError):
        anchors.verify_file(path)


def test_SEC_42_record_refuses_unconfigured_destination(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    with pytest.raises(DataIntegrityError):
        LedgerAnchors(Ledger(engine, clock), clock).record(path=tmp_path / "arbitrary.anchors")


def test_SEC_42_delivery_failure_preserves_anchor_evidence(
    engine: Engine, clock: FrozenClock
) -> None:
    def fail(message: str) -> None:
        raise OSError("offline")

    with pytest.raises(DataIntegrityError):
        LedgerAnchors(Ledger(engine, clock), clock).record(send=fail)
    assert len(_events(engine, "LEDGER_ANCHOR")) == 1


@pytest.mark.parametrize("name", ["missing/anchor", "bad\nname"])
def test_SEC_42_destination_validation_is_typed(tmp_path: Path, name: str) -> None:
    with pytest.raises(DataIntegrityError):
        controlled_path(tmp_path / name)


def test_SEC_42_model_is_frozen_and_extra_forbidden(clock: FrozenClock) -> None:
    from pydantic import ValidationError

    anchor = LedgerAnchor(seq=0, digest="a" * 64, created_at=clock.now())
    with pytest.raises(ValidationError):
        anchor.seq = 5
    with pytest.raises(ValidationError):
        LedgerAnchor.model_validate({**anchor.model_dump(), "ignored": True})


def test_SEC_42_indirect_path_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "is_symlink", lambda path: True)
    with pytest.raises(DataIntegrityError):
        controlled_path(tmp_path / "linked.anchors")


def test_SEC_42_future_anchor_file_refuses(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    anchors = LedgerAnchors(Ledger(engine, clock), clock)
    values = anchors.create().model_dump(mode="json")
    values["created_at"] = "2099-01-01T00:00:00Z"
    path = tmp_path / "future.anchors"
    path.write_text(json.dumps(values), encoding="utf-8")
    with pytest.raises(LedgerIntegrityError):
        anchors.verify_file(path)


def test_SEC_42_local_record_without_delivery_is_valid(engine: Engine, clock: FrozenClock) -> None:
    anchors = LedgerAnchors(Ledger(engine, clock), clock)
    assert anchors.record().seq == 0
    assert len(_events(engine, "LEDGER_ANCHOR")) == 1
