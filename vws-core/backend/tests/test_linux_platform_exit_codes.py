"""LP-25/LP-34 exit codes through the production CLI, on every platform."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.ops import panic_flag, quiescence
from backend.ops.panic_flag import OSFlagAdapter
from backend.ops.platform_primitives import backend_for
from backend.ops.quiescence import BrokerActor, Lease
from backend.tests import test_panic_flag_roots as roots
from backend.tests.broker_real_adapters import Adapters, RealBackedFlag
from backend.tests.platform_expect import fresh_flag_state as fresh_flag_state
from backend.tests.test_broker_coordination import FakeSlots
from backend.tests.test_broker_flag_os import child
from backend.tests.test_panic_flag_create_failure import (
    FailingKernel,
    NativeFailureFlag,
    assert_native_failure,
)
from backend.tests.test_security_cli import MemorySecrets, make_security_context
from backend.tests.test_security_cli import no_native_keyring as no_native_keyring
from vws import __main__ as cli
from vws import runtime_cli, security_cli

context = make_security_context

HOLD_HOST_LOCK = (
    "from pathlib import Path; import sys; "
    "from backend.ops.platform_primitives import backend_for; "
    "lock=backend_for(sys.platform).runtime_lock(Path(sys.argv[1])); lock.__enter__(); "
    "print('LOCKED',flush=True); sys.stdin.readline()"
)


def first_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    return process.stdout.readline().strip()


def test_LP25_start_exits_1_with_the_busy_message_while_another_process_holds_the_host_lock(
    context: security_cli.SecurityContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "data"
    data.mkdir(mode=0o700, exist_ok=True)
    holder = child(HOLD_HOST_LOCK, data)
    assert first_line(holder) == "LOCKED"
    monkeypatch.setattr(security_cli, "PROJECT", tmp_path)
    monkeypatch.setattr(runtime_cli, "KeyringSecretStore", MemorySecrets)
    monkeypatch.setattr(runtime_cli, "load_host_settings", lambda *_args: context.settings)
    try:
        code = cli.main(["start"])
    finally:
        output, errors = holder.communicate("exit\n")
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == "Another Project V process holds the host lock\n"
    assert holder.returncode == 0 and not output and not errors
    with backend_for(sys.platform).runtime_lock(data):
        assert (data / "runtime.lock").read_bytes() == b"0"


def test_LP34_unrecorded_panic_exits_1_on_the_real_flag_failure_of_the_running_platform(
    context: security_cli.SecurityContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    codes: list[int] = []

    def recording_main(argv: list[str]) -> int:
        codes.append(cli.main(argv))
        return codes[-1]

    monkeypatch.setattr(roots, "cli", SimpleNamespace(main=recording_main))
    if sys.platform == "win32":
        kernel = FailingKernel("set")
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
        slots = FakeSlots()
        flag = NativeFailureFlag(tmp_path)
        monkeypatch.setattr(quiescence, "OSSlots", lambda _directory: slots)
        monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: flag)
        roots.test_B1_flag_and_both_record_writes_fail_nonzero_after_emergency_ops(
            context, monkeypatch, (slots, flag), capsys
        )
        assert_native_failure(kernel, observed)
        assert codes == [1]
        return
    blocked = tmp_path / "flag-is-a-file"
    blocked.write_bytes(b"not a directory")
    adapters = Adapters(security_cli.PROJECT)
    real_slots = adapters.slots()
    real_flag = RealBackedFlag(adapters.directory)
    real_flag.native = OSFlagAdapter(blocked)
    monkeypatch.setattr(quiescence, "OSSlots", lambda _directory: real_slots)
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: real_flag)
    try:
        roots.test_B1_flag_and_both_record_writes_fail_nonzero_after_emergency_ops(
            context, monkeypatch, (real_slots, real_flag), capsys
        )
    finally:
        adapters.finish()
    assert codes == [1]
    assert real_flag.signals >= 1 and not real_flag.signaled
