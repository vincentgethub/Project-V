"""QV-06: owner-curated, hash-bound point-in-time membership; no data fetching."""

import csv
import hashlib
import io
from collections.abc import Collection
from datetime import date
from pathlib import Path
from typing import Any, Self

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.data.history import Digest
from backend.domain.models import FrozenModel, SessionDate, Symbol

PIT_NOTICE = (
    "POINT-IN-TIME universe from the registered historical membership file. "
    "Delisted history availability is UNVERIFIED; incomplete bars fail closed."
)


class Membership(FrozenModel):
    symbol: Symbol
    date_added: SessionDate
    date_removed: SessionDate | None = None

    @model_validator(mode="after")
    def dates(self) -> Self:
        if self.date_removed is not None and self.date_removed <= self.date_added:
            raise ValueError("QV-06: removal must follow addition")
        return self

    def contains(self, day: date) -> bool:
        return self.date_added <= day and (self.date_removed is None or day < self.date_removed)


class HistoricalUniverse(FrozenModel):
    file_sha256: Digest
    rows: tuple[Membership, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        keys = tuple((row.symbol, row.date_added) for row in self.rows)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("QV-06: ordered unique membership intervals required")
        for first, second in zip(self.rows, self.rows[1:], strict=False):
            if first.symbol == second.symbol and (
                first.date_removed is None or first.date_removed > second.date_added
            ):
                raise ValueError("QV-06: membership intervals cannot overlap")
        return self

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted({row.symbol for row in self.rows}))

    def contains(self, symbol: str, day: date) -> bool:
        return any(row.symbol == symbol and row.contains(day) for row in self.rows)

    @classmethod
    def recorded(cls, values: dict[str, Any]) -> "HistoricalUniverse":
        return cls.model_validate(
            {
                **values,
                "rows": tuple(
                    {
                        **row,
                        "date_added": date.fromisoformat(row["date_added"]),
                        "date_removed": None
                        if row["date_removed"] is None
                        else date.fromisoformat(row["date_removed"]),
                    }
                    for row in values["rows"]
                ),
            }
        )


def load(path: Path, allowed: Collection[str]) -> HistoricalUniverse | None:
    if not path.exists():
        return None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256000:
            raise ValueError("bounded regular membership file required")
        raw = path.read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != ["symbol", "date_added", "date_removed"]:
            raise ValueError("exact QV-06 columns required")
        rows = []
        for index, row in enumerate(reader):
            if index >= 1000 or set(row) != set(reader.fieldnames) or None in row.values():
                raise ValueError("bounded complete CSV rows required")
            rows.append(
                Membership(
                    symbol=row["symbol"],
                    date_added=date.fromisoformat(row["date_added"]),
                    date_removed=date.fromisoformat(row["date_removed"])
                    if row["date_removed"]
                    else None,
                )
            )
        result = HistoricalUniverse(
            file_sha256=hashlib.sha256(raw).hexdigest(),
            rows=tuple(sorted(rows, key=lambda row: (row.symbol, row.date_added))),
        )
        if not set(result.symbols).issubset(allowed) or len(result.symbols) > 100:
            raise ValueError(
                "historical symbols require allowlisted instrument metadata, at most 100"
            )
        return result
    except Exception:
        raise DataIntegrityError(
            "QV-06: historical membership file is invalid; no universe inferred"
        ) from None
