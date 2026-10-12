"""EG-02: public Item 2.02 filing timestamps; unavailable timing stays explicit."""

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, SessionDate, Symbol, UTCDateTime

ET = ZoneInfo("America/New_York")


class EarningsReport(FrozenModel):
    symbol: Symbol
    report_date: SessionDate
    known_at: UTCDateTime
    accepted_at: UTCDateTime | None = None
    accession: str | None = Field(default=None, pattern=r"^\d{10}-\d{2}-\d{6}$")
    source: str = Field(pattern=r"^(SEC_8K_ITEM_202|KNOWN_CALENDAR)$")

    @model_validator(mode="after")
    def causal(self) -> Self:
        if self.accepted_at is not None and (
            self.accepted_at > self.known_at
            or self.accepted_at.astimezone(ET).date() != self.report_date
        ):
            raise ValueError("EG-02: known report date/time differs from its evidence")
        if self.source == "SEC_8K_ITEM_202" and (
            self.accession is None or self.accepted_at is None
        ):
            raise ValueError("EG-02: filing proxy needs accession and acceptance time")
        return self


def gap_sessions(
    report: EarningsReport, as_of: datetime, calendar: MarketCalendar
) -> tuple[date, ...]:
    evidence = EarningsReport.model_validate(report)
    instant = ensure_utc(as_of)
    if evidence.known_at > instant:
        return ()
    day = evidence.report_date
    for _ in range(10):
        if calendar.is_session(day):
            break
        day += timedelta(days=1)
    else:
        raise DataIntegrityError("EG-02: report session cannot be determined")
    if evidence.accepted_at is None:
        # A date-only report can gap in either the report session or the next session.
        return (day, calendar.add_sessions(day, 1)) if day == evidence.report_date else (day,)
    return (
        (day,)
        if evidence.accepted_at < calendar.session_open(day)
        else (calendar.add_sessions(day, 1),)
    )


def sec_reports(
    symbol: str, submissions: Mapping[str, object], as_of: datetime
) -> tuple[EarningsReport, ...]:
    """The SEC compact columnar recent filings; no guessed local time for naive stamps.

    # VERIFY actual submissions.items/acceptanceDateTime on the configured SEC
    # reader. These schema checks and fakes cannot certify real service access.
    """
    instant = ensure_utc(as_of)
    filings = submissions.get("filings")
    recent = filings.get("recent") if isinstance(filings, Mapping) else None
    if not isinstance(recent, Mapping):
        raise DataIntegrityError("EG-02: submissions recent filing columns unavailable")
    columns = tuple(
        recent.get(name) for name in ("form", "items", "acceptanceDateTime", "accessionNumber")
    )
    if any(not isinstance(column, list) or len(column) > 5000 for column in columns):
        raise DataIntegrityError("EG-02: required submissions columns unavailable or unbounded")
    if len({len(column) for column in columns if isinstance(column, list)}) != 1:
        raise DataIntegrityError("EG-02: submissions column lengths differ")
    rows = []
    for form, items, accepted, accession in zip(*columns, strict=True):
        if not isinstance(form, str) or not isinstance(items, str) or len(items) > 200:
            raise DataIntegrityError("EG-02: malformed filing form/items")
        if form != "8-K" or "2.02" not in tuple(part.strip() for part in items.split(",")):
            continue
        if (
            not isinstance(accepted, str)
            or len(accepted) > 40
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})", accepted) is None
        ):
            raise DataIntegrityError("EG-02: acceptance time needs an explicit timezone")
        try:
            timestamp = ensure_utc(datetime.fromisoformat(accepted.replace("Z", "+00:00")))
            if timestamp > instant:
                continue
            rows.append(
                EarningsReport(
                    symbol=symbol,
                    report_date=timestamp.astimezone(ET).date(),
                    known_at=timestamp,
                    accepted_at=timestamp,
                    accession=accession,
                    source="SEC_8K_ITEM_202",
                )
            )
        except Exception:
            raise DataIntegrityError(
                "EG-02: filing proxy date/identity cannot be verified"
            ) from None
    if len({row.accession for row in rows}) != len(rows):
        raise DataIntegrityError("EG-02: duplicate filing accession")
    return tuple(sorted(rows, key=lambda row: (row.known_at, row.accession or "")))
