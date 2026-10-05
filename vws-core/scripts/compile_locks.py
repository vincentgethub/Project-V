"""SEC-20: reproducible Windows/Linux union locks using pinned pip-tools.

Subprocess execution is limited to the current Python interpreter and the
pinned pip-tools module, with no shell or arbitrary executable input.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from backend.core.dependencies import require_dependency_justifications, require_hash_lock
from backend.core.errors import ConfigurationError

_PIN = re.compile(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)")
_PLATFORM_PACKAGES = frozenset({"secretstorage", "jeepney"})


def _pins(path: Path) -> dict[str, str]:
    require_hash_lock(path)
    return {
        re.sub(r"[-_.]+", "-", match.group(1)).lower(): match.group(2)
        for match in _PIN.finditer(path.read_text(encoding="utf-8"))
    }


def _compiler_project(project: Path) -> str:
    """SEC-20: augment only temporary compiler metadata, never app metadata."""
    data: dict[str, Any] = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    platform_requirements = [
        line.strip()
        for line in (project / "requirements-platform.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if set(platform_requirements) != {"SecretStorage>=3.2", "jeepney>=0.4.2"}:
        raise ConfigurationError("SEC-20: platform closure input requires an explicit review")
    metadata = data["project"]
    lines = [
        "[build-system]",
        f"requires = {json.dumps(data['build-system']['requires'])}",
        f"build-backend = {json.dumps(data['build-system']['build-backend'])}",
        "",
        "[project]",
        f"name = {json.dumps(metadata['name'])}",
        f"version = {json.dumps(metadata['version'])}",
        f"requires-python = {json.dumps(metadata['requires-python'])}",
        f"dependencies = {json.dumps([*metadata['dependencies'], *platform_requirements])}",
        "",
        "[project.optional-dependencies]",
    ]
    for name, requirements in metadata.get("optional-dependencies", {}).items():
        lines.append(f"{json.dumps(name)} = {json.dumps(requirements)}")
    return "\n".join(lines) + "\n"


def _compile(
    source: Path, target: Path, constraints: tuple[Path, ...], *, development: bool
) -> None:
    arguments = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        str(source),
        "--no-config",
        "--no-build-isolation",
        "--all-build-deps",
        "--generate-hashes",
        "--allow-unsafe",
        "--strip-extras",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
        "--resolver=backtracking",
        f"--output-file={target}",
        "--pip-args=--timeout 30 --retries 2",
        "--quiet",
    ]
    arguments.extend(f"--constraint={path}" for path in constraints)
    if development:
        arguments.append("--extra=dev")
    environment = os.environ.copy()
    environment["CUSTOM_COMPILE_COMMAND"] = "python -m scripts.compile_locks"
    # Fixed interpreter/module, validated local paths and no shell.
    completed = subprocess.run(  # nosec B603
        arguments,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        # Resolver errors can contain credential-bearing package-index URLs.
        raise ConfigurationError("SEC-20: pinned lock compilation failed; no lock was replaced")


def main() -> int:
    """SEC-20: retain every existing pin and publish only validated hash locks."""
    project = Path(__file__).resolve().parents[1]
    try:
        require_dependency_justifications(
            project / "pyproject.toml", project / "docs/DEPENDENCIES.md"
        )
        runtime = project / "requirements.lock"
        development = project / "requirements-dev.lock"
        prior_runtime, prior_dev = _pins(runtime), _pins(development)
        with tempfile.TemporaryDirectory(prefix="vws-lock-compile-") as scratch:
            temporary = Path(scratch)
            source = temporary / "pyproject.toml"
            source.write_text(_compiler_project(project), encoding="utf-8")
            compiled_runtime = temporary / "requirements.lock"
            compiled_dev = temporary / "requirements-dev.lock"
            # pip-tools can reuse already verified release hashes for old pins.
            compiled_runtime.write_bytes(runtime.read_bytes())
            compiled_dev.write_bytes(development.read_bytes())
            _compile(source, compiled_runtime, (runtime, development), development=False)
            _compile(
                source, compiled_dev, (runtime, development, compiled_runtime), development=True
            )
            runtime_pins, dev_pins = _pins(compiled_runtime), _pins(compiled_dev)
            for old, new in ((prior_runtime, runtime_pins), (prior_dev, dev_pins)):
                if not old.items() <= new.items() or not _PLATFORM_PACKAGES <= new.keys():
                    raise ConfigurationError(
                        "SEC-20: compiled lock changed or omitted an existing pin"
                    )
            if not runtime_pins.items() <= dev_pins.items():
                raise ConfigurationError("SEC-20: runtime and development lock pins conflict")
            runtime.write_bytes(compiled_runtime.read_bytes())
            development.write_bytes(compiled_dev.read_bytes())
        print(
            f"Hash locks compiled: {len(runtime_pins)} runtime, {len(dev_pins)} development records"
        )
        return 0
    except Exception:
        print("SEC-20: hash lock compilation failed; inspect the compiler inputs", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
