"""Paper host broker actors: nonblocking slots and durable invocation inventory."""

import asyncio
import ctypes
import hashlib
import json
import logging
import os
import re
import sys
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import BinaryIO, Protocol, TypeVar, cast
from uuid import UUID, uuid4

from backend.core.errors import ConfigurationError
from backend.ops.panic_flag import FlagAdapter, FlagHandle, OSFlagAdapter, PanicFlagError


class QuiescenceError(ConfigurationError):
    """No positive claim is permitted when coordination is unverified."""


class Lease(Protocol):
    @property
    def held(self) -> bool: ...

    def release(self) -> None: ...


class SlotAdapter(Protocol):
    def acquire(self, name: str) -> Lease | None: ...


class FlockAPI(Protocol):
    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int) -> None: ...


class FileLease:
    def __init__(self, file: BinaryIO, api: FlockAPI) -> None:
        self.file, self.api = file, api
        self.owner = threading.get_ident()

    @property
    def held(self) -> bool:
        return not self.file.closed and threading.get_ident() == self.owner

    def release(self) -> None:
        if threading.get_ident() != self.owner:
            raise QuiescenceError("Broker lease release must stay on its owner thread")
        try:
            self.api.flock(self.file.fileno(), self.api.LOCK_UN)
        finally:
            self.file.close()


_owned_mutexes: set[str] = set()


class WindowsLease:
    def __init__(self, handle: int, name: str) -> None:
        self.handle, self.name, self.owner = handle, name, threading.get_ident()
        self.active = True

    @property
    def held(self) -> bool:
        return self.active and self.name in _owned_mutexes and self.owner == threading.get_ident()

    def release(self) -> None:
        if threading.get_ident() != self.owner:
            raise QuiescenceError("Broker mutex release must stay on its owner thread")
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.ReleaseMutex.argtypes = [ctypes.c_void_p]
        api.ReleaseMutex.restype = ctypes.c_int
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        api.CloseHandle.restype = ctypes.c_int
        released = api.ReleaseMutex(self.handle)
        closed = api.CloseHandle(self.handle)
        self.active = False
        _owned_mutexes.discard(self.name)
        if not released or not closed:
            raise QuiescenceError("Broker mutex release is unverified")


