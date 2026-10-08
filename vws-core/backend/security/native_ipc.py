"""SEC-11/32: permit only synchronous native Secret Service user-bus IPC.

This grants no DNS, TCP, abstract sockets, inbound binds or general Unix IPC.
The thread-local scope exists only while the approved native keyring backend
is executing. Each connection rechecks socket ownership and path provenance.
"""

import os
import platform
import re
import socket
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import local
from typing import Protocol, cast

from backend.core.errors import ConfigurationError

_SCOPE = local()


class _UnixUser(Protocol):
    def geteuid(self) -> int: ...


def _verified_bus() -> str:
    """SEC-11: accept only the current user's ordinary session-bus socket.

    VERIFY: pinned jeepney 0.9.0 jeepney/bus.py parses unix:path and optional
    guid fields; no alternate transport/address or percent escape is accepted.
    """
    uid = cast(_UnixUser, os).geteuid()
    if type(uid) is not int or uid <= 0:
        raise ConfigurationError("Native user-bus identity is unavailable")
    expected = f"/run/user/{uid}/bus"
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if (
        re.fullmatch(re.escape("unix:path=" + expected) + r"(?:,guid=[0-9a-fA-F]{32})?", address)
        is None
    ):
        raise ConfigurationError("Native Secret Service needs the verified local user bus")
    path = Path(expected)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ConfigurationError("Native user-bus path provenance is unavailable")
    info, parent = path.lstat(), path.parent.lstat()
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != uid
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != uid
        or parent.st_mode & 0o022
    ):
        raise ConfigurationError("Native user-bus ownership is unavailable")
    return expected


@contextmanager
def native_keyring_call() -> Iterator[None]:
    """SEC-11: scope a native backend call; never hold this across an await."""
    if platform.system() != "Linux":
        yield
        return
    endpoint = _verified_bus()
    previous = _SCOPE.__dict__.get("endpoint")
    _SCOPE.endpoint = endpoint
    try:
        yield
    finally:
        _SCOPE.endpoint = previous


def native_connection_allowed(sock: object, endpoint: object) -> bool:
    """SEC-32: revalidate the exact scoped Unix destination, fail closed."""
    active = _SCOPE.__dict__.get("endpoint")
    if not isinstance(active, str) or endpoint != active or not isinstance(sock, socket.SocketType):
        return False
    family = getattr(socket, "AF_UNIX", None)
    if family is None or sock.family != family:
        return False
    try:
        return _verified_bus() == active
    except Exception:
        return False
