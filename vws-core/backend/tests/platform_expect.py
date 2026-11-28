"""Per-platform expectations for the LP tests: no markers, every test runs on every platform."""

import os
import sys
from collections.abc import Callable, Iterator

import pytest

from backend.ops import panic_flag
from backend.ops.private_dir import RuntimeDirError


def posix_uid() -> int:
    if sys.platform == "win32":
        raise AssertionError("POSIX-only helper")
    return os.getuid()


def windows_refuses(call: Callable[[], object], message: str) -> bool:
    """On win32 a Linux-only entry point refuses by name; the Linux assertions then end."""
    if sys.platform != "win32":
        return False
    with pytest.raises(RuntimeDirError, match=message):
        call()
    return True


@pytest.fixture(autouse=True)
def fresh_flag_state() -> Iterator[None]:
    """Test-only teardown of the process-retained flag (production never resets it).

    The Linux marker descriptor and the Windows named event are retained for the life of the
    process by design; without this every in-process real-flag test would see its predecessor's
    signal on Windows, where the event is process-wide rather than per temporary directory.
    """
    yield
    for retained in panic_flag._retained_files.values():
        retained.close()
    panic_flag._retained_files.clear()
    if sys.platform == "win32":
        api = panic_flag._kernel()
        for handle in panic_flag._retained_windows.values():
            api.CloseHandle(handle)
        panic_flag._retained_windows.clear()
