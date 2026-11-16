"""OPS-KS: data/KILL_SWITCH refuses new entries only and fails closed."""

import ast
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import SecurityEvent
from backend.core.errors import EntryAdmissionRevoked, ExecutionDisabledError
from backend.execution import kill_switch as module
from backend.execution.alpaca_executor import AlpacaExecutor, ExactLimit, ExactStop
from backend.execution.kill_switch import KILL_SWITCH_NAME, EntryKillSwitchGate, KillSwitch
from backend.tests.test_auto_execution import (
    AUTO,
    FakeTradingClient,
    executor,
    fill_entry,
    journal_existing_partial_repair,
)
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness
PROJECT = Path(__file__).resolve().parents[2]


def private(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    path.chmod(0o700)
    return path


def test_OPS_KS_absent_switch_allows_entries_and_never_writes(tmp_path: Path) -> None:
    runtime = private(tmp_path / "data")
    switch = KillSwitch(runtime)
    assert switch.path == runtime / "KILL_SWITCH" and KILL_SWITCH_NAME == "KILL_SWITCH"
    switch.assert_entries_allowed()
    assert list(runtime.iterdir()) == []


@pytest.mark.parametrize("kind", ["file", "empty", "directory", "dangling_link"])
def test_OPS_KS_any_switch_entry_blocks_new_entries(tmp_path: Path, kind: str) -> None:
    runtime = private(tmp_path / "data")
    target = runtime / KILL_SWITCH_NAME
    if kind == "file":
        target.write_text("maintenance by owner\n", encoding="utf-8")
    elif kind == "empty":
        target.touch()
    elif kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "missing")
    with pytest.raises(ExecutionDisabledError) as caught:
        KillSwitch(runtime).assert_entries_allowed()
    assert str(caught.value) == (
        "Kill switch is engaged: remove data/KILL_SWITCH to allow new entries"
    )


def test_OPS_KS_missing_runtime_directory_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ExecutionDisabledError, match="runtime directory is unreadable"):
        KillSwitch(tmp_path / "absent").assert_entries_allowed()


@pytest.mark.parametrize("kind", ["file", "link"])
def test_OPS_KS_runtime_path_must_be_a_real_directory(tmp_path: Path, kind: str) -> None:
    runtime = tmp_path / "data"
    if kind == "file":
        runtime.write_text("", encoding="utf-8")
    else:
        runtime.symlink_to(private(tmp_path / "real"), target_is_directory=True)
    with pytest.raises(ExecutionDisabledError, match="not a real directory"):
        KillSwitch(runtime).assert_entries_allowed()


@pytest.mark.parametrize("mode", [0o750, 0o755, 0o500, 0o000])
def test_OPS_KS_runtime_directory_must_be_private(tmp_path: Path, mode: int) -> None:
    runtime = private(tmp_path / "data")
    runtime.chmod(mode)
    try:
        with pytest.raises(ExecutionDisabledError, match="not private 0700"):
            KillSwitch(runtime).assert_entries_allowed()
    finally:
        runtime.chmod(0o700)


def test_OPS_KS_runtime_directory_owned_by_another_user_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = private(tmp_path / "data")
    other = os.geteuid() + 1
    monkeypatch.setattr(module.os, "geteuid", lambda: other)
    with pytest.raises(ExecutionDisabledError, match="run-user owned"):
        KillSwitch(runtime).assert_entries_allowed()


def test_OPS_KS_unreadable_switch_state_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = private(tmp_path / "data")
    real = os.lstat

    def denied(path: Any) -> os.stat_result:
        if Path(path).name == KILL_SWITCH_NAME:
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(module.os, "lstat", denied)
    with pytest.raises(ExecutionDisabledError) as caught:
        KillSwitch(runtime).assert_entries_allowed()
    assert str(caught.value) == (
        "Kill-switch state is unknown: switch path is unreadable; new entries refused"
    )


def test_OPS_KS_windows_ignores_posix_mode_bits_but_still_reads_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = private(tmp_path / "data")
    runtime.chmod(0o755)
    monkeypatch.setattr(module.os, "name", "nt")
    KillSwitch(runtime).assert_entries_allowed()
    (runtime / KILL_SWITCH_NAME).touch()
    with pytest.raises(ExecutionDisabledError, match="engaged"):
        KillSwitch(runtime).assert_entries_allowed()


def test_OPS_KS_unbound_gate_fails_closed() -> None:
    gate = EntryKillSwitchGate()
    gate.kill_switch = None
    with pytest.raises(ExecutionDisabledError) as caught:
        gate._require_entries_not_killed()
    assert str(caught.value) == (
        "Kill-switch state is unknown: runtime directory is unbound; new entries refused"
    )


