"""DAT-12: strict local broker CSVs with explicit restrictions and order proof."""

from __future__ import annotations

import csv
import io
import os
import re
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    ProviderError,
    SafetyError,
    StaleDataError,
)
from backend.core.money import decimal_money, validate_cent_price
from backend.data.broker_state import MarksProvider
from backend.data.data_layer import validate_quote
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import (
    AccountFlags,
    AccountType,
    MarketContext,
    MarketStatus,
    OpenOrder,
    PortfolioSnapshot,
    Position,
    validate_symbol,
)

MarketContextProvider = Callable[[str, datetime], MarketContext]
AccountFlagsProvider = Callable[[datetime], AccountFlags | None]
PendingOrdersProvider = Callable[[datetime], tuple[OpenOrder, ...]]
_MAX_CSV_BYTES = 1_048_576
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NEW_YORK = ZoneInfo("America/New_York")
_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_QUANTITY = re.compile(r"^(?:0|[1-9][0-9]*)$")


class ManualCSVBrokerState:
    """DAT-12/AX-15: MANUAL-only read projection, never an assumed clean account.

    CSVs contain holdings and cash, not account restriction or pending-order
    proof. The latter must come from explicit fresh injected attestations.
    Missing pending-order evidence prevents a complete snapshot. Missing flags
    remain None, causing ReadBoundary to fail closed. Current prices and equity
    baselines come from verified injected providers, never average cost guesses.
    """

    def __init__(
        self,
        config: Settings,
        clock: Clock,
        calendar: MarketCalendar,
        marks_provider: MarksProvider,
        positions_path: Path,
        cash_path: Path,
        *,
        account_id: str,
        known_symbols: frozenset[str],
        market_context_provider: MarketContextProvider,
        flags_provider: AccountFlagsProvider | None = None,
        pending_orders_provider: PendingOrdersProvider | None = None,
    ) -> None:
        """DAT-12: pin the account and reject automatic execution composition."""
        try:
            values = config.model_dump(mode="python")
            if (
                not config.telegram_allowed_user_ids
                and "telegram_allowed_user_ids" not in config.model_fields_set
            ):
                values.pop("telegram_allowed_user_ids")
            self._config = Settings.model_validate(values)
            if (
                self._config.execution_mode != "MANUAL"
                or self._config.broker_state_source != "MANUAL_CSV"
            ):
                raise ValueError("manual CSV source requires MANUAL mode and MANUAL_CSV selection")
            if (
                not isinstance(account_id, str)
                or not account_id.strip()
                or account_id != account_id.strip()
                or len(account_id) > 128
            ):
                raise ValueError("a pinned manual account identifier is required")
            if not isinstance(known_symbols, frozenset) or not known_symbols:
                raise ValueError("manual positions need an immutable symbol allowlist")
            for symbol in known_symbols:
                validate_symbol(symbol)
            for callback in (marks_provider, market_context_provider):
                if not callable(callback):
                    raise ValueError("manual projection requires explicit verified providers")
            if any(
                value is not None and not callable(value)
                for value in (flags_provider, pending_orders_provider)
            ):
                raise ValueError("account attestations must be explicit read providers")
            self._clock, self._calendar, self._marks = clock, calendar, marks_provider
            self._positions_path, self._cash_path = Path(positions_path), Path(cash_path)
            self._account_id, self._known = account_id, known_symbols
            self._market = market_context_provider
            self._flags, self._pending = flags_provider, pending_orders_provider
            self.last_flags: AccountFlags | None = None
        except Exception:
            raise ConfigurationError(
                "DAT-12: manual broker configuration cannot be verified"
            ) from None

    def _active_session(self, instant: datetime) -> datetime:
        """DAT-12: staleness advances at actual XNYS opens, not calendar midnight."""
        day = instant.astimezone(_NEW_YORK).date()
        if self._calendar.is_session(day) and instant >= self._calendar.session_open(day):
            return self._calendar.session_open(day)
        return self._calendar.session_open(self._calendar.last_completed_session(instant))

    def _file(self, path: Path, columns: frozenset[str], instant: datetime) -> list[dict[str, str]]:
        """DAT-12: reject future/old/symlink files and concurrent partial edits."""
        if path.is_symlink():
            raise DataIntegrityError("DAT-12: manual broker CSV must not be a symbolic link")
        try:
            with path.open("rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_CSV_BYTES:
                    raise DataIntegrityError("DAT-12: manual broker CSV is invalid or oversized")
                raw = handle.read(_MAX_CSV_BYTES + 1)
                after = os.fstat(handle.fileno())
            observed_path = path.stat()
            if len(raw) > _MAX_CSV_BYTES or (
                before.st_ino,
                before.st_dev,
                before.st_size,
                before.st_mtime_ns,
            ) != (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
                raise DataIntegrityError("DAT-12: manual broker CSV changed during the read")
            if path.is_symlink() or (
                observed_path.st_ino,
                observed_path.st_dev,
                observed_path.st_size,
                observed_path.st_mtime_ns,
            ) != (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns):
                raise DataIntegrityError("DAT-12: manual broker CSV path changed during the read")
            modified = _EPOCH + timedelta(microseconds=after.st_mtime_ns // 1000)
            if modified > instant:
                raise DataIntegrityError(
                    "DAT-12: manual broker CSV modification time is in the future"
                )
            current = self._active_session(instant).date()
            previous = self._calendar.previous_sessions(current, 1)[0]
            if self._active_session(modified).date() < previous:
                raise StaleDataError("DAT-12: manual broker CSV is older than one XNYS session")
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
            if (
                reader.fieldnames is None
                or len(reader.fieldnames) != len(columns)
                or set(reader.fieldnames) != columns
            ):
                raise DataIntegrityError("DAT-12: manual broker CSV headers are invalid")
            result: list[dict[str, str]] = []
            for row in reader:
                if set(row) != columns or any(
                    not isinstance(value, str) or not value for value in row.values()
                ):
                    raise DataIntegrityError("DAT-12: manual broker CSV row is incomplete")
                result.append(row)
            return result
        except SafetyError:
            raise
        except Exception:
            raise DataIntegrityError(
                "DAT-12: manual broker CSV cannot be read or verified"
            ) from None

    @staticmethod
    def _money(value: str) -> Decimal:
        """R-04: human CSV money is an exact decimal, without grouping or exponent."""
        if _NUMBER.fullmatch(value) is None:
            raise DataIntegrityError("DAT-12: manual broker CSV money is malformed")
        return decimal_money(value)

    def snapshot(self, now: datetime) -> PortfolioSnapshot:
        """DAT-12: complete fresh evidence or a typed failure, never invented orders."""
        self.last_flags = None
        try:
            instant = ensure_utc(now)
            local = ensure_utc(self._clock.now())
            if abs(instant - local) > timedelta(seconds=self._config.max_clock_skew_seconds):
                raise DataIntegrityError("DAT-12: manual broker read time differs from the clock")
            raw_positions = self._file(
                self._positions_path, frozenset({"symbol", "qty", "avg_cost"}), instant
            )
            raw_cash = self._file(self._cash_path, frozenset({"cash", "settled_cash"}), instant)
            if len(raw_cash) != 1:
                raise DataIntegrityError("DAT-12: manual cash CSV requires exactly one row")
            cash, settled = (self._money(raw_cash[0][field]) for field in ("cash", "settled_cash"))
            if cash >= 0 and settled > cash:
                raise DataIntegrityError("DAT-12: settled cash cannot exceed total cash")
            positions: dict[str, Position] = {}
            for row in raw_positions:
                symbol = validate_symbol(row["symbol"])
                if symbol not in self._known or symbol in positions:
                    raise DataIntegrityError(
                        "DAT-12: manual position symbol is duplicate or not allowlisted"
                    )
                if _QUANTITY.fullmatch(row["qty"]) is None or len(row["qty"]) > 12:
                    raise DataIntegrityError(
                        "DAT-12: manual position quantity must be nonnegative whole shares"
                    )
                quantity = int(row["qty"])
                cost = validate_cent_price(self._money(row["avg_cost"]))
                market = MarketContext.model_validate(self._market(symbol, instant))
                validate_quote(market, instant, self._config, self._calendar)
                if market.status != MarketStatus.OK:
                    raise DataIntegrityError("DAT-12: manual position valuation is suspect")
                positions[symbol] = Position(
                    qty=quantity, avg_cost=cost, last_price=market.last_price
                )
            if self._pending is None:
                raise DataIntegrityError(
                    "DAT-12: pending orders are unavailable; no complete manual snapshot"
                )
            pending = self._pending(instant)
            if type(pending) is not tuple:
                raise DataIntegrityError("DAT-12: pending-order attestation must be immutable")
            orders = tuple(OpenOrder.model_validate(order) for order in pending)
            if any(order.symbol not in self._known for order in orders):
                raise DataIntegrityError(
                    "DAT-12: pending-order attestation includes an unknown symbol"
                )
            flags = None if self._flags is None else self._flags(instant)
            checked_flags = None if flags is None else AccountFlags.model_validate(flags)
            with localcontext() as context:
                context.prec = 80
                equity = decimal_money(
                    cash + sum((position.value for position in positions.values()), Decimal(0))
                )
            high_water, day_start = self._marks(equity, instant)
            result = PortfolioSnapshot(
                account_id=self._account_id,
                account_type=AccountType(self._config.broker_account_type),
                as_of=instant,
                equity=equity,
                cash=cash,
                settled_cash=settled,
                positions=positions,
                open_orders=orders,
                high_water_mark=high_water,
                day_start_equity=day_start,
            )
            self.last_flags = checked_flags
            return result
        except SafetyError:
            raise
        except (ValueError, TypeError):
            raise DataIntegrityError(
                "DAT-12: manual broker state failed schema validation"
            ) from None
        except Exception:
            raise ProviderError("DAT-12: manual broker state cannot be verified") from None
