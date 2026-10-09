"""AX-12/15/16: real pinned SDK reaches only the narrow, admitted transport."""

import json
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from alpaca.trading.client import TradingClient
from requests import ReadTimeout, Response
from requests import Session as RequestsSession

from backend.core.errors import ProviderError
from backend.core.execution_policy import ORDER_HTTP_PATH
from backend.execution.alpaca_executor import configure_execution_client
from backend.net.egress import EgressPolicy, build_allowlist
from backend.tests.test_auto_execution import AUTO, executor
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


def response(url: str, status: int, body: object | None) -> Response:
    result = Response()
    result.status_code, result.url = status, url
    result._content = b"" if body is None else json.dumps(body).encode("utf-8")
    result.__dict__["_content_consumed"] = True
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("lost_response", [False, True])
async def test_AX_12_16_real_pinned_submit_lookup_cancel_are_single_attempt_and_exact(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    lost_response: bool,
) -> None:
    h = harness
    alert = await deliver(h)
    client = TradingClient(
        api_key=h.settings.broker_api_key.get_secret_value(),
        secret_key=h.settings.broker_secret_key.get_secret_value(),
        paper=True,
        raw_data=True,
    )
    built = executor(h, cast(Any, client))
    configure_execution_client(
        client,
        h.settings,
        EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger),
        before_request=built.worker.before_request,
    )
    physical: list[tuple[str, str]] = []
    orders: dict[str, dict[str, Any]] = {}
    posts: list[dict[str, Any]] = []

    def wire(session: RequestsSession, method: str, url: str, **kwargs: Any) -> Response:
        physical.append((method, urlsplit(url).path))
        assert session.trust_env is False
        assert kwargs["verify"] is True and kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        assert 0 < kwargs["timeout"][0] <= 5 and 0 < kwargs["timeout"][1] <= 20
        assert kwargs["headers"]["APCA-API-KEY-ID"] == "TEST_ONLY_PAPER_ID"
        assert kwargs["headers"]["APCA-API-SECRET-KEY"] == "TEST_ONLY_PAPER_SECRET"
        path = urlsplit(url).path
        if method == "GET" and path == "/v2/account":
            return response(
                url,
                200,
                {
                    "id": "offline-paper",
                    "status": "ACTIVE",
                    "currency": "USD",
                    "trading_blocked": False,
                    "account_blocked": False,
                    "trade_suspended_by_user": False,
                },
            )
        if method == "GET" and path.endswith(":by_client_order_id"):
            raw = orders.get(kwargs["params"]["client_order_id"])
            return response(
                url,
                404 if raw is None else 200,
                {"code": 404, "message": "synthetic missing order"} if raw is None else raw,
            )
        if method == "POST":
            fields = kwargs["json"]
            posts.append(fields)
            assert fields["qty"].isdigit()
            assert (
                isinstance(fields["limit_price"], str)
                and len(fields["limit_price"].split(".")[1]) == 2
            )
            assert "extended_hours" not in fields
            raw = {
                **fields,
                "id": str(uuid4()),
                "status": "new",
                "filled_qty": "0",
                "submitted_at": h.clock.now().isoformat(),
                "legs": None,
            }
            raw["legs"] = [
                {
                    "id": str(uuid4()),
                    "client_order_id": "generated-" + uuid4().hex,
                    "symbol": fields["symbol"],
                    "side": "sell",
                    "type": kind,
                    "qty": fields["qty"],
                    "filled_qty": "0",
                    "status": "held",
                    "time_in_force": "gtc",
                    "order_class": "simple",
                    "submitted_at": raw["submitted_at"],
                    "legs": None,
                    **price,
                }
                for kind, price in (("limit", fields["take_profit"]), ("stop", fields["stop_loss"]))
            ]
            orders[fields["client_order_id"]] = raw
            if lost_response:
                raise ReadTimeout("synthetic server accepted; response lost")
            return response(url, 200, raw)
        if method == "DELETE":
            assert "params" not in kwargs and "json" not in kwargs
            raw = next(row for row in orders.values() if path.endswith(row["id"]))
            raw["status"] = "canceled"
            for child in raw["legs"]:
                child["status"] = "canceled"
            return response(url, 204, None)
        if method == "GET" and path == ORDER_HTTP_PATH:
            return response(url, 200, list(orders.values()))
        if method == "GET" and path == "/v2/positions":
            return response(url, 200, [])
        if method == "GET" and path.startswith(ORDER_HTTP_PATH + "/"):
            return response(
                url,
                200,
                next(
                    row
                    for parent in orders.values()
                    for row in (parent, *parent["legs"])
                    if path.endswith(row["id"])
                ),
            )
        raise AssertionError("Unexpected physical SDK route")

    monkeypatch.setattr(RequestsSession, "request", wire)
    try:
        result = await built.enter(alert.proposal_id)
        assert result.recovered_after_ambiguity is lost_response
        assert len(posts) == 1 and client._retry == 0
        built.modes.downgrade("PAUSE", actor="fixture owner")
        await built.monitor()
        assert len([method for method, _ in physical if method == "DELETE"]) == 1
        assert next(iter(orders.values()))["status"] == "canceled"
        h.state.ledger.verify_chain()
    finally:
        await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_15_sdk_endpoint_drift_is_refused_before_physical_request(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = harness
    client = TradingClient(api_key="TEST_ONLY", secret_key="TEST_ONLY", paper=True, raw_data=True)
    built = executor(h, cast(Any, client))
    configure_execution_client(
        client,
        h.settings,
        EgressPolicy(build_allowlist(mode="AUTO_PAPER"), h.state.ledger),
        before_request=built.worker.before_request,
    )
    called = False

    def wire(*args: Any, **kwargs: Any) -> Response:
        nonlocal called
        called = True
        raise AssertionError("Forbidden endpoint reached the physical transport")

    monkeypatch.setattr(RequestsSession, "request", wire)
    client._base_url = "https://api.alpaca.markets"
    try:
        with pytest.raises(ProviderError, match="destination"):
            await built._verify_account()
        assert called is False
    finally:
        await built.close()
