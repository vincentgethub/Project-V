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
from scripts.mutation_inventory import (
    ADDITIONS,
    BASE_SELECTION,
    digest_ids,
    load_shards,
    prove_partition,
)
from scripts.run_mutation_shard import parse_results, select_configuration

ROOT = Path(__file__).resolve().parents[2]


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


@pytest.mark.parametrize("change", ["extra", "duplicate", "missing", "owner"])
def test_OPS_06_approval_file_cannot_expand_authorization(tmp_path: Path, change: str) -> None:
    data = json.loads((ROOT / "config/tax-equivalent-mutants.json").read_text())
    if change == "extra":
        data["entries"].append({**data["entries"][0], "id": "another_mutant"})
    elif change == "duplicate":
        data["entries"][1] = data["entries"][0]
    elif change == "missing":
        data["entries"].pop()
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
    for shard in shards:
        manifest = {
            "shard": shard.name,
            "parent": shard.parent,
            "head_sha": "test-commit",
            "inventory_sha256": inventory_hash,
            "assignment_sha256": assignment,
            "selected": list(shard.ids),
            "expected_count": len(shard.ids),
        }
        report = {
            "manifest": manifest,
            "records": dict.fromkeys(shard.ids, "killed"),
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
    ],
)
def test_OPS_06_aggregate_requires_every_id_and_every_job(
    complete_evidence: tuple[Path, dict[str, set[str]]], fault: str
) -> None:
    directory, _ = complete_evidence
    path = directory / "tax.json"
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
        path.write_text(json.dumps(report), encoding="utf-8")
    summary = gate.aggregate(
        ROOT, directory, "test-commit", "timed_out" if fault == "matrix_timeout" else "success"
    )
    assert summary["passed"] is (fault in {"none", "approved"})
    assert len(summary["jobs"]) == 63
    if summary["passed"]:
        assert summary["reported"] == 13381


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
