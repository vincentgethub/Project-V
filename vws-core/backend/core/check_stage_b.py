"""R-02/R-10: portable strict typing for completed Stages A and B."""

import sys
from pathlib import Path

from mypy import api

from backend.core.check_stage_a import TYPE_FILES as STAGE_A_TYPE_FILES
from backend.core.errors import ConfigurationError

TYPE_FILES = (
    *STAGE_A_TYPE_FILES,
    "backend/core/check_stage_b.py",
    "backend/domain/__init__.py",
    "backend/domain/models.py",
    "backend/domain/instruments.py",
    "backend/risk/__init__.py",
    "backend/risk/risk_cro.py",
    "backend/risk/boundary.py",
    "backend/tests/test_domain.py",
    "backend/tests/test_risk_cro.py",
    "backend/tests/test_risk_boundary.py",
    "backend/tests/test_stage_b_adversarial.py",
)


def main() -> int:
    """R-02: fixed source paths work from a nested or standalone Git checkout."""
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
        raise ConfigurationError("Stage A/B type checker could not start") from exc


if __name__ == "__main__":
    raise SystemExit(main())
