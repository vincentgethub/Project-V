"""PF-04: exact host commands, no implicit credentials, bounded diagnostics."""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from backend.core.errors import DataIntegrityError
from vws.__main__ import main


@pytest.mark.parametrize("operation", ["scan", "replay"])
def test_PF_profile_runs_real_offline_engine_without_owner_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
) -> None:
    # Empty sentinel modules make any attempted owner composition import fail.
    monkeypatch.setitem(sys.modules, "vws.security_cli", ModuleType("vws.security_cli"))
    monkeypatch.setitem(sys.modules, "vws.runtime_cli", ModuleType("vws.runtime_cli"))
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("PAPER_TRADING", "false")
    output = tmp_path / "profiles"
    args = [
        "profile",
        operation,
        "--end",
        "2026-10-02",
        "--symbols",
        "NVDA",
        "--offline-fixtures",
        "--output",
        str(output),
    ]
    if operation == "replay":
        args.extend(["--start", "2026-09-01", "--workers", "1"])
    assert main(args) == 0
    captured = capsys.readouterr()
    assert "Profile top 20:" in captured.out and "SYNTHETIC" in captured.out
    assert len(tuple(output.glob("*.pstats"))) == 1
    text = next(output.glob("*.txt")).read_text(encoding="utf-8")
    assert "worker CPU is not included" in text and "not a performance gate" in text
    assert not tuple(tmp_path.glob("*.db"))


@pytest.mark.parametrize("case", ["dotenv", "protected", "unknown_symbol", "missing_history"])
def test_PF_profile_refuses_unavailable_or_unsafe_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    output = tmp_path / ("backend/profiles" if case == "protected" else "profiles")
    args = ["profile", "scan", "--end", "2026-10-02", "--symbols", "NVDA", "--output", str(output)]
    if case == "missing_history":
        args.extend(["--history", str(tmp_path / "missing")])
    else:
        args.append("--offline-fixtures")
    if case == "dotenv":
        args = ["--env-file", str(tmp_path / ".env"), *args]
    elif case == "unknown_symbol":
        args[args.index("NVDA")] = "UNKNOWN"
    assert main(args) == 1
    assert "Profile top 20:" not in capsys.readouterr().out
    assert not tuple(output.glob("*.pstats"))


def test_PF_failed_scan_never_publishes_successful_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vws import profile_cli

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise DataIntegrityError("PF-04: no completed data")

    monkeypatch.setattr(profile_cli, "scan", unavailable)
    args = [
        "profile",
        "scan",
        "--end",
        "2026-10-02",
        "--symbols",
        "NVDA",
        "--offline-fixtures",
        "--output",
        str(tmp_path / "profiles"),
    ]
    assert main(args) == 1
    assert not tuple((tmp_path / "profiles").glob("*.pstats"))
