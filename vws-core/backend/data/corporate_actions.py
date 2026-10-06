"""DAT-10: public corporate-action evidence, never a guessed gap exemption."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal, Protocol, Self, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from alpaca.data.historical.corporate_actions import CorporateActionsClient
from alpaca.data.requests import CorporateActionsRequest
from pydantic import Field, model_validator

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError, ProviderError, SafetyError
from backend.core.ledger import Ledger
from backend.data.async_reader import AsyncReadExecutor
from backend.data.broker_state import configure_alpaca_transport
from backend.domain.models import (
    FrozenModel,
    ProviderStatus,
    SessionDate,
    Symbol,
    UTCDateTime,
    validate_symbol,
)

_NEW_YORK = ZoneInfo("America/New_York")
_MAX_ACTIONS = 1000
# Verified against pinned alpaca-py 0.44.0 models and the official /v1 endpoint.
# start/end filter process_date, which is deliberately distinct from price-effective dates.
_PRICE_FIELDS: dict[str, tuple[str, str]] = {
    "forward_splits": ("symbol", "ex_date"),
    "reverse_splits": ("symbol", "ex_date"),
    "stock_dividends": ("symbol", "ex_date"),
    "cash_dividends": ("symbol", "ex_date"),
    "spin_offs": ("source_symbol", "ex_date"),
    "rights_distributions": ("source_symbol", "ex_date"),
    "unit_splits": ("old_symbol", "effective_date"),
    "cash_mergers": ("acquiree_symbol", "effective_date"),
    "stock_mergers": ("acquiree_symbol", "effective_date"),
    "stock_and_cash_mergers": ("acquiree_symbol", "effective_date"),
}
_NO_PRICE_DATE = frozenset({"redemptions", "name_changes", "worthless_removals"})


class ReadOnlyCorporateActionsClient(Protocol):
    def get_corporate_actions(self, request_params: CorporateActionsRequest) -> object:
        """Read public actions only; no order/funding capability is exposed."""
        ...


class CorporateActionEvidence(FrozenModel):
    """Only an explicit ex/effective date can explain this symbol's overnight gap."""

    provider_id: UUID
    kind: str = Field(strict=True, min_length=1, max_length=40)
    symbol: Symbol
    effective_date: SessionDate
    process_date: SessionDate
    effective_date_field: Literal["ex_date", "effective_date"]

    @model_validator(mode="after")
    def valid_kind(self) -> Self:
        fields = _PRICE_FIELDS.get(self.kind)
        if fields is None or fields[1] != self.effective_date_field:
            raise ValueError("action lacks a verified price-effective field")
        return self


class CorporateActionsResult(FrozenModel):
    """Explicit query coverage/fetch time; unavailable evidence explains no gaps."""

    provider: Literal["ALPACA", "FAKE"]
    status: ProviderStatus
    fetched_at: UTCDateTime
    symbols: tuple[Symbol, ...] = Field(min_length=1, max_length=1000)
    process_start: SessionDate
    process_end: SessionDate
    actions: tuple[CorporateActionEvidence, ...] = Field(default=(), max_length=_MAX_ACTIONS)
    reason: str = Field(strict=True, min_length=1, max_length=280)

    @model_validator(mode="after")
    def valid_evidence(self) -> Self:
        today = self.fetched_at.astimezone(_NEW_YORK).date()
        if (
            len(set(self.symbols)) != len(self.symbols)
            or self.process_start > self.process_end
            or self.process_end > today
        ):
            raise ValueError("corporate-action query bounds are unverifiable")
        if self.status != ProviderStatus.OK and self.actions:
            raise ValueError("unavailable corporate actions cannot explain a gap")
        if len({action.provider_id for action in self.actions}) != len(self.actions):
            raise ValueError("corporate action IDs must be unique")
        for action in self.actions:
            if (
                action.symbol not in self.symbols
                or not self.process_start <= action.process_date <= self.process_end
                or action.effective_date > today
            ):
                raise ValueError("corporate-action evidence is unbound or future")
        return self

    @property
    def known_actions(self) -> frozenset[tuple[str, date]]:
        """DAT-02: availability never becomes a blanket 'known corporate action'."""
        checked = CorporateActionsResult.model_validate(self)
        return frozenset((item.symbol, item.effective_date) for item in checked.actions)


