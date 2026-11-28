"""Linux parity: one platform module with one interface for slots, runtime lock and panic flag."""

import ctypes
import os
import stat
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import ConfigurationError
from backend.ops.panic_flag import FlagAdapter, OSFlagAdapter, marker_signaled, panic_marker
from backend.ops.process import ProcessLock
from backend.ops.quiescence import OSSlots, SlotAdapter

# statfs f_type values (linux/magic.h) for local filesystems that give flock its single-host
# semantics. Network, FUSE and unknown filesystems (including overlayfs) are refused.
ALLOWED_FILESYSTEMS = frozenset({0x01021994, 0xEF53, 0x58465342, 0x9123683E})


class PlatformRefusal(ConfigurationError):
    """No silent fallback: an unsupported platform is a named refusal."""


class RuntimeDirError(ConfigurationError):
    """The runtime directory is unsafe; it is never repaired."""


@dataclass(frozen=True)
class PlatformBackend:
    """Same interface on every platform; `kind` names the OS primitive family."""

    kind: str

    def slots(self, directory: Path) -> SlotAdapter:
        return OSSlots(directory)

    def flag(self, directory: Path) -> FlagAdapter:
        return OSFlagAdapter(directory)

    def runtime_lock(self, directory: Path) -> ProcessLock:
        return ProcessLock(directory / "runtime.lock")

    def panic_set(self, directory: Path) -> bool:
        return OSFlagAdapter(directory).signal_if_present()

    def panic_is_set(self, directory: Path) -> bool:
        return marker_signaled(panic_marker(directory))


def backend_for(platform: str) -> PlatformBackend:
    if platform.startswith("linux"):
        return PlatformBackend("flock-file")
    if platform == "win32":
        return PlatformBackend("windows-mutex-event")
    raise PlatformRefusal("Unsupported platform for broker primitives")


def current_backend() -> PlatformBackend:
    return backend_for(sys.platform)


class _StatFS(ctypes.Structure):
    # Only f_type is read; the buffer exceeds every Linux statfs layout.
    _fields_ = [("f_type", ctypes.c_long), ("rest", ctypes.c_ubyte * 120)]


def filesystem_magic(path: Path) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.statfs.argtypes = [ctypes.c_char_p, ctypes.POINTER(_StatFS)]
    libc.statfs.restype = ctypes.c_int
    result = _StatFS()
    if libc.statfs(os.fsencode(path), ctypes.byref(result)) != 0:
        raise RuntimeDirError("Runtime directory filesystem is unverified")
    return int(result.f_type) & 0xFFFFFFFF


def _base(env: Mapping[str, str]) -> Path:
    xdg = env.get("XDG_RUNTIME_DIR", "")
    if xdg:
        base = Path(xdg)
        if not base.is_absolute() or not base.is_dir():
            raise RuntimeDirError("XDG_RUNTIME_DIR must be an existing absolute path")
        return base / "projectv"
    home = Path(env.get("HOME", ""))
    if not home.is_absolute():
        raise RuntimeDirError("No private runtime directory base is available")
    (home / ".projectv").mkdir(mode=0o700, exist_ok=True)
    return home / ".projectv" / "run"


def prepare_runtime_dir(
    env: Mapping[str, str],
    statfs: Callable[[Path], int] = filesystem_magic,
    uid: Callable[[], int] | None = None,
) -> Path:
    """Create or verify the private 0700 runtime directory; refuse, never repair."""
    if sys.platform == "win32":
        raise RuntimeDirError("Runtime directory preparation is Linux-only")
    owner = os.getuid if uid is None else uid
    path = _base(env)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    status = path.lstat()
    if not stat.S_ISDIR(status.st_mode):
        raise RuntimeDirError("Runtime directory must be a direct directory")
    if status.st_uid != owner():
        raise RuntimeDirError("Runtime directory is not owned by this user")
    if stat.S_IMODE(status.st_mode) != 0o700:
        raise RuntimeDirError("Runtime directory must be private (mode 0700)")
    if statfs(path) not in ALLOWED_FILESYSTEMS:
        raise RuntimeDirError("Runtime directory is not on an allowed local filesystem")
    return path
