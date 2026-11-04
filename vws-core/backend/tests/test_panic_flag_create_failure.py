"""Exercise Windows flag failures through the native adapter and offline panic proofs."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.ops import panic_flag, quiescence
from backend.ops.quiescence import BrokerActor, Lease
from backend.tests import test_panic_dryrun_stop as dryrun
from backend.tests import test_panic_flag_roots as roots
from backend.tests.broker_flag_fakes import FakeFlagAdapter
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_broker_coordination import FakeSlots
from backend.tests.test_security_cli import no_native_keyring as no_native_keyring
from backend.tests.test_swarm_and_callbacks import Harness
from vws.security_cli import SecurityContext

context = roots.context
harness = dryrun.harness


class FailingKernel:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.calls: list[str] = []

    def CreateEventW(self, *_args: object) -> int:
        self.calls.append("CreateEventW")
        return 0 if self.stage == "create" else 1

    def SetEvent(self, _handle: int) -> int:
        self.calls.append("SetEvent")
        return 0

    def CloseHandle(self, _handle: int) -> int:
        self.calls.append("CloseHandle")
        return 1


class NativeFailureFlag(FakeFlagAdapter):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.native = panic_flag.OSFlagAdapter(path)

    def signal_if_present(self) -> bool:
        return self.native.signal_if_present()


@pytest.fixture(params=("create", "set"))
def native_failure(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[NativeFailureFlag, FailingKernel, list[bool]]:
    stage = request.param
    assert isinstance(stage, str)
    kernel = FailingKernel(stage)
    monkeypatch.setattr(panic_flag, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(panic_flag, "_kernel", lambda: kernel)
    monkeypatch.setattr(panic_flag, "_retained_windows", {})
    observed: list[bool] = []
    original = BrokerActor.before_broker_call

    def observe(actor: BrokerActor) -> Lease | None:
        lease = original(actor)
        if actor.kind == "panic":
            observed.append(actor._flag_failed)
        return lease

    monkeypatch.setattr(BrokerActor, "before_broker_call", observe)
    return NativeFailureFlag(tmp_path), kernel, observed


def assert_native_failure(kernel: FailingKernel, observed: list[bool]) -> None:
    expected = ["CreateEventW"]
    if kernel.stage == "set":
        expected += ["SetEvent", "CloseHandle"]
    assert observed and all(observed)
    assert kernel.calls == expected * len(observed)


def test_native_flag_failure_reports_unrecorded_panic_after_emergency_calls(
    context: SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    native_failure: tuple[NativeFailureFlag, FailingKernel, list[bool]],
) -> None:
    flag, kernel, observed = native_failure
    slots = FakeSlots()
    monkeypatch.setattr(quiescence, "OSSlots", lambda _directory: slots)
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: flag)
    roots.test_B1_flag_and_both_record_writes_fail_nonzero_after_emergency_ops(
        context, monkeypatch, (slots, flag), capsys
    )
    assert_native_failure(kernel, observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_native_flag_failure_still_refuses_on_broker_snapshot_change(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_failure: tuple[NativeFailureFlag, FailingKernel, list[bool]],
) -> None:
    flag, kernel, observed = native_failure
    monkeypatch.setattr(dryrun, "FakeFlagAdapter", lambda: flag)
    await dryrun.test_B2_dryrun_real_ensure_stop_change_refuses_at_existing_comparison(
        harness, tmp_path, monkeypatch
    )
    assert_native_failure(kernel, observed)
