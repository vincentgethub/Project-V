"""OPS-06: subdivide original source owners without moving mutation identities."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.mutation_fingerprints import BASE_COMMIT, read_map, require
from scripts.mutation_inventory import EXPECTED_TOTAL

PARENTS_PATH = "config/mutation-parent-jobs.json"
COUNTS_PATH = "config/mutation-child-counts.json"
SPLIT_PATH = "config/mutation-shards.json"
ADDED_PATH = "config/mutation-added-ids.json"
# SHA-256 of ADDED_PATH: the Boss-approved NEW IDs whose source function has several
# original owners. Any other NEW ID in such a function still fails closed.
ADDED_SHA256 = "233e865e37fa831bf62a0db328c8c53b647c2a23a247dbaac12e3d7bd4b424c4"


def source_parents(root: Path) -> list[dict[str, Any]]:
    data = json.loads((root / PARENTS_PATH).read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = data["shards"]
    require(data["expected_total"] == 15457 and len(rows) == 63, "original parent inventory")
    keys = [key for row in rows for key in row["ids"]]
    require(len(keys) == len(set(keys)) == 15457, "original parent ownership")
    require(len({row["shard"] for row in rows}) == 63, "original parent names")
    return rows


def child_counts(root: Path) -> dict[str, int]:
    data = json.loads((root / COUNTS_PATH).read_text(encoding="utf-8"))
    counts: dict[str, int] = data["children"]
    require(
        data["schema_version"] == 1 and data["parent_commit_url"].rsplit("/", 1)[1] == BASE_COMMIT,
        "split baseline",
    )
    require(set(counts) == {row["shard"] for row in source_parents(root)}, "split parent names")
    require(
        all(type(value) is int and value > 0 for value in counts.values())
        and sum(counts.values()) == 135,
        "135 child counts",
    )
    return counts


def approved_additions(root: Path) -> frozenset[str]:
    raw = (root / ADDED_PATH).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ADDED_SHA256, "approved added-ID list hash")
    data = json.loads(raw)
    ids: list[str] = data["ids"]
    require(
        data["schema_version"] == 1
        and data["base_commit"] == BASE_COMMIT
        and all(isinstance(key, str) and "__mutmut_" in key for key in ids)
        and ids == sorted(set(ids)),
        "approved added-ID list format",
    )
    return frozenset(ids)


def source_function(key: str) -> str:
    return key.rsplit("__mutmut_", 1)[0]


def owner_order(owner: str) -> tuple[str, int]:
    prefix, _, number = owner.rpartition("-")
    require(number.isdigit(), "owner name")
    return prefix, int(number)


def new_owner(key: str, candidates: set[str], approved: frozenset[str]) -> str:
    """Owner of a NEW ID: its function's only original owner; with several owners the ID
    must be on the approved list and goes to the lowest-numbered owner. No owner fails closed."""
    require(bool(candidates), "NEW mutation source-function owner")
    if len(candidates) == 1:
        return next(iter(candidates))
    require(key in approved, "NEW mutation source-function owner")
    return min(candidates, key=owner_order)


def owned_mutants(root: Path) -> dict[str, list[tuple[str, int, str]]]:
    parents = source_parents(root)
    owners = {key: parent["shard"] for parent in parents for key in parent["ids"]}
    functions: dict[str, set[str]] = defaultdict(set)
    for key, owner in owners.items():
        functions[source_function(key)].add(owner)
    mapping = read_map(root)
    require(
        {row["old_id"] for row in mapping if row["old_id"]} == set(owners), "map original owners"
    )
    approved = approved_additions(root)
    shared: set[str] = set()
    result: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for appearance, row in enumerate(mapping):
        if not row["new_id"]:
            continue
        if row["old_id"]:
            owner = owners[row["old_id"]]
        else:
            candidates = functions[source_function(row["new_id"])]
            owner = new_owner(row["new_id"], candidates, approved)
            if len(candidates) > 1:
                shared.add(row["new_id"])
        result[owner].append((row["fingerprint"], appearance, row["new_id"]))
    require(shared == approved, "approved added-ID list differs from shared-owner NEW IDs")
    return dict(result)


def build_split(root: Path) -> dict[str, Any]:
    parents = source_parents(root)
    counts = child_counts(root)
    owned = owned_mutants(root)
    approved = approved_additions(root)
    children: list[dict[str, Any]] = []
    for parent in parents:
        owner = parent["shard"]
        values = sorted(row for row in owned[owner] if row[2] not in approved)
        size = counts[owner]
        require(len(values) >= size, "nonempty child jobs")
        groups = [[row[2] for row in values[index::size]] for index in range(size)]
        # An approved addition never re-stripes existing IDs: it joins the lowest-numbered
        # child that already holds an ID of its source function.
        for key in sorted(row[2] for row in owned[owner] if row[2] in approved):
            holders = [
                index
                for index, group in enumerate(groups)
                if any(source_function(other) == source_function(key) for other in group)
            ]
            require(bool(holders), "NEW mutation source-function owner")
            groups[holders[0]].append(key)
        for index in range(size):
            ids = sorted(groups[index])
            children.append(
                {
                    "shard": owner + "-" + str(index + 1),
                    "parent": parent["parent"],
                    "source_job": owner,
                    "count": len(ids),
                    "paths": parent["paths"],
                    "additional_tests": parent["additional_tests"],
                    "ids": ids,
                }
            )
    require(len(children) == 135 and all(row["ids"] for row in children), "135 nonempty jobs")
    keys = [key for row in children for key in row["ids"]]
    require(len(keys) == len(set(keys)) == EXPECTED_TOTAL, "current exactly-once inventory")
    return {
        "schema_version": 2,
        "generator_version": "3.8.0",
        "expected_total": EXPECTED_TOTAL,
        "shards": children,
    }


def prove_child_ownership(root: Path, data: dict[str, Any]) -> dict[str, Any]:
    expected = build_split(root)
    require(data == expected, "child partition differs from deterministic fingerprint split")
    owned = owned_mutants(root)
    mapping = read_map(root)
    fingerprint_by_id = {row["new_id"]: row["fingerprint"] for row in mapping if row["new_id"]}
    rows = []
    for parent in source_parents(root):
        owner = parent["shard"]
        children = [row for row in data["shards"] if row["source_job"] == owner]
        actual = [key for child in children for key in child["ids"]]
        required = [row[2] for row in owned[owner]]
        require(
            len(actual) == len(set(actual)) and set(actual) == set(required), "parent child union"
        )
        require(
            Counter(fingerprint_by_id[key] for key in actual)
            == Counter(row[0] for row in owned[owner]),
            "parent fingerprint multiplicity",
        )
        rows.append(
            {
                "parent": owner,
                "cohort": parent["parent"],
                "children": len(children),
                "assigned": len(actual),
            }
        )
    return {
        "parents": rows,
        "jobs": 135,
        "assigned": EXPECTED_TOTAL,
        "matched_owner_moves": 0,
        "missing": 0,
        "duplicates": 0,
    }


def encoded_split(root: Path) -> bytes:
    return (json.dumps(build_split(root), ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path.cwd()
    try:
        content = encoded_split(root)
        if args.check:
            require((root / SPLIT_PATH).read_bytes() == content, "committed child split differs")
        else:
            (root / SPLIT_PATH).write_bytes(content)
        proof = prove_child_ownership(root, json.loads(content))
        print(
            f"Child partition proof PASS: 63 parents; 135 nonempty children; {EXPECTED_TOTAL} IDs exactly once; matched owner moves:",
            proof["matched_owner_moves"],
        )
        return 0
    except Exception:
        print(
            "Child partition proof FAIL: ownership, count or deterministic regeneration mismatch."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
