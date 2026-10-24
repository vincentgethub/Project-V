"""OPS-06: a deterministic diagnostic pilot cannot certify a mutation gate."""

import csv
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.core.errors import DataIntegrityError
from scripts import mutation_pilot as pilot
from scripts.check_mutations import require_complete_results
from scripts.mutation_evidence import observation, write_exports
from scripts.mutation_inventory import BASE_SELECTION, load_shards

ROOT = Path(__file__).resolve().parents[2]


def test_pilot_scope_sample_and_fingerprint_batches_are_reproducible() -> None:
    plan = pilot.build_plan(ROOT)
    assert pilot.encoded(plan) == pilot.encoded(pilot.build_plan(ROOT))
    config = json.loads((ROOT / pilot.CONFIG).read_text())
    shards = load_shards(ROOT / "config/mutation-shards.json")
    owners = {key: shard for shard in shards for key in shard.ids}
    wanted = {key for key, row in owners.items() if row.source_job in config["parents"]}
    with (ROOT / pilot.POOL).open(encoding="utf-8", newline="") as handle:
        pool = list(csv.DictReader(handle))
    sampled = sorted(
        {row["fingerprint"] for row in pool},
        key=lambda fp: (hashlib.sha256(("39856462454:" + fp).encode()).hexdigest(), fp),
    )[:100]
    assert {row["fingerprint"] for row in plan["sample"]} == set(sampled)
    assert len(plan["sample"]) == len(set(sampled)) == 100
    assigned = [key for batch in plan["batches"] for key in batch["selected"]]
    assert set(assigned) == wanted | {row["id"] for row in plan["sample"]}
    assert len(assigned) == len(set(assigned)) == 6201
    assert len(wanted) == plan["parent_mutants"] == 6115
    assert plan["sample_outside_parents"] == 86
    assert len(plan["batches"]) == 190
    assert len(plan["batches"]) + 2 < 256
    for batch in plan["batches"]:
        assert 1 <= batch["expected_count"] <= 40
        assert batch["patterns"] == batch["selected"]
        assert batch["base_selection"] == list(BASE_SELECTION)
        for key in batch["selected"]:
            owner = owners[key]
            assert owner.source_job == batch["source_job"]
            assert owner.parent == batch["parent"]
            assert list(owner.paths) == batch["paths"]
            assert list(owner.additional_tests) == batch["additional_tests"]


def test_dispatch_workflow_is_separate_from_the_normal_gate() -> None:
    path = ROOT / ".github/workflows/mutation-pilot.yml"
    assert path.read_bytes() == (ROOT.parent / ".github/workflows/mutation-pilot.yml").read_bytes()
    workflow = yaml.safe_load(path.read_text())
    assert workflow.get("on", workflow.get(True)) == {"workflow_dispatch": None}
    assert set(workflow["jobs"]) == {"plan", "measurements", "report"}
    assert workflow["jobs"]["measurements"]["timeout-minutes"] == 120
    text = path.read_text()
    assert "python -m mutmut run" in text
    for forbidden in (
        "check_mutations",
        "aggregate_mutations",
        "run_mutation_shard",
        "name: mutation-result-",
    ):
        assert forbidden not in text
    main = ROOT / ".github/workflows/ci.yml"
    assert main.read_bytes() == (ROOT.parent / ".github/workflows/ci.yml").read_bytes()
    assert (
        hashlib.sha256(main.read_text().encode()).hexdigest()
        == "9824325fd123bec943c0b0f03a8a96762339dac4fce380a0b7182591ce3cc5d4"
    )
    assert "pattern: mutation-result-*" in main.read_text()
    assert "diagnostic-pilot" not in main.read_text()


@pytest.fixture
def pilot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    batch = pilot.build_plan(ROOT)["batches"][0]
    monkeypatch.setattr(pilot, "build_plan", lambda root: {"batches": [batch]})
    (tmp_path / "pyproject.toml").write_bytes((ROOT / "pyproject.toml").read_bytes())
    return tmp_path, batch["shard"]


def test_pilot_prepare_preserves_all_nonselection_configuration_and_never_writes_gate_paths(
    pilot_root: tuple[Path, str],
) -> None:
    root, name = pilot_root
    original = tomllib.loads((root / "pyproject.toml").read_text())
    pilot.prepare(root, name)
    patched = tomllib.loads((root / "pyproject.toml").read_text())
    manifest = json.loads((root / pilot.OUTPUT / name / (name + ".json")).read_text())["manifest"]
    for field in ("source_paths", "pytest_add_cli_args_test_selection"):
        original["tool"]["mutmut"][field] = patched["tool"]["mutmut"][field]
    assert original == patched
    assert manifest["purpose"] == pilot.PURPOSE
    assert manifest["shard"].startswith("pilot-")
    assert not (root / "build/mutation-results").exists()
    with pytest.raises(DataIntegrityError, match="fresh pilot required"):
        pilot.prepare(root, name)


