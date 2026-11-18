"""OPS-06: owner rule for NEW mutation IDs in functions with several original owners."""

import importlib
import json
import shutil
from pathlib import Path

import pytest

from backend.core.errors import DataIntegrityError

ROOT = Path(__file__).resolve().parents[2]
children = importlib.import_module("scripts.mutation_children")


def test_OPS_06_new_id_with_one_owner_joins_it() -> None:
    assert children.new_owner("m.f__mutmut_9", {"risk-sizing-3"}, frozenset()) == "risk-sizing-3"


def test_OPS_06_listed_shared_owner_new_id_joins_the_lowest_numbered_owner() -> None:
    owners = {"executor-a-10", "executor-a-2", "executor-a-9"}
    listed = frozenset({"m.f__mutmut_9"})
    assert children.new_owner("m.f__mutmut_9", owners, listed) == "executor-a-2"


def test_OPS_06_unlisted_shared_owner_new_id_fails_closed() -> None:
    with pytest.raises(DataIntegrityError, match="NEW mutation source-function owner"):
        children.new_owner("m.f__mutmut_9", {"executor-a-1", "executor-a-2"}, frozenset())


def test_OPS_06_ownerless_new_id_fails_closed_even_when_listed() -> None:
    with pytest.raises(DataIntegrityError, match="NEW mutation source-function owner"):
        children.new_owner("m.f__mutmut_9", set(), frozenset({"m.f__mutmut_9"}))


@pytest.mark.parametrize("tamper", ["extra", "missing", "reordered"])
def test_OPS_06_added_id_list_is_hash_pinned(tmp_path: Path, tamper: str) -> None:
    source = json.loads((ROOT / children.ADDED_PATH).read_text(encoding="utf-8"))
    ids = list(source["ids"])
    changed = {
        "extra": sorted([*ids, ids[0][:-1] + "999"]),
        "missing": ids[1:],
        "reordered": ids[::-1],
    }[tamper]
    (tmp_path / "config").mkdir()
    (tmp_path / children.ADDED_PATH).write_text(
        json.dumps({**source, "ids": changed}, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DataIntegrityError, match="approved added-ID list hash"):
        children.approved_additions(tmp_path)


def test_OPS_06_added_ids_join_the_lowest_owning_child_and_move_no_existing_id() -> None:
    approved = children.approved_additions(ROOT)
    owned = children.owned_mutants(ROOT)
    counts = children.child_counts(ROOT)
    split = children.build_split(ROOT)

    def order(shard: str) -> list[object]:
        return [int(part) if part.isdigit() else part for part in shard.split("-")]

    holders = {key: row["shard"] for row in split["shards"] for key in row["ids"]}
    for key in approved:
        function = children.source_function(key)
        owning = [
            row["shard"]
            for row in split["shards"]
            if any(
                children.source_function(other) == function and other not in approved
                for other in row["ids"]
            )
        ]
        assert holders[key] == min(owning, key=order)
    # Existing IDs keep the unmodified stripe: the additions never shift them.
    for owner, rows in owned.items():
        values = sorted(row for row in rows if row[2] not in approved)
        size = counts[owner]
        for index in range(size):
            child = next(row for row in split["shards"] if row["shard"] == f"{owner}-{index + 1}")
            existing = sorted(key for key in child["ids"] if key not in approved)
            assert existing == sorted(row[2] for row in values[index::size])
    keys = [key for row in split["shards"] for key in row["ids"]]
    assert len(keys) == len(set(keys)) == children.EXPECTED_TOTAL


def test_OPS_06_split_without_the_added_list_fails_closed(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "build" / "pass7").mkdir(parents=True)
    shutil.copy(ROOT / "build/pass7/inventory-fingerprint-map.csv", tmp_path / "build/pass7")
    (tmp_path / children.ADDED_PATH).unlink()
    with pytest.raises(FileNotFoundError):
        children.build_split(tmp_path)
