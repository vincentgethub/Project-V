"""PF-02/DQ-01: bounded npz cache, exact decoded values and split invalidation.

Only public indicator arrays are stored. Existing malformed, changed-input or
wrong-version files fail closed; reads never silently manufacture a successful
cache hit. NumPy object/pickle arrays and oversized zip members are refused.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

import numpy as np
from numpy.typing import NDArray

from backend.agents.indicators import IndicatorSeries, MACDSeries, _bars, _export
from backend.core.errors import DataIntegrityError
from backend.core.money import CENT
from backend.data.data_layer import Bar, _bars_digest
from backend.data.history import Adjustment
from backend.domain.models import validate_symbol
from backend.indicators import vectorized
from backend.ops.anchors import controlled_path

CODE_VERSION = "pf1-v1"
_MAX_BYTES = 32 * 1024 * 1024
_MAX_ROWS = 20000
_FIELDS = (
    "ema20",
    "ema50",
    "ema200",
    "rsi14",
    "atr14",
    "rvol20",
    "anchored_vwap",
    "macd_line",
    "macd_signal",
    "macd_histogram",
)
_PRICE_FIELDS = frozenset(_FIELDS) - {"rsi14", "rvol20"}


def _json(payload: object) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _output_digest(result: IndicatorSeries) -> str:
    return hashlib.sha256(_json(result.model_dump(mode="json")).encode("ascii")).hexdigest()


def _arrays(result: IndicatorSeries) -> dict[str, NDArray[np.float64]]:
    values = (
        result.ema20,
        result.ema50,
        result.ema200,
        result.rsi14,
        result.atr14,
        result.rvol20,
        result.anchored_vwap,
        result.macd.line,
        result.macd.signal,
        result.macd.histogram,
    )
    return {
        name: np.asarray(
            tuple(np.nan if value is None else value for value in series), dtype=np.float64
        )
        for name, series in zip(_FIELDS, values, strict=True)
    }


class IndicatorCache:
    """Explicit existing cache directory; no home, dotenv or network discovery."""

    def __init__(self, root: Path) -> None:
        self.root = controlled_path(root / "cache_probe.npz").parent

    def _identity(
        self,
        symbol: str,
        adjustment: Adjustment,
        feed: Literal["SIP", "FAKE"],
        bars: tuple[Bar, ...],
        anchor_index: int,
    ) -> tuple[Path, dict[str, object], tuple[Bar, ...]]:
        validate_symbol(symbol)
        if adjustment not in {"RAW", "SPLIT", "DIVIDEND", "SPIN_OFF", "ALL"} or feed not in {
            "SIP",
            "FAKE",
        }:
            raise DataIntegrityError("PF-02: unknown cache adjustment or feed")
        checked = _bars(bars)
        if (
            len(checked) > _MAX_ROWS
            or type(anchor_index) is not int
            or not 0 <= anchor_index < len(checked)
        ):
            raise DataIntegrityError("PF-02: invalid cache length or anchor")
        params = {
            "ema": (20, 50, 200),
            "wilder": 14,
            "macd": (12, 26, 9),
            "rvol": 20,
            "anchor_index": anchor_index,
        }
        parameter_hash = hashlib.sha256(_json(params).encode("ascii")).hexdigest()
        session = checked[-1].session_date.isoformat()
        path = controlled_path(
            self.root / f"{symbol}_{adjustment}_{session}_{parameter_hash}_{CODE_VERSION}.npz"
        )
        signature: dict[str, object] = {
            "format_version": 1,
            "symbol": symbol,
            "adjustment": adjustment,
            "feed": feed,
            "last_session": session,
            "parameters_sha256": parameter_hash,
            "code_version": CODE_VERSION,
            "bars_sha256": _bars_digest(checked)[0],
            "rows": len(checked),
        }
        return path, signature, checked

    @staticmethod
    def _calculate(bars: tuple[Bar, ...], anchor: int) -> IndicatorSeries:
        prices = tuple(bar.close for bar in bars)
        return IndicatorSeries(
            ema20=vectorized.ema(prices, 20),
            ema50=vectorized.ema(prices, 50),
            ema200=vectorized.ema(prices, 200),
            rsi14=vectorized.rsi(prices),
            atr14=vectorized.atr(bars),
            macd=vectorized.macd(prices),
            rvol20=vectorized.rvol(tuple(bar.volume for bar in bars)),
            anchored_vwap=vectorized.anchored_vwap(bars, anchor),
        )

    @staticmethod
    def _read(path: Path, signature: dict[str, object]) -> IndicatorSeries:
        if path.stat().st_size > _MAX_BYTES:
            raise DataIntegrityError("PF-02: cache file exceeds its size bound")
        with ZipFile(path) as archive:
            members = archive.infolist()
            if (
                {member.filename for member in members}
                != {f"{field}.npy" for field in (*_FIELDS, "metadata")}
                or len(members) != len(_FIELDS) + 1
                or sum(member.file_size for member in members) > _MAX_BYTES
            ):
                raise DataIntegrityError("PF-02: cache member inventory or decoded size differs")
        with np.load(path, allow_pickle=False) as stored:
            metadata = stored["metadata"]
            if metadata.shape != () or metadata.dtype.kind != "U" or metadata.nbytes > 65536:
                raise DataIntegrityError("PF-02: cache metadata is malformed")
            payload = json.loads(str(metadata.item()))
            if (
                set(payload) != {*signature, "output_sha256"}
                or {name: payload[name] for name in signature} != signature
            ):
                raise DataIntegrityError("PF-02: cached identity or source bars differ")
            decoded: dict[str, tuple[Decimal | None, ...]] = {}
            for field in _FIELDS:
                values = stored[field]
                if values.dtype != np.dtype("float64") or values.shape != (signature["rows"],):
                    raise DataIntegrityError("PF-02: cached array type or length differs")
                decoded[field] = _export(
                    values, CENT if field in _PRICE_FIELDS else Decimal("0.000001")
                )
            result = IndicatorSeries(
                ema20=decoded["ema20"],
                ema50=decoded["ema50"],
                ema200=decoded["ema200"],
                rsi14=decoded["rsi14"],
                atr14=decoded["atr14"],
                rvol20=decoded["rvol20"],
                anchored_vwap=decoded["anchored_vwap"],
                macd=MACDSeries(
                    line=decoded["macd_line"],
                    signal=decoded["macd_signal"],
                    histogram=decoded["macd_histogram"],
                ),
            )
            if payload["output_sha256"] != _output_digest(result):
                raise DataIntegrityError("PF-02: decoded output hash differs")
            return result

    def calculate(
        self,
        symbol: str,
        adjustment: Adjustment,
        bars: tuple[Bar, ...],
        anchor_index: int,
        *,
        feed: Literal["SIP", "FAKE"],
    ) -> IndicatorSeries:
        try:
            path, signature, checked = self._identity(symbol, adjustment, feed, bars, anchor_index)
            if path.exists():
                return self._read(path, signature)
            result = self._calculate(checked, anchor_index)
            payload = {**signature, "output_sha256": _output_digest(result)}
            # The exclusive file handle prevents a competing writer from
            # overwriting evidence. An interrupted write remains a typed fault.
            with path.open("xb") as stream:
                np.savez_compressed(
                    stream,
                    allow_pickle=False,
                    metadata=np.asarray(_json(payload)),
                    **_arrays(result),
                )
            return result
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("PF-02: indicator cache could not be verified") from None

    def invalidate_symbol(self, symbol: str) -> int:
        """DQ-01: remove only that symbol's direct npz artifacts, never ledger rows."""
        try:
            validate_symbol(symbol)
            selected = tuple(sorted(self.root.glob(f"{symbol}_*.npz")))
            if len(selected) > 100000:
                raise DataIntegrityError("DQ-01: indicator cache invalidation exceeds its bound")
            paths = tuple(controlled_path(path) for path in selected)
            if any(path.parent != self.root or not path.is_file() for path in paths):
                raise DataIntegrityError("DQ-01: cache invalidation path is not a direct file")
            for path in paths:
                path.unlink()
            return len(paths)
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("DQ-01: cache invalidation failed") from None
