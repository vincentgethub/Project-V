"""GD-05: real pinned Telegram SDK, fake HTTP, no external messaging."""

from datetime import datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from telegram import Update

from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EgressDeniedError,
    ProviderError,
)
from backend.core.system_state import SystemState
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import TelegramRequest
from backend.notifications.callbacks import callback_data
from backend.notifications.telegram_bot import TelegramBot, quiet_hours
from backend.tests.test_swarm_and_callbacks import (  # noqa: F401
    Harness,
    deliver,
    make_research_harness,
)


class API:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.messages: list[str] = []
        self.targets: list[int] = []
        self.webhook = ""
        self.chat_type = "private"
        self.chat_id = 123
        self.send_error = False
        self.edit_error = False
        self.edit_messages: list[str] = []

    async def http(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[1]
        self.calls.append(method)
        parameters = parse_qs((await request.aread()).decode())
        result: Any = True
        if method == "getMe":
            result = dict(
                id=99999,
                is_bot=True,
                first_name="Offline",
                username="offline_bot",
                can_join_groups=False,
                can_read_all_group_messages=False,
            )
        elif method == "getWebhookInfo":
            result = dict(url=self.webhook, has_custom_certificate=False, pending_update_count=0)
        elif method == "getChat":
            result = dict(
                id=self.chat_id,
                type=self.chat_type,
                first_name="Owner",
                accent_color_id=0,
                max_reaction_count=0,
            )
        elif method == "getUpdates":
            result = []
        elif method == "sendMessage":
            if self.send_error:
                return httpx.Response(500, json={"ok": False, "description": "offline outage"})
            self.messages.append(parameters["text"][0])
            self.targets.append(int(parameters["chat_id"][0]))
            result = dict(
                message_id=456,
                date=1790780400,
                chat=dict(id=123, type="private"),
                text=parameters["text"][0],
            )
        elif method == "editMessageText":
            if self.edit_error:
                return httpx.Response(500, json={"ok": False, "description": "offline edit outage"})
            self.edit_messages.append(parameters["text"][0])
        return httpx.Response(200, json=dict(ok=True, result=result))


def make(h: Harness, api: API) -> TelegramBot:
    policy = EgressPolicy(build_allowlist(), h.state.ledger)
    token = h.settings.telegram_bot_token.get_secret_value()
    return TelegramBot(
        h.settings,
        h.state,
        h.clock,
        h.gate,
        policy,
        {},
        transport=TelegramRequest(token, policy, transport=httpx.MockTransport(api.http)),
        polling_transport=TelegramRequest(token, policy, transport=httpx.MockTransport(api.http)),
    )


@pytest.mark.asyncio
async def test_GD_05_private_start_delivery_and_bound_double_click(harness: Harness) -> None:
    h, api = harness, API()
    alert = await deliver(h)
    # Build a second undelivered research alert is intentionally unnecessary:
    # the first delivery fixture already bound the original actionable message.
    bot = make(h, api)
    await bot.start()
    try:
        assert {"getMe", "getChat", "getWebhookInfo"}.issubset(api.calls)
        assert not await bot.deliver(alert.id, 123)
        update = Update.de_json(
            {
                "update_id": 1,
                "callback_query": {
                    "id": "click-1",
                    "from": {"id": 123, "is_bot": False, "first_name": "Owner"},
                    "chat_instance": "offline",
                    "data": callback_data("A", alert.proposal_id, 123, h.settings),
                    "message": {
                        "message_id": 456,
                        "date": 1790780400,
                        "chat": {"id": 123, "type": "private"},
                        "text": "fixture",
                    },
                },
            },
            bot.application.bot,
        )
        assert update is not None
        await bot._callback(update, None)  # type: ignore[arg-type]
        assert (
            h.source.calls == 1
            and "answerCallbackQuery" in api.calls
            and "editMessageText" in api.calls
        )
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_SEC_51_unauthorized_halt_ignored_owner_halt_persists(harness: Harness) -> None:
    h, api = harness, API()
    bot = make(h, api)
    await bot.application.initialize()
    try:
        for user in (999, 123):
            update = Update.de_json(
                {
                    "update_id": user,
                    "message": {
                        "message_id": 42,
                        "date": 1790780400,
                        "from": {"id": user, "is_bot": False, "first_name": "Owner"},
                        "chat": {"id": user, "type": "private"},
                        "text": "/halt offline reason",
                    },
                },
                bot.application.bot,
            )
            assert update is not None
            await bot._command(update, None)  # type: ignore[arg-type]
            assert h.state.current() == (SystemState.RUNNING if user == 999 else SystemState.HALTED)
        assert len(api.messages) == 2 and api.targets == [123, 123]
    finally:
        await bot.application.shutdown()


@pytest.mark.asyncio
async def test_SEC_34_configured_webhook_is_preserved_and_polling_refused(harness: Harness) -> None:
    api = API()
    api.webhook = "https://example.com"
    bot = make(harness, api)
    with pytest.raises(ConfigurationError):
        await bot.start()
    assert "deleteWebhook" not in api.calls
    await bot.application.shutdown()


@pytest.mark.parametrize(
    "instant,quiet",
    [
        ("2026-10-07T02:59:59+00:00", False),
        ("2026-10-07T03:00:00+00:00", True),
        ("2026-10-07T11:59:59+00:00", True),
        ("2026-10-07T12:00:00+00:00", False),
        ("2026-11-02T04:00:00+00:00", True),
    ],
)
def test_GD_05_quiet_hours_ct_and_dst(instant: str, quiet: bool) -> None:
    assert quiet_hours(datetime.fromisoformat(instant)) == quiet


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["host", "method", "redirect", "large", "fault"])
async def test_SEC_30_transport_prohibits_unsafe_destination_method_and_body(
    harness: Harness, case: str
) -> None:
    policy = EgressPolicy(build_allowlist(), harness.state.ledger)

    async def response(request: httpx.Request) -> httpx.Response:
        if case == "fault":
            raise httpx.ReadTimeout("private URL must never be exposed")
        if case == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.com"})
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))

    transport = TelegramRequest("123:fixture", policy, transport=httpx.MockTransport(response))
    url = "https://api.telegram.org/bot123:fixture/" + (
        "setWebhook" if case == "method" else "getMe"
    )
    if case == "host":
        url = "https://example.com/getMe"
    with pytest.raises((EgressDeniedError, ProviderError)):
        await transport.do_request(url, "POST")
    await transport.shutdown()


