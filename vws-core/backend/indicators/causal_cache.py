"""PF-02/03: bounded, pickle-free economic arrays before day-basis quantization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from pydantic import TypeAdapter

from backend.agents.indicators import Array
from backend.core.errors import DataIntegrityError
from backend.data.history import Digest
from backend.domain.models import validate_symbol
from backend.ops.anchors import controlled_path

CODE_VERSION = "pf3-causal-v1"
FIELDS = ("ema20", "ema50", "ema200", "atr14", "rsi14", "rvol20", "typical", "volume")
MAX_BYTES = 32 * 1024 * 1024
PARAMS = {
    "ema": (20, 50, 200),
    "wilder": 14,
    "rvol": 20,
    "basis": "native_raw_times_effective_splits",
    "anchor": "last60_low_or_newer_gap",
}


def _json(payload: object) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _digest(arrays: dict[str, Array]) -> str:
    digest = hashlib.sha256()
    for field in FIELDS:
        digest.update(field.encode("ascii") + b"\n")
        digest.update(arrays[field].tobytes(order="C"))
    return digest.hexdigest()


def _checked(arrays: dict[str, Array], rows: int) -> dict[str, Array]:
    if set(arrays) != set(FIELDS):
        raise ValueError("causal array inventory differs")
    for name, values in arrays.items():
        if values.dtype != np.dtype("float64") or values.shape != (rows,) or np.isinf(values).any():
            raise ValueError("causal array type/shape/finiteness differs")
        if name in {"typical", "volume"} and (
            not np.isfinite(values).all() or not (values > 0).all()
        ):
            raise ValueError("economic price/volume unavailable")
        defined = values[np.isfinite(values)]
        if (defined < 0).any() or (name == "rsi14" and (defined > 100).any()):
            raise ValueError("causal indicator is out of bounds")
        values.setflags(write=False)
    return arrays


def load_or_compute(
    root: Path | None,
    symbol: str,
    last: date,
    rows: int,
    source_sha256: str,
    actions_sha256: str,
    compute: Callable[[], dict[str, Array]],
) -> dict[str, Array]:
    try:
        validate_symbol(symbol)
        if type(last) is not date or type(rows) is not int or not 1 <= rows <= 20000:
            raise ValueError("bounded causal cache scope required")
        TypeAdapter(Digest).validate_python(source_sha256)
        TypeAdapter(Digest).validate_python(actions_sha256)
        if root is None:
            return _checked(compute(), rows)
        params_hash = hashlib.sha256(_json(PARAMS).encode("ascii")).hexdigest()
        path = controlled_path(
            root / f"{symbol}_SPLIT_{last.isoformat()}_{params_hash}_{CODE_VERSION}.npz"
        )
        signature = {
            "format_version": 1,
            "symbol": symbol,
            "last_session": last.isoformat(),
            "rows": rows,
            "source_sha256": source_sha256,
            "actions_sha256": actions_sha256,
            "parameters_sha256": params_hash,
            "code_version": CODE_VERSION,
            "feed": "SIP",
            "adjustment": "SPLIT",
        }
        if path.exists():
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("causal cache exceeds compressed bound")
            with ZipFile(path) as archive:
                members = archive.infolist()
                if (
                    len(members) != len(FIELDS) + 1
                    or {item.filename for item in members}
                    != {f"{name}.npy" for name in (*FIELDS, "metadata")}
                    or sum(item.file_size for item in members) > MAX_BYTES
                ):
                    raise ValueError("causal cache member inventory/decoded size differs")
            with np.load(path, allow_pickle=False) as stored:
                metadata = stored["metadata"]
                if metadata.shape != () or metadata.dtype.kind != "U" or metadata.nbytes > 65536:
                    raise ValueError("causal cache metadata differs")
                payload = json.loads(str(metadata.item()))
                if (
                    set(payload) != {*signature, "output_sha256"}
                    or {name: payload[name] for name in signature} != signature
                ):
                    raise ValueError("causal cache identity/source differs")
                arrays = _checked({name: stored[name] for name in FIELDS}, rows)
                if _digest(arrays) != payload["output_sha256"]:
                    raise ValueError("causal cache output digest differs")
                return arrays
        arrays = _checked(compute(), rows)
        with path.open("xb") as stream:
            np.savez_compressed(
                stream,
                allow_pickle=False,
                metadata=np.asarray(_json({**signature, "output_sha256": _digest(arrays)})),
                **arrays,
            )
        return arrays
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("PF-02: causal indicator cache is unverifiable") from None
