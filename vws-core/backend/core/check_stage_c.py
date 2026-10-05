"""R-02/R-10: portable strict typing for completed Stages A through C."""

import sys
from pathlib import Path

from mypy import api

from backend.core.check_stage_b import TYPE_FILES as STAGE_B_TYPE_FILES
from backend.core.errors import ConfigurationError

TYPE_FILES = (
    *STAGE_B_TYPE_FILES,
    "backend/core/check_stage_c.py",
    "backend/domain/compliance_models.py",
    "backend/risk/compliance.py",
    "backend/risk/wash_sales.py",
    "backend/risk/compliance_boundary.py",
    "backend/tests/test_compliance.py",
    "backend/tests/test_wash_sales.py",
    "backend/tests/test_compliance_boundary.py",
    "backend/tests/test_stage_c_adversarial.py",
)


def main() -> int:
    """R-02: fixed verified source paths work from either Git layout."""
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
                *(str(project / path) for path in TYPE_FILES),
            ]
        )
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        return status
    except Exception as exc:
        raise ConfigurationError("Stage A-C type checker could not start") from exc


if __name__ == "__main__":
    raise SystemExit(main())
