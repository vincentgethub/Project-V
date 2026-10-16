"""R-05/R-07: isolated clocks, databases and environment; no real dotenv."""

import asyncio
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import cast

import pytest
import pytest_socket
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import create_database, create_schema
from backend.data import market_calendar
from backend.data.market_calendar import CalendarFactory, MarketCalendar


@pytest.fixture(scope="session", autouse=True)
def pristine_calendars() -> Iterator[None]:
    """Cache immutable schedules only within this pytest invocation.

    Every constructor still returns a distinct instance. Custom providers and
    invalid arguments always exercise the real constructor. Session teardown
    restores it and discards all cached values before another mutant runs.
    """
    original = MarketCalendar.__init__
    official = market_calendar._official_calendar
    instant = market_calendar._calendar_instant
    argument = market_calendar._date_argument
    schedules: dict[
        tuple[str, date, date],
        tuple[tuple[date, ...], tuple[datetime, ...], tuple[datetime, ...]],
    ] = {}

    def initialize(
        self: MarketCalendar,
        *,
        name: str = "XNYS",
        start: date = date(1990, 1, 1),
        end: date = date(2030, 12, 31),
        calendar_factory: CalendarFactory | None = None,
    ) -> None:
        cacheable = (
            name == "XNYS"
            and type(start) is date
            and type(end) is date
            and start < end
            and calendar_factory is None
            and market_calendar._official_calendar is official
            and market_calendar._calendar_instant is instant
            and market_calendar._date_argument is argument
        )
        key = (name, start, end)
        if cacheable and key in schedules:
            self._sessions, self._opens, self._closes = schedules[key]
            return
        original(self, name=name, start=start, end=end, calendar_factory=calendar_factory)
        if cacheable:
            schedules[key] = (self._sessions, self._opens, self._closes)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(MarketCalendar, "__init__", initialize)
        yield
    schedules.clear()


@pytest.fixture(scope="session")
def pristine_schema() -> Iterator[Connection]:
    """Build a pristine in-memory schema anew for each pytest invocation."""
    template = create_database("sqlite:///:memory:")
    try:
        create_schema(template)
        with template.connect() as connection:
            yield cast(Connection, connection.connection.driver_connection)
    finally:
        template.dispose()


@pytest.fixture(scope="session")
def pristine_research_indicators() -> Iterator[
    dict[tuple[object, ...], tuple[tuple[tuple[str, str, date], str, int, str], ...]]
]:
    """DAT-05: keep serialized pure indicator seeds only within this test run.

    Tests receive fresh memos and revalidated models; no mutable memo, model,
    ledger or clock is shared. Teardown removes every seed before another mutant.
    """
    seeds: dict[tuple[object, ...], tuple[tuple[tuple[str, str, date], str, int, str], ...]] = {}
    try:
        yield seeds
    finally:
        seeds.clear()


def pytest_addoption(parser: pytest.Parser) -> None:
    """R-07: real paper credentials are read only from an explicitly named file."""
    parser.addoption(
        "--paper-integration-env-file",
        default=None,
        help="Explicit private paper-only configuration file; integration only",
    )
    parser.addoption(
        "--postgres-test-url",
        default=None,
        help="Explicit disposable loopback vws_ci database only; never owner storage",
    )
    parser.addoption(
        "--paper-cancel-order-ids",
        default=None,
        help="Explicit existing canceled paper OTO root and OCO root broker UUIDs, comma separated; read-only integration",
    )


def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    """SEC-30: create asyncio's local self-pipe, then keep test sockets blocked.

    Windows asyncio needs a local TCP socket pair during loop construction.
    No test body or coroutine runs while constructors are briefly restored.
    VERIFY: installed pytest-asyncio 1.4 plugin's loop factory hook contract.
    """

    def offline_loop() -> asyncio.AbstractEventLoop:
        pytest_socket.enable_socket()
        try:
            return asyncio.new_event_loop()
        finally:
            pytest_socket.disable_socket(allow_unix_socket=True)

    return {"offline": offline_loop}


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
        "FRED_",
        "LLM_",
        "TELEGRAM_",
        "NEWSAPI_",
        "NEWS_",
        "EARNINGS_",
        "ALERT_",
        "PROPOSAL_",
        "ENABLE_",
        "SCAN_",
        "OFFHOURS_",
        "SCHEDULER_",
        "EXECUTION_",
        "AUTO_",
        "SECRET_",
        "LOG_",
        "BACKUP_",
        "TG_",
        "ANCHOR_",
        "HEALTHCHECK_",
        "SEC_",
        "TAX_",
        "OPENAI_",
        "DISPLAY_",
    )
    for name in tuple(os.environ):
        if name.upper().startswith(prefixes):
            monkeypatch.delenv(name)
    # This explicit synthetic value never attests to the owner's broker account.
    monkeypatch.setenv("BROKER_ACCOUNT_TYPE", "CASH")


@pytest.fixture(autouse=True)
def isolated_sdk_egress_policy(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-30/31: legacy SDK fakes use an explicit allowlist and audit ledger."""
    if Path(str(request.node.fspath)).name in {
        "test_broker_state.py",
        "test_data_layer.py",
        "test_liquidity.py",
    }:
        from backend.core.ledger import Ledger
        from backend.net import http
        from backend.net.egress import EgressPolicy, build_allowlist

        engine = request.getfixturevalue("engine")
        clock = request.getfixturevalue("clock")
        monkeypatch.setattr(http, "_policy", EgressPolicy(build_allowlist(), Ledger(engine, clock)))


@pytest.fixture
def clock() -> FrozenClock:
    """R-05: regular XNYS hours on a fixed ordinary session."""
    return FrozenClock(datetime(2026, 9, 29, 15, 0, tzinfo=UTC))


@pytest.fixture
def engine(tmp_path: Path, pristine_schema: Connection) -> Iterator[Engine]:
    """R-02: each test gets an independent on-disk SQLite ledger."""
    database = create_database(f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    try:
        with database.connect() as connection:
            pristine_schema.backup(cast(Connection, connection.connection.driver_connection))
        yield database
    finally:
        database.dispose()
