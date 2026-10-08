"""OPS-03: durable notification episodes for missed scans and repeated jobs."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.orchestrator import JobName
from backend.core.clock import Clock, ensure_utc
from backend.core.database import JobRun, SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemStateStore
from backend.data.market_calendar import MarketCalendar

Notify = Callable[[str], Awaitable[None]]


class Watchdog:
    def __init__(
        self, state: SystemStateStore, calendar: MarketCalendar, clock: Clock, notify: Notify
    ) -> None:
        if state.clock is not clock:
            raise DataIntegrityError("Watchdog requires the bound ledger clock")
        self.state, self.calendar, self.clock, self.notify = state, calendar, clock, notify
        self._lock = asyncio.Lock()

    def _delivered(self, kind: str, episode: str) -> bool:
        with Session(self.state.engine) as session:
            rows = session.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "WATCHDOG_ALERT_DELIVERED",
                    SecurityEvent.detail["kind"].as_string() == kind,
                    SecurityEvent.detail["episode"].as_string() == episode,
                )
                .limit(1)
            )
            return rows.first() is not None

    async def _alert(self, kind: str, episode: str, message: str) -> bool:
        if self._delivered(kind, episode):
            return False
        try:
            async with asyncio.timeout(30):
                await self.notify(message)
        except Exception as exc:
            self.state.ledger.append(
                SecurityEvent,
                kind="WATCHDOG_NOTIFICATION_FAILED",
                detail={"kind": kind, "episode": episode, "error_type": type(exc).__name__},
            )
            return False
        self.state.ledger.append(
            SecurityEvent,
            kind="WATCHDOG_ALERT_DELIVERED",
            detail={"kind": kind, "episode": episode},
        )
        return True

    async def check(self) -> int:
        """Retry failed notification delivery; never claim it arrived on error."""
        async with self._lock:
            self.state.ledger.verify_chain()
            now = ensure_utc(self.clock.now())
            day = now.astimezone(ZoneInfo("America/New_York")).date()
            delivered = 0
            if self.calendar.is_session(day):
                closed = self.calendar.session_close(day)
                deadline = closed + timedelta(minutes=90)
                if now >= deadline:
                    with Session(self.state.engine) as session:
                        success = session.scalar(
                            select(JobRun.seq)
                            .where(
                                JobRun.job == JobName.DAILY_SCAN.value,
                                JobRun.outcome == "PASS",
                                JobRun.started_at >= closed,
                                JobRun.finished_at <= deadline,
                            )
                            .limit(1)
                        )
                    if success is None:
                        delivered += await self._alert(
                            "missed_daily_scan",
                            day.isoformat(),
                            "Urgent: the daily scan did not succeed by exchange close plus 90 minutes. Check the host and job failures.",
                        )
            for name in JobName:
                with Session(self.state.engine) as session:
                    breaker = session.scalar(
                        select(JobRun.seq)
                        .where(JobRun.job == name.value, JobRun.outcome != "FAIL")
                        .order_by(JobRun.seq.desc())
                        .limit(1)
                    )
                    failures = tuple(
                        session.scalars(
                            select(JobRun)
                            .where(
                                JobRun.job == name.value,
                                JobRun.outcome == "FAIL",
                                JobRun.seq > (breaker or 0),
                            )
                            .order_by(JobRun.seq)
                            .limit(3)
                        )
                    )
                    if any(row.finished_at > now for row in failures):
                        raise DataIntegrityError("Watchdog job evidence is in the future")
                if len(failures) == 3:
                    delivered += await self._alert(
                        "job_failures",
                        name.value + ":" + str(failures[0].seq),
                        "Urgent: "
                        + name.value
                        + " failed three times in a row. Inspect the redacted logs and resolve the fault before any host reset.",
                    )
            return delivered
