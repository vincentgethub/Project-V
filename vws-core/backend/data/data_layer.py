"""DAT-01..04/R-02/R-08: validated, reproducible read-only market data.

Vendor-adjusted bars are as of the query date. Snapshots prevent look-ahead and
make replay reproducible; they do not reconstruct historical adjustment vintages.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from decimal import ROUND_FLOOR, Decimal, localcontext
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar
from zoneinfo import ZoneInfo

import requests
from pydantic import Field, model_validator
from sqlalchemy import select
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter
from urllib3.exceptions import TimeoutError as UrllibTimeoutError

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import DataSnapshot, SystemControl, SystemEvent, transaction
from backend.core.errors import DataIntegrityError, ProviderError, SafetyError, StaleDataError
from backend.core.ledger import Ledger
from backend.core.money import decimal_money, validate_cent_price
from backend.core.system_state import SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    FrozenModel,
    MarketContext,
    MarketStatus,
    Price,
    UTCDateTime,
    validate_symbol,
)

ReadT = TypeVar("ReadT")
DataAdjustment = Literal["RAW", "SPLIT", "DIVIDEND", "ALL"]
NEW_YORK = ZoneInfo("America/New_York")

if TYPE_CHECKING:
    from backend.data.async_reader import AsyncAlpacaReader
    from backend.data.corporate_actions import CorporateActionsResult


class Bar(FrozenModel):
    """DAT-02: exact OHLCV, checked before any signal can observe it."""

    timestamp: UTCDateTime
    open: Price
    high: Price
    low: Price
    close: Price
    volume: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def valid_ohlc(self) -> Bar:
        """DAT-02/R-13: malformed prices fail at construction and revalidation."""
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("DAT-02: impossible OHLC range")
        return self

    def validate_integrity(self) -> None:
        """DAT-02/R-13: frozen/model_copy objects are still untrusted at ingress."""
        try:
            Bar.model_validate(self)
        except Exception:
            raise DataIntegrityError("DAT-02: invalid OHLCV bar") from None

    @property
    def session_date(self) -> date:
        """DAT-03: Alpaca daily labels use the America/New_York trading date."""
        return self.timestamp.astimezone(NEW_YORK).date()


class MarketDataProvider(Protocol):
    """R-08: market boundary exposes reads only."""

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        """Read completed and possibly in-progress raw daily bars."""
        raise NotImplementedError("provider must implement daily_bars")

    def latest_market(self, symbol: str, now: datetime) -> MarketContext:
        """Read current price, its timestamp and a documented ADV estimate."""
        raise NotImplementedError("provider must implement latest_market")


@dataclass(frozen=True)
class FakeMarketData:
    """R-08: deterministic in-memory provider for offline tests."""

    bars: tuple[Bar, ...]
    context: MarketContext
    symbol: str

    def _bound_symbol(self, symbol: str) -> None:
        """DAT-02/R-02: synthetic observations are bound to one explicit symbol."""
        try:
            validate_symbol(self.symbol)
            validate_symbol(symbol)
        except Exception:
            raise DataIntegrityError("DAT-02: invalid fixture symbol") from None
        if symbol != self.symbol:
            raise DataIntegrityError("DAT-02: fixture symbol does not match request")

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        self._bound_symbol(symbol)
        return tuple(bar for bar in self.bars if start <= bar.session_date <= end)

    def latest_market(self, symbol: str, now: datetime) -> MarketContext:
        self._bound_symbol(symbol)
        return self.context


def _transient(error: BaseException) -> bool:
    """DAT-04: retry only timeouts, 429 and server failures."""
    if isinstance(error, (TimeoutError, requests.Timeout, UrllibTimeoutError)):
        return True
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "status", None)
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    return type(status) is int and (status == 429 or 500 <= status <= 599)


class ResilientReader:
    """DAT-04: bounded retries, request budget and latched circuit breaker.

    Jitter and sleeping are I/O scheduling, never rule logic. Every exhausted or
    non-transient read halts; no read failure can manufacture trusted data.
    """

    def __init__(
        self,
        clock: Clock,
        state: SystemStateStore,
        *,
        attempts: int = 3,
        calls_per_minute: int | None = None,
        plan: str = "BASIC",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if calls_per_minute is None:
            calls_per_minute = 180 if plan == "BASIC" else 9000
        if (
            type(attempts) is not int
            or type(calls_per_minute) is not int
            or not 1 <= attempts <= 10
            or plan not in {"BASIC", "ALGO_TRADER_PLUS"}
            or not 1 <= calls_per_minute <= (180 if plan == "BASIC" else 9000)
        ):
            raise ProviderError("DAT-04: invalid resilience bounds")
        self.clock = clock
        self.state = state
        self.attempts = attempts
        self.calls_per_minute = calls_per_minute
        self.plan = plan
        self.sleep = sleep
        self.tripped = False
        self._calls: deque[datetime] = deque()

    def _budget(self) -> None:
        now = ensure_utc(self.clock.now())
        if self._calls and now < self._calls[-1]:
            raise DataIntegrityError("DAT-02: local clock moved backward")
        while self._calls and now - self._calls[0] >= timedelta(minutes=1):
            self._calls.popleft()
        if len(self._calls) >= self.calls_per_minute:
            raise ProviderError("DAT-04: historical request budget exhausted")
        self._calls.append(now)

    def before_request(self) -> None:
        """DAT-04: transport hooks count every actual request, including SDK pages."""
        self._budget()

    def run(self, operation: Callable[[], ReadT], *, budget_request: bool = True) -> ReadT:
        """DAT-04/R-02: bounded external read or typed failure plus HALTED."""
        if self.tripped:
            raise ProviderError("DAT-04: circuit breaker is latched")
        try:

            def bounded_operation() -> ReadT:
                if budget_request:
                    self._budget()
                return operation()

            retrying = Retrying(
                stop=stop_after_attempt(self.attempts),
                wait=wait_exponential_jitter(initial=1, max=8),
                retry=retry_if_exception(_transient),
                sleep=self.sleep,
                reraise=True,
            )
            return retrying(bounded_operation)
        except Exception as exc:
            self.tripped = True
            self.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise ProviderError("DAT-04: read failed; circuit latched HALTED") from None


def validate_quote(
    context: MarketContext, now: datetime, config: Settings, calendar: MarketCalendar
) -> None:
    """DAT-01/DAT-02: session-aware quote freshness; no weekend age inflation."""
    instant = ensure_utc(now)
    try:
        context = MarketContext.model_validate(context)
    except Exception:
        raise DataIntegrityError("DAT-02: invalid quote context") from None
    timestamp = ensure_utc(context.last_price_ts)
    if timestamp > instant:
        raise DataIntegrityError("DAT-02: quote timestamp is in the future")
    if calendar.is_open(instant):
        cutoff = instant - timedelta(seconds=config.stale_quote_seconds)
    else:
        session = calendar.last_completed_session(instant)
        cutoff = calendar.session_close(session) - timedelta(seconds=config.stale_quote_seconds)
    if timestamp < cutoff:
        raise StaleDataError("DAT-01: quote predates the latest required session observation")


def validate_clock_skew(broker_time: datetime, now: datetime, config: Settings) -> None:
    """DAT-02: compare aware instants without money or float arithmetic."""
    skew = abs(ensure_utc(broker_time) - ensure_utc(now))
    if skew > timedelta(seconds=config.max_clock_skew_seconds):
        raise DataIntegrityError("DAT-02: broker/local clock skew exceeds ceiling")


class _DailySymbolStatus:
    """DAT-02: one durable gap/acknowledgment rule shared by both data paths."""

    def __init__(
        self,
        config: Settings,
        calendar: MarketCalendar,
        clock: Clock,
        state: SystemStateStore,
        ledger: Ledger,
        corporate_actions: frozenset[tuple[str, date]] = frozenset(),
    ) -> None:
        self.config, self.calendar, self.clock = config, calendar, clock
        self.state, self.ledger = state, ledger
        self.corporate_actions = corporate_actions
        self._suspect: set[str] = set()
        self._acknowledged_through: dict[str, date] = {}

    def _reload_symbol_status(self) -> None:
        """DAT-02/R-02: verify durable flags so another worker cannot leave a stale OK."""
        self.ledger.verify_chain()
        suspect: set[str] = set()
        acknowledgments: dict[str, date] = {}
        with transaction(self.ledger.engine) as session:
            for event in session.scalars(select(SystemEvent).order_by(SystemEvent.seq)):
                if event.reason.startswith("DAT-02 symbol status: "):
                    payload = json.loads(event.reason.removeprefix("DAT-02 symbol status: "))
                    symbol = validate_symbol(payload["symbol"])
                    status = MarketStatus(payload["status"])
                    if status == MarketStatus.SUSPECT:
                        suspect.add(symbol)
                    else:
                        suspect.discard(symbol)
                        if "acknowledged_through" in payload:
                            through = date.fromisoformat(payload["acknowledged_through"])
                            if through > event.created_at.astimezone(NEW_YORK).date():
                                raise DataIntegrityError("DAT-02: future gap acknowledgment")
                            acknowledgments[symbol] = through
        self._suspect = suspect
        self._acknowledged_through = acknowledgments

    def _record_symbol_status(
        self,
        symbol: str,
        status: str,
        operator_id: str | None,
        reason: str,
        *,
        acknowledged_through: date | None = None,
    ) -> None:
        """DAT-02: durable suspect flags survive process restarts."""
        with transaction(self.ledger.engine) as session:
            control = session.get(SystemControl, 1)
            if control is None:
                raise DataIntegrityError("DAT-02: missing state control for symbol status")
            fields = {"symbol": symbol, "status": status, "reason": reason}
            if acknowledged_through is not None:
                fields["acknowledged_through"] = acknowledged_through.isoformat()
            payload = json.dumps(fields, sort_keys=True)
            self.ledger.append_in_session(
                session,
                SystemEvent,
                state=control.state,
                reason="DAT-02 symbol status: " + payload,
                operator_id=operator_id,
                event_type="ESCALATE",
            )
            control.version += 1

    def acknowledge_gap(self, symbol: str, operator_id: str, reason: str) -> None:
        """DAT-02: explicit local operator acknowledgment clears a suspect symbol."""
        try:
            if not operator_id.strip() or not reason.strip():
                raise DataIntegrityError("DAT-02: gap acknowledgment needs attribution")
            validate_symbol(symbol)
            self.ledger.verify_chain()
            through = self.calendar.last_completed_session(ensure_utc(self.clock.now()))
            self._record_symbol_status(
                symbol, "OK", operator_id, reason, acknowledged_through=through
            )
            self._acknowledged_through[symbol] = through
            self._suspect.discard(symbol)
        except Exception as exc:
            self.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise DataIntegrityError("DAT-02: symbol acknowledgment failed") from None

    def evaluate(
        self,
        symbol: str,
        bars: tuple[Bar, ...],
        *,
        known_actions: frozenset[tuple[str, date]] = frozenset(),
    ) -> MarketStatus:
        if any(bar.volume <= 0 for bar in bars):
            self.mark_suspect(symbol, "DQ-03: daily session volume is not positive")
        for left, right in zip(bars, bars[1:], strict=False):
            with localcontext() as context:
                context.prec = 50
                gap_amount = abs(right.open - left.close)
                gap_limit = self.config.gap_alert_pct * left.close
            if (
                gap_amount > gap_limit
                and (symbol, right.session_date) not in self.corporate_actions
                and (symbol, right.session_date) not in known_actions
                and right.session_date > self._acknowledged_through.get(symbol, date.min)
            ):
                if symbol not in self._suspect:
                    self._record_symbol_status(symbol, "SUSPECT", None, "unexplained overnight gap")
                self._suspect.add(symbol)
        return MarketStatus.SUSPECT if symbol in self._suspect else MarketStatus.OK

    def mark_suspect(self, symbol: str, reason: str) -> None:
        """DQ-03: durable exclusion applies to all subsequent quote/bar reads."""
        validate_symbol(symbol)
        if symbol not in self._suspect:
            self._record_symbol_status(symbol, "SUSPECT", None, reason)
        self._suspect.add(symbol)


class DataLayer:
    """DAT-01..04: validation, provenance and state escalation around provider reads."""

    def __init__(
        self,
        config: Settings,
        provider: MarketDataProvider,
        calendar: MarketCalendar,
        clock: Clock,
        state: SystemStateStore,
        ledger: Ledger,
        *,
        sip_grace_seconds: int = 900,
        corporate_actions: frozenset[tuple[str, date]] = frozenset(),
        reader: ResilientReader | None = None,
    ) -> None:
        if type(sip_grace_seconds) is not int or not 0 <= sip_grace_seconds <= 900:
            raise DataIntegrityError("DAT-01: invalid completed-bar grace")
        self.config = config
        self.provider = provider
        self.calendar = calendar
        self.clock = clock
        self.state = state
        self.ledger = ledger
        self.sip_grace_seconds = sip_grace_seconds
        self.corporate_actions = corporate_actions
        self.reader = reader or ResilientReader(clock, state)
        try:
            self.config = _checked_settings(config)
            if not isinstance(corporate_actions, frozenset):
                raise DataIntegrityError("DAT-02: corporate actions must be immutable")
            for corporate_symbol, corporate_day in corporate_actions:
                validate_symbol(corporate_symbol)
                if type(corporate_day) is not date:
                    raise DataIntegrityError("DAT-02: corporate action date is invalid")
            self._status = _DailySymbolStatus(
                self.config, calendar, clock, state, ledger, corporate_actions
            )
            self._status._reload_symbol_status()
        except Exception as exc:
            self.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise DataIntegrityError("DAT-02: persisted symbol status is unverifiable") from None

    def acknowledge_gap(self, symbol: str, operator_id: str, reason: str) -> None:
        """DAT-02: preserve the explicit local-only durable acknowledgment API."""
        self._status.acknowledge_gap(symbol, operator_id, reason)

    def _record_symbol_status(
        self,
        symbol: str,
        status: str,
        operator_id: str | None,
        reason: str,
        *,
        acknowledged_through: date | None = None,
    ) -> None:
        """DAT-02: preserve the internal audited status boundary for existing callers."""
        self._status._record_symbol_status(
            symbol,
            status,
            operator_id,
            reason,
            acknowledged_through=acknowledged_through,
        )

    def latest_market(self, symbol: str) -> MarketContext:
        """DAT-01/R-02: every malformed or stale provider quote halts."""
        try:
            validate_symbol(symbol)
            now = ensure_utc(self.clock.now())
            if isinstance(self.provider, AlpacaMarketData):
                context = self.provider.latest_market(symbol, now)
            else:
                context = self.reader.run(lambda: self.provider.latest_market(symbol, now))
            context = MarketContext.model_validate(context)
            completed_at = ensure_utc(self.clock.now())
            if completed_at < now:
                raise DataIntegrityError("DAT-02: clock moved backwards during quote read")
            validate_quote(context, completed_at, self.config, self.calendar)
            self._status._reload_symbol_status()
            if symbol in self._status._suspect:
                context = context.model_copy(update={"status": MarketStatus.SUSPECT})
            return context
        except Exception as exc:
            self.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise DataIntegrityError("DAT-02: unverifiable market context") from None

    def completed_daily_bars(self, symbol: str, start: date) -> tuple[Bar, ...]:
        """DAT-01..03: store raw fetch; return only complete, contiguous sessions."""
        try:
            validate_symbol(symbol)
            now = ensure_utc(self.clock.now())
            end = now.astimezone(NEW_YORK).date()
            _validate_daily_window(start, end)
            self._status._reload_symbol_status()
            try:
                if isinstance(self.provider, AlpacaMarketData):
                    fetched = self.provider.daily_bars(symbol, start, end)
                else:
                    fetched = self.reader.run(lambda: self.provider.daily_bars(symbol, start, end))
            except DataIntegrityError:
                self._status.mark_suspect(symbol, "DQ-03: malformed daily provider evidence")
                raise
            if not isinstance(fetched, tuple) or not fetched:
                raise DataIntegrityError("DAT-02: daily data is empty")
            try:
                raw = tuple(Bar.model_validate(bar) for bar in fetched)
            except Exception:
                self._status.mark_suspect(symbol, "DQ-03: invalid daily OHLC/session evidence")
                raise
            previous: datetime | None = None
            previous_day: date | None = None
            for bar in raw:
                bar.validate_integrity()
                if not start <= bar.session_date <= end:
                    raise DataIntegrityError("DAT-02: daily bar is outside requested range")
                if bar.timestamp > now:
                    raise DataIntegrityError("DAT-02: daily bar is in the future")
                if previous is not None and bar.timestamp <= previous:
                    self._status.mark_suspect(symbol, "DQ-03: duplicate or unordered sessions")
                    raise DataIntegrityError("DAT-02: duplicate or unordered daily timestamps")
                if previous_day == bar.session_date:
                    self._status.mark_suspect(symbol, "DQ-03: duplicate daily session")
                    raise DataIntegrityError("DAT-02: duplicate daily session")
                previous = bar.timestamp
                previous_day = bar.session_date
                try:
                    self.calendar.session_close(bar.session_date)
                except Exception:
                    self._status.mark_suspect(symbol, "DQ-03: bar is not an XNYS session")
                    raise
            encoded = json.dumps(
                [bar.model_dump(mode="json") for bar in raw],
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            self.ledger.append(
                DataSnapshot,
                symbol=symbol,
                timeframe="1Day",
                range_start=raw[0].timestamp,
                range_end=raw[-1].timestamp,
                feed="SIP",
                adjustment="SPLIT",
                fetched_at=now,
                bar_count=len(raw),
                sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                bars=json.loads(encoded),
            )
            completed = tuple(
                bar for bar in raw if self.calendar.session_close(bar.session_date) <= now
            )
            expected = self.calendar.last_completed_session(
                now - timedelta(seconds=self.sip_grace_seconds)
            )
            if not completed or completed[-1].session_date < expected:
                raise StaleDataError("DAT-01: latest completed daily session is missing")
            first_expected = start
            while not self.calendar.is_session(first_expected):
                first_expected += timedelta(days=1)
            if completed[0].session_date != first_expected:
                self._status.mark_suspect(symbol, "DQ-03: first requested session is missing")
                raise DataIntegrityError("DAT-02: first requested exchange session is missing")
            for left, right in zip(completed, completed[1:], strict=False):
                if self.calendar.add_sessions(left.session_date, 1) != right.session_date:
                    self._status.mark_suspect(symbol, "DQ-03: daily session is missing")
                    raise DataIntegrityError("DAT-02: exchange session missing from daily data")
            self._status.evaluate(symbol, completed)
            return completed
        except Exception as exc:
            self.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise DataIntegrityError("DAT-02: unverifiable daily bars") from None

    def validate_intraday(
        self, bars: Sequence[Bar], timeframe_seconds: int, *, grace_seconds: int = 0
    ) -> tuple[Bar, ...]:
        """DAT-01/DAT-02: check bar end times; reject future and duplicate observations."""
        try:
            if (
                type(timeframe_seconds) is not int
                or type(grace_seconds) is not int
                or not 1 <= timeframe_seconds <= 86400
                or not 0 <= grace_seconds <= 900
                or not bars
            ):
                raise DataIntegrityError("DAT-02: invalid intraday contract")
            bars = tuple(Bar.model_validate(bar) for bar in bars)
            now = ensure_utc(self.clock.now())
            previous: datetime | None = None
            for bar in bars:
                bar.validate_integrity()
                if not self.calendar.is_open(bar.timestamp):
                    raise DataIntegrityError("DAT-02: intraday bar is outside regular hours")
                if bar.timestamp > now or (previous is not None and bar.timestamp <= previous):
                    raise DataIntegrityError("DAT-02: invalid intraday timestamps")
                bar_date = bar.timestamp.astimezone(NEW_YORK).date()
                close = self.calendar.session_close(bar_date)
                if bar.timestamp + timedelta(seconds=timeframe_seconds) > close:
                    raise DataIntegrityError("DAT-02: intraday bar straddles session close")
                if previous is not None:
                    previous_date = previous.astimezone(NEW_YORK).date()
                    if previous_date == bar_date and bar.timestamp != previous + timedelta(
                        seconds=timeframe_seconds
                    ):
                        raise DataIntegrityError("DAT-02: intraday interval is missing")
                    if previous_date != bar_date and (
                        self.calendar.add_sessions(previous_date, 1) != bar_date
                        or bar.timestamp != self.calendar.session_open(bar_date)
                        or previous + timedelta(seconds=timeframe_seconds)
                        != self.calendar.session_close(previous_date)
                    ):
                        raise DataIntegrityError("DAT-02: exchange session interval is missing")
                previous = bar.timestamp
            end = bars[-1].timestamp + timedelta(seconds=timeframe_seconds)
            if end > now:
                raise DataIntegrityError("DAT-03: intraday bar is still in progress")
            if self.calendar.is_open(now):
                cutoff = now - timedelta(seconds=2 * timeframe_seconds + grace_seconds)
            else:
                cutoff = self.calendar.session_close(
                    self.calendar.last_completed_session(now)
                ) - timedelta(seconds=2 * timeframe_seconds + grace_seconds)
            if end < cutoff:
                raise StaleDataError("DAT-01: intraday bars are stale")
            return tuple(bars)
        except Exception as exc:
            self.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise DataIntegrityError("DAT-02: unverifiable intraday bars") from None


class AlpacaMarketData:
    """DAT-03/R-08: official SDK read requests, SIP daily and IEX real-time.

    The transport enforces timeout; each SDK read is wrapped in ResilientReader.
    Adjusted history is query-date-adjusted, rather than historical-vintage data.
    """

    def __init__(
        self,
        settings: Settings,
        reader: ResilientReader,
        *,
        client: Any = None,
        calendar: MarketCalendar | None = None,
    ) -> None:
        from alpaca.data.historical import StockHistoricalDataClient

        from backend.data.broker_state import configure_alpaca_transport

        self.reader = reader
        try:
            self.settings = _checked_settings(settings)
            self.calendar = calendar or MarketCalendar()
            # VERIFY: https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html
            self.client: Any = (
                client
                if client is not None
                else StockHistoricalDataClient(
                    api_key=self.settings.broker_api_key.get_secret_value(),
                    secret_key=self.settings.broker_secret_key.get_secret_value(),
                    raw_data=True,
                )
            )
            configure_alpaca_transport(
                self.client,
                self.settings.request_timeout_seconds,
                before_request=self.reader.before_request,
            )
        except Exception as exc:
            self.reader.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise ProviderError("DAT-04: market client initialization failed") from None

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[Bar, ...]:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        try:
            validate_symbol(symbol)
            _validate_daily_window(start, end)
            # VERIFY: https://alpaca.markets/sdks/python/api_reference/data/stock/requests.html
            # Pinned SDK normalizes these aware bounds to naive UTC internally.
            request = StockBarsRequest(
                symbol_or_symbols=[symbol],
                start=datetime.combine(start, datetime_time.min, tzinfo=NEW_YORK),
                end=min(
                    datetime.combine(end + timedelta(days=1), datetime_time.min, tzinfo=NEW_YORK),
                    ensure_utc(self.reader.clock.now()) - timedelta(minutes=16),
                    self.calendar.session_close(
                        _eligible_session(self.calendar, self.reader.clock.now(), 30)
                    ),
                ),
                timeframe=TimeFrame.Day,
                feed=DataFeed.SIP,
                adjustment=Adjustment.SPLIT,
            )
            response = self.reader.run(
                lambda: self.client.get_stock_bars(request), budget_request=False
            )
            if not isinstance(response, Mapping):
                raise DataIntegrityError("DAT-02: unexpected SDK bars response")
            payload = response.get(symbol)
            if not isinstance(payload, list):
                raise DataIntegrityError("DAT-02: requested symbol bars are missing")
            bars = tuple(self._parse_bar(value) for value in payload)
            if any(not start <= bar.session_date <= end for bar in bars):
                raise DataIntegrityError("DAT-02: SDK bars are outside requested range")
            return bars
        except Exception as exc:
            self.reader.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise ProviderError("DAT-04: Alpaca daily bars read failed") from None

    @staticmethod
    def _parse_bar(value: object) -> Bar:
        if not isinstance(value, Mapping):
            raise DataIntegrityError("DAT-02: malformed bar record")
        try:
            timestamp = datetime.fromisoformat(str(value["t"]).replace("Z", "+00:00"))
            return Bar(
                timestamp=timestamp,
                open=_provider_money(value["o"]),
                high=_provider_money(value["h"]),
                low=_provider_money(value["l"]),
                close=_provider_money(value["c"]),
                volume=value["v"],
            )
        except Exception:
            raise DataIntegrityError("DAT-02: malformed Alpaca bar") from None

    def latest_market(self, symbol: str, now: datetime) -> MarketContext:
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest

        try:
            validate_symbol(symbol)
            now = ensure_utc(now)
            # VERIFY: https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html
            quote = self.reader.run(
                lambda: self.client.get_stock_latest_quote(
                    StockLatestQuoteRequest(symbol_or_symbols=[symbol], feed=DataFeed.IEX)
                ),
                budget_request=False,
            )
            trade = self.reader.run(
                lambda: self.client.get_stock_latest_trade(
                    StockLatestTradeRequest(symbol_or_symbols=[symbol], feed=DataFeed.IEX)
                ),
                budget_request=False,
            )
            q = quote[symbol]
            t = trade[symbol]
            completed_at = ensure_utc(self.reader.clock.now())
            if completed_at < now:
                raise DataIntegrityError("DAT-02: clock moved backwards during quote read")
            now = completed_at
            bid, ask = _provider_money(q["bp"]), _provider_money(q["ap"])
            if ask < bid:
                raise DataIntegrityError("DAT-02: invalid bid/ask")
            timestamp = datetime.fromisoformat(str(t["t"]).replace("Z", "+00:00"))
            quote_time = datetime.fromisoformat(str(q["t"]).replace("Z", "+00:00"))
            if quote_time > now or timestamp > now:
                raise DataIntegrityError("DAT-02: future quote/trade")
            # An explicit 60-day window supplies 20 complete sessions even around holidays.
            bars = self.daily_bars(symbol, now.date() - timedelta(days=60), now.date())
            eligible = _eligible_session(self.calendar, now, 30)
            cutoff = min(
                ensure_utc(now) - timedelta(minutes=16), self.calendar.session_close(eligible)
            )
            previous: datetime | None = None
            previous_day: date | None = None
            for bar in bars:
                bar.validate_integrity()
                if bar.timestamp > now:
                    raise DataIntegrityError("DAT-02: future ADV bar")
                if previous is not None and bar.timestamp <= previous:
                    raise DataIntegrityError("DAT-02: duplicate or unordered ADV timestamps")
                if previous_day == bar.session_date:
                    raise DataIntegrityError("DAT-02: duplicate ADV session")
                previous, previous_day = bar.timestamp, bar.session_date
            complete = tuple(
                bar for bar in bars if self.calendar.session_close(bar.session_date) <= cutoff
            )[-20:]
            if len(complete) != 20:
                raise DataIntegrityError("DAT-02: insufficient ADV history")
            if complete[-1].session_date != self.calendar.last_completed_session(cutoff):
                raise StaleDataError("DAT-01: ADV history is stale")
            for left, right in zip(complete, complete[1:], strict=False):
                if self.calendar.add_sessions(left.session_date, 1) != right.session_date:
                    raise DataIntegrityError("DAT-02: ADV exchange session missing")
            # Floor only the derived average so the liquidity cap is conservative.
            with localcontext() as ctx:
                ctx.prec = max(50, max(len(str(bar.volume)) for bar in complete) + 30)
                adv = (
                    sum((bar.close * bar.volume for bar in complete), Decimal(0)) / Decimal(20)
                ).quantize(Decimal("0.000001"), rounding=ROUND_FLOOR)
            context = MarketContext(
                last_price=_provider_money(t["p"]),
                last_price_ts=min(timestamp, quote_time),
                adv20_usd=adv,
                status=MarketStatus.OK,
            )
            validate_quote(context, now, self.settings, self.calendar)
            return context
        except Exception as exc:
            self.reader.state.halt_for_error(exc)
            if isinstance(exc, SafetyError):
                raise exc from None
            raise DataIntegrityError("DAT-02: malformed Alpaca quote/trade") from None


def _provider_money(value: object) -> Decimal:
    """R-04: transport already parsed exact JSON; inexact injected SDK data fails."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise DataIntegrityError("DAT-02: provider money must be exact")
    return validate_cent_price(decimal_money(value))


