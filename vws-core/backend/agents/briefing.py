"""GD-04/UX: deterministic private desk status, digest and command bodies."""

from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from decimal import Decimal, localcontext
from html import escape
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.llm_budget import LLMBudget
from backend.agents.orchestrator import JobName
from backend.agents.position_monitor import Protection, distance_to_stop, monitor
from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import (
    Alert,
    DataSnapshot,
    Fill,
    JobRun,
    RiskDecision,
    SecurityEvent,
    TicketEvent,
    TradeTicket,
)
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    FrozenModel,
    MarketContext,
    Money,
    PortfolioSnapshot,
    Symbol,
    UTCDateTime,
)
from backend.execution.modes import ModeStore
from backend.notifications.card_formatter import display_time

_NY = ZoneInfo("America/New_York")


def pages(text: str) -> tuple[str, ...]:
    """Keep all evidence, splitting only between lines; never truncate."""
    if not isinstance(text, str) or not text or len(text) > 100_000:
        raise DataIntegrityError("UX: bounded nonempty command text required")
    result: list[str] = []
    current = ""
    for line in text.splitlines():
        if len(line.encode("utf-16-le")) // 2 > 4096:
            raise DataIntegrityError("UX: command line exceeds message boundary")
        candidate = current + ("\n" if current else "") + line
        if len(candidate.encode("utf-16-le")) // 2 > 4096:
            result.append(current)
            current = line
        else:
            current = candidate
    if current:
        result.append(current)
    return tuple(result)


class DeskStatus(FrozenModel):
    state: Literal["RUNNING", "REDUCE_ONLY", "HALTED"]
    as_of: UTCDateTime
    last_success: tuple[tuple[str, UTCDateTime | None], ...]
    latest_public_data_at: UTCDateTime | None
    pending_alerts: int = Field(strict=True, ge=0)
    open_tickets: int = Field(strict=True, ge=0)
    llm_committed_today: Money = Field(ge=0)


def read_status(state: SystemStateStore, settings: Settings) -> DeskStatus:
    """One status read for private commands and the specified later UI."""
    policy = Settings.validated_copy(settings)
    ledger, now = state.ledger, ensure_utc(state.clock.now())
    ledger.verify_chain()
    budget = LLMBudget(ledger, state.clock, policy, state.notifier)
    with Session(state.engine) as session:
        successes = tuple(
            (
                name.value,
                session.scalar(
                    select(JobRun.finished_at)
                    .where(JobRun.job == name.value, JobRun.outcome == "PASS")
                    .order_by(JobRun.seq.desc())
                    .limit(1)
                ),
            )
            for name in JobName
        )
        fetched = session.scalar(
            select(DataSnapshot.fetched_at).order_by(DataSnapshot.fetched_at.desc()).limit(1)
        )
        alerts = tuple(session.scalars(select(Alert.id)))
        tickets = tuple(session.scalars(select(TradeTicket)))
        open_count = 0
        for ticket in tickets:
            followup = session.scalar(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id))
            if followup is not None and followup.action == "TICKET_SKIPPED":
                continue
            alert = session.get(Alert, ticket.alert_id)
            from backend.core.database import Order

            order = (
                None
                if alert is None
                else session.scalar(select(Order).where(Order.proposal_id == alert.proposal_id))
            )
            if order is None:
                raise DataIntegrityError("UX: status ticket lacks its proposal")
            quantity = sum(session.scalars(select(Fill.qty).where(Fill.order_id == order.id)))
            if quantity < ticket.qty and now < ticket.valid_until:
                open_count += 1
        reserved, settled, _ = budget._rows(session, now.astimezone(_NY).date())
        with localcontext() as context:
            context.prec = 80
            spend = sum(
                (
                    settled[key].amount if key in settled else row.amount
                    for key, row in reserved.items()
                ),
                Decimal(0),
            )
    if fetched is not None and fetched > now:
        raise DataIntegrityError("UX: status data clock is in the future")
    return DeskStatus(
        state=state.current().value,
        as_of=now,
        last_success=successes,
        latest_public_data_at=fetched,
        pending_alerts=sum(
            ledger.current_alert_status(key) in {"PENDING", "SENT"} for key in alerts
        ),
        open_tickets=open_count,
        llm_committed_today=spend,
    )


