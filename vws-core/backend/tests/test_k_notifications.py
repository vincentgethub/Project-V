"""XK-02/08/09: exact private reply bindings and guarded order-size boundary."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import Update

from backend.core.database import SecurityEvent
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    ExecutionDisabledError,
    ProviderError,
)
from backend.core.system_state import SystemState
from backend.data.fill_polling import ObservedFill
from backend.domain.models import Side
from backend.notifications.control import downgrade
from backend.ops.journal import Journal
from backend.ops.k_runtime import actual_resolved
from backend.ops.trading_controls import ControlScope
from backend.tax.models import TaxFill
from backend.tax.storage import append_evidence
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from backend.tests.test_telegram_flow import API, make

harness = make_research_harness


def journal(h: Harness) -> Journal:
    return Journal(
        h.state.ledger, ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER")
    )


def reply_update(bot: Any, text: str, reply_id: int) -> Update:
    value = Update.de_json(
        {
            "update_id": 888,
            "message": {
                "message_id": 888,
                "date": 1790780400,
                "from": {"id": 123, "is_bot": False, "first_name": "Owner"},
                "chat": {"id": 123, "type": "private"},
                "text": text,
                "reply_to_message": {
                    "message_id": reply_id,
                    "date": 1790780400,
                    "chat": {"id": 123, "type": "private"},
                    "text": "original",
                },
            },
        },
        bot.application.bot,
    )
    assert value is not None
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "unbound", "oversized", "halt", "watch"])
async def test_XK_02_private_reply_is_bound_escaped_and_never_changes_trade_decisions(
    harness: Harness, case: str
) -> None:
    h, api = harness, API()
    alert = await deliver(h)
    store = journal(h)
    bot = make(h, api)
    await bot.application.initialize()
    bot._admitted = True

    async def note(user: int, chat: int, message: int, text: str) -> UUID:
        return store.note(user_id=user, chat_id=chat, message_id=message, text=text, allowed=(123,))

    async def watch(symbol: str, chat: int) -> tuple[str, ...]:
        assert symbol == "NVDA" and chat == 123
        return ("manual-only watch result",)

    bot.note_handler, bot.watch_handler = note, watch
    try:
        text = (
            "/halt"
            if case == "halt"
            else "/watch NVDA"
            if case == "watch"
            else "x" * 1001
            if case == "oversized"
            else "<b>Untrusted BUY</b>"
        )
        await bot._command(reply_update(bot, text, 999 if case == "unbound" else 456), None)  # type: ignore[arg-type]
        if case in {"oversized", "unbound"}:
            assert "Note refused" in api.messages[-1]
        elif case == "halt":
            assert h.state.current() == SystemState.HALTED
        elif case == "watch":
            assert "manual-only" in api.messages[-1]
        else:
            assert "Journal note recorded" in api.messages[-1]
            assert "&lt;b&gt;Untrusted BUY&lt;/b&gt;" in store.csv().decode()
            assert h.state.ledger.current_alert_status(alert.id) == "SENT"
    finally:
        await bot.application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["normal", "quiet", "unknown", "unadmitted", "misbound"])
async def test_XK_02_trade_fyi_is_bound_before_reply_notes(harness: Harness, case: str) -> None:
    h, api = harness, API()
    alert = await deliver(h)
    bot = make(h, api)
    await bot.application.initialize()
    bot._admitted = case != "unadmitted"
    try:
        if case == "quiet":
            h.clock.current = datetime(2026, 10, 1, 3, tzinfo=UTC)
        if case == "unadmitted":
            with pytest.raises(ConfigurationError):
                await bot.notify_trade("PAPER fill", False, alert.proposal_id)
        elif case == "unknown":
            with pytest.raises(DataIntegrityError):
                await bot.notify_trade("PAPER fill", False, uuid4())
        elif case == "misbound":

            async def send(*args: object, **kwargs: object) -> object:
                return SimpleNamespace(chat=SimpleNamespace(id=999, type="private"), message_id=1)

            from unittest.mock import patch

            with patch.object(type(bot.application.bot), "send_message", send):
                with pytest.raises(DataIntegrityError):
                    await bot.notify_trade("PAPER fill", False, alert.proposal_id)
        else:
            await bot.notify_trade("PAPER fill", False, alert.proposal_id)
            if case == "quiet":
                assert not api.messages
                h.clock.current = datetime(2026, 10, 1, 12, tzinfo=UTC)
                await bot.flush_pending()
            with Session(h.state.engine) as session:
                binding = session.scalar(
                    select(SecurityEvent).where(SecurityEvent.kind == "TRADE_FYI_BINDING")
                )
                assert binding is not None and binding.detail["alert_id"] == str(alert.id)
    finally:
        await bot.application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["bad_action", "actor", "foreign_mode"])
async def test_XK_01_shared_downgrade_refuses_invalid_or_foreign_state(
    harness: Harness, case: str
) -> None:
    foreign: Any = SimpleNamespace(state=object())
    action: Any = "UPGRADE" if case == "bad_action" else "HALT"
    with pytest.raises(DataIntegrityError):
        await downgrade(
            harness.state,
            foreign if case == "foreign_mode" else None,
            None,
            action,
            "" if case == "actor" else "Offline owner",
            "scratch",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("size", [0, 1, True, 100000, Decimal(1)])
async def test_XK_03_06_actual_executor_size_boundary_never_increases_qty(
    harness: Harness, size: Any
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)

    async def quantity(proposal: object, inputs: object) -> int:
        return size  # type: ignore[no-any-return]

    built.size_entry = quantity
    if type(size) is int and size == 1:
        await built.enter(alert.proposal_id)
        assert client.posts[0]["qty"] == "1"
    elif size == 0 and type(size) is int:
        with pytest.raises(ExecutionDisabledError):
            await built.enter(alert.proposal_id)
        assert h.state.current() == SystemState.RUNNING and not client.posts
    else:
        with pytest.raises(ProviderError):
            await built.enter(alert.proposal_id)
        assert h.state.current() == SystemState.HALTED and not client.posts


def test_XK_02_unassigned_physical_sale_keeps_context_unavailable_and_is_idempotent(
    harness: Harness,
) -> None:
    h = harness
    sale = TaxFill(
        fill_id=uuid4(),
        activity_id="external-manual-sale",
        account_id=h.request.portfolio.account_id,
        env="PAPER",
        symbol="NVDA",
        side=Side.SELL,
        qty=2,
        price=Decimal("101.50"),
        fees=Decimal("0.10"),
        ts=h.clock.now(),
        fee_source="BROKER",
        payload_sha256="a" * 64,
    )
    append_evidence(
        h.state.ledger,
        sale.account_id,
        sale.env,
        "FILL",
        sale.activity_id,
        sale.payload_sha256,
        sale.model_dump(mode="json"),
    )
    store = journal(h)
    assert store.sync() == 1 and store.sync() == 0
    exported = store.csv().decode()
    assert (
        "UNASSIGNED" in exported
        and "UNAVAILABLE" in exported
        and "no recorded Project V proposal" in exported
    )
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XK_06_completed_physical_round_trip_counts_once(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, buy = await fill_entry(h, client, built)
    child = next(row for row in parent["legs"] if row["type"] == "stop")
    h.clock.current += timedelta(minutes=1)
    built.observe_fill(
        ObservedFill(
            account_id=buy.account_id,
            broker_fill_id="complete-stop-fill",
            broker_order_id=UUID(child["id"]),
            symbol=buy.symbol,
            side=Side.SELL,
            qty=buy.qty,
            price=Decimal(child["stop_price"]),
            filled_at=h.clock.now(),
        )
    )
    store = journal(h)
    assert actual_resolved(h.state.ledger, store.scope) == 1
    assert (
        actual_resolved(
            h.state.ledger, ControlScope(account_id=store.scope.account_id, environment="LIVE")
        )
        == 0
    )