def _validate_daily_window(start: date, end: date) -> None:
    """DAT-02/R-05: daily requests require explicit ordered calendar dates."""
    if type(start) is not date or type(end) is not date or start > end:
        raise DataIntegrityError("DAT-02: invalid daily request window")


def _checked_settings(config: Settings) -> Settings:
    """R-02: reconstruct frozen settings so model_copy cannot bypass ceilings."""
    payload = config.model_dump()
    if (
        not config.telegram_allowed_user_ids
        and "telegram_allowed_user_ids" not in config.model_fields_set
    ):
        payload.pop("telegram_allowed_user_ids")
    return Settings.model_validate(payload)


def _eligible_session(calendar: MarketCalendar, now: datetime, delay_minutes: int) -> date:
    instant = ensure_utc(now)
    session = calendar.last_completed_session(instant)
    if instant < calendar.session_close(session) + timedelta(minutes=delay_minutes):
        session = calendar.previous_sessions(session, 1)[0]
    return session


def _bars_digest(bars: tuple[Bar, ...]) -> tuple[str, list[dict[str, Any]]]:
    payload = [bar.model_dump(mode="json") for bar in bars]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest(), payload


class SymbolBars(FrozenModel):
    """DAT-05: exact cached sessions and their reproducible completed-data hash."""

    symbol: str
    adjustment: DataAdjustment = "SPLIT"
    bars: tuple[Bar, ...] = Field(min_length=1, max_length=20000)
    data_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: MarketStatus = MarketStatus.OK

    @model_validator(mode="after")
    def bound_bars(self) -> SymbolBars:
        validate_symbol(self.symbol)
        if not self.bars or self.data_sha256 != _bars_digest(self.bars)[0]:
            raise ValueError("DAT-05: bars require a matching immutable payload hash")
        return self


