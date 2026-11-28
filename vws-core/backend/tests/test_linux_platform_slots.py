"""LP-20..LP-25: real flock slots and runtime.lock; barriers are pipes, never sleeps."""

import subprocess
from pathlib import Path

import pytest

from backend.ops.platform_primitives import backend_for, prepare_runtime_dir
from backend.ops.process import ProcessBusyError
from backend.ops.quiescence import BrokerCoordination, QuiescenceError
from backend.tests.test_broker_flag_os import child

HOLD = (
    "from pathlib import Path; import sys; import os; "
    "from backend.ops.platform_primitives import backend_for; "
    "lease=backend_for('linux').slots(Path(sys.argv[1])).acquire({slot!r}); "
    "print('HELD' if lease else 'BUSY',flush=True); {tail}"
)
WAIT = "sys.stdin.readline()"
CRASH = "os._exit(1)"


def hold(directory: Path, slot: str, tail: str = WAIT) -> subprocess.Popen[str]:
    return child(HOLD.format(slot=slot, tail=tail), directory)


def first_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    return process.stdout.readline().strip()


def release(process: subprocess.Popen[str]) -> None:
    output, errors = process.communicate("exit\n")
    assert process.returncode == 0 and not output and not errors


def prepared(project: Path) -> BrokerCoordination:
    coordination = BrokerCoordination(project)
    coordination.initialize()
    return coordination


def test_LP20_second_process_gets_held_immediately_without_waiting(tmp_path: Path) -> None:
    slots = backend_for("linux").slots(prepared(tmp_path).directory)
    process = hold(prepared(tmp_path).directory, "slot-3")
    assert first_line(process) == "HELD"
    assert slots.acquire("slot-3") is None
    release(process)
    freed = slots.acquire("slot-3")
    assert freed is not None and freed.held
    freed.release()


def test_LP21_other_slots_stay_independent(tmp_path: Path) -> None:
    directory = prepared(tmp_path).directory
    process = hold(directory, "slot-3")
    assert first_line(process) == "HELD"
    other = backend_for("linux").slots(directory).acquire("slot-4")
    assert other is not None and other.held
    other.release()
    release(process)


def test_LP22_crash_without_cleanup_releases_the_slot_on_first_try(tmp_path: Path) -> None:
    directory = prepared(tmp_path).directory
    process = hold(directory, "slot-5", CRASH)
    assert first_line(process) == "HELD"
    assert process.wait(timeout=30) == 1
    lease = backend_for("linux").slots(directory).acquire("slot-5")
    assert lease is not None
    lease.release()


def test_LP23_resolver_needs_all_eight_slots_and_leaks_none_when_one_is_held(
    tmp_path: Path,
) -> None:
    coordination = prepared(tmp_path)
    process = hold(coordination.directory, "slot-2")
    assert first_line(process) == "HELD"
    with pytest.raises(QuiescenceError, match=r"^Broker actor slot is occupied$"):
        with coordination.resolver():
            raise AssertionError("resolver must not proceed with a held slot")
    slots = backend_for("linux").slots(coordination.directory)
    for index in (0, 1, 3, 4, 5, 6, 7):
        lease = slots.acquire(f"slot-{index}")
        assert lease is not None, f"slot-{index} leaked by the refused resolver"
        lease.release()
    assert slots.acquire("slot-2") is None
    release(process)


def test_LP24_same_process_second_open_file_description_is_refused(tmp_path: Path) -> None:
    """Pinned: flock locks belong to the open file description, so a second open is HELD."""
    directory = prepared(tmp_path).directory
    first = backend_for("linux").slots(directory).acquire("slot-1")
    assert first is not None
    assert backend_for("linux").slots(directory).acquire("slot-1") is None
    first.release()
    again = backend_for("linux").slots(directory).acquire("slot-1")
    assert again is not None
    again.release()


LOCK_HOLD = (
    "from pathlib import Path; import sys; "
    "from backend.ops.platform_primitives import backend_for; "
    "lock=backend_for('linux').runtime_lock(Path(sys.argv[1])); lock.__enter__(); "
    "print('LOCKED',flush=True); sys.stdin.readline()"
)


def test_LP25_runtime_lock_is_nonblocking_and_reports_the_existing_busy_refusal(
    tmp_path: Path,
) -> None:
    runtime = prepare_runtime_dir({"XDG_RUNTIME_DIR": str(tmp_path)})
    process = child(LOCK_HOLD, runtime)
    assert first_line(process) == "LOCKED"
    contender = backend_for("linux").runtime_lock(runtime)
    with pytest.raises(ProcessBusyError, match=r"^Another Project V process holds the host lock$"):
        contender.__enter__()
    release(process)
    with backend_for("linux").runtime_lock(runtime):
        assert (runtime / "runtime.lock").read_bytes() == b"0"
