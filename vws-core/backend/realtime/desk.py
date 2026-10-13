"""RT/EVT/AC: host-bound context and entry checks with no order capability."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import YamlConfig
from backend.core.database import Order, SecurityEvent
from backend.core.errors import DataIntegrityError, ExecutionDisabledError
from backend.data.market_calendar import MarketCalendar
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import (
    REQUIRED,
    HealthStatus,
    RealtimeContext,
    RealtimeEvent,
)
from backend.realtime.policy import context, exit_event, health_at
from backend.realtime.schedules import Schedules
from backend.realtime.storage import RealtimeStore


class RealtimeDesk:
    def __init__(
        self,
        store: RealtimeStore,
        config: YamlConfig,
        calendar: MarketCalendar,
        schedules: Schedules,
        automatic: Callable[[], bool],
    ) -> None:
        self.store, self.config, self.calendar, self.schedules = (
            store,
            YamlConfig.model_validate(config),
            calendar,
            schedules,
        )
        if (
            schedules.ledger.engine is not store.ledger.engine
            or store.policy_hash != self.config.config_hash
        ):
            raise DataIntegrityError(
                "RT: desk must bind the complete current YAML policy and ledger"
            )
        self.automatic = automatic

    def context(self, symbol: str, at: datetime | None = None) -> RealtimeContext:
        return context(
            self.store.scope,
            symbol,
            self.store.ledger.clock.now() if at is None else at,
            self.store.policy_hash,
            self.config.rt,
            self.config.events_policy,
            self.store.health(),
            self.store.events(),
            self.schedules.macro.read() if self.schedules.macro.path.is_file() else (),
            self.calendar,
            auto=self.automatic(),
            schedules_verified=self.schedules.confirmed(),
        )

    def factor(self, symbol: str, at: datetime) -> Decimal:
        row = self.context(symbol, at)
        self.store.record_size_context(row.model_dump(mode="python"))
        return row.entry_multiplier

    def hard_exit(
        self, symbol: str, acquired: datetime
    ) -> tuple[Literal["DELIST", "DILUTION"], str] | None:
        """Return a durable confirmed event; only the isolated executor acts."""
        now = self.store.ledger.clock.now()
        for row in self.store.events():
            if (
                row.symbol == symbol
                and acquired <= row.occurred_at <= now < row.expires_at
                and exit_event(row, self.config.rt, held=True)
            ):
                if row.kind == "DELIST":
                    return "DELIST", self.store.key(row)
                if row.kind == "DILUTION":
                    return "DILUTION", self.store.key(row)
        return None

    def record(self, proposal_id: UUID, symbol: str) -> RealtimeContext:
        row = self.context(symbol)
        self.store.record_context(proposal_id, row.model_dump(mode="python"))
        return row

    async def require_entry(self, proposal_id: UUID) -> None:
        """Only an opening proposal may call this; held exits have no RT gate."""
        if not isinstance(proposal_id, UUID):
            raise DataIntegrityError("RT-10: canonical opening proposal identity required")
        self.store.ledger.verify_chain()
        with Session(self.store.ledger.engine) as session:
            order = session.scalar(select(Order).where(Order.proposal_id == proposal_id))
        if (
            order is None
            or order.account_id != self.store.scope.account_id
            or order.side != "BUY"
            or order.intent not in {"ENTRY", "ADD"}
        ):
            raise DataIntegrityError("RT-10: entry gate requires a bound opening proposal")
        row = self.record(proposal_id, order.symbol)
        if row.blocked:
            reason = "; ".join(row.warnings) or ", ".join(tag.value for tag in row.tags)
            raise ExecutionDisabledError("RT-10/EVT: new entry unavailable: " + reason)

    def required_healthy(self) -> bool:
        rows = {row.feed: row for row in self.store.health()}
        now = self.store.ledger.clock.now()
        return all(
            name in rows and health_at(rows[name], now, self.config.rt) == HealthStatus.OK
            for name in REQUIRED
        ) and set(self.config.watchlist).issubset(rows["assets"].symbols)

    def history_ready(self, paper_account_id: str, minimum: int) -> bool:
        if type(minimum) is not int or minimum < 5 or minimum > 10000:
            raise DataIntegrityError("RT-14: live prerequisite has a five-session floor")
        paper = RealtimeStore(
            self.store.ledger,
            ControlScope(account_id=paper_account_id, environment="PAPER"),
            self.store.policy_hash,
        )
        return (
            self.required_healthy()
            and len(paper.healthy_sessions(self.calendar, self.config.rt)) >= minimum
        )

    def statuses(self) -> tuple[str, ...]:
        health = {row.feed: row for row in self.store.health()}
        now = self.store.ledger.clock.now()
        lines = []
        for name in ("clock", "halts", "news", "assets", "ca", "edgar", "fred", "macro"):
            row = health.get(name)
            if row is None:
                lines.append(f"{name}: UNVERIFIED; no verified heartbeat")
            else:
                seconds = int((now - row.observed_at).total_seconds())
                lines.append(
                    f"{name}: {health_at(row, now, self.config.rt).value}; last heartbeat {seconds}s ago"
                )
        return tuple(lines)

    def events(self) -> str:
        now = self.store.ledger.clock.now()
        upcoming = tuple(row for row in self.schedules.macro.read() if row.release_at >= now)[:10]
        tags: set[str] = set()
        for symbol in self.config.watchlist:
            tags.update(tag.value for tag in self.context(symbol).tags)
        lines = ["Events (masked)", "Today's context: " + (", ".join(sorted(tags)) or "none")]
        lines.extend(
            f"{row.event}: {row.release_at.astimezone(ZoneInfo('America/Chicago')):%Y-%m-%d %H:%M %Z}"
            for row in upcoming
        )
        lines.append(
            "Scheduled events need confirmed official sources. Halts never force an exit; event rules can only reduce exposure."
        )
        return "\n".join(lines)

    async def dispatch(
        self,
        event: RealtimeEvent,
        held: Callable[[str], Awaitable[bool]],
        notify: Callable[[str, bool], Awaitable[None]],
        hard_exit: Callable[[RealtimeEvent], Awaitable[None]] | None = None,
    ) -> None:
        row = RealtimeEvent.model_validate(event)
        if row.symbol is None or row.kind not in {
            "HALT",
            "HALT_NEWS",
            "ASSET_INACTIVE",
            "NEWS_NEG",
            "DELIST",
            "DILUTION",
        }:
            return
        owned = await held(row.symbol)
        if type(owned) is not bool:
            raise DataIntegrityError("RT-11: fresh held ownership required")
        self.store.flag_once(row, held=owned)
        if not self.store.notice_delivered(row):
            await notify(
                f"Realtime flag: {row.symbol} {row.kind}. {'Held position flagged.' if owned else 'Watched symbol flagged.'} {row.text}",
                owned,
            )
            self.store.delivered_notice(row)
        if exit_event(row, self.config.rt, held=owned) and self.automatic():
            if hard_exit is None:
                raise ExecutionDisabledError(
                    "RT-11: configured confirmed hard-event exit is unavailable"
                )
            # Dispatch completion follows the callback. On ambiguous delivery,
            # its executor must look up its stable id before any retry.
            await hard_exit(row)

    def journal_write_probe(self) -> None:
        receipt = self.store.ledger.append(
            SecurityEvent,
            kind="LEARNING_WRITE_CHECK",
            detail={
                "scope": self.store.scope.model_dump(mode="json"),
                "policy_sha256": self.store.policy_hash,
            },
        )
        self.store.ledger.verify_chain()
        if receipt.ts > self.store.ledger.clock.now():
            raise DataIntegrityError("AC-04: journal write receipt is in the future")
