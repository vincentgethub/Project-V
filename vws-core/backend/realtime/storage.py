"""AC-02/RT-14: append-only event outbox and full-session health evidence."""

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import RealtimeConfig
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import Digest
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, Symbol, UTCDateTime
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import REQUIRED, Feed, FeedHealth, HealthStatus, RealtimeEvent
from backend.realtime.policy import health_at

MAX_ROWS = 500000


class HealthSample(FrozenModel):
    scope: ControlScope
    policy_sha256: Digest
    at: UTCDateTime
    symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=1000)
    feeds: tuple[FeedHealth, ...] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def full(self) -> Self:
        if (
            tuple(row.feed for row in self.feeds) != REQUIRED
            or self.symbols != tuple(sorted(set(self.symbols)))
            or any(row.observed_at > self.at for row in self.feeds)
        ):
            raise ValueError("RT-14: complete, causal required-feed sample required")
        return self

    @classmethod
    def recorded(cls, payload: dict[str, Any]) -> "HealthSample":
        try:
            values = dict(payload)
            values["at"] = datetime.fromisoformat(values["at"])
            values["feeds"] = tuple(FeedHealth.recorded(row) for row in values["feeds"])
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("RT-14: stored session health is malformed") from None


class RealtimeStore:
    def __init__(self, ledger: Ledger, scope: ControlScope, policy_hash: str) -> None:
        self.ledger, self.scope = ledger, ControlScope.model_validate(scope)
        if (
            not isinstance(policy_hash, str)
            or len(policy_hash) != 64
            or any(c not in "0123456789abcdef" for c in policy_hash)
        ):
            raise DataIntegrityError("RT: complete policy hash required")
        self.policy_hash = policy_hash

    def _rows(
        self, session: Session, kinds: tuple[str, ...], *, since: datetime | None = None
    ) -> tuple[SecurityEvent, ...]:
        query = select(SecurityEvent).where(
            SecurityEvent.kind.in_(kinds),
            SecurityEvent.detail["scope"]["account_id"].as_string() == self.scope.account_id,
            SecurityEvent.detail["scope"]["environment"].as_string() == self.scope.environment,
            SecurityEvent.detail["policy_sha256"].as_string() == self.policy_hash,
        )
        if since is not None:
            query = query.where(SecurityEvent.ts >= since)
        rows = tuple(session.scalars(query.order_by(SecurityEvent.seq).limit(MAX_ROWS + 1)))
        if len(rows) > MAX_ROWS or any(row.ts > self.ledger.clock.now() for row in rows):
            raise DataIntegrityError("RT: bounded causal evidence inventory required")
        for row in rows:
            if ControlScope.model_validate(row.detail["scope"]) != self.scope:
                raise DataIntegrityError("RT: evidence scope differs")
        return rows

    def _detail(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "scope": self.scope.model_dump(mode="json"),
            "policy_sha256": self.policy_hash,
            **values,
        }

    def mark(self, health: FeedHealth) -> None:
        row = FeedHealth.model_validate(health)
        if row.observed_at > self.ledger.clock.now():
            raise DataIntegrityError("RT: future health cannot be recorded")
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            prior = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "REALTIME_HEALTH",
                    SecurityEvent.detail["scope"]["account_id"].as_string()
                    == self.scope.account_id,
                    SecurityEvent.detail["scope"]["environment"].as_string()
                    == self.scope.environment,
                    SecurityEvent.detail["policy_sha256"].as_string() == self.policy_hash,
                    SecurityEvent.detail["health"]["feed"].as_string() == row.feed,
                )
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
            if prior is not None:
                previous = FeedHealth.recorded(prior.detail["health"])
                # A cached observation cannot heal a newer outage or create a
                # new heartbeat. Actual successful polls carry a new time.
                if row.observed_at < previous.observed_at or row == previous:
                    return
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="REALTIME_HEALTH",
                detail=self._detail({"health": row.model_dump(mode="json")}),
            )

    def health(self) -> tuple[FeedHealth, ...]:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            rows = self._rows(
                session, ("REALTIME_HEALTH",), since=self.ledger.clock.now() - timedelta(days=91)
            )
        latest: dict[Feed, FeedHealth] = {}
        for row in rows:
            value = FeedHealth.recorded(row.detail["health"])
            if value.observed_at > row.ts:
                raise DataIntegrityError("RT: health time exceeds its receipt")
            previous = latest.get(value.feed)
            if previous is not None and value.observed_at < previous.observed_at:
                raise DataIntegrityError("RT: health clock moved backward")
            latest[value.feed] = value
        return tuple(latest[name] for name in sorted(latest))

    @staticmethod
    def key(event: RealtimeEvent) -> str:
        row = RealtimeEvent.model_validate(event)
        return hashlib.sha256(
            json.dumps(
                (row.feed, row.provider_id, row.kind, row.symbol),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()

    def receive(self, event: RealtimeEvent) -> bool:
        """Persist before a critical event may be queued or cause an action."""
        row = RealtimeEvent.model_validate(event)
        if row.observed_at > self.ledger.clock.now():
            raise DataIntegrityError("RT: future event cannot be recorded")
        key = self.key(row)
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            prior = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "REALTIME_EVENT",
                    SecurityEvent.detail["key"].as_string() == key,
                    SecurityEvent.detail["scope"]["account_id"].as_string()
                    == self.scope.account_id,
                    SecurityEvent.detail["scope"]["environment"].as_string()
                    == self.scope.environment,
                    SecurityEvent.detail["policy_sha256"].as_string() == self.policy_hash,
                )
                .limit(1)
            )
            if prior is not None:
                old = RealtimeEvent.recorded(prior.detail["event"])
                if old.model_dump(exclude={"observed_at"}) != row.model_dump(
                    exclude={"observed_at"}
                ):
                    raise DataIntegrityError("AC-02: repeated event changed public evidence")
                return False
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="REALTIME_EVENT",
                detail=self._detail({"key": key, "event": row.model_dump(mode="json")}),
            )
        return True

    def events(self, *, pending_only: bool = False) -> tuple[RealtimeEvent, ...]:
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            rows = self._rows(session, ("REALTIME_EVENT", "REALTIME_EVENT_DONE"))
        done = {row.detail["key"] for row in rows if row.kind == "REALTIME_EVENT_DONE"}
        values = []
        for row in rows:
            if row.kind != "REALTIME_EVENT":
                continue
            event = RealtimeEvent.recorded(row.detail["event"])
            if row.detail["key"] != self.key(event) or event.observed_at > row.ts:
                raise DataIntegrityError("AC-02: event identity or time differs")
            if not pending_only or row.detail["key"] not in done:
                values.append(event)
        return tuple(values)

    def complete(self, event: RealtimeEvent) -> None:
        event = RealtimeEvent.model_validate(event)
        key = self.key(event)
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            rows = self._rows(session, ("REALTIME_EVENT", "REALTIME_EVENT_DONE"))
            original = next(
                (row for row in rows if row.kind == "REALTIME_EVENT" and row.detail["key"] == key),
                None,
            )
            if original is None:
                raise DataIntegrityError("AC-02: completion lacks a durable event")
            if RealtimeEvent.recorded(original.detail["event"]).model_dump(
                exclude={"observed_at"}
            ) != event.model_dump(exclude={"observed_at"}):
                raise DataIntegrityError("AC-02: completion changed durable evidence")
            if not any(
                row.kind == "REALTIME_EVENT_DONE" and row.detail["key"] == key for row in rows
            ):
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="REALTIME_EVENT_DONE",
                    detail=self._detail({"key": key}),
                )

    def flag_once(self, event: RealtimeEvent, *, held: bool) -> bool:
        event = RealtimeEvent.model_validate(event)
        if type(held) is not bool:
            raise DataIntegrityError("RT-11: explicit ownership required")
        key = self.key(event)
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            rows = self._rows(session, ("REALTIME_EVENT", "REALTIME_FLAG"))
            original = next(
                (row for row in rows if row.kind == "REALTIME_EVENT" and row.detail["key"] == key),
                None,
            )
            if original is None or RealtimeEvent.recorded(original.detail["event"]).model_dump(
                exclude={"observed_at"}
            ) != event.model_dump(exclude={"observed_at"}):
                raise DataIntegrityError("AC-02: flag lacks matching durable evidence")
            if any(row.kind == "REALTIME_FLAG" and row.detail["key"] == key for row in rows):
                return False
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="REALTIME_FLAG",
                detail=self._detail(
                    {"key": key, "held": held, "symbol": event.symbol, "kind": event.kind}
                ),
            )
        return True

    def notice_delivered(self, event: RealtimeEvent) -> bool:
        key = self.key(event)
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            rows = self._rows(session, ("REALTIME_NOTICE_DELIVERED",))
        return any(row.detail["key"] == key for row in rows)

    def delivered_notice(self, event: RealtimeEvent) -> None:
        row = RealtimeEvent.model_validate(event)
        key = self.key(row)
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            received = self._rows(
                session, ("REALTIME_EVENT", "REALTIME_FLAG", "REALTIME_NOTICE_DELIVERED")
            )
            if not any(
                item.kind == "REALTIME_EVENT" and item.detail["key"] == key for item in received
            ) or not any(
                item.kind == "REALTIME_FLAG" and item.detail["key"] == key for item in received
            ):
                raise DataIntegrityError("AC-02: a notice needs its durable received flag")
            if any(
                item.kind == "REALTIME_NOTICE_DELIVERED" and item.detail["key"] == key
                for item in received
            ):
                return
            self.ledger.append_in_session(
                session,
                SecurityEvent,
                kind="REALTIME_NOTICE_DELIVERED",
                detail=self._detail({"key": key}),
            )

    def record_context(self, proposal_id: UUID, payload: dict[str, Any]) -> None:
        from backend.realtime.models import RealtimeContext

        row = RealtimeContext.model_validate(payload)
        if (
            not isinstance(proposal_id, UUID)
            or row.scope != self.scope
            or row.policy_sha256 != self.policy_hash
            or row.as_of > self.ledger.clock.now()
        ):
            raise DataIntegrityError("RT-12: proposal context binding differs")
        self.ledger.append(
            SecurityEvent,
            kind="REALTIME_CONTEXT",
            detail=self._detail(
                {"proposal_id": str(proposal_id), "context": row.model_dump(mode="json")}
            ),
        )

    def record_size_context(self, payload: dict[str, Any]) -> None:
        from backend.data.history import canonical_bytes
        from backend.realtime.models import RealtimeContext

        row = RealtimeContext.model_validate(payload)
        if (
            row.scope != self.scope
            or row.policy_sha256 != self.policy_hash
            or row.as_of > self.ledger.clock.now()
        ):
            raise DataIntegrityError("RT-12: sizing context binding differs")
        key = hashlib.sha256(canonical_bytes(row)).hexdigest()
        with transaction(self.ledger.engine) as session:
            self.ledger._verify_in_session(session)
            prior = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "REALTIME_SIZE_CONTEXT",
                    SecurityEvent.detail["key"].as_string() == key,
                )
                .limit(1)
            )
            if prior is None:
                self.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="REALTIME_SIZE_CONTEXT",
                    detail=self._detail({"key": key, "context": row.model_dump(mode="json")}),
                )

    def sample(self, symbols: tuple[str, ...]) -> None:
        now = self.ledger.clock.now()
        by_feed = {row.feed: row for row in self.health()}
        feeds = tuple(
            by_feed.get(
                name,
                FeedHealth(
                    feed=name,
                    status=HealthStatus.UNAVAILABLE,
                    observed_at=now,
                    detail="No verified heartbeat",
                ),
            )
            for name in REQUIRED
        )
        row = HealthSample(
            scope=self.scope, policy_sha256=self.policy_hash, at=now, symbols=symbols, feeds=feeds
        )
        self.ledger.append(
            SecurityEvent, kind="REALTIME_SAMPLE", detail=row.model_dump(mode="json")
        )

    def healthy_sessions(
        self, calendar: MarketCalendar, config: RealtimeConfig
    ) -> tuple[date, ...]:
        """A closing snapshot cannot invent an entire healthy trading session."""
        now = self.ledger.clock.now()
        self.ledger.verify_chain()
        with Session(self.ledger.engine) as session:
            rows = self._rows(session, ("REALTIME_SAMPLE",), since=now - timedelta(days=90))
        samples = tuple(HealthSample.recorded(row.detail) for row in rows)
        if any(sample.at > receipt.ts for sample, receipt in zip(samples, rows, strict=True)):
            raise DataIntegrityError("RT-14: sample exceeds its durable receipt")
        eligible = healthy_sessions(samples, now, calendar, config)
        with Session(self.ledger.engine) as session:
            changes = self._rows(session, ("REALTIME_HEALTH",), since=now - timedelta(days=90))
        failed = set()
        for receipt in changes:
            observed = FeedHealth.recorded(receipt.detail["health"])
            if observed.observed_at > receipt.ts:
                raise DataIntegrityError("RT-14: heartbeat exceeds its receipt")
            day = receipt.ts.astimezone(ZoneInfo("America/New_York")).date()
            if (
                day in eligible
                and calendar.session_open(day) <= receipt.ts <= calendar.session_close(day)
                and observed.feed in REQUIRED
                and observed.status != HealthStatus.OK
            ):
                failed.add(day)
        return tuple(day for day in eligible if day not in failed)


