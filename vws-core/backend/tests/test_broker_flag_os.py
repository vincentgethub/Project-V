"""Actual OS primitives; helpers exit normally without releases or signals."""

import subprocess
import sys
from pathlib import Path

from backend.ops.panic_flag import OSFlagAdapter
from backend.ops.quiescence import BrokerCoordination, OSSlots


def child_creation_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def child(code: str, path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-B", "-c", code, str(path)],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=child_creation_flags(),
    )


def test_Q7_kernel_slot_releases_when_owner_process_exits_without_release(tmp_path: Path) -> None:
    coordination = BrokerCoordination(tmp_path)
    coordination.initialize()
    process = child(
        "from pathlib import Path; import sys; "
        "from backend.ops.quiescence import OSSlots; "
        "lease=OSSlots(Path(sys.argv[1])).acquire('slot-6'); "
        "print('HELD' if lease else 'BUSY',flush=True); sys.stdin.readline()",
        coordination.directory,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "HELD"
    adapter = OSSlots(coordination.directory)
    assert adapter.acquire("slot-6") is None
    output, errors = process.communicate("exit\n")
    assert process.returncode == 0 and not output and not errors
    released = adapter.acquire("slot-6")
    assert released is not None
    released.release()


def test_real_flag_remains_signaled_until_panic_owner_process_exits(tmp_path: Path) -> None:
    adapter = OSFlagAdapter(tmp_path / "flag")
    first = adapter.open_window()
    assert not first.signaled()
    process = child(
        "from pathlib import Path; import sys; "
        "from backend.ops.panic_flag import OSFlagAdapter; "
        "flag=OSFlagAdapter(Path(sys.argv[1])); "
        "print('SIGNALED' if flag.signal_if_present() else 'ABSENT',flush=True); "
        "sys.stdin.readline()",
        tmp_path / "flag",
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "SIGNALED"
    assert first.signaled()
    first.close()
    later = adapter.open_window()
    assert later.signaled(), "panic process holds the manual-reset object alive"
    later.close()
    output, errors = process.communicate("exit\n")
    assert process.returncode == 0 and not output and not errors
    if sys.platform == "win32":
        fresh = adapter.open_window()
        assert not fresh.signaled(), "no reset: the old object ceased to exist on process exit"
        fresh.close()


def test_F1_real_panic_creates_signal_before_any_resolver(tmp_path: Path) -> None:
    process = child(
        "from pathlib import Path; import sys; "
        "from backend.ops.panic_flag import OSFlagAdapter; "
        "flag=OSFlagAdapter(Path(sys.argv[1])); flag.signal_if_present(); "
        "print('READY',flush=True); sys.stdin.readline()",
        tmp_path / "precreated",
    )
    assert process.stdout is not None
    handle = None
    try:
        assert process.stdout.readline().strip() == "READY"
        handle = OSFlagAdapter(tmp_path / "precreated").open_window()
        assert handle.signaled(), "panic creates and retains the flag before any resolver exists"
    finally:
        if handle is not None:
            handle.close()
        output, errors = process.communicate("exit\n")
    assert process.returncode == 0 and not output and not errors
