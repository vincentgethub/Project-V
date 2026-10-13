"""SEC-12: read-only filesystem permission probes with mode-dependent refusal."""

from __future__ import annotations

import ctypes
import os
import platform
import re
import stat

# SEC-12 requires the read-only native ACL utility; no shell is used.
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from backend.core.errors import ConfigurationError

_BROAD_ACL = re.compile(
    r"(?:Everyone|BUILTIN\\Users|NT AUTHORITY\\Authenticated Users|"
    r"S-1-1-0|S-1-5-32-545|S-1-5-11)\s*:\s*((?:\([^)]*\))+)",
    re.IGNORECASE,
)
_READ_RIGHTS = frozenset({"F", "M", "RX", "R", "GR", "GA", "RD"})
_WRITE_RIGHTS = frozenset({"F", "M", "W", "GW", "GA", "WD", "AD"})


class _PosixUserAPI(Protocol):
    """SEC-12: this OS method is reached only on a POSIX platform."""

    def getuid(self) -> int:
        """SEC-12: return the process owner identifier."""
        raise NotImplementedError("POSIX user identity is required")


@dataclass(frozen=True, slots=True)
class PermissionFinding:
    """SEC-12: UNKNOWN never means the owner has safe permissions."""

    path: Path
    status: Literal["PASS", "WARN", "UNKNOWN"]
    reason: str


def _windows_acl(path: Path) -> str:
    """SEC-12: icacls without mutation flags reads the current Windows ACL."""
    # VERIFY: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls
    if sys.platform != "win32":
        raise ConfigurationError("Windows ACL probe is unavailable on this platform")
    # VERIFY: https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getsystemdirectoryw
    directory = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(directory, len(directory))
    if not 0 < length < len(directory):
        raise ConfigurationError("Windows system directory could not be verified")
    executable = Path(directory.value) / "icacls.exe"
    # Absolute native utility, fixed read-only argv, and no shell.
    result = subprocess.run(  # nosec B603
        [str(executable), str(path)],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if result.returncode != 0:
        raise ConfigurationError("Windows file ACL could not be read")
    return result.stdout


def _acl_finding(path: Path, text: str, *, database: bool) -> PermissionFinding:
    """SEC-12: broad Windows read permissions WARN; world-write DB refuses."""
    if not isinstance(text, str) or not text.strip() or ":(" not in text.replace(" ", ""):
        return PermissionFinding(path, "UNKNOWN", "Windows ACL permissions could not be verified")
    broad_read = False
    for entry in _BROAD_ACL.finditer(text):
        rights = {
            right.strip().upper()
            for group in re.findall(r"\(([^)]*)\)", entry.group(1))
            for right in group.split(",")
        }
        if (
            database
            and entry.group(0).casefold().startswith(("everyone", "s-1-1-0"))
            and rights.intersection(_WRITE_RIGHTS)
        ):
            raise ConfigurationError("world-writable database is always refused")
        broad_read = broad_read or bool(rights.intersection(_READ_RIGHTS))
    if broad_read:
        return PermissionFinding(path, "WARN", "A broad Windows group can read this path")
    return PermissionFinding(path, "PASS", "No broad read permission found in the Windows ACL")


def _posix_metadata(path: Path) -> os.stat_result:
    """SEC-12: isolate the read-only POSIX probe for portable fake tests."""
    return path.stat()


def _run_uid() -> int:
    """SEC-12: retrieve the POSIX run user without a Windows-only import."""
    return cast(_PosixUserAPI, os).getuid()


def check_permissions(
    *,
    env_file: Path | None = None,
    data_dir: Path | None = None,
    logs_dir: Path | None = None,
    backups_dir: Path | None = None,
    db_path: Path | None = None,
    mode: str = "MANUAL",
    platform_name: str | None = None,
    windows_probe: Callable[[Path], str] | None = None,
    uid: int | None = None,
) -> tuple[PermissionFinding, ...]:
    """SEC-12: inspect supplied paths only; never chmod, chown or read contents.

    POSIX warnings refuse AUTO_*. Windows permission probes are warnings only,
    except a positively world-writable database is always refused.
    """
    if mode not in {"MANUAL", "AUTO_PAPER", "AUTO_LIVE"}:
        raise ConfigurationError("permission validation requires a known execution mode")
    system = platform.system() if platform_name is None else platform_name
    paths = (
        (env_file, "env"),
        (data_dir, "directory"),
        (logs_dir, "directory"),
        (backups_dir, "directory"),
        (db_path, "database"),
    )
    findings: list[PermissionFinding] = []
    for path, kind in paths:
        if path is None:
            continue
        path = Path(path)
        if system == "Windows":
            try:
                probe = _windows_acl if windows_probe is None else windows_probe
                findings.append(_acl_finding(path, probe(path), database=kind == "database"))
            except ConfigurationError as exc:
                if "world-writable" in str(exc):
                    raise
                findings.append(
                    PermissionFinding(path, "UNKNOWN", "Windows ACL probe is unavailable")
                )
            except Exception:
                findings.append(
                    PermissionFinding(path, "UNKNOWN", "Windows ACL probe is unavailable")
                )
            continue
        if system not in {"Linux", "Darwin", "FreeBSD"}:
            findings.append(
                PermissionFinding(path, "UNKNOWN", "Filesystem permission probe is unsupported")
            )
            continue
        try:
            if path.is_symlink():
                raise ConfigurationError("Permission path must not be a symbolic link")
            metadata = _posix_metadata(path)
            permission_mode = stat.S_IMODE(metadata.st_mode)
            run_uid = _run_uid() if uid is None else uid
            if kind == "database" and permission_mode & 0o002:
                raise ConfigurationError("world-writable database is always refused")
            valid_type = (
                stat.S_ISDIR(metadata.st_mode)
                if kind == "directory"
                else stat.S_ISREG(metadata.st_mode)
            )
            private = (
                permission_mode == 0o700 if kind == "directory" else not permission_mode & 0o077
            )
            safe = valid_type and private and metadata.st_uid == run_uid
            findings.append(
                PermissionFinding(
                    path,
                    "PASS" if safe else "WARN",
                    "Private permissions and run-user ownership"
                    if safe
                    else "Permissions or ownership are too broad",
                )
            )
        except ConfigurationError as exc:
            if "world-writable" in str(exc):
                raise
            findings.append(PermissionFinding(path, "WARN", "Permission path cannot be trusted"))
        except Exception:
            findings.append(
                PermissionFinding(path, "UNKNOWN", "Filesystem permissions could not be read")
            )
    if (
        system != "Windows"
        and mode.startswith("AUTO_")
        and any(item.status != "PASS" for item in findings)
    ):
        raise ConfigurationError("AUTO mode requires private, owned filesystem paths")
    return tuple(findings)