def command_update(
    bot: TelegramBot, text: str, user: int = 123, chat_type: str = "private"
) -> Update:
    item = Update.de_json(
        {
            "update_id": user,
            "message": {
                "message_id": 42,
                "date": 1790780400,
                "from": {"id": user, "is_bot": False, "first_name": "Owner"},
                "chat": {"id": user if chat_type == "private" else -123, "type": chat_type},
                "text": text,
            },
        },
        bot.application.bot,
    )
    assert item is not None
    return item


@pytest.mark.asyncio
async def test_GD_05_delivery_is_bound_once_and_no_retry_after_ambiguity(harness: Harness) -> None:
    h, api = harness, API()
    result = await h.swarm.run(h.request)
    assert result.alert_id is not None
    bot = make(h, api)
    with pytest.raises(ConfigurationError):
        await bot.deliver(result.alert_id, 123)
    await bot.start()
    try:
        from uuid import uuid4

        with pytest.raises(DataIntegrityError):
            await bot.deliver(uuid4(), 123)
        with pytest.raises(ConfigurationError):
            await bot.deliver(result.alert_id, 999)
        assert await bot.deliver(result.alert_id, 123)
        assert not await bot.deliver(result.alert_id, 123) and len(api.messages) == 1
        assert result.proposal is not None
        assert len(bot.keyboard(result.proposal.proposal_id, 123).inline_keyboard[0]) == 3
    finally:
        await bot.stop()
        await bot.stop()