class SymbolQuote(FrozenModel):
    symbol: Symbol
    feed: Literal["IEX"]
    market: MarketContext


class PositionView(FrozenModel):
    portfolio: PortfolioSnapshot
    quotes: tuple[SymbolQuote, ...] = Field(max_length=2000)
    protections: tuple[Protection, ...] = Field(max_length=2000)
    protections_at_broker: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def unique(self) -> "PositionView":
        if (
            len({row.symbol for row in self.quotes}) != len(self.quotes)
            or len({row.symbol for row in self.protections}) != len(self.protections)
            or any(row.kind != "HELD" for row in self.protections)
        ):
            raise ValueError("positions require unique held protection and explicit IEX quotes")
        if self.protections_at_broker:
            for protection in self.protections:
                held = self.portfolio.positions.get(protection.symbol)
                stops = tuple(
                    row
                    for row in self.portfolio.protective_stops
                    if row.symbol == protection.symbol
                )
                if (
                    held is None
                    or not stops
                    or protection.qty != held.qty
                    or sum(row.qty for row in stops) != held.qty
                    or protection.stop != min(row.stop_price for row in stops)
                ):
                    raise ValueError(
                        "Observed broker protection requires exact snapshot stop coverage"
                    )
        return self


class PositionsSource(Protocol):
    async def read(self) -> PositionView: ...


CommandBody = Callable[[str], Awaitable[tuple[str, ...]]]


