"""SEC-22: explicit host audit; proof binds both current hash-pinned locks."""

import hashlib
import json
import re

# Explicit host maintenance runs one fixed, hash-installed audit tool, without a shell.
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from pathlib import Path

from packaging.requirements import Requirement

from backend.core.database import SecurityEvent
from backend.core.dependencies import require_hash_lock
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.ledger import Ledger

LOCKS = ("requirements.lock", "requirements-dev.lock")


def lock_hashes(project: Path) -> dict[str, str]:
    result = {}
    for name in LOCKS:
        path = project / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_097_152:
            raise ConfigurationError("Dependency audit locks must be bounded direct files")
        require_hash_lock(path)
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def active_pins(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^[A-Za-z0-9_.-]+==", line):
            requirement = Requirement(line.split("--hash=", 1)[0].rstrip(" \\"))
            if requirement.marker is None or requirement.marker.evaluate():
                name = re.sub(r"[-_.]+", "-", requirement.name).lower()
                result[name] = next(iter(requirement.specifier)).version
    return result


def run_lock(path: Path) -> bytes:
    # Explicit host maintenance, never invoked by a running research worker.
    # VERIFY: pinned pip-audit --help: JSON stdout, strict collection, no fixes.
    # Fixed interpreter/module/arguments; no user command or shell is accepted.
    result = subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "pip_audit",
            "-r",
            str(path),
            "--no-deps",
            "--disable-pip",
            "--strict",
            "--format",
            "json",
            "--progress-spinner",
            "off",
            "--timeout",
            "15",
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > 2_097_152:
        raise ProviderError("Dependency audit failed or was unavailable; no clean result recorded")
    return result.stdout


def audit(
    project: Path, ledger: Ledger, operator: str, *, runner: Callable[[Path], bytes] = run_lock
) -> dict[str, int]:
    if (
        not isinstance(operator, str)
        or not 1 <= len(operator.strip()) <= 128
        or not operator.isprintable()
    ):
        raise ConfigurationError("Dependency audit requires a bounded named host operator")
    ledger.verify_chain()
    hashes = lock_hashes(project)
    counts: dict[str, int] = {}
    try:
        for name in LOCKS:
            raw = runner(project / name)
            if len(raw) > 2_097_152:
                raise DataIntegrityError("Dependency audit output exceeded its bound")
            payload = json.loads(raw)
            rows = payload["dependencies"]
            expected = active_pins(project / name)
            if not isinstance(rows, list) or len(rows) != len(expected):
                raise DataIntegrityError("Dependency audit did not cover every active lock pin")
            observed: dict[str, str] = {}
            for row in rows:
                key = re.sub(r"[-_.]+", "-", row["name"]).lower()
                if key in observed or row.get("vulns") != [] or "skip_reason" in row:
                    raise DataIntegrityError(
                        "Dependency audit contains skipped, duplicate or vulnerable pins"
                    )
                observed[key] = row["version"]
            if observed != expected:
                raise DataIntegrityError(
                    "Dependency audit inventory differs from the selected lock"
                )
            counts[name] = len(observed)
        if lock_hashes(project) != hashes:
            raise DataIntegrityError("Dependency locks changed during the audit")
    except Exception as error:
        ledger.append(
            SecurityEvent,
            kind="PIP_AUDIT_FAILED",
            detail={
                "operator": operator.strip(),
                "lock_hashes": hashes,
                "error_type": type(error).__name__,
            },
        )
        if isinstance(error, (ConfigurationError, DataIntegrityError, ProviderError)):
            raise
        raise DataIntegrityError("Dependency audit proof could not be verified") from None
    ledger.append(
        SecurityEvent,
        kind="PIP_AUDIT_PASSED",
        detail={
            "operator": operator.strip(),
            "lock_hashes": hashes,
            "counts": counts,
        },
    )
    return counts
