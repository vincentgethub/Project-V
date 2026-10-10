"""Private document receipts, forged watch approvals and public card boundaries."""

from uuid import uuid4

import httpx
import pytest

from backend.core.database import Alert
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import TelegramRequest
from backend.notifications.telegram_bot import TelegramBot
from backend.ops.html_report import html_report
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor
from backend.tests.test_k_integration import Documents, snapshot
from backend.tests.test_swarm_and_callbacks import (
    Harness,
    ack,
    click,
    deliver,
    make_research_harness,
)
from backend.tests.test_telegram_flow import API, command_update, make

harness = make_research_harness


class MisboundDocument(Documents):
    def __init__(self, fault: str) -> None:
        super().__init__()
        self.fault = fault

    async def http(self, request: httpx.Request) -> httpx.Response:
        response = await super().http(request)
        if request.url.path.endswith("sendDocument"):
            payload = response.json()
            message = payload["result"]
            if self.fault == "chat":
                message["chat"]["id"] = 999
            elif self.fault == "group":
                message["chat"]["type"] = "group"
            else:
                message["message_id"] = 0
            return httpx.Response(200, json=payload)
        return response


def document_bot(h: Harness, api: Documents) -> TelegramBot:
    policy = EgressPolicy(build_allowlist(), h.state.ledger)
    token = h.settings.telegram_bot_token.get_secret_value()
    return TelegramBot(
        h.settings,
        h.state,
        h.clock,
        h.gate,
        policy,
        {},
        transport=TelegramRequest(
            token, policy, transport=httpx.MockTransport(api.http), document_chats=(123,)
        ),
        polling_transport=TelegramRequest(token, policy, transport=httpx.MockTransport(api.http)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["chat", "group", "message"])
async def test_XK_08_document_refuses_misbound_sdk_receipt(harness: Harness, fault: str) -> None:
    bot = document_bot(harness, MisboundDocument(fault))
    await bot.application.initialize()
    bot._admitted = True
    try:
        with pytest.raises(DataIntegrityError, match="identity differs"):
            await bot.document(123, html_report(snapshot(harness)))
    finally:
        await bot.application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XK_09_valid_hmac_cannot_approve_auto_watch(harness: Harness) -> None:
    h = harness
    h.request = h.request.model_copy(update={"manual_only": True})
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "FAILED" and result.text is not None and "manual only" in result.text
    assert not client.posts and h.state.current() == SystemState.RUNNING
    assert h.state.ledger.current_alert_status(alert.id) == "SENT"
    bot = make(h, API())
    # Details and annotation edits must also retain the read-only keyboard.
    assert await bot._proposal_is_auto(alert.proposal_id)


def test_XK_09_unknown_card_has_no_manual_or_auto_permission(harness: Harness) -> None:
    bot = make(harness, API())
    with pytest.raises(DataIntegrityError, match="bound signal"):
        bot._manual_only(Alert(proposal_id=uuid4()))


@pytest.mark.asyncio
async def test_XK_03_public_card_context_is_escaped(harness: Harness) -> None:
    alert = await deliver(harness)
    bot = make(harness, API())
    bot.card_annotations = lambda _: ("<b>SPY below EMA200</b>",)
    text = bot._updated_card(alert)
    assert "&lt;b&gt;SPY below EMA200&lt;/b&gt;" in text
    assert "<b>SPY below EMA200</b>" not in text


@pytest.mark.asyncio
async def test_XK_08_private_report_command_sends_generated_attachment(harness: Harness) -> None:
    api = Documents()
    bot = document_bot(harness, api)
    payload = html_report(snapshot(harness))

    async def pages(argument: str) -> tuple[str, ...]:
        assert argument == ""
        return ("Paper report: estimates; 1099-B wins.",)

    async def report() -> bytes:
        return payload

    bot.commands["/report"] = pages
    bot.report_document = report
    await bot.application.initialize()
    bot._admitted = True
    try:
        await bot._command(command_update(bot, "/report"), None)  # type: ignore[arg-type]
        assert api.targets == [123] and len(api.documents) == 1
        assert payload in api.documents[0]
        assert harness.state.current() == SystemState.RUNNING
    finally:
        await bot.application.shutdown()
