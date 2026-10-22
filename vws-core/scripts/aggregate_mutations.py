"""OPS-06: fail closed unless all current assigned fingerprints have acceptable evidence."""

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.check_mutations import approved_equivalents
from scripts.mutation_fingerprints import MAP_PATH, read_map
from scripts.mutation_inventory import (
    EXPECTED_TOTAL,
    generate_inventory,
    load_shards,
    prove_partition,
    require,
)


def aggregate(root: Path, directory: Path, head: str, matrix_result: str) -> dict[str, Any]:
    config = root / "config/mutation-shards.json"
    shards = load_shards(config)
    inventory_hash = prove_partition(shards, generate_inventory(root))
    assignment_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    approvals = approved_equivalents(root / "config/tax-equivalent-mutants.json")
    fingerprint_map_hash = hashlib.sha256((root / MAP_PATH).read_bytes()).hexdigest()
    fingerprints = {row["new_id"]: row["fingerprint"] for row in read_map(root) if row["new_id"]}
    expected_files = {s.name + ".json" for s in shards}
    files = {p.name for p in directory.glob("*.json")}
    failures: list[str] = []
    if files != expected_files:
        failures.append("missing or unexpected result files")
    all_records: dict[str, str] = {}
    all_audits: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for shard in shards:
        path = directory / (shard.name + ".json")
        counts: Counter[str] = Counter()
        error = ""
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            manifest = report["manifest"]
            require(
                manifest["shard"] == shard.name
                and manifest["parent"] == shard.parent
                and manifest["source_job"] == shard.source_job,
                "job identity",
            )
            require(
                manifest["head_sha"] == head
                and manifest["assignment_sha256"] == assignment_hash
                and manifest["inventory_sha256"] == inventory_hash,
                "stale or different inventory",
            )
            require(
                manifest["selected"] == list(shard.ids)
                and manifest["expected_count"] == len(shard.ids),
                "job ownership",
            )
            require(
                manifest["fingerprint_map_sha256"] == fingerprint_map_hash
                and manifest["fingerprints"] == {key: fingerprints[key] for key in shard.ids},
                "fingerprint identity",
            )
            records = report["records"]
            require(
                isinstance(records, dict) and set(records) == set(shard.ids),
                "incomplete result IDs",
            )
            require(
                all(isinstance(status, str) for status in records.values()), "invalid result status"
            )
            require(not set(records).intersection(all_records), "duplicate processed ID")
            all_records.update(records)
            counts.update(records.values())
            audits = report["fingerprint_records"]
            require(
                isinstance(audits, list)
                and len(audits) == len(records)
                and {row["id"] for row in audits} == set(records),
                "complete kill-reason evidence",
            )
            require(
                all(
                    row["fingerprint"] == fingerprints[row["id"]]
                    and row["native_status"] == records[row["id"]]
                    for row in audits
                ),
                "kill audit fingerprint identity",
            )
            all_audits.extend(audits)
            require(
                all(
                    row["reason"] == "assertion"
                    and any(
                        failure["kind"] == "assertion" and failure["phase"] == "call"
                        for failure in row["failures"]
                    )
                    for row in audits
                    if row["native_status"] == "killed"
                ),
                "timeout/crash kills do not count",
            )
            accepted = all(
                status in {"killed", "caught by type check"}
                or (status == "survived" and key in approvals)
                for key, status in records.items()
            )
            require(
                accepted
                and report["run_exit"] == 0
                and report["export_exit"] == 0
                and report["passed"] is True,
                "unlisted or unverified mutant results",
            )
        except Exception:
            error = "missing, surviving, malformed or unverified results"
            failures.append(shard.name)
        rows.append(
            {
                "shard": shard.name,
                "assigned": len(shard.ids),
                "records": dict(counts),
                "error": error,
            }
        )
        print(
            "Aggregate job:",
            shard.name,
            "assigned:",
            len(shard.ids),
            "results:",
            json.dumps(dict(counts), sort_keys=True),
            "FAIL" if error else "PASS",
        )
    require(len(all_records) <= EXPECTED_TOTAL, "unexpected processed IDs")
    if len(all_records) != EXPECTED_TOTAL:
        failures.append("not all current IDs processed")
    if matrix_result != "success":
        failures.append("one or more matrix jobs did not succeed")
    unlisted = sum(
        status == "survived" and key not in approvals for key, status in all_records.items()
    )
    processed = sum(status != "not checked" for status in all_records.values())
    summary = {
        "expected": EXPECTED_TOTAL,
        "fingerprint_map_sha256": fingerprint_map_hash,
        "kill_reasons": dict(Counter(row["reason"] for row in all_audits)),
        "qualified_killed": sum(
            row["native_status"] == "killed" and row["reason"] == "assertion" for row in all_audits
        ),
        "unqualified_killed": [
            row
            for row in all_audits
            if row["native_status"] == "killed" and row["reason"] != "assertion"
        ],
        "reported": len(all_records),
        "processed": processed,
        "unprocessed": EXPECTED_TOTAL - processed,
        "inventory_sha256": inventory_hash,
        "assignment_sha256": assignment_hash,
        "head_sha": head,
        "counts": dict(Counter(all_records.values())),
        "unlisted_survivors": unlisted,
        "jobs": rows,
        "failures": failures,
        "passed": not failures,
    }
    return summary


def main() -> int:
    try:
        root = Path.cwd()
        summary = aggregate(
            root,
            root / "build/mutation-results",
            os.environ["GITHUB_SHA"],
            os.environ["MUTATIONS_RESULT"],
        )
        path = root / "build/mutation-aggregate.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print("Aggregate inventory SHA256:", summary["inventory_sha256"])
        print("Aggregate commit:", summary["head_sha"])
        print("Aggregate counts:", json.dumps(summary["counts"], sort_keys=True))
        print("Qualified assertion kills:", summary["qualified_killed"])
        print("Unqualified killed tags:", len(summary["unqualified_killed"]))
        print(
            "Processed:",
            summary["processed"],
            "/",
            EXPECTED_TOTAL,
            "unlisted survivors:",
            summary["unlisted_survivors"],
        )
        require(summary["passed"] is True, "aggregate incomplete or unverified")
        print(f"Aggregate mutation gate PASS: all {EXPECTED_TOTAL} IDs processed exactly once")
        return 0
    except Exception:
        print(
            "Aggregate mutation gate FAIL: missing, surviving, no-test, timed out or unverified results."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
