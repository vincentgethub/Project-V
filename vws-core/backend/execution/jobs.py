"""AX-22/28/40: account bound auto jobs through the pure execution protocol."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.orchestrator import JobCounts
from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import Alert, AutoJobRun, ExecutionOrderRecord, SecurityEvent
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    ExecutionDisabledError,
    OrderRejectedError,
)
from backend.core.system_state import SystemState
from backend.data.market_calendar import MarketCalendar
from backend.execution.modes import ModeStore
from backend.execution.policy import entry_window
from backend.execution.protocol import OrderExecutor

AutoJob = Literal["auto_entry", "auto_poll"]
_NY = ZoneInfo("America/New_York")


class AutoJobs:
    def __init__(
        self,
        settings: Settings,
        modes: ModeStore,
        calendar: MarketCalendar,
        executor: OrderExecutor,
        sync_fills: Callable[[], Awaitable[object]],
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        if (
            self.settings.execution_mode == "MANUAL"
            or modes.settings.config_hash != self.settings.config_hash
        ):
            raise ConfigurationError("Auto jobs require a bound automatic configuration")
        self.modes, self.state, self.calendar = modes, modes.state, calendar
        self.executor, self.sync_fills = executor, sync_fills
        self._locks = {name: asyncio.Lock() for name in ("auto_entry", "auto_poll")}

    def due(self, name: AutoJob, now: datetime) -> bool:
        now = ensure_utc(now)
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            latest = session.scalar(
                select(AutoJobRun)
                .where(
                    AutoJobRun.job == name,
                    AutoJobRun.account_id == self.modes.account_id,
                    AutoJobRun.environment == self.modes.environment,
                )
                .order_by(AutoJobRun.seq.desc())
                .limit(1)
            )
            managed = (
                session.scalar(
                    select(ExecutionOrderRecord.id)
                    .where(
                        ExecutionOrderRecord.account_id == self.modes.account_id,
                        ExecutionOrderRecord.environment == self.modes.environment,
                    )
                    .limit(1)
                )
                is not None
            )
        if latest is not None and latest.started_at > now:
            raise DataIntegrityError("Auto job clock moved backward")
        if name == "auto_entry":
            if not entry_window(self.settings, self.calendar, now):
                return False
            return (
                latest is None
                or latest.started_at.astimezone(_NY).date() != now.astimezone(_NY).date()
            )
        # Monitoring stays alive after the close, a pause or a halt. In particular
        # DAY exit expiry must be followed by restoring overnight GTC protection.
        return (managed or self.calendar.is_open(now)) and (
            latest is None or now - latest.started_at >= timedelta(seconds=60)
        )

    async def entry(self) -> JobCounts:
        if not self.modes.entries_enabled:
            return JobCounts(counts={"entries_skipped": 1})
        await self.sync_fills()
        with Session(self.state.engine) as session:
            alerts = tuple(
                session.scalars(
                    select(Alert)
                    .where(
                        Alert.expires_at > self.state.clock.now(),
                        Alert.config_hash == self.settings.config_hash,
                        Alert.score >= self.settings.auto_min_score,
                    )
                    .order_by(Alert.seq)
                )
            )
        counts = {"submitted": 0, "refused": 0}
        for alert in alerts:
            if self.state.ledger.current_alert_status(alert.id) != "SENT":
                continue
            try:
                await self.executor.enter(alert.proposal_id)
                counts["submitted"] += 1
            except (ExecutionDisabledError, OrderRejectedError):
                counts["refused"] += 1
            if not self.modes.entries_enabled:
                break
        return JobCounts(counts=counts)

    async def poll(self) -> JobCounts:
        try:
            await self.sync_fills()
        finally:
            # A data failure halts entries but cannot suppress stop verification.
            await self.executor.monitor()
        return JobCounts(counts={"activity_polls": 1, "monitors": 1})

    async def tick(self, name: AutoJob) -> None:
        if self._locks[name].locked():
            return
        async with self._locks[name]:
            started = ensure_utc(self.state.clock.now())
            if not self.due(name, started):
                return
            loop, counts, outcome, cancelled = (
                asyncio.get_running_loop(),
                JobCounts(),
                "PASS",
                False,
            )
            mono = loop.time()
            try:
                if name == "auto_entry" and not self.modes.entries_enabled:
                    outcome = "SKIPPED"
                else:
                    async with asyncio.timeout(600):
                        counts = JobCounts.model_validate(
                            await (self.entry() if name == "auto_entry" else self.poll())
                        )
            except asyncio.CancelledError:
                cancelled, outcome = True, "FAIL"
                self.state.escalate(SystemState.HALTED, "Auto job cancelled")
            except Exception as error:
                outcome = "FAIL"
                self.state.halt_for_error(error)
                self.state.ledger.append(
                    SecurityEvent,
                    kind="AUTO_JOB_FAILED",
                    detail={
                        "job": name,
                        "account_id": self.modes.account_id,
                        "environment": self.modes.environment,
                        "error_type": type(error).__name__,
                    },
                )
            self.state.ledger.append(
                AutoJobRun,
                job=name,
                account_id=self.modes.account_id,
                environment=self.modes.environment,
                config_hash=self.settings.config_hash,
                started_at=started,
                finished_at=ensure_utc(self.state.clock.now()),
                outcome=outcome,
                counts=counts.counts,
                duration_ms=max(0, int((loop.time() - mono) * 1000)),
            )
            if cancelled:
                raise asyncio.CancelledError
