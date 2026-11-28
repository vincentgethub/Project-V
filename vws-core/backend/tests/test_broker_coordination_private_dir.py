"""Production wiring: BrokerCoordination applies the private-directory checks to its real path."""

import os
import stat
import sys
from pathlib import Path

import pytest

from backend.ops import private_dir
from backend.ops.quiescence import BrokerActor, BrokerCoordination, QuiescenceError, actor_scope

UNSAFE = r"^Broker coordination directory is unsafe$"
NFS = 0x6969


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_initialize_creates_the_existing_data_path_private_on_linux(tmp_path: Path) -> None:
    coordination = BrokerCoordination(tmp_path)
    coordination.initialize()
    assert coordination.directory == tmp_path.resolve() / "data" / "broker-coordination"
    assert coordination.directory.is_dir()
    if sys.platform != "win32":
        assert mode(coordination.directory) == 0o700


def test_existing_group_readable_directory_is_refused_everywhere_and_not_repaired(
    tmp_path: Path,
) -> None:
    coordination = BrokerCoordination(tmp_path)
    coordination.directory.mkdir(parents=True)
    coordination.directory.chmod(0o755)
    if sys.platform == "win32":
        coordination.initialize()
        return
    with pytest.raises(QuiescenceError, match=UNSAFE):
        coordination.initialize()
    assert mode(coordination.directory) == 0o755
    with pytest.raises(QuiescenceError, match=UNSAFE):
        with coordination.resolver():
            raise AssertionError("resolver must not trust an unsafe directory")
    message = coordination.doctor_message()
    assert message is not None and message.startswith("FIX_G_QUIESCENCE_UNVERIFIED")


def test_directory_owned_by_another_user_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        BrokerCoordination(tmp_path).initialize()
        return
    monkeypatch.setattr(private_dir, "_current_uid", lambda: os.getuid() + 1)
    coordination = BrokerCoordination(tmp_path)
    coordination.directory.mkdir(parents=True, mode=0o700)
    with pytest.raises(QuiescenceError, match=UNSAFE):
        coordination.initialize()


def test_network_or_unknown_filesystem_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform == "win32":
        BrokerCoordination(tmp_path).initialize()
        return
    monkeypatch.setattr(private_dir, "filesystem_magic", lambda _path: NFS)
    with pytest.raises(QuiescenceError, match=UNSAFE):
        BrokerCoordination(tmp_path).initialize()
    assert not list((tmp_path / "data" / "broker-coordination").glob("generation"))


def test_runtime_actor_refuses_to_start_but_panic_actor_still_does_emergency_work(
    tmp_path: Path,
) -> None:
    if sys.platform == "win32":
        return_value = BrokerActor(BrokerCoordination(tmp_path), "runtime")
        return_value.start()
        return_value.finish()
        return
    coordination = BrokerCoordination(tmp_path)
    coordination.directory.mkdir(parents=True)
    coordination.directory.chmod(0o755)
    with pytest.raises(QuiescenceError, match=UNSAFE):
        with actor_scope(tmp_path, "runtime"):
            raise AssertionError("runtime must not start on an unsafe directory")
    panic = BrokerActor(BrokerCoordination(tmp_path), "panic")
    panic.start()
    ran: list[str] = []
    panic.retain()
    panic.physical_call(lambda: ran.append("cancel"))
    panic.finish()
    assert ran == ["cancel"] and "QuiescenceError" in panic.failure_types
