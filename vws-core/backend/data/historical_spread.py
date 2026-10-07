"""CM-01: delayed, bounded multi-symbol SIP quote evidence for modeled costs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from functools import partial
from typing import Literal, Self

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockQuotesRequest
from pydantic import Field, model_validator

from backend.core.clock import ensure_utc
from backend.core.errors import DataIntegrityError, SafetyError
from backend.data.data_layer import NEW_YORK, AsyncAlpacaMarketData, _provider_money
from backend.domain.models import FrozenModel, ProviderStatus, SessionDate, Symbol, UTCDateTime
from backend.evaluation.costs import Exact, Note


class SpreadMeasurement(FrozenModel):
    symbol: Symbol
    session: SessionDate
    feed: Literal["SIP"] = "SIP"
    window_start: UTCDateTime
    window_end: UTCDateTime
    fetched_at: UTCDateTime
    status: ProviderStatus
    samples: int = Field(strict=True, ge=0, le=10000)
    half_spread_bps: Exact | None = Field(default=None, ge=0, le=10000)
    reason: Note

    @model_validator(mode="after")
    def bound_measurement(self) -> Self:
        start, end = _window(self.session)
        if self.window_start != start or self.window_end != end:
            raise ValueError("CM-01: quote measurement window differs from 15:45–15:50 ET")
        if self.status == ProviderStatus.OK:
            if self.samples == 0 or self.half_spread_bps is None:
                raise ValueError("CM-01: OK requires observed quotes and a measured median")
            if self.fetched_at < end + timedelta(seconds=960):
                raise ValueError("CM-01: SIP quotes require the safe historical delay")
        elif self.samples != 0 or self.half_spread_bps is not None:
            raise ValueError("CM-01: unavailable measurements cannot infer a spread")
        return self


def _window(session: date) -> tuple[datetime, datetime]:
    return (
        ensure_utc(datetime.combine(session, time(15, 45), tzinfo=NEW_YORK)),
        ensure_utc(datetime.combine(session, time(15, 50), tzinfo=NEW_YORK)),
    )


def _result(
    symbol: str, session: date, now: datetime, values: tuple[Decimal, ...], reason: str
) -> SpreadMeasurement:
    start, end = _window(session)
    median: Decimal | None = None
    if values:
        ordered = sorted(values)
        middle = len(ordered) // 2
        with localcontext() as context:
            context.prec = 256
            median = (
                ordered[middle]
                if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
            )
            median = median.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
    return SpreadMeasurement(
        symbol=symbol,
        session=session,
        window_start=start,
        window_end=end,
        fetched_at=now,
        status=ProviderStatus.OK if values else ProviderStatus.UNAVAILABLE,
        samples=len(values),
        half_spread_bps=median,
        reason=reason,
    )


def _measure(
    raw: object, symbols: tuple[str, ...], session: date, now: datetime
) -> tuple[SpreadMeasurement, ...]:
    if not isinstance(raw, Mapping) or not set(raw).issubset(symbols):
        raise DataIntegrityError("CM-01: historical quote response symbols are unbound")
    start, end = _window(session)
    measurements: list[SpreadMeasurement] = []
    for symbol in symbols:
        rows = raw.get(symbol, [])
        if not isinstance(rows, list) or len(rows) > 10000:
            raise DataIntegrityError("CM-01: historical quote samples exceed their bound")
        values: list[Decimal] = []
        previous: datetime | None = None
        for row in rows:
            if not isinstance(row, Mapping):
                raise DataIntegrityError("CM-01: malformed historical quote")
            try:
                instant = ensure_utc(datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00")))
                bid, ask = _provider_money(row["bp"]), _provider_money(row["ap"])
                if (
                    not start <= instant <= end
                    or (previous is not None and instant < previous)
                    or ask < bid
                ):
                    raise ValueError("unverifiable quote range/order")
                previous = instant
                with localcontext() as context:
                    context.prec = 256
                    values.append((ask - bid) * Decimal(10000) / (ask + bid))
            except Exception:
                raise DataIntegrityError(
                    "CM-01: exact historical quote evidence is invalid"
                ) from None
        measurements.append(
            _result(
                symbol,
                session,
                now,
                tuple(values),
                "Historical SIP median half-spread; the liquidity floor still applies"
                if values
                else "Historical quotes unavailable; use the liquidity floor",
            )
        )
    return tuple(measurements)


class HistoricalSpreadSampler:
    """Reuses the configured read-only client, timeout, egress and physical GET budget."""

    def __init__(self, market: AsyncAlpacaMarketData) -> None:
        if not isinstance(market, AsyncAlpacaMarketData):
            raise DataIntegrityError("CM-01: a bound historical market reader is required")
        self.market = market

    async def sample(
        self, symbols: tuple[str, ...], session: date
    ) -> tuple[SpreadMeasurement, ...]:
        market = self.market
        try:
            market.reader.bind_policy(market.settings, market.ledger)
            now = ensure_utc(market.reader.clock.now())
            if (
                not isinstance(symbols, tuple)
                or not 1 <= len(symbols) <= 200
                or len(set(symbols)) != len(symbols)
            ):
                raise DataIntegrityError("CM-01: bounded unique immutable symbols required")
            for symbol in symbols:
                # Validate before a provider call or construction of an unavailable result.
                from backend.domain.models import validate_symbol

                validate_symbol(symbol)
            if (
                type(session) is not date
                or not market.calendar.is_session(session)
                or session > now.astimezone(NEW_YORK).date()
            ):
                raise DataIntegrityError("CM-01: an observed XNYS session is required")
            start, end = _window(session)
            if market.calendar.session_close(session) < end or end > now - timedelta(
                seconds=market.sip_lag_seconds
            ):
                return tuple(
                    _result(
                        symbol,
                        session,
                        now,
                        (),
                        "15:45–15:50 ET window unavailable or SIP delay incomplete; use the liquidity floor",
                    )
                    for symbol in symbols
                )
            # VERIFY: pinned alpaca-py 0.44.0 StockQuotesRequest/get_stock_quotes
            # sends multi-symbol GET /v2/stocks/quotes and paginates. Each physical
            # GET is charged by the already-installed reader transport hook.
            # https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html
            request = StockQuotesRequest(
                symbol_or_symbols=list(symbols),
                start=start,
                end=end,
                feed=DataFeed.SIP,
                limit=10000,
            )
            raw = await market.reader.run(
                partial(market.client.get_stock_quotes, request), budget_request=False
            )
            return await market.reader.run(
                partial(_measure, raw, symbols, session, now), budget_request=False
            )
        except Exception as error:
            await market.reader.halt(error)
            if isinstance(error, SafetyError):
                raise error from None
            raise DataIntegrityError("CM-01: historical spread evidence is unverifiable") from None
