"""SEC-20/21: hash locks and documented direct dependencies are checked data."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from backend.core.errors import ConfigurationError

PROHIBITED_OPTIMIZERS = frozenset({"optuna", "hyperopt", "scikit-optimize", "deap", "nevergrad"})


def _refuse_optimizers(names: frozenset[str]) -> None:
    """Amendment 05: neither justification nor transitive installation permits optimization."""
    if names & PROHIBITED_OPTIMIZERS:
        raise ConfigurationError("SEC-21: optimizer dependencies are prohibited")


def dependency_names(project: Path) -> frozenset[str]:
    """SEC-21: include runtime, development and build dependencies."""
    try:
        data = tomllib.loads(project.read_text(encoding="utf-8"))
        requirements = list(data["project"]["dependencies"])
        for entries in data["project"].get("optional-dependencies", {}).values():
            requirements.extend(entries)
        requirements.extend(data["build-system"]["requires"])
        names: set[str] = set()
        for item in requirements:
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", item)
            if match is None:
                raise ValueError("malformed direct requirement")
            names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
        return frozenset(names)
    except Exception:
        raise ConfigurationError("SEC-21: direct dependency inventory is unverifiable") from None


def require_dependency_justifications(project: Path, policy: Path) -> None:
    """SEC-21: an unlisted dependency fails, including build/dev additions."""
    try:
        text = policy.read_text(encoding="utf-8")
        listed = frozenset(re.findall(r"(?m)^- `([a-z0-9-]+)`: .+", text))
        names = dependency_names(project)
        _refuse_optimizers(names)
        if names != listed:
            raise ConfigurationError("SEC-21: direct dependency policy and metadata differ")
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("SEC-21: dependency policy could not be read") from None


def require_hash_lock(path: Path) -> frozenset[str]:
    """SEC-20: all compiled requirement records need exact pins and SHA256."""
    try:
        text = path.read_text(encoding="utf-8")
        records: list[str] = []
        current = ""
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("--") and not line.startswith("--hash="):
                raise ValueError("unapproved lock option")
            if line.endswith("\\"):
                current += line[:-1] + " "
            else:
                records.append(current + line)
                current = ""
        if current or not records:
            raise ValueError("incomplete or empty lock")
        names: set[str] = set()
        for record in records:
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)", record)
            hashes = re.findall(r"--hash=sha256:([a-f0-9]{64})(?:\s|$)", record)
            if match is None or not hashes or "://" in record:
                raise ValueError("every lock record requires an exact pin and SHA256")
            names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
        result = frozenset(names)
        _refuse_optimizers(result)
        return result
    except Exception:
        raise ConfigurationError("SEC-20: dependency lock is not fully hash pinned") from None