def test_OPS_KS_executor_mixes_in_the_entry_gate() -> None:
    assert issubclass(AlpacaExecutor, EntryKillSwitchGate)


class CountingClient(FakeTradingClient):
    """Records every broker method, including reads, before any response."""

    def __init__(self, h: Harness) -> None:
        super().__init__(h)
        self.calls: list[str] = []

    def __getattribute__(self, name: str) -> Any:
        value = super().__getattribute__(name)
        if callable(value) and not name.startswith("_") and name not in {"calls", "h"}:
            super().__getattribute__("calls").append(name)
        return value


def engaged(h: Harness, built: AlpacaExecutor, tmp_path: Path) -> Path:
    runtime = private(tmp_path / "data")
    built.kill_switch = KillSwitch(runtime)
    return runtime / KILL_SWITCH_NAME


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_OPS_KS_engaged_switch_refuses_entry_before_any_broker_call(
    harness: Harness, tmp_path: Path
) -> None:
    alert = await deliver(harness)
    client = CountingClient(harness)
    built = executor(harness, client)
    switch = engaged(harness, built, tmp_path)
    switch.write_text("owner maintenance\n", encoding="utf-8")
    client.calls.clear()
    with pytest.raises(ExecutionDisabledError, match="Kill switch is engaged"):
        await built.enter(alert.proposal_id)
    assert client.calls == [] and client.posts == [] and client.lookups == []
    with Session(harness.state.engine) as session:
        blocked = session.scalars(
            select(SecurityEvent).where(SecurityEvent.kind == "AUTO_ENTRY_BLOCKED")
        ).all()
    assert len(blocked) == 1
    assert blocked[0].detail["reason"].startswith("Kill switch is engaged")
    assert switch.read_text(encoding="utf-8") == "owner maintenance\n"
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_OPS_KS_unbound_executor_refuses_entry_before_any_broker_call(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = CountingClient(harness)
    built = executor(harness, client)
    built.kill_switch = None
    client.calls.clear()
    with pytest.raises(ExecutionDisabledError, match="runtime directory is unbound"):
        await built.enter(alert.proposal_id)
    assert client.calls == [] and client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_OPS_KS_switch_engaged_mid_admission_revokes_before_physical_send(
    harness: Harness, tmp_path: Path
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    switch = engaged(harness, built, tmp_path)

    async def owner_engages(_proposal_id: object) -> None:
        switch.touch()

    built.realtime_entry = owner_engages
    with pytest.raises(EntryAdmissionRevoked, match="Kill switch is engaged"):
        await built.enter(alert.proposal_id)
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_OPS_KS_final_guard_revokes_between_intent_and_physical_request(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alert = await deliver(harness)
    sent: list[str] = []

    class Broker(FakeTradingClient):
        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            sent.append(order_data.client_order_id)
            return super().submit_order(order_data)

    client = Broker(harness)
    built = executor(harness, client)
    switch = engaged(harness, built, tmp_path)
    original = built._submit

    async def engage_then_submit(*args: Any, **kwargs: Any) -> Any:
        switch.touch()
        return await original(*args, **kwargs)

    monkeypatch.setattr(built, "_submit", engage_then_submit)
    with pytest.raises(EntryAdmissionRevoked, match="Kill switch is engaged"):
        await built.enter(alert.proposal_id)
    assert sent == [] and client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_OPS_KS_engaged_switch_never_traps_stop_repair_or_monitoring(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    switch = engaged(h, built, tmp_path)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)
    journal_existing_partial_repair(built)
    switch.write_text("stop new entries\n", encoding="utf-8")
    await built.monitor()
    assert parent["status"] == "canceled"
    assert len(client.posts) == 2
    assert client.posts[1]["type"] == "stop" and client.posts[1]["qty"] == "1"
    with pytest.raises(ExecutionDisabledError, match="Kill switch is engaged"):
        await built.enter(alert.proposal_id)
    assert len(client.posts) == 2
    h.state.ledger.verify_chain()
    await built.close()


def test_OPS_KS_host_runtime_binds_the_private_data_directory() -> None:
    tree = ast.parse((PROJECT / "vws/runtime_cli.py").read_text(encoding="utf-8"))
    compose = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "compose" and node.body[1:]
    )
    bindings = [
        node
        for node in ast.walk(compose)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Attribute)
        and node.targets[0].attr == "kill_switch"
    ]
    assert len(bindings) == 1
    binding = bindings[0]
    target = binding.targets[0]
    assert isinstance(target, ast.Attribute) and ast.unparse(target.value) == "execution"
    assert ast.unparse(binding.value) == "KillSwitch(project / 'data')"