@pytest.mark.asyncio
async def test_GD_05_failed_delivery_halts_without_actionable_binding(harness: Harness) -> None:
    h, api = harness, API()
    result = await h.swarm.run(h.request)
    assert result.alert_id is not None
    bot = make(h, api)
    await bot.start()
    try:
        api.send_error = True
        with pytest.raises(ProviderError):
            await bot.deliver(result.alert_id, 123)
        assert h.state.current() == SystemState.HALTED
        assert h.state.ledger.current_alert_status(result.alert_id) == "PENDING"
        assert not await bot.deliver(result.alert_id, 123)
    finally:
        await bot.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{"proposal_ttl_sessions": 3}], indirect=True)
async def test_GD_05_quiet_queue_persists_and_flushes_once_but_stop_notice_is_urgent(
    harness: Harness,
) -> None:
    h, api = harness, API()
    result = await h.swarm.run(h.request)
    assert result.alert_id is not None
    bot = make(h, api)
    await bot.start()
    try:
        h.clock.current = datetime.fromisoformat("2026-10-01T03:00:00+00:00")
        assert not await bot.deliver(result.alert_id, 123)
        await bot.notify("ordinary <notice>", False)
        await bot.notify("stop breached", True)
        assert api.messages == ["stop breached"]
        await bot.flush_pending()
        assert api.messages == ["stop breached"]
        h.clock.current = datetime.fromisoformat("2026-10-01T12:00:00+00:00")
        await bot.flush_pending()
        await bot.flush_pending()
        assert len(api.messages) == 3 and "ordinary &lt;notice&gt;" in api.messages
        assert h.state.ledger.current_alert_status(result.alert_id) == "SENT"
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_GD_05_expired_pending_is_closed_before_delivery(harness: Harness) -> None:
    h, api = harness, API()
    result = await h.swarm.run(h.request)
    assert result.alert_id is not None and result.proposal is not None
    bot = make(h, api)
    await bot.start()
    try:
        h.clock.current = result.proposal.expires_at
        assert not await bot.deliver(result.alert_id, 123)
        assert (
            h.state.ledger.current_alert_status(result.alert_id) == "EXPIRED" and not api.messages
        )
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_SEC_51_reply_limits_group_leave_commands_and_errors(harness: Harness) -> None:
    from types import SimpleNamespace

    h, api = harness, API()
    bot = make(h, api)
    await bot.application.initialize()
    try:
        with pytest.raises(DataIntegrityError):
            await bot.reply(999, "private")
        with pytest.raises(DataIntegrityError):
            await bot.reply(123, "x" * 4097)
        await bot._command(command_update(bot, "/halt", 123, "group"), None)  # type: ignore[arg-type]
        assert "leaveChat" in api.calls and h.state.current() == SystemState.RUNNING

        async def help_body(argument: str) -> tuple[str, ...]:
            return ("private help",)

        bot.commands["/help"] = help_body
        await bot._command(command_update(bot, "/help"), None)  # type: ignore[arg-type]
        await bot._command(command_update(bot, "/resume"), None)  # type: ignore[arg-type]
        assert h.state.current() == SystemState.RUNNING
        await bot._command(command_update(bot, "/pause"), None)  # type: ignore[arg-type]
        assert h.state.current() == SystemState.REDUCE_ONLY
        await bot._command(Update(999), None)  # type: ignore[arg-type]
        await bot._callback(Update(999), None)  # type: ignore[arg-type]
        await bot._error(None, SimpleNamespace(error=RuntimeError("secret detail")))  # type: ignore[arg-type]
        await bot._error(None, SimpleNamespace(error=None))  # type: ignore[arg-type]
        assert h.state.current() == SystemState.HALTED
    finally:
        await bot.application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", ["group", "user"])
