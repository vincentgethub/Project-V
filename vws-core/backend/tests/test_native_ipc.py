"""SEC-11/32: fake native calls certify scope, never open a user-bus connection."""

import os
import platform
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.errors import ConfigurationError, EgressDeniedError
from backend.core.ledger import Ledger
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist
from backend.security import native_ipc, secrets
from backend.tests.test_secrets import FakeNative

BUS = "/run/user/10001/bus"


class FakeSocket:
    """Portable Unix-shaped object; no socket is opened on Windows."""

    family = 1

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, *_args: object) -> None:
        pass


def fake_socket_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native_ipc, "socket", SimpleNamespace(AF_UNIX=1, SocketType=FakeSocket))


@pytest.mark.parametrize(
    "fault",
    [
        "",
        "address",
        "alternate",
        "abstract",
        "tcp",
        "escape",
        "guid",
        "root",
        "symlink",
        "file",
        "owner",
        "parent_owner",
        "parent_mode",
        "missing",
    ],
)
def test_SEC_11_native_bus_metadata_is_exact(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0 if fault == "root" else 10001, raising=False)
    addresses = {
        "address": "unix:path=/tmp/bus",
        "alternate": f"unix:path={BUS};unix:path=/tmp/bus",
        "abstract": "unix:abstract=bus",
        "tcp": "tcp:host=example.com,port=443",
        "escape": "unix:path=/run/user/10001/%62us",
        "guid": f"unix:path={BUS},guid=bad",
    }
    monkeypatch.setenv(
        "DBUS_SESSION_BUS_ADDRESS", addresses.get(fault, f"unix:path={BUS},guid={'a' * 32}")
    )

    class FakePath:
        parent: Any
        parents: tuple[Any, ...] = ()

        def is_symlink(self) -> bool:
            return fault == "symlink"

        def lstat(self) -> Any:
            if fault == "missing":
                raise FileNotFoundError("fake bus absent")
            return SimpleNamespace(
                st_mode=0o100600 if fault == "file" else 0o140600,
                st_uid=10002 if fault == "owner" else 10001,
            )

    path = FakePath()
    path.parent = SimpleNamespace(
        lstat=lambda: SimpleNamespace(
            st_mode=0o040777 if fault == "parent_mode" else 0o040700,
            st_uid=10002 if fault == "parent_owner" else 10001,
        )
    )
    monkeypatch.setattr(native_ipc, "Path", lambda _value: path)
    if fault:
        with pytest.raises((ConfigurationError, FileNotFoundError)):
            native_ipc._verified_bus()
    else:
        assert native_ipc._verified_bus() == BUS


def test_SEC_32_only_native_call_thread_can_connect_and_scope_always_clears(
    engine: Engine,
    clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = SDKSocketGuard(EgressPolicy(build_allowlist(), Ledger(engine, clock)))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(native_ipc, "_verified_bus", lambda: BUS)
    fake_socket_api(monkeypatch)
    with FakeSocket() as sock:
        assert not native_ipc.native_connection_allowed(sock, BUS)
        with pytest.raises(EgressDeniedError):
            guard.audit("socket.connect", (sock, BUS))
        with native_ipc.native_keyring_call():
            guard.audit("socket.connect", (sock, BUS))
            for address in ["/tmp/bus", "\x00bus", ("8.8.8.8", 443)]:
                with pytest.raises(EgressDeniedError):
                    guard.audit("socket.connect", (sock, address))
            with pytest.raises(EgressDeniedError):
                guard.audit("socket.bind", (sock, BUS))
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert not pool.submit(native_ipc.native_connection_allowed, sock, BUS).result()
            monkeypatch.setattr(native_ipc, "_verified_bus", lambda: "/run/user/10002/bus")
            assert not native_ipc.native_connection_allowed(sock, BUS)
        monkeypatch.setattr(native_ipc, "_verified_bus", lambda: BUS)
        with pytest.raises(RuntimeError), native_ipc.native_keyring_call():
            raise RuntimeError("fake native failure")
        assert not native_ipc.native_connection_allowed(sock, BUS)
    guard.policy.ledger.verify_chain()


@pytest.mark.parametrize("operation", ["get", "set", "delete"])
def test_SEC_11_store_scopes_each_native_operation(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(native_ipc, "_verified_bus", lambda: BUS)
    fake_socket_api(monkeypatch)
    with FakeSocket() as sock:

        class ScopedNative(FakeNative):
            def get_password(self, service: str, username: str) -> str | None:
                assert native_ipc.native_connection_allowed(sock, BUS)
                return super().get_password(service, username)

            def set_password(self, service: str, username: str, password: str) -> None:
                assert native_ipc.native_connection_allowed(sock, BUS)
                super().set_password(service, username, password)

            def delete_password(self, service: str, username: str) -> None:
                assert native_ipc.native_connection_allowed(sock, BUS)
                super().delete_password(service, username)

        backend = ScopedNative()
        backend.values["vws-core:FERNET_KEY", "vws"] = "TEST_ONLY_NOT_A_CREDENTIAL"
        monkeypatch.setattr(secrets, "_native_backend", lambda: backend)
        store = secrets.KeyringSecretStore()
        if operation == "get":
            assert store.get("FERNET_KEY") is not None
        elif operation == "set":
            store.set("FERNET_KEY", SecretStr("TEST_ONLY_NOT_A_CREDENTIAL"))
        else:
            store.delete("FERNET_KEY")
        assert not native_ipc.native_connection_allowed(sock, BUS)


def test_SEC_11_bus_validation_failure_never_calls_native_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    def denied() -> str:
        raise ConfigurationError("fake missing user bus")

    monkeypatch.setattr(native_ipc, "_verified_bus", denied)
    native = FakeNative()
    monkeypatch.setattr(secrets, "_native_backend", lambda: native)
    with pytest.raises(ConfigurationError):
        secrets.KeyringSecretStore().set("FERNET_KEY", SecretStr("TEST_ONLY_NOT_A_CREDENTIAL"))
    assert not native.values
