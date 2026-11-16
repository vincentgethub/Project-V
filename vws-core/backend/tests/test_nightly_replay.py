"""Item 5: a scheduled, read-only, secret-free nightly run of the existing replay."""

import re
from pathlib import Path
from typing import Any

import yaml

PROJECT = Path(__file__).resolve().parents[2]
NAME = ".github/workflows/nightly-replay.yml"


def workflow() -> tuple[str, dict[Any, Any]]:
    root, nested = PROJECT.parent / NAME, PROJECT / NAME
    assert root.read_bytes() == nested.read_bytes()
    text = root.read_text(encoding="utf-8")
    value = yaml.safe_load(text)
    assert isinstance(value, dict)
    return text, value


def test_REPLAY_NIGHTLY_is_scheduled_daily_single_flight_and_read_only() -> None:
    text, value = workflow()
    triggers = value[True]  # YAML 1.1 reads the bare key `on` as True.
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    (cron,) = (row["cron"] for row in triggers["schedule"])
    minute, hour, *rest = cron.split()
    assert rest == ["*", "*", "*"] and minute.isdigit() and hour.isdigit()
    assert value["permissions"] == {"contents": "read"}
    assert value["concurrency"] == {"group": "vws-nightly-replay", "cancel-in-progress": False}
    for job in value["jobs"].values():
        assert "permissions" not in job and "environment" not in job
        assert job["runs-on"] == "ubuntu-latest" and 1 <= job["timeout-minutes"] <= 60


def test_REPLAY_NIGHTLY_uses_only_the_pinned_actions_and_no_secrets() -> None:
    text, _ = workflow()
    uses = set(re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", text))
    ci = (PROJECT.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    pinned = set(re.findall(r"(?m)^\s*-?\s*uses:\s*([^\s#]+)", ci))
    assert uses and uses <= pinned
    assert all(re.fullmatch(r"[^\s@]+@[0-9a-f]{40}", value) for value in uses)
    assert re.search(r"\$\{\{\s*secrets(?:\.|\[)", text) is None
    for banned in ("pull_request_target", "git push", "upload-artifact", ".env", "API_KEY"):
        assert banned not in text


def test_REPLAY_NIGHTLY_runs_the_existing_offline_replay() -> None:
    text, _ = workflow()
    assert "--require-hashes --no-deps -r requirements-dev.lock" in text
    assert "-m 'not perf' backend/tests/test_replay_cli.py" in text
    assert "-m perf backend/tests/test_replay_cli.py" in text
    assert re.search(r"python -m vws replay .*--offline-fixtures", text) is not None
