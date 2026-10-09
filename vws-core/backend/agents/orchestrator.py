"""GD-04: calendar-driven jobs and immutable run evidence.

Job bodies are composed by the host runtime. Each callback is awaited under a
single instance lock; HALTED suppresses entries while monitors keep running.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from structlog.contextvars import bound_contextvars

from backend.core.clock import Clock, ensure_utc
from backend.core.config import YamlConfig
from backend.core.database import JobRun, SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel


class JobName(StrEnum):
    DAILY_SCAN = "daily_scan"
    PREMARKET_CHECK = "premarket_check"
    POSITION_MONITOR = "position_monitor"
    NEWS_WATCH = "news_watch"
    WEEKLY_REPORT = "weekly_report"
    HOUSEKEEPING = "housekeeping"


class JobCounts(FrozenModel):
    counts: dict[str, int] = Field(default_factory=dict, max_length=30)

    @field_validator("counts", mode="before")
    @classmethod
    def bounded(cls, value: object) -> object:
        if not isinstance(value, dict) or any(
            not isinstance(key, str)
            or not 1 <= len(key) <= 48
            or not key.isascii()
            or not key.replace("_", "").isalnum()
            or type(number) is not int
            or not 0 <= number <= 10**9
            for key, number in value.items()
        ):
            raise ValueError("GD-04: job counts require bounded exact nonnegative integers")
        return value


JobBody = Callable[[], Awaitable[JobCounts]]


class Orchestrator:
    def __init__(
        self,
        config: YamlConfig,
        calendar: MarketCalendar,
        state: SystemStateStore,
        clock: Clock,
        jobs: Mapping[JobName, JobBody],
        *,
        on_finished: Callable[[JobRun], Awaitable[None]] | None = None,
        auto_tick: Callable[[Literal["auto_entry", "auto_poll"]], Awaitable[None]] | None = None,
    ) -> None:
        self.config = YamlConfig.model_validate(config)
        if set(jobs) != set(JobName) or state.clock is not clock:
            raise ConfigurationError("GD-04: all six jobs and the bound clock are required")
        self.calendar, self.state, self.clock = calendar, state, clock
        self.jobs = dict(jobs)
        self.on_finished = on_finished
        self.auto_tick = auto_tick
        self._locks = {name: asyncio.Lock() for name in JobName}
        self._active: set[asyncio.Task[object]] = set()
        self._closing = False
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        for name in JobName:
            # A minute dispatcher computes close/holiday/DST eligibility from
            # the verified calendar, rather than a guessed wall-clock close.
            self.scheduler.add_job(
                self.tick,
                "interval",
                minutes=1,
                args=(name,),
                id=name.value,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=self.config.schedule.scheduler_misfire_grace_seconds,
            )

        if auto_tick is not None:
            for auto_name in ("auto_entry", "auto_poll"):
                self.scheduler.add_job(
                    self._tick_auto,
                    "interval",
                    seconds=60,
                    args=(auto_name,),
                    id=auto_name,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=self.config.schedule.scheduler_misfire_grace_seconds,
                )

    async def _tick_auto(self, name: Literal["auto_entry", "auto_poll"]) -> None:
        task = asyncio.current_task()
        if self._closing or task is None or self.auto_tick is None:
            return
        self._active.add(task)
        try:
            with bound_contextvars(cycle_id=str(uuid4()), job=name):
                await self.auto_tick(name)
        finally:
            self._active.discard(task)

    def _latest(self, name: JobName) -> JobRun | None:
        with Session(self.state.engine) as session:
            return session.scalar(
                select(JobRun).where(JobRun.job == name.value).order_by(JobRun.seq.desc()).limit(1)
            )

    def due(self, name: JobName, now: datetime) -> bool:
        instant = ensure_utc(now)
        ny = instant.astimezone(ZoneInfo("America/New_York"))
        latest = self._latest(name)
        if latest is not None and latest.started_at > instant:
            raise DataIntegrityError("GD-04: job clock moved backward")
        schedule = self.config.schedule
        session = self.calendar.is_session(ny.date())
        if name in {JobName.DAILY_SCAN, JobName.WEEKLY_REPORT, JobName.PREMARKET_CHECK}:
            if not session or (name == JobName.WEEKLY_REPORT and ny.weekday() != 4):
                return False
            due_at = (
                (
                    datetime.combine(ny.date(), datetime.min.time(), ZoneInfo("America/New_York"))
                    + timedelta(hours=8, minutes=45)
                )
                if name == JobName.PREMARKET_CHECK
                else (
                    self.calendar.session_close(ny.date())
                    + timedelta(
                        minutes=30
                        if name == JobName.WEEKLY_REPORT
                        else schedule.daily_scan_delay_minutes
                    )
                )
            )
            if (
                latest is not None
                and latest.started_at.astimezone(ZoneInfo("America/New_York")).date() == ny.date()
            ):
                return False
            return (
                due_at
                <= instant
                <= due_at + timedelta(seconds=schedule.scheduler_misfire_grace_seconds)
            )
        if name == JobName.HOUSEKEEPING:
            due_at = datetime.combine(
                ny.date(), datetime.min.time(), ZoneInfo("America/New_York")
            ) + timedelta(hours=2)
            return due_at <= instant <= due_at + timedelta(
                seconds=schedule.scheduler_misfire_grace_seconds
            ) and (
                latest is None
                or latest.started_at.astimezone(ZoneInfo("America/New_York")).date() != ny.date()
            )
        interval = schedule.offhours_news_interval_minutes
        if name == JobName.POSITION_MONITOR:
            if not self.calendar.is_open(instant):
                return False
            interval = schedule.monitor_interval_minutes
            anchor = self.calendar.session_open(ny.date())
        else:
            anchor = datetime.combine(ny.date(), datetime.min.time(), ZoneInfo("America/New_York"))
        elapsed = int((instant - anchor).total_seconds())
        period = interval * 60
        slot = anchor + timedelta(seconds=(elapsed // period) * period)
        return instant - slot <= timedelta(seconds=schedule.scheduler_misfire_grace_seconds) and (
            latest is None or latest.started_at < slot
        )

    async def tick(self, name: JobName) -> None:
        task = asyncio.current_task()
        if self._closing or task is None:
            return
        self._active.add(task)
        try:
            with bound_contextvars(cycle_id=str(uuid4()), job=name.value):
                await self._tick(name)
        finally:
            self._active.discard(task)

    async def _tick(self, name: JobName) -> None:
        if self._locks[name].locked():
            return
        async with self._locks[name]:
            started = ensure_utc(self.clock.now())
            if not self.due(name, started):
                return
            outcome, counts = "PASS", JobCounts()
            cancelled = False
            loop = asyncio.get_running_loop()
            start_mono = loop.time()
            try:
                self.state.ledger.verify_chain()
                if name == JobName.DAILY_SCAN and self.state.current() != SystemState.RUNNING:
                    outcome = "SKIPPED"
                else:
                    async with asyncio.timeout(600):
                        counts = JobCounts.model_validate(await self.jobs[name]())
            except asyncio.CancelledError:
                cancelled, outcome = True, "FAIL"
                self.state.escalate(SystemState.HALTED, "GD-04 scheduled job cancelled")
            except Exception as exc:
                outcome = "FAIL"
                self.state.halt_for_error(exc)
                self.state.ledger.append(
                    SecurityEvent,
                    kind="JOB_FAILED",
                    detail={"job": name.value, "error_type": type(exc).__name__},
                )
            finished = ensure_utc(self.clock.now())
            if finished < started:
                self.state.escalate(SystemState.HALTED, "GD-04 job clock moved backward")
                raise DataIntegrityError("GD-04: cannot certify job interval")
            finished_run = self.state.ledger.append(
                JobRun,
                job=name.value,
                started_at=started,
                finished_at=finished,
                outcome=outcome,
                counts=counts.counts,
                duration_ms=max(0, int((loop.time() - start_mono) * 1000)),
            )
            if self.on_finished is not None:
                try:
                    async with asyncio.timeout(30):
                        await self.on_finished(finished_run)
                except Exception as exc:
                    self.state.halt_for_error(exc)
                    self.state.ledger.append(
                        SecurityEvent,
                        kind="JOB_COMPLETION_HOOK_FAILED",
                        detail={"job": name.value, "error_type": type(exc).__name__},
                    )
            if cancelled:
                raise asyncio.CancelledError

    def start(self) -> None:
        if self._closing:
            raise ConfigurationError("A closed scheduler cannot be restarted")
        self.scheduler.start()

    def stop(self) -> None:
        self._closing = True
        self.scheduler.shutdown(wait=False)

    async def aclose(self) -> None:
        """Finish cancellation audits before host resources or DB are closed."""
        self._closing = True
        if self.scheduler.running:
            self.stop()
        await asyncio.sleep(0)  # APScheduler's shutdown is queued on this loop.
        active = tuple(task for task in self._active if task is not asyncio.current_task())
        for task in active:
            task.cancel()
        if active:
            async with asyncio.timeout(35):
                await asyncio.gather(*active, return_exceptions=True)

    def healthcheck(self) -> bool:
        """A running scheduler and verified ledger are necessary, not readiness."""
        self.state.ledger.verify_chain()
        return bool(self.scheduler.running)
