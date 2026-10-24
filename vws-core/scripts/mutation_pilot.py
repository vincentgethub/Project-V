"""OPS-06: dispatch-only measurements, deliberately unusable as mutation gate evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.mutation_evidence import harvest
from scripts.mutation_fingerprints import MAP_PATH, read_map
from scripts.mutation_inventory import BASE_SELECTION, load_shards, require
from scripts.run_mutation_shard import select_configuration

SEED = 39856462454
SAMPLE_SIZE = 100
BATCH_SIZE = 40
PURPOSE = "diagnostic-only; never gate evidence"
CONFIG = "config/mutation-pilot.json"
POOL = "config/mutation-pilot-exception-pool.csv"
OUTPUT = "build/mutation-pilot"


def encoded(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def build_plan(root: Path) -> dict[str, Any]:
    config = json.loads((root / CONFIG).read_text(encoding="utf-8"))
    require(config["baseline_run"] == 39856462454, "pilot baseline")
    require(len(config["parents"]) == len(set(config["parents"])) == 18, "pilot parents")
    require(config["seed"] == SEED and config["sample_size"] == SAMPLE_SIZE, "pilot sample")
    pool_bytes = (root / POOL).read_text(encoding="utf-8").encode()
    require(
        "sha256:" + hashlib.sha256(pool_bytes).hexdigest() == config["pool_sha256"],
        "pilot pool changed",
    )
    with (root / POOL).open(encoding="utf-8", newline="") as handle:
        pool = list(csv.DictReader(handle))
    require(len(pool) == 5162 and len({row["id"] for row in pool}) == 5162, "pilot pool size")
    shards = load_shards(root / "config/mutation-shards.json")
    owners = {key: shard for shard in shards for key in shard.ids}
    fingerprints = {row["new_id"]: row["fingerprint"] for row in read_map(root) if row["new_id"]}
    require(
        all(fingerprints.get(row["id"]) == row["fingerprint"] for row in pool),
        "pilot pool fingerprint changed",
    )
    # Duplicate fingerprints retain deterministic native-ID occurrence selection.
    by_fingerprint: dict[str, list[str]] = {}
    for row in sorted(
        pool,
        key=lambda row: (row["id"].partition("__mutmut_")[0], int(row["id"].rpartition("_")[2])),
    ):
        by_fingerprint.setdefault(row["fingerprint"], []).append(row["id"])
    sampled = sorted(
        sorted(
            by_fingerprint,
            key=lambda fp: (hashlib.sha256((str(SEED) + ":" + fp).encode()).hexdigest(), fp),
        )[:SAMPLE_SIZE]
    )
    sample: list[dict[str, Any]] = [
        {"fingerprint": fp, "id": by_fingerprint[fp][0], "occurrences": by_fingerprint[fp]}
        for fp in sampled
    ]
    parents = set(config["parents"])
    require(parents <= {shard.source_job for shard in shards}, "unknown pilot parent")
    selected = {key for key, owner in owners.items() if owner.source_job in parents}
    parent_count = len(selected)
    selected.update(row["id"] for row in sample)
    batches: list[dict[str, Any]] = []
    for parent in sorted({owners[key].source_job for key in selected}):
        keys = sorted(
            (key for key in selected if owners[key].source_job == parent),
            key=lambda key: (fingerprints[key], key),
        )
        owner = owners[keys[0]]
        for offset in range(0, len(keys), BATCH_SIZE):
            assigned = keys[offset : offset + BATCH_SIZE]
            batches.append(
                {
                    "shard": "pilot-" + parent + "-" + str(offset // BATCH_SIZE + 1),
                    "parent": owner.parent,
                    "source_job": parent,
                    "paths": list(owner.paths),
                    "base_selection": list(BASE_SELECTION),
                    "additional_tests": list(owner.additional_tests),
                    "patterns": assigned,
                    "selected": assigned,
                    "expected_count": len(assigned),
                    "fingerprints": {key: fingerprints[key] for key in assigned},
                    "generated": sorted(
                        key for key, row in owners.items() if row.paths == owner.paths
                    ),
                    "sample_ids": sorted(
                        key for key in assigned if key in {r["id"] for r in sample}
                    ),
                    "purpose": PURPOSE,
                }
            )
    assigned = [key for batch in batches for key in batch["selected"]]
    require(len(assigned) == len(set(assigned)) and set(assigned) == selected, "pilot union")
    require(len(batches) + 2 < 256, "pilot matrix limit")
    return {
        "purpose": PURPOSE,
        "baseline_run": config["baseline_run"],
        "seed": SEED,
        "sample_algorithm": "first 100 fingerprints ranked by sha256(str(seed) + ':' + fingerprint), then fingerprint",
        "sample": sample,
        "distinct_exception_fingerprints": len(by_fingerprint),
        "parent_mutants": parent_count,
        "sample_outside_parents": len(selected) - parent_count,
        "assigned": len(selected),
        "parents": sorted(parents),
        "batches": batches,
        "fingerprint_map_sha256": hashlib.sha256((root / MAP_PATH).read_bytes()).hexdigest(),
        "assignment_sha256": hashlib.sha256(
            (root / "config/mutation-shards.json").read_bytes()
        ).hexdigest(),
    }


def prepare(root: Path, name: str) -> None:
    plan = build_plan(root)
    batches = {row["shard"]: row for row in plan["batches"]}
    require(name in batches, "unknown pilot batch")
    destination = root / OUTPUT / name
    require(not destination.exists() and not (root / "mutants").exists(), "fresh pilot required")
    destination.mkdir(parents=True)
    manifest = {
        **batches[name],
        "head_sha": os.environ.get("GITHUB_SHA", "LOCAL"),
        "plan_sha256": hashlib.sha256(encoded(plan)).hexdigest(),
    }
    (destination / (name + ".json")).write_bytes(
        encoded({"manifest": manifest, "purpose": PURPOSE})
    )
    (destination / "native-ids.txt").write_text(
        "\n".join(manifest["selected"]) + "\n", encoding="utf-8"
    )
    project = root / "pyproject.toml"
    original = project.read_bytes()
    (destination / "original-pyproject.toml").write_bytes(original)
    project.write_text(select_configuration(original.decode(), manifest), encoding="utf-8")
    print("Diagnostic pilot only:", name, manifest["expected_count"], "mutants")


def finish(root: Path, name: str) -> dict[str, Any]:
    directory = root / OUTPUT / name
    project = directory / "original-pyproject.toml"
    if project.exists():
        (root / "pyproject.toml").write_bytes(project.read_bytes())
    report_path = directory / (name + ".json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    require(report["purpose"] == PURPOSE and report["manifest"]["shard"] == name, "pilot identity")
    records = {}
    result = directory / "native-results.txt"
    if result.exists():
        selected = set(report["manifest"]["selected"])
        for line in result.read_text(encoding="utf-8").splitlines():
            key, separator, status = line.strip().partition(": ")
            if separator and key in selected:
                require(key not in records, "duplicate pilot export")
                records[key] = status
    report["records"] = records
    # No passed, run_exit, export_exit or fingerprint_records: not a gate report.
    report_path.write_bytes(encoded(report))
    summary = harvest(root, name, directory=directory)
    print(
        "Diagnostic observations only:",
        json.dumps({k: summary[k] for k in ("assigned", "missing", "survivors")}),
    )
    return summary


def summarize(root: Path) -> dict[str, Any]:
    from scripts.mutation_evidence import metrics, observation, write_exports

    plan = build_plan(root)
    directory = root / OUTPUT
    rows: list[dict[str, Any]] = []
    missing_batches = []
    for batch in plan["batches"]:
        path = directory / batch["shard"] / (batch["shard"] + "-evidence") / "native-status.json"
        if not path.exists():
            missing_batches.append(batch["shard"])
            rows.extend(
                observation(batch, key, "not checked", False, {}, {}, None)
                for key in batch["selected"]
            )
            continue
        manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        require(
            manifest
            == {
                **batch,
                "head_sha": os.environ.get("GITHUB_SHA", "LOCAL"),
                "plan_sha256": hashlib.sha256(encoded(plan)).hexdigest(),
            },
            "stale or different pilot identity",
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        require(
            {row["id"] for row in data["records"]} == set(batch["selected"]),
            "pilot export ownership",
        )
        require(
            all(
                row["fingerprint"] == batch["fingerprints"][row["id"]]
                and row["child"] == batch["shard"]
                and row["source_job"] == batch["source_job"]
                and row["cohort"] == batch["parent"]
                for row in data["records"]
            ),
            "pilot export fingerprints",
        )
        rows.extend(data["records"])
    summary = write_exports(directory / "summary", rows, [])
    sampled = {row["id"] for row in plan["sample"]}
    exceptions = [row for row in rows if row["id"] in sampled]
    result = {
        "purpose": PURPOSE,
        "missing_batches": missing_batches,
        "expected": plan["assigned"],
        "observed": sum(row["native_status"] != "not checked" for row in rows),
        "per_parent": {
            parent: metrics([row for row in rows if row["source_job"] == parent])
            for parent in plan["parents"]
        },
        "sample": exceptions,
        "sample_categories": dict(Counter(row["exception_category"] for row in exceptions)),
        "summary": summary,
    }
    (directory / "summary/pilot-summary.json").write_bytes(encoded(result))
    print(
        "Diagnostic pilot coverage:",
        len(rows),
        "/",
        plan["assigned"],
        "; missing batches:",
        len(missing_batches),
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "prepare", "finish", "summarize"))
    parser.add_argument("--batch")
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == "plan":
        plan = build_plan(root)
        directory = root / OUTPUT
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "plan.json").write_bytes(encoded(plan))
        matrix = {"batch": [row["shard"] for row in plan["batches"]]}
        if "GITHUB_OUTPUT" in os.environ:
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as handle:
                handle.write("matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n")
        print(
            "Diagnostic plan:",
            plan["assigned"],
            "mutants;",
            len(plan["batches"]),
            "batches; seed",
            SEED,
        )
    elif args.action == "summarize":
        summarize(root)
    else:
        require(bool(args.batch), "pilot batch required")
        if args.action == "prepare":
            prepare(root, args.batch)
        else:
            finish(root, args.batch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