class DeskCommands:
    def __init__(
        self,
        state: SystemStateStore,
        settings: Settings,
        account_id: str,
        calendar: MarketCalendar,
        positions: PositionsSource,
        *,
        modes: ModeStore | None = None,
        extra_status: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        if not account_id:
            raise ConfigurationError("UX: private desk commands need an account binding")
        self.state, self.settings, self.account_id = (
            state,
            Settings.validated_copy(settings),
            account_id,
        )
        self.calendar, self.position_source = calendar, positions
        self.modes = modes
        self.extra_status = extra_status

    def handlers(self) -> dict[str, CommandBody]:
        return {
            "/status": self.status,
            "/positions": self.positions,
            "/digest": self.digest,
            "/report": self.report,
            "/edge": self.edge,
            "/help": self.help,
            "/progress": self.progress,
        }

    async def status(self, argument: str) -> tuple[str, ...]:
        snapshot = read_status(self.state, self.settings)
        public = (
            "unavailable"
            if snapshot.latest_public_data_at is None
            else display_time(snapshot.latest_public_data_at, self.settings)
        )
        amount = (
            "$•••"
            if self.settings.telegram_mask_amounts
            else f"${snapshot.llm_committed_today:.6f}"
        )
        return pages(
            "\n".join(
                [
                    f"State: {snapshot.state} · Mode: {self.settings.execution_mode if self.modes is None else self.modes.effective}",
                    "Account: " + ("paper" if self.settings.paper_trading else "live"),
                    f"Pending alerts: {snapshot.pending_alerts} · Open tickets: {snapshot.open_tickets}",
                    f"Latest stored public data: {public} (daily history; fresh IEX checked on approval)",
                    f"LLM committed today: {amount} (includes unsettled reservations)",
                    *[
                        f"{name}: "
                        + ("no successful run" if at is None else display_time(at, self.settings))
                        for name, at in snapshot.last_success
                    ],
                    "Other-account wash-sale awareness depends on lots you enter or import.",
                    "Held exits and protection remain available. Resets and upgrades require the host.",
                    *(self.extra_status() if self.extra_status is not None else ()),
                ]
            )
        )

    async def positions(self, argument: str) -> tuple[str, ...]:
        try:
            view = PositionView.model_validate(await self.position_source.read())
            now = ensure_utc(self.state.clock.now())
            if (
                view.portfolio.account_id != self.account_id
                or view.portfolio.as_of > now
                or now - view.portfolio.as_of > timedelta(seconds=self.settings.stale_quote_seconds)
            ):
                raise DataIntegrityError(
                    "UX: position snapshot is stale or belongs to another account"
                )
            quotes, protection = (
                {row.symbol: row for row in view.quotes},
                {row.symbol: row for row in view.protections},
            )
            lines = [
                "Held positions · observed broker stop coverage"
                if view.protections_at_broker
                else "Held positions · planned stop levels; verify broker protection separately"
            ]
            for symbol, held in sorted(view.portfolio.positions.items()):
                qty = "$•••" if self.settings.telegram_mask_amounts else str(held.qty)
                quote, stop = quotes.get(symbol), protection.get(symbol)
                if quote is None:
                    lines.append(
                        f"{symbol}: {qty} shares · IEX last trade unavailable · distance unavailable"
                    )
                    continue
                if (
                    not timedelta(0)
                    <= now - quote.market.last_price_ts
                    <= timedelta(seconds=self.settings.stale_quote_seconds)
                ):
                    raise DataIntegrityError("UX: positions quote is stale/future")
                if stop is None:
                    lines.append(
                        f"{symbol}: {qty} shares · IEX ${quote.market.last_price:.2f} · stop unavailable"
                    )
                else:
                    monitor(
                        stop,
                        view.portfolio,
                        quote.market,
                        now=now,
                        quote_feed=quote.feed,
                        settings=self.settings,
                        calendar=self.calendar,
                    )
                    lines.append(
                        f"{symbol}: {qty} shares · IEX ${quote.market.last_price:.2f} · "
                        f"{'broker' if view.protections_at_broker else 'planned'} stop ${stop.stop:.2f} · "
                        f"distance {distance_to_stop(quote.market.last_price, stop.stop):.2f}%"
                    )
            if not view.portfolio.positions:
                lines.append("No holdings observed.")
            return pages("\n".join(lines))
        except Exception as exc:
            self.state.halt_for_error(exc)
            raise DataIntegrityError(
                "UX: positions could not be verified; entries halted"
            ) from None

    def save_digest(
        self, market_context: str, *, pnl: str | None = None, auto_summary: str | None = None
    ) -> str:
        """Counts are ledger observations; missing SPY evidence stays unavailable."""
        if market_context not in {
            "SPY above 200-day avg",
            "SPY below 200-day avg",
            "SPY unavailable",
        }:
            raise DataIntegrityError("UX: digest market context must be a deterministic status")
        self.state.ledger.verify_chain()
        now = ensure_utc(self.state.clock.now())
        day = now.astimezone(_NY).date()
        start = datetime.combine(day, time.min, _NY).astimezone(now.tzinfo)
        end = datetime.combine(day + timedelta(days=1), time.min, _NY).astimezone(now.tzinfo)
        with Session(self.state.engine) as session:
            alerts = tuple(
                session.scalars(
                    select(Alert).where(Alert.created_at >= start, Alert.created_at < end)
                )
            )
            decisions = tuple(
                session.scalars(
                    select(RiskDecision)
                    .where(RiskDecision.evaluated_at >= start, RiskDecision.evaluated_at < end)
                    .order_by(RiskDecision.seq)
                )
            )
        counts = Counter(self.state.ledger.current_alert_status(row.id) for row in alerts)
        latest = {row.proposal_id: row for row in decisions}
        vetoes = sum(
            row.decision == "VETOED"
            for key, row in latest.items()
            if key not in {alert.proposal_id for alert in alerts}
        )
        text = (
            f"Evening digest · {display_time(now, self.settings)}\n"
            f"Setups saved: {len(alerts)} · Approved: {counts['APPROVED'] + counts['AUTO_APPROVED']} · Rejected: {counts['REJECTED']}\n"
            f"Expired: {counts['EXPIRED']} · Fresh checks failed: {counts['REVALIDATION_FAILED']}\n"
            f"Pending: {counts['PENDING'] + counts['SENT']} · CRO-vetoed proposals: {vetoes}\n"
            f"{market_context}\n"
            + (
                "Automatic fills and weekly hypothetical outcomes are reported separately."
                if self.modes is not None and self.modes.effective != "MANUAL"
                else "Manual review only; weekly hypothetical outcomes are reported separately."
            )
        )
        if pnl is not None:
            from backend.core.content import sanitize_text

            if len(pnl) > 2000 or not pnl.strip():
                raise DataIntegrityError("PL-05: bounded nonempty accounting digest required")
            text += "\n" + sanitize_text(pnl)
        if auto_summary is not None:
            if self.modes is None or not auto_summary.strip() or len(auto_summary) > 2000:
                raise DataIntegrityError("AX-51: bounded account-bound auto summary required")
            text += "\n" + auto_summary
        self.state.ledger.append(
            SecurityEvent, kind="DESK_DIGEST", detail={"day": day.isoformat(), "text": text}
        )
        return text

    async def digest(self, argument: str) -> tuple[str, ...]:
        self.state.ledger.verify_chain()
        day = ensure_utc(self.state.clock.now()).astimezone(_NY).date().isoformat()
        with Session(self.state.engine) as session:
            row = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "DESK_DIGEST",
                    SecurityEvent.detail["day"].as_string() == day,
                )
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
        return pages(
            escape("Today's digest is not available yet." if row is None else row.detail["text"])
        )

    async def report(self, argument: str) -> tuple[str, ...]:
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            row = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "WEEKLY_REPORT",
                    SecurityEvent.detail["account_id"].as_string() == self.account_id,
                    SecurityEvent.detail["cohort"].as_string()
                    == ("PAPER" if self.settings.paper_trading else "LIVE"),
                )
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
        if row is None:
            return pages("No weekly report has been generated yet.")
        from backend.evaluation.evidence import recorded_publication
        from backend.evaluation.weekly import render_weekly

        report = recorded_publication(row.detail)
        if (
            report.context.account_id != self.account_id
            or report.context.cohort != ("PAPER" if self.settings.paper_trading else "LIVE")
            or (report.security is not None and report.security.as_of > self.state.clock.now())
        ):
            raise DataIntegrityError("EV-02: stored report account/mode/hash binding differs")
        return pages(
            escape(render_weekly(report, mask_amounts=self.settings.telegram_mask_amounts))
        )

    async def edge(self, argument: str) -> tuple[str, ...]:
        """ER-03: same after-cost evidence; private admission and heavy rate limits apply."""
        return await self.report(argument)

    async def help(self, argument: str) -> tuple[str, ...]:
        if self.modes is not None:
            return (
                "/status · /positions · /digest · /report · /edge · /progress · /pnl · /tax · /watch TICKER\n"
                "Watch cards never auto-trade. Reply to a trade card or FYI to save a journal note.\n"
                "/halt, /pause and /manual stop automatic entries; held exits and broker stops continue.\n"
                "In an automatic mode, Approve places the order now after fresh checks.\n"
                "Resume only on the host: python -m vws ops resume-auto --operator NAME (type RESUME).",
            )
        return (
            "/status · /positions · /digest · /report · /edge · /progress · /pnl · /tax · /watch TICKER\n"
            "Reply to a trade card or FYI to save a journal note.\n"
            "/halt reason stops entries immediately. /pause allows reductions only.\n"
            "Approve creates a manual ticket after fresh checks. Details is read-only.\n"
            "I placed it records your action; broker fills are checked separately.\n"
            "Reset and mode upgrades require the host.",
        )

    async def progress(self, argument: str) -> tuple[str, ...]:
        from vws.progress import private_progress_text

        return pages(escape(private_progress_text()))
