"""SEC-42: verified global ledger-prefix anchors across every immutable table."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pydantic import Field
from sqlalchemy import select

from backend.core.clock import Clock, ensure_utc
from backend.core.database import LEDGER_MODELS, SecurityEvent, transaction
from backend.core.errors import DataIntegrityError, LedgerIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, UTCDateTime
from backend.security.write_guard import protected_output_path


class LedgerAnchor(FrozenModel):
    """SEC-42: ordered-prefix identity, independent of any individual table head."""

    seq: int = Field(strict=True, ge=0)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: UTCDateTime

    def message(self) -> str:
        return f"🔗 Ledger anchor · seq {self.seq} · {self.digest[:16]}"


def controlled_path(path: Path) -> Path:
    """SEC-12/SEC-42: reject links and indirect parent paths before local writes."""
    try:
        absolute = path.absolute()
        if protected_output_path(absolute.as_posix()):
            raise ValueError("runtime artifacts cannot overwrite source or settings")
        if absolute.is_symlink() or absolute.parent.resolve(strict=True) != absolute.parent:
            raise ValueError("indirect local path")
        if not absolute.name or any(ord(character) < 32 for character in absolute.name):
            raise ValueError("malformed anchor filename")
        return absolute
    except Exception:
        raise DataIntegrityError(
            "SEC-42: anchor destination must use a direct local path"
        ) from None


class LedgerAnchors:
    """SEC-42: record full digests off-box; short Telegram digests are spot checks."""

    def __init__(self, ledger: Ledger, clock: Clock, anchor_path: Path | None = None) -> None:
        self.ledger = ledger
        self.clock = clock
        self.anchor_path = anchor_path

    def create(self, seq: int | None = None) -> LedgerAnchor:
        try:
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                self.ledger._verify_in_session(session)
                entries = sorted(
                    (record.seq, model.__tablename__, record.row_hash)
                    for model in LEDGER_MODELS
                    for record in session.scalars(select(model))
                )
                latest = len(entries)
                selected = latest if seq is None else seq
                if type(selected) is not int or not 0 <= selected <= latest:
                    raise ValueError("anchor sequence outside verified history")
                digest = hashlib.sha256(b"vws-global-ledger-prefix-v1\n")
                for index, table, row_hash in entries[:selected]:
                    digest.update(
                        json.dumps([index, table, row_hash], separators=(",", ":")).encode("utf-8")
                        + b"\n"
                    )
                return LedgerAnchor(
                    seq=selected, digest=digest.hexdigest(), created_at=ensure_utc(self.clock.now())
                )
        except Exception:
            raise LedgerIntegrityError(
                "SEC-42: global ledger anchor could not be verified"
            ) from None

    def verify(self, seq: int, digest: str) -> LedgerAnchor:
        try:
            if (
                not isinstance(digest, str)
                or len(digest) not in {16, 64}
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise ValueError("malformed anchor digest")
            current = self.create(seq)
            if not hmac.compare_digest(current.digest[: len(digest)], digest):
                raise LedgerIntegrityError(f"SEC-42: ledger anchor mismatch at seq {seq}")
            self.ledger.append(
                SecurityEvent,
                kind="ANCHOR_VERIFIED",
                detail={"seq": seq, "digest": current.digest},
                ts=ensure_utc(self.clock.now()),
            )
            return current
        except LedgerIntegrityError:
            raise
        except Exception:
            raise LedgerIntegrityError("SEC-42: invalid anchor verification request") from None

    def verify_file(self, path: Path) -> tuple[LedgerAnchor, ...]:
        try:
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("anchor file too large")
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                raise ValueError("empty anchor file")
            parsed: list[LedgerAnchor] = []
            for line in lines:
                values = json.loads(line)
                if not isinstance(values, dict) or not isinstance(values.get("created_at"), str):
                    raise ValueError("anchor timestamp missing")
                values["created_at"] = datetime.fromisoformat(values["created_at"])
                anchor = LedgerAnchor.model_validate(values)
                if anchor.created_at > ensure_utc(self.clock.now()):
                    raise ValueError("anchor timestamp is future")
                parsed.append(anchor)
            anchors = tuple(parsed)
            for anchor in anchors:
                self.verify(anchor.seq, anchor.digest)
            return anchors
        except Exception:
            raise LedgerIntegrityError("SEC-42: anchor file verification failed") from None

    def record(
        self, path: Path | None = None, send: Callable[[str], None] | None = None
    ) -> LedgerAnchor:
        """SEC-42: append an audit event, optional controlled file and notification."""
        try:
            chosen = self.anchor_path if path is None else path
            if path is not None and (
                self.anchor_path is None or path.absolute() != self.anchor_path.absolute()
            ):
                raise ValueError("anchor file differs from operator configuration")
            anchor = self.create()
            self.ledger.append(
                SecurityEvent,
                kind="LEDGER_ANCHOR",
                telegram_user_id=None,
                detail={"seq": anchor.seq, "digest": anchor.digest},
                ts=anchor.created_at,
            )
            if chosen is not None:
                destination = controlled_path(chosen)
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(descriptor, "ab") as handle:
                    handle.write(anchor.model_dump_json().encode("utf-8") + b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            if send is not None:
                send(anchor.message())
            return anchor
        except Exception:
            raise DataIntegrityError("SEC-42: anchor recording or delivery failed") from None
