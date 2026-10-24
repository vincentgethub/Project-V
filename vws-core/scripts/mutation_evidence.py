"""OPS-06: retain diagnostics without deciding or changing any mutation verdict."""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Any

from mutmut.stats import status_by_exit_code


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    errors.append("unreadable evidence file")
    return {}


def exception_category(row: dict[str, Any]) -> str:
    """Diagnostic attribution only; this never qualifies an exception as a kill."""
    if row["native_status"] == "timeout":
        return "runner:timeout"
    if row["native_status"] == "segfault":
        return "runner:worker-death"
    if row.get("native_exit_code") == 3:
        return "runner:internal"
    failures = row.get("failures", [])
    for failure in failures:
        if failure["phase"] == "collection":
            return "runner:collection/import"
        if failure["phase"] == "internal":
            return "runner:internal"
        frames = failure.get("frames", [])
        if frames and frames[-1]["origin"] == "production":
            return "production"
        if failure["phase"] in {"setup", "teardown"}:
            return "runner:fixture/setup"
        if frames and frames[-1]["origin"] == "test-harness":
            return "runner:test-harness"
        if any(frame["origin"] == "production" for frame in frames):
            return "production-via-library"
        if any(frame["origin"] == "runner" for frame in frames):
            return "runner:internal"
    return "unverified"


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    seconds = sorted(row["native_seconds"] for row in rows if row["native_seconds"] is not None)
    selected = [row["tests_selected"] for row in rows if row["tests_selected"] is not None]
    return {
        "native_duration_count": len(seconds),
        "median_seconds": median(seconds) if seconds else None,
        "p95_seconds": seconds[math.ceil(len(seconds) * 0.95) - 1] if seconds else None,
        "p95_method": "nearest rank",
        "median_tests_selected": median(selected) if selected else None,
        "max_tests_selected": max(selected) if selected else None,
        "slowest_10": sorted(
            (row for row in rows if row["native_seconds"] is not None),
            key=lambda row: (-row["native_seconds"], row["fingerprint"], row["id"]),
        )[:10],
    }


