"""OPS-SPREAD: entry-only spread gate composed onto the realtime entry hook.

The executor calls its realtime entry hook only on the opening-entry path
(before and after the fresh-input refresh), never for exits, stops, repairs
or cancels. This gate runs the existing realtime check first, then reads its
own fresh IEX quote and refuses the entry when the spread rule refuses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import Order
from backend.core.errors import DataIntegrityError, ExecutionDisabledError
from backend.data.top_of_book import TopOfBook, spread_refusal


class EntrySpreadGate:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        clock: Clock,
        quote: Callable[[str], Awaitable[TopOfBook]],
        then: Callable[[UUID], Awaitable[None]],
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.engine, self.clock, self.quote, self.then = engine, clock, quote, then

    async def __call__(self, proposal_id: UUID) -> None:
        await self.then(proposal_id)
        with Session(self.engine) as session:
            order = session.scalar(select(Order).where(Order.proposal_id == proposal_id))
        if order is None or order.side != "BUY" or order.intent not in {"ENTRY", "ADD"}:
            raise DataIntegrityError("OPS-SPREAD: spread gate requires a bound opening proposal")
        top = TopOfBook.model_validate(await self.quote(order.symbol))
        if top.symbol != order.symbol:
            raise DataIntegrityError("OPS-SPREAD: quote symbol differs from the proposal")
        reason = spread_refusal(
            top,
            ensure_utc(self.clock.now()),
            max_spread=self.settings.max_entry_spread,
            max_age_seconds=self.settings.stale_quote_seconds,
        )
        if reason is not None:
            raise ExecutionDisabledError("Spread gate blocks entry: " + reason)
