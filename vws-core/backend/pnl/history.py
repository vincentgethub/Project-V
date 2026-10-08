"""PL-01: documented portfolio-history GET, with exact JSON money at ingress."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError, ProviderError
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel, Money, SessionDate, UTCDateTime
from backend.funding.activities import AlpacaActivitiesSource
from backend.pnl.models import MAX_PNL_SESSIONS
from backend.tax.models import Environment


class EquityClose(FrozenModel):
    session: SessionDate
    equity: Money = Field(ge=0)


class EquityHistory(FrozenModel):
    account_id: str = Field(min_length=1, max_length=128)
    env: Environment
    as_of: UTCDateTime
    closes: tuple[EquityClose, ...] = Field(max_length=MAX_PNL_SESSIONS)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def ordered(self) -> EquityHistory:
        dates = tuple(row.session for row in self.closes)
        if dates != tuple(sorted(set(dates))) or any(day > self.as_of.date() for day in dates):
            raise ValueError("PL-01: history sessions must be unique, ordered and observed")
        return self


async def read_history(
    source: AlpacaActivitiesSource, start: date, end: date, calendar: MarketCalendar
) -> EquityHistory:
    """The SDK model converts equity to float; use the same guarded HTTP client.

    VERIFY: https://docs.alpaca.markets/us/reference/getaccountportfoliohistory-1
    1D returns exchange sessions and equity, not historic cash or position value.
    Broker percentages are not reused: PL-02 computes its own external-flow math.
    """
    try:
        if type(start) is not date or type(end) is not date or start > end:
            raise ValueError("PL-01: explicit daily range required")
        now = ensure_utc(source.clock.now())
        if calendar.session_close(end) > now:
            raise ValueError("PL-01: history includes an unfinished session")
        base = source.settings.broker_endpoint
        account = await source.client.get(base + "/v2/account", headers=source._headers)
        if account.status_code != 200 or account.json().get("id") != source.account_id:
            raise ValueError("PL-04: portfolio history account differs")
        response = await source.client.get(
            base + "/v2/account/portfolio/history",
            headers=source._headers,
            params={
                "start": datetime.combine(start, datetime.min.time(), UTC).isoformat(),
                "end": calendar.session_close(end).isoformat(),
                "timeframe": "1D",
                "cashflow_types": "NONE",
                "extended_hours": "false",
            },
        )
        if response.status_code != 200:
            raise ProviderError("PL-01: portfolio history unavailable")
        raw = json.loads(response.content, parse_float=Decimal)
        if not isinstance(raw, dict) or raw.get("timeframe") != "1D":
            raise ValueError("PL-01: daily portfolio history required")
        timestamps, equities = raw["timestamp"], raw["equity"]
        if (
            not isinstance(timestamps, list)
            or not isinstance(equities, list)
            or len(timestamps) != len(equities)
            or len(timestamps) > MAX_PNL_SESSIONS
        ):
            raise ValueError("PL-01: bounded aligned equity history required")
        closes: list[EquityClose] = []
        for stamp, equity in zip(timestamps, equities, strict=True):
            if type(stamp) is not int:
                raise ValueError("PL-01: integer UNIX timestamp required")
            instant = datetime.fromtimestamp(stamp, UTC)
            day = instant.date()
            if not start <= day <= end or not calendar.is_session(day):
                raise ValueError("PL-01: broker point is outside the session range")
            if instant > now or closes and closes[-1].session >= day:
                raise ValueError("PL-01: unordered, duplicate or future broker history")
            closes.append(EquityClose(session=day, equity=equity))
        return EquityHistory(
            account_id=source.account_id,
            env="PAPER" if source.settings.paper_trading else "LIVE",
            as_of=now,
            closes=tuple(closes),
            sha256=hashlib.sha256(response.content).hexdigest(),
        )
    except Exception:
        raise DataIntegrityError("PL-01: portfolio history is UNVERIFIED") from None
