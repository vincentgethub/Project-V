"""WZ-06/08: host-only, reversible file and native-keyring application.

Individual renames are atomic. The containing operation restores prior bytes
and entries on exceptions, including Ctrl-C. Power loss between distinct file
renames is not a multi-file transaction; startup configuration validation and
drift checks remain mandatory.
"""

import os
import re
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from pydantic import SecretStr

from backend.core.clock import Clock, ensure_utc
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.security.secrets import SecretStore


def setup_path(project: Path, relative: str) -> Path:
    """WZ-06: only the two specified configuration files may be replaced."""
    if relative not in {".env", "config/config.yaml"}:
        raise ConfigurationError("Setup can only change its environment and research files")
    root = project.absolute()
    path = root / relative
    if root.resolve() != root or any(part.is_symlink() for part in (path, *path.parents)):
        raise ConfigurationError("Setup paths must not cross links or redirected directories")
    if not path.parent.is_dir() or (path.exists() and not path.is_file()):
        raise ConfigurationError("Setup needs the existing project configuration directory")
    return path


def _sync_directory(path: Path) -> None:
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _temp(path: Path, data: bytes) -> Path:
    if type(data) is not bytes or len(data) > 1_048_576:
        raise ConfigurationError("Setup file size exceeds its safe bound")
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".setup-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def setup_application(
    project: Path,
    files: Mapping[str, bytes],
    secrets: Mapping[str, SecretStr | None],
    store: SecretStore,
    clock: Clock,
    changed_names: tuple[str, ...],
    record: Callable[[tuple[str, ...]], None],
    rolled_back: Callable[[tuple[str, ...]], None] | None = None,
) -> Iterator[tuple[Path, ...]]:
    """WZ-06: rollback files, new backups and keyring entries on failed apply.

    The caller holds the ledger transaction while recording CONFIG_APPLIED, so a
    failed audit rolls back its rows alongside these file/keyring changes.
    """
    allowed = {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CALLBACK_SECRET",
        "ALPACA_PAPER_KEY_ID",
        "ALPACA_PAPER_SECRET",
        "FRED_API_KEY",
        "VWS_FINGERPRINT_SALT",
    }
    if (
        not set(secrets) <= allowed
        or any(re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name) is None for name in changed_names)
        or len(set(changed_names)) != len(changed_names)
    ):
        raise ConfigurationError("Setup change inventory is invalid")
    if any(value is not None and not isinstance(value, SecretStr) for value in secrets.values()):
        raise ConfigurationError("Setup credentials must remain masked")
    destinations = {setup_path(project, name): data for name, data in files.items()}
    old_files = {path: path.read_bytes() if path.exists() else None for path in destinations}
    old_secrets = {name: store.get(name) for name in secrets}
    temporaries: list[Path] = []
    backups: list[Path] = []
    touched_files: list[Path] = []
    touched_secrets: list[str] = []
    recorded = False
    stamp = ensure_utc(clock.now()).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex
    try:
        staged: dict[Path, Path] = {}
        for path, data in destinations.items():
            if data == old_files[path]:
                continue
            staged[path] = _temp(path, data)
            temporaries.append(staged[path])
            old = old_files[path]
            if old is not None:
                backup = path.with_name(path.name + ".bak-" + stamp)
                temporary = _temp(backup, old)
                temporaries.append(temporary)
                os.replace(temporary, backup)
                backups.append(backup)
                _sync_directory(path.parent)
        for name, value in secrets.items():
            touched_secrets.append(name)
            if value is None:
                store.delete(name)
            else:
                store.set(name, value)
            if store.get(name) != value:
                raise DataIntegrityError("Saved keyring entry could not be verified")
        for path, temporary in staged.items():
            # Include the path before replacement: an interruption immediately
            # after the native rename must still restore its previous bytes.
            touched_files.append(path)
            os.replace(temporary, path)
            _sync_directory(path.parent)
        record(changed_names)
        recorded = True
        yield tuple(backups)
    except BaseException as failure:
        restoration_failed = False
        for path in reversed(touched_files):
            try:
                old = old_files[path]
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    temporary = _temp(path, old)
                    temporaries.append(temporary)
                    os.replace(temporary, path)
                _sync_directory(path.parent)
            except BaseException:
                restoration_failed = True
        for name in reversed(touched_secrets):
            try:
                old_secret = old_secrets[name]
                if old_secret is None:
                    store.delete(name)
                else:
                    store.set(name, old_secret)
                if store.get(name) != old_secret:
                    restoration_failed = True
            except BaseException:
                restoration_failed = True
        for backup in backups:
            try:
                backup.unlink(missing_ok=True)
            except BaseException:
                restoration_failed = True
        if recorded and rolled_back is not None:
            try:
                rolled_back(changed_names)
            except BaseException:
                restoration_failed = True
        if restoration_failed:
            raise DataIntegrityError(
                "Setup failed; prior files or keyring restoration is UNVERIFIED"
            ) from None
        raise failure
    finally:
        for temporary in temporaries:
            # After a successful rename these paths no longer exist. Cleanup
            # failure must not turn a completed commit into an unaudited error.
            if temporary.exists():
                temporary.unlink()


def apply_setup(
    project: Path,
    files: Mapping[str, bytes],
    secrets: Mapping[str, SecretStr | None],
    store: SecretStore,
    clock: Clock,
    changed_names: tuple[str, ...],
    record: Callable[[tuple[str, ...]], None],
) -> tuple[Path, ...]:
    with setup_application(project, files, secrets, store, clock, changed_names, record) as backups:
        return backups
