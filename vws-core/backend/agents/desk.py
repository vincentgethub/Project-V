"""GD-04: durable cooldown and atomic daily-card admission before research."""

from datetime import timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.agents.swarm_runner import ResearchRequest, SwarmResult, SwarmRunner
from backend.core.clock import ensure_utc
from backend.core.database import Alert, SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.domain.models import FrozenModel


class DeskResult(FrozenModel):
    status: Literal["COOLDOWN", "DAILY_CAP", "DROPPED", "VETOED", "ALERT"]
    research: SwarmResult | None = None


class Desk:
    def __init__(self, swarm: SwarmRunner) -> None:
        self.swarm = swarm
        self.ledger = swarm.ledger

    async def research(self, request: ResearchRequest) -> DeskResult:
        try:
            request = ResearchRequest.model_validate(request)
            self.ledger.verify_chain()
            candidate = request.candidate
            now = ensure_utc(self.swarm.clock.now())
            ny = now.astimezone(ZoneInfo("America/New_York"))
            start = ny.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            calendar = self.swarm.risk.cro.calendar
            current_session = calendar.last_completed_session(now)
            past = calendar.previous_sessions(
                current_session, self.swarm.config.alerts.alert_cooldown_sessions - 1
            )
            cooldown_sessions = {*past, current_session}
            with transaction(self.ledger.engine) as session:
                cards = tuple(
                    session.scalars(
                        select(Alert).where(Alert.created_at >= start, Alert.created_at < end)
                    )
                )
                events = tuple(
                    session.scalars(
                        select(SecurityEvent).where(
                            SecurityEvent.created_at >= start,
                            SecurityEvent.created_at < end,
                            SecurityEvent.kind.in_(("DESK_RESERVED", "DESK_COMPLETED")),
                        )
                    )
                )
                completed = {row.detail["token"] for row in events if row.kind == "DESK_COMPLETED"}
                active = [
                    row
                    for row in events
                    if row.kind == "DESK_RESERVED" and row.detail["token"] not in completed
                ]
                latest = session.scalar(
                    select(Alert)
                    .where(
                        Alert.symbol == candidate.symbol, Alert.playbook == candidate.playbook.value
                    )
                    .order_by(Alert.seq.desc())
                    .limit(1)
                )
                suppressed: Literal["", "COOLDOWN", "DAILY_CAP"] = ""
                if (
                    latest is not None
                    and calendar.last_completed_session(latest.created_at) in cooldown_sessions
                    or any(
                        row.detail["symbol"] == candidate.symbol
                        and row.detail["playbook"] == candidate.playbook.value
                        for row in active
                    )
                ):
                    suppressed = "COOLDOWN"
                elif len(cards) + len(active) >= self.swarm.settings.max_alerts_per_day:
                    suppressed = "DAILY_CAP"
                if suppressed:
                    self.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="DESK_SUPPRESSED",
                        detail={
                            "symbol": candidate.symbol,
                            "playbook": candidate.playbook.value,
                            "reason": suppressed,
                        },
                    )
                    return DeskResult(status=suppressed)
                token = uuid4().hex
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="DESK_RESERVED",
                    detail={
                        "token": token,
                        "symbol": candidate.symbol,
                        "playbook": candidate.playbook.value,
                    },
                )
            try:
                result = await self.swarm.run(request)
                return DeskResult(status=result.status, research=result)
            finally:
                self.ledger.append(SecurityEvent, kind="DESK_COMPLETED", detail={"token": token})
        except Exception as error:
            self.swarm.state.halt_for_error(error)
            raise DataIntegrityError("GD-04: desk admission failed; entries halted") from None
