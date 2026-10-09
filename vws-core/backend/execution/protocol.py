"""AX-10/11: pure composition contract; no SDK or order transport imports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from backend.data.fill_polling import ObservedFill
from backend.execution.models import Submission

if TYPE_CHECKING:
    from backend.notifications.callbacks import CallbackClick


class OrderExecutor(Protocol):
    async def enter(
        self, proposal_id: UUID, *, click: CallbackClick | None = None
    ) -> Submission: ...
    async def prepare_fills(self, symbols: tuple[str, ...]) -> None: ...
    def observe_fill(self, fill: ObservedFill) -> object: ...
    async def reconcile(self) -> None: ...
    async def monitor(self) -> None: ...
    async def close(self) -> None: ...
