"""SEC-24/OPS: GitHub Actions single-flight review for every workflow.

No workflow may trade, hold secrets or write repository state. Scheduled and
manually dispatched workflows run single-flight with ``cancel-in-progress:
false`` so a running job is never interrupted. The push/pull_request gate is
deliberately exempt: a concurrency group would cancel *pending* gate runs, so
an intermediate commit could skip its required checks.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT = Path(__file__).resolve().parents[2]
ROOT_WORKFLOWS = PROJECT.parent / ".github/workflows"
NESTED_WORKFLOWS = PROJECT / ".github/workflows"

SINGLE_FLIGHT = {
    "mutation-diagnostics.yml": "vws-mutation-diagnostics",
    "mutation-pilot.yml": "vws-mutation-pilot",
    "weekly-audit.yml": "vws-weekly-audit",
}
PER_COMMIT_GATES = {"ci.yml"}


def _load(path: Path) -> dict[Any, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_OPS_concurrency_every_workflow_is_classified_and_mirrored() -> None:
    names = {path.name for path in ROOT_WORKFLOWS.glob("*.yml")}
    assert names == set(SINGLE_FLIGHT) | PER_COMMIT_GATES
    assert {path.name for path in NESTED_WORKFLOWS.glob("*.yml")} == names
    assert not set(ROOT_WORKFLOWS.glob("*.yaml")) and not set(NESTED_WORKFLOWS.glob("*.yaml"))
    for name in names:
        assert (ROOT_WORKFLOWS / name).read_bytes() == (NESTED_WORKFLOWS / name).read_bytes()


@pytest.mark.parametrize("name", sorted(SINGLE_FLIGHT))
def test_OPS_concurrency_scheduled_and_dispatch_workflows_are_single_flight(name: str) -> None:
    workflow = _load(ROOT_WORKFLOWS / name)
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    assert set(trigger) <= {"schedule", "workflow_dispatch"}
    assert workflow["concurrency"] == {"group": SINGLE_FLIGHT[name], "cancel-in-progress": False}
    for job in workflow["jobs"].values():
        assert "concurrency" not in job


def test_OPS_concurrency_per_commit_gate_never_drops_pending_runs() -> None:
    workflow = _load(ROOT_WORKFLOWS / "ci.yml")
    assert workflow.get("on", workflow.get(True)) == ["push", "pull_request"]
    assert "concurrency" not in workflow
    assert all("concurrency" not in job for job in workflow["jobs"].values())


@pytest.mark.parametrize("name", sorted(set(SINGLE_FLIGHT) | PER_COMMIT_GATES))
def test_OPS_concurrency_no_workflow_can_trade_or_write_state(name: str) -> None:
    text = (ROOT_WORKFLOWS / name).read_text(encoding="utf-8")
    workflow = _load(ROOT_WORKFLOWS / name)
    assert workflow["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in workflow["jobs"].values())
    assert re.search(r"\$\{\{\s*secrets(?:\.|\[)", text) is None
    assert "pull_request_target" not in text
    for forbidden in ("git push", "gh api", "gh pr", "gh release", "-m vws ", "vws start"):
        assert forbidden not in text
