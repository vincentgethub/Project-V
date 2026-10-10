"""XK-09: atomic daily admission, deterministic single-symbol manual-only research."""

from datetime import timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.agents.desk import Desk
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.notifications.telegram_bot import TelegramBot
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.journal import Journal


class WatchDesk:
    def __init__(
        self, desk: Desk, source: ConnectedDeskSource, bot: TelegramBot, journal: Journal
    ) -> None:
        self.desk, self.source, self.bot, self.journal = desk, source, bot, journal

    async def __call__(self, argument: str, chat_id: int) -> tuple[str, ...]:
        symbol = argument.strip().upper()
        if chat_id not in self.bot.settings.telegram_allowed_user_ids:
            raise DataIntegrityError("XK-09: private owner admission required")
        if symbol not in self.source.registry.symbols:
            return ("Use /watch with one ticker listed in instruments.csv.",)
        ledger = self.journal.ledger
        ledger.verify_chain()
        now = ledger.clock.now()
        start = now.astimezone(ZoneInfo("America/New_York")).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with transaction(ledger.engine) as session:
            ledger._verify_in_session(session)
            rows = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(
                        SecurityEvent.kind == "WATCH_REQUEST",
                        SecurityEvent.created_at >= start,
                        SecurityEvent.created_at < start + timedelta(days=1),
                    )
                    .limit(100001)
                )
            )
            if len(rows) > 100000:
                raise DataIntegrityError("XK-09: daily watch evidence exceeds its bound")
            used = sum(
                row.detail["scope"] == self.journal.scope.model_dump(mode="json") for row in rows
            )
            if used >= 10:
                return ("Daily /watch limit reached: ten requests per account and environment.",)
            ledger.append_in_session(
                session,
                SecurityEvent,
                kind="WATCH_REQUEST",
                telegram_user_id=chat_id,
                detail={"scope": self.journal.scope.model_dump(mode="json"), "symbol": symbol},
            )
        cycle = await self.source.scan((symbol,))
        messages = []
        for request in cycle.requests:
            if not request.manual_only or request.candidate.symbol != symbol:
                raise DataIntegrityError("XK-09: single-symbol manual-only source differs")
            fresh = await self.source.refresh_request(request)
            if fresh is None:
                continue
            if not fresh.manual_only:
                raise DataIntegrityError("XK-09: refreshed watch lost its manual-only binding")
            result = await self.desk.research(fresh)
            self.journal.sync()
            if (
                result.status == "ALERT"
                and result.research is not None
                and result.research.alert_id is not None
            ):
                await self.bot.deliver(result.research.alert_id, chat_id)
                messages.append(escape(f"{symbol}: manual-only watch card recorded."))
            else:
                messages.append(
                    escape(f"{symbol}: {result.status.lower()} after deterministic checks.")
                )
        return tuple(messages) or (
            escape(f"{symbol}: no eligible setup after deterministic checks."),
        )
