"""SEC-22..24/OPS-06: actual lock SBOMs and the Git-root workflow mirrors."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from backend.core.dependencies import require_hash_lock

PROJECT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["requirements.lock", "requirements-dev.lock"])
def test_SEC_23_generated_cyclonedx_contains_exact_hash_lock_pins(
    tmp_path: Path, name: str
) -> None:
    lock = PROJECT / name
    output = tmp_path / "sbom.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cyclonedx_py",
            "requirements",
            str(lock),
            "--output-format",
            "JSON",
            "--output-file",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(output.read_bytes())
    assert document["bomFormat"] == "CycloneDX"

    def canonical(value: str) -> str:
        return re.sub(r"[-_.]+", "-", value).lower()

    inventory = {canonical(row["name"]): row["version"] for row in document["components"]}
    pins = {
        canonical(name): version
        for name, version in re.findall(
            r"(?m)^([A-Za-z0-9_.-]+)==([^\s;]+)", lock.read_text(encoding="utf-8")
        )
    }
    assert inventory == pins
    assert set(inventory) == require_hash_lock(lock)


@pytest.mark.parametrize("name", ["ci.yml", "weekly-audit.yml"])
def test_SEC_24_workflows_are_sha_pinned_and_reachable_at_actual_git_root(name: str) -> None:
    nested = PROJECT / ".github/workflows" / name
    root = PROJECT.parent / ".github/workflows" / name
    assert root.read_bytes() == nested.read_bytes()
    text = root.read_text(encoding="utf-8")
    uses = re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", text)
    assert uses and all(re.fullmatch(r"[^\s@]+@[0-9a-f]{40}", value) for value in uses)
    assert (
        "pull_request_target" not in text and re.search(r"\$\{\{\s*secrets(?:\.|\[)", text) is None
    )
    value = yaml.safe_load(text)
    assert value["permissions"] == {"contents": "read"}
    assert "--require-hashes --no-deps" in text
    assert "--output-file build/sbom/runtime.json" in text
    assert "--output-file build/sbom/development.json" in text
    assert "if-no-files-found: error" in text
    assert "pip_audit -r requirements.lock" in text and "pip_audit -r requirements-dev.lock" in text


def test_SEC_22_weekly_audit_and_dependabot_only_propose_reviewed_updates() -> None:
    nested = PROJECT / ".github/dependabot.yml"
    root = PROJECT.parent / ".github/dependabot.yml"
    assert root.read_bytes() == nested.read_bytes()
    value = yaml.safe_load(root.read_text(encoding="utf-8"))
    items = value["updates"]
    assert {item["package-ecosystem"] for item in items} == {"pip", "github-actions", "docker"}
    assert all(item["schedule"]["interval"] == "weekly" and item["groups"] for item in items)
    assert (
        next(item for item in items if item["package-ecosystem"] == "github-actions")["directory"]
        == "/"
    )
    weekly = (PROJECT / ".github/workflows/weekly-audit.yml").read_text(encoding="utf-8")
    assert "schedule:" in weekly and "cron:" in weekly
    assert "workflow_dispatch:" in weekly
    assert "automerge" not in weekly and "git push" not in weekly


def test_OPS_06_root_ci_keeps_mutation_postgres_build_and_whole_coverage() -> None:
    text = (PROJECT.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "services:" in text and "postgres:" in text
    assert "docker compose build" in text
    assert "scripts.check_mutations" in text
    assert "--cov-fail-under=100" in text and "--cov=backend.agents.fundamentals" in text
    assert "--cov=backend.evaluation" in text
