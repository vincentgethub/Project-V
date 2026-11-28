"""LP-41/LP-44: production panic/flag roots against the real OS adapters, on every platform.

The fixtures keep the fake-shaped counters the existing pins read, but every lock and every flag
read or write goes through the real adapter for the running platform (flock + sticky marker on
Linux, named mutex + event on Windows).
"""

from pathlib import Path

import pytest

from backend.core.clock import FrozenClock
from backend.core.system_state import SystemState
from backend.ops.panic_flag import OSFlagAdapter
from backend.ops.quiescence import current_actor
from backend.tests import test_panic_call_choke as choke
from backend.tests import test_panic_flag_roots as roots
from backend.tests.broker_real_adapters import (
    SLOT_NAMES,
    Adapters,
    assert_no_leaked_locks,
    flag_is_set,
)
from backend.tests.platform_expect import fresh_flag_state as fresh_flag_state
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_security_cli import make_security_context
from backend.tests.test_security_cli import no_native_keyring as no_native_keyring
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from vws import security_cli

context = make_security_context
harness = make_research_harness


def test_LP41_halt_is_persisted_before_the_flag_and_the_flag_before_the_first_broker_call(
    tmp_path: Path, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = roots.file_ops(tmp_path, clock)
    adapters = Adapters(tmp_path)
    held = adapters.slots()
    held.held.update(SLOT_NAMES)
    events: list[tuple[str, object, object]] = []
    original = OSFlagAdapter.signal_if_present

    def traced(self: OSFlagAdapter) -> bool:
        events.append(("flag", ops.state.current(), None))
        return original(self)

    monkeypatch.setattr(OSFlagAdapter, "signal_if_present", traced)

    def cancel() -> None:
        actor = current_actor()
        assert actor is not None and actor.slot is None
        actor.retain()
        actor.physical_call(
            lambda: events.append(("broker", ops.state.current(), flag_is_set(adapters.directory)))
        )

    try:
        assert ops.state.current() != SystemState.HALTED
        result = ops.panic("Owner", "offline panic", mode="AUTO_PAPER", cancel_unfilled=cancel)
        assert result.state == SystemState.HALTED
        assert events == [
            ("flag", SystemState.HALTED, None),
            ("broker", SystemState.HALTED, True),
        ], "HALT must be persisted before the flag, and the flag before the broker call"
    finally:
        adapters.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("path", ["panic", "panic-partial", "panic-completed", "manual"])
@pytest.mark.parametrize("with_flag", [False, True])
async def test_LP44_every_worker_recovery_cancel_and_stop_call_signals_like_the_fake(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    with_flag: bool,
) -> None:
    """Pins roots :424 (signals == calls, or 0 under a held slot) on the real adapters."""
    adapters = Adapters(tmp_path)
    monkeypatch.setattr(choke, "FakeSlots", adapters.slots)
    monkeypatch.setattr(choke, "FakeFlagAdapter", adapters.flag)
    try:
        await choke.test_F2_every_worker_recovery_cancel_and_stop_call_has_common_hook(
            harness, tmp_path, monkeypatch, path, with_flag
        )
    finally:
        adapters.finish()


@pytest.mark.asyncio
async def test_LP44_activity_account_pages_and_order_reads_signal_four_times(
    context: security_cli.SecurityContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins choke :173 (flag.signals == 4, no waits) on the real adapters."""
    adapters = Adapters(tmp_path)
    monkeypatch.setattr(choke, "FakeSlots", adapters.slots)
    monkeypatch.setattr(choke, "FakeFlagAdapter", adapters.flag)
    try:
        await choke.test_F2_activity_account_pages_and_order_reads_share_common_hook(
            context, tmp_path, monkeypatch
        )
    finally:
        adapters.finish()


def test_LP44_leak_check_detects_a_locked_slot(tmp_path: Path) -> None:
    adapters = Adapters(tmp_path)
    held = adapters.slots()
    held.held.update(["slot-3"])
    with pytest.raises(AssertionError, match="slot-3 is still locked"):
        assert_no_leaked_locks(adapters.directory)
    held.pinned.release_all()
    assert_no_leaked_locks(adapters.directory)
