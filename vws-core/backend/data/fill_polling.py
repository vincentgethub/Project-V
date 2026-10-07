"""UX/GD-06: read-only FILL activities and conservative manual ticket matching.

Unmatched trades are immutable MANUAL signals with the exact observed fill in
their payload. They are not proposed orders; no fictitious stop is created.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

import httpx
from pydantic import Field, model_validator
from sqlalchemy import select

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import (
    Alert,
    DataSnapshot,
    Fill,
    Order,
    OrderEvent,
    SecurityEvent,
    Signal,
    TicketEvent,
    TradeTicket,
    transaction,
)
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError
from backend.core.logging import register_secrets
from backend.core.system_state import SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import FrozenModel, PositiveQty, Price, Side, Symbol, UTCDateTime
from backend.net.egress import EgressPolicy
from backend.net.http import make_client


class ObservedFill(FrozenModel):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    broker_fill_id: str = Field(
        strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:._-]+$"
    )
    broker_order_id: UUID
    symbol: Symbol
    side: Side
    qty: PositiveQty
    price: Price
    filled_at: UTCDateTime


class FillBatch(FrozenModel):
    account_id: str = Field(strict=True, min_length=1, max_length=128)
    as_of: UTCDateTime
    fills: tuple[ObservedFill, ...] = Field(max_length=10000)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if len({row.broker_fill_id for row in self.fills}) != len(self.fills):
            raise ValueError("duplicate activity identity in one batch")
        if any(
            row.account_id != self.account_id or row.filled_at > self.as_of for row in self.fills
        ):
            raise ValueError("activity account/time does not match the batch")
        if (
            tuple(sorted(self.fills, key=lambda row: (row.filled_at, row.broker_fill_id)))
            != self.fills
        ):
            raise ValueError("activities must be in deterministic chronological order")
        return self


class AlpacaFillSource:
    """The pinned TradingClient has no activity reader; use its documented GET.

    VERIFY: https://docs.alpaca.markets/us/reference/getaccountactivities-2
    Account identity is checked on the same key/endpoint before pagination.
    Every physical request shares the bound Alpaca request budget. No writes.
    """

    def __init__(
        self,
        settings: Settings,
        account_id: str,
        state: SystemStateStore,
        clock: Clock,
        reader: AsyncAlpacaReader,
        policy: EgressPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        if (
            not account_id
            or len(account_id) > 128
            or state.clock is not clock
            or reader.state is not state
            or policy.ledger.engine is not state.engine
            or self.settings.broker_state_source != "ALPACA"
        ):
            raise ConfigurationError("UX: fill polling policies/account differ")
        self.account_id, self.state, self.clock, self.reader = account_id, state, clock, reader
        reader.bind_policy(self.settings, state.ledger)
        self._headers = {
            "APCA-API-KEY-ID": self.settings.broker_api_key.get_secret_value(),
            "APCA-API-SECRET-KEY": self.settings.broker_secret_key.get_secret_value(),
        }
        if not all(self._headers.values()):
            raise ConfigurationError("UX: read-only fill polling requires broker credentials")
        register_secrets(*self._headers.values())
        self.client = make_client(
            "alpaca_fills",
            policy=policy,
            transport=transport,
            request_hook=reader.bucket.acquire,
            allow_redirects=False,
            max_response_bytes=1_048_576,
        )

    async def read(self, after: datetime, until: datetime) -> FillBatch:
        try:
            start, end = ensure_utc(after), ensure_utc(until)
            if start >= end or end > ensure_utc(self.clock.now()) or self.reader.tripped:
                raise DataIntegrityError("UX: invalid fill polling range/circuit")
            async with asyncio.timeout(30):
                base = self.settings.broker_endpoint
                account = await self.client.get(base + "/v2/account", headers=self._headers)
                if account.status_code != 200 or account.json().get("id") != self.account_id:
                    raise DataIntegrityError("UX: broker fill account binding failed")
                rows: list[ObservedFill] = []
                token: str | None = None
                seen: set[str] = set()
                for _page in range(100):
                    params = {
                        "activity_types": "FILL",
                        "direction": "asc",
                        "page_size": "100",
                        "after": start.isoformat(),
                        "until": end.isoformat(),
                    }
                    if token is not None:
                        params["page_token"] = token
                    response = await self.client.get(
                        base + "/v2/account/activities", headers=self._headers, params=params
                    )
                    if response.status_code == 429:
                        await self.reader.bucket.drain(response.headers.get("Retry-After"))
                        raise ProviderError("UX: fill polling rate limited")
                    if response.status_code != 200:
                        raise ProviderError("UX: fill polling response unavailable")
                    page = response.json()
                    if not isinstance(page, list) or len(page) > 100:
                        raise DataIntegrityError("UX: malformed fill page")
                    for raw in page:
                        if not isinstance(raw, dict) or raw.get("activity_type") != "FILL":
                            raise DataIntegrityError("UX: activity must be an explicit FILL")
                        quantity = raw.get("qty")
                        if not isinstance(quantity, str) or len(quantity) > 32:
                            raise DataIntegrityError("UX: fill quantity must be whole shares")
                        shares = Decimal(quantity)
                        if (
                            not shares.is_finite()
                            or shares <= 0
                            or shares != shares.to_integral_value()
                        ):
                            raise DataIntegrityError(
                                "UX: fill quantity must be positive whole shares"
                            )
                        if not isinstance(raw.get("price"), str) or not isinstance(
                            raw.get("transaction_time"), str
                        ):
                            raise DataIntegrityError("UX: fill price/time must be explicit")
                        row = ObservedFill(
                            account_id=self.account_id,
                            broker_fill_id=raw["id"],
                            broker_order_id=UUID(raw["order_id"]),
                            symbol=raw["symbol"],
                            side=Side(raw["side"].upper()),
                            qty=int(shares),
                            price=Decimal(raw["price"]),
                            filled_at=datetime.fromisoformat(raw["transaction_time"]),
                        )
                        if not start <= row.filled_at <= end or row.broker_fill_id in seen:
                            raise DataIntegrityError(
                                "UX: overlapping or out-of-range fill pagination"
                            )
                        seen.add(row.broker_fill_id)
                        rows.append(row)
                    if len(page) < 100:
                        return FillBatch(
                            account_id=self.account_id,
                            as_of=end,
                            fills=tuple(
                                sorted(rows, key=lambda row: (row.filled_at, row.broker_fill_id))
                            ),
                        )
                    token = rows[-1].broker_fill_id
                raise DataIntegrityError("UX: fill pagination exceeded its bound")
        except asyncio.CancelledError:
            await self.reader.halt(ProviderError("UX: fill polling cancelled"))
            raise
        except Exception as exc:
            await self.reader.halt(exc)
            raise DataIntegrityError(
                "UX: broker fills could not be verified; entries halted"
            ) from None

    async def close(self) -> None:
        await self.client.aclose()


class FillMatch(FrozenModel):
    status: Literal["MATCHED", "MANUAL", "DUPLICATE"]
    broker_fill_id: str = Field(min_length=1, max_length=128)
    ticket_id: UUID | None = None


class TicketFillMatcher:
    """Each observation is single-use and never matched by guesswork."""

    def __init__(
        self,
        settings: Settings,
        account_id: str,
        state: SystemStateStore,
        registry: InstrumentRegistry,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.account_id, self.state, self.registry = account_id, state, registry
        if not account_id or self.settings.execution_mode != "MANUAL":
            raise ConfigurationError("UX: Stage F fill matching requires MANUAL and an account")

    def record(self, fill: ObservedFill) -> FillMatch:
        try:
            row = ObservedFill.model_validate(fill)
            if row.account_id != self.account_id or row.filled_at > ensure_utc(
                self.state.clock.now()
            ):
                raise DataIntegrityError("UX: observed fill account/time mismatch")
            self.registry.get(row.symbol)
            self.state.ledger.verify_chain()
            payload = row.model_dump(mode="json")
            with transaction(self.state.engine) as session:
                previous = session.scalar(
                    select(SecurityEvent).where(
                        SecurityEvent.kind == "BROKER_FILL_RECORDED",
                        SecurityEvent.detail["fill"]["broker_fill_id"].as_string()
                        == row.broker_fill_id,
                    )
                )
                if previous is not None:
                    if previous.detail["fill"] != payload:
                        raise DataIntegrityError("UX: repeated broker fill identity changed")
                    return FillMatch(status="DUPLICATE", broker_fill_id=row.broker_fill_id)
                if (
                    session.scalar(select(Fill).where(Fill.broker_fill_id == row.broker_fill_id))
                    is not None
                ):
                    raise DataIntegrityError("UX: fill exists without matcher provenance")
                pairs = tuple(
                    session.execute(
                        select(TradeTicket, Order)
                        .join(Alert, TradeTicket.alert_id == Alert.id)
                        .join(Order, Alert.proposal_id == Order.proposal_id)
                        .where(
                            Order.account_id == row.account_id,
                            TradeTicket.symbol == row.symbol,
                            TradeTicket.side == row.side.value,
                            TradeTicket.created_at <= row.filled_at,
                            TradeTicket.valid_until >= row.filled_at,
                        )
                    )
                )
                eligible: list[tuple[TradeTicket, Order]] = []
                binding = session.scalar(
                    select(OrderEvent)
                    .where(OrderEvent.broker_order_id == str(row.broker_order_id))
                    .order_by(OrderEvent.seq)
                    .limit(1)
                )
                for ticket, order in pairs:
                    if binding is not None and order.id != binding.order_id:
                        continue
                    followup = session.scalar(
                        select(TicketEvent).where(TicketEvent.ticket_id == ticket.id)
                    )
                    filled = sum(session.scalars(select(Fill.qty).where(Fill.order_id == order.id)))
                    price_ok = (
                        row.price <= ticket.limit_price
                        if row.side == Side.BUY
                        else row.price >= ticket.limit_price
                    )
                    if (
                        (followup is None or followup.action != "TICKET_SKIPPED")
                        and filled + row.qty <= ticket.qty
                        and price_ok
                    ):
                        eligible.append((ticket, order))
                if binding is not None and len(eligible) != 1:
                    raise DataIntegrityError("UX: later fill violates its bound ticket")
                ticket_id: UUID | None = None
                if len(eligible) == 1:
                    ticket, order = eligible[0]
                    ticket_id = ticket.id
                    latest = session.scalar(
                        select(OrderEvent)
                        .where(OrderEvent.order_id == order.id)
                        .order_by(OrderEvent.seq.desc())
                        .limit(1)
                    )
                    if latest is None:
                        raise DataIntegrityError("UX: matched proposal lacks its lifecycle")
                    if latest.state == "PROPOSED":
                        self.state.ledger.append_in_session(
                            session,
                            OrderEvent,
                            order_id=order.id,
                            state="APPROVED",
                            reason="manual ticket approved; broker fill now observed",
                            broker_order_id=None,
                        )
                    if latest.state in {"PROPOSED", "APPROVED"}:
                        self.state.ledger.append_in_session(
                            session,
                            OrderEvent,
                            order_id=order.id,
                            state="SUBMITTED",
                            reason="read-only broker observation; no order sent by Project V",
                            broker_order_id=str(row.broker_order_id),
                        )
                    self.state.ledger.record_fill(
                        order.id,
                        broker_fill_id=row.broker_fill_id,
                        qty=row.qty,
                        price=row.price,
                        filled_at=row.filled_at,
                        session=session,
                    )
                    result = FillMatch(
                        status="MATCHED", broker_fill_id=row.broker_fill_id, ticket_id=ticket_id
                    )
                else:
                    snapshot = session.scalar(
                        select(DataSnapshot)
                        .where(
                            DataSnapshot.symbol == row.symbol,
                            DataSnapshot.feed == "SIP",
                            DataSnapshot.adjustment == "SPLIT",
                            DataSnapshot.fetched_at <= self.state.clock.now(),
                        )
                        .order_by(DataSnapshot.seq.desc())
                        .limit(1)
                    )
                    if snapshot is None:
                        raise DataIntegrityError(
                            "UX: manual signal requires real stored public market provenance"
                        )
                    self.state.ledger.append_in_session(
                        session,
                        Signal,
                        agent_name="broker_observed_manual",
                        symbol=row.symbol,
                        direction=row.side.value,
                        signal_type="MANUAL",
                        confidence=Decimal(0),
                        structured_thesis={"observed_fill": payload},
                        invalidation="observed trade only; no setup or stop inferred",
                        data_snapshot_id=snapshot.id,
                        prompt_hash=None,
                    )
                    result = FillMatch(status="MANUAL", broker_fill_id=row.broker_fill_id)
                self.state.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="BROKER_FILL_RECORDED",
                    detail={
                        "fill": payload,
                        "status": result.status,
                        "ticket_id": str(ticket_id) if ticket_id else None,
                        "endpoint": self.settings.broker_endpoint,
                        "mode": self.settings.execution_mode,
                    },
                )
            return result
        except Exception as exc:
            self.state.halt_for_error(exc)
            raise DataIntegrityError("UX: fill matching failed; entries halted") from None
