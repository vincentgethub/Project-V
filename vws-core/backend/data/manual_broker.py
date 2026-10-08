"""DAT-12: disabled by owner decision, October 8 2026; no manual file reads."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from backend.core.clock import Clock
from backend.core.config import MANUAL_CSV_DISABLED_MESSAGE, Settings
from backend.core.errors import ConfigurationError
from backend.data.broker_state import MarksProvider
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import AccountFlags, MarketContext, OpenOrder, PortfolioSnapshot

MarketContextProvider = Callable[[str, datetime], MarketContext]
AccountFlagsProvider = Callable[[datetime], AccountFlags | None]
PendingOrdersProvider = Callable[[datetime], tuple[OpenOrder, ...]]


class ManualCSVBrokerState:
    """Disabled compatibility boundary, including direct component use."""

    last_flags: AccountFlags | None = None

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
        raise ConfigurationError(MANUAL_CSV_DISABLED_MESSAGE)

    def snapshot(self, now: datetime) -> PortfolioSnapshot:
        """Refuse even a caller that bypassed the constructor."""
        raise ConfigurationError(MANUAL_CSV_DISABLED_MESSAGE)
