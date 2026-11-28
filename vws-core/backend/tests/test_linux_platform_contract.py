"""LP-01/LP-02: one platform module; Linux selects the flock/file backend; no silent fallback."""

import inspect
import sys
from pathlib import Path

import pytest

from backend.ops import platform_primitives
from backend.ops.platform_primitives import PlatformRefusal, backend_for, current_backend
from backend.ops.quiescence import OSSlots

PINNED_SIGNATURES = {
    "slots": "(directory: pathlib.Path) -> backend.ops.quiescence.SlotAdapter",
    "flag": "(directory: pathlib.Path) -> backend.ops.panic_flag.FlagAdapter",
    "runtime_lock": "(directory: pathlib.Path) -> backend.ops.process.ProcessLock",
    "panic_set": "(directory: pathlib.Path) -> bool",
    "panic_is_set": "(directory: pathlib.Path) -> bool",
}


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_LP01_interface_is_identical_on_every_supported_platform(platform: str) -> None:
    backend = backend_for(platform)
    public = {name for name in dir(backend) if not name.startswith("_")}
    assert public == {"kind", *PINNED_SIGNATURES}
    for name, expected in PINNED_SIGNATURES.items():
        assert str(inspect.signature(getattr(backend, name))) == expected


def test_LP02_linux_uses_the_flock_file_backend_and_windows_the_mutex_event_backend() -> None:
    assert backend_for("linux").kind == "flock-file"
    assert backend_for("win32").kind == "windows-mutex-event"


@pytest.mark.parametrize("platform", ["darwin", "freebsd13", "cygwin", "java", ""])
def test_LP02_unknown_platform_is_a_named_refusal_never_a_noop_backend(platform: str) -> None:
    with pytest.raises(PlatformRefusal, match=r"^Unsupported platform for broker primitives$"):
        backend_for(platform)


@pytest.mark.parametrize(
    ("platform", "kind"), [("linux", "flock-file"), ("win32", "windows-mutex-event")]
)
def test_LP02_current_backend_follows_sys_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str, kind: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    assert current_backend().kind == kind
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(PlatformRefusal):
        current_backend()


def test_LP02_linux_backend_returns_the_real_kernel_slot_adapter(tmp_path: Path) -> None:
    assert type(backend_for("linux").slots(tmp_path)) is OSSlots
    assert platform_primitives.PlatformRefusal.__mro__[1].__name__ == "ConfigurationError"
