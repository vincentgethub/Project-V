"""Fix G-0.1: transport requires both the recorder and its failure callback."""

from typing import Any

import pytest
from alpaca.trading.client import TradingClient
from requests import Response
from requests import Session as RequestsSession

from backend.core.clock import FrozenClock
from backend.core.errors import ConfigurationError
from backend.data.async_reader import AsyncTokenBucket
from backend.execution.alpaca_executor import configure_execution_client
from backend.execution.worker import SingleAttemptWorker, TransportRecord
from backend.net.egress import EgressPolicy, build_allowlist
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_execution_transport import response
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness

harness = make_research_harness


def test_R1_setter_refuses_none_recorder(clock: FrozenClock) -> None:
    worker = SingleAttemptWorker(AsyncTokenBucket(clock))
    options: dict[str, Any] = {"recorder": None, "on_refusal_error": lambda error: None}
    with pytest.raises(ConfigurationError, match="transport recorder"):
        worker.set_transport_recorder(**options)
    assert worker._recorder is None and worker._refusal_error is None


class CountingTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        self.calls += 1
        return response(url, 200, {})


def offline_client(
    harness: Harness,
    worker: SingleAttemptWorker,
    transport: CountingTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> TradingClient:
    client = TradingClient(
        api_key="TEST_ONLY_PAPER_ID", secret_key="TEST_ONLY_PAPER_SECRET", paper=True, raw_data=True
    )

    def wire(session: RequestsSession, method: str, url: str, **kwargs: Any) -> Response:
        return transport.request(method, url, **kwargs)

    configure_execution_client(
        client,
        harness.settings,
        EgressPolicy(build_allowlist(), harness.state.ledger),
        before_request=worker.before_request,
    )
    monkeypatch.setattr(RequestsSession, "request", wire)
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_R2_unset_recorder_refuses_before_admission_and_transport(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = SingleAttemptWorker(AsyncTokenBucket(harness.clock))
    worker._refusal_error = harness.state.halt_for_error
    transport = CountingTransport()
    client = offline_client(harness, worker, transport, monkeypatch)
    caught: Exception | None = None
    try:
        try:
            await worker.attempt(lambda: client.get_order_by_client_id("vws-g01-unwired"))
        except Exception as error:
            caught = error
        assert transport.calls == 0, "an unset recorder must refuse before Session.request"
        assert isinstance(caught, ConfigurationError)
        assert worker._recorder is None
        with pytest.raises(ConfigurationError, match="transport recorder"):
            worker.before_request()
    finally:
        await worker.aclose()
        client._session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_R3_wired_worker_makes_exactly_one_request(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = SingleAttemptWorker(AsyncTokenBucket(harness.clock))
    records: list[TransportRecord] = []
    worker.set_transport_recorder(records.append, on_refusal_error=harness.state.halt_for_error)
    transport = CountingTransport()
    client = offline_client(harness, worker, transport, monkeypatch)
    try:
        result = await worker.attempt(lambda: client.get_order_by_client_id("vws-g01-wired"))
        assert result == {}
        assert transport.calls == 1, "a wired attempt must make exactly one physical request"
        assert records == []
    finally:
        await worker.aclose()
        client._session.close()
