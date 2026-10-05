"""SEC-12: portable fake POSIX metadata and read-only Windows ACL probes."""

import os
import stat
from pathlib import Path

import pytest

from backend.core.errors import ConfigurationError
from backend.security import permissions as module
from backend.security.permissions import check_permissions


def metadata(mode: int, *, uid: int = 1001, directory: bool = False) -> os.stat_result:
    """SEC-12: hand-supplied ownership and permission bits need no host ACL."""
    file_type = stat.S_IFDIR if directory else stat.S_IFREG
    return os.stat_result((file_type | mode, 1, 1, 1, uid, 1001, 0, 0, 0, 0))


@pytest.mark.parametrize("mode", ["MANUAL", "AUTO_PAPER", "AUTO_LIVE"])
def test_SEC_12_private_owned_posix_paths_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    env, database = tmp_path / ".env", tmp_path / "ledger.db"
    data, logs, backups = (tmp_path / name for name in ("data", "logs", "backups"))
    records = {env: metadata(0o600), database: metadata(0o600)}
    records.update({item: metadata(0o700, directory=True) for item in (data, logs, backups)})
    monkeypatch.setattr(module, "_posix_metadata", lambda path: records[path])
    results = check_permissions(
        env_file=env,
        db_path=database,
        data_dir=data,
        logs_dir=logs,
        backups_dir=backups,
        mode=mode,
        platform_name="Linux",
        uid=1001,
    )
    assert len(results) == 5
    assert all(item.status == "PASS" for item in results)


@pytest.mark.parametrize("permission_mode,owner", [(0o644, 1001), (0o600, 1002)])
def test_SEC_12_broad_or_foreign_env_warns_manual_and_refuses_auto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    permission_mode: int,
    owner: int,
) -> None:
    monkeypatch.setattr(
        module, "_posix_metadata", lambda _path: metadata(permission_mode, uid=owner)
    )
    result = check_permissions(env_file=tmp_path / ".env", platform_name="Linux", uid=1001)
    assert result[0].status == "WARN"
    for mode in ("AUTO_PAPER", "AUTO_LIVE"):
        with pytest.raises(ConfigurationError, match="private, owned"):
            check_permissions(
                env_file=tmp_path / ".env", platform_name="Linux", uid=1001, mode=mode
            )


@pytest.mark.parametrize("permission_mode", [0o750, 0o755, 0o777, 0o600])
def test_SEC_12_directories_need_exact_private_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    permission_mode: int,
) -> None:
    monkeypatch.setattr(
        module, "_posix_metadata", lambda _path: metadata(permission_mode, directory=True)
    )
    result = check_permissions(data_dir=tmp_path / "data", platform_name="Linux", uid=1001)
    assert result[0].status == "WARN"


@pytest.mark.parametrize("mode", ["MANUAL", "AUTO_PAPER", "AUTO_LIVE"])
def test_SEC_12_world_writable_database_always_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setattr(module, "_posix_metadata", lambda _path: metadata(0o602))
    with pytest.raises(ConfigurationError, match="world-writable"):
        check_permissions(
            db_path=tmp_path / "ledger.db", platform_name="Linux", uid=1001, mode=mode
        )


def test_SEC_12_missing_posix_path_is_unknown_and_never_auto_pass(tmp_path: Path) -> None:
    absent = tmp_path / "absent.env"
    assert (
        check_permissions(env_file=absent, platform_name="Linux", uid=1001)[0].status == "UNKNOWN"
    )
    with pytest.raises(ConfigurationError):
        check_permissions(env_file=absent, platform_name="Linux", uid=1001, mode="AUTO_PAPER")


@pytest.mark.parametrize(
    "group",
    [
        "Everyone",
        "BUILTIN\\Users",
        "NT AUTHORITY\\Authenticated Users",
        "S-1-1-0",
        "S-1-5-32-545",
        "S-1-5-11",
    ],
)
def test_SEC_12_windows_broad_read_warns_without_mutation(tmp_path: Path, group: str) -> None:
    calls: list[Path] = []

    def probe(path: Path) -> str:
        calls.append(path)
        return f"{path} {group}:(I)(OI)(CI)(RX)\nSuccessfully processed 1 files"

    path = tmp_path / ".env"
    for mode in ("MANUAL", "AUTO_PAPER", "AUTO_LIVE"):
        result = check_permissions(
            env_file=path, platform_name="Windows", mode=mode, windows_probe=probe
        )
        assert result[0].status == "WARN"
    assert calls == [path, path, path]
    assert not path.exists()


def test_SEC_12_windows_private_acl_and_unavailable_acl(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    result = check_permissions(
        env_file=path, platform_name="Windows", windows_probe=lambda _path: "owner:(F)"
    )
    assert result[0].status == "PASS"
    assert (
        check_permissions(
            env_file=path, platform_name="Windows", windows_probe=lambda _path: "unreadable"
        )[0].status
        == "UNKNOWN"
    )

    def denied(_path: Path) -> str:
        raise RuntimeError("ACL probe denied")

    assert (
        check_permissions(env_file=path, platform_name="Windows", windows_probe=denied)[0].status
        == "UNKNOWN"
    )


@pytest.mark.parametrize("rights", ["F", "M", "W", "WD,AD", "GW", "GA"])
def test_SEC_12_world_write_windows_database_always_refuses(tmp_path: Path, rights: str) -> None:
    with pytest.raises(ConfigurationError, match="world-writable"):
        check_permissions(
            db_path=tmp_path / "ledger.db",
            platform_name="Windows",
            windows_probe=lambda _path: f"Everyone:(I)({rights})",
        )


def test_SEC_12_unknown_platform_and_mode_fail_closed(tmp_path: Path) -> None:
    result = check_permissions(env_file=tmp_path / ".env", platform_name="Unknown")
    assert result[0].status == "UNKNOWN"
    with pytest.raises(ConfigurationError):
        check_permissions(env_file=tmp_path / ".env", platform_name="Unknown", mode="AUTO_PAPER")
    with pytest.raises(ConfigurationError, match="known"):
        check_permissions(mode="GUESS")
