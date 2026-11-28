"""LP-10/LP-11/LP-12: private, local runtime directory; refuse, never repair."""

import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from backend.ops import platform_primitives
from backend.ops.platform_primitives import (
    RuntimeDirError,
    filesystem_magic,
    prepare_runtime_dir,
)

TMPFS, EXT4, XFS, BTRFS = 0x01021994, 0xEF53, 0x58465342, 0x9123683E
NFS, CIFS, FUSE, OVERLAY = 0x6969, 0xFF534D42, 0x65735546, 0x794C7630


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def fixed(value: int) -> Callable[[Path], int]:
    return lambda _path: value


def test_LP10_creates_directory_0700_owned_by_current_uid(tmp_path: Path) -> None:
    base = tmp_path / "run"
    base.mkdir(mode=0o700)
    runtime = prepare_runtime_dir({"XDG_RUNTIME_DIR": str(base)}, statfs=fixed(EXT4))
    assert runtime == base / "projectv"
    assert mode(runtime) == 0o700 and runtime.lstat().st_uid == os.getuid()
    assert prepare_runtime_dir({"XDG_RUNTIME_DIR": str(base)}, statfs=fixed(EXT4)) == runtime


def test_LP10_existing_0755_directory_is_refused_and_not_repaired(tmp_path: Path) -> None:
    runtime = tmp_path / "projectv"
    runtime.mkdir()
    runtime.chmod(0o755)
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory must be private \(mode 0700\)$"):
        prepare_runtime_dir({"XDG_RUNTIME_DIR": str(tmp_path)}, statfs=fixed(EXT4))
    assert mode(runtime) == 0o755


def test_LP10_directory_owned_by_another_user_is_refused(tmp_path: Path) -> None:
    runtime = tmp_path / "projectv"
    runtime.mkdir(mode=0o700)
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory is not owned by this user$"):
        prepare_runtime_dir(
            {"XDG_RUNTIME_DIR": str(tmp_path)},
            statfs=fixed(EXT4),
            uid=lambda: os.getuid() + 1,
        )


def test_LP10_symlink_and_file_in_place_of_the_directory_are_refused(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    base = tmp_path / "base"
    base.mkdir(mode=0o700)
    (base / "projectv").symlink_to(target)
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory must be a direct directory$"):
        prepare_runtime_dir({"XDG_RUNTIME_DIR": str(base)}, statfs=fixed(EXT4))
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    (other / "projectv").write_bytes(b"x")
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory must be a direct directory$"):
        prepare_runtime_dir({"XDG_RUNTIME_DIR": str(other)}, statfs=fixed(EXT4))


@pytest.mark.parametrize("magic", [TMPFS, EXT4, XFS, BTRFS])
def test_LP11_allowlisted_local_filesystems_start(tmp_path: Path, magic: int) -> None:
    runtime = prepare_runtime_dir({"XDG_RUNTIME_DIR": str(tmp_path)}, statfs=fixed(magic))
    assert runtime == tmp_path / "projectv"


@pytest.mark.parametrize("magic", [NFS, CIFS, FUSE, OVERLAY, 0])
def test_LP11_network_fuse_and_unknown_filesystems_refuse_to_start(
    tmp_path: Path, magic: int
) -> None:
    with pytest.raises(
        RuntimeDirError, match=r"^Runtime directory is not on an allowed local filesystem$"
    ):
        prepare_runtime_dir({"XDG_RUNTIME_DIR": str(tmp_path)}, statfs=fixed(magic))


def test_LP11_real_statfs_matches_the_kernel_report(tmp_path: Path) -> None:
    reported = subprocess.run(
        ["stat", "-f", "-c", "%t", str(tmp_path)], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert filesystem_magic(tmp_path) == int(reported, 16)


def test_LP11_statfs_failure_is_a_named_refusal(tmp_path: Path) -> None:
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory filesystem is unverified$"):
        filesystem_magic(tmp_path / "missing")


def test_LP12_unset_xdg_falls_back_to_a_private_projectv_owned_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    runtime = prepare_runtime_dir({"HOME": str(home)}, statfs=fixed(EXT4))
    assert runtime == home / ".projectv" / "run"
    assert mode(runtime) == 0o700 and mode(home / ".projectv") == 0o700
    empty = prepare_runtime_dir({"HOME": str(home), "XDG_RUNTIME_DIR": ""}, statfs=fixed(EXT4))
    assert empty == runtime


def test_LP12_no_xdg_and_no_home_is_refused_not_a_world_writable_tmp(tmp_path: Path) -> None:
    with pytest.raises(RuntimeDirError, match=r"^No private runtime directory base is available$"):
        prepare_runtime_dir({}, statfs=fixed(EXT4))
    with pytest.raises(RuntimeDirError, match=r"^No private runtime directory base is available$"):
        prepare_runtime_dir({"HOME": "relative/home"}, statfs=fixed(EXT4))


def test_LP12_relative_or_missing_xdg_base_is_refused(tmp_path: Path) -> None:
    with pytest.raises(
        RuntimeDirError, match=r"^XDG_RUNTIME_DIR must be an existing absolute path$"
    ):
        prepare_runtime_dir({"XDG_RUNTIME_DIR": "run/user"}, statfs=fixed(EXT4))
    with pytest.raises(
        RuntimeDirError, match=r"^XDG_RUNTIME_DIR must be an existing absolute path$"
    ):
        prepare_runtime_dir({"XDG_RUNTIME_DIR": str(tmp_path / "missing")}, statfs=fixed(EXT4))


def test_LP12_runtime_dir_preparation_is_linux_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory preparation is Linux-only$"):
        platform_primitives.prepare_runtime_dir({"XDG_RUNTIME_DIR": str(tmp_path)})


def test_LP12b_protected_path_component_is_refused_like_the_process_lock(tmp_path: Path) -> None:
    if sys.platform == "win32":
        with pytest.raises(RuntimeDirError, match=r"^Runtime directory preparation is Linux-only$"):
            prepare_runtime_dir({"HOME": str(tmp_path)})
        return
    home = tmp_path / "deploy"
    home.mkdir(mode=0o700)
    with pytest.raises(
        RuntimeDirError, match=r"^Runtime directory is a protected or indirect path$"
    ):
        prepare_runtime_dir({"HOME": str(home)}, statfs=fixed(EXT4))


def test_LP12b_symlinked_parent_is_refused_like_the_process_lock(tmp_path: Path) -> None:
    if sys.platform == "win32":
        return
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(
        RuntimeDirError, match=r"^Runtime directory is a protected or indirect path$"
    ):
        prepare_runtime_dir({"XDG_RUNTIME_DIR": str(link)}, statfs=fixed(EXT4))


def test_LP12b_dot_projectv_parent_is_verified_not_trusted(tmp_path: Path) -> None:
    if sys.platform == "win32":
        return
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    parent = home / ".projectv"
    parent.mkdir()
    parent.chmod(0o755)
    with pytest.raises(RuntimeDirError, match=r"^Runtime directory must be private \(mode 0700\)$"):
        prepare_runtime_dir({"HOME": str(home)}, statfs=fixed(EXT4))
    assert mode(parent) == 0o755
