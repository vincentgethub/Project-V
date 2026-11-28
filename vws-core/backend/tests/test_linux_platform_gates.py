"""Windows-only kernel code is reachable only behind sys.platform == "win32"."""

import sys

import pytest

from backend.ops import panic_flag
from backend.ops.panic_flag import PanicFlagError
from backend.ops.quiescence import QuiescenceError, WindowsLease, _owned_mutexes


def test_panic_kernel_api_is_refused_off_windows() -> None:
    with pytest.raises(PanicFlagError, match=r"^Panic flag kernel API is Windows-only$"):
        panic_flag._kernel()


def test_broker_mutex_release_is_refused_off_windows_and_state_is_untouched() -> None:
    lease = WindowsLease(1, "slot-0")
    with pytest.raises(QuiescenceError, match=r"^Broker mutex release is Windows-only$"):
        lease.release()
    assert lease.active is True and "slot-0" not in _owned_mutexes


def test_windows_platform_reaches_the_kernel_loader_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On win32 the guards are no-ops: both paths go straight to ctypes.WinDLL."""
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(AttributeError, match="WinDLL"):
        panic_flag._kernel()
    with pytest.raises(AttributeError, match="WinDLL"):
        WindowsLease(1, "slot-0").release()
