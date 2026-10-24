"""OPS-06: partition ownership, individual approvals and aggregate failures."""

import hashlib
import json
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.core.errors import DataIntegrityError
from scripts import aggregate_mutations as gate
from scripts.check_mutations import (
    OWNER_APPROVED_IDS,
    approved_equivalents,
    require_complete_results,
)
from scripts.mutation_fingerprints import MAP_PATH, read_map
from scripts.mutation_inventory import (
    ADDITIONS,
    BASE_SELECTION,
    digest_ids,
    load_shards,
    prove_partition,
)
from scripts.run_mutation_shard import parse_results, select_configuration

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("placement", ["extra-pilot-file", "renamed-as-normal-result"])
def test_OPS_06_pilot_cannot_satisfy_normal_aggregate_even_with_all_native_killed(
    complete_evidence: tuple[Path, dict[str, set[str]]], placement: str
) -> None:
    from scripts.mutation_pilot import PURPOSE, build_plan

    directory, _ = complete_evidence
    batch = build_plan(ROOT)["batches"][0]
    report = {
        "purpose": PURPOSE,
        "manifest": batch,
        "records": dict.fromkeys(batch["selected"], "killed"),
    }
    name = (
        batch["shard"]
        if placement == "extra-pilot-file"
        else load_shards(ROOT / "config/mutation-shards.json")[0].name
    )
    (directory / (name + ".json")).write_text(json.dumps(report), encoding="utf-8")
    summary = gate.aggregate(ROOT, directory, "test-commit", "success")
    assert summary["passed"] is False
    assert summary["failures"]


def test_OPS_06_workflow_partition_and_selector_additions_are_exact() -> None:
    shards = load_shards(ROOT / "config/mutation-shards.json")
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    matrix = workflow["jobs"]["mutations"]
    assert matrix["strategy"]["matrix"]["shard"] == [s.name for s in shards]
    assert matrix["timeout-minutes"] == 120
    assert matrix["strategy"]["fail-fast"] is False
    assert (ROOT / ".github/workflows/ci.yml").read_bytes() == (
        ROOT.parent / ".github/workflows/ci.yml"
    ).read_bytes()
    original = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert (
        tuple(tomllib.loads(original)["tool"]["mutmut"]["pytest_add_cli_args_test_selection"])
        == BASE_SELECTION
    )
    for shard in shards:
        patched = select_configuration(
            original,
            {
                "paths": list(shard.paths),
                "base_selection": list(BASE_SELECTION),
                "additional_tests": list(shard.additional_tests),
            },
        )
        config = tomllib.loads(patched)["tool"]["mutmut"]
        assert config["source_paths"] == list(shard.paths)
        assert config["pytest_add_cli_args_test_selection"] == list(
            BASE_SELECTION + ADDITIONS.get(shard.parent, ())
        )


@pytest.mark.parametrize("status", ["survived", "no tests", "timeout", "not checked"])
def test_OPS_06_only_individually_approved_survivors_are_accepted(status: str) -> None:
    assert approved_equivalents() == OWNER_APPROVED_IDS
    for key in OWNER_APPROVED_IDS:
        evidence = "m_" + key.encode("utf-8").hex() + ": " + status
        if status == "survived":
            assert require_complete_results(evidence) == 1
        else:
            with pytest.raises(DataIntegrityError):
                require_complete_results(evidence)
    with pytest.raises(DataIntegrityError):
        require_complete_results("m_" + b"unlisted".hex() + ": " + status)


@pytest.mark.parametrize("change", ["extra", "duplicate", "missing", "owner", "fingerprint"])
def test_OPS_06_approval_file_cannot_expand_authorization(tmp_path: Path, change: str) -> None:
    data = json.loads((ROOT / "config/tax-equivalent-mutants.json").read_text())
    if change == "extra":
        data["entries"].append({**data["entries"][0], "id": "another_mutant"})
    elif change == "duplicate":
        data["entries"][1] = data["entries"][0]
    elif change == "missing":
        data["entries"].pop()
    elif change == "fingerprint":
        data["entries"][0]["fingerprint"] = "sha256:" + "0" * 64
    else:
        data["entries"][0]["approved_by"] = "agent"
    path = tmp_path / "approvals.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        approved_equivalents(path)


@pytest.mark.parametrize(
    "text", ["a: killed", "a: killed\na: killed", "a: killed\nb: killed\nc: killed", "malformed"]
)
def test_OPS_06_native_results_must_cover_generated_ids_exactly(text: str) -> None:
    with pytest.raises(DataIntegrityError):
        parse_results(text, ["a", "b"])
    assert parse_results("a: killed\nb: survived\n", ["a", "b"]) == {"a": "killed", "b": "survived"}


