"""OPS-06: diagnostic retention, ownership, redaction and unchanged qualification."""

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml

from scripts import mutation_evidence as evidence
from scripts import run_mutation_shard as runner
from scripts.mutation_audit import audit_results, sanitized_frames

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def retained_child(tmp_path: Path) -> tuple[Path, dict[str, Any], list[str]]:
    keys = ["backend.risk.probe.x_rule__mutmut_" + str(i) for i in (1, 2, 3)]
    manifest = {
        "shard": "risk-sizing-1-1",
        "source_job": "risk-sizing-1",
        "parent": "risk-sizing",
        "head_sha": "fresh-offline-head",
        "selected": keys,
        "fingerprints": {key: "sha256:" + char * 64 for key, char in zip(keys, "abc", strict=True)},
    }
    directory = tmp_path / "build/mutation-results"
    directory.mkdir(parents=True)
    (directory / "risk-sizing-1-1.json").write_text(
        json.dumps({"manifest": manifest, "records": {keys[0]: "survived"}}), encoding="utf-8"
    )
    native = tmp_path / "mutants/backend/risk"
    native.mkdir(parents=True)
    (native / "probe.py.meta").write_text(
        json.dumps(
            {
                "exit_code_by_key": {keys[0]: 0, keys[1]: 1, keys[2]: None, "foreign": 0},
                "durations_by_key": {keys[0]: 12.5, keys[1]: 42.0},
                "estimated_durations_by_key": {keys[0]: 20.0, keys[1]: 20.0},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "mutants/mutmut-stats.json").write_text(
        json.dumps(
            {
                "tests_by_mangled_function_name": {
                    "backend.risk.probe.x_rule": ["test_a", "test_b"]
                },
                "duration_by_test": {"test_" + str(i): 1.0 for i in range(10)},
            }
        ),
        encoding="utf-8",
    )
    audit = directory / "risk-sizing-1-1-audit"
    audit.mkdir()
    (audit / "failed.json").write_text(
        json.dumps(
            {
                "mutant": keys[1],
                "collect_only": False,
                "calls": 1,
                "collected": 2,
                "duration_seconds": 41.0,
                "finished": True,
                "exit_status": 1,
                "failures": [
                    {
                        "phase": "call",
                        "kind": "crash",
                        "type": "ValueError",
                        "frames": [
                            {
                                "file": "backend/risk/probe.py",
                                "function": "rule",
                                "line": 7,
                                "origin": "production",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, manifest, keys


def test_native_timing_status_mapping_and_every_missing_id_are_retained(
    retained_child: tuple[Path, dict[str, Any], list[str]],
) -> None:
    root, manifest, keys = retained_child
    summary = evidence.harvest(root, manifest["shard"])
    assert summary["assigned"] == 3 and summary["missing"] == 2 and summary["survivors"] == 1
    assert summary["metrics"]["median_seconds"] == 27.25
    assert summary["metrics"]["p95_seconds"] == 42.0
    assert summary["metrics"]["median_tests_selected"] == 2
    assert summary["metrics"]["max_tests_selected"] == 2
    assert summary["cohort_test_count"] == 10
    directory = root / "build/mutation-results/risk-sizing-1-1-evidence"
    data = json.loads((directory / "native-status.json").read_text())
    rows = {row["id"]: row for row in data["records"]}
    assert set(rows) == set(keys)
    assert rows[keys[0]]["native_status"] == "survived"
    assert rows[keys[1]]["native_exit_code"] == 1 and rows[keys[1]]["native_seconds"] == 42.0
    assert rows[keys[1]]["exception_category"] == "production"
    assert rows[keys[1]]["pytest_seconds"] == 41.0
    assert rows[keys[2]]["native_status"] == "not checked"
    assert rows[keys[2]]["native_seconds"] is None
    assert keys[0] in (directory / "ALL_SURVIVORS.md").read_text()
    assert {row["id"] for row in csv.DictReader((directory / "MISSING_IDS.csv").open())} == set(
        keys[1:]
    )
    assert len(list(csv.DictReader((directory / "timings.csv").open()))) == 3
    assert (
        json.loads((directory / "exception-frames.json").read_text())[0]["failures"][0]["frames"][
            0
        ]["line"]
        == 7
    )
    assert json.loads((directory / "test-selection.json").read_text())["tests_by_function"] == {
        "backend.risk.probe.x_rule": ["test_a", "test_b"]
    }


@pytest.mark.parametrize(
    "kind",
    [
        "missing-meta",
        "missing-stats",
        "empty-stats",
        "collection-audit",
        "foreign-audit",
        "invalid-meta",
    ],
)
def test_incomplete_child_stays_explicit_without_inventing_results(
    retained_child: tuple[Path, dict[str, Any], list[str]],
    kind: str,
) -> None:
    root, manifest, keys = retained_child
    if kind == "missing-meta":
        (root / "mutants/backend/risk/probe.py.meta").unlink()
    elif kind == "missing-stats":
        (root / "mutants/mutmut-stats.json").unlink()
    elif kind == "empty-stats":
        (root / "mutants/mutmut-stats.json").write_text(
            '{"duration_by_test": {}, "tests_by_mangled_function_name": {}}'
        )
    elif kind == "invalid-meta":
        (root / "mutants/backend/risk/probe.py.meta").write_text("invalid")
    else:
        path = root / "build/mutation-results/risk-sizing-1-1-audit/failed.json"
        data = json.loads(path.read_text())
        data.update(
            collect_only=kind == "collection-audit",
            mutant="foreign" if kind == "foreign-audit" else keys[1],
        )
        path.write_text(json.dumps(data))
    summary = evidence.harvest(root, manifest["shard"])
    assert summary["assigned"] == 3 and summary["missing"] == 2
    data = json.loads(
        (root / "build/mutation-results/risk-sizing-1-1-evidence/native-status.json").read_text()
    )
    assert {r["id"] for r in data["records"]} == set(keys)
    if kind in {"missing-meta", "invalid-meta"}:
        assert summary["metrics"]["native_duration_count"] == 0
    if kind == "missing-stats":
        assert summary["metrics"]["median_tests_selected"] is None
    if kind == "empty-stats":
        assert summary["metrics"]["max_tests_selected"] == 0
    if kind in {"collection-audit", "foreign-audit"}:
        assert all(not r["failures"] for r in data["records"])


@pytest.mark.parametrize("value", ["missing", "[]", "broken", "{}"])
def test_unreadable_diagnostic_files_are_reported_without_exception_text(
    tmp_path: Path, value: str
) -> None:
    path = tmp_path / "input.json"
    if value != "missing":
        path.write_text(value)
    errors: list[str] = []
    assert evidence.read_json(path, errors) == {}
    assert errors == ([] if value == "{}" else ["unreadable evidence file"])


@pytest.mark.parametrize(
    "change",
    ["none", "missing-child", "different-head", "different-fingerprint", "different-owner"],
)
def test_aggregate_exports_every_survivor_and_missing_id_without_accepting_observations(
    retained_child: tuple[Path, dict[str, Any], list[str]],
    change: str,
) -> None:
    root, manifest, keys = retained_child
    evidence.harvest(root, manifest["shard"])
    directory = root / "build/mutation-results"
    records = {keys[0]: "survived"}
    if change == "missing-child":
        for path in (directory / "risk-sizing-1-1-evidence").iterdir():
            path.unlink()
    elif change == "different-head":
        path = directory / "risk-sizing-1-1-evidence/manifest.json"
        path.write_text(json.dumps({**manifest, "head_sha": "stale"}))
    elif change in {"different-fingerprint", "different-owner"}:
        path = directory / "risk-sizing-1-1-evidence/native-status.json"
        data = json.loads(path.read_text())
        for row in data["records"]:
            row["fingerprint" if change == "different-fingerprint" else "source_job"] = "different"
        path.write_text(json.dumps(data))
    summary = evidence.aggregate_exports(
        directory, [manifest], records, [{"id": keys[0], "failures": []}]
    )
    assert summary["assigned"] == 3 and summary["missing"] == 2
    assert summary["survivors"] == 1
    markdown = (directory / "aggregate-evidence/ALL_SURVIVORS.md").read_text()
    assert keys[0] in markdown
    assert set(
        r["id"] for r in csv.DictReader((directory / "aggregate-evidence/MISSING_IDS.csv").open())
    ) == set(keys[1:])
    if change.startswith("different"):
        assert summary["errors"]


@pytest.mark.parametrize(
    ("status", "phase", "origins", "expected"),
    [
        ("timeout", "call", [], "runner:timeout"),
        ("segfault", "call", [], "runner:worker-death"),
        ("killed", "collection", [], "runner:collection/import"),
        ("killed", "setup", ["test-harness"], "runner:fixture/setup"),
        ("killed", "call", ["test-harness"], "runner:test-harness"),
        ("killed", "setup", ["production"], "production"),
        ("killed", "call", ["production", "external"], "production-via-library"),
        ("killed", "call", ["runner", "external"], "runner:internal"),
        ("killed", "call", [], "unverified"),
    ],
)
def test_exception_attribution_is_diagnostic_and_does_not_qualify_a_kill(
    tmp_path: Path,
    status: str,
    phase: str,
    origins: list[str],
    expected: str,
) -> None:
    failure = {
        "phase": phase,
        "kind": "crash",
        "type": "ValueError",
        "frames": [{"origin": origin} for origin in origins],
    }
    assert evidence.exception_category({"native_status": status, "failures": [failure]}) == expected
    key = "offline.x_rule__mutmut_1"
    (tmp_path / "audit.json").write_text(
        json.dumps(
            {
                "mutant": key,
                "collect_only": False,
                "finished": True,
                "exit_status": 1,
                "failures": [failure],
                "calls": 1,
                "collected": 1,
            }
        )
    )
    records, _ = audit_results(tmp_path, {key: status}, {key: "sha256:" + "a" * 64})
    assert records[0]["reason"] != "assertion"


def test_empty_timing_evidence_is_unknown_not_zero() -> None:
    assert evidence.metrics([]) == {
        "native_duration_count": 0,
        "median_seconds": None,
        "p95_seconds": None,
        "p95_method": "nearest rank",
        "median_tests_selected": None,
        "max_tests_selected": None,
        "slowest_10": [],
    }


def test_native_internal_error_code_is_runner_evidence_without_a_traceback() -> None:
    assert (
        evidence.exception_category({"native_status": "killed", "native_exit_code": 3})
        == "runner:internal"
    )


def test_diagnostic_command_uses_the_preflight_child(
    retained_child: tuple[Path, dict[str, Any], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, manifest, _ = retained_child
    monkeypatch.chdir(root)
    monkeypatch.setenv("VWS_MUTATION_SHARD", manifest["shard"])
    assert evidence.main() == 0


def test_diagnostic_export_refuses_to_guess_a_missing_preflight(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^preflight identity unavailable$"):
        evidence.harvest(tmp_path, "missing-child")


def test_frames_never_include_dynamic_paths_messages_source_or_local_values(tmp_path: Path) -> None:
    marker = "FRAME" + "_CANARY_" + "VALUE"
    info = cast(
        pytest.ExceptionInfo[BaseException],
        SimpleNamespace(
            value=ValueError(marker),
            traceback=[SimpleNamespace(path=tmp_path / marker, name=marker, lineno=0)],
        ),
    )
    frames = sanitized_frames(info)
    serialized = json.dumps(frames)
    assert marker not in serialized
    assert all(set(frame) == {"file", "function", "line", "origin"} for frame in frames)
    assert frames[-1]["file"] == "<external>" and frames[-1]["function"] == "<external>"
    assert not re.search(r"(?i)(api[_-]?key|token|password|authorization)\s*[:=]", serialized)


@pytest.mark.parametrize("phase", ["call", "setup", "collection", "internal"])
def test_real_pytest_retains_timing_selection_and_sanitized_exception_locations(
    tmp_path: Path, phase: str
) -> None:
    target = tmp_path / "backend/tests"
    target.mkdir(parents=True)
    body = {
        "call": "def test_probe():\n    import os\n    raise ValueError(os.environ['FRAME_CANARY'])\n",
        "setup": "import pytest,os\n@pytest.fixture\ndef broken():\n    raise ValueError(os.environ['FRAME_CANARY'])\ndef test_probe(broken):\n    pass\n",
        "collection": "import os\nraise ImportError(os.environ['FRAME_CANARY'])\n",
        "internal": "def test_probe():\n    pass\n",
    }[phase]
    (target / "test_probe.py").write_text(body)
    if phase == "internal":
        (target / "conftest.py").write_text(
            "import os\ndef pytest_collection_modifyitems(items):\n    raise RuntimeError(os.environ['FRAME_CANARY'])\n"
        )
    marker = "FRAME" + "_CANARY_" + "VALUE"
    directory = tmp_path / "audit"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-socket",
            "-p",
            "scripts.mutation_audit",
            str(target),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "VWS_MUTATION_AUDIT_DIR": str(directory),
            "MUTANT_UNDER_TEST": "offline.x_probe__mutmut_1",
            "FRAME_CANARY": marker,
        },
        capture_output=True,
        check=False,
    )
    assert result.returncode == (3 if phase == "internal" else 2 if phase == "collection" else 1)
    data = json.loads(next(directory.glob("*.json")).read_text())
    assert data["finished"] and data["duration_seconds"] > 0 and data["started_utc"]
    assert data["collected"] == (0 if phase == "collection" else 1)
    assert data["failures"][0]["phase"] == phase
    assert data["failures"][0]["frames"][-1]["file"] == (
        "backend/tests/conftest.py" if phase == "internal" else "backend/tests/test_probe.py"
    )
    assert marker not in json.dumps(data)
    assert not re.search(
        rb"(?i)(api[_-]?key|token|password|authorization)\s*[:=]",
        next(directory.glob("*.json")).read_bytes(),
    )
    if phase not in {"collection", "internal"}:
        assert data["phase_seconds"][phase] >= 0


def test_preflight_identity_exists_before_the_native_process_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "shard": "offline-1",
        "paths": ["backend/risk/"],
        "base_selection": [],
        "additional_tests": [],
        "patterns": [],
    }
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    (tmp_path / "vws-mutation-shard.json").write_text(json.dumps(manifest))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("VWS_MUTATION_SHARD", "offline-1")
    monkeypatch.setattr(runner, "build_manifest", lambda root, name: manifest)

    def interrupted(*args: Any, **kwargs: Any) -> None:
        assert (
            json.loads((tmp_path / "build/mutation-results/offline-1.json").read_text())["manifest"]
            == manifest
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.main()
    assert (tmp_path / "pyproject.toml").read_text() == (ROOT / "pyproject.toml").read_text()


def test_workflows_publish_diagnostics_without_changing_native_command_or_gate() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    mutations = workflow["jobs"]["mutations"]
    assert (
        mutations["timeout-minutes"] == 120 and len(mutations["strategy"]["matrix"]["shard"]) == 135
    )
    steps = mutations["steps"]
    native = next(
        s for s in steps if s.get("name") == "Native mutmut and unchanged 100 percent gate"
    )
    assert native["run"].splitlines() == [
        "python -m scripts.run_mutation_shard",
        'python -m scripts.check_mutations "$RUNNER_TEMP/vws-mutants.txt"',
    ]
    export = next(s for s in steps if s.get("run") == "python -m scripts.mutation_evidence")
    assert export["if"] == "${{ always() }}"
    artifact = next(
        s for s in steps if s.get("name") == "Preserve individual native mutation results"
    )
    assert "${{ matrix.shard }}-evidence/" in artifact["with"]["path"]
    aggregate = workflow["jobs"]["mutations-gate"]
    assert aggregate["needs"] == "mutations" and aggregate["if"] == "${{ always() }}"
    assert "aggregate-evidence/" in aggregate["steps"][-1]["with"]["path"]
    assert (ROOT / ".github/workflows/ci.yml").read_bytes() == (
        ROOT.parent / ".github/workflows/ci.yml"
    ).read_bytes()
