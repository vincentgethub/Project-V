"""SEC-13/42/72: finite, secret-free weekly evidence from verified ledger rows."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import select

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import FrozenModel, UTCDateTime
from backend.ops.anchors import LedgerAnchor, LedgerAnchors


class EventCount(FrozenModel):
    kind: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    count: int = Field(strict=True, ge=1, le=100000)


class CredentialAge(FrozenModel):
    name: str = Field(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    last_rotated: UTCDateTime | None
    age_days: int | None = Field(default=None, strict=True, ge=0)
    status: Literal["PASS", "WARN", "UNKNOWN"]

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (self.last_rotated is None) != (self.age_days is None) or (self.status == "UNKNOWN") != (
            self.last_rotated is None
        ):
            raise ValueError("SEC-13: unknown rotation cannot claim a known age")
        return self


class CheckEvidence(FrozenModel):
    check: Literal["anchor_verify", "drill", "pip_audit", "restore_test"]
    at: UTCDateTime | None
    status: Literal["PASS", "FAIL", "UNVERIFIED"]

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (self.at is None) != (self.status == "UNVERIFIED"):
            raise ValueError("SEC-72: unverified check cannot claim a recorded result")
        return self


class WeeklySecurity(FrozenModel):
    start: UTCDateTime
    as_of: UTCDateTime
    events: tuple[EventCount, ...] = Field(max_length=1000)
    new_ids: tuple[int, ...] = Field(max_length=10000)
    credentials: tuple[CredentialAge, ...] = Field(max_length=100)
    latest_anchor: LedgerAnchor | None
    checks: tuple[CheckEvidence, ...] = Field(min_length=4, max_length=4)
    max_secret_age_days: int = Field(strict=True, ge=30, le=365)

    @model_validator(mode="after")
    def bound(self) -> Self:
        kinds = tuple(item.kind for item in self.events)
        names = tuple(item.name for item in self.credentials)
        if (
            self.start > self.as_of
            or kinds != tuple(sorted(set(kinds)))
            or names != tuple(sorted(set(names)))
            or self.new_ids != tuple(sorted(set(self.new_ids)))
            or any(type(item) is not int or not 0 < item <= 2**63 - 1 for item in self.new_ids)
            or tuple(item.check for item in self.checks)
            != ("anchor_verify", "drill", "pip_audit", "restore_test")
        ):
            raise ValueError("SEC-72: finite ordered weekly evidence required")
        stamps = (
            *(item.at for item in self.checks),
            None if self.latest_anchor is None else self.latest_anchor.created_at,
            *(item.last_rotated for item in self.credentials),
        )
        if any(stamp is not None and stamp > self.as_of for stamp in stamps) or any(
            item.last_rotated is not None
            and (
                item.age_days != (self.as_of - item.last_rotated).days
                or item.status
                != (
                    "WARN"
                    if (self.as_of - item.last_rotated).days >= self.max_secret_age_days
                    else "PASS"
                )
            )
            for item in self.credentials
        ):
            raise ValueError("SEC-72: evidence timestamps or credential ages differ")
        return self


def weekly_security(ledger: Ledger, settings: Settings, start: datetime) -> WeeklySecurity:
    try:
        limits = Settings.validated_copy(settings)
        since, now = ensure_utc(start), ensure_utc(ledger.clock.now())
        ledger.verify_chain()
        with transaction(ledger.engine) as session:
            ledger._verify_in_session(session)
            rows = tuple(
                session.scalars(select(SecurityEvent).order_by(SecurityEvent.seq).limit(100001))
            )
            if len(rows) > 100000 or any(row.ts > now for row in rows):
                raise ValueError("security evidence exceeds its size/time bound")
            counts: dict[str, int] = {}
            seen: set[int] = set()
            new: set[int] = set()
            for row in rows:
                if row.ts >= since:
                    counts[row.kind] = counts.get(row.kind, 0) + 1
                if row.kind in {"TELEGRAM_STRANGER", "TELEGRAM_NONPRIVATE"}:
                    user_id = row.detail.get("user_id")
                    if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
                        raise ValueError("security user identifier is unverifiable")
                    if user_id not in seen and row.ts >= since:
                        new.add(user_id)
                    seen.add(user_id)
            names: tuple[str, ...] = (
                ("ALPACA_PAPER_KEY_ID", "ALPACA_PAPER_SECRET")
                if limits.paper_trading
                else ("ALPACA_LIVE_KEY_ID", "ALPACA_LIVE_SECRET")
            )
            names = (
                *names,
                "BROKER_API_KEY",
                "BROKER_SECRET_KEY",
                "TELEGRAM_BOT_TOKEN",
                "PLAID_SECRET",
                "PLAID_ACCESS_TOKEN",
                "TELEGRAM_CALLBACK_SECRET",
                "VWS_BACKUP_KEY",
            )
            ages: list[CredentialAge] = []
            for name in sorted(names):
                latest = next(
                    (
                        row.ts
                        for row in reversed(rows)
                        if row.kind == "SECRET_ROTATED" and row.detail.get("name") == name
                    ),
                    None,
                )
                days = None if latest is None else (now - latest).days
                ages.append(
                    CredentialAge(
                        name=name,
                        last_rotated=latest,
                        age_days=days,
                        status="UNKNOWN"
                        if days is None
                        else "WARN"
                        if days >= limits.secret_max_age_days
                        else "PASS",
                    )
                )

            checks: list[CheckEvidence] = []
            for name, passed, failed in (
                ("anchor_verify", "ANCHOR_VERIFIED", "ANCHOR_VERIFY_FAILED"),
                ("drill", "DRILL_PASSED", "DRILL_FAILED"),
                ("pip_audit", "PIP_AUDIT_PASSED", "PIP_AUDIT_FAILED"),
                ("restore_test", "RESTORE_TEST_PASSED", "RESTORE_TEST_FAILED"),
            ):
                result_row = next(
                    (row for row in reversed(rows) if row.kind in {passed, failed}), None
                )
                checks.append(
                    CheckEvidence.model_validate(
                        {
                            "check": name,
                            "at": None if result_row is None else result_row.ts,
                            "status": "UNVERIFIED"
                            if result_row is None
                            else "PASS"
                            if result_row.kind == passed
                            else "FAIL",
                        }
                    )
                )

            anchor_row = next((row for row in reversed(rows) if row.kind == "LEDGER_ANCHOR"), None)
            anchor = (
                None
                if anchor_row is None
                else LedgerAnchor(
                    seq=anchor_row.detail["seq"],
                    digest=anchor_row.detail["digest"],
                    created_at=anchor_row.ts,
                )
            )
            result = WeeklySecurity(
                start=since,
                as_of=now,
                events=tuple(
                    EventCount(kind=kind, count=count) for kind, count in sorted(counts.items())
                ),
                new_ids=tuple(sorted(new)),
                credentials=tuple(ages),
                latest_anchor=anchor,
                checks=tuple(checks),
                max_secret_age_days=limits.secret_max_age_days,
            )
        if (
            anchor is not None
            and LedgerAnchors(ledger, ledger.clock).create(anchor.seq).digest != anchor.digest
        ):
            raise ValueError("stored anchor differs from its verified ledger prefix")
        return result
    except DataIntegrityError:
        raise
    except Exception:
        raise DataIntegrityError("SEC-72: weekly security evidence is unverifiable") from None


def render_security(summary: WeeklySecurity | None, *, masked: bool) -> tuple[str, ...]:
    if summary is None:
        return ("Security evidence unavailable for this report; no checks claimed.",)
    bound = WeeklySecurity.model_validate(summary)
    anchor = bound.latest_anchor
    return (
        "Security events: "
        + (", ".join(f"{row.kind}={row.count}" for row in bound.events) or "none in this period"),
        "New IDs: "
        + (
            "masked"
            if masked and bound.new_ids
            else ", ".join(str(item) for item in bound.new_ids) or "none in this period"
        ),
        "Latest ledger anchor: "
        + ("unavailable" if anchor is None else f"seq {anchor.seq} · {anchor.digest[:16]}"),
        *(
            f"Credential age {item.name}: {item.status}"
            + (" (unknown)" if item.age_days is None else f" ({item.age_days} days)")
            for item in bound.credentials
        ),
        *(
            f"Last {item.check.replace('_', ' ')}: {item.status}"
            + (
                ""
                if item.at is None
                else " · "
                + item.at.astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M %Z")
            )
            for item in bound.checks
        ),
    )