async def test_SEC_51_start_rejects_wrong_recipient(harness: Harness, wrong: str) -> None:
    api = API()
    if wrong == "group":
        api.chat_type = "group"
    else:
        api.chat_id = 999
    bot = make(harness, api)
    with pytest.raises(ConfigurationError):
        await bot.start()
    assert "deleteWebhook" not in api.calls
    await bot.application.shutdown()


@pytest.mark.asyncio
async def test_GD_05_readonly_details_replay_and_followup_adapter(harness: Harness) -> None:
    h, api = harness, API()
    alert = await deliver(h)
    bot = make(h, api)
    await bot.start()

    def update(action: str, data: str | None = None, user: int = 123) -> Update:
        from typing import cast

        from backend.notifications.callbacks import Action

        item = Update.de_json(
            {
                "update_id": 1,
                "callback_query": {
                    "id": "click-1",
                    "from": {"id": user, "is_bot": False, "first_name": "Owner"},
                    "chat_instance": "offline",
                    "data": data
                    or callback_data(cast(Action, action), alert.proposal_id, 123, h.settings),
                    "message": {
                        "message_id": 456,
                        "date": 1790780400,
                        "chat": {"id": user, "type": "private"},
                        "text": "fixture",
                    },
                },
            },
            bot.application.bot,
        )
        assert item is not None
        return item

    try:
        await bot._callback(update("D"), None)  # type: ignore[arg-type]
        assert api.edit_messages and "CRO-01" in api.edit_messages[-1]
        await bot._callback(update("A", data="v1:A:" + "a" * 32 + ":" + "0" * 16), None)  # type: ignore[arg-type]
        await bot._callback(update("A", user=999), None)  # type: ignore[arg-type]
        assert h.source.calls == 0
        await bot._callback(update("A"), None)  # type: ignore[arg-type]
        ticket_text = api.edit_messages[-1]
        await bot._callback(update("A"), None)  # type: ignore[arg-type]
        assert api.edit_messages[-1] == ticket_text
        await bot._callback(update("P"), None)  # type: ignore[arg-type]
        assert "Recorded" in api.edit_messages[-1] and h.source.calls == 1
    finally:
        await bot.stop()


def test_GD_05_constructor_refuses_a_different_clock(harness: Harness) -> None:
    from backend.tests.test_swarm_and_callbacks import MovingClock

    h = harness
    with pytest.raises(ConfigurationError):
        TelegramBot(
            h.settings,
            h.state,
            MovingClock(h.clock.now()),
            h.gate,
            EgressPolicy(build_allowlist(), h.state.ledger),
            {},
        )


@pytest.mark.asyncio
async def test_GD_05_sdk_without_updater_cannot_be_admitted(harness: Harness) -> None:
    bot = make(harness, API())
    updater = bot.application.updater
    bot.application.updater = None
    try:
        with pytest.raises(ConfigurationError, match="updater unavailable"):
            await bot.start()
        assert not bot._admitted
    finally:
        await bot.stop()
        if updater is not None:
            await updater.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [True, False])
