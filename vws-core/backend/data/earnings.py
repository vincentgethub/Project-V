"""DAT-11: manual overrides, optional evidence, then point-in-time SEC estimates."""

from __future__ import annotations

import asyncio
import csv
import io
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.core.clock import ensure_utc
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.domain.models import EarningsInfo, EarningsStatus, validate_symbol

EarningsLookup = Callable[[str, datetime], Awaitable[EarningsInfo | None]]
SubmissionsLookup = Callable[[str, datetime], Awaitable[Mapping[str, object] | None]]
_MAX_CALENDAR_BYTES = 1_048_576
_NEW_YORK = ZoneInfo("America/New_York")


def _iso_date(value: object) -> date:
    """DAT-11: dates are explicit ISO calendar labels, never parsed timestamps."""
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise DataIntegrityError("DAT-11: earnings evidence needs an ISO calendar date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise DataIntegrityError("DAT-11: earnings evidence has an invalid date") from None


class EarningsProvider:
    """DAT-11: no third-party or SEC network client is enabled by construction.

    Injected async readers own HTTP retries and provenance. The SEC reader is
    shared with the later SEC provider; this module never opens a second client.
    Past manual/optional dates and expired estimates do not establish clearance.
    Expected unavailable reads fall through to UNKNOWN, which the CRO warns on.
    Malformed evidence raises a typed error for the caller's fail-closed boundary.
    """

    def __init__(
        self,
        calendar_path: Path,
        *,
        known_symbols: frozenset[str],
        third_party: EarningsLookup | None = None,
        submissions: SubmissionsLookup | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        """DAT-11: freeze the allowlist and bound every optional evidence read."""
        try:
            if not isinstance(known_symbols, frozenset) or not known_symbols:
                raise ValueError("a nonempty immutable symbol allowlist is required")
            for symbol in known_symbols:
                validate_symbol(symbol)
            if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
                raise ValueError("earnings timeout must be bounded")
            if third_party is not None and not callable(third_party):
                raise ValueError("optional earnings reader must be callable")
            if submissions is not None and not callable(submissions):
                raise ValueError("SEC submissions reader must be callable")
            self.calendar_path = Path(calendar_path)
            self.known_symbols = known_symbols
            self.third_party = third_party
            self.submissions = submissions
            self.timeout_seconds = timeout_seconds
        except Exception:
            raise ConfigurationError("DAT-11: earnings provider configuration is invalid") from None

    def _manual(self, symbol: str, today: date) -> EarningsInfo | None:
        """DAT-11: each read observes edits; an empty/header-only calendar is valid."""
        path = self.calendar_path
        if path.is_symlink():
            raise DataIntegrityError("DAT-11: manual earnings calendar must not be a symbolic link")
        if not path.exists():
            return None
        try:
            if not path.is_file():
                raise DataIntegrityError("DAT-11: manual earnings calendar is not a regular file")
            with path.open("rb") as handle:
                raw = handle.read(_MAX_CALENDAR_BYTES + 1)
            if len(raw) > _MAX_CALENDAR_BYTES:
                raise DataIntegrityError("DAT-11: manual earnings calendar is oversized")
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            if (
                reader.fieldnames is None
                or len(reader.fieldnames) != 2
                or set(reader.fieldnames) != {"symbol", "date"}
            ):
                raise DataIntegrityError(
                    "DAT-11: manual earnings calendar headers must be symbol,date"
                )
            matches: list[date] = []
            seen: set[tuple[str, date]] = set()
            for row in reader:
                if set(row) != {"symbol", "date"} or any(
                    not isinstance(value, str) or not value for value in row.values()
                ):
                    raise DataIntegrityError("DAT-11: manual earnings calendar row is incomplete")
                ticker = validate_symbol(row["symbol"])
                if ticker not in self.known_symbols:
                    raise DataIntegrityError("DAT-11: manual earnings symbol is not allowlisted")
                event = _iso_date(row["date"])
                key = ticker, event
                if key in seen:
                    raise DataIntegrityError(
                        "DAT-11: manual earnings calendar has duplicate evidence"
                    )
                seen.add(key)
                if ticker == symbol and event >= today:
                    matches.append(event)
            if not matches:
                return None
            return EarningsInfo(date=min(matches), status=EarningsStatus.KNOWN, source="manual CSV")
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError(
                "DAT-11: manual earnings calendar cannot be verified"
            ) from None

    @staticmethod
    def _current(info: EarningsInfo, today: date) -> bool:
        """DAT-11: expired evidence is uncertainty, never a current clear date."""
        if info.status == EarningsStatus.KNOWN:
            return info.date is not None and info.date >= today
        return (
            info.status == EarningsStatus.ESTIMATED
            and info.window_end is not None
            and info.window_end >= today
        )

    @staticmethod
    def _estimate(payload: Mapping[str, object], today: date) -> EarningsInfo | None:
        """DAT-11: recent 10-Q/10-K filing dates are filtered before estimation."""
        try:
            filings = payload.get("filings")
            if not isinstance(filings, Mapping):
                raise DataIntegrityError("DAT-11: SEC submissions require a filings object")
            recent = filings.get("recent")
            if not isinstance(recent, Mapping):
                raise DataIntegrityError("DAT-11: SEC submissions require recent filings")
            forms, dates = recent.get("form"), recent.get("filingDate")
            if (
                not isinstance(forms, list)
                or not isinstance(dates, list)
                or len(forms) != len(dates)
            ):
                raise DataIntegrityError("DAT-11: SEC filing arrays are incomplete")
            eligible: list[date] = []
            for form, raw_date in zip(forms, dates, strict=True):
                if not isinstance(form, str):
                    raise DataIntegrityError("DAT-11: SEC filing form is invalid")
                filed = _iso_date(raw_date)
                if form in {"10-Q", "10-K"} and filed <= today:
                    eligible.append(filed)
            if not eligible:
                return None
            latest = max(eligible)
            start, end = latest + timedelta(days=85), latest + timedelta(days=100)
            if end < today:
                return None
            return EarningsInfo(
                status=EarningsStatus.ESTIMATED,
                source="SEC submissions estimate",
                window_start=start,
                window_end=end,
            )
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("DAT-11: SEC earnings estimate cannot be verified") from None

    async def get(self, symbol: str, as_of: datetime) -> EarningsInfo:
        """DAT-11: manual -> optional third party -> SEC estimate -> UNKNOWN."""
        try:
            validate_symbol(symbol)
            if symbol not in self.known_symbols:
                raise DataIntegrityError("DAT-11: requested earnings symbol is not allowlisted")
            instant = ensure_utc(as_of)
            today = instant.astimezone(_NEW_YORK).date()
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("DAT-11: earnings request is invalid") from None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                manual = await asyncio.to_thread(self._manual, symbol, today)
        except TimeoutError:
            raise ProviderError("DAT-11: manual earnings read exceeded its deadline") from None
        except (DataIntegrityError, ProviderError):
            raise
        except Exception:
            raise DataIntegrityError("DAT-11: manual earnings read cannot be verified") from None
        if manual is not None:
            return manual
        if self.third_party is not None:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    optional = await self.third_party(symbol, instant)
            except (ProviderError, TimeoutError, OSError):
                optional = None
            except Exception:
                raise ProviderError("DAT-11: optional earnings read failed") from None
            if optional is not None:
                try:
                    checked = EarningsInfo.model_validate(optional)
                except Exception:
                    raise DataIntegrityError(
                        "DAT-11: optional earnings evidence is invalid"
                    ) from None
                if self._current(checked, today):
                    return checked
        if self.submissions is not None:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    payload = await self.submissions(symbol, instant)
            except (ProviderError, TimeoutError, OSError):
                payload = None
            except Exception:
                raise ProviderError("DAT-11: SEC submissions read failed") from None
            if payload is not None:
                if not isinstance(payload, Mapping):
                    raise DataIntegrityError("DAT-11: SEC submissions evidence is invalid")
                estimate = self._estimate(payload, today)
                if estimate is not None:
                    return estimate
        return EarningsInfo(
            status=EarningsStatus.UNKNOWN, source="unknown: no current earnings evidence"
        )
