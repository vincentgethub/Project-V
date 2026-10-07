"""PF-02: warm arrays, source binding, decoded bounds and split clearing."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.agents.indicators import Array, IndicatorMemo
from backend.core.config import YamlConfig
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar
from backend.data.history import HistorySeries
from backend.indicators import causal_cache
from backend.indicators.cache import IndicatorCache
from backend.indicators.causal_cache import FIELDS, load_or_compute
from backend.indicators.replay import precompute_symbol
from backend.tests import test_replay_gates as golden
from backend.tests.test_indicator_cache import _bars

calendar = golden.calendar
bars = golden.bars
policy = golden.policy


def compute() -> dict[str, Array]:
    return {name: np.ones(210, dtype=np.float64) for name in FIELDS}


def cached(root: Path | None, **values: Any) -> dict[str, Array]:
    return load_or_compute(
        root,
        "AAPL",
        date(2026, 9, 28),
        210,
        values.get("source", "a" * 64),
        "b" * 64,
        values.get("compute", compute),
    )


def test_PF_02_warm_causal_arrays_match_and_never_recompute(tmp_path: Path) -> None:
    original = cached(tmp_path)

    def refused() -> dict[str, Array]:
        raise RuntimeError("warm hit recomputed")

    warm = cached(tmp_path, compute=refused)
    assert all(np.array_equal(original[name], warm[name], equal_nan=True) for name in FIELDS)
    assert all(not values.flags.writeable for values in warm.values())
    with pytest.raises(DataIntegrityError):
        cached(tmp_path, source="c" * 64)
    assert all(np.array_equal(original[name], cached(None)[name]) for name in FIELDS)


@pytest.mark.parametrize(
    "fault",
    [
        "metadata",
        "metadata_type",
        "metadata_size",
        "member",
        "shape",
        "dtype",
        "infinity",
        "negative",
        "rsi",
        "price_nan",
        "volume_zero",
        "digest",
        "pickle",
    ],
)
def test_PF_02_causal_poisoned_archives_are_refused_not_repaired(
    tmp_path: Path, fault: str
) -> None:
    cached(tmp_path)
    path = next(tmp_path.glob("*.npz"))
    with np.load(path, allow_pickle=False) as stored:
        arrays: dict[str, Any] = {name: stored[name] for name in (*FIELDS, "metadata")}
    if fault == "metadata":
        values = json.loads(str(arrays["metadata"].item()))
        values["rows"] = 211
        arrays["metadata"] = np.asarray(json.dumps(values))
    elif fault == "metadata_type":
        arrays["metadata"] = np.asarray(1)
    elif fault == "metadata_size":
        arrays["metadata"] = np.asarray("x" * 70000)
    elif fault == "member":
        arrays["unexpected"] = np.asarray([1])
    elif fault == "shape":
        arrays["ema20"] = np.ones(209, dtype=np.float64)
    elif fault == "dtype":
        arrays["ema20"] = np.ones(210, dtype=np.float32)
    elif fault == "pickle":
        arrays["ema20"] = np.asarray([object()] * 210, dtype=object)
    else:
        name = (
            "rsi14"
            if fault == "rsi"
            else "typical"
            if fault == "price_nan"
            else "volume"
            if fault == "volume_zero"
            else "ema20"
        )
        arrays[name] = arrays[name].copy()
        arrays[name][0] = (
            np.inf
            if fault == "infinity"
            else -1
            if fault == "negative"
            else 101
            if fault == "rsi"
            else np.nan
            if fault == "price_nan"
            else 0
            if fault == "volume_zero"
            else 2
        )
    np.savez_compressed(path, **arrays)
    poisoned = path.read_bytes()
    with pytest.raises(DataIntegrityError):
        cached(tmp_path)
    assert path.read_bytes() == poisoned


def test_PF_02_causal_compressed_and_decoded_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached(tmp_path)
    path = next(tmp_path.glob("*.npz"))
    monkeypatch.setattr(causal_cache, "MAX_BYTES", path.stat().st_size - 1)
    with pytest.raises(DataIntegrityError):
        cached(tmp_path)
    monkeypatch.setattr(causal_cache, "MAX_BYTES", path.stat().st_size + 1)
    with pytest.raises(DataIntegrityError):
        cached(tmp_path)


def test_DQ_01_one_split_clears_memory_and_both_disk_cache_kinds(
    tmp_path: Path,
    bars: tuple[Bar, ...],
    policy: YamlConfig,
) -> None:  # noqa: F811
    disk = IndicatorCache(tmp_path)
    memo = IndicatorMemo(disk)
    first = memo.calculate("AAPL", bars, 0)
    assert first == IndicatorMemo().calculate("AAPL", bars, 0)
    causal = precompute_symbol(
        HistorySeries(symbol="AAPL", adjustment="RAW", bars=bars),
        (),
        policy,
        "a" * 64,
        cache_root=tmp_path,
    )
    assert (
        precompute_symbol(
            HistorySeries(symbol="AAPL", adjustment="RAW", bars=bars),
            (),
            policy,
            "a" * 64,
            cache_root=tmp_path,
        )
        == causal
    )
    memo.calculate("MSFT", _bars(), 0)
    assert len(tuple(tmp_path.glob("AAPL_*.npz"))) == 2
    memo.invalidate_symbol("AAPL")
    assert not tuple(tmp_path.glob("AAPL_*.npz")) and tuple(tmp_path.glob("MSFT_*.npz"))
    assert all(key[0] != "AAPL" for key in memo._entries)
    assert memo.calculate("AAPL", bars, 0) == first
