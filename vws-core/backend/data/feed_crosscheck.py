"""DQ-02: delayed same-vendor close/volume warnings and persisted streaks."""

from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Self

from pydantic import Field, model_validator
from sqlalchemy import select

from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.data_layer import Bar
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, MarketStatus, Money, SessionDate, Symbol

NOTICE = (
    "SIP and IEX are from the same vendor, not independent; IEX represents partial market volume."
)


class FeedCheck(FrozenModel):
    symbol: Symbol
    session: SessionDate
    sip: Bar
    iex: Bar
    atr14: Money = Field(ge=0)
    flagged: bool = Field(strict=True)
    consecutive: int = Field(strict=True, ge=0, le=20000)
    status: MarketStatus
    notice: str = NOTICE

    @model_validator(mode="after")
    def bound(self) -> Self:
        if (
            self.sip.session_date != self.session
            or self.iex.session_date != self.session
            or self.notice != NOTICE
            or self.flagged != flagged(self.sip, self.iex, self.atr14)
        ):
            raise ValueError("DQ-02: feeds must describe the same completed session")
        if (self.status == MarketStatus.SUSPECT) != (self.consecutive >= 3) or (
            (not self.flagged and self.consecutive != 0)
            or (self.flagged and self.consecutive == 0)
            or self.status not in {MarketStatus.OK, MarketStatus.SUSPECT}
        ):
            raise ValueError("DQ-02: three consecutive warnings make data suspect")
        return self


def flagged(sip: Bar, iex: Bar, atr14: Decimal) -> bool:
    first, second = Bar.model_validate(sip), Bar.model_validate(iex)
    if (
        first.session_date != second.session_date
        or not isinstance(atr14, Decimal)
        or not atr14.is_finite()
        or atr14 < 0
        or first.volume <= 0
        or second.volume <= 0
    ):
        raise DataIntegrityError("DQ-02: exact same-session bar evidence is unavailable")
    with localcontext() as context:
        context.prec = 256
        threshold = max(Decimal("0.01"), Decimal("0.3") * atr14 / first.close)
        return abs(first.close / second.close - 1) > threshold or second.volume > first.volume


def record(
    ledger: Ledger, calendar: MarketCalendar, symbol: str, sip: Bar, iex: Bar, atr14: Decimal
) -> FeedCheck:
    warning = flagged(sip, iex, atr14)
    day = sip.session_date
    if not calendar.is_session(day) or calendar.session_close(day) > ledger.clock.now():
        raise DataIntegrityError("DQ-02: feed cross-check requires a completed XNYS session")
    ledger.verify_chain()
    with transaction(ledger.engine) as session:
        ledger._verify_in_session(session)
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "FEED_CROSSCHECK")
                .order_by(SecurityEvent.seq.desc())
                .limit(10001)
            )
        )
        if len(rows) > 10000 or any(row.created_at > ledger.clock.now() for row in rows):
            raise DataIntegrityError("DQ-02: feed-check history is unavailable")
        previous = []
        for row in rows:
            payload = dict(row.detail)
            payload["session"] = date.fromisoformat(payload["session"])
            for feed in ("sip", "iex"):
                payload[feed] = {
                    **payload[feed],
                    "timestamp": datetime.fromisoformat(payload[feed]["timestamp"]),
                }
                for name in ("open", "high", "low", "close"):
                    payload[feed][name] = Decimal(payload[feed][name])
            checked = FeedCheck.model_validate(payload)
            if checked.symbol == symbol:
                previous.append(checked)
        latest = previous[0] if previous else None
        if latest is not None and latest.session >= day:
            if latest.session == day and (latest.sip, latest.iex, latest.atr14) == (
                sip,
                iex,
                atr14,
            ):
                return latest
            raise DataIntegrityError(
                "DQ-02: a completed feed check cannot be replaced or backdated"
            )
        streak = 0
        if warning:
            streak = 1 + (
                latest.consecutive
                if latest is not None and calendar.add_sessions(latest.session, 1) == day
                else 0
            )
        check = FeedCheck(
            symbol=symbol,
            session=day,
            sip=sip,
            iex=iex,
            atr14=atr14,
            flagged=warning,
            consecutive=streak,
            status=MarketStatus.SUSPECT if streak >= 3 else MarketStatus.OK,
        )
        ledger.append_in_session(
            session, SecurityEvent, kind="FEED_CROSSCHECK", detail=check.model_dump(mode="json")
        )
        return check