async def test_GD_05_annotations_preserve_pending_state_and_are_escaped(
    harness: Harness, delivered: bool
) -> None:
    from uuid import uuid4

    h, api = harness, API()
    if delivered:
        alert_id = (await deliver(h)).id
    else:
        result = await h.swarm.run(h.request)
        assert result.alert_id is not None
        alert_id = result.alert_id
    bot = make(h, api)
    await bot.start()
    try:
        assert not await bot.annotate(uuid4(), "unavailable")
        with pytest.raises(DataIntegrityError):
            await bot.annotate(alert_id, "x" * 601)
        assert await bot.annotate(alert_id, "Public guidance & changed")
        if delivered:
            assert "&amp; changed" in api.edit_messages[-1]
            before = len(api.edit_messages)
            await bot.flush_annotations()
            assert len(api.edit_messages) == before
        else:
            await bot.flush_annotations()
            assert not api.edit_messages
            await bot.deliver(alert_id, 123)
            assert "&amp; changed" in api.messages[-1]
            await bot.flush_annotations()
        assert h.state.ledger.current_alert_status(alert_id) == "SENT"
        assert await bot.invalidate(alert_id, "Corporate action changed the setup")
        assert not await bot.annotate(alert_id, "handled")
        assert not await bot.invalidate(alert_id, "handled")
        assert h.state.ledger.current_alert_status(alert_id) == "REVALIDATION_FAILED"
        await bot.flush_annotations()
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_GD_05_sent_annotations_wait_for_end_of_quiet_hours(harness: Harness) -> None:
    h, api = harness, API()
    alert = await deliver(h)
    bot = make(h, api)
    await bot.start()
    try:
        h.clock.current = datetime.fromisoformat("2026-10-01T03:00:00+00:00")
        assert await bot.annotate(alert.id, "Overnight public headline changed")
        await bot.flush_annotations()
        assert not api.edit_messages
        h.clock.current = datetime.fromisoformat("2026-10-01T12:00:00+00:00")
        await bot.flush_annotations()
        await bot.flush_annotations()
        assert len(api.edit_messages) == 1 and "Overnight" in api.edit_messages[-1]
    finally:
        await bot.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivered", [True, False])
async def test_GD_05_expiry_removes_actions_once_even_after_halt(
    harness: Harness, delivered: bool
) -> None:
    h, api = harness, API()
    if delivered:
        alert = await deliver(h)
    else:
        from sqlalchemy.orm import Session

        from backend.core.database import Alert

        result = await h.swarm.run(h.request)
        with Session(h.state.engine) as session:
            pending_alert = session.get(Alert, result.alert_id)
            assert pending_alert is not None
            alert = pending_alert
    bot = make(h, api)
    await bot.start()
    try:
        h.clock.current = alert.expires_at
        h.state.escalate(SystemState.HALTED, "expire pending cards under halt")
        assert await bot.expire_alerts() == 1
        assert await bot.expire_alerts() == 0
        assert api.edit_messages == (["Expired. No ticket."] if delivered else [])
        assert h.state.ledger.current_alert_status(alert.id) == "EXPIRED"
    finally:
        await bot.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["annotation", "queued_annotation", "invalidate", "expiry"])
async def test_GD_05_edit_outage_never_restores_a_closed_card(
    harness: Harness, action: str
) -> None:
    h, api = harness, API()
    alert = await deliver(h)
    bot = make(h, api)
    await bot.start()
    try:
        if action == "queued_annotation":
            h.clock.current = datetime.fromisoformat("2026-10-01T03:00:00+00:00")
            await bot.annotate(alert.id, "Overnight facts")
            h.clock.current = datetime.fromisoformat("2026-10-01T12:00:00+00:00")
        api.edit_error = True
        with pytest.raises(ProviderError):
            if action == "annotation":
                await bot.annotate(alert.id, "Changed facts")
            elif action == "queued_annotation":
                await bot.flush_annotations()
            elif action == "invalidate":
                await bot.invalidate(alert.id, "SUSPECT symbol")
            else:
                h.clock.current = alert.expires_at
                await bot.expire_alerts()
        assert h.state.current() == SystemState.HALTED
        assert h.state.ledger.current_alert_status(alert.id) == (
            "REVALIDATION_FAILED"
            if action == "invalidate"
            else "EXPIRED"
            if action == "expiry"
            else "SENT"
        )
    finally:
        await bot.stop()


