"""OPS-02/03: one asyncio lifecycle, guarded startup and health evidence."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.orchestrator import Orchestrator
from backend.core.config import Settings
from backend.core.database import SecurityEvent, SystemEvent, enable_sqlite_wal
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.logging import redact
from backend.core.notifier import ConsoleNotifier, DeduplicatingNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.ops.doctor import DoctorResult
from backend.ops.process import Heartbeat, write_heartbeat
from backend.ops.watchdog import Watchdog


class PollingDesk(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def notify(self, text: str, urgent: bool) -> None: ...


class SafetyNotifications:
    """Thread-safe queue; failed delivery remains pending and is retried.

    Synchronous state transitions never block the same event loop that must
    deliver Telegram. A bounded queue overflow is a typed notification fault.
    """

    def __init__(self) -> None:
        self.queue: Queue[tuple[str, str]] = Queue(maxsize=100)
        self.pending: tuple[str, str] | None = None

    def notify(self, state: str, reason: str) -> None:
        safe = str(redact(reason))[:280]
        ConsoleNotifier().notify(state, safe)
        try:
            self.queue.put_nowait((state, safe))
        except Full:
            raise ProviderError(
                "Safety notification queue is full; delivery is UNVERIFIED"
            ) from None

    async def flush(self, bot: PollingDesk, state: SystemStateStore) -> None:
        if self.pending is None:
            try:
                self.pending = self.queue.get_nowait()
            except Empty:
                return
        operating, reason = self.pending
        try:
            async with asyncio.timeout(30):
                await bot.notify(f"Urgent: {operating}: {reason}", True)
        except Exception as error:
            state.ledger.append(
                SecurityEvent,
                kind="SAFETY_NOTIFICATION_FAILED",
                detail={"error_type": type(error).__name__},
            )
            raise ProviderError(
                "Safety notification remains pending after failed delivery"
            ) from None
        state.ledger.append(
            SecurityEvent, kind="SAFETY_NOTIFICATION_DELIVERED", detail={"state": operating}
        )
        self.pending = None


class HostRuntime:
    def __init__(
        self,
        settings: Settings,
        state: SystemStateStore,
        orchestrator: Orchestrator,
        bot: PollingDesk,
        watchdog: Watchdog,
        heartbeat_path: Path,
        doctor: Callable[[], Awaitable[DoctorResult]],
        *,
        close_resources: Callable[[], Awaitable[None]],
        verify_broker_time: Callable[[], Awaitable[object]],
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        if (
            self.settings.execution_mode != "MANUAL"
            or not self.settings.paper_trading
            or orchestrator.state is not state
            or watchdog.state is not state
        ):
            raise ConfigurationError(
                "Stage H startup requires the bound MANUAL paper desk; auto modes await Stage I"
            )
        self.state, self.orchestrator, self.bot, self.watchdog = state, orchestrator, bot, watchdog
        self.heartbeat_path, self.doctor, self.close_resources = (
            heartbeat_path,
            doctor,
            close_resources,
        )
        self.run_id = uuid4()
        self.verify_broker_time = verify_broker_time
        self.notifications = SafetyNotifications()
        self.state.notifier = DeduplicatingNotifier(self.notifications)

    async def run(self, stop: asyncio.Event) -> None:
        started_bot = False
        try:
            result = DoctorResult.model_validate(await self.doctor())
            if result.exit_code != 0:
                raise ConfigurationError(
                    "Required doctor checks failed or are UNVERIFIED; runtime startup is refused"
                )
            self.state.startup()
            enable_sqlite_wal(self.state.engine)
            started_bot = True  # cleanup covers partial polling initialization
            await self.bot.start()
            self.orchestrator.start()
            self.state.ledger.append(
                SecurityEvent,
                kind="HOST_STARTED",
                detail={"run_id": str(self.run_id), "mode": "MANUAL", "cohort": "PAPER"},
            )
            with Session(self.state.engine) as session:
                last_state = session.scalar(
                    select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1)
                )
            reason = "" if last_state is None else ": " + str(redact(last_state.reason))[:280]
            await self.bot.notify(
                "Project V started: MANUAL, paper. State: "
                + self.state.current().value
                + reason
                + ". Held exit warnings continue during a halt.",
                True,
            )
            while not stop.is_set():
                await self.verify_broker_time()
                if not await asyncio.to_thread(self.orchestrator.healthcheck):
                    raise DataIntegrityError("Runtime scheduler health cannot be verified")
                await self.watchdog.check()
                notification_ok = True
                try:
                    await self.notifications.flush(self.bot, self.state)
                except ProviderError as error:
                    self.state.halt_for_error(error)
                    notification_ok = False
                if not notification_ok:
                    # Keep polling/held exits alive, retain pending urgent delivery,
                    # and let the heartbeat expire while delivery is unverified.
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=30)
                    except TimeoutError:
                        pass
                    continue
                await asyncio.to_thread(
                    write_heartbeat,
                    self.heartbeat_path,
                    Heartbeat(
                        run_id=self.run_id,
                        updated_at=self.state.clock.now(),
                        mode="MANUAL",
                        paper=True,
                        scheduler_running=True,
                    ),
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            self.state.escalate(
                SystemState.HALTED,
                "Host lifecycle cancelled; inspect before audited reset",
            )
            raise
        except Exception as error:
            self.state.halt_for_error(error)
            raise
        finally:
            cleanup_error: Exception | None = None
            actions: list[tuple[str, Callable[[], Awaitable[None]]]] = [
                ("scheduler", self.orchestrator.aclose)
            ]
            if started_bot:
                actions.append(("polling", self.bot.stop))
            actions.append(("resources", self.close_resources))
            for name, close in actions:
                try:
                    async with asyncio.timeout(35):
                        await close()
                except Exception as error:
                    cleanup_error = error
                    self.state.halt_for_error(error)
                    self.state.ledger.append(
                        SecurityEvent,
                        kind="HOST_CLEANUP_FAILED",
                        detail={"component": name, "error_type": type(error).__name__},
                    )
            self.state.ledger.append(
                SecurityEvent,
                kind="HOST_STOPPED",
                detail={
                    "run_id": str(self.run_id),
                    "pending_notifications": self.notifications.queue.qsize()
                    + int(self.notifications.pending is not None),
                    "cleanup_verified": cleanup_error is None,
                },
            )
            if cleanup_error is not None:
                raise ProviderError("Host shutdown could not be fully verified; HALTED") from None
