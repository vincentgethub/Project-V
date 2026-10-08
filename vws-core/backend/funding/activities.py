"""FN-02/TX-02: guarded read-only retail activities; pinned SDK lacks this method."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.ledger import _json_value
from backend.data.fill_polling import AlpacaFillSource
from backend.domain.models import FrozenModel, Side, UTCDateTime
from backend.evaluation.costs import FeeSchedule, fees
from backend.funding.models import Activity
from backend.tax.lots import trade_day
from backend.tax.models import Environment, TaxFill

ACTIVITY_IDENTITY = UUID("4b9a8ffc-7b79-4078-9db0-207b1152a143")
MAX_ACTIVITY_PAGES = 1000


class ActivityBatch(FrozenModel):
    account_id: str = Field(min_length=1, max_length=128)
    env: Environment
    as_of: UTCDateTime
    complete_history: bool = Field(strict=True)
    activities: tuple[Activity, ...] = Field(max_length=100000)

    @model_validator(mode="after")
    def bound(self) -> ActivityBatch:
        if len({row.activity_id for row in self.activities}) != len(self.activities) or any(
            (row.account_id, row.env, row.observed_at) != (self.account_id, self.env, self.as_of)
            for row in self.activities
        ):
            raise ValueError("FN-02: activity batch duplicates or bindings differ")
        return self


def parse_activity(
    raw: object, account_id: str, env: Environment, observed_at: datetime, schedule: FeeSchedule
) -> Activity:
    try:
        if (
            not isinstance(raw, dict)
            or len(raw) > 100
            or any(not isinstance(key, str) for key in raw)
        ):
            raise ValueError("FN-02: bounded broker object required")
        # Decimal JSON parser at transport ingress rejects float money. The source
        # hash retains original numeric string fields without account credentials.
        digest = hashlib.sha256(
            json.dumps(
                _json_value(raw),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        ).hexdigest()
        kind, identity = raw["activity_type"], raw["id"]
        if not isinstance(kind, str) or not isinstance(identity, str):
            raise ValueError("FN-02: activity identity/type required")
        fill = None
        broker_order_id = None
        occurred = None
        symbol = raw.get("symbol") or None
        if kind == "FILL":
            if not isinstance(symbol, str):
                raise ValueError("TX-02: explicit fill symbol required")
            if not all(
                isinstance(raw.get(key), str)
                for key in ("qty", "price", "transaction_time", "side", "order_id")
            ):
                raise ValueError("TX-02: exact documented fill fields required")
            quantity = Decimal(raw["qty"])
            if (
                not quantity.is_finite()
                or quantity != quantity.to_integral_value()
                or not 0 < quantity <= 10**9
            ):
                raise ValueError("TX-02: whole-share long-only fills required")
            occurred = ensure_utc(datetime.fromisoformat(raw["transaction_time"]))
            price, side = Decimal(raw["price"]), Side(raw["side"].upper())
            modeled = fees(side, int(quantity), price, trade_day(occurred), schedule=schedule)
            fill = TaxFill(
                fill_id=uuid5(ACTIVITY_IDENTITY, f"{account_id}/{env}/{identity}"),
                activity_id=identity,
                account_id=account_id,
                env=env,
                symbol=symbol,
                side=side,
                qty=int(quantity),
                price=price,
                fees=modeled.total,
                ts=occurred,
                fee_source="MODELED",
                payload_sha256=digest,
            )
            broker_order_id = UUID(raw["order_id"])
            effective = occurred.date()
            amount = Decimal(0)  # FILL is separately stored in tax_events, never as a cash flow.
        else:
            if not isinstance(raw.get("net_amount"), str) or not isinstance(raw.get("date"), str):
                raise ValueError("FN-02: exact net_amount/date required")
            amount = Decimal(raw["net_amount"])
            stamp = raw["date"]
            if len(stamp) == 10:
                effective = date.fromisoformat(stamp)
            else:
                occurred = ensure_utc(datetime.fromisoformat(stamp))
                effective = occurred.date()
        return Activity(
            account_id=account_id,
            env=env,
            activity_id=identity,
            type=kind,
            amount=amount,
            date=effective,
            observed_at=observed_at,
            occurred_at=occurred,
            source="BROKER",
            symbol=symbol,
            fill=fill,
            broker_order_id=broker_order_id,
            payload_sha256=digest,
        )
    except Exception:
        raise DataIntegrityError("FN-02/TX-02: broker activity is unverifiable") from None


class AlpacaActivitiesSource(AlpacaFillSource):
    """Same account/endpoint/budget/backstop as H; only GET calls exist here.

    VERIFY: https://docs.alpaca.markets/us/docs/account-activities
    TradingClient 0.44.0 has no retail get_account_activities; broker requests
    are for a different API and cannot be substituted. Date-less startup capture
    pages the full available account history, never an arbitrary 61-day window.
    """

    async def read_activities(
        self, after: datetime | None, until: datetime, schedule: FeeSchedule
    ) -> ActivityBatch:
        try:
            end = ensure_utc(until)
            start = None if after is None else ensure_utc(after)
            if (
                start is not None
                and start >= end
                or end > ensure_utc(self.clock.now())
                or self.reader.tripped
            ):
                raise DataIntegrityError("FN-02: invalid activity range/circuit")
            env: Environment = "PAPER" if self.settings.paper_trading else "LIVE"
            async with asyncio.timeout(60):
                base = self.settings.broker_endpoint
                account = await self.client.get(base + "/v2/account", headers=self._headers)
                if account.status_code != 200 or account.json().get("id") != self.account_id:
                    raise DataIntegrityError("FN-02: account activity binding differs")
                rows: list[Activity] = []
                identities: set[str] = set()
                token = None
                for _page in range(MAX_ACTIVITY_PAGES):
                    params = {"direction": "asc", "page_size": "100", "until": end.isoformat()}
                    if start is not None:
                        params["after"] = start.isoformat()
                    if token is not None:
                        params["page_token"] = token
                    response = await self.client.get(
                        base + "/v2/account/activities", headers=self._headers, params=params
                    )
                    if response.status_code == 429:
                        await self.reader.bucket.drain(response.headers.get("Retry-After"))
                        raise ProviderError("FN-02: activity source rate limited")
                    if response.status_code != 200:
                        raise ProviderError("FN-02: account activity source unavailable")
                    page = json.loads(response.content, parse_float=Decimal)
                    if not isinstance(page, list) or len(page) > 100:
                        raise DataIntegrityError("FN-02: bounded activity page required")
                    for raw in page:
                        row = parse_activity(raw, self.account_id, env, end, schedule)
                        if (
                            row.activity_id in identities
                            or row.date > end.date()
                            or start is not None
                            and (
                                row.occurred_at is not None
                                and row.occurred_at < start
                                or row.occurred_at is None
                                and row.date < start.date()
                            )
                        ):
                            raise DataIntegrityError("FN-02: overlapping/out-of-range pagination")
                        identities.add(row.activity_id)
                        rows.append(row)
                    if len(page) < 100:
                        return ActivityBatch(
                            account_id=self.account_id,
                            env=env,
                            as_of=end,
                            complete_history=start is None,
                            activities=tuple(
                                sorted(
                                    rows,
                                    key=lambda row: (
                                        row.date,
                                        row.occurred_at or end,
                                        row.activity_id,
                                    ),
                                )
                            ),
                        )
                    token = rows[-1].activity_id
                raise DataIntegrityError("FN-02: account history exceeded bounded pagination")
        except asyncio.CancelledError:
            await self.reader.halt(ProviderError("FN-02: activity polling cancelled"))
            raise
        except Exception as exc:
            await self.reader.halt(exc)
            raise DataIntegrityError("FN-02: activities unverified; entries halted") from None