@pytest.fixture
def complete_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, set[str]]]:
    shards = load_shards(ROOT / "config/mutation-shards.json")
    generated: dict[str, set[str]] = {p: set() for s in shards for p in s.paths}
    for shard in shards:
        for key in shard.ids:
            filename = next(
                p for p in shard.paths if key.startswith(p[:-3].replace("/", ".") + ".")
            )
            generated[filename].add(key)
    inventory_hash = prove_partition(shards, generated)
    assert inventory_hash == digest_ids(set().union(*generated.values()))
    monkeypatch.setattr(gate, "generate_inventory", lambda root: generated)
    assignment = hashlib.sha256((ROOT / "config/mutation-shards.json").read_bytes()).hexdigest()
    fingerprints = {row["new_id"]: row["fingerprint"] for row in read_map(ROOT) if row["new_id"]}
    for shard in shards:
        manifest = {
            "shard": shard.name,
            "parent": shard.parent,
            "source_job": shard.source_job,
            "fingerprint_map_sha256": hashlib.sha256((ROOT / MAP_PATH).read_bytes()).hexdigest(),
            "fingerprints": {key: fingerprints[key] for key in shard.ids},
            "head_sha": "test-commit",
            "inventory_sha256": inventory_hash,
            "assignment_sha256": assignment,
            "selected": list(shard.ids),
            "expected_count": len(shard.ids),
        }
        report = {
            "manifest": manifest,
            "records": dict.fromkeys(shard.ids, "killed"),
            "fingerprint_records": [
                {
                    "id": key,
                    "fingerprint": fingerprints[key],
                    "native_status": "killed",
                    "reason": "assertion",
                    "failures": [
                        {
                            "kind": "assertion",
                            "phase": "call",
                            "type": "AssertionError",
                            "test": "offline behavior evidence",
                        }
                    ],
                }
                for key in shard.ids
            ],
            "run_exit": 0,
            "export_exit": 0,
            "passed": True,
        }
        (tmp_path / (shard.name + ".json")).write_text(json.dumps(report), encoding="utf-8")
    return tmp_path, generated


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "approved",
        "unlisted",
        "no tests",
        "timeout",
        "not checked",
        "missing_file",
        "missing_id",
        "stale",
        "native_failure",
        "matrix_timeout",
        "crash_kill",
        "unaudited_kill",
        "fingerprint",
        "wrong_parent",
    ],
)
def test_OPS_06_aggregate_requires_every_id_and_every_job(
    complete_evidence: tuple[Path, dict[str, set[str]]], fault: str
) -> None:
    directory, _ = complete_evidence
    path = directory / "tax-1.json"
    report: dict[str, Any] = json.loads(path.read_text())
    key = next(k for k in report["records"] if k not in OWNER_APPROVED_IDS)
    if fault == "missing_file":
        path.unlink()
    else:
        if fault == "approved":
            report["records"].update(dict.fromkeys(OWNER_APPROVED_IDS, "survived"))
        elif fault == "unlisted":
            report["records"][key] = "survived"
        elif fault in {"no tests", "timeout", "not checked"}:
            report["records"][key] = fault
        elif fault == "missing_id":
            del report["records"][key]
        elif fault == "stale":
            report["manifest"]["head_sha"] = "old-commit"
        elif fault == "native_failure":
            report["run_exit"] = 1
        elif fault == "crash_kill":
            report["fingerprint_records"][0]["reason"] = "crash"
            report["fingerprint_records"][0]["failures"] = [
                {
                    "kind": "crash",
                    "phase": "setup",
                    "type": "RuntimeError",
                    "test": "offline failure",
                }
            ]
        elif fault == "unaudited_kill":
            report["fingerprint_records"].pop()
        elif fault == "fingerprint":
            report["manifest"]["fingerprints"][key] = "sha256:" + "0" * 64
        elif fault == "wrong_parent":
            report["manifest"]["source_job"] = "executor-a-1"
        for audit in report["fingerprint_records"]:
            if audit["id"] in report["records"]:
                audit["native_status"] = report["records"][audit["id"]]
                if audit["native_status"] != "killed":
                    audit["reason"] = audit["native_status"]
        path.write_text(json.dumps(report), encoding="utf-8")
    summary = gate.aggregate(
        ROOT, directory, "test-commit", "timed_out" if fault == "matrix_timeout" else "success"
    )
    assert summary["passed"] is (fault in {"none", "approved"})
    assert len(summary["jobs"]) == 135
    if summary["passed"]:
        assert summary["reported"] == 15467


def test_OPS_06_partition_rejects_overlap_missing_and_wrong_source(
    complete_evidence: tuple[Path, dict[str, set[str]]],
) -> None:
    _, generated = complete_evidence
    shards = load_shards(ROOT / "config/mutation-shards.json")
    changed = {p: set(ids) for p, ids in generated.items()}
    path = "backend/tax/reports.py"
    changed[path].pop()
    with pytest.raises(DataIntegrityError):
        prove_partition(shards, changed)
    overlapping = (
        shards[0],
        replace(shards[1], ids=(shards[0].ids[0], *shards[1].ids[1:])),
        *shards[2:],
    )
    with pytest.raises(DataIntegrityError):
        prove_partition(overlapping, generated)
    wrong_source = {p: set(ids) for p, ids in generated.items()}
    moved = wrong_source["backend/execution/alpaca_executor.py"].pop()
    wrong_source["backend/tax/reports.py"].add(moved)
    with pytest.raises(DataIntegrityError):
        prove_partition(shards, wrong_source)
    changed = {p: set(ids) for p, ids in generated.items()}
    changed[path].add("backend.tax.reports.x_unassigned__mutmut_1")
    with pytest.raises(DataIntegrityError):
        prove_partition(shards, changed)


