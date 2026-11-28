"""Refuse-never-repair checks for directories that hold flock files: owner, 0700, direct, local FS."""

import ctypes
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from backend.core.errors import ConfigurationError

# statfs f_type values (linux/magic.h) for local filesystems that give flock its single-host
# semantics. Network, FUSE and unknown filesystems (including overlayfs) are refused.
ALLOWED_FILESYSTEMS = frozenset({0x01021994, 0xEF53, 0x58465342, 0x9123683E})


class RuntimeDirError(ConfigurationError):
    """The directory is unsafe; it is never repaired."""


class _StatFS(ctypes.Structure):
    # Only f_type is read; the buffer exceeds every Linux statfs layout.
    _fields_ = [("f_type", ctypes.c_long), ("rest", ctypes.c_ubyte * 120)]


def filesystem_magic(path: Path) -> int:
    if sys.platform == "win32":
        raise RuntimeDirError("Runtime directory filesystem checks are Linux-only")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.statfs.argtypes = [ctypes.c_char_p, ctypes.POINTER(_StatFS)]
    libc.statfs.restype = ctypes.c_int
    result = _StatFS()
    if libc.statfs(os.fsencode(path), ctypes.byref(result)) != 0:
        raise RuntimeDirError("Runtime directory filesystem is unverified")
    return int(result.f_type) & 0xFFFFFFFF


def _current_uid() -> int:
    if sys.platform == "win32":
        raise RuntimeDirError("Runtime directory ownership checks are Linux-only")
    return os.getuid()


def verify_owner_and_mode(path: Path, uid: Callable[[], int] | None = None) -> None:
    status = path.lstat()
    if not stat.S_ISDIR(status.st_mode):
        raise RuntimeDirError("Runtime directory must be a direct directory")
    if status.st_uid != (_current_uid if uid is None else uid)():
        raise RuntimeDirError("Runtime directory is not owned by this user")
    if stat.S_IMODE(status.st_mode) != 0o700:
        raise RuntimeDirError("Runtime directory must be private (mode 0700)")


def verify_private_directory(
    path: Path,
    statfs: Callable[[Path], int] | None = None,
    uid: Callable[[], int] | None = None,
) -> None:
    """POSIX only: direct directory, current owner, mode 0700, allow-listed local filesystem."""
    verify_owner_and_mode(path, uid)
    if (filesystem_magic if statfs is None else statfs)(path) not in ALLOWED_FILESYSTEMS:
        raise RuntimeDirError("Runtime directory is not on an allowed local filesystem")