class OSSlots:
    """Every acquisition is nonblocking; Windows ownership is thread-specific."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def acquire(self, name: str) -> Lease | None:
        if re.fullmatch(r"slot-[0-7]|lease-[0-9a-f]{32}", name) is None:
            raise QuiescenceError("Invalid broker lease name")
        if sys.platform == "win32":
            if name in _owned_mutexes:
                return None
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            api.CreateMutexW.restype = ctypes.c_void_p
            api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            api.WaitForSingleObject.restype = ctypes.c_uint32
            api.CloseHandle.argtypes = [ctypes.c_void_p]
            api.CloseHandle.restype = ctypes.c_int
            handle = api.CreateMutexW(None, False, "Local\\ProjectV-broker-" + name)
            if not handle:
                raise QuiescenceError("Broker mutex creation is unverified")
            status = api.WaitForSingleObject(handle, 0)
            if status == 0:
                _owned_mutexes.add(name)
                return WindowsLease(handle, name)
            if status == 0x80:  # WAIT_ABANDONED grants ownership, but never proof.
                WindowsLease(handle, name).release()
                raise QuiescenceError("Abandoned broker mutex is unverified")
            api.CloseHandle(handle)
            if status == 0x102:
                return None
            raise QuiescenceError("Broker mutex probe is unverified")
        import fcntl

        flock_api = cast(FlockAPI, fcntl)
        file = (self.directory / name).open("r+b")
        acquired = False
        try:
            flock_api.flock(file.fileno(), flock_api.LOCK_EX | flock_api.LOCK_NB)
            acquired = True
        except BlockingIOError:
            return None
        finally:
            if not acquired:
                file.close()
        return FileLease(file, flock_api)


class BrokerCoordination:
    """Append-only UUID inventory is the epoch; no wall-clock ordering or TTL."""

    def __init__(
        self,
        project: Path,
        adapter: SlotAdapter | None = None,
        flag_adapter: FlagAdapter | None = None,
    ) -> None:
        self.project = project.resolve()
        self.directory = self.project / "data" / "broker-coordination"
        self.adapter = adapter if adapter is not None else OSSlots(self.directory)
        self.flag_adapter = (
            flag_adapter if flag_adapter is not None else OSFlagAdapter(self.directory)
        )
        self._epoch: tuple[tuple[str, str], ...] | None = None
        self._leases: list[Lease] = []
        self._flag_handle: FlagHandle | None = None

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise QuiescenceError("Direct broker coordination directory required")
        generation = self.directory / "generation"
        try:
            with generation.open("x", encoding="ascii") as output:
                output.write(uuid4().hex)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            pass
        if sys.platform != "win32":
            for index in range(8):
                try:
                    with (self.directory / f"slot-{index}").open("xb") as output:
                        output.write(b"0")
                except FileExistsError:
                    pass

    def publish(self, identity: UUID, phase: str, kind: str, slot: bool) -> None:
        payload = {"id": identity.hex, "phase": phase, "kind": kind, "slot": slot}
        with (self.directory / f"{identity.hex}.{phase}").open("x", encoding="ascii") as output:
            output.write(json.dumps(payload, sort_keys=True))
            output.flush()
            os.fsync(output.fileno())

    def publish_failure(self, identity: UUID, error_type: str) -> None:
        payload = {"id": identity.hex, "error_type": error_type}
        with (self.directory / f"{identity.hex}.FAIL").open("x", encoding="ascii") as output:
            output.write(json.dumps(payload, sort_keys=True))
            output.flush()
            os.fsync(output.fileno())

    def _inventory(self) -> tuple[tuple[str, str], ...]:
        if self.directory.is_symlink():
            raise QuiescenceError("Direct broker coordination directory required")
        generation_path = self.directory / "generation"
        if generation_path.is_symlink():
            raise QuiescenceError("Direct broker generation required")
        try:
            generation = generation_path.read_text(encoding="ascii")
        except UnicodeError:
            raise QuiescenceError("Broker generation is corrupt") from None
        if re.fullmatch(r"[0-9a-f]{32}", generation) is None:
            raise QuiescenceError("Broker generation is unverified")
        epoch = [("generation", generation)]
        phases: dict[str, set[str]] = {}
        for path in sorted(self.directory.iterdir()):
            if path.name in {"generation", "panic-window", "panic-seen"} or re.fullmatch(
                r"slot-[0-7]|lease-[0-9a-f]{32}", path.name
            ):
                continue
            if path.suffix == ".FAIL":
                raise QuiescenceError("Incomplete panic/recovery invocation; inspect doctor")
            match = re.fullmatch(r"([0-9a-f]{32})\.(BEGIN|END)", path.name)
            if match is None or path.is_symlink():
                raise QuiescenceError("Broker inventory is unverified")
            data = path.read_bytes()
            try:
                payload = json.loads(data)
            except (UnicodeError, json.JSONDecodeError):
                raise QuiescenceError("Broker invocation is corrupt") from None
            identity, phase = match.groups()
            if (
                not isinstance(payload, dict)
                or set(payload) != {"id", "phase", "kind", "slot"}
                or payload["id"] != identity
                or payload["phase"] != phase
                or payload["kind"] not in {"runtime", "panic"}
                or type(payload["slot"]) is not bool
            ):
                raise QuiescenceError("Broker invocation is unverified")
            phases.setdefault(identity, set()).add(phase)
            epoch.append((path.name, hashlib.sha256(data).hexdigest()))
        for identity, observed in phases.items():
            if observed != {"BEGIN", "END"}:
                raise QuiescenceError("Incomplete panic/recovery invocation; inspect doctor")
            lease = self.adapter.acquire("lease-" + identity)
            if lease is None:
                raise QuiescenceError("Broker invocation is still running")
            lease.release()
        return tuple(epoch)

    @contextmanager
    def resolver(self) -> Iterator["BrokerCoordination"]:
        try:
            self.acquire_proof()
        except OSError:
            raise QuiescenceError("Broker coordination is unverified") from None
        try:
            yield self
            self.check()
        finally:
            self.release_proof()

    def acquire_proof(self) -> None:
        if self._leases:
            raise QuiescenceError("Broker proof is already held")
        complete = False
        try:
            self._flag_handle = self.flag_adapter.open_window()
            if self._flag_handle.signaled():
                raise QuiescenceError("Panic flag is signaled")
            for index in range(8):
                lease = self.adapter.acquire(f"slot-{index}")
                if lease is None:
                    raise QuiescenceError("Broker actor slot is occupied")
                self._leases.append(lease)
            self._epoch = self._inventory()
            complete = True
        except PanicFlagError:
            raise QuiescenceError("Panic flag is unverified") from None
        finally:
            if not complete:
                self.release_proof()

    def release_proof(self) -> None:
        leases, self._leases = self._leases, []
        self._epoch = None
        failure: OSError | QuiescenceError | PanicFlagError | None = None
        for lease in reversed(leases):
            try:
                lease.release()
            except (OSError, QuiescenceError) as error:
                failure = error
        handle, self._flag_handle = self._flag_handle, None
        if handle is not None:
            try:
                handle.close()
            except (OSError, PanicFlagError) as error:
                failure = error
        if failure is not None:
            primary = sys.exception()
            if primary is not None:
                primary.add_note("Broker slot release failed: " + type(failure).__name__)
            else:
                raise QuiescenceError("Broker proof cleanup failed") from None

    def check(self) -> None:
        try:
            if self._flag_handle is None or self._flag_handle.signaled():
                raise QuiescenceError("Panic flag is signaled or unavailable")
        except PanicFlagError:
            raise QuiescenceError("Panic flag read is unverified") from None
        if (
            len(self._leases) != 8
            or not all(lease.held for lease in self._leases)
            or self._epoch is None
            or self._inventory() != self._epoch
        ):
            raise QuiescenceError("Broker epoch changed during evidence collection")

    def doctor_message(self) -> str | None:
        try:
            self._inventory()
        except (OSError, QuiescenceError):
            return (
                "FIX_G_QUIESCENCE_UNVERIFIED: incomplete panic/recovery invocation; "
                "no automatic expiry or stale-lock removal. "
                "Verify broker state and reconcile through the existing host recovery procedure."
            )
        return None


ResultT = TypeVar("ResultT")
_active: ContextVar["BrokerActor | None"] = ContextVar("broker-actor", default=None)


class BrokerActor:
    """Emergency observations never become a prerequisite for emergency work."""

    def __init__(self, coordination: BrokerCoordination, kind: str) -> None:
        self.coordination, self.kind = coordination, kind
        self.identity = uuid4()
        self.slot: Lease | None = None
        self.lease: Lease | None = None
        self._lock = threading.Lock()
        self._pending = 0
        self._closing = False
        self._finished = False
        self._healthy = True
        self.failure_types: set[str] = set()
        self._failure_recorded = False
        self._begin_recorded = False
        self._flag_failed = False
        self._stderr_reported = False
        try:
            self.loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

    def _free_slot(self) -> Lease | None:
        for index in range(8):
            lease = self.coordination.adapter.acquire(f"slot-{index}")
            if lease is not None:
                return lease
        return None

    def start(self) -> None:
        try:
            self.coordination.initialize()
            name = "lease-" + self.identity.hex
            if sys.platform != "win32":
                with (self.coordination.directory / name).open("xb") as output:
                    output.write(b"0")
            self.lease = self.coordination.adapter.acquire(name)
            self.slot = self._free_slot()
            if self.lease is None:
                raise QuiescenceError("Broker invocation lease unavailable")
            if self.kind == "runtime" and self.slot is None:
                raise QuiescenceError("Runtime requires a free broker actor slot")
        except (OSError, QuiescenceError) as error:
            self._record_failure(error)
            if self.kind == "runtime":
                raise
        try:
            self.coordination.publish(self.identity, "BEGIN", self.kind, self.slot is not None)
            self._begin_recorded = True
        except (OSError, QuiescenceError) as error:
            self._record_failure(error)
            if self.kind == "runtime":
                raise

    def _record_failure(self, error: OSError | QuiescenceError | PanicFlagError) -> None:
        self._healthy = False
        self.failure_types.add(type(error).__name__)
        if not self._failure_recorded:
            try:
                self.coordination.publish_failure(self.identity, type(error).__name__)
                self._failure_recorded = True
            except (OSError, QuiescenceError) as publication_error:
                self.failure_types.add(type(publication_error).__name__)

    def retain(self) -> None:
        with self._lock:
            self._pending += 1

    def before_broker_call(self) -> Lease | None:
        """ONE nonblocking slot/flag choke point for sync and async panic transport."""
        transient: Lease | None = None
        if self.slot is None:
            try:
                transient = self._free_slot()
            except (OSError, QuiescenceError) as error:
                self._record_failure(error)
            if self.kind == "panic":
                try:
                    self.coordination.flag_adapter.signal_if_present()
                except (OSError, PanicFlagError) as error:
                    self._flag_failed = True
                    self._record_failure(error)
        return transient

    def physical_call(self, operation: Callable[[], ResultT]) -> ResultT:
        transient: Lease | None = None
        try:
            transient = self.before_broker_call()
            return operation()
        finally:
            self._call_finished(transient)

    async def async_call(self, operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
        self.retain()
        transient: Lease | None = None
        try:
            transient = self.before_broker_call()
            return await operation()
        finally:
            self._call_finished(transient)

    def _call_finished(self, transient: Lease | None) -> None:
        if transient is not None:
            try:
                transient.release()
            except (OSError, QuiescenceError) as error:
                self._record_failure(error)
        with self._lock:
            self._pending -= 1
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._finish_if_idle)

    def finish(self) -> None:
        self._closing = True
        self._finish_if_idle()

    @property
    def panic_not_recorded(self) -> bool:
        return self._flag_failed and not (self._begin_recorded or self._failure_recorded)

    def _finish_if_idle(self) -> None:
        with self._lock:
            if not self._closing or self._pending or self._finished:
                return
            self._finished = True
        try:
            if self._healthy:
                self.coordination.publish(self.identity, "END", self.kind, self.slot is not None)
        except (OSError, QuiescenceError) as error:
            self._record_failure(error)
        finally:
            for lease in (self.slot, self.lease):
                if lease is not None:
                    try:
                        lease.release()
                    except (OSError, QuiescenceError) as error:
                        self._record_failure(error)
            if self.failure_types:
                logging.getLogger(__name__).warning(
                    "Broker coordination UNVERIFIED; failure types=%s; durable failure=%s",
                    ",".join(sorted(self.failure_types)),
                    self._failure_recorded,
                )
            if self.panic_not_recorded and not self._stderr_reported:
                self._stderr_reported = True
                print(
                    "PANIC_NOT_RECORDED: clear-intent --apply must not run until vws doctor is clean.",
                    file=sys.stderr,
                )


def current_actor() -> BrokerActor | None:
    return _active.get()


@contextmanager
def actor_scope(project: Path, kind: str) -> Iterator[BrokerActor]:
    existing = _active.get()
    if existing is not None:
        yield existing
        return
    actor = BrokerActor(BrokerCoordination(project), kind)
    token = _active.set(actor)
    try:
        actor.start()
        yield actor
    finally:
        _active.reset(token)
        actor.finish()
