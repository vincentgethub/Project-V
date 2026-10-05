"""R-02/R-10: portable strict typing for completed Stages A through D."""

import sys
from pathlib import Path

from mypy import api

from backend.core.check_stage_c import TYPE_FILES as STAGE_C_TYPE_FILES
from backend.core.errors import ConfigurationError

TYPE_FILES = (
    *STAGE_C_TYPE_FILES,
    "backend/core/check_stage_d.py",
    "backend/risk/portfolio_marks.py",
    "backend/data/data_layer.py",
    "backend/data/broker_state.py",
    "backend/data/liquidity.py",
    "backend/data/boundary.py",
    "backend/agents/__init__.py",
    "backend/agents/indicators.py",
    "backend/agents/scanner.py",
    "scripts/plaid_sandbox_token.py",
    "backend/tests/test_data_layer.py",
    "backend/tests/test_broker_state.py",
    "backend/tests/test_liquidity.py",
    "backend/tests/test_read_boundary.py",
    "backend/tests/test_indicators.py",
    "backend/tests/test_scanner.py",
    "backend/tests/test_portfolio_marks.py",
    "backend/tests/test_progress.py",
    "vws/__init__.py",
    "vws/__main__.py",
    "vws/progress.py",
)


def main() -> int:
    """R-02: validate fixed source paths from either supported Git layout."""
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
        raise ConfigurationError("Stage A-D type checker could not start") from exc


if __name__ == "__main__":
    raise SystemExit(main())
