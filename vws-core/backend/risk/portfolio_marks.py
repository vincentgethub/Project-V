"""CRO-09/CRO-10: append-only financial marks outside the pure risk rules."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import PortfolioState, SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.money import decimal_money
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import PortfolioSnapshot


class PersistedPortfolioMarks:
    """CRO-09/CRO-10: carry verified baselines and session entry-block evidence.

    Bootstrap uses the broker/caller's attested full snapshot; it never invents
    an earlier account history. The read callback initializes at current equity
    only when no local history exists. Operators record external cash flows
    through Ledger.record_cash_flow before the next observation. Baselines roll
    on the first observation at or after the next actual XNYS open, retaining
    the last session across nights, weekends and holidays. Only immutable local
    observations prove a prior daily breach. No system-state reset occurs.
    """

    def __init__(
        self, ledger: Ledger, account_id: str, calendar: MarketCalendar, config: Settings
    ) -> None:
        try:
            if (
                not isinstance(ledger, Ledger)
                or not isinstance(calendar, MarketCalendar)
                or not isinstance(account_id, str)
                or not account_id.strip()
                or account_id != account_id.strip()
                or len(account_id) > 128
            ):
                raise ValueError("invalid managed account or marks dependencies")
            self.config = Settings.validated_copy(config)
            self.ledger = ledger
            self.account_id = account_id
            self.calendar = calendar
        except Exception:
            raise ConfigurationError(
                "CRO-09/CRO-10: financial marks policy is unverifiable"
            ) from None

    def _session(self, instant: datetime) -> date:
        day = instant.astimezone(ZoneInfo("America/New_York")).date()
        if self.calendar.is_session(day) and instant >= self.calendar.session_open(day):
            return day
        return self.calendar.last_completed_session(instant)

    def _now(self, observed: datetime) -> datetime:
        instant = ensure_utc(observed)
        current = ensure_utc(self.ledger.clock.now())
        if (
            instant > current
            or (current - instant).total_seconds() > self.config.stale_quote_seconds
        ):
            raise DataIntegrityError("CRO-10: financial observation is stale or future")
        return instant

    def _rows(self, session: Session, instant: datetime) -> tuple[PortfolioState, ...]:
        rows = tuple(
            session.scalars(
                select(PortfolioState)
                .where(PortfolioState.account_id == self.account_id)
                .order_by(PortfolioState.seq)
            )
        )
        if any(row.as_of > instant for row in rows):
            raise DataIntegrityError("CRO-09/CRO-10: financial observation moved backward")
        return rows

    def _marks(
        self, equity: Decimal, instant: datetime, previous: PortfolioState | None
    ) -> tuple[Decimal, Decimal]:
        if previous is None:
            return equity, equity
        daily = (
            equity
            if self._session(instant) > self._session(previous.as_of)
            else previous.day_start_equity
        )
        return max(previous.high_water_mark, equity), daily

    @staticmethod
    def _breached(equity: Decimal, baseline: Decimal, limit: Decimal) -> bool:
        with localcontext() as context:
            context.prec = 80
            return baseline <= 0 or equity <= 0 or baseline - equity >= limit * baseline

    def _witnessed(
        self,
        session: Session,
        rows: tuple[PortfolioState, ...],
        instant: datetime,
        active: date,
    ) -> bool:
        """CRO-10: validate historical threshold evidence before replaying it."""
        by_seq = {row.seq: row for row in rows}
        blocked = False
        events = session.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.kind == "DAILY_LOSS_BREACH")
            .order_by(SecurityEvent.seq)
        )
        for event in events:
            detail = event.detail
            if set(detail) != {"account_id", "session", "portfolio_seq", "limit", "config_hash"}:
                raise DataIntegrityError("CRO-10: malformed session-breach evidence")
            if detail["account_id"] != self.account_id:
                continue
            index = detail["portfolio_seq"]
            label = detail["session"]
            fingerprint = detail["config_hash"]
            limit = decimal_money(detail["limit"])
            source = by_seq.get(index) if type(index) is int else None
            if (
                source is None
                or source.seq >= event.seq
                or type(label) is not str
                or self._session(source.as_of).isoformat() != label
                or self._session(event.ts).isoformat() != label
                or event.ts < source.as_of
                or event.ts > instant
                or not isinstance(fingerprint, str)
                or len(fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in fingerprint)
                or limit < 0
                or limit > Settings.DECIMAL_BOUNDS["daily_loss_limit"][1]
                or not self._breached(source.equity, source.day_start_equity, limit)
            ):
                raise DataIntegrityError("CRO-10: session-breach provenance is unverifiable")
            if label == active.isoformat():
                blocked = True
        return blocked

    def __call__(self, equity: Decimal, now: datetime) -> tuple[Decimal, Decimal]:
        """CRO-09/CRO-10: broker-injected read callback; no rows are written."""
        try:
            if not isinstance(equity, Decimal):
                raise DataIntegrityError("CRO-09: observed equity must be exact Decimal")
            decimal_money(equity)
            instant = self._now(now)
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                rows = self._rows(session, instant)
                return self._marks(equity, instant, rows[-1] if rows else None)
        except Exception:
            raise DataIntegrityError(
                "CRO-09/CRO-10: persisted financial marks read failed"
            ) from None

    def observe(self, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
        """CRO-09/CRO-10: bind and append a full read with preserved baselines."""
        try:
            snapshot = PortfolioSnapshot.model_validate(snapshot)
            instant = self._now(snapshot.as_of)
            if (
                snapshot.account_id != self.account_id
                or snapshot.account_type != self.config.broker_account_type
            ):
                raise DataIntegrityError(
                    "CRO-09/CRO-10: financial snapshot account differs from policy"
                )
            self.ledger.verify_chain()
            with transaction(self.ledger.engine) as session:
                rows = self._rows(session, instant)
                if rows:
                    high, daily = self._marks(snapshot.equity, instant, rows[-1])
                else:
                    high, daily = (
                        max(snapshot.high_water_mark, snapshot.equity),
                        snapshot.day_start_equity,
                    )
                checked = PortfolioSnapshot.model_validate(
                    {
                        **snapshot.model_dump(),
                        "high_water_mark": high,
                        "day_start_equity": daily,
                    }
                )
                recorded = self.ledger.append_in_session(
                    session,
                    PortfolioState,
                    account_id=checked.account_id,
                    account_type=checked.account_type.value,
                    as_of=instant,
                    equity=checked.equity,
                    cash=checked.cash,
                    settled_cash=checked.settled_cash,
                    positions=checked.model_dump(mode="json")["positions"],
                    high_water_mark=high,
                    day_start_equity=daily,
                    cash_flow_amount=Decimal(0),
                    cash_flow_at=None,
                )
                active = self._session(instant)
                observed = (*rows, recorded)
                if not self._witnessed(session, observed, instant, active):
                    source = next(
                        (
                            row
                            for row in observed
                            if self._session(row.as_of) == active
                            and self._breached(
                                row.equity, row.day_start_equity, self.config.daily_loss_limit
                            )
                        ),
                        None,
                    )
                    if source is not None:
                        self.ledger.append_in_session(
                            session,
                            SecurityEvent,
                            kind="DAILY_LOSS_BREACH",
                            telegram_user_id=None,
                            detail={
                                "account_id": self.account_id,
                                "session": active.isoformat(),
                                "portfolio_seq": source.seq,
                                "limit": str(self.config.daily_loss_limit),
                                "config_hash": self.config.config_hash,
                            },
                            ts=instant,
                        )
                return checked
        except Exception:
            raise DataIntegrityError(
                "CRO-09/CRO-10: financial observation could not be recorded"
            ) from None

    def daily_loss_blocked(self, now: datetime) -> bool:
        """CRO-10: a witnessed breach lasts through recovery until next open."""
        try:
            instant = self._now(now)
            self.ledger.verify_chain()
            active = self._session(instant)
            with transaction(self.ledger.engine) as session:
                rows = self._rows(session, instant)
                return self._witnessed(session, rows, instant, active) or any(
                    self._session(row.as_of) == active
                    and self._breached(
                        row.equity, row.day_start_equity, self.config.daily_loss_limit
                    )
                    for row in rows
                )
        except Exception:
            raise DataIntegrityError(
                "CRO-10: session entry-block evidence could not be verified"
            ) from None
