"""SEC-41/71: mocked native probes; no real host is certified by tests."""

import json
from pathlib import Path

import pytest

from backend.ops.host import ProbeName, inspect_host


def test_SEC_71_windows_green_mocked_statuses() -> None:
    data = {
        "defender": {
            "AMServiceEnabled": True,
            "AntivirusEnabled": True,
            "RealTimeProtectionEnabled": True,
        },
        "firewall": [{"Name": name, "Enabled": True} for name in ("Domain", "Private", "Public")],
        "encryption": {"MountPoint": "C:", "ProtectionStatus": 1, "EncryptionPercentage": 100},
    }

    def probe(name: ProbeName) -> str:
        return json.dumps(data[name])

    result = inspect_host(Path("C:/data"), system="Windows", probe=probe, privileged=lambda: False)
    assert len(result) == 4 and all(row.status == "PASS" for row in result)


@pytest.mark.parametrize(
    "fault",
    [
        "admin",
        "defender_off",
        "defender_missing",
        "firewall_off",
        "firewall_missing",
        "encryption_off",
        "encryption_missing",
        "bad_json",
        "unavailable",
    ],
)
def test_SEC_71_windows_bad_or_unknown_is_not_pass(fault: str) -> None:
    data: dict[str, object] = {
        "defender": {
            "AMServiceEnabled": True,
            "AntivirusEnabled": True,
            "RealTimeProtectionEnabled": True,
        },
        "firewall": [{"Name": name, "Enabled": True} for name in ("Domain", "Private", "Public")],
        "encryption": {"MountPoint": "C:", "ProtectionStatus": 1, "EncryptionPercentage": 100},
    }
    if fault == "defender_off":
        data["defender"] = {
            "AMServiceEnabled": True,
            "AntivirusEnabled": True,
            "RealTimeProtectionEnabled": False,
        }
    elif fault == "defender_missing":
        data["defender"] = {"AntivirusEnabled": True}
    elif fault == "firewall_off":
        data["firewall"] = [
            {"Name": name, "Enabled": name != "Public"} for name in ("Domain", "Private", "Public")
        ]
    elif fault == "firewall_missing":
        data["firewall"] = [{"Name": "Private", "Enabled": True}]
    elif fault == "encryption_off":
        data["encryption"] = {
            "MountPoint": "C:",
            "ProtectionStatus": 0,
            "EncryptionPercentage": 100,
        }
    elif fault == "encryption_missing":
        data["encryption"] = {
            "MountPoint": "D:",
            "ProtectionStatus": 1,
            "EncryptionPercentage": 100,
        }

    def probe(name: ProbeName) -> str:
        if fault == "unavailable":
            raise OSError("injected probe unavailable")
        return "invalid" if fault == "bad_json" else json.dumps(data[name])

    result = inspect_host(
        Path("C:/data"), system="Windows", probe=probe, privileged=lambda: fault == "admin"
    )
    assert any(row.status != "PASS" for row in result)
    assert all(row.fix for row in result)


@pytest.mark.parametrize(
    "fault",
    [
        "",
        "ssh_password",
        "ssh_match",
        "ssh_include",
        "ssh_missing",
        "firewall_off",
        "updates_off",
        "updates_missing",
        "not_encrypted",
        "bad_json",
    ],
)
def test_SEC_71_linux_status_and_unknowns(tmp_path: Path, fault: str) -> None:
    ssh_config = tmp_path / "sshd_config"
    ssh_config.write_text(
        "Match User guest\n"
        if fault == "ssh_match"
        else "Include /tmp/unreviewed/*.conf\n"
        if fault == "ssh_include"
        else "PasswordAuthentication no\nPermitRootLogin no\n",
        encoding="utf-8",
    )
    source = {
        "sshd": "passwordauthentication yes\npermitrootlogin no\n"
        if fault == "ssh_password"
        else "wrong"
        if fault == "ssh_missing"
        else "passwordauthentication no\npermitrootlogin no\n",
        "firewall": "Status: inactive" if fault == "firewall_off" else "Status: active",
        "updates": 'APT::Periodic::Unattended-Upgrade "0";\nAPT::Periodic::Update-Package-Lists "1";'
        if fault == "updates_off"
        else "wrong"
        if fault == "updates_missing"
        else 'APT::Periodic::Unattended-Upgrade "1";\nAPT::Periodic::Update-Package-Lists "1";',
        "mounts": json.dumps(
            {"filesystems": [{"target": tmp_path.as_posix(), "source": "device", "fstype": "ext4"}]}
        ),
        "encryption": json.dumps(
            {
                "blockdevices": [
                    {
                        "name": "device",
                        "type": "disk" if fault == "not_encrypted" else "crypt",
                        "mountpoints": [tmp_path.as_posix()],
                    }
                ]
            }
        ),
    }

    def probe(name: ProbeName) -> str:
        return "invalid" if fault == "bad_json" else source[name]

    result = inspect_host(
        tmp_path,
        system="Linux",
        probe=probe,
        privileged=lambda: False,
        ssh_config_files=(ssh_config,),
    )
    assert len(result) == 5
    if fault:
        assert any(row.status != "PASS" for row in result)
    else:
        assert all(row.status == "PASS" for row in result)


def test_SEC_71_unsupported_host_and_unknown_privilege_are_explicit(tmp_path: Path) -> None:
    def unavailable() -> bool:
        raise OSError("injected probe unavailable")

    result = inspect_host(tmp_path, system="unsupported", privileged=unavailable)
    assert all(row.status == "UNKNOWN" for row in result)