@pytest.mark.parametrize("exported", [True, False])
def test_pilot_finish_keeps_native_timing_survivors_and_missing_without_gate_credentials(
    pilot_root: tuple[Path, str], exported: bool
) -> None:
    root, name = pilot_root
    original = (root / "pyproject.toml").read_bytes()
    pilot.prepare(root, name)
    directory = root / pilot.OUTPUT / name
    report_path = directory / (name + ".json")
    manifest = json.loads(report_path.read_text())["manifest"]
    key = manifest["selected"][0]
    metadata = root / "mutants/backend/execution"
    metadata.mkdir(parents=True)
    (metadata / "probe.meta").write_text(
        json.dumps({"exit_code_by_key": {key: 0}, "durations_by_key": {key: 12.5}})
    )
    if exported:
        (directory / "native-results.txt").write_text(key + ": survived\n", encoding="utf-8")
    summary = pilot.finish(root, name)
    assert (root / "pyproject.toml").read_bytes() == original
    assert summary["metrics"]["median_seconds"] == 12.5
    assert summary["survivors"] == 1
    assert summary["missing"] == manifest["expected_count"] - int(exported)
    report = json.loads(report_path.read_text())
    assert set(report) == {"manifest", "records", "purpose"}
    assert not (root / "build/mutation-results").exists()
    evidence = directory / (name + "-evidence")
    for path in (
        report_path,
        evidence / "native-status.json",
        evidence / "timings.csv",
        evidence / "ALL_SURVIVORS.md",
    ):
        with pytest.raises(DataIntegrityError):
            require_complete_results(path.read_text(encoding="utf-8"))


def test_pilot_summary_lists_every_missing_mutant_and_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = pilot.build_plan(ROOT)
    monkeypatch.setattr(pilot, "build_plan", lambda root: plan)
    summary = pilot.summarize(tmp_path)
    assert len(summary["missing_batches"]) == 190
    assert summary["summary"]["missing"] == summary["expected"] == 6201
    assert len(summary["sample"]) == 100
    assert summary["sample_categories"] == {"unverified": 100}
    missing = tmp_path / pilot.OUTPUT / "summary/MISSING_IDS.csv"
    with missing.open(encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 6201


@pytest.mark.parametrize("fault", ["none", "head", "row"])
def test_pilot_summary_accepts_only_fresh_matching_batch_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    plan = pilot.build_plan(ROOT)
    monkeypatch.setattr(pilot, "build_plan", lambda root: plan)
    monkeypatch.setenv("GITHUB_SHA", "fresh-pilot-head")
    batch = plan["batches"][0]
    destination = tmp_path / pilot.OUTPUT / batch["shard"] / (batch["shard"] + "-evidence")
    rows = [
        observation(batch, key, "survived", True, {"seconds": 1.25}, {}, 4)
        for key in batch["selected"]
    ]
    if fault == "row":
        rows[0]["source_job"] = "another-parent"
    write_exports(destination, rows, [])
    manifest = {
        **batch,
        "head_sha": "old-head" if fault == "head" else "fresh-pilot-head",
        "plan_sha256": hashlib.sha256(pilot.encoded(plan)).hexdigest(),
    }
    (destination / "manifest.json").write_bytes(pilot.encoded(manifest))
    if fault == "none":
        result = pilot.summarize(tmp_path)
        assert result["observed"] == len(rows)
        assert result["summary"]["survivors"] == len(rows)
        assert result["per_parent"][batch["source_job"]]["median_seconds"] == 1.25
    else:
        with pytest.raises(DataIntegrityError):
            pilot.summarize(tmp_path)


@pytest.mark.parametrize("fault", ["pool", "parents", "sample"])
def test_pilot_rejects_unapproved_scope_changes(tmp_path: Path, fault: str) -> None:
    (tmp_path / "config").mkdir()
    config: dict[str, Any] = json.loads((ROOT / pilot.CONFIG).read_text())
    (tmp_path / pilot.POOL).write_bytes((ROOT / pilot.POOL).read_bytes())
    if fault == "pool":
        config["pool_sha256"] = "changed"
    elif fault == "parents":
        config["parents"].pop()
    else:
        config["sample_size"] = 99
    (tmp_path / pilot.CONFIG).write_text(json.dumps(config))
    with pytest.raises(DataIntegrityError):
        pilot.build_plan(tmp_path)
