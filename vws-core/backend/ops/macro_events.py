"""XK-04: bounded owner-maintained calendar; existing CRO-11 windows only."""

import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.domain.models import BlackoutWindow, FrozenModel, SessionDate, UTCDateTime

NY = ZoneInfo("America/New_York")
OFFICIAL_HOSTS = frozenset({"www.federalreserve.gov", "www.bls.gov", "www.bea.gov"})
LEGACY_COLUMNS = ["date", "et_time", "event", "source"]
# Item 4: an owner-marked provisional time only ever widens its blackout.
TIME_STATUS = {"confirmed": True, "provisional": False}


class MacroEvent(FrozenModel):
    date: SessionDate
    release_at: UTCDateTime
    event: Literal["FOMC", "CPI", "NFP", "GDP", "PCE"]
    source: str = Field(strict=True, min_length=1, max_length=512)
    time_confirmed: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def bound(self) -> Self:
        parts = urlsplit(self.source)
        if (
            self.release_at.astimezone(NY).date() != self.date
            or parts.scheme != "https"
            or parts.hostname not in OFFICIAL_HOSTS
            or parts.username
            or parts.password
            or parts.port not in {None, 443}
            or parts.fragment
        ):
            raise ValueError("XK-04: date and official HTTPS calendar source required")
        return self

    def window(self) -> BlackoutWindow:
        if not self.time_confirmed:
            return BlackoutWindow(
                start=datetime.combine(self.date, time(), NY).astimezone(UTC),
                end=datetime.combine(self.date + timedelta(days=1), time(), NY).astimezone(UTC)
                + timedelta(minutes=30),
                reason=f"Macro {self.event} release time unconfirmed; full ET day",
            )
        return BlackoutWindow(
            start=datetime.combine(self.date, time(), NY).astimezone(UTC),
            end=self.release_at + timedelta(minutes=30),
            reason=f"Macro {self.event} release plus 30 minutes",
        )


def horizon(rows: tuple[MacroEvent, ...]) -> date | None:
    """The last ET date the calendar covers; None for an empty calendar."""
    return max((row.date for row in rows), default=None)


class MacroCalendar:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> tuple[MacroEvent, ...]:
        try:
            if (
                self.path.is_symlink()
                or self.path.parent.resolve(strict=True) != self.path.parent.absolute()
            ):
                raise ValueError("indirect calendar path")
            if self.path.stat().st_size > 65536:
                raise ValueError("calendar size exceeds bound")
            reader = csv.DictReader(io.StringIO(self.path.read_text(encoding="utf-8-sig")))
            marked = reader.fieldnames == [*LEGACY_COLUMNS, "time_status"]
            if reader.fieldnames != LEGACY_COLUMNS and not marked:
                raise ValueError("calendar columns differ")
            rows = list(reader)
            if len(rows) > 500:
                raise ValueError("calendar event count exceeds bound")
            result = []
            for row in rows:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("malformed calendar row")
                day = date.fromisoformat(row["date"])
                clock = time.fromisoformat(row["et_time"])
                if clock.tzinfo is not None or clock.second or clock.microsecond:
                    raise ValueError("ET calendar time must be local minute precision")
                local = datetime.combine(day, clock, NY)
                # Reject nonexistent/ambiguous DST wall times, never guess.
                if (
                    local.replace(fold=1).utcoffset() != local.utcoffset()
                    or local.astimezone(UTC).astimezone(NY) != local
                ):
                    raise ValueError("ambiguous or nonexistent ET release time")
                result.append(
                    MacroEvent.model_validate(
                        {
                            "date": day,
                            "release_at": local.astimezone(UTC),
                            "event": row["event"],
                            "source": row["source"],
                            "time_confirmed": TIME_STATUS[row["time_status"]] if marked else True,
                        }
                    )
                )
            keys = tuple((row.date, row.event) for row in result)
            if len(set(keys)) != len(keys):
                raise ValueError("duplicate macro event")
            return tuple(sorted(result, key=lambda row: (row.release_at, row.event)))
        except Exception:
            raise DataIntegrityError(
                "XK-04: macro calendar is missing, invalid or unbounded"
            ) from None

    def warnings(self, now: datetime) -> tuple[str, ...]:
        checked = ensure_utc(now)
        self.read()
        try:
            modified = datetime.fromtimestamp(self.path.stat().st_mtime, UTC)
        except OSError:
            raise DataIntegrityError("XK-04: macro calendar cannot be inspected") from None
        if modified > checked:
            raise DataIntegrityError("XK-04: macro calendar modification is future")
        rows, today = self.read(), checked.astimezone(NY).date()
        lines = (
            ["Macro calendar is over 90 days old; verify official release dates."]
            if checked - modified > timedelta(days=90)
            else []
        )
        last = horizon(rows)
        if last is not None and today > last:
            lines.append(
                f"Macro calendar is past its horizon ({last.isoformat()}); entries are blacked "
                "out until official release dates are added and confirmed."
            )
        lines.extend(
            f"{row.event} {row.date.isoformat()} has no confirmed official release time; "
            "that ET day is a full entry blackout until the time is confirmed."
            for row in rows
            if not row.time_confirmed and row.date >= today
        )
        return tuple(lines)
