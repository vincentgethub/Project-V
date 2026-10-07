"""PF-02/DQ-01 real npz roundtrips, hostile members, versions and splits."""

import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import numpy as np
import pytest

from backend.agents.indicators import IndicatorSeries
from backend.core.errors import DataIntegrityError
from backend.indicators.cache import IndicatorCache
from backend.tests.test_indicator_cache import _bars


def test_PF_02_real_cache_roundtrip_and_versioned_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.indicators.cache as implementation

    cache = IndicatorCache(tmp_path)
    bars = _bars()
    result = cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")
    assert cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP") == result
    assert isinstance(result, IndicatorSeries)
    assert "AAPL_SPLIT_" in next(tmp_path.glob("*.npz")).name
    cache.calculate("AAPL", "ALL", bars, 0, feed="SIP")
    cache.calculate("AAPL", "SPLIT", bars, 1, feed="SIP")
    monkeypatch.setattr(implementation, "CODE_VERSION", "pf1-v2")
    assert cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP") == result
    assert len(tuple(tmp_path.glob("*.npz"))) == 4


def test_DQ_01_split_invalidates_all_adjustments_without_other_symbols(tmp_path: Path) -> None:
    cache = IndicatorCache(tmp_path)
    bars = _bars()
    cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")
    cache.calculate("AAPL", "ALL", bars, 0, feed="SIP")
    cache.calculate("MSFT", "SPLIT", bars, 0, feed="SIP")
    assert cache.invalidate_symbol("AAPL") == 2
    assert cache.invalidate_symbol("AAPL") == 0
    assert len(tuple(tmp_path.glob("MSFT_*.npz"))) == 1
    changed = (bars[0].model_copy(update={"volume": 9999}), *bars[1:])
    assert cache.calculate("AAPL", "SPLIT", changed, 0, feed="SIP") is not None


@pytest.mark.parametrize("case", ["feed", "adjustment", "anchor", "symbol", "source"])
def test_PF_02_unknown_or_changed_inputs_refused(case: str, tmp_path: Path) -> None:
    cache = IndicatorCache(tmp_path)
    bars = _bars()
    cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")
    kwargs: dict[str, Any] = {
        "symbol": "AAPL",
        "adjustment": "SPLIT",
        "bars": bars,
        "anchor_index": 0,
        "feed": "SIP",
    }
    if case == "source":
        kwargs["bars"] = (bars[0].model_copy(update={"volume": 9999}), *bars[1:])
    else:
        key = {"anchor": "anchor_index"}.get(case, case)
        kwargs[key] = {"feed": "UNKNOWN", "adjustment": "BAD", "anchor": -1, "symbol": "aapl"}[case]
    with pytest.raises(DataIntegrityError):
        cache.calculate(**kwargs)


@pytest.mark.parametrize(
    "case",
    [
        "members",
        "metadata_shape",
        "metadata_type",
        "identity",
        "array_type",
        "array_shape",
        "nonfinite",
        "digest",
        "pickle",
    ],
)
def test_PF_02_corrupt_npz_cannot_be_a_success(case: str, tmp_path: Path) -> None:
    cache = IndicatorCache(tmp_path)
    bars = _bars()
    cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")
    path = next(tmp_path.glob("*.npz"))
    with np.load(path, allow_pickle=False) as stored:
        data = {name: stored[name] for name in stored.files}
    if case == "members":
        data["unknown"] = np.asarray([1])
    elif case == "metadata_shape":
        data["metadata"] = np.asarray([str(data["metadata"].item())])
    elif case == "metadata_type":
        data["metadata"] = np.asarray(1)
    elif case == "identity":
        metadata = json.loads(str(data["metadata"].item()))
        metadata["code_version"] = "other"
        data["metadata"] = np.asarray(json.dumps(metadata))
    elif case == "array_type":
        data["ema20"] = data["ema20"].astype("float32")
    elif case == "array_shape":
        data["ema20"] = data["ema20"][:-1]
    elif case == "nonfinite":
        data["ema20"][-1] = np.inf
    elif case == "digest":
        data["ema20"][-1] += 1
    else:
        data["metadata"] = np.asarray({"synthetic": "object"}, dtype=object)
    np.savez_compressed(path, allow_pickle=case == "pickle", **data)
    with pytest.raises(DataIntegrityError):
        cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")


def test_PF_02_compressed_and_decoded_size_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.indicators.cache as implementation

    cache = IndicatorCache(tmp_path)
    bars = _bars()
    cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")
    path = next(tmp_path.glob("*.npz"))
    with ZipFile(path) as stored:
        expanded = sum(member.file_size for member in stored.infolist())
    assert expanded > path.stat().st_size
    monkeypatch.setattr(implementation, "_MAX_BYTES", 1)
    with pytest.raises(DataIntegrityError, match="file exceeds"):
        cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")
    monkeypatch.setattr(implementation, "_MAX_BYTES", path.stat().st_size + 1)
    with pytest.raises(DataIntegrityError, match="decoded size"):
        cache.calculate("AAPL", "SPLIT", bars, 0, feed="SIP")


def test_DQ_cache_invalidation_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = IndicatorCache(tmp_path)
    directory = tmp_path / "AAPL_bad.npz"
    directory.mkdir()
    with pytest.raises(DataIntegrityError, match="direct file"):
        cache.invalidate_symbol("AAPL")
    with pytest.raises(DataIntegrityError, match="invalidation failed"):
        cache.invalidate_symbol("aapl")
    monkeypatch.setattr(Path, "glob", lambda *args: [directory] * 100001)
    with pytest.raises(DataIntegrityError, match="exceeds its bound"):
        cache.invalidate_symbol("AAPL")
