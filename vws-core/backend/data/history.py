"""DQ-01/03/04: sealed SIP history, raw audit prices and known split evidence.

Sealing is an explicit host operation, never a replay side effect. A manifest
is published last; existing snapshots are never overwritten. Consumers verify
every byte and XNYS session before exposing a bar. Vendor subcent prices are
rejected by the existing price boundary, rather than silently rounded.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from backend.core.config import _bounded_exact_decimal
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import AsyncAlpacaMarketData, Bar
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, SessionDate, Symbol
from backend.ops.anchors import controlled_path

Adjustment = Literal["RAW", "SPLIT", "DIVIDEND", "SPIN_OFF", "ALL"]
Ratio = Annotated[Decimal, BeforeValidator(_bounded_exact_decimal), Field(gt=0, le=1000000)]
Digest = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
_LIMIT = 16 * 1024 * 1024


def canonical_bytes(model: FrozenModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        + b"\n"
    )


class KnownSplit(FrozenModel):
    symbol: Symbol
    effective_session: SessionDate
    new_shares_per_old: Ratio

    @model_validator(mode="after")
    def changed(self) -> Self:
        if self.new_shares_per_old == 1:
            raise ValueError("DQ-01: a split must change the share ratio")
        return self


class HistorySeries(FrozenModel):
    symbol: Symbol
    feed: Literal["SIP"] = "SIP"
    adjustment: Adjustment
    bars: tuple[Bar, ...] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if any(not 0 < bar.volume <= 2**53 for bar in self.bars) or any(
            previous.session_date >= following.session_date
            for previous, following in zip(self.bars, self.bars[1:], strict=False)
        ):
            raise ValueError("DQ-03: sessions must be unique, increasing and have volume")
        return self

    @property
    def sessions(self) -> tuple[date, ...]:
        return tuple(bar.session_date for bar in self.bars)


class HistoryBundle(FrozenModel):
    series: tuple[HistorySeries, ...] = Field(min_length=3, max_length=500)
    splits: tuple[KnownSplit, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        keys = tuple((item.symbol, item.adjustment) for item in self.series)
        split_keys = tuple((item.symbol, item.effective_session) for item in self.splits)
        if len(set(keys)) != len(keys) or len(set(split_keys)) != len(split_keys):
            raise ValueError("DQ-01: duplicate history series or corporate action")
        symbols = {item.symbol for item in self.series}
        if any(item.symbol not in symbols for item in self.splits):
            raise ValueError("DQ-01: corporate action has no history symbol")
        for symbol in symbols:
            selected = tuple(item for item in self.series if item.symbol == symbol)
            if not {"RAW", "SPLIT", "ALL"}.issubset({item.adjustment for item in selected}):
                raise ValueError("DQ-01: raw audit, split signals and all benchmark are required")
            if any(item.sessions != selected[0].sessions for item in selected[1:]):
                raise ValueError("DQ-03: adjusted and raw sessions differ")
            raw, split = self.for_symbol(symbol, "RAW"), self.for_symbol(symbol, "SPLIT")
            actions = {
                item.effective_session: item for item in self.splits if item.symbol == symbol
            }
            if any(day not in raw.sessions[1:] for day in actions):
                raise ValueError("DQ-01: split must follow the audit anchor and have a bar")
            # Cross multiplication avoids rounding a nonterminating ratio. Raw
            # fills remain in native cents; split data supplies economic continuity.
            with localcontext() as precision:
                precision.prec = 256
                cumulative = Decimal(1)
                for native, adjusted in zip(raw.bars, split.bars, strict=True):
                    action = actions.get(native.session_date)
                    if action is not None:
                        cumulative *= action.new_shares_per_old
                    for native_price, adjusted_price in zip(
                        (native.open, native.high, native.low, native.close),
                        (adjusted.open, adjusted.high, adjusted.low, adjusted.close),
                        strict=True,
                    ):
                        if (
                            native_price * split.bars[0].close * cumulative
                            != adjusted_price * raw.bars[0].close
                        ):
                            raise ValueError(
                                "DQ-03: split/raw prices change without matching action"
                            )
        return self

    def for_symbol(self, symbol: str, adjustment: Adjustment) -> HistorySeries:
        for item in self.series:
            if (item.symbol, item.adjustment) == (symbol, adjustment):
                return item
        raise DataIntegrityError("DQ-04: required symbol/adjustment is absent from frozen history")


class ManifestEntry(FrozenModel):
    symbol: Symbol
    adjustment: Adjustment
    sessions: tuple[SessionDate, ...] = Field(min_length=1, max_length=20000)
    sha256: Digest
    filename: str = Field(
        strict=True, pattern=r"^[A-Z][A-Z0-9.\-]{0,14}_(RAW|SPLIT|DIVIDEND|SPIN_OFF|ALL)\.json$"
    )

    @model_validator(mode="after")
    def bound_name(self) -> Self:
        if self.filename != f"{self.symbol}_{self.adjustment}.json" or any(
            previous >= following
            for previous, following in zip(self.sessions, self.sessions[1:], strict=False)
        ):
            raise ValueError("DQ-04: manifest name and unique sessions must match identity")
        return self


class HistoryManifest(FrozenModel):
    format_version: Literal[1] = 1
    entries: tuple[ManifestEntry, ...] = Field(min_length=3, max_length=500)
    splits: tuple[KnownSplit, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def canonical_order(self) -> Self:
        keys = tuple((entry.symbol, entry.adjustment) for entry in self.entries)
        actions = tuple((action.symbol, action.effective_session) for action in self.splits)
        if keys != tuple(sorted(set(keys))) or actions != tuple(sorted(set(actions))):
            raise ValueError("DQ-04: manifest identities must be unique and canonically ordered")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class FrozenHistory(FrozenModel):
    manifest: HistoryManifest
    bundle: HistoryBundle

    @model_validator(mode="after")
    def bound_manifest(self) -> Self:
        if self.manifest.splits != tuple(
            sorted(self.bundle.splits, key=lambda x: (x.symbol, x.effective_session))
        ):
            raise ValueError("DQ-04: split proof differs from the manifest")
        actual = tuple(sorted(self.bundle.series, key=lambda x: (x.symbol, x.adjustment)))
        if len(actual) != len(self.manifest.entries):
            raise ValueError("DQ-04: manifest series count differs")
        for item, entry in zip(actual, self.manifest.entries, strict=True):
            if (
                item.symbol,
                item.adjustment,
                item.sessions,
                hashlib.sha256(canonical_bytes(item)).hexdigest(),
            ) != (entry.symbol, entry.adjustment, entry.sessions, entry.sha256):
                raise ValueError("DQ-04: frozen series identity, sessions or digest differs")
        return self


def validate_history(bundle: HistoryBundle, calendar: MarketCalendar) -> HistoryBundle:
    try:
        checked = HistoryBundle.model_validate(bundle)
        for item in checked.series:
            first, last = item.sessions[0], item.sessions[-1]
            if not calendar.is_session(first) or not calendar.is_session(last):
                raise ValueError("non-session history endpoint")
            expected: tuple[date, ...] = (first,)
            if first != last:
                expected = (*calendar.previous_sessions(last, len(item.sessions) - 1), last)
            if item.sessions != expected:
                raise ValueError("missing or non-XNYS session")
        return checked
    except Exception:
        raise DataIntegrityError("DQ-03: frozen history is SUSPECT; replay refused") from None


def _read(path: Path) -> bytes:
    checked = controlled_path(path)
    with checked.open("rb") as stream:
        contents = stream.read(_LIMIT + 1)
    if len(contents) > _LIMIT:
        raise DataIntegrityError("DQ-04: frozen history file exceeds its bound")
    return contents


def seal_history(root: Path, bundle: HistoryBundle, calendar: MarketCalendar) -> FrozenHistory:
    """Write once to an existing direct history directory; manifest comes last."""
    try:
        checked = validate_history(bundle, calendar)
        ordered = tuple(sorted(checked.series, key=lambda item: (item.symbol, item.adjustment)))
        entries = tuple(
            ManifestEntry(
                symbol=item.symbol,
                adjustment=item.adjustment,
                sessions=item.sessions,
                sha256=hashlib.sha256(canonical_bytes(item)).hexdigest(),
                filename=f"{item.symbol}_{item.adjustment}.json",
            )
            for item in ordered
        )
        manifest = HistoryManifest(
            entries=entries,
            splits=tuple(
                sorted(checked.splits, key=lambda item: (item.symbol, item.effective_session))
            ),
        )
        paths = tuple(controlled_path(root / entry.filename) for entry in entries)
        manifest_path = controlled_path(root / "manifest.json")
        if any(path.exists() for path in (*paths, manifest_path)):
            raise DataIntegrityError("DQ-04: existing frozen history cannot be overwritten")
        for path, item in zip(paths, ordered, strict=True):
            with path.open("xb") as stream:
                stream.write(canonical_bytes(item))
        with manifest_path.open("xb") as stream:
            stream.write(canonical_bytes(manifest))
        return FrozenHistory(
            manifest=manifest, bundle=HistoryBundle(series=ordered, splits=manifest.splits)
        )
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("DQ-04: history sealing failed; no replay permitted") from None


def load_history(root: Path, calendar: MarketCalendar) -> FrozenHistory:
    """Pure replay's only data adapter: local sealed files, no provider fallback."""
    try:
        contents = _read(root / "manifest.json")
        payload = json.loads(contents, parse_float=Decimal)
        for entry_payload in payload["entries"]:
            entry_payload["sessions"] = tuple(
                date.fromisoformat(day) for day in entry_payload["sessions"]
            )
        for split_payload in payload["splits"]:
            split_payload["effective_session"] = date.fromisoformat(
                split_payload["effective_session"]
            )
        manifest = HistoryManifest.model_validate(payload)
        if contents != canonical_bytes(manifest):
            raise DataIntegrityError("DQ-04: manifest bytes are not canonical")
        series: list[HistorySeries] = []
        for entry in manifest.entries:
            contents = _read(root / entry.filename)
            if hashlib.sha256(contents).hexdigest() != entry.sha256:
                raise DataIntegrityError("DQ-04: historical data hash differs")
            payload = json.loads(contents, parse_float=Decimal)
            payload["bars"] = tuple(
                AsyncAlpacaMarketData._cached_bar(bar) for bar in payload["bars"]
            )
            item = HistorySeries.model_validate(payload)
            if contents != canonical_bytes(item):
                raise DataIntegrityError("DQ-04: historical data bytes are not canonical")
            series.append(item)
        checked = validate_history(
            HistoryBundle(series=tuple(series), splits=manifest.splits), calendar
        )
        return FrozenHistory(manifest=manifest, bundle=checked)
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError(
            "DQ-04: missing or malformed frozen history; replay refused"
        ) from None
