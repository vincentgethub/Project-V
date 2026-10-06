"""R-05/R-07: isolated clocks, databases and environment; no real dotenv."""

import asyncio
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_socket
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import create_database, create_schema


def pytest_addoption(parser: pytest.Parser) -> None:
    """R-07: real paper credentials are read only from an explicitly named file."""
    parser.addoption(
        "--paper-integration-env-file",
        default=None,
        help="Explicit private paper-only configuration file; integration only",
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
        "SECRET_",
        "LOG_",
        "TG_",
        "ANCHOR_",
        "HEALTHCHECK_",
        "SEC_",
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
def engine(tmp_path: Path) -> Iterator[Engine]:
    """R-02: each test gets an independent on-disk SQLite ledger."""
    database = create_database(f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    create_schema(database)
    yield database
    database.dispose()