class CorporateActionsProvider(Protocol):
    async def fetch(
        self, symbols: tuple[str, ...], start: date, end: date
    ) -> CorporateActionsResult:
        """Fetch by process-date interval, preserving exact action provenance."""
        ...


def _bounds(symbols: tuple[str, ...], start: date, end: date, clock: Clock) -> datetime:
    try:
        now = ensure_utc(clock.now())
        if (
            not isinstance(symbols, tuple)
            or not 1 <= len(symbols) <= 1000
            or len(set(symbols)) != len(symbols)
        ):
            raise ValueError("bounded unique symbols required")
        for symbol in symbols:
            validate_symbol(symbol)
        if (
            type(start) is not date
            or type(end) is not date
            or start > end
            or end > now.astimezone(_NEW_YORK).date()
        ):
            raise ValueError("explicit completed date interval required")
        return now
    except Exception:
        raise DataIntegrityError("DAT-10: invalid corporate-action query") from None


def _date(value: object) -> date:
    try:
        if type(value) is date:
            return value
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("explicit date required")
        return date.fromisoformat(value)
    except Exception:
        raise DataIntegrityError("DAT-10: corporate-action date is unverifiable") from None


def _unavailable(
    provider: Literal["ALPACA", "FAKE"],
    symbols: tuple[str, ...],
    start: date,
    end: date,
    now: datetime,
    reason: str,
) -> CorporateActionsResult:
    return CorporateActionsResult(
        provider=provider,
        status=ProviderStatus.UNAVAILABLE,
        fetched_at=now,
        symbols=symbols,
        process_start=start,
        process_end=end,
        reason=reason,
    )


