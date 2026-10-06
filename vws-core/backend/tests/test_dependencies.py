"""SEC-20/21: direct policy and compiled hash pin acceptance."""

from pathlib import Path

import pytest

from backend.core.dependencies import require_dependency_justifications, require_hash_lock
from backend.core.errors import ConfigurationError

PROJECT = Path(__file__).resolve().parents[2]


def test_SEC_21_every_direct_dependency_is_justified() -> None:
    require_dependency_justifications(PROJECT / "pyproject.toml", PROJECT / "docs/DEPENDENCIES.md")


def test_SEC_21_unlisted_dependency_fails(tmp_path: Path) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\ndependencies=["new-package==1"]\n[build-system]\nrequires=[]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        require_dependency_justifications(project, PROJECT / "docs/DEPENDENCIES.md")


def test_SEC_20_runtime_and_dev_locks_have_hashes() -> None:
    runtime = require_hash_lock(PROJECT / "requirements.lock")
    dev = require_hash_lock(PROJECT / "requirements-dev.lock")
    assert runtime.issubset(dev) and "keyring" in runtime and "pip-tools" in dev


@pytest.mark.parametrize(
    "record",
    [
        "pkg==1\n",
        "pkg>=1 --hash=sha256:" + "a" * 64,
        "pkg @ https://example.com/pkg\n",
        "--trusted-host example.com\n",
        "pkg==1 \\\n",
        "# empty\n",
    ],
)
def test_SEC_20_unhashed_or_unsafe_lock_fails(tmp_path: Path, record: str) -> None:
    lock = tmp_path / "bad.lock"
    lock.write_text(record, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        require_hash_lock(lock)


@pytest.mark.parametrize(
    "name", ["optuna", "hyperopt", "scikit-optimize", "scikit_optimize", "deap", "nevergrad"]
)
def test_SEC_21_optimizer_ban_cannot_be_justified_or_hidden_in_lock(
    tmp_path: Path, name: str
) -> None:
    canonical = name.replace("_", "-")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        f'[project]\ndependencies=["{name}==1"]\n[build-system]\nrequires=[]\n', encoding="utf-8"
    )
    policy = tmp_path / "policy.md"
    policy.write_text(f"- `{canonical}`: claimed evaluation purpose.\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="optimizer"):
        require_dependency_justifications(project, policy)
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"{name}==1 --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        require_hash_lock(lock)
