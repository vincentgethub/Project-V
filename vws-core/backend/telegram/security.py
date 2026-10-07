"""SEC-50..53: private chats, owner limits and account-amount masking."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from backend.core.clock import Clock, ensure_utc
from backend.core.content import sanitize_text
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger

_HEAVY = frozenset({"/watch", "/pnl", "/report", "/edge", "/tax", "/progress"})
_UNLIMITED = frozenset({"/halt", "/pause"})
_MASKED = frozenset(
    {
        "equity",
        "cash",
        "settled_cash",
        "buying_power",
        "pnl_usd",
        "deposit_usd",
        "withdrawal_usd",
        "tax_usd",
        "position_value",
        "qty",
        "quantity",
    }
)
Notify = Callable[[str, bool], Awaitable[None]]
Leave = Callable[[int], Awaitable[None]]
Reply = Callable[[int, str], Awaitable[None]]


@dataclass(frozen=True)
class Admission:
    """SEC-51/52: handlers may run only after an accepted admission."""

    accepted: bool
    reason: str


@dataclass
class _Bucket:
    tokens: int
    updated_at: datetime
    warned: bool = False


class TelegramSecurity:
    """SEC-51/52: network effects occur after the local admission lock."""

    def __init__(
        self,
        allowed_ids: tuple[int, ...],
        ledger: Ledger,
        clock: Clock,
        *,
        notify: Notify,
        leave: Leave,
        reply: Reply,
        rate: int = 20,
        heavy_rate: int = 5,
    ) -> None:
        if (
            not isinstance(allowed_ids, tuple)
            or not allowed_ids
            or any(type(value) is not int or not 0 < value < 2**63 for value in allowed_ids)
            or len(allowed_ids) != len(set(allowed_ids))
            or type(rate) is not int
            or not 1 <= rate <= 20
            or type(heavy_rate) is not int
            or not 1 <= heavy_rate <= 5
        ):
            raise ConfigurationError("SEC-52: private owner allowlist or rates are invalid")
        self.allowed_ids = frozenset(allowed_ids)
        self.ledger, self.clock = ledger, clock
        self.notify, self.leave, self.reply = notify, leave, reply
        self.rate, self.heavy_rate = rate, heavy_rate
        self._buckets: dict[tuple[int, bool], _Bucket] = {}
        self._lock = asyncio.Lock()

    def _take(self, user_id: int, heavy: bool, now: datetime) -> tuple[bool, bool]:
        rate = self.heavy_rate if heavy else self.rate
        capacity = rate * 60_000_000
        bucket = self._buckets.setdefault((user_id, heavy), _Bucket(capacity, now))
        elapsed = now - bucket.updated_at
        if elapsed < timedelta(0):
            raise DataIntegrityError("SEC-52: rate-limit clock moved backward")
        microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
        bucket.tokens = min(capacity, bucket.tokens + microseconds * rate)
        bucket.updated_at = now
        if bucket.tokens >= 60_000_000:
            bucket.tokens -= 60_000_000
            bucket.warned = False
            return True, False
        warn = not bucket.warned
        bucket.warned = True
        return False, warn

    async def admit(
        self,
        *,
        user_id: int,
        chat_id: int,
        chat_type: str,
        command: str,
        username: str | None = None,
    ) -> Admission:
        """SEC-51/52: outsiders receive no reply and cannot reach a handler."""
        if (
            type(user_id) is not int
            or not 0 < user_id < 2**63
            or type(chat_id) is not int
            or not -(2**63) < chat_id < 2**63
            or chat_id == 0
            or not isinstance(chat_type, str)
            or not isinstance(command, str)
            or (username is not None and not isinstance(username, str))
        ):
            raise DataIntegrityError("SEC-51: Telegram update identity is malformed")
        parsed = command.split(maxsplit=1)[0].split("@", 1)[0] if command.strip() else "/unknown"
        cmd = parsed if re.fullmatch(r"/[a-z_]{1,32}", parsed) else "/unknown"
        now = ensure_utc(self.clock.now())
        notice: tuple[str, bool] | None = None
        slow = False
        async with self._lock:
            self.ledger.verify_chain()
            if chat_type != "private":
                self.ledger.append(
                    SecurityEvent,
                    kind="TELEGRAM_NONPRIVATE",
                    detail={"user_id": user_id, "chat_id": chat_id},
                )
                result = Admission(False, "private chats only")
            elif user_id not in self.allowed_ids or chat_id != user_id:
                self.ledger.append(
                    SecurityEvent,
                    kind="TELEGRAM_STRANGER",
                    detail={"user_id": user_id, "command": cmd},
                )
                with transaction(self.ledger.engine) as session:
                    recent = tuple(
                        session.scalars(
                            select(SecurityEvent).where(SecurityEvent.ts >= now - timedelta(days=1))
                        )
                    )
                attempts = tuple(
                    row
                    for row in recent
                    if row.kind == "TELEGRAM_STRANGER" and row.detail.get("user_id") == user_id
                )
                prior = tuple(row for row in recent if row.kind == "TELEGRAM_STRANGER_NOTICE")
                if any(row.ts > now for row in recent):
                    raise DataIntegrityError("SEC-52: stranger history is in the future")
                urgent = len(attempts) >= 5
                last = max((row.ts for row in prior), default=None)
                escalated = any(row.detail.get("urgent") is True for row in prior)
                if last is None or now - last >= timedelta(hours=1) or (urgent and not escalated):
                    # Usernames are ephemeral display text, never stored in the ledger.
                    handle = "" if not username else ", @" + sanitize_text(username, limit=64)
                    notice = (f"Someone ({user_id}{handle}) tried {cmd}", urgent)
                    self.ledger.append(
                        SecurityEvent,
                        kind="TELEGRAM_STRANGER_NOTICE",
                        detail={"user_id": user_id, "urgent": urgent},
                    )
                result = Admission(False, "owner allowlist only")
            elif cmd in _UNLIMITED:
                result = Admission(True, "emergency command")
            else:
                normal, slow = self._take(user_id, False, now)
                heavy, heavy_slow = (
                    self._take(user_id, True, now) if normal and cmd in _HEAVY else (True, False)
                )
                slow = slow or heavy_slow
                result = Admission(
                    normal and heavy, "accepted" if normal and heavy else "rate limited"
                )
        if chat_type != "private":
            await self.leave(chat_id)
        if notice is not None:
            await self.notify(*notice)
        if slow:
            await self.reply(chat_id, "slow down")
        return result


def bot_security_findings(
    me: Mapping[str, object],
    webhook: Mapping[str, object],
    *,
    mode: str,
    ledger: Ledger | None = None,
) -> tuple[str, ...]:
    """SEC-34/50: unknown BotFather facts cannot satisfy live prerequisites."""
    if mode not in {"MANUAL", "AUTO_PAPER", "AUTO_LIVE"}:
        raise ConfigurationError("SEC-50: bot check requires a known mode")
    url = webhook.get("url")
    if not isinstance(url, str):
        raise DataIntegrityError("SEC-34: webhook URL could not be verified")
    warnings: list[str] = []
    if url:
        warnings.append("URGENT: bot token may be leaked; webhook is configured")
        if ledger is not None:
            ledger.append(SecurityEvent, kind="TELEGRAM_WEBHOOK_DETECTED", detail={"urgent": True})
    for name in ("can_join_groups", "can_read_all_group_messages"):
        if me.get(name) is not False:
            warnings.append("WARN: BotFather setting " + name + " is not verified false")
    if (url and mode.startswith("AUTO_")) or (warnings and mode == "AUTO_LIVE"):
        raise ConfigurationError(
            "SEC-34/50: bot security blocks automatic mode; " + "; ".join(warnings)
        )
    return tuple(warnings)


def mask_account_fields(values: Mapping[str, str], *, enabled: bool) -> dict[str, str]:
    """SEC-53: named account dollars and shares hide; prices and percentages stay."""
    if (
        type(enabled) is not bool
        or not isinstance(values, Mapping)
        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in values.items())
    ):
        raise DataIntegrityError("SEC-53: rendered account field inventory is invalid")
    return {key: "$•••" if enabled and key in _MASKED else value for key, value in values.items()}