def write_exports(
    destination: Path, rows: list[dict[str, Any]], errors: list[str]
) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: (row["child"], row["fingerprint"], row["id"]))
    survivors = [row for row in rows if row["native_status"] == "survived"]
    missing = [
        row for row in rows if not row["complete_export"] or row["native_status"] == "not checked"
    ]
    summary = {
        "assigned": len(rows),
        "survivors": len(survivors),
        "missing": len(missing),
        "errors": errors,
        "metrics": metrics(rows),
    }
    for name, value in (
        ("native-status.json", {"records": rows, "summary": summary}),
        ("exception-frames.json", [row for row in rows if row["failures"]]),
        ("summary.json", summary),
    ):
        (destination / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
    fields = [
        "id",
        "fingerprint",
        "child",
        "source_job",
        "cohort",
        "native_status",
        "native_exit_code",
        "native_seconds",
        "estimated_test_seconds",
        "tests_selected",
        "tests_collected",
        "tests_run",
        "pytest_seconds",
        "complete_export",
        "exception_category",
    ]
    for name, values in (("timings.csv", rows), ("MISSING_IDS.csv", missing)):
        with (destination / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(values)
    lines = [
        "# Every observed native survivor",
        "",
        "Incomplete child observations are labeled; they do not pass the gate.",
        "",
    ]
    for row in survivors:
        lines.extend(
            [
                "## " + row["id"],
                "",
                "Fingerprint: `" + row["fingerprint"] + "`.",
                "",
                "Child: "
                + row["child"]
                + "; original parent: "
                + row["source_job"]
                + "; cohort: "
                + row["cohort"]
                + ".",
                "",
                "Complete native export: " + str(row["complete_export"]) + ".",
                "",
            ]
        )
    (destination / "ALL_SURVIVORS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def observation(
    manifest: dict[str, Any],
    key: str,
    status: str,
    complete: bool,
    native: dict[str, Any],
    audit: dict[str, Any],
    selected: int | None,
) -> dict[str, Any]:
    row = {
        "id": key,
        "fingerprint": manifest["fingerprints"][key],
        "child": manifest["shard"],
        "source_job": manifest["source_job"],
        "cohort": manifest["parent"],
        "native_status": status,
        "native_exit_code": native.get("exit_code"),
        "native_seconds": native.get("seconds"),
        "estimated_test_seconds": native.get("estimated_seconds"),
        "tests_selected": selected,
        "tests_collected": audit.get("collected"),
        "tests_run": audit.get("calls"),
        "pytest_seconds": audit.get("duration_seconds"),
        "complete_export": complete,
        "failures": audit.get("failures", []),
    }
    row["exception_category"] = exception_category(row)
    return row


def harvest(root: Path, child: str) -> dict[str, Any]:
    """Read existing results once after native execution, including after cancellation."""
    directory = root / "build/mutation-results"
    errors: list[str] = []
    report = read_json(directory / (child + ".json"), errors)
    manifest = report.get("manifest")
    if not manifest or manifest["shard"] != child:
        raise ValueError("preflight identity unavailable")
    destination = directory / (child + "-evidence")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    selected_ids = set(manifest["selected"])
    native: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "mutants").rglob("*.meta")):
        data = read_json(path, errors)
        for key, code in data.get("exit_code_by_key", {}).items():
            if key in selected_ids:
                native[key] = {
                    "exit_code": code,
                    "seconds": data.get("durations_by_key", {}).get(key),
                    "estimated_seconds": data.get("estimated_durations_by_key", {}).get(key),
                }
    stats_path = root / "mutants/mutmut-stats.json"
    stats = read_json(stats_path, errors) if stats_path.exists() else {}
    mappings = stats.get("tests_by_mangled_function_name", {})
    functions = {key.partition("__mutmut_")[0] for key in selected_ids}
    (destination / "test-selection.json").write_text(
        json.dumps(
            {
                "tests_by_function": {
                    key: sorted(mappings.get(key, [])) for key in sorted(functions)
                },
                "cohort_test_count": len(stats.get("duration_by_test", {})) if stats else None,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    runs: dict[str, dict[str, Any]] = {}
    for path in sorted((directory / (child + "-audit")).glob("*.json")):
        run = read_json(path, errors)
        if run.get("mutant") in selected_ids and not run.get("collect_only"):
            runs[run["mutant"]] = run
    records = report.get("records", {})
    rows = []
    for key in manifest["selected"]:
        raw = native.get(key, {})
        status = status_by_exit_code[raw.get("exit_code")]
        count = len(mappings.get(key.partition("__mutmut_")[0], [])) if stats else None
        rows.append(
            observation(
                manifest,
                key,
                records.get(key, status),
                key in records,
                raw,
                runs.get(key, {}),
                count,
            )
        )
    summary = write_exports(destination, rows, errors)
    summary["cohort_test_count"] = len(stats.get("duration_by_test", {})) if stats else None
    (destination / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def aggregate_exports(
    directory: Path,
    manifests: list[dict[str, Any]],
    records: dict[str, str],
    audits: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    failures_by_id = {row["id"]: row.get("failures", []) for row in audits}
    rows = []
    for manifest in manifests:
        evidence = directory / (manifest["shard"] + "-evidence")
        observed: dict[str, dict[str, Any]] = {}
        if (evidence / "manifest.json").exists():
            actual = read_json(evidence / "manifest.json", errors)
            if all(actual.get(field) == value for field, value in manifest.items()):
                data = read_json(evidence / "native-status.json", errors)
                observed = {row["id"]: row for row in data.get("records", [])}
            else:
                errors.append("different preflight identity")
        for key in manifest["selected"]:
            row = observed.get(key, {})
            if row and (
                row.get("fingerprint") != manifest["fingerprints"][key]
                or row.get("child") != manifest["shard"]
                or row.get("source_job") != manifest["source_job"]
                or row.get("cohort") != manifest["parent"]
            ):
                errors.append("different row identity")
                row = {}
            if not row:
                row = observation(manifest, key, "not checked", False, {}, {}, None)
            row = {
                **row,
                "native_status": records.get(key, row["native_status"]),
                "complete_export": key in records,
                "failures": failures_by_id.get(key, row["failures"]),
            }
            row["exception_category"] = exception_category(row)
            rows.append(row)
    return write_exports(directory / "aggregate-evidence", rows, errors)


def main() -> int:
    summary = harvest(Path.cwd(), os.environ["VWS_MUTATION_SHARD"])
    print("Diagnostic exports:", summary["assigned"], "assigned;", summary["missing"], "missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
