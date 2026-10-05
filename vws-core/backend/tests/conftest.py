"""R-05/R-07: isolated clocks, databases and environment; no real dotenv."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import create_database, create_schema


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-07: settings tests are independent of broker/Plaid credentials."""
    import os

    prefixes = (
        "MAX_",
        "MIN_",
        "DD_",
        "DAILY_",
        "STOP_",
        "SECTOR_",
        "THEME_",
        "PRICE_",
        "STALE_",
        "GAP_",
        "CHECKING_",
        "RESERVED_",
        "LIQUIDITY_",
        "WASH_",
        "DAY_",
        "BROKER_",
        "ALPACA_",
        "PLAID_",
        "PAPER_",
        "LIVE_",
        "DB_",
        "FERNET_",
        "LLM_",
        "TELEGRAM_",
        "NEWSAPI_",
        "EARNINGS_",
        "ALERT_",
        "PROPOSAL_",
        "ENABLE_",
        "SCAN_",
        "OFFHOURS_",
        "SCHEDULER_",
    )
    for name in tuple(os.environ):
        if name.upper().startswith(prefixes):
            monkeypatch.delenv(name)
    # This explicit synthetic value never attests to the owner's broker account.
    monkeypatch.setenv("BROKER_ACCOUNT_TYPE", "CASH")


@pytest.fixture
def clock() -> FrozenClock:
    """R-05: regular XNYS hours on a fixed ordinary session."""
    return FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """R-02: each test gets an independent on-disk SQLite ledger."""
    database = create_database(f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    create_schema(database)
    yield database
    database.dispose()
