"""RT-08/EVT: official schedule review and explicit quarterly host confirmation."""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.ledger import Ledger
from backend.data.history import Digest
from backend.domain.models import FrozenModel, UTCDateTime
from backend.net.egress import EgressPolicy
from backend.net.http import make_client
from backend.ops.macro_events import MacroCalendar
from backend.realtime.policy import NY

SOURCES = (
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "https://www.bls.gov/schedule/news_release/cpi.htm",
    "https://www.bls.gov/schedule/news_release/empsit.htm",
    "https://www.bea.gov/news/schedule",
)
CONFIRM = "CONFIRM MACRO SCHEDULES"


class ScheduleReview(FrozenModel):
    at: UTCDateTime
    quarter: str = Field(strict=True, pattern=r"^[0-9]{4}-Q[1-4]$")
    file_sha256: Digest
    source_sha256: tuple[tuple[str, Digest], ...] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if tuple(url for url, _ in self.source_sha256) != SOURCES or self.quarter != quarter(
            self.at
        ):
            raise ValueError(
                "RT-08: complete official-source review bound to the current quarter required"
            )
        return self


def quarter(now: datetime) -> str:
    local = now.astimezone(NY)
    return f"{local.year}-Q{(local.month - 1) // 3 + 1}"


class Schedules:
    def __init__(self, ledger: Ledger, macro: MacroCalendar, events_policy: Path) -> None:
        self.ledger, self.macro, self.events_policy = ledger, macro, events_policy

    def file_hash(self) -> str:
        self.macro.read()
        return hashlib.sha256(self.macro.path.read_bytes()).hexdigest()

    async def review(self, policy: EgressPolicy) -> ScheduleReview:
        """Fetch bounded official pages for manual review, never write the CSV."""
        if policy.ledger.engine is not self.ledger.engine:
            raise DataIntegrityError("RT-08: schedule reads must use the same ledger")
        hashes = []
        async with make_client(
            "official-schedules", policy=policy, allow_redirects=False, max_response_bytes=2097152
        ) as client:
            for url in SOURCES:
                response = await client.get(url)
                if response.status_code != 200:
                    raise ProviderError(
                        "RT-08: official schedule unavailable; review remains UNVERIFIED"
                    )
                hashes.append((url, hashlib.sha256(response.content).hexdigest()))
        return ScheduleReview(
            at=self.ledger.clock.now(),
            quarter=quarter(self.ledger.clock.now()),
            file_sha256=self.file_hash(),
            source_sha256=tuple(hashes),
        )

    def confirm(self, review: ScheduleReview, phrase: str) -> None:
        checked = ScheduleReview.model_validate(review)
        now = self.ledger.clock.now()
        if (
            phrase != CONFIRM
            or checked.file_sha256 != self.file_hash()
            or checked.quarter != quarter(now)
            or not timedelta(0) <= now - checked.at <= timedelta(minutes=15)
        ):
            raise ConfigurationError(
                "RT-08: fresh reviewed CSV and explicit host confirmation required"
            )
        events = tuple(
            row for row in self.macro.read() if quarter(row.release_at) == checked.quarter
        )
        if not {"FOMC", "CPI", "NFP", "GDP", "PCE"}.issubset({row.event for row in events}):
            raise ConfigurationError(
                "RT-08: quarterly CSV must include all five scheduled event types"
            )
        self.ledger.append(
            SecurityEvent, kind="MACRO_SCHEDULES_CONFIRMED", detail=checked.model_dump(mode="json")
        )

    def confirmed(self) -> bool:
        if (
            not self.events_policy.is_file()
            or self.events_policy.is_symlink()
            or not self.macro.path.is_file()
        ):
            return False
        digest = self.file_hash()
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            rows = tuple(
                session.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind == "MACRO_SCHEDULES_CONFIRMED")
                    .order_by(SecurityEvent.seq.desc())
                    .limit(1001)
                )
            )
        if len(rows) > 1000:
            raise DataIntegrityError("RT-08: quarterly confirmation inventory exceeds bound")
        now = self.ledger.clock.now()
        for row in rows:
            try:
                values = dict(row.detail)
                values["at"] = datetime.fromisoformat(values["at"])
                proof = ScheduleReview.model_validate(values)
                if proof.at > row.ts or row.ts > now:
                    raise ValueError("future schedule confirmation")
            except Exception:
                raise DataIntegrityError("RT-08: malformed schedule confirmation") from None
            if (
                proof.file_sha256 == digest
                and proof.quarter == quarter(now)
                and now - proof.at <= timedelta(days=90)
            ):
                return True
        return False
