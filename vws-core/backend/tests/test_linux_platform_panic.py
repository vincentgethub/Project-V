"""LP-30..LP-35 and the Linux-backend parts of LP-40..LP-44 (real files, real processes)."""

import ast
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from backend.ops import panic_flag
from backend.ops.panic_flag import OSFlagAdapter
from backend.ops.platform_primitives import backend_for
from backend.ops.quiescence import BrokerActor, BrokerCoordination, QuiescenceError
from backend.tests.test_broker_flag_os import child

SET = (
    "from pathlib import Path; import sys; import os; "
    "from backend.ops.platform_primitives import backend_for; "
    "print('SET' if backend_for('linux').panic_set(Path(sys.argv[1])) else 'NO',flush=True); {tail}"
)
WAIT = "sys.stdin.readline()"
DIE = "os._exit(0)"


def setter(directory: Path, tail: str) -> subprocess.Popen[str]:
    return child(SET.format(tail=tail), directory)


def first_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    return process.stdout.readline().strip()


def test_LP30_flag_set_in_one_process_is_visible_in_another(tmp_path: Path) -> None:
    directory = tmp_path / "flag"
    backend = backend_for("linux")
    assert backend.panic_is_set(directory) is False
    process = setter(directory, WAIT)
    assert first_line(process) == "SET"
    assert backend.panic_is_set(directory) is True
    output, errors = process.communicate("exit\n")
    assert process.returncode == 0 and not output and not errors


def test_LP32_flag_survives_setter_death_without_cleanup(tmp_path: Path) -> None:
    directory = tmp_path / "flag"
    process = setter(directory, DIE)
    assert first_line(process) == "SET"
    assert process.wait(timeout=30) == 0
    assert backend_for("linux").panic_is_set(directory) is True
    assert (directory / "panic-seen").read_bytes() == b"1"


