"""EV-03/DQ-04: explicit, write-once SEC evidence for offline replay.

The symbol/CIK mapping is part of the frozen manifest. Missing issuers are
unavailable; changed files are errors. Replay never fetches a replacement.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Self, cast

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.data.history import Digest, canonical_bytes
from backend.data.sec_edgar import SecPayload, exact_json
from backend.domain.models import FrozenModel, Symbol, UTCDateTime
from backend.ops.anchors import controlled_path

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024


class FilingEntry(FrozenModel):
    symbol: Symbol
    cik: str = Field(strict=True, pattern=r"^[0-9]{10}$")
    fetched_at: UTCDateTime
    data_sha256: Digest
    bytes: int = Field(strict=True, gt=0, le=MAX_FILE)
    filename: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9.]{0,14}_companyfacts\.json$")

    @model_validator(mode="after")
    def bound_name(self) -> Self:
        if self.filename != f"{self.symbol}_companyfacts.json":
            raise ValueError("EV-03: filing filename differs from issuer")
        return self


class FilingsManifest(FrozenModel):
    format_version: int = Field(default=1, strict=True, ge=1, le=1)
    entries: tuple[FilingEntry, ...] = Field(max_length=200)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        symbols = tuple(entry.symbol for entry in self.entries)
        if (
            symbols != tuple(sorted(set(symbols)))
            or sum(entry.bytes for entry in self.entries) > MAX_TOTAL
        ):
            raise ValueError("EV-03: filing manifest is duplicated, unordered or oversized")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class FilingEvidence(FrozenModel):
    symbol: Symbol
    payload: SecPayload

    @model_validator(mode="after")
    def companyfacts(self) -> Self:
        if self.payload.kind != "COMPANYFACTS" or self.payload.cik is None:
            raise ValueError("EV-03: issuer companyfacts required")
        return self


class FrozenFilings(FrozenModel):
    manifest: FilingsManifest
    evidence: tuple[FilingEvidence, ...] = Field(max_length=200)

    @model_validator(mode="after")
    def bound_manifest(self) -> Self:
        if len(self.manifest.entries) != len(self.evidence):
            raise ValueError("EV-03: filing manifest count differs")
        for entry, item in zip(self.manifest.entries, self.evidence, strict=True):
            payload = item.payload
            if (entry.symbol, entry.cik, entry.fetched_at, entry.data_sha256, entry.bytes) != (
                item.symbol,
                payload.cik,
                payload.fetched_at,
                payload.data_sha256,
                len(payload.raw),
            ):
                raise ValueError("EV-03: frozen issuer evidence differs from manifest")
        return self

    def for_symbol(self, symbol: str) -> SecPayload | None:
        return next((item.payload for item in self.evidence if item.symbol == symbol), None)


def seal_filings(root: Path, evidence: tuple[FilingEvidence, ...]) -> FrozenFilings:
    """Explicit host preparation only; even an empty evidence set is sealed."""
    try:
        if not isinstance(evidence, tuple) or len(evidence) > 200:
            raise ValueError("bounded immutable issuer evidence required")
        rows = tuple(
            sorted(
                (FilingEvidence.model_validate(item) for item in evidence),
                key=lambda item: item.symbol,
            )
        )
        entries = tuple(
            FilingEntry(
                symbol=item.symbol,
                cik=cast(str, item.payload.cik),
                fetched_at=item.payload.fetched_at,
                data_sha256=item.payload.data_sha256,
                bytes=len(item.payload.raw),
                filename=f"{item.symbol}_companyfacts.json",
            )
            for item in rows
        )
        frozen = FrozenFilings(manifest=FilingsManifest(entries=entries), evidence=rows)
        manifest_path = controlled_path(root / "filings_manifest.json")
        paths = tuple(controlled_path(root / entry.filename) for entry in entries)
        if any(path.exists() for path in (*paths, manifest_path)):
            raise ValueError("existing frozen filings cannot be overwritten")
        for path, item in zip(paths, rows, strict=True):
            with path.open("xb") as stream:
                stream.write(item.payload.raw)
        with manifest_path.open("xb") as stream:
            stream.write(canonical_bytes(frozen.manifest))
        return frozen
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-03: filing sealing failed") from None


def load_filings(root: Path) -> FrozenFilings:
    try:
        manifest_path = controlled_path(root / "filings_manifest.json")
        with manifest_path.open("rb") as stream:
            contents = stream.read(1024 * 1024 + 1)
        if len(contents) > 1024 * 1024:
            raise ValueError("filing manifest exceeds its bound")
        decoded = exact_json(contents)
        for entry in decoded["entries"]:
            entry["fetched_at"] = datetime.fromisoformat(entry["fetched_at"])
        manifest = FilingsManifest.model_validate(decoded)
        if contents != canonical_bytes(manifest):
            raise ValueError("filing manifest bytes are not canonical")
        rows: list[FilingEvidence] = []
        for entry in manifest.entries:
            with controlled_path(root / entry.filename).open("rb") as stream:
                raw = stream.read(entry.bytes + 1)
            if len(raw) != entry.bytes:
                raise ValueError("frozen filing byte count differs")
            rows.append(
                FilingEvidence(
                    symbol=entry.symbol,
                    payload=SecPayload(
                        kind="COMPANYFACTS",
                        cik=entry.cik,
                        fetched_at=entry.fetched_at,
                        raw=raw,
                        data_sha256=entry.data_sha256,
                    ),
                )
            )
        return FrozenFilings(manifest=manifest, evidence=tuple(rows))
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("EV-03: missing or malformed frozen filing evidence") from None
