"""XK-01/AX-03: shared downgrade path for authenticated Telegram and scratch drills."""

from typing import Literal, Protocol

from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.execution.modes import ModeStore


class ProtectionMonitor(Protocol):
    async def monitor(self) -> None: ...


async def downgrade(
    state: SystemStateStore,
    modes: ModeStore | None,
    executor: ProtectionMonitor | None,
    action: Literal["HALT", "PAUSE", "MANUAL"],
    actor: str,
    reason: str,
) -> None:
    if action not in {"HALT", "PAUSE", "MANUAL"} or not actor.strip():
        raise DataIntegrityError("AX-03: downgrade action and attributed actor required")
    if modes is not None:
        if modes.state is not state:
            raise DataIntegrityError("AX-03: mode controller belongs to another state")
        modes.downgrade(action, actor=actor)
        if executor is not None:
            await executor.monitor()
    elif action != "MANUAL":
        state.escalate(SystemState.HALTED if action == "HALT" else SystemState.REDUCE_ONLY, reason)
