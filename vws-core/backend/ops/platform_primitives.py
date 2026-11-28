"""Linux parity: one platform module with one interface for slots, runtime lock and panic flag."""

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.ops.anchors import controlled_path
from backend.ops.panic_flag import FlagAdapter, OSFlagAdapter, marker_signaled, panic_marker
from backend.ops.private_dir import (
    ALLOWED_FILESYSTEMS,
    RuntimeDirError,
    filesystem_magic,
    verify_owner_and_mode,
    verify_private_directory,
)
from backend.ops.process import ProcessLock
from backend.ops.quiescence import OSSlots, SlotAdapter

__all__ = [
    "ALLOWED_FILESYSTEMS",
    "PlatformBackend",
    "PlatformRefusal",
    "RuntimeDirError",
    "backend_for",
    "current_backend",
    "filesystem_magic",
    "prepare_runtime_dir",
]


class PlatformRefusal(ConfigurationError):
    """No silent fallback: an unsupported platform is a named refusal."""


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
        if self.kind == "windows-mutex-event":
            handle = OSFlagAdapter(directory).open_window()
            try:
                return handle.signaled()
            finally:
                handle.close()
        return marker_signaled(panic_marker(directory))


def backend_for(platform: str) -> PlatformBackend:
    if platform.startswith("linux"):
        return PlatformBackend("flock-file")
    if platform == "win32":
        return PlatformBackend("windows-mutex-event")
    raise PlatformRefusal("Unsupported platform for broker primitives")


def current_backend() -> PlatformBackend:
    return backend_for(sys.platform)


def _base(env: Mapping[str, str], uid: Callable[[], int] | None) -> Path:
    xdg = env.get("XDG_RUNTIME_DIR", "")
    if xdg:
        base = Path(xdg)
        if not base.is_absolute() or not base.is_dir():
            raise RuntimeDirError("XDG_RUNTIME_DIR must be an existing absolute path")
        return base / "projectv"
    home = Path(env.get("HOME", ""))
    if not home.is_absolute():
        raise RuntimeDirError("No private runtime directory base is available")
    parent = home / ".projectv"
    try:
        parent.mkdir(mode=0o700)
    except FileExistsError:
        pass
    verify_owner_and_mode(parent, uid)
    return parent / "run"


def prepare_runtime_dir(
    env: Mapping[str, str],
    statfs: Callable[[Path], int] | None = None,
    uid: Callable[[], int] | None = None,
) -> Path:
    """Create or verify the private 0700 runtime directory; refuse, never repair."""
    if sys.platform == "win32":
        raise RuntimeDirError("Runtime directory preparation is Linux-only")
    path = _base(env, uid)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    verify_private_directory(path, statfs, uid)
    try:
        controlled_path(path / "runtime.lock")
    except DataIntegrityError:
        raise RuntimeDirError("Runtime directory is a protected or indirect path") from None
    return path