@pytest.mark.asyncio
async def test_GD_05_invalidation_without_delivery_is_durable_and_edit_binding_is_private(
    harness: Harness,
) -> None:
    from backend.core.database import AlertEvent

    h, api = harness, API()
    result = await h.swarm.run(h.request)
    assert result.alert_id is not None
    bot = make(h, api)
    with pytest.raises(ConfigurationError):
        await bot._edit("private", AlertEvent(telegram_chat_id=999, telegram_message_id=1))
    with pytest.raises(DataIntegrityError):
        await bot.invalidate(result.alert_id, "\ninvalid")
    assert await bot.invalidate(result.alert_id, "Changed public facts")
    assert not await bot.invalidate(result.alert_id, "Already closed")
    assert not api.edit_messages


@pytest.mark.asyncio
async def test_GD_05_oversize_annotation_cannot_silently_drop_card_evidence(
    harness: Harness,
) -> None:
    from sqlalchemy.orm import Session

    from backend.core.database import Alert, SecurityEvent

    h = harness
    alert = await deliver(h)
    bot = make(h, API())
    h.state.ledger.append(
        SecurityEvent,
        kind="ALERT_ANNOTATED",
        detail={"alert_id": str(alert.id), "note": "'" * 600},
    )
    with Session(h.state.engine) as session:
        bound = session.get(Alert, alert.id)
        assert bound is not None
    with pytest.raises(DataIntegrityError, match="message boundary"):
        bot._updated_card(bound)


@pytest.mark.asyncio
async def test_GD_05_changed_policy_cannot_annotate_an_old_actionable_card(
    harness: Harness,
) -> None:
    from backend.core.config import Settings

    h, api = harness, API()
    alert = await deliver(h)
    bot = make(h, api)
    bot.settings = Settings.validated_copy(
        bot.settings.model_copy(
            update={"telegram_mask_amounts": not bot.settings.telegram_mask_amounts}
        )
    )
    with pytest.raises(DataIntegrityError, match="policy differs"):
        await bot.annotate(alert.id, "Updated public evidence")
    assert not api.edit_messages and h.state.current() == SystemState.HALTED
    assert h.state.ledger.current_alert_status(alert.id) == "SENT"


@pytest.mark.asyncio
async def test_GD_05_lost_queued_annotation_evidence_halts_without_edit(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.orm import Session

    from backend.core.database import Alert

    h, api = harness, API()
    alert = await deliver(h)
    bot = make(h, api)
    h.clock.current = datetime.fromisoformat("2026-10-01T03:00:00+00:00")
    await bot.annotate(alert.id, "Overnight public evidence")
    h.clock.current = datetime.fromisoformat("2026-10-01T12:00:00+00:00")
    original = Session.get
    reads = 0

    def lost(session: Session, entity: Any, ident: Any, **kwargs: Any) -> Any:
        nonlocal reads
        if entity is Alert and ident == alert.id:
            reads += 1
            if reads == 2:
                return None
        return original(session, entity, ident, **kwargs)

    monkeypatch.setattr(Session, "get", lost)
    with pytest.raises(DataIntegrityError, match="lost delivery provenance"):
        await bot.flush_annotations()
    assert reads >= 2 and not api.edit_messages and h.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_GD_05_expiry_rechecks_consumption_inside_serialized_writer(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import UUID

    from sqlalchemy.orm import Session

    from backend.core.database import AlertEvent, ApprovalEvent

    h, api = harness, API()
    alert = await deliver(h)
    bot = make(h, api)
    h.clock.current = alert.expires_at
    original = h.state.ledger._latest_alert_event
    consumed = False
    reads = 0

    def consume(session: Session, alert_id: UUID) -> AlertEvent | None:
        nonlocal consumed, reads
        reads += 1
        if reads == 2:
            consumed = True
            h.state.ledger.append_in_session(
                session, ApprovalEvent, alert_id=alert_id, action="EXPIRED", reasons=[]
            )
        return original(session, alert_id)

    monkeypatch.setattr(h.state.ledger, "_latest_alert_event", consume)
    assert await bot.expire_alerts() == 0
    assert consumed and not api.edit_messages
    assert h.state.ledger.current_alert_status(alert.id) == "EXPIRED"
    h.state.ledger.verify_chain()
