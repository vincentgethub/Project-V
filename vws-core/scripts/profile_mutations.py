"""Observe pinned native mutmut without changing selection, limits or results."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Generator, Iterable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest


class Phases:
    """Measure existing pytest reports and fixture bodies; do not alter outcomes."""

    def __init__(self) -> None:
        self.seconds: defaultdict[str, float] = defaultdict(float)
        self.fixtures: defaultdict[str, float] = defaultdict(float)
        self.executed = 0
        self.record: Callable[[bool], None] | None = None

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef: Any, request: Any) -> Generator[Any, Any, Any]:
        started = time.perf_counter()
        try:
            return (yield)
        finally:
            self.fixtures[fixturedef.argname] += time.perf_counter() - started

    def pytest_runtest_logreport(self, report: Any) -> None:
        self.seconds[report.when] += report.duration
        if report.when == "call":
            self.executed += 1
        if report.when == "teardown" and self.record is not None:
            self.record(False)


def main() -> None:
    """Run the unchanged mutmut CLI with observation hooks only."""
    if version("mutmut") != "3.8.0":
        raise RuntimeError("Mutation profiling requires the pinned mutmut 3.8.0")
    import mutmut.__main__ as cli_module
    from mutmut.runners.harness import PytestRunner
    from mutmut.state import state
    from mutmut.workers.isolation import ForkRunner

    manifest = json.loads(
        Path(os.environ["RUNNER_TEMP"], "vws-mutation-shard.json").read_text(encoding="utf-8")
    )
    output = Path(os.environ["RUNNER_TEMP"], "vws-mutation-profile")
    output.mkdir(exist_ok=True)
    descriptor = os.dup(1)

    def emit(event: str, **values: Any) -> None:
        data = json.dumps({"event": event, "shard": manifest["shard"], **values}, ensure_ascii=True)
        os.write(descriptor, ("VWS_MUTATION_PROFILE " + data + "\n").encode("utf-8"))

    original_execute = PytestRunner.execute_pytest
    original_run = PytestRunner.run_tests
    original_submit = ForkRunner.submit
    original_wait = ForkRunner.wait_for_result
    current: Phases | None = None
    announced = False
    submitted: dict[str, int] = {}

    def execute(self: Any, params: list[str], **kwargs: Any) -> int:
        if current is not None:
            kwargs["plugins"] = [*kwargs.get("plugins", []), current]
        return int(original_execute(self, params, **kwargs))

    def run_tests(self: Any, *, mutant_name: str | None, tests: Iterable[str]) -> int:
        nonlocal current
        if mutant_name is None:
            return int(original_run(self, mutant_name=mutant_name, tests=tests))
        selected = list(tests)
        current = Phases()
        started = time.perf_counter()
        path = output / (mutant_name.encode("utf-8").hex() + ".jsonl")
        try:
            handle = path.open("w", encoding="utf-8")
        except OSError as error:
            emit("observation_error", id=mutant_name, kind=type(error).__name__)
            handle = None

        def record(complete: bool) -> None:
            if current is None or handle is None:
                return
            payload = {
                "id": mutant_name,
                "complete": complete,
                "tests": len(selected),
                "executed": current.executed,
                "wall": time.perf_counter() - started,
                "phases": dict(current.seconds),
                "fixtures": dict(current.fixtures),
            }
            try:
                handle.write(json.dumps(payload) + "\n")
                handle.flush()
            except OSError as error:
                # Observation failure cannot turn a survivor into a false kill.
                emit("observation_error", id=mutant_name, kind=type(error).__name__)
                current.record = None

        current.record = record
        try:
            return int(original_run(self, mutant_name=mutant_name, tests=selected))
        finally:
            record(True)
            if handle is not None:
                try:
                    handle.close()
                except OSError as error:
                    emit("observation_error", id=mutant_name, kind=type(error).__name__)
            current = None

    def submit(
        self: Any,
        mutant_name: str,
        tests: list[str],
        cpu_time_limit: int,
        estimated_time: float,
    ) -> None:
        nonlocal announced
        if not announced:
            counts = Counter(key.rsplit("__mutmut_", 1)[0] for key in manifest["selected"])
            for function, count in sorted(counts.items()):
                emit(
                    "mapping",
                    function=function,
                    mutants=count,
                    tests=len(state().tests_by_mangled_function_name.get(function, set())),
                )
            emit("workers", max_workers=self.max_workers, cpu_count=os.cpu_count())
            announced = True
        submitted[mutant_name] = len(tests)
        try:
            (output / (mutant_name.encode("utf-8").hex() + ".jsonl")).unlink(missing_ok=True)
        except OSError as error:
            emit("observation_error", id=mutant_name, kind=type(error).__name__)
        original_submit(self, mutant_name, tests, cpu_time_limit, estimated_time)

    def wait(self: Any, timeout: float | None = None) -> Any:
        result = original_wait(self, timeout)
        path = output / (result.mutant_name.encode("utf-8").hex() + ".jsonl")
        detail = {}
        try:
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            for line in reversed(lines):
                try:
                    detail = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        except OSError as error:
            # A CPU limit may interrupt a metrics write. Keep the native result.
            detail = {"unavailable": type(error).__name__}
        emit(
            "result",
            id=result.mutant_name,
            exit_code=result.exit_code,
            parent_wall=result.duration,
            mapped_tests=submitted.get(result.mutant_name),
            detail=detail,
        )
        return result

    arguments = sys.argv[1:]
    sys.argv = ["mutmut", "run", *arguments]
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(PytestRunner, "execute_pytest", execute)
            patch.setattr(PytestRunner, "run_tests", run_tests)
            patch.setattr(ForkRunner, "submit", submit)
            patch.setattr(ForkRunner, "wait_for_result", wait)
            cli_module.cli()
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    main()
