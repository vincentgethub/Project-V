"""SEC-41/70/71: read-only, bounded native host probes; UNKNOWN is not PASS."""

import ctypes
import json
import os
import platform
import re
import subprocess  # nosec B404
from collections.abc import Callable
from pathlib import Path, PureWindowsPath
from typing import Literal, Protocol, cast

from pydantic import Field

from backend.core.errors import ConfigurationError
from backend.domain.models import FrozenModel

HostStatus = Literal["PASS", "WARN", "UNKNOWN"]
ProbeName = Literal["defender", "firewall", "encryption", "sshd", "updates", "mounts"]
Probe = Callable[[ProbeName], str]


class HostFinding(FrozenModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_]+$")
    status: HostStatus
    reason: str = Field(min_length=1, max_length=280)
    fix: str = Field(min_length=1, max_length=280)


class _UserAPI(Protocol):
    def geteuid(self) -> int: ...


def is_privileged() -> bool:
    if os.name == "nt":
        # VERIFY: https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-isuseranadmin
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return cast(_UserAPI, os).geteuid() == 0


def _windows_powershell() -> Path:
    directory = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(directory, len(directory))
    if not 0 < length < len(directory):
        raise ConfigurationError("Native Windows system directory is unavailable")
    return Path(directory.value) / "WindowsPowerShell/v1.0/powershell.exe"