class BatchBars(FrozenModel):
    """DAT-05: immutable multi-symbol data; benchmarks share the same SDK batch."""

    as_of: UTCDateTime
    through: date
    entries: tuple[SymbolBars, ...] = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def unique_symbols(self) -> BatchBars:
        names = tuple((entry.symbol, entry.adjustment) for entry in self.entries)
        if not names or len(names) != len(set(names)):
            raise ValueError("DAT-05: batch symbol/adjustment pairs must be unique and nonempty")
        if any(entry.bars[-1].session_date != self.through for entry in self.entries):
            raise ValueError("DAT-05: all symbols require the same completed tail")
        return self

    def for_symbol(self, symbol: str, adjustment: DataAdjustment = "SPLIT") -> tuple[Bar, ...]:
        validate_symbol(symbol)
        for entry in self.entries:
            if (entry.symbol, entry.adjustment) == (symbol, adjustment):
                return entry.bars
        raise DataIntegrityError("DAT-05: requested symbol is absent from batch")

    def status_for(self, symbol: str, adjustment: DataAdjustment = "SPLIT") -> MarketStatus:
        validate_symbol(symbol)
        for entry in self.entries:
            if (entry.symbol, entry.adjustment) == (symbol, adjustment):
                return entry.status
        raise DataIntegrityError("DAT-05: requested status is absent from batch")