def healthy_sessions(
    values: tuple[HealthSample, ...],
    now: datetime,
    calendar: MarketCalendar,
    config: RealtimeConfig,
) -> tuple[date, ...]:
    """RT-14: pure coverage rule; production receipts are verified by the store."""
    now = ensure_utc(now)
    config = RealtimeConfig.model_validate(config)
    if not isinstance(values, tuple) or len(values) > MAX_ROWS:
        raise DataIntegrityError("RT-14: bounded immutable samples required")
    samples = tuple(HealthSample.model_validate(row) for row in values)
    if (
        any(row.at > now for row in samples)
        or any(b.at <= a.at for a, b in zip(samples, samples[1:], strict=False))
        or len({(row.scope, row.policy_sha256) for row in samples}) > 1
    ):
        raise DataIntegrityError("RT-14: causal ordered samples with one scope and policy required")
    days = tuple(
        sorted({sample.at.astimezone(ZoneInfo("America/New_York")).date() for sample in samples})
    )
    result = []
    for day in days:
        if not calendar.is_session(day) or calendar.session_close(day) > now:
            continue
        opened, closed = calendar.session_open(day), calendar.session_close(day)
        window = tuple(
            sample
            for sample in samples
            if opened - timedelta(seconds=30) <= sample.at <= closed + timedelta(seconds=30)
        )
        if not window or window[0].at > opened or window[-1].at < closed:
            continue
        if any(
            b.at <= a.at or b.at - a.at > timedelta(seconds=30)
            for a, b in zip(window, window[1:], strict=False)
        ):
            continue
        if any(
            any(
                health_at(feed, sample.at, config) != HealthStatus.OK
                or feed.feed == "assets"
                and not set(sample.symbols).issubset(feed.symbols)
                for feed in sample.feeds
            )
            for sample in window
        ):
            continue
        result.append(day)
    return tuple(result)