class AlpacaCorporateActionsProvider:
    """DAT-10/06/08: pinned SDK via the shared async read boundary and GET hook."""

    def __init__(
        self,
        settings: Settings,
        reader: AsyncReadExecutor,
        ledger: Ledger,
        *,
        client: ReadOnlyCorporateActionsClient | None = None,
    ) -> None:
        reader.bind_policy(settings, ledger)
        payload = settings.model_dump()
        if (
            not settings.telegram_allowed_user_ids
            and "telegram_allowed_user_ids" not in settings.model_fields_set
        ):
            payload.pop("telegram_allowed_user_ids")
        checked = Settings.model_validate(payload)
        self.reader, self.clock = reader, ledger.clock
        # VERIFY: https://alpaca.markets/sdks/python/api_reference/data/corporate_actions/historical.html
        # This client is not exported from alpaca.data.historical in pinned 0.44.0.
        try:
            self.client: ReadOnlyCorporateActionsClient = (
                client
                if client is not None
                else CorporateActionsClient(
                    api_key=checked.broker_api_key.get_secret_value(),
                    secret_key=checked.broker_secret_key.get_secret_value(),
                    raw_data=True,
                )
            )
            configure_alpaca_transport(
                self.client,
                checked.request_timeout_seconds,
                before_request=reader.before_request,
            )
        except SafetyError:
            raise
        except Exception:
            raise ProviderError(
                "DAT-10: public actions SDK could not be safely initialized"
            ) from None

    async def fetch(
        self, symbols: tuple[str, ...], start: date, end: date
    ) -> CorporateActionsResult:
        now = _bounds(symbols, start, end, self.clock)
        # VERIFY: https://docs.alpaca.markets/us/reference/corporateactions-1
        request = CorporateActionsRequest(
            symbols=list(symbols), start=start, end=end, limit=_MAX_ACTIONS
        )
        try:
            raw = await self.reader.run(
                lambda: self.client.get_corporate_actions(request), budget_request=False
            )
        except ProviderError:
            return _unavailable(
                "ALPACA",
                symbols,
                start,
                end,
                now,
                "Corporate actions unavailable; unexplained gaps remain SUSPECT",
            )
        return await self.reader.run(
            lambda: self._parse(raw, symbols, start, end, now), budget_request=False
        )

    def _parse(
        self, raw: object, symbols: tuple[str, ...], start: date, end: date, now: datetime
    ) -> CorporateActionsResult:
        if not isinstance(raw, Mapping) or any(not isinstance(key, str) for key in raw):
            raise DataIntegrityError("DAT-10: corporate-action response is malformed")
        actions: dict[UUID, CorporateActionEvidence] = {}
        count = 0
        for kind, rows in raw.items():
            if not isinstance(rows, list):
                raise DataIntegrityError("DAT-10: corporate-action records must be bounded arrays")
            count += len(rows)
            if count > _MAX_ACTIONS:
                raise DataIntegrityError("DAT-10: corporate-action response exceeds its boundary")
            if not rows:
                continue
            if kind not in _PRICE_FIELDS:
                reason = (
                    "Actions lack verified price-effective dates; unexplained gaps remain SUSPECT"
                    if kind in _NO_PRICE_DATE
                    else "Unsupported action type; unexplained gaps remain SUSPECT"
                )
                return _unavailable("ALPACA", symbols, start, end, now, reason)
            symbol_field, date_field = _PRICE_FIELDS[kind]
            for row in rows:
                if not isinstance(row, Mapping):
                    raise DataIntegrityError("DAT-10: corporate-action record is malformed")
                if row.get(date_field) is None:
                    return _unavailable(
                        "ALPACA",
                        symbols,
                        start,
                        end,
                        now,
                        "Incomplete action date; unexplained gaps remain SUSPECT",
                    )
                try:
                    raw_id, raw_symbol = row.get("id"), row.get(symbol_field)
                    if not isinstance(raw_id, (str, UUID)) or not isinstance(raw_symbol, str):
                        raise ValueError("action identity and symbol are required")
                    evidence = CorporateActionEvidence(
                        provider_id=UUID(raw_id) if isinstance(raw_id, str) else raw_id,
                        kind=kind,
                        symbol=raw_symbol,
                        effective_date=_date(row[date_field]),
                        process_date=_date(row.get("process_date")),
                        effective_date_field=cast(Literal["ex_date", "effective_date"], date_field),
                    )
                except Exception:
                    raise DataIntegrityError("DAT-10: invalid corporate-action evidence") from None
                previous = actions.get(evidence.provider_id)
                if previous is not None and previous != evidence:
                    raise DataIntegrityError("DAT-10: conflicting corporate-action identity")
                actions[evidence.provider_id] = evidence
        try:
            return CorporateActionsResult(
                provider="ALPACA",
                status=ProviderStatus.OK,
                fetched_at=now,
                symbols=symbols,
                process_start=start,
                process_end=end,
                actions=tuple(actions.values()),
                reason="Only explicit symbol/ex-date or effective-date evidence explains gaps",
            )
        except Exception:
            raise DataIntegrityError(
                "DAT-10: corporate-action coverage is unbound or future"
            ) from None


class FakeCorporateActionsProvider:
    """DAT-10: deterministic fake with the same fail-closed coverage validation."""

    def __init__(
        self,
        clock: Clock,
        actions: tuple[CorporateActionEvidence, ...] = (),
        *,
        available: bool = True,
    ) -> None:
        if (
            type(available) is not bool
            or not isinstance(actions, tuple)
            or len(actions) > _MAX_ACTIONS
        ):
            raise ConfigurationError("fake corporate actions require a bounded immutable fixture")
        self.clock, self.actions, self.available = clock, actions, available

    async def fetch(
        self, symbols: tuple[str, ...], start: date, end: date
    ) -> CorporateActionsResult:
        now = _bounds(symbols, start, end, self.clock)
        if not self.available:
            return _unavailable(
                "FAKE",
                symbols,
                start,
                end,
                now,
                "Synthetic actions unavailable; unexplained gaps remain SUSPECT",
            )
        try:
            checked = tuple(CorporateActionEvidence.model_validate(item) for item in self.actions)
            if any(item.effective_date > now.astimezone(_NEW_YORK).date() for item in checked):
                raise ValueError("future action evidence")
            return CorporateActionsResult(
                provider="FAKE",
                status=ProviderStatus.OK,
                fetched_at=now,
                symbols=symbols,
                process_start=start,
                process_end=end,
                actions=tuple(
                    item
                    for item in checked
                    if item.symbol in symbols and start <= item.process_date <= end
                ),
                reason="Synthetic explicit effective dates; no guessed exemptions",
            )
        except Exception:
            raise DataIntegrityError(
                "DAT-10: invalid synthetic corporate-action evidence"
            ) from None
