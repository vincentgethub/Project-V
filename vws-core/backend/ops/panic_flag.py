"""G-q rev E: session-local manual-reset panic flag adapter."""

import ctypes
import os
import sys
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from backend.core.errors import ConfigurationError


class PanicFlagError(ConfigurationError):
    """Only static operation names, never OS or broker free text."""


class FlagHandle(Protocol):
    def signaled(self) -> bool: ...

    def close(self) -> None: ...


class FlagAdapter(Protocol):
    def open_window(self) -> FlagHandle: ...

    def signal_if_present(self) -> bool: ...


NAME = "Local\\ProjectV-panic-seen"
_retained_windows: dict[str, int] = {}
_retained_files: dict[Path, BinaryIO] = {}


def _kernel() -> ctypes.WinDLL:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    api.CreateEventW.restype = ctypes.c_void_p
    api.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    api.OpenEventW.restype = ctypes.c_void_p
    api.SetEvent.argtypes = [ctypes.c_void_p]
    api.SetEvent.restype = ctypes.c_int
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.WaitForSingleObject.restype = ctypes.c_uint32
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int
    return api


class WindowsFlagHandle:
    def __init__(self, handle: int) -> None:
        self.handle = handle

    def signaled(self) -> bool:
        state = _kernel().WaitForSingleObject(self.handle, 0)
        if state == 0:
            return True
        if state == 0x102:
            return False
        raise PanicFlagError("Panic flag read failed")

    def close(self) -> None:
        if not _kernel().CloseHandle(self.handle):
            raise PanicFlagError("Panic flag close failed")


class FlockAPI(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, flags: int) -> None: ...


def _flock() -> FlockAPI:
    import fcntl

    return cast(FlockAPI, fcntl)


class FileFlagHandle:
    def __init__(self, file: BinaryIO, marker: Path) -> None:
        self.file, self.marker = file, marker

    def signaled(self) -> bool:
        if self.marker.is_symlink():
            raise PanicFlagError("Panic flag marker is not direct")
        try:
            data = self.marker.read_bytes()
        except FileNotFoundError:
            return False
        if data != b"1":
            raise PanicFlagError("Panic flag marker is corrupt")
        return True

    def close(self) -> None:
        try:
            api = _flock()
            api.flock(self.file.fileno(), api.LOCK_UN)
        finally:
            self.file.close()


class OSFlagAdapter:
    """Never resets signals; panic makes no blocking wait call."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def open_window(self) -> FlagHandle:
        if sys.platform == "win32":
            handle = _kernel().CreateEventW(None, True, False, NAME)
            if not handle:
                raise PanicFlagError("Panic flag creation failed")
            return WindowsFlagHandle(handle)
        if self.directory.is_symlink():
            raise PanicFlagError("Panic flag directory is not direct")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "panic-window"
        if path.is_symlink():
            raise PanicFlagError("Panic flag window is not direct")
        file = path.open("a+b")
        locked = False
        try:
            api = _flock()
            api.flock(file.fileno(), api.LOCK_EX | api.LOCK_NB)
            locked = True
        finally:
            if not locked:
                file.close()
        return FileFlagHandle(file, self.directory / "panic-seen")

    def signal_if_present(self) -> bool:
        """Legacy method name: rev F ALWAYS creates/opens, sets and retains."""
        if sys.platform == "win32":
            handle = _retained_windows.get(NAME)
            fresh = handle is None
            if handle is None:
                handle = _kernel().CreateEventW(None, True, False, NAME)
                if not handle:
                    raise PanicFlagError("Panic flag creation failed")
            if not _kernel().SetEvent(handle):
                if fresh:
                    _kernel().CloseHandle(handle)
                raise PanicFlagError("Panic flag signal failed")
            _retained_windows[NAME] = handle
            return True
        if self.directory.is_symlink():
            raise PanicFlagError("Panic flag directory is not direct")
        self.directory.mkdir(parents=True, exist_ok=True)
        marker = self.directory / "panic-seen"
        if marker.is_symlink():
            raise PanicFlagError("Panic flag marker is not direct")
        if marker not in _retained_files:
            try:
                retained = marker.open("x+b")
            except FileExistsError as exc:
                retained = marker.open("r+b")
                if retained.read() != b"1":
                    retained.close()
                    raise PanicFlagError("Panic flag marker is corrupt") from exc
            else:
                retained.write(b"1")
                retained.flush()
                os.fsync(retained.fileno())
            _retained_files[marker] = retained
        return True