class AsyncAlpacaMarketData:
    """DAT-05..08: ledger-backed incremental multi-symbol completed daily bars."""

    def __init__(
        self,
        settings: Settings,
        reader: AsyncAlpacaReader,
        calendar: MarketCalendar,
        ledger: Ledger,
        client: Any = None,
        *,
        daily_scan_delay_minutes: int = 30,
        sip_lag_seconds: int = 960,
        invalidate_indicators: Callable[[str], None] | None = None,
    ) -> None:
        from alpaca.data.historical import StockHistoricalDataClient

        from backend.data.broker_state import configure_alpaca_transport

        if (
            type(daily_scan_delay_minutes) is not int
            or not 30 <= daily_scan_delay_minutes <= 1440
            or type(sip_lag_seconds) is not int
            or not 960 <= sip_lag_seconds <= 3600
        ):
            raise DataIntegrityError("DAT-07: daily delay or SIP lag weakens required bounds")
        self.settings = _checked_settings(settings)
        self.reader, self.calendar, self.ledger = reader, calendar, ledger
        reader.bind_policy(self.settings, ledger)
        self._status = _DailySymbolStatus(
            self.settings, calendar, reader.clock, reader.state, ledger
        )
        self.delay, self.sip_lag_seconds = daily_scan_delay_minutes, sip_lag_seconds
        self.invalidate_indicators = invalidate_indicators
        self._seen_split_epochs: dict[str, int] = {}
        try:
            self.client: Any = (
                client
                if client is not None
                else StockHistoricalDataClient(
                    api_key=self.settings.broker_api_key.get_secret_value(),
                    secret_key=self.settings.broker_secret_key.get_secret_value(),
                    raw_data=True,
                )
            )
            configure_alpaca_transport(
                self.client,
                self.settings.request_timeout_seconds,
                before_request=reader.before_request,
            )
        except Exception as error:
            self.reader.state.halt_for_error(error)
            raise ProviderError("DAT-08: async market transport could not be configured") from None

    def _cache(
        self, symbols: tuple[str, ...], now: datetime, adjustment: DataAdjustment = "SPLIT"
    ) -> dict[str, dict[date, Bar]]:
        self.reader.ensure_active()
        self.ledger.verify_chain()
        result: dict[str, dict[date, Bar]] = {symbol: {} for symbol in symbols}
        with transaction(self.ledger.engine) as session:
            from backend.data.split_cache import current_epochs

            epochs = current_epochs(session, now)
            records = session.scalars(
                select(DataSnapshot)
                .where(
                    DataSnapshot.symbol.in_(symbols),
                    DataSnapshot.timeframe == "1Day",
                    DataSnapshot.feed == "SIP",
                    DataSnapshot.adjustment == adjustment,
                )
                .order_by(DataSnapshot.seq)
            )
            for record in records:
                self.reader.ensure_active()
                if record.seq <= epochs.get(record.symbol, 0):
                    continue
                if record.fetched_at > now:
                    raise DataIntegrityError("DAT-05: cached snapshot is future data")
                bars = tuple(self._cached_bar(value) for value in record.bars)
                if (
                    not bars
                    or record.bar_count != len(bars)
                    or record.sha256 != _bars_digest(bars)[0]
                    or record.range_start != bars[0].timestamp
                    or record.range_end != bars[-1].timestamp
                ):
                    raise DataIntegrityError("DAT-05: cached payload differs from its provenance")
                previous: Bar | None = None
                for bar in bars:
                    bar.validate_integrity()
                    if bar.timestamp > record.fetched_at:
                        raise DataIntegrityError("DAT-05: cached bar is later than its fetch")
                    if previous is not None and (
                        bar.timestamp <= previous.timestamp
                        or bar.session_date <= previous.session_date
                    ):
                        raise DataIntegrityError("DAT-05: cached raw daily sessions are unordered")
                    previous = bar
                    if (
                        self.calendar.session_close(bar.session_date)
                        + timedelta(minutes=self.delay)
                        > record.fetched_at
                    ):
                        # Raw legacy snapshots can include an in-progress bar. Its
                        # exact digest is checked, but it is never completed evidence.
                        continue
                    existing = result[record.symbol].get(bar.session_date)
                    if existing is not None and existing != bar:
                        raise DataIntegrityError("DAT-05: conflicting immutable cached session")
                    result[record.symbol][bar.session_date] = bar
        self.reader.ensure_active()
        return result

    def _invalidate_splits(self, actions: CorporateActionsResult | None, now: datetime) -> None:
        from backend.data.split_cache import observe_splits

        self.reader.ensure_active()
        epochs = observe_splits(self.ledger, actions, now)
        for symbol, seq in epochs.items():
            if seq > self._seen_split_epochs.get(symbol, 0):
                if self.invalidate_indicators is not None:
                    self.invalidate_indicators(symbol)
                self._seen_split_epochs[symbol] = seq
        self.reader.ensure_active()

    @staticmethod
    def _cached_bar(value: object) -> Bar:
        """DAT-05/R-04: deserialize exact stored JSON through the typed bar boundary."""
        if not isinstance(value, Mapping) or set(value) != set(Bar.model_fields):
            raise DataIntegrityError("DAT-05: cached bar has an invalid field inventory")
        try:
            return Bar(
                timestamp=datetime.fromisoformat(value["timestamp"]),
                open=_provider_money(value["open"]),
                high=_provider_money(value["high"]),
                low=_provider_money(value["low"]),
                close=_provider_money(value["close"]),
                volume=value["volume"],
            )
        except Exception:
            raise DataIntegrityError("DAT-05: cached exact bar is malformed") from None

    def _store(
        self,
        snapshots: tuple[tuple[str, tuple[Bar, ...]], ...],
        entries: tuple[SymbolBars, ...],
        now: datetime,
        known_actions: frozenset[tuple[str, date]],
        adjustment: DataAdjustment = "SPLIT",
    ) -> tuple[SymbolBars, ...]:
        """DAT-02/05/08: DB/cache and durable gaps share the bounded worker path."""
        self.reader.ensure_active()
        self._status._reload_symbol_status()
        checked: list[SymbolBars] = []
        for entry in entries:
            self.reader.ensure_active()
            status = self._status.evaluate(entry.symbol, entry.bars, known_actions=known_actions)
            checked.append(SymbolBars.model_validate(entry.model_copy(update={"status": status})))
        with transaction(self.ledger.engine) as session:
            from backend.data.split_cache import current_epochs

            epochs = current_epochs(session, now)
            if any(
                epochs.get(entry.symbol, 0) != self._seen_split_epochs.get(entry.symbol, 0)
                for entry in entries
            ):
                raise DataIntegrityError("DQ-01: a split invalidated the active fetch")
            for symbol, bars in snapshots:
                self.reader.ensure_active()
                digest, raw = _bars_digest(bars)
                self.ledger.append_in_session(
                    session,
                    DataSnapshot,
                    symbol=symbol,
                    timeframe="1Day",
                    range_start=bars[0].timestamp,
                    range_end=bars[-1].timestamp,
                    feed="SIP",
                    adjustment=adjustment,
                    fetched_at=now,
                    bar_count=len(bars),
                    sha256=digest,
                    bars=raw,
                )
            self.reader.ensure_active()
        self.reader.ensure_active()
        return tuple(checked)

    def _parse_completed(
        self, symbol: str, payload: object, first: date, tail: date, now: datetime
    ) -> tuple[Bar, ...]:
        """DQ-03: malformed sessions leave durable SUSPECT evidence before the HALT."""
        try:
            if not isinstance(payload, list) or not 1 <= len(payload) <= 20000:
                raise StaleDataError("DAT-05: incremental symbol sessions are unavailable")
            bars = tuple(AlpacaMarketData._parse_bar(value) for value in payload)
            expected = first
            for bar in bars:
                if bar.session_date != expected or bar.timestamp > now or bar.session_date > tail:
                    raise DataIntegrityError(
                        "DQ-03: daily sessions are unordered, missing or future"
                    )
                expected = self.calendar.add_sessions(expected, 1)
            if bars[-1].session_date != tail:
                raise StaleDataError("DAT-05: incremental completed tail is missing")
            return bars
        except Exception:
            self._status._reload_symbol_status()
            self._status.mark_suspect(symbol, "DQ-03: invalid daily OHLC or exchange sessions")
            raise

    async def completed_daily_bars(
        self,
        symbols: tuple[str, ...],
        start: date,
        *,
        benchmarks: tuple[str, ...] = ("SPY",),
        corporate_actions: CorporateActionsResult | None = None,
        adjustment: DataAdjustment = "SPLIT",
    ) -> BatchBars:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        try:
            self.reader.bind_policy(self.settings, self.ledger)
            if adjustment not in {"RAW", "SPLIT", "DIVIDEND", "ALL"}:
                raise DataIntegrityError("DQ-01: unsupported SDK bar adjustment")
            if not isinstance(symbols, tuple) or not isinstance(benchmarks, tuple):
                raise DataIntegrityError("DAT-05: symbols and benchmarks must be immutable")
            names = tuple(dict.fromkeys((*symbols, *benchmarks)))
            if not symbols or len(names) > 200:
                raise DataIntegrityError("DAT-05: batch requires 1 through 200 symbols")
            for symbol in names:
                validate_symbol(symbol)
            now = ensure_utc(self.reader.clock.now())
            tail = _eligible_session(self.calendar, now, self.delay)
            _validate_daily_window(start, tail)
            first = start
            while not self.calendar.is_session(first):
                first += timedelta(days=1)
            known_actions: frozenset[tuple[str, date]] = frozenset()
            if corporate_actions is not None:
                from backend.data.corporate_actions import CorporateActionsResult

                actions = CorporateActionsResult.model_validate(corporate_actions)
                if actions.fetched_at > now:
                    raise DataIntegrityError("DAT-10: corporate actions are future evidence")
                known_actions = actions.known_actions
            await self.reader.run(
                partial(self._invalidate_splits, corporate_actions, now), budget_request=False
            )
            cache = await self.reader.run(
                partial(self._cache, names, now, adjustment), budget_request=False
            )
            snapshots: list[tuple[str, tuple[Bar, ...]]] = []
            groups: dict[date, list[str]] = {}
            for symbol in names:
                present = sorted(day for day in cache[symbol] if first <= day <= tail)
                cursor = first
                for day in present:
                    if day != cursor:
                        raise DataIntegrityError("DAT-05: cached session coverage has a gap")
                    cursor = self.calendar.add_sessions(day, 1)
                if cursor <= tail:
                    groups.setdefault(cursor, []).append(symbol)
            for missing_start, group in sorted(groups.items()):
                # VERIFY: pinned alpaca-py 0.44.0 get_stock_bars paginates
                # GET /v2/stocks/bars; every page enters the transport budget hook.
                # https://docs.alpaca.markets/us/reference/stockbars
                request = StockBarsRequest(
                    symbol_or_symbols=group,
                    start=datetime.combine(missing_start, datetime_time.min, tzinfo=NEW_YORK),
                    end=min(
                        self.calendar.session_close(tail),
                        now - timedelta(seconds=self.sip_lag_seconds),
                    ),
                    timeframe=TimeFrame.Day,
                    feed=DataFeed.SIP,
                    adjustment=Adjustment(adjustment.lower()),
                )
                response = await self.reader.run(
                    partial(self.client.get_stock_bars, request),
                    budget_request=False,
                )
                if not isinstance(response, Mapping) or set(response) != set(group):
                    raise DataIntegrityError("DAT-05: batch response symbols differ from request")
                for symbol in group:
                    bars = await self.reader.run(
                        partial(
                            self._parse_completed,
                            symbol,
                            response[symbol],
                            missing_start,
                            tail,
                            now,
                        ),
                        budget_request=False,
                    )
                    snapshots.append((symbol, bars))
                    cache[symbol].update((bar.session_date, bar) for bar in bars)
            entries = tuple(
                SymbolBars(
                    symbol=symbol,
                    adjustment=adjustment,
                    bars=tuple(
                        cache[symbol][day] for day in sorted(cache[symbol]) if first <= day <= tail
                    ),
                    data_sha256=_bars_digest(
                        tuple(
                            cache[symbol][day]
                            for day in sorted(cache[symbol])
                            if first <= day <= tail
                        )
                    )[0],
                )
                for symbol in names
            )
            validated = await self.reader.run(
                partial(self._store, tuple(snapshots), entries, now, known_actions, adjustment),
                budget_request=False,
            )
            return BatchBars(as_of=now, through=tail, entries=validated)
        except Exception as error:
            await self.reader.halt(error)
            if isinstance(error, SafetyError):
                raise error from None
            raise DataIntegrityError(
                "DAT-05: batch data cannot establish completed evidence"
            ) from None

    def _quality_evidence(
        self, entries: tuple[SymbolBars, ...], known_splits: frozenset[tuple[str, date]]
    ) -> tuple[SymbolBars, ...]:
        self.reader.ensure_active()
        self._status._reload_symbol_status()
        by_key = {(entry.symbol, entry.adjustment): entry for entry in entries}
        for symbol in sorted({entry.symbol for entry in entries}):
            raw, split = by_key[(symbol, "RAW")].bars, by_key[(symbol, "SPLIT")].bars
            bad = tuple(bar.session_date for bar in raw) != tuple(bar.session_date for bar in split)
            with localcontext() as context:
                context.prec = 256
                previous_raw, previous_split = raw[0].close, split[0].close
                for left, right in zip(raw, split, strict=True):
                    if any(
                        native * right.close != adjusted * left.close
                        for native, adjusted in zip(
                            (left.open, left.high, left.low),
                            (right.open, right.high, right.low),
                            strict=True,
                        )
                    ):
                        bad = True
                    if (
                        left.close * previous_split != right.close * previous_raw
                        and (symbol, left.session_date) not in known_splits
                    ):
                        bad = True
                    previous_raw, previous_split = left.close, right.close
            if bad:
                self._status.mark_suspect(
                    symbol, "DQ-03: split/raw ratio lacks known split evidence"
                )
        return tuple(
            SymbolBars.model_validate(
                entry.model_copy(
                    update={
                        "status": MarketStatus.SUSPECT
                        if entry.symbol in self._status._suspect
                        else entry.status
                    }
                )
            )
            for entry in entries
        )

    async def completed_daily_evidence(
        self,
        symbols: tuple[str, ...],
        start: date,
        *,
        benchmarks: tuple[str, ...] = ("SPY",),
        corporate_actions: CorporateActionsResult | None = None,
    ) -> BatchBars:
        """DQ-01/03: SPLIT signals, ALL comparisons, RAW audit; three shared SDK batches."""
        try:
            batches = tuple(
                [
                    await self.completed_daily_bars(
                        symbols,
                        start,
                        benchmarks=benchmarks,
                        corporate_actions=corporate_actions,
                        adjustment=adjustment,
                    )
                    for adjustment in ("RAW", "SPLIT", "ALL")
                ]
            )
            if len({batch.through for batch in batches}) != 1:
                raise DataIntegrityError(
                    "DQ-03: adjustment fetches span different completed sessions"
                )
            known = frozenset(
                (action.symbol, action.effective_date)
                for action in (() if corporate_actions is None else corporate_actions.actions)
                if action.kind in {"forward_splits", "reverse_splits"}
            )
            entries = await self.reader.run(
                partial(
                    self._quality_evidence,
                    tuple(entry for batch in batches for entry in batch.entries),
                    known,
                ),
                budget_request=False,
            )
            return BatchBars(
                as_of=max(batch.as_of for batch in batches),
                through=batches[0].through,
                entries=entries,
            )
        except Exception as error:
            await self.reader.halt(error)
            if isinstance(error, SafetyError):
                raise error from None
            raise DataIntegrityError("DQ-03: adjustment evidence is unverifiable") from None

    def _latest_market(self, symbol: str, batch: BatchBars, now: datetime) -> MarketContext:
        """DAT-01/02/05: quote/trade and ADV use the same validated completed batch."""
        from alpaca.data.enums import DataFeed
        from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest

        self.reader.ensure_active()
        bars = batch.for_symbol(symbol)
        if len(bars) < 20:
            raise DataIntegrityError("DAT-02: completed batch lacks ADV20 history")
        complete = bars[-20:]
        for left, right in zip(complete, complete[1:], strict=False):
            if self.calendar.add_sessions(left.session_date, 1) != right.session_date:
                raise DataIntegrityError("DAT-02: batch ADV exchange session is missing")
        # VERIFY: pinned alpaca-py 0.44.0 raw_data=True mappings are exercised
        # by installed-SDK tests; these are GET /v2/stocks/{quotes,trades}/latest.
        # https://alpaca.markets/sdks/python/api_reference/data/stock/historical.html
        quote = self.client.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=[symbol], feed=DataFeed.IEX)
        )
        trade = self.client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=[symbol], feed=DataFeed.IEX)
        )
        if (
            not isinstance(quote, Mapping)
            or not isinstance(trade, Mapping)
            or set(quote) != {symbol}
            or set(trade) != {symbol}
            or not isinstance(quote[symbol], Mapping)
            or not isinstance(trade[symbol], Mapping)
        ):
            raise DataIntegrityError("DAT-02: quote/trade symbol differs from request")
        q, t = quote[symbol], trade[symbol]
        completed_at = ensure_utc(self.reader.clock.now())
        if completed_at < now or batch.through != _eligible_session(
            self.calendar, completed_at, self.delay
        ):
            raise DataIntegrityError(
                "DAT-01/02: clock or completed session changed during quote read"
            )
        now = completed_at
        bid, ask = _provider_money(q["bp"]), _provider_money(q["ap"])
        if ask < bid:
            raise DataIntegrityError("DAT-02: invalid bid/ask")
        quote_time = datetime.fromisoformat(str(q["t"]).replace("Z", "+00:00"))
        timestamp = datetime.fromisoformat(str(t["t"]).replace("Z", "+00:00"))
        if ensure_utc(quote_time) > now or ensure_utc(timestamp) > now:
            raise DataIntegrityError("DAT-02: future quote/trade")
        with localcontext() as context:
            context.prec = max(50, max(len(str(bar.volume)) for bar in complete) + 30)
            adv = (
                sum((bar.close * bar.volume for bar in complete), Decimal(0)) / Decimal(20)
            ).quantize(Decimal("0.000001"), rounding=ROUND_FLOOR)
        self._status._reload_symbol_status()
        status = batch.status_for(symbol)
        if symbol in self._status._suspect:
            status = MarketStatus.SUSPECT
        result = MarketContext(
            last_price=_provider_money(t["p"]),
            last_price_ts=min(timestamp, quote_time),
            adv20_usd=adv,
            status=status,
        )
        validate_quote(result, now, self.settings, self.calendar)
        self.reader.ensure_active()
        return result

    async def latest_market(self, symbol: str, batch: BatchBars) -> MarketContext:
        """DAT-08: public IEX reads share the bucket and bounded worker admission."""
        try:
            self.reader.bind_policy(self.settings, self.ledger)
            validate_symbol(symbol)
            batch = BatchBars.model_validate(batch)
            now = ensure_utc(self.reader.clock.now())
            if (
                batch.as_of > now
                or batch.through != _eligible_session(self.calendar, now, self.delay)
                or any(bar.timestamp > batch.as_of for entry in batch.entries for bar in entry.bars)
            ):
                raise DataIntegrityError("DAT-01/02: quote requires the current completed batch")
            return await self.reader.run(partial(self._latest_market, symbol, batch, now))
        except Exception as error:
            await self.reader.halt(error)
            if isinstance(error, SafetyError):
                raise error from None
            raise DataIntegrityError(
                "DAT-02: async quote/trade cannot establish evidence"
            ) from None
