"""OPS-KS: operator kill-switch file that refuses NEW entries only.

The switch is a file named ``KILL_SWITCH`` inside the private runtime
directory (``<project>/data``, mode 0700 on POSIX). Any directory entry with
that name (regular file, empty file, directory or link) blocks every new entry
before the first broker request. Exits, stop protection, repairs, cancels and
reconciliation never consult it, mirroring HALT/PANIC: halts stop entries and
never trap held exits.

Fail closed: if the switch state cannot be determined (unbound runtime
directory, a runtime directory that is missing, a link, not private or owned by
another user, or any error other than a definite "file not found"), new
entries are refused.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import ExecutionDisabledError

KILL_SWITCH_NAME = "KILL_SWITCH"


@dataclass(frozen=True, slots=True)
class KillSwitch:
    """Reads the kill-switch state; it never creates, writes or removes files."""

    runtime_dir: Path

    @property
    def path(self) -> Path:
        return self.runtime_dir / KILL_SWITCH_NAME

    def _require_private_runtime_dir(self) -> None:
        try:
            metadata = os.lstat(self.runtime_dir)
        except OSError:
            raise ExecutionDisabledError(
                "Kill-switch state is unknown: runtime directory is unreadable; new entries refused"
            ) from None
        if not stat.S_ISDIR(metadata.st_mode):
            raise ExecutionDisabledError(
                "Kill-switch state is unknown: runtime path is not a real directory; "
                "new entries refused"
            )
        if os.name != "nt" and (
            stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != os.geteuid()
        ):
            raise ExecutionDisabledError(
                "Kill-switch state is unknown: runtime directory is not private 0700 "
                "and run-user owned; new entries refused"
            )

    def assert_entries_allowed(self) -> None:
        self._require_private_runtime_dir()
        try:
            os.lstat(self.path)
        except FileNotFoundError:
            return
        except OSError:
            raise ExecutionDisabledError(
                "Kill-switch state is unknown: switch path is unreadable; new entries refused"
            ) from None
        raise ExecutionDisabledError(
            "Kill switch is engaged: remove data/KILL_SWITCH to allow new entries"
        )


class EntryKillSwitchGate:
    """Entry-only gate mixed into the executor; exits never call it.

    The host runtime binds ``kill_switch`` after construction. Unbound means
    the state is unknown, so new entries are refused.
    """

    kill_switch: KillSwitch | None = None

    def _require_entries_not_killed(self) -> None:
        gate = self.kill_switch
        if gate is None:
            raise ExecutionDisabledError(
                "Kill-switch state is unknown: runtime directory is unbound; new entries refused"
            )
        gate.assert_entries_allowed()
