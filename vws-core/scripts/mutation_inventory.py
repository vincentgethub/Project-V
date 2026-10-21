"""OPS-06: prove the approved 63-way partition against freshly generated IDs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

from backend.core.errors import DataIntegrityError

EXPECTED_TOTAL = 15457
PARENT_JOBS = {
    "executor-a": 8,
    "executor-b": 9,
    "risk-controls": 27,
    "risk-sizing": 7,
    "fundamentals-callbacks": 11,
    "tax": 1,
}
ADDITIONS = {
    "risk-controls": ("backend/tests/test_risk_boundary.py",),
    "risk-sizing": (
        "backend/tests/test_v_risk.py",
        "backend/tests/test_v_risk_boundaries.py",
        "backend/tests/test_portfolio_marks.py",
        "backend/tests/test_risk_boundary.py",
        "backend/tests/test_v_connections.py",
    ),
}
BASE_SELECTION = (
    "backend/tests/test_risk_cro.py",
    "backend/tests/test_compliance.py",
    "backend/tests/test_wash_sales.py",
    "backend/tests/test_compliance_boundary.py",
    "backend/tests/test_stage_c_adversarial.py",
    "backend/tests/test_swarm_and_callbacks.py",
    "backend/tests/test_fundamentals.py",
    "backend/tests/test_tax_accounting.py",
    "backend/tests/test_tax_reports.py",
    "backend/tests/test_tax_guards.py",
    "backend/tests/test_auto_execution.py",
    "backend/tests/test_auto_exits.py",
    "backend/tests/test_auto_admission.py",
    "backend/tests/test_auto_contracts.py",
    "backend/tests/test_auto_safety.py",
    "backend/tests/test_execution_policy.py",
    "backend/tests/test_live_unlock.py",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DataIntegrityError("OPS-06: " + message)


@dataclass(frozen=True)
class Shard:
    name: str
    parent: str
    paths: tuple[str, ...]
    additional_tests: tuple[str, ...]
    ids: tuple[str, ...]


def digest_ids(ids: set[str] | tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode("utf-8")).hexdigest()


def load_shards(path: Path) -> tuple[Shard, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    require(
        data["schema_version"] == 1 and data["generator_version"] == "3.8.0", "partition format"
    )
    require(
        type(data["expected_total"]) is int and data["expected_total"] == EXPECTED_TOTAL,
        "inventory total",
    )
    expected_names = {
        "tax" if parent == "tax" else f"{parent}-{n}"
        for parent, count in PARENT_JOBS.items()
        for n in range(1, count + 1)
    }
    shards: list[Shard] = []
    seen: set[str] = set()
    for row in data["shards"]:
        require(row["parent"] in PARENT_JOBS, "unknown parent")
        require(
            isinstance(row["shard"], str)
            and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", row["shard"]) is not None,
            "invalid shard name",
        )
        require(
            row["shard"] == "tax"
            if row["parent"] == "tax"
            else row["shard"].startswith(row["parent"] + "-"),
            "job name differs from its parent",
        )
        for field in ("paths", "additional_tests", "ids"):
            require(
                isinstance(row[field], list) and all(isinstance(v, str) and v for v in row[field]),
                "invalid partition field",
            )
            require(len(row[field]) == len(set(row[field])), "duplicate partition field")
        require(bool(row["paths"]) and bool(row["ids"]), "empty shard")
        require(type(row["count"]) is int and row["count"] == len(row["ids"]), "assigned count")
        require(
            tuple(row["additional_tests"]) == ADDITIONS.get(row["parent"], ()),
            "unapproved selector addition",
        )
        require(not seen.intersection(row["ids"]), "overlapping mutant ownership")
        seen.update(row["ids"])
        shards.append(
            Shard(
                row["shard"],
                row["parent"],
                tuple(row["paths"]),
                tuple(row["additional_tests"]),
                tuple(row["ids"]),
            )
        )
    names = [s.name for s in shards]
    require(
        len(names) == len(set(names)) == 63 and set(names) == expected_names,
        "expected 63 named jobs",
    )
    require(len(seen) == EXPECTED_TOTAL, "missing or extra assigned IDs")
    return tuple(shards)


def generate_inventory(root: Path) -> dict[str, set[str]]:
    from mutmut.mutation.file_mutation import mutate_file_contents
    from mutmut.utils.format_utils import get_mutant_name

    require(version("mutmut") == "3.8.0", "unexpected generator version")
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mutmut"]
    require(
        tuple(config["pytest_add_cli_args_test_selection"]) == BASE_SELECTION,
        "base selection changed",
    )
    files: set[str] = set()
    for source in config["source_paths"]:
        path = root / source
        require(path.exists(), "configured source missing")
        files.update(
            p.relative_to(root).as_posix()
            for p in (path.rglob("*.py") if path.is_dir() else (path,))
        )
    require(len(files) == 18, "configured file count changed")
    result: dict[str, set[str]] = {}
    for filename in sorted(files):
        mutated = mutate_file_contents(filename, (root / filename).read_text(encoding="utf-8"))
        keys = [get_mutant_name(Path(filename), name) for name in mutated.mutant_names]
        require(len(keys) == len(set(keys)), "duplicate generated ID")
        result[filename] = set(keys)
    union = set().union(*result.values())
    require(
        len(union) == sum(map(len, result.values())) == EXPECTED_TOTAL,
        "fresh inventory differs from 15457",
    )
    return result


def prove_partition(shards: tuple[Shard, ...], generated: dict[str, set[str]]) -> str:
    assigned_files = {path for shard in shards for path in shard.paths}
    require(assigned_files == set(generated), "unassigned or unexpected source file")
    seen: set[str] = set()
    for shard in shards:
        allowed = set().union(*(generated[path] for path in shard.paths))
        require(set(shard.ids) <= allowed, "ID outside its job source files")
        require(not seen.intersection(shard.ids), "duplicate ID ownership")
        seen.update(shard.ids)
    actual = set().union(*generated.values())
    require(
        seen == actual and len(seen) == EXPECTED_TOTAL, "unassigned or nonexistent generated ID"
    )
    return digest_ids(actual)


def build_manifest(root: Path, name: str) -> dict[str, Any]:
    path = root / "config/mutation-shards.json"
    shards = load_shards(path)
    generated = generate_inventory(root)
    inventory_hash = prove_partition(shards, generated)
    require(name in {s.name for s in shards}, "unknown current job")
    row = next(s for s in shards if s.name == name)
    generated_for_job = set().union(*(generated[p] for p in row.paths))
    patterns = [] if row.parent == "tax" else list(row.ids)
    require(
        all(not any(char in pattern for char in "*?[") for pattern in patterns),
        "nonliteral CLI selection",
    )
    matched = generated_for_job.intersection(patterns) if patterns else generated_for_job
    require(matched == set(row.ids), "native CLI selection differs from assigned IDs")
    return {
        "shard": row.name,
        "parent": row.parent,
        "paths": list(row.paths),
        "patterns": patterns,
        "expected_count": len(row.ids),
        "selected": list(row.ids),
        "generated": sorted(generated_for_job),
        "base_selection": list(BASE_SELECTION),
        "additional_tests": list(row.additional_tests),
        "inventory_sha256": inventory_hash,
        "assignment_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "head_sha": os.environ.get("GITHUB_SHA", "LOCAL"),
    }


def main() -> int:
    try:
        root = Path.cwd()
        manifest = build_manifest(root, os.environ["VWS_MUTATION_SHARD"])
        destination = Path(os.environ["RUNNER_TEMP"], "vws-mutation-shard.json")
        destination.write_text(json.dumps(manifest, ensure_ascii=True), encoding="utf-8")
        print(
            "Partition proof PASS: 18 files; 63 jobs; 15457 freshly generated unique IDs; every ID owned exactly once"
        )
        print("Inventory SHA256:", manifest["inventory_sha256"])
        print("Shard:", manifest["shard"], "assigned:", manifest["expected_count"])
        return 0
    except Exception:
        print("Mutation shard coverage FAIL: incomplete, overlapping or unapproved partition.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
