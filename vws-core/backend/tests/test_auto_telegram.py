"""AX-01/02/50/52/53: mode fuzzing through the pinned Telegram SDK, fake HTTP."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import Update

from backend.core.database import SecurityEvent
from backend.core.system_state import SystemState
from backend.execution.modes import ModeStore
from backend.notifications.callbacks import callback_data
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_execution_controls import live_settings
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from backend.tests.test_telegram_flow import API, command_update, make

harness = make_research_harness
MODES: list[dict[str, Any]] = [
    {},
    AUTO,
    {
        **AUTO,
        **live_settings().model_dump(
            include={
                "execution_mode",
                "paper_trading",
                "live_trading_enabled",
                "live_trading_confirm",
                "broker_api_key",
                "broker_secret_key",
                "live_max_order_notional",
                "live_max_daily_orders",
                "live_max_open_positions",
                "live_max_gross_exposure_pct",
                "live_max_risk_per_trade",
                "live_daily_loss_limit",
            }
        ),
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("command", ["/pause", "/halt", "/manual"])
async def test_AX_30_private_downgrade_cancels_remainder_and_preserves_protection(
    harness: Harness, command: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    h.gate.bind_auto(built, built.modes)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)
    api = API()
    bot = make(h, api)
    await bot.application.initialize()
    try:
        await bot._command(command_update(bot, command), None)  # type: ignore[arg-type]
        assert parent["status"] == "canceled" and not built.modes.entries_enabled
        assert len(client.posts) == 2 and client.posts[-1]["type"] == "stop"
        assert client.posts[-1]["qty"] == "1"
        assert any("Held exits and protection remain available" in text for text in api.messages)
    finally:
        await bot.application.shutdown()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_AX_02_manual_command_never_adds_executor_or_changes_safety_state(
    harness: Harness,
) -> None:
    h = harness
    api = API()
    bot = make(h, api)
    await bot.application.initialize()
    try:
        await bot._command(command_update(bot, "/manual"), None)  # type: ignore[arg-type]
        assert h.gate.executor is None and h.gate.modes is None
        assert h.state.current() == SystemState.RUNNING
        with Session(h.state.engine) as session:
            assert (
                session.scalar(select(SecurityEvent).where(SecurityEvent.kind == "TELEGRAM_MANUAL"))
                is not None
            )
    finally:
        await bot.application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "harness", [AUTO, {**AUTO, "auto_min_score": Decimal("10")}], indirect=True
)
async def test_AX_50_annotation_keeps_auto_fyi_and_hybrid_language_distinct(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    built = executor(h, FakeTradingClient(h))
    h.gate.bind_auto(built, built.modes)
    api = API()
    bot = make(h, api)
    await bot.start()
    try:
        assert await bot.annotate(alert.id, "Public evidence updated")
        assert len(api.edit_messages) == 1
        text = api.edit_messages[0]
        assert text.startswith("PAPER · ") and "Manual review required" not in text
        if alert.score >= h.settings.auto_min_score:
            assert "Planned for the next entry window" in text
            assert "Approve = places the order" not in text
        else:
            assert "Approve = places the order now (PAPER)" in text
    finally:
        await bot.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_50_expiry_never_reopens_or_closes_a_recorded_broker_intent(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    await executor(h, client).enter(alert.proposal_id)
    h.clock.current = alert.expires_at
    api = API()
    bot = make(h, api)
    assert await bot.expire_alerts() == 0
    assert h.state.ledger.current_alert_status(alert.id) == "AUTO_APPROVED"
    assert len(client.posts) == 1 and not api.edit_messages
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", MODES, indirect=True)
async def test_AX_02_all_private_commands_cannot_upgrade_or_reset(harness: Harness) -> None:
    h = harness
    modes = ModeStore(h.settings, h.state, "offline-paper")
    h.gate.modes = modes
    api = API()
    bot = make(h, api)
    await bot.application.initialize()
    initial = modes.effective
    try:
        for text in (
            "/resume",
            "/auto",
            "/enable-live",
            "/reset RUNNING",
            "/status",
            "/positions",
            "/digest",
            "/report",
            "/edge",
            "/progress",
            "/pnl",
            "/tax",
            "/watch NVDA",
            "/help",
            "/start",
        ):
            await bot._command(command_update(bot, text), None)  # type: ignore[arg-type]
            assert modes.effective == initial and h.state.current() == SystemState.RUNNING
        for command, kind in (
            ("/pause", "TELEGRAM_PAUSE"),
            ("/manual", "TELEGRAM_MANUAL"),
            ("/halt", "TELEGRAM_HALT"),
        ):
            await bot._command(command_update(bot, command), None)  # type: ignore[arg-type]
            assert not modes.entries_enabled
            assert modes.effective in {initial, "MANUAL"}
            with Session(h.state.engine) as session:
                assert (
                    session.scalar(select(SecurityEvent).where(SecurityEvent.kind == kind))
                    is not None
                )
        assert modes.effective == "MANUAL" and h.state.current() == SystemState.HALTED
        for text in ("/resume", "/AUTO_LIVE", "/reset", "/enable-live"):
            await bot._command(command_update(bot, text), None)  # type: ignore[arg-type]
            assert modes.effective == "MANUAL" and not modes.entries_enabled
        assert any("resume-auto --operator NAME" in message for message in api.messages)
    finally:
        await bot.application.shutdown()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", MODES, indirect=True)
@pytest.mark.parametrize("action", ["A", "R", "D", "P", "S", "malformed"])
async def test_AX_02_every_callback_cannot_upgrade_mode(harness: Harness, action: Any) -> None:
    h = harness
    alert = await deliver(h)
    modes = ModeStore(h.settings, h.state, "offline-paper")
    h.gate.modes = modes
    bot = make(h, API())
    await bot.application.initialize()
    initial = modes.effective
    try:
        data = (
            "untrusted:AUTO_LIVE:RESUME"
            if action == "malformed"
            else callback_data(action, alert.proposal_id, 123, h.settings)
        )
        update = Update.de_json(
            {
                "update_id": 1,
                "callback_query": {
                    "id": "fuzz",
                    "from": {"id": 123, "is_bot": False, "first_name": "Owner"},
                    "chat_instance": "offline",
                    "data": data,
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
        assert modes.effective == initial
    finally:
        await bot.application.shutdown()
    h.state.ledger.verify_chain()
