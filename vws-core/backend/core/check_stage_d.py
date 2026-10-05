"""R-02/R-10: portable strict typing for every authored project Python file."""

import sys
from pathlib import Path

from mypy import api

from backend.core.errors import ConfigurationError
from backend.core.execution_policy import GENERATED_DIRECTORIES


def authored_type_files(project: Path) -> tuple[Path, ...]:
    """R-02: include new packages and scripts without maintaining a fixed list."""
    root = project.resolve(strict=True)
    sources: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            if path.is_symlink():
                raise ConfigurationError("typing source links cannot establish provenance")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise ConfigurationError("typing source escapes the project directory")
            if path.is_dir():
                if path.name not in GENERATED_DIRECTORIES and not path.name.endswith(".egg-info"):
                    pending.append(path)
            elif path.suffix == ".py":
                sources.append(resolved)
    if not sources:
        raise ConfigurationError("whole-project typing requires authored Python sources")
    return tuple(sorted(sources))


def main() -> int:
    """R-02: validate all source paths from either supported Git layout."""
    project = Path(__file__).resolve().parents[2]
    try:
        # VERIFY: https://mypy.readthedocs.io/en/stable/extending_mypy.html#integrating-mypy-into-another-python-application
        stdout, stderr, status = api.run(
            [
                "--strict",
                "--config-file",
                str(project / "pyproject.toml"),
                "--cache-dir",
                str(project / ".mypy_cache"),
                *(str(path) for path in authored_type_files(project)),
            ]
        )
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        return status
    except Exception:
        raise ConfigurationError("whole-project type checker could not start") from None


if __name__ == "__main__":
    raise SystemExit(main())
