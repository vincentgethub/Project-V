"""OPS-06: run native mutmut and preserve complete, individually identified evidence."""

import json
import os
import re
import subprocess  # nosec B404
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.check_mutations import require_complete_results
from scripts.mutation_audit import audit_results
from scripts.mutation_inventory import build_manifest, require


def select_configuration(original: str, manifest: dict[str, Any]) -> str:
    before = tomllib.loads(original)
    patched = original
    updates = {
        "source_paths": manifest["paths"],
        "pytest_add_cli_args_test_selection": manifest["base_selection"]
        + manifest["additional_tests"],
    }
    for field, value in updates.items():
        patched, changes = re.subn(
            r"(?m)^" + field + r" = .*?$", field + " = " + json.dumps(value), patched
        )
        require(changes == 1, "could not select approved job configuration")
        before["tool"]["mutmut"][field] = value
    require(tomllib.loads(patched) == before, "unapproved configuration change")
    return patched


def parse_results(text: str, generated: list[str]) -> dict[str, str]:
    records: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, status = line.strip().partition(": ")
        require(
            bool(separator) and bool(status) and key not in records, "malformed or duplicate result"
        )
        records[key] = status
    require(set(records) == set(generated), "missing or unexpected generated results")
    return records


def main() -> int:
    report: dict[str, Any] = {"error": "native run did not produce verified evidence"}
    destination: Path | None = None
    try:
        root = Path.cwd()
        name = os.environ["VWS_MUTATION_SHARD"]
        manifest = json.loads(
            Path(os.environ["RUNNER_TEMP"], "vws-mutation-shard.json").read_text(encoding="utf-8")
        )
        require(manifest == build_manifest(root, name), "preflight manifest changed")
        destination = root / "build/mutation-results" / (name + ".json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        report = {"manifest": manifest, "records": {}, "run_exit": None, "export_exit": None}
        project = root / "pyproject.toml"
        original = project.read_text(encoding="utf-8")
        audit_directory = destination.with_name(name + "-audit")
        require(
            not audit_directory.exists() and not (root / "mutants").exists(),
            "fresh mutation run required",
        )
        audit_directory.mkdir()
        audit_environment = {**os.environ, "VWS_MUTATION_AUDIT_DIR": str(audit_directory.resolve())}
        try:
            project.write_text(select_configuration(original, manifest), encoding="utf-8")
            # Native command; no diagnostic profiler, worker or timeout overrides.
            result = subprocess.run(
                [sys.executable, "-m", "mutmut", "run", *manifest["patterns"]],
                check=False,
                env=audit_environment,
            )  # nosec B603
            report["run_exit"] = result.returncode
            exported = subprocess.run(
                [sys.executable, "-m", "mutmut", "results", "--all", "true"],
                check=False,
                capture_output=True,
                text=True,
            )  # nosec B603
            report["export_exit"] = exported.returncode
        finally:
            project.write_text(original, encoding="utf-8")
        require(exported.returncode == 0, "native results export failed")
        records = parse_results(exported.stdout, manifest["generated"])
        selected = {key: records[key] for key in manifest["selected"]}
        report["records"] = selected
        audit, clean_runs = audit_results(audit_directory, selected, manifest["fingerprints"])
        report["fingerprint_records"] = audit
        report["kill_reasons"] = dict(Counter(row["reason"] for row in audit))
        report["clean_runs"] = clean_runs
        print("Native kill reasons:", name, json.dumps(report["kill_reasons"], sort_keys=True))
        print(
            "Native panic clean runs:",
            name,
            json.dumps(
                [
                    {
                        "mutant": row["mutant"],
                        "exit_status": row["exit_status"],
                        "panic_cases": row["panic_cases"],
                    }
                    for row in clean_runs
                ],
                ensure_ascii=True,
            ),
        )
        print(
            "Native job results:",
            name,
            json.dumps(dict(Counter(selected.values())), sort_keys=True),
        )
        print(
            "Native survivor IDs:",
            json.dumps(
                [key for key, status in selected.items() if status == "survived"], ensure_ascii=True
            ),
        )
        require(result.returncode == 0, "native mutation command failed")
        evidence = (
            "\n".join(
                "m_" + key.encode("utf-8").hex() + ": " + status for key, status in selected.items()
            )
            + "\n"
        )
        Path(os.environ["RUNNER_TEMP"], "vws-mutants.txt").write_text(evidence, encoding="utf-8")
        count = require_complete_results(evidence)
        require(count == manifest["expected_count"], "incomplete assigned results")
        require(
            all(row["reason"] == "assertion" for row in audit if row["native_status"] == "killed"),
            "crash or unaudited kills do not count",
        )
        report["passed"] = True
        print("Shard complete 100% gate:", name, count)
        return 0
    except Exception:
        report["passed"] = False
        print("Mutation gate FAIL: missing, surviving, malformed or unverified results.")
        return 1
    finally:
        if destination is not None:
            destination.write_text(
                json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    raise SystemExit(main())
