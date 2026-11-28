"""(vi) The data/ directory that holds runtime.lock gets the same owner/0700/local-FS check."""

import ast
import stat
import sys
from pathlib import Path

import pytest

from backend.core.errors import DataIntegrityError
from backend.ops import private_dir
from backend.ops.private_dir import RuntimeDirError
from backend.ops.process import ProcessLock
from backend.ops.quiescence import BrokerCoordination
from backend.tests.platform_expect import posix_uid
from backend.tests.test_security_cli import MemorySecrets, make_security_context
from backend.tests.test_security_cli import no_native_keyring as no_native_keyring
from vws import __main__ as cli
from vws import runtime_cli, security_cli

context = make_security_context
PRIVATE = r"^Runtime directory must be private \(mode 0700\)$"
NFS = 0x6969


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def locked(directory: Path) -> None:
    with ProcessLock(directory / "runtime.lock"):
        assert (directory / "runtime.lock").read_bytes() == b"0"


def test_group_readable_data_directory_is_refused_and_not_repaired(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o755)
    if sys.platform == "win32":
        locked(data)
        return
    with pytest.raises(RuntimeDirError, match=PRIVATE):
        locked(data)
    assert mode(data) == 0o755 and not (data / "runtime.lock").exists()


def test_private_data_directory_locks_on_every_platform(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    locked(data)


def test_other_lock_files_are_not_subject_to_the_host_directory_check(tmp_path: Path) -> None:
    other = tmp_path / "scratch"
    other.mkdir()
    other.chmod(0o755)
    with ProcessLock(other / "other.lock"):
        assert (other / "other.lock").read_bytes() == b"0"


def test_foreign_owner_and_network_filesystem_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    if sys.platform == "win32":
        locked(data)
        return
    monkeypatch.setattr(private_dir, "_current_uid", lambda: posix_uid() + 1)
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory is not owned by this user$"):
        locked(data)
    monkeypatch.undo()
    monkeypatch.setattr(private_dir, "filesystem_magic", lambda _path: NFS)
    with pytest.raises(
        RuntimeDirError, match=r"^Runtime directory is not on an allowed local filesystem$"
    ):
        locked(data)


def test_symlinked_data_directory_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "data"
    link.symlink_to(real)
    if sys.platform == "win32":
        return
    with pytest.raises(DataIntegrityError, match=r"^SEC-42: anchor destination must use"):
        locked(link)


def test_coordination_initialize_creates_data_private_on_linux(tmp_path: Path) -> None:
    BrokerCoordination(tmp_path).initialize()
    if sys.platform != "win32":
        assert mode(tmp_path / "data") == 0o700
        locked(tmp_path / "data")


def test_start_exits_1_with_the_directory_message_for_an_unsafe_data_directory(
    context: security_cli.SecurityContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    data.chmod(0o755)
    if sys.platform == "win32":
        return
    monkeypatch.setattr(security_cli, "PROJECT", tmp_path)
    monkeypatch.setattr(runtime_cli, "KeyringSecretStore", MemorySecrets)
    monkeypatch.setattr(runtime_cli, "load_host_settings", lambda *_args: context.settings)
    assert cli.main(["start"]) == 1
    assert capsys.readouterr().err == "Runtime directory must be private (mode 0700)\n"
    assert mode(data) == 0o755


def test_every_production_runtime_lock_site_goes_through_process_lock() -> None:
    root = Path(__file__).resolve().parents[2]
    sites: dict[str, bool] = {}
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if ".venv" in parts or "tests" in parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "runtime.lock" not in text:
            continue
        tree = ast.parse(text)
        sites["/".join(parts)] = any(
            isinstance(node, ast.Name) and node.id == "ProcessLock" for node in ast.walk(tree)
        )
    assert sites == {
        "backend/execution/coordinated_intent.py": True,
        "backend/execution/intent_resolution.py": True,
        "backend/ops/platform_primitives.py": True,
        "backend/ops/process.py": True,
        "vws/__main__.py": False,
        "vws/runtime_cli.py": True,
    }, "a new runtime.lock site must use ProcessLock (and so the data-directory check)"
