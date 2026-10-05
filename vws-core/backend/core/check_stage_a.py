"""R-02/R-10: portable Stage A strict-type gate for CI and Git-root hooks."""

import sys
from pathlib import Path

from mypy import api

from backend.core.errors import ConfigurationError

TYPE_FILES = (
    "backend/core/check_stage_a.py",
    "backend/core/config.py",
    "backend/core/clock.py",
    "backend/core/errors.py",
    "backend/core/money.py",
    "backend/core/logging.py",
    "backend/core/notifier.py",
    "backend/core/database.py",
    "backend/core/ledger.py",
    "backend/core/system_state.py",
    "backend/core/source_guard.py",
    "backend/core/execution_policy.py",
    "backend/data/market_calendar.py",
    "backend/tests/test_config_safety.py",
    "backend/tests/test_yaml_config.py",
    "backend/tests/test_money.py",
    "backend/tests/test_logging.py",
    "backend/tests/test_ledger.py",
    "backend/tests/test_research_ledger.py",
    "backend/tests/test_system_state.py",
    "backend/tests/test_market_calendar.py",
    "backend/tests/test_no_order_exec.py",
)


def main() -> int:
    """R-02: run the fixed check in its project, even from the parent Git root."""
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
        raise ConfigurationError("Stage A type checker could not start") from exc


if __name__ == "__main__":
    raise SystemExit(main())
