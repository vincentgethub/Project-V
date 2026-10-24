"""OPS-06: record fresh pytest failure causes without changing test execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest
from _pytest.outcomes import Failed
from mutmut.mutation.trampoline import get_mutant_under_test


def sanitized_frames(excinfo: pytest.ExceptionInfo[BaseException]) -> list[dict[str, Any]]:
    """Keep code locations only: never messages, source lines, locals or absolute paths."""
    roots = (Path(__file__).resolve().parents[1], Path.cwd().resolve())
    frames = []
    entries = list(excinfo.traceback)
    error = excinfo.value
    seen = {id(error)}
    while True:
        cause = error.__cause__ or error.__context__
        if cause is None or id(cause) in seen or cause.__traceback__ is None:
            break
        seen.add(id(cause))
        entries.extend(pytest.ExceptionInfo.from_exception(cause).traceback)
        error = cause
    for entry in entries:
        path = Path(str(entry.path)).resolve()
        filename, origin = "<external>", "external"
        for root in roots:
            if path.is_relative_to(root):
                relative = path.relative_to(root).as_posix()
                if relative.startswith(("backend/", "scripts/", "vws/")) and path.is_file():
                    filename = relative
                    origin = (
                        "test-harness"
                        if relative.startswith("backend/tests/")
                        else "runner"
                        if relative.startswith("scripts/")
                        else "production"
                    )
                    break
        name = entry.name if filename != "<external>" else "<external>"
        if not re.fullmatch(r"[\w.<>]+", name):
            name = "<redacted>"
        frames.append(
            {"file": filename, "function": name, "line": entry.lineno + 1, "origin": origin}
        )
    return frames


@dataclass(eq=False)
class Audit:
    destination: Path
    mutant: str
    collected_only: bool
    calls: int = 0
    collected: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    panic_cases: list[dict[str, str]] = field(default_factory=list)
    finished: bool = False
    exit_status: int | None = None
    started: float = field(default_factory=perf_counter)
    started_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    phase_seconds: dict[str, float] = field(default_factory=dict)

    def pytest_internalerror(
        self, excrepr: Any, excinfo: pytest.ExceptionInfo[BaseException]
    ) -> None:
        self.failures.append(
            {
                "test": "<internal>",
                "phase": "internal",
                "type": type(excinfo.value).__name__,
                "kind": "crash",
                "frames": sanitized_frames(excinfo),
            }
        )
        self.write()

    def write(self) -> None:
        payload = {
            "mutant": self.mutant,
            "collect_only": self.collected_only,
            "calls": self.calls,
            "collected": self.collected,
            "failures": self.failures,
            "panic_cases": self.panic_cases,
            "finished": self.finished,
            "exit_status": self.exit_status,
            "started_utc": self.started_utc,
            "duration_seconds": perf_counter() - self.started,
            "phase_seconds": self.phase_seconds,
        }
        temporary = self.destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(self.destination)


KEY = pytest.StashKey[Audit]()


def pytest_configure(config: pytest.Config) -> None:
    directory = os.environ.get("VWS_MUTATION_AUDIT_DIR")
    if not directory:
        return
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    mutant = get_mutant_under_test()
    tag = hashlib.sha256(mutant.encode("utf-8")).hexdigest()
    record = Audit(
        root / (tag + "-" + str(os.getpid()) + ".json"),
        mutant,
        bool(config.getoption("collectonly")),
    )
    config.stash[KEY] = record
    config.pluginmanager.register(record, "vws-internal-error-audit")
    record.write()


def pytest_collection_finish(session: pytest.Session) -> None:
    if KEY in session.config.stash:
        record = session.config.stash[KEY]
        record.collected = len(session.items)
        record.write()


def pytest_exception_interact(
    node: pytest.Item | pytest.Collector,
    call: pytest.CallInfo[Any],
    report: pytest.TestReport | pytest.CollectReport,
) -> None:
    if isinstance(report, pytest.CollectReport) and KEY in node.config.stash:
        record = node.config.stash[KEY]
        record.failures.append(
            {
                "test": "<collection>",
                "phase": "collection",
                "type": type(call.excinfo.value).__name__ if call.excinfo else "Unknown",
                "kind": "crash",
                "frames": sanitized_frames(call.excinfo) if call.excinfo else [],
            }
        )
        record.write()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[Any]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if KEY not in item.config.stash:
        return report
    record = item.config.stash[KEY]
    record.phase_seconds[call.when] = record.phase_seconds.get(call.when, 0.0) + call.duration
    panic_case = call.when == "call" and "test_SEC_73" in item.nodeid
    if call.when == "call":
        record.calls += 1
        if panic_case:
            record.panic_cases.append({"test": item.nodeid, "outcome": report.outcome})
    if report.failed:
        error = call.excinfo.value if call.excinfo else None
        kind = (
            "assertion"
            if call.when == "call" and isinstance(error, (AssertionError, Failed))
            else "crash"
        )
        record.failures.append(
            {
                "test": item.nodeid,
                "phase": call.when,
                "type": type(error).__name__,
                "kind": kind,
                "frames": sanitized_frames(call.excinfo) if call.excinfo else [],
            }
        )
    if report.failed or panic_case:
        record.write()
    return report


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if KEY not in session.config.stash:
        return
    record = session.config.stash[KEY]
    record.finished = True
    record.exit_status = int(exitstatus)
    record.write()


def audit_results(
    directory: Path, records: dict[str, str], fingerprints: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runs: list[dict[str, Any]] = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))
    ]
    details: list[dict[str, Any]] = []
    for mutant, status in records.items():
        evidence = [row for row in runs if row["mutant"] == mutant and not row["collect_only"]]
        failures = [failure for row in evidence for failure in row["failures"]]
        if status == "killed":
            complete = bool(evidence) and all(
                row["finished"] and row["exit_status"] == 1 for row in evidence
            )
            if not complete or any(row["kind"] == "crash" for row in failures):
                reason = "crash"
            elif any(row["kind"] == "assertion" for row in failures):
                reason = "assertion"
            else:
                reason = "suspicious"
        elif status == "timeout":
            reason = "timeout"
        elif status in {"segfault", "check was interrupted by user"}:
            reason = "crash"
        elif status == "suspicious":
            reason = "suspicious"
        else:
            reason = status
        details.append(
            {
                "id": mutant,
                "fingerprint": fingerprints[mutant],
                "native_status": status,
                "reason": reason,
                "tests_collected": max((row["collected"] for row in evidence), default=0),
                "tests_run": max((row["calls"] for row in evidence), default=0),
                "failures": failures,
                "pytest_seconds": max(
                    (row.get("duration_seconds", 0.0) for row in evidence), default=0.0
                ),
            }
        )
    clean = [
        row
        for row in runs
        if "__mutmut_" not in row["mutant"]
        and row["mutant"] != "fail"
        and not row["collect_only"]
        and row["calls"]
    ]
    return details, clean