@pytest.mark.parametrize(
    ("body", "native_status", "expected", "exit_code"),
    [
        ("def test_behavior():\n    assert False\n", "killed", "assertion", 1),
        (
            "import pytest\ndef test_behavior():\n    with pytest.raises(ValueError):\n        pass\n",
            "killed",
            "assertion",
            1,
        ),
        (
            "def test_behavior():\n    raise TypeError('offline injected runtime failure')\n",
            "killed",
            "crash",
            1,
        ),
        (
            "import pytest\n@pytest.fixture\ndef broken():\n    raise RuntimeError('offline setup failure')\ndef test_behavior(broken):\n    pass\n",
            "killed",
            "crash",
            1,
        ),
        ("raise ImportError('offline collection failure')\n", "killed", "crash", 2),
        ("def test_behavior():\n    assert True\n", "survived", "survived", 0),
    ],
)
def test_OPS_06_native_pytest_audit_distinguishes_behavior_from_crashes(
    tmp_path: Path, body: str, native_status: str, expected: str, exit_code: int
) -> None:
    import os
    import subprocess
    import sys

    from scripts.mutation_audit import audit_results

    module = tmp_path / "test_offline_audit.py"
    module.write_text(body, encoding="utf-8")
    audit_directory = tmp_path / "audit"
    mutant = "offline.behavior.x_contract__mutmut_1"
    environment = {
        **os.environ,
        "VWS_MUTATION_AUDIT_DIR": str(audit_directory),
        "MUTANT_UNDER_TEST": mutant,
        "PYTHONPATH": str(ROOT),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-socket",
            "-p",
            "scripts.mutation_audit",
            str(module),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == exit_code
    rows, clean = audit_results(
        audit_directory, {mutant: native_status}, {mutant: "sha256:" + "a" * 64}
    )
    assert clean == [] and len(rows) == 1
    assert rows[0]["reason"] == expected
    assert rows[0]["fingerprint"] == "sha256:" + "a" * 64
    if expected == "assertion":
        assert rows[0]["failures"][0]["phase"] == "call"
        assert rows[0]["failures"][0]["type"] in {"AssertionError", "Failed"}
        assert rows[0]["tests_collected"] == 1


@pytest.mark.parametrize("status", ["timeout", "segfault", "suspicious"])
def test_OPS_06_timeout_crash_and_missing_assertion_evidence_never_count_as_kills(
    tmp_path: Path, status: str
) -> None:
    from scripts.mutation_audit import audit_results

    key = "offline.behavior.x_contract__mutmut_1"
    rows, clean = audit_results(tmp_path, {key: status}, {key: "sha256:" + "a" * 64})
    assert clean == []
    assert (
        rows[0]["reason"]
        == {"timeout": "timeout", "segfault": "crash", "suspicious": "suspicious"}[status]
    )
    assert rows[0]["reason"] != "assertion"


def test_OPS_06_fingerprint_survives_line_and_native_number_changes() -> None:
    from scripts.mutation_fingerprints import mutation_rows

    before = "def rule(value):\n    return value + 1\n"
    after = "\n\ndef rule(value):\n    limit = 10\n    return value + 1\n"
    old = [
        row
        for row in mutation_rows("backend/risk/example.py", before)
        if row["payload"][2] == "return value + 1"
    ]
    new = [
        row
        for row in mutation_rows("backend/risk/example.py", after)
        if row["payload"][2] == "return value + 1"
    ]
    assert {row["fingerprint"] for row in old} == {row["fingerprint"] for row in new}
    assert old and new and old[0]["line"] != new[0]["line"] and old[0]["id"] != new[0]["id"]


def test_OPS_06_fingerprint_keeps_exact_mutated_audit_message_whitespace() -> None:
    from scripts.mutation_fingerprints import mutation_rows

    source = "def audit():\n    return 'alpha  beta'\n"
    rows = mutation_rows("backend/risk/example.py", source)
    text_mutations = [row for row in rows if row["operator"] == "operator_string"]
    assert text_mutations
    assert any("alpha  beta" in row["payload"][4] for row in text_mutations)
    assert all(row["payload"][4] == row["mutated_text"] for row in rows)


def test_OPS_06_duplicate_fingerprints_preserve_every_occurrence_in_source_order() -> None:
    from collections import defaultdict

    from scripts.mutation_fingerprints import mutation_rows

    source = "def rule(value):\n    value = value + 1\n    value = value + 1\n    return value\n"
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows = mutation_rows("backend/risk/example.py", source)
    for row in rows:
        groups[row["fingerprint"]].append(row)
    duplicates = [group for group in groups.values() if len(group) > 1]
    assert duplicates
    assert sum(len(group) for group in groups.values()) == len(rows)
    assert all(
        [row["line"] for row in group] == sorted(row["line"] for row in group)
        for group in duplicates
    )
    assert len({row["id"] for row in rows}) == len(rows)
