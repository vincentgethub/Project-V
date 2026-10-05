"""R-05: injectable clocks and a single aware-UTC timestamp boundary."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from backend.core.errors import DataIntegrityError


def ensure_utc(value: datetime) -> datetime:
    """R-05/DAT-02: reject naive timestamps and normalize aware ones to UTC."""
    if not isinstance(value, datetime):
        raise DataIntegrityError("timestamp must be a datetime")
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            raise DataIntegrityError("timestamp must be timezone-aware")
        return value.astimezone(UTC)
    except DataIntegrityError:
        raise
    except Exception as exc:
        raise DataIntegrityError("timestamp could not be normalized to UTC") from exc


class Clock(Protocol):
    """R-05: rules receive time rather than reading the system clock."""

    def now(self) -> datetime:
        """Return a timezone-aware UTC timestamp."""
        raise NotImplementedError("Clock implementations must supply now")


class SystemClock:
    """R-05: the only core boundary permitted to read wall-clock time."""

    def now(self) -> datetime:
        """R-05: read wall-clock time in UTC."""
        return datetime.now(UTC)


@dataclass(frozen=True)
class FrozenClock:
    """R-05: an immutable deterministic clock for tests and replay."""

    current: datetime

    def __post_init__(self) -> None:
        """R-05: validate and normalize the supplied instant once."""
        object.__setattr__(self, "current", ensure_utc(self.current))

    def now(self) -> datetime:
        """R-05: return the injected instant without consulting the system."""
        return self.current
