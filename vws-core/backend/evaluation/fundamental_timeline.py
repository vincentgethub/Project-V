"""EV-03: bounded filing/age change points, using the existing FA computation."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from backend.agents.fundamentals import TAGS, FundamentalReport, compute_fundamentals
from backend.core.config import FundamentalsConfig
from backend.core.errors import DataIntegrityError
from backend.data.market_calendar import MarketCalendar
from backend.data.sec_edgar import SecPayload
from backend.domain.models import FrozenModel, Instrument, SessionDate


class FundamentalPoint(FrozenModel):
    session: SessionDate
    report: FundamentalReport


class FundamentalTimeline(FrozenModel):
    first: SessionDate
    last: SessionDate
    points: tuple[FundamentalPoint, ...] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            self.first > self.last
            or self.points[0].session != self.first
            or any(
                a.session >= b.session for a, b in zip(self.points, self.points[1:], strict=False)
            )
            or self.points[-1].session > self.last
        ):
            raise ValueError("EV-03: filing timeline is unordered")
        if len(
            {
                (point.report.symbol, point.report.cik, point.report.data_sha256)
                for point in self.points
            }
        ) != 1 or any(
            point.report.as_of.astimezone(ZoneInfo("America/New_York")).date() != point.session
            for point in self.points
        ):
            raise ValueError("EV-03: filing timeline cannot mix issuer evidence or future reports")
        return self

    def at(self, session: date) -> FundamentalReport:
        if type(session) is not date or not self.first <= session <= self.last:
            raise DataIntegrityError("EV-03: filing lookup is outside the frozen replay scope")
        index = bisect_right(tuple(point.session for point in self.points), session) - 1
        return FundamentalReport.model_validate(self.points[index].report)


def precompute_fundamentals(
    instrument: Instrument,
    payload: SecPayload | None,
    config: FundamentalsConfig,
    sessions: tuple[date, ...],
    calendar: MarketCalendar,
) -> FundamentalTimeline:
    """Changed filings and period-age expiries recompute; the day loop just looks up.

    Later downloaded companyfacts may contain earlier filings. Their `filed`
    date alone controls visibility, matching FA-01. A future amendment cannot
    replace an earlier version until its own filed date. No network fallback.
    """
    try:
        issuer = Instrument.model_validate(instrument)
        policy = FundamentalsConfig.model_validate(config)
        evidence = SecPayload.model_validate(payload) if payload is not None else None
        if (
            not isinstance(sessions, tuple)
            or not 1 <= len(sessions) <= 20000
            or any(type(day) is not date for day in sessions)
            or sessions != tuple(sorted(set(sessions)))
        ):
            raise ValueError("bounded ordered session tuple required")
        if evidence is not None and evidence.kind != "COMPANYFACTS":
            raise ValueError("issuer companyfacts required")
        markers = {sessions[0]}
        if evidence is not None:
            taxonomy = evidence.parsed().get("facts", {}).get("us-gaap", {})
            if not isinstance(taxonomy, Mapping):
                raise ValueError("unverifiable financial taxonomy")
            for tag in {name for names in TAGS.values() for name in names}:
                concept = taxonomy.get(tag, {})
                if not isinstance(concept, Mapping) or not isinstance(
                    concept.get("units", {}), Mapping
                ):
                    raise ValueError("unverifiable financial units")
                rows = concept.get("units", {}).get("USD", [])
                if not isinstance(rows, list) or len(rows) > 30000:
                    raise ValueError("unbounded financial rows")
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise ValueError("unverifiable financial row")
                    if row.get("form") not in {"10-K", "10-Q", "10-K/A", "10-Q/A"}:
                        continue
                    filed = date.fromisoformat(row["filed"])
                    if filed > sessions[-1]:
                        continue
                    end = date.fromisoformat(row["end"])
                    if end > filed:
                        raise ValueError("financial period follows filing")
                    for day in (filed, end + timedelta(days=policy.max_filing_age_days + 1)):
                        if sessions[0] < day <= sessions[-1]:
                            markers.add(day)
        changes = tuple(sorted(markers))
        points: list[FundamentalPoint] = []
        cursor = 0
        for day in sessions:
            calendar.session_close(day)
            if cursor < len(changes) and day >= changes[cursor]:
                while cursor < len(changes) and changes[cursor] <= day:
                    cursor += 1
                report = compute_fundamentals(
                    issuer, evidence, calendar.session_close(day) + timedelta(minutes=30), policy
                )
                points.append(FundamentalPoint(session=day, report=report))
        return FundamentalTimeline(first=sessions[0], last=sessions[-1], points=tuple(points))
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError(
            "EV-03: point-in-time fundamental evidence is unverifiable"
        ) from None
