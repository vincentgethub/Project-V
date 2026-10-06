"""DAT-05..12/R-07: explicit paper-only read integration, never an order call."""

from datetime import timedelta
from pathlib import Path

import pytest
import pytest_socket
from alpaca.trading.client import TradingClient
from alpaca.trading.models import TradeAccount
from sqlalchemy import Engine

from backend.core.clock import SystemClock
from backend.core.config import load_settings
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.broker_state import prepare_alpaca_client
from backend.data.data_layer import AsyncAlpacaMarketData
from backend.data.market_calendar import MarketCalendar
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist
from backend.net.http import configure_network


@pytest.mark.integration
@pytest.mark.asyncio
async def test_DAT_paper_SIP_daily_bars_and_current_account(
    request: pytest.FixtureRequest, engine: Engine
) -> None:
    """DAT-07/R-06: no implicit dotenv/keyring read; requires explicit paper keys."""
    selected = request.config.getoption("--paper-integration-env-file")
    if selected is None:
        pytest.skip("UNVERIFIED: explicit paper integration credentials not supplied")
    config = load_settings(env_file=Path(selected))
    if (
        not config.broker_api_key.get_secret_value()
        or not config.broker_secret_key.get_secret_value()
    ):
        pytest.skip("UNVERIFIED: paper keys absent from the explicitly selected configuration")
    assert config.paper_trading and config.execution_mode == "MANUAL"
    clock = SystemClock()
    ledger = Ledger(engine, clock)
    policy = EgressPolicy(build_allowlist(), ledger)
    configure_network(policy)
    SDKSocketGuard(policy).install()
    reader = AsyncAlpacaReader(
        clock, SystemStateStore(engine, clock, ConsoleNotifier()), plan=config.alpaca_data_plan
    )
    calendar = MarketCalendar()
    provider = AsyncAlpacaMarketData(config, reader, calendar, ledger)
    client = TradingClient(
        api_key=config.broker_api_key.get_secret_value(),
        secret_key=config.broker_secret_key.get_secret_value(),
        paper=True,
        raw_data=True,
    )
    prepare_alpaca_client(client, config)
    pytest_socket.enable_socket()
    try:
        account = await reader.run(client.get_account)
        assert isinstance(account, dict)
        parsed = TradeAccount.model_validate(account)
        assert parsed.currency == "USD" and str(parsed.id)
        if "account_type" in account:
            assert account["account_type"] == config.broker_account_type
        batch = await provider.completed_daily_bars(
            ("SPY",), clock.now().date() - timedelta(days=10)
        )
        assert len(batch.entries) == 1 and batch.entries[0].symbol == "SPY"
        assert batch.entries[0].bars and batch.entries[0].bars[-1].session_date == batch.through
        ledger.verify_chain()
    finally:
        client._session.close()
        pytest_socket.disable_socket(allow_unix_socket=True)
