"""EX-06: explicit read-only paper cancellation verification; no implicit secrets."""

from pathlib import Path
from uuid import UUID

import pytest
import pytest_socket
from alpaca.trading.client import TradingClient
from sqlalchemy import Engine

from backend.core.clock import SystemClock
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.broker_state import prepare_alpaca_client
from backend.net.egress import EgressPolicy, SDKSocketGuard, build_allowlist
from backend.net.http import configure_network
from backend.security.secrets import KeyringSecretStore
from vws.host_config import load_host_settings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_EX_06_real_paper_OTO_stop_and_OCO_sibling_cancellation(
    request: pytest.FixtureRequest,
    engine: Engine,
) -> None:
    selected = request.config.getoption("--paper-integration-env-file")
    identities = request.config.getoption("--paper-cancel-order-ids")
    if selected is None or identities is None:
        pytest.skip(
            "UNVERIFIED: explicit paper config and existing canceled OTO/OCO broker UUIDs required"
        )
    config = load_host_settings(
        Path(__file__).resolve().parents[2], Path(selected), KeyringSecretStore()
    )
    assert config.paper_trading and config.execution_mode == "AUTO_PAPER"
    ids = tuple(UUID(value.strip()) for value in identities.split(","))
    assert len(ids) == 2 and ids[0] != ids[1]
    assert config.broker_api_key.get_secret_value() and config.broker_secret_key.get_secret_value()
    # MANUAL refuses above before the isolated order module can be imported.
    from backend.execution.alpaca_executor import inspect_paper_cancel_semantics

    clock = SystemClock()
    ledger = Ledger(engine, clock)  # Disposable test ledger; never owner DB.
    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), ledger)
    configure_network(policy)
    SDKSocketGuard(policy).install()
    reader = AsyncAlpacaReader(
        clock, SystemStateStore(engine, clock, ConsoleNotifier()), plan=config.alpaca_data_plan
    )
    reader.bind_policy(config, ledger)
    client = TradingClient(
        config.broker_api_key.get_secret_value(),
        config.broker_secret_key.get_secret_value(),
        paper=True,
        raw_data=True,
    )
    prepare_alpaca_client(client, config)
    pytest_socket.enable_socket()
    try:
        oto, oco = await inspect_paper_cancel_semantics(config, reader, client, ids[0], ids[1])
        assert oto.legs[0].status == oco.legs[0].status == oco.status == "canceled"
        ledger.verify_chain()
    finally:
        await reader.aclose()
        client._session.close()
        pytest_socket.disable_socket(allow_unix_socket=True)