def test_LP33_second_set_from_another_process_succeeds_and_changes_nothing(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "flag"
    assert backend_for("linux").panic_set(directory) is True
    marker = directory / "panic-seen"
    before = (marker.read_bytes(), marker.stat().st_mtime_ns, marker.stat().st_ino)
    process = setter(directory, "pass")
    assert first_line(process) == "SET"
    assert process.wait(timeout=30) == 0
    assert (marker.read_bytes(), marker.stat().st_mtime_ns, marker.stat().st_ino) == before
    assert backend_for("linux").panic_set(directory) is True


def test_LP33_corrupt_marker_is_refused_loudly(tmp_path: Path) -> None:
    directory = tmp_path / "flag"
    directory.mkdir()
    (directory / "panic-seen").write_bytes(b"0")
    with pytest.raises(panic_flag.PanicFlagError, match=r"^Panic flag marker is corrupt$"):
        backend_for("linux").panic_set(directory)
    with pytest.raises(panic_flag.PanicFlagError, match=r"^Panic flag marker is corrupt$"):
        backend_for("linux").panic_is_set(directory)


def test_LP33_marker_symlink_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "flag"
    directory.mkdir()
    (directory / "panic-seen").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(panic_flag.PanicFlagError, match=r"^Panic flag marker is not direct$"):
        backend_for("linux").panic_is_set(directory)


FORBIDDEN_CALLS = {
    "unlink",
    "remove",
    "truncate",
    "ftruncate",
    "rename",
    "replace",
    "rmtree",
    "rmdir",
    "write_bytes",
    "write_text",
}


def calls(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    return names


def test_LP31_nothing_deletes_resets_or_rewrites_the_sticky_flag() -> None:
    ops = Path(panic_flag.__file__).resolve().parent
    assert calls(ops / "panic_flag.py") & FORBIDDEN_CALLS == set()
    assert calls(ops / "platform_primitives.py") & FORBIDDEN_CALLS == set()
    owners = sorted(
        path.name
        for path in ops.parents[0].rglob("*.py")
        if "tests" not in path.parts and ".venv" not in path.parts
        if "panic-seen" in path.read_text(encoding="utf-8")
    )
    assert owners == ["panic_flag.py", "quiescence.py"]


def test_LP34_create_failure_is_loud_and_never_silently_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked = tmp_path / "flag"
    blocked.write_bytes(b"not a directory")
    with pytest.raises(OSError):
        backend_for("linux").panic_set(blocked)
    project = tmp_path / "project"
    coordination = BrokerCoordination(project, flag_adapter=OSFlagAdapter(blocked))

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("offline record unavailable")

    monkeypatch.setattr(BrokerCoordination, "publish", unavailable)
    monkeypatch.setattr(BrokerCoordination, "publish_failure", unavailable)
    coordination.initialize()
    held = [coordination.adapter.acquire(f"slot-{index}") for index in range(8)]
    actor = BrokerActor(coordination, "panic")
    actor.start()
    ran: list[str] = []
    actor.retain()
    actor.physical_call(lambda: ran.append("cancel"))
    actor.finish()
    for lease in held:
        assert lease is not None
        lease.release()
    assert ran == ["cancel"], "emergency work still runs"
    assert actor.panic_not_recorded is True
    assert "PANIC_NOT_RECORDED: clear-intent --apply must not run" in capsys.readouterr().err


def test_LP35_marker_is_flushed_and_fsynced_before_the_set_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "flag"
    seen: list[tuple[int, bytes]] = []
    real = os.fsync

    def spy(fd: int) -> None:
        seen.append((fd, (directory / "panic-seen").read_bytes()))
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    assert backend_for("linux").panic_set(directory) is True
    assert len(seen) == 1 and seen[0][1] == b"1"
    retained = panic_flag._retained_files[directory / "panic-seen"]
    assert seen[0][0] == retained.fileno()


class CountingFlag(OSFlagAdapter):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.signals = 0

    def signal_if_present(self) -> bool:
        self.signals += 1
        return super().signal_if_present()


def real_coordination(project: Path) -> tuple[BrokerCoordination, CountingFlag]:
    flag = CountingFlag(project / "data" / "broker-coordination")
    coordination = BrokerCoordination(project, flag_adapter=flag)
    coordination.initialize()
    return coordination, flag


def test_LP40_LP41_panic_is_slotless_and_flag_is_set_before_the_first_broker_call(
    tmp_path: Path,
) -> None:
    coordination, flag = real_coordination(tmp_path)
    held = [coordination.adapter.acquire(f"slot-{index}") for index in range(8)]
    assert all(lease is not None for lease in held)
    events: list[str] = []
    backend = backend_for("linux")

    def broker_call() -> None:
        events.append("flag_set" if backend.panic_is_set(coordination.directory) else "flag_unset")
        events.append("broker_call")

    actor = BrokerActor(coordination, "panic")
    actor.start()
    assert actor.slot is None
    actor.retain()
    actor.physical_call(broker_call)
    actor.finish()
    assert events == ["flag_set", "broker_call"]
    assert flag.signals == 1 and actor.failure_types == set()
    runtime = BrokerActor(coordination, "runtime")
    with pytest.raises(QuiescenceError, match=r"^Runtime requires a free broker actor slot$"):
        runtime.start()
    for lease in held:
        assert lease is not None
        lease.release()


def test_LP42_resolver_refuses_on_the_flag_at_entry_and_recheck_and_never_resets_it(
    tmp_path: Path,
) -> None:
    coordination, _flag = real_coordination(tmp_path)
    backend = backend_for("linux")
    backend.panic_set(coordination.directory)
    with pytest.raises(QuiescenceError, match=r"^Panic flag is signaled$"):
        with coordination.resolver():
            raise AssertionError("resolver must refuse a set flag")
    assert backend.panic_is_set(coordination.directory) is True
    slots = backend.slots(coordination.directory)
    for index in range(8):
        lease = slots.acquire(f"slot-{index}")
        assert lease is not None, "refused resolver leaked a slot"
        lease.release()


def test_LP42_flag_set_after_proof_is_caught_at_the_recheck(tmp_path: Path) -> None:
    coordination, _flag = real_coordination(tmp_path)
    coordination.acquire_proof()
    try:
        backend_for("linux").panic_set(coordination.directory)
        with pytest.raises(QuiescenceError, match=r"^Panic flag is signaled or unavailable$"):
            coordination.check()
    finally:
        coordination.release_proof()
    assert backend_for("linux").panic_is_set(coordination.directory) is True


def test_LP43_broker_inventory_change_between_snapshots_refuses(tmp_path: Path) -> None:
    coordination, _flag = real_coordination(tmp_path)
    coordination.acquire_proof()
    try:
        coordination.publish(uuid4(), "BEGIN", "panic", False)
        with pytest.raises(
            QuiescenceError, match=r"^Incomplete panic/recovery invocation; inspect doctor$"
        ):
            coordination.check()
    finally:
        coordination.release_proof()


def test_LP44_signal_counting_rule_matches_the_choke_point(tmp_path: Path) -> None:
    coordination, flag = real_coordination(tmp_path)
    slotless = BrokerActor(coordination, "panic")
    slotless.start()
    slotless.slot = None
    for _ in range(4):
        slotless.retain()
        slotless.physical_call(lambda: None)
    slotless.finish()
    assert flag.signals == 4
    slotted = BrokerActor(coordination, "panic")
    slotted.start()
    assert slotted.slot is not None
    for _ in range(4):
        slotted.retain()
        slotted.physical_call(lambda: None)
    slotted.finish()
    assert flag.signals == 4, "a held actor slot never signals"
