"""SEC-34/50..53: fake-only bot admission and masked golden fields."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError
from backend.core.ledger import Ledger
from backend.telegram.security import TelegramSecurity, bot_security_findings, mask_account_fields


class MovingClock:
    def __init__(self) -> None:
        self.instant = datetime(2026, 10, 5, 15, tzinfo=UTC)

    def now(self) -> datetime:
        return self.instant


class Bot:
    def __init__(self) -> None:
        self.notices: list[tuple[str, bool]] = []
        self.left: list[int] = []
        self.replies: list[tuple[int, str]] = []

    async def notify(self, text: str, urgent: bool) -> None:
        self.notices.append((text, urgent))

    async def leave(self, chat_id: int) -> None:
        self.left.append(chat_id)

    async def reply(self, chat_id: int, text: str) -> None:
        self.replies.append((chat_id, text))


def guard(engine: Engine, clock: MovingClock, bot: Bot) -> TelegramSecurity:
    return TelegramSecurity(
        (123,), Ledger(engine, clock), clock, notify=bot.notify, leave=bot.leave, reply=bot.reply
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
async def test_SEC_51_nonprivate_is_ignored_left_and_logged(engine: Engine, chat_type: str) -> None:
    clock, bot = MovingClock(), Bot()
    result = await guard(engine, clock, bot).admit(
        user_id=123, chat_id=-456, chat_type=chat_type, command="/halt"
    )
    assert not result.accepted and bot.left == [-456] and not bot.replies
    with transaction(engine) as session:
        assert session.scalar(select(SecurityEvent.kind)) == "TELEGRAM_NONPRIVATE"


@pytest.mark.asyncio
async def test_SEC_52_stranger_notices_throttle_survive_restart_and_escalate(
    engine: Engine,
) -> None:
    clock, bot = MovingClock(), Bot()
    security = guard(engine, clock, bot)
    for _ in range(5):
        assert not (
            await security.admit(
                user_id=999,
                chat_id=999,
                chat_type="private",
                command="/status",
                username="intruder",
            )
        ).accepted
    assert len(bot.notices) == 2 and not bot.notices[0][1] and bot.notices[-1][1]
    assert not bot.replies
    security = guard(engine, clock, bot)
    await security.admit(user_id=999, chat_id=999, chat_type="private", command="/status")
    assert len(bot.notices) == 2
    clock.instant += timedelta(hours=1)
    await security.admit(user_id=999, chat_id=999, chat_type="private", command="/status")
    assert len(bot.notices) == 3
    with transaction(engine) as session:
        rows = tuple(session.scalars(select(SecurityEvent)))
    assert "intruder" not in str([row.detail for row in rows])


@pytest.mark.asyncio
async def test_SEC_52_21st_command_drops_but_emergencies_always_pass(engine: Engine) -> None:
    clock, bot = MovingClock(), Bot()
    security = guard(engine, clock, bot)

    async def admit(command: str) -> bool:
        return (
            await security.admit(user_id=123, chat_id=123, chat_type="private", command=command)
        ).accepted

    assert all([await admit("/status") for _ in range(20)])
    assert not await admit("/status") and not await admit("/status")
    assert bot.replies == [(123, "slow down")]
    assert await admit("/halt") and await admit("/pause")
    clock.instant += timedelta(seconds=3)
    assert await admit("/status")


@pytest.mark.asyncio
async def test_SEC_52_heavy_commands_have_separate_five_token_budget(engine: Engine) -> None:
    clock, bot = MovingClock(), Bot()
    security = guard(engine, clock, bot)
    for _ in range(5):
        assert (
            await security.admit(user_id=123, chat_id=123, chat_type="private", command="/report")
        ).accepted
    assert not (
        await security.admit(user_id=123, chat_id=123, chat_type="private", command="/tax")
    ).accepted
    assert (
        await security.admit(user_id=123, chat_id=123, chat_type="private", command="/status")
    ).accepted


@pytest.mark.asyncio
async def test_SEC_30_async_test_body_still_cannot_open_network_sockets() -> None:
    """The Windows loop self-pipe exception never enables test body networking."""
    import socket

    from pytest_socket import SocketBlockedError

    with pytest.raises(SocketBlockedError):
        socket.socket()


def test_SEC_34_webhook_is_urgent_and_refuses_auto(engine: Engine) -> None:
    me = {"can_join_groups": False, "can_read_all_group_messages": False}
    assert bot_security_findings(me, {"url": ""}, mode="AUTO_LIVE") == ()
    for mode in ("AUTO_PAPER", "AUTO_LIVE"):
        with pytest.raises(ConfigurationError, match="blocks automatic"):
            bot_security_findings(me, {"url": "https://example.com"}, mode=mode)
    assert "URGENT" in bot_security_findings(me, {"url": "https://example.com"}, mode="MANUAL")[0]
    assert len(bot_security_findings({}, {"url": ""}, mode="MANUAL")) == 2
    with pytest.raises(ConfigurationError):
        bot_security_findings({}, {"url": ""}, mode="AUTO_LIVE")


def test_SEC_53_masked_golden_fields_keep_price_percent_and_symbol() -> None:
    values = {
        "equity": "$25,000",
        "cash": "$1000",
        "pnl_usd": "$125",
        "tax_usd": "$25",
        "qty": "10",
        "price": "$45.00",
        "stop": "$44.00",
        "target": "$47.00",
        "percent": "1.2%",
        "symbol": "AAPL",
    }
    masked = mask_account_fields(values, enabled=True)
    assert {
        key: masked[key] for key in ("equity", "cash", "pnl_usd", "tax_usd", "qty")
    } == dict.fromkeys(("equity", "cash", "pnl_usd", "tax_usd", "qty"), "$•••")
    assert all(
        masked[key] == values[key] for key in ("price", "stop", "target", "percent", "symbol")
    )
    assert mask_account_fields(values, enabled=False) == values
