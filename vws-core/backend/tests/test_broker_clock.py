"""OPS-01/RT-01: actual verifier with fake reads, clocks and disposable ledger."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.config import Settings
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, LedgerIntegrityError, ProviderError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.broker_clock import BrokerTimeVerifier
from backend.data.market_calendar import MarketCalendar

NY = ZoneInfo("America/New_York")


@dataclass
class MovingClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


class Reads:
    def __init__(self, calendar: MarketCalendar, clock: MovingClock, fault: str = "") -> None:
        self.calendar, self.clock, self.fault = calendar, clock, fault
        self.calendar_calls = self.clock_calls = 0

    async def sessions(self, start: date, end: date) -> object:
        self.calendar_calls += 1
        rows = [
            {
                "date": day.isoformat(),
                "open": self.calendar.session_open(day).astimezone(NY).strftime("%H:%M"),
                "close": self.calendar.session_close(day).astimezone(NY).strftime("%H:%M"),
            }
            for i in range((end - start).days + 1)
            if self.calendar.is_session(day := start + timedelta(days=i))
        ]
        if self.fault == "missing_session":
            rows.pop()
        elif self.fault == "duplicate":
            rows.append(rows[-1])
        elif self.fault == "reordered":
            rows.reverse()
        elif self.fault == "hours":
            rows[0]["close"] = "17:00"
        elif self.fault == "date":
            rows[0]["date"] = "bad"
        elif self.fault == "time":
            rows[0]["open"] = "09:30:00"
        elif self.fault == "list":
            return {"sessions": rows}
        elif self.fault == "oversized":
            return rows * 40
        elif self.fault == "provider":
            raise ProviderError("injected provider unavailable")
        return rows

    async def time(self) -> object:
        self.clock_calls += 1
        now = self.clock.now()
        today = now.astimezone(NY).date()
        future = [today + timedelta(days=i) for i in range(15)]
        future = [day for day in future if self.calendar.is_session(day)]
        opened = next(
            self.calendar.session_open(day)
            for day in future
            if self.calendar.session_open(day) > now
        )
        closed = next(
            self.calendar.session_close(day)
            for day in future
            if self.calendar.session_close(day) > now
        )
        result: dict[str, object] = {
            "timestamp": now.isoformat(),
            "is_open": self.calendar.is_open(now),
            "next_open": opened.isoformat(),
            "next_close": closed.isoformat(),
        }
        if self.fault in {"past", "future"}:
            result["timestamp"] = (
                now + timedelta(seconds=-3 if self.fault == "past" else 3)
            ).isoformat()
        elif self.fault == "naive":
            result["timestamp"] = now.replace(tzinfo=None).isoformat()
        elif self.fault == "flag":
            result["is_open"] = not self.calendar.is_open(now)
        elif self.fault == "bool":
            result["is_open"] = 1
        elif self.fault == "next_close":
            result["next_close"] = (closed + timedelta(minutes=1)).isoformat()
        elif self.fault == "next_open":
            result["next_open"] = (opened + timedelta(minutes=1)).isoformat()
        elif self.fault == "uncertainty":
            self.clock.current += timedelta(seconds=3)
        elif self.fault == "backward":
            self.clock.current -= timedelta(seconds=1)
        elif self.fault == "clock_list":
            return [result]
        return result


def verifier(
    engine: Engine, calendar: MarketCalendar, now: datetime, fault: str = ""
) -> tuple[BrokerTimeVerifier, Reads, SystemStateStore]:
    clock = MovingClock(now)
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    source = Reads(calendar, clock, fault)
    settings = Settings(_env_file=None, broker_account_type="CASH")
    return (
        BrokerTimeVerifier(settings, calendar, clock, state, source.time, source.sessions),
        source,
        state,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 29, 15, tzinfo=UTC),
        datetime(2026, 11, 27, 17, tzinfo=UTC),
        datetime(2026, 11, 27, 19, tzinfo=UTC),
        datetime(2026, 11, 26, 15, tzinfo=UTC),
        datetime(2026, 3, 9, 15, tzinfo=UTC),
    ],
)
async def test_RT_01_normal_early_close_holiday_and_DST_cache(
    engine: Engine, calendar: MarketCalendar, now: datetime
) -> None:
    service, source, state = verifier(engine, calendar, now)
    first, second = await asyncio.gather(service.verify(), service.verify())
    assert first == second and first.is_open == calendar.is_open(now)
    assert source.calendar_calls == 1 and source.clock_calls == 2
    assert state.current() == SystemState.RUNNING
    state.ledger.verify_chain()
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "BROKER_CALENDAR_VERIFIED")
            )
        )
    assert len(rows) == 1 and rows[0].detail["endpoint"] == "https://paper-api.alpaca.markets"
    source.clock.current += timedelta(days=1)
    await service.verify()
    assert source.calendar_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "missing_session",
        "duplicate",
        "reordered",
        "hours",
        "date",
        "time",
        "list",
        "oversized",
        "past",
        "future",
        "naive",
        "flag",
        "bool",
        "next_close",
        "next_open",
        "uncertainty",
        "backward",
        "clock_list",
        "provider",
    ],
)
async def test_RT_01_unverified_time_never_passes_and_durably_halts(
    engine: Engine, calendar: MarketCalendar, fault: str
) -> None:
    service, source, state = verifier(
        engine, calendar, datetime(2026, 9, 29, 15, tzinfo=UTC), fault
    )
    with pytest.raises((DataIntegrityError, ProviderError)):
        await service.verify()
    assert state.current() == SystemState.HALTED
    if fault == "backward":
        with pytest.raises(LedgerIntegrityError):
            state.ledger.verify_chain()
        source.clock.current = datetime(2026, 9, 29, 15, tzinfo=UTC)
    state.ledger.verify_chain()
    assert state.current() == SystemState.HALTED
