"""XK-08/ER-03: nightly projection and private, durable weekly document delivery."""

import asyncio
from collections.abc import Callable
from hashlib import sha256
from html import unescape
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import DeskCommands
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.notifications.telegram_bot import TelegramBot, quiet_hours
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.html_report import ReportSnapshot, html_report, save_html
from backend.ops.trading_controls import ControlScope
from backend.pnl.service import AccountingReports
from backend.pnl.storage import read_days


class ReportPublisher:
    def __init__(
        self,
        root: Path,
        scope: ControlScope,
        accounting: AccountingReports,
        source: ConnectedDeskSource,
        commands: DeskCommands,
        bot: TelegramBot,
        extra_status: Callable[[], tuple[str, ...]],
    ) -> None:
        self.root, self.scope, self.accounting = root, scope, accounting
        self.source, self.commands, self.bot, self.extra_status = (
            source,
            commands,
            bot,
            extra_status,
        )
        self.ledger = accounting.state.ledger
        self._lock = asyncio.Lock()

    async def capture(self) -> SecurityEvent:
        async with self._lock:
            days = await asyncio.to_thread(
                read_days, self.ledger, self.scope.account_id, self.scope.environment
            )
            spy = None
            if days:
                try:
                    start = self.accounting.calendar.previous_sessions(
                        days[0].observation.session, 1
                    )[0]
                    spy = await self.accounting.spy(start, days[-1].observation.session)
                except Exception:
                    # Benchmark unavailability is displayed and never becomes a zero return.
                    spy = None
            portfolio = (await self.source.positions()).portfolio
            book = await asyncio.to_thread(self.accounting.tax.book)
            trades = tuple(
                sorted(
                    (row for row in book.fills if row.account_id == self.scope.account_id),
                    key=lambda row: (row.ts, str(row.fill_id)),
                    reverse=True,
                )[:20]
            )
            snapshot = ReportSnapshot(
                scope=self.scope,
                as_of=self.ledger.clock.now(),
                days=days,
                spy=spy,
                portfolio=portfolio,
                trades=trades,
                tax=tuple(unescape(page) for page in await self.accounting.tax_summary()),
                health=tuple(unescape(page) for page in await self.commands.status("")),
                edge=tuple(unescape(page) for page in await self.commands.edge("")),
            )
            payload = html_report(snapshot)
            await asyncio.to_thread(save_html, self.root, snapshot)
            return self.ledger.append(
                SecurityEvent,
                kind="NIGHTLY_HTML_REPORT",
                detail={
                    "scope": self.scope.model_dump(mode="json"),
                    "snapshot": snapshot.model_dump(mode="json"),
                    "sha256": sha256(payload).hexdigest(),
                },
            )

    def _bytes(self, identity: UUID) -> bytes:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            row = session.get(SecurityEvent, identity)
            if row is None or row.kind != "NIGHTLY_HTML_REPORT" or row.ts > self.ledger.clock.now():
                raise DataIntegrityError("XK-08: queued document has no immutable report")
            snapshot = ReportSnapshot.recorded(row.detail["snapshot"])
            payload = html_report(snapshot)
            if snapshot.scope != self.scope or sha256(payload).hexdigest() != row.detail["sha256"]:
                raise DataIntegrityError("XK-08: queued document scope or hash differs")
            return payload

    async def latest(self) -> bytes:
        report = await self.capture()
        return self._bytes(report.id)

    async def weekly(self) -> None:
        report = await self.capture()
        self.ledger.append(
            SecurityEvent,
            kind="HTML_REPORT_DOCUMENT_PENDING",
            detail={"scope": self.scope.model_dump(mode="json"), "report_id": str(report.id)},
        )
        await self.flush()

    async def flush(self) -> None:
        if quiet_hours(self.ledger.clock.now()):
            return
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            queued = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "HTML_REPORT_DOCUMENT_PENDING")
                    .order_by(SecurityEvent.seq)
                    .limit(100001)
                )
            )
            delivered = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "HTML_REPORT_DOCUMENT_DELIVERED")
                    .limit(100001)
                )
            )
            if len(queued) > 100000 or len(delivered) > 100000:
                raise DataIntegrityError("XK-08: document queue exceeds its bound")
            if any(row.ts > self.ledger.clock.now() for row in (*queued, *delivered)):
                raise DataIntegrityError("XK-08: document queue contains future evidence")
            sent = {(row.detail["pending_id"], row.detail["owner_id"]) for row in delivered}
        for item in queued:
            if ControlScope.model_validate(item.detail["scope"]) != self.scope:
                continue
            payload = self._bytes(UUID(item.detail["report_id"]))
            for owner in self.bot.settings.telegram_allowed_user_ids:
                if (str(item.id), owner) in sent:
                    continue
                await self.bot.document(owner, payload)
                self.ledger.append(
                    SecurityEvent,
                    kind="HTML_REPORT_DOCUMENT_DELIVERED",
                    detail={"pending_id": str(item.id), "owner_id": owner},
                )
