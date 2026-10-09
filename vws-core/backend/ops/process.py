"""OPS-02: an OS-held process lock and private, bounded UTC heartbeat."""

import errno
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Protocol, cast
from uuid import UUID

from pydantic import Field

from backend.core.clock import Clock, ensure_utc
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.domain.models import FrozenModel, UTCDateTime
from backend.ops.anchors import controlled_path


class _FlockAPI(Protocol):
    LOCK_EX: int
    LOCK_NB: int

    def flock(self, fd: int, operation: int) -> None: ...


class ProcessLock:
    """OS lock is released on exit or crash; no PID guesses or stale resets."""

    def __init__(self, path: Path) -> None:
        self.path = controlled_path(path)
        self.fd: int | None = None

    def __enter__(self) -> "ProcessLock":
        if self.fd is not None:
            raise ConfigurationError("The process lock is already held by this instance")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                api = cast(_FlockAPI, fcntl)
                api.flock(fd, api.LOCK_EX | api.LOCK_NB)
        except OSError as error:
            os.close(fd)
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise ProcessBusyError("Another Project V process holds the host lock") from None
            raise ConfigurationError("The host process lock is unavailable") from None
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Heartbeat(FrozenModel):
    run_id: UUID
    updated_at: UTCDateTime
    mode: str = Field(pattern=r"^(MANUAL|AUTO_PAPER|AUTO_LIVE)$")
    paper: bool = Field(strict=True)
    scheduler_running: bool = Field(strict=True)


class ProcessBusyError(ConfigurationError):
    """OPS-02: distinct from an unavailable or invalid OS lock."""


def write_heartbeat(path: Path, heartbeat: Heartbeat) -> None:
    checked = Heartbeat.model_validate(heartbeat)
    if (
        not checked.scheduler_running
        or (checked.mode == "AUTO_PAPER" and not checked.paper)
        or (checked.mode == "AUTO_LIVE" and checked.paper)
    ):
        raise DataIntegrityError("A stopped or unbound runtime cannot certify its heartbeat")
    destination = controlled_path(path)
    fd, name = tempfile.mkstemp(prefix=".heartbeat-", dir=destination.parent)
    staging = Path(name)
    try:
        os.chmod(staging, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(checked.model_dump_json().encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, destination)
    finally:
        if staging.exists():
            staging.unlink()


def heartbeat_is_fresh(path: Path, lock_path: Path, clock: Clock) -> bool:
    """Health does not mean trading readiness; require a held OS lock too."""
    try:
        source = controlled_path(path)
        if not source.is_file() or source.stat().st_size > 2048:
            return False
        pairs = json.loads(source.read_bytes(), object_pairs_hook=list)
        if not isinstance(pairs, list) or len(pairs) != len(Heartbeat.model_fields):
            return False
        payload = dict(pairs)
        if len(payload) != len(pairs) or set(payload) != set(Heartbeat.model_fields):
            return False
        if not isinstance(payload["updated_at"], str) or not isinstance(payload["run_id"], str):
            return False
        payload["updated_at"] = datetime.fromisoformat(payload["updated_at"])
        payload["run_id"] = UUID(payload["run_id"])
        checked = Heartbeat.model_validate(payload)
        now = ensure_utc(clock.now())
        if (
            not checked.scheduler_running
            or (checked.mode == "AUTO_PAPER" and not checked.paper)
            or (checked.mode == "AUTO_LIVE" and checked.paper)
            or not timedelta(0) <= now - checked.updated_at <= timedelta(seconds=180)
        ):
            return False
        held = ProcessLock(lock_path)
        try:
            held.__enter__()
        except ProcessBusyError:
            return True
        else:
            held.__exit__(None, None, None)
            return False
    except Exception:
        return False
