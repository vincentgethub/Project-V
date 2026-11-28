"""Real OS slot/flag adapters behind the fake-shaped test surface (counters kept, state real)."""

import os
import sys
from collections.abc import Iterable
from pathlib import Path

from backend.ops.panic_flag import FlagHandle, OSFlagAdapter
from backend.ops.platform_primitives import current_backend
from backend.ops.quiescence import Lease, OSSlots
from backend.tests.broker_flag_fakes import FakeFlagAdapter, FakeFlagHandle
from backend.tests.test_broker_coordination import FakeLease, FakeSlots

SLOT_NAMES = tuple(f"slot-{index}" for index in range(8))


def prepare_coordination_directory(directory: Path) -> None:
    """Create the coordination directory the way production does (0700, slot files)."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    if sys.platform != "win32":
        for name in SLOT_NAMES:
            slot = directory / name
            if not slot.exists():
                slot.write_bytes(b"0")


class HeldSet(set[str]):
    """Names other actors hold: every membership change is a real lock, not a bookkeeping entry."""

    def __init__(self, native: OSSlots) -> None:
        super().__init__()
        self.native = native
        self.leases: dict[str, Lease] = {}

    def update(self, *others: Iterable[str]) -> None:
        for names in others:
            for name in names:
                if name not in self:
                    lease = self.native.acquire(name)
                    assert lease is not None, f"{name} was already held outside the test"
                    self.leases[name] = lease
                    super().add(name)

    def difference_update(self, *others: Iterable[object]) -> None:
        for names in others:
            for name in names:
                lease = self.leases.pop(str(name), None)
                if lease is not None:
                    lease.release()
                    super().discard(str(name))

    def release_all(self) -> None:
        self.difference_update(tuple(self.leases))


class TrackedLease(FakeLease):
    def __init__(self, slots: "RealBackedSlots", name: str, lease: Lease) -> None:
        super().__init__(slots, name)
        self.lease = lease

    @property
    def held(self) -> bool:
        return self.lease.held

    def release(self) -> None:
        try:
            self.lease.release()
        finally:
            set.discard(self.slots.held, self.name)


class RealBackedSlots(FakeSlots):
    def __init__(self, directory: Path) -> None:
        super().__init__()
        prepare_coordination_directory(directory)
        self.directory = directory
        self.native = OSSlots(directory)
        self.pinned = HeldSet(self.native)
        self.held = self.pinned

    def acquire(self, name: str) -> FakeLease | None:
        self.probes.append(name)
        lease = self.native.acquire(name)
        if lease is None:
            return None
        set.add(self.held, name)
        return TrackedLease(self, name, lease)


class RealBackedFlagHandle(FakeFlagHandle):
    def __init__(self, adapter: "RealBackedFlag", native: FlagHandle) -> None:
        super().__init__(adapter)
        self.native = native

    def signaled(self) -> bool:
        self.adapter.reads += 1
        return self.native.signaled()

    def close(self) -> None:
        self.adapter.windows -= 1
        self.native.close()


class RealBackedFlag(FakeFlagAdapter):
    """Counts like the fake; every state read and write goes through the real OS flag."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory
        self.native = OSFlagAdapter(directory)

    def open_window(self) -> RealBackedFlagHandle:
        handle = self.native.open_window()
        self.windows += 1
        return RealBackedFlagHandle(self, handle)

    def signal_if_present(self) -> bool:
        self.signals += 1
        self.trace.append("flag")
        self.native.signal_if_present()
        self.retained = True
        self.signaled = flag_is_set(self.directory)
        assert self.signaled, "the real flag must read back as set after signalling"
        return True


def flag_is_set(directory: Path) -> bool:
    return current_backend().panic_is_set(directory)


def open_files_under(directory: Path) -> list[str]:
    """Descriptors still open inside the directory (POSIX); none to list on Windows.

    The sticky ``panic-seen`` descriptor is retained for the life of the process by design
    (an unlocked open file, the analogue of Windows' retained event) so it is not a leak.
    """
    if sys.platform == "win32":
        return []
    found: list[str] = []
    for entry in Path("/proc/self/fd").iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith(str(directory)) and not target.endswith("/panic-seen"):
            found.append(target)
    return sorted(found)


def assert_no_leaked_locks(directory: Path) -> None:
    """Every actor slot can be taken again and no descriptor into the directory is left open."""
    native = OSSlots(directory)
    for name in SLOT_NAMES:
        lease = native.acquire(name)
        assert lease is not None, f"{name} is still locked"
        lease.release()
    window = OSFlagAdapter(directory).open_window()
    window.close()
    assert open_files_under(directory) == []


class Adapters:
    """Real-backed adapters created for one test, always released and checked at the end."""

    def __init__(self, project: Path) -> None:
        self.directory = project / "data" / "broker-coordination"
        self.created: list[RealBackedSlots] = []

    def slots(self) -> RealBackedSlots:
        made = RealBackedSlots(self.directory)
        self.created.append(made)
        return made

    def flag(self) -> RealBackedFlag:
        return RealBackedFlag(self.directory)

    def finish(self) -> None:
        for made in self.created:
            made.pinned.release_all()
        assert_no_leaked_locks(self.directory)