def native_probe(name: ProbeName) -> str:
    """SEC-71: no shell interpolation, network, writes, elevation or window."""
    if os.name == "nt":
        commands = {
            # VERIFY: https://learn.microsoft.com/en-us/powershell/module/defender/get-mpcomputerstatus
            "defender": "Get-MpComputerStatus -ErrorAction Stop | Select-Object AMServiceEnabled,AntivirusEnabled,RealTimeProtectionEnabled | ConvertTo-Json -Compress",
            # VERIFY: https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallprofile
            "firewall": "Get-NetFirewallProfile -ErrorAction Stop | Select-Object Name,Enabled | ConvertTo-Json -Compress",
            # VERIFY: https://learn.microsoft.com/en-us/powershell/module/bitlocker/get-bitlockervolume
            "encryption": "Get-BitLockerVolume -ErrorAction Stop | Select-Object MountPoint,ProtectionStatus,EncryptionPercentage | ConvertTo-Json -Compress",
        }
        if name not in commands:
            raise ConfigurationError("This host probe is unavailable on Windows")
        argv = [
            str(_windows_powershell()),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            commands[name],
        ]
    else:
        commands_linux = {
            # Effective sshd configuration includes sshd_config.d; Match blocks
            # remain UNKNOWN below because a single default context is not enough.
            # VERIFY: https://man.openbsd.org/sshd.8
            "sshd": ["/usr/sbin/sshd", "-T"],
            "firewall": ["/usr/sbin/ufw", "status"],
            "updates": ["/usr/bin/apt-config", "dump"],
            # VERIFY: https://man7.org/linux/man-pages/man8/lsblk.8.html
            "encryption": ["/usr/bin/lsblk", "--json", "--output", "NAME,TYPE,MOUNTPOINTS"],
            "mounts": ["/usr/bin/findmnt", "--json", "--output", "TARGET,SOURCE,FSTYPE"],
        }
        if name not in commands_linux:
            raise ConfigurationError("This host probe is unavailable on Linux")
        argv = commands_linux[name]
    result = subprocess.run(  # nosec B603
        argv,
        shell=False,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if result.returncode != 0 or not result.stdout.strip() or len(result.stdout) > 1_048_576:
        raise ConfigurationError("Native host status could not be read")
    return result.stdout


def _json_rows(text: str) -> list[dict[str, object]]:
    value = json.loads(text)
    rows = [value] if isinstance(value, dict) else value
    if (
        not isinstance(rows, list)
        or not 1 <= len(rows) <= 1000
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise ValueError("native host JSON is unavailable")
    return rows


def inspect_host(
    data_dir: Path,
    *,
    system: str | None = None,
    probe: Probe = native_probe,
    privileged: Callable[[], bool] = is_privileged,
    ssh_config_files: tuple[Path, ...] | None = None,
) -> tuple[HostFinding, ...]:
    """SEC-71: use explicit fakes in tests; native probes never change settings."""
    selected = platform.system() if system is None else system
    findings: list[HostFinding] = []

    def collect(name: str, fix: str, action: Callable[[], tuple[HostStatus, str]]) -> None:
        try:
            status, reason = action()
            finding = HostFinding(name=name, status=status, reason=reason, fix=fix)
        except Exception:
            finding = HostFinding(
                name=name,
                status="UNKNOWN",
                reason="This read-only host check could not be verified.",
                fix=fix,
            )
        findings.append(finding)

    def admin() -> tuple[HostStatus, str]:
        value = privileged()
        if type(value) is not bool:
            raise ValueError("privilege result is not boolean")
        return (
            ("WARN", "Process runs as administrator or root.")
            if value
            else ("PASS", "Process runs as a standard user.")
        )

    collect(
        "administrator",
        "Run Project V under a dedicated standard user; live refuses admin/root.",
        admin,
    )
    if selected == "Windows":

        def defender() -> tuple[HostStatus, str]:
            rows = _json_rows(probe("defender"))
            if len(rows) != 1:
                raise ValueError("Defender status is ambiguous")
            values = [
                rows[0].get(name)
                for name in ("AMServiceEnabled", "AntivirusEnabled", "RealTimeProtectionEnabled")
            ]
            if any(type(value) is not bool for value in values):
                raise ValueError("Defender status is unavailable")
            return (
                ("PASS", "Defender antivirus and realtime protection are enabled.")
                if all(values)
                else ("WARN", "Defender protection is disabled.")
            )

        def firewall_windows() -> tuple[HostStatus, str]:
            rows = _json_rows(probe("firewall"))
            if (
                {row.get("Name") for row in rows} != {"Domain", "Private", "Public"}
                or len(rows) != 3
                or any(type(row.get("Enabled")) is not bool for row in rows)
            ):
                raise ValueError("Firewall profiles are unavailable")
            return (
                ("PASS", "All three Windows firewall profiles are enabled.")
                if all(row["Enabled"] for row in rows)
                else ("WARN", "A Windows firewall profile is disabled.")
            )

        def encryption_windows() -> tuple[HostStatus, str]:
            drive = PureWindowsPath(str(data_dir)).drive.upper()
            rows = [
                row for row in _json_rows(probe("encryption")) if row.get("MountPoint") == drive
            ]
            if (
                len(rows) != 1
                or type(rows[0].get("ProtectionStatus")) is not int
                or type(rows[0].get("EncryptionPercentage")) is not int
            ):
                raise ValueError("Data volume BitLocker status is unavailable")
            safe = rows[0]["ProtectionStatus"] == 1 and rows[0]["EncryptionPercentage"] == 100
            return (
                ("PASS", "The data volume is encrypted and BitLocker protection is on.")
                if safe
                else ("WARN", "The data volume is not fully protected by BitLocker.")
            )

        collect(
            "defender", "Enable Defender and realtime protection in Windows Security.", defender
        )
        collect(
            "firewall", "Enable Domain, Private and Public firewall profiles.", firewall_windows
        )
        collect(
            "disk_encryption",
            "Check BitLocker for the data volume; save its recovery key off-box.",
            encryption_windows,
        )
    elif selected == "Linux":

        def ssh() -> tuple[HostStatus, str]:
            text = probe("sshd")
            values = dict(
                re.findall(r"(?m)^(passwordauthentication|permitrootlogin)\s+(\S+)\s*$", text)
            )
            if set(values) != {"passwordauthentication", "permitrootlogin"}:
                raise ValueError("Effective SSH configuration is unavailable")
            # A readable effective default configuration does not certify every
            # Match context. The host runbook also requires auditing those blocks.
            config_files = (
                ssh_config_files
                if ssh_config_files is not None
                else (
                    Path("/etc/ssh/sshd_config"),
                    *sorted(Path("/etc/ssh/sshd_config.d").glob("*.conf")),
                )
            )
            for path in config_files:
                if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_048_576:
                    raise ValueError("SSH include provenance is unavailable")
                contents = path.read_text(encoding="utf-8")
                if re.search(r"(?im)^\s*Match\s+", contents):
                    raise ValueError("SSH Match contexts need owner review")
                includes = re.findall(r"(?im)^\s*Include\s+([^#\r\n]+)", contents)
                if includes and (
                    path != Path("/etc/ssh/sshd_config")
                    or any(value.strip() != "/etc/ssh/sshd_config.d/*.conf" for value in includes)
                ):
                    raise ValueError("SSH custom or recursive includes need owner review")
            return (
                ("PASS", "Effective SSH disables passwords and root login.")
                if all(value == "no" for value in values.values())
                else ("WARN", "Effective SSH permits passwords or root login.")
            )

        def firewall_linux() -> tuple[HostStatus, str]:
            text = probe("firewall")
            if re.search(r"(?m)^Status: active\s*$", text):
                return "PASS", "UFW is active; review inbound SSH-only policy in the runbook."
            if re.search(r"(?m)^Status: inactive\s*$", text):
                return "WARN", "UFW is inactive."
            raise ValueError("Firewall status is unavailable")

        def updates() -> tuple[HostStatus, str]:
            text = probe("updates")
            values = dict(
                re.findall(
                    r'(?m)^APT::Periodic::(Unattended-Upgrade|Update-Package-Lists) "([0-9]+)";\s*$',
                    text,
                )
            )
            if len(values) != 2:
                raise ValueError("Automatic update policy is unavailable")
            return (
                ("PASS", "Daily package-list refresh and unattended upgrades are configured.")
                if all(value == "1" for value in values.values())
                else ("WARN", "Daily unattended upgrades are not configured.")
            )

        def encryption_linux() -> tuple[HostStatus, str]:
            mounts = json.loads(probe("mounts"))
            blocks = json.loads(probe("encryption"))
            if not isinstance(mounts, dict) or not isinstance(blocks, dict):
                raise ValueError("Linux storage metadata is unavailable")
            data = data_dir.resolve(strict=True)
            matches: list[Path] = []
            pending = list(mounts.get("filesystems", []))
            seen = 0
            while pending:
                row = pending.pop()
                seen += 1
                if (
                    seen > 1000
                    or not isinstance(row, dict)
                    or not isinstance(row.get("target"), str)
                ):
                    raise ValueError("Linux mount inventory is malformed")
                mount = Path(row["target"])
                if data.is_relative_to(mount):
                    matches.append(mount)
                pending.extend(row.get("children", []))
            if not matches:
                raise ValueError("Data mount is unavailable")
            target = max(matches, key=lambda item: len(item.parts))
            protections: list[bool] = []
            queue = [(row, False) for row in blocks.get("blockdevices", [])]
            seen = 0
            while queue:
                row, encrypted = queue.pop()
                seen += 1
                if seen > 1000 or not isinstance(row, dict):
                    raise ValueError("Linux block inventory is malformed")
                encrypted = encrypted or row.get("type") == "crypt"
                points = row.get("mountpoints")
                if points is not None and not isinstance(points, list):
                    raise ValueError("Linux mount points are malformed")
                if isinstance(points, list) and any(
                    isinstance(point, str) and Path(point) == target for point in points
                ):
                    protections.append(encrypted)
                queue.extend((child, encrypted) for child in row.get("children", []))
            if len(protections) != 1:
                raise ValueError("Data mount encryption is ambiguous")
            return (
                ("PASS", "The data mount has a crypt device ancestor.")
                if protections[0]
                else ("WARN", "The data mount has no observed crypt device ancestor.")
            )

        collect(
            "sshd",
            "Audit sshd_config and includes; require SSH keys, no passwords or root login.",
            ssh,
        )
        collect(
            "firewall", "Enable the firewall and allow only necessary inbound SSH.", firewall_linux
        )
        collect(
            "automatic_updates",
            "Configure unattended upgrades and verify their last successful run.",
            updates,
        )
        collect(
            "disk_encryption",
            "Use LUKS for the data device; save its recovery material off-box.",
            encryption_linux,
        )
    else:
        findings.append(
            HostFinding(
                name="supported_host",
                status="UNKNOWN",
                reason="Only Windows and Linux host checks are supported.",
                fix="Use a supported standard-user host and rerun doctor.",
            )
        )
    return tuple(findings)
