"""GD-05/06, SEC-30/51: private, outbound-only polling and bound cards."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import Alert, AlertEvent, ApprovalEvent, SecurityEvent, transaction
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    ProviderError,
)
from backend.core.system_state import SystemState, SystemStateStore
from backend.net.egress import EgressPolicy
from backend.net.http import TelegramRequest
from backend.notifications.callbacks import (
    Action,
    ApprovalGate,
    CallbackClick,
    ClickResult,
    callback_data,
)
from backend.telegram.security import TelegramSecurity, bot_security_findings

CommandBody = Callable[[str], Awaitable[tuple[str, ...]]]


def quiet_hours(now: datetime) -> bool:
    local = ensure_utc(now).astimezone(ZoneInfo("America/Chicago"))
    return local.hour >= 22 or local.hour < 7


class TelegramBot:
    def __init__(
        self,
        settings: Settings,
        state: SystemStateStore,
        clock: Clock,
        gate: ApprovalGate,
        policy: EgressPolicy,
        commands: dict[str, CommandBody],
        *,
        transport: TelegramRequest | None = None,
        polling_transport: TelegramRequest | None = None,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.settings.assert_telegram_ready()
        if (
            state.clock is not clock
            or gate.state is not state
            or gate.settings.config_hash != self.settings.config_hash
            or policy.ledger.engine is not state.engine
        ):
            raise ConfigurationError("GD-05: Telegram policies/state differ")
        self.state, self.clock, self.gate = state, clock, gate
        self.commands = dict(commands)
        token = self.settings.telegram_bot_token.get_secret_value()
        self.application: Application[Any, Any, Any, Any, Any, Any] = (
            Application.builder()
            .token(token)
            .request(transport or TelegramRequest(token, policy))
            .get_updates_request(polling_transport or TelegramRequest(token, policy))
            .concurrent_updates(8)
            .build()
        )
        self.security = TelegramSecurity(
            self.settings.telegram_allowed_user_ids,
            state.ledger,
            clock,
            notify=self.notify,
            leave=self.leave,
            reply=self.reply,
            rate=self.settings.tg_rate_per_min,
            heavy_rate=self.settings.tg_heavy_rate_per_min,
        )
        self.application.add_handler(CallbackQueryHandler(self._callback))
        self.application.add_handler(MessageHandler(filters.ALL, self._command))
        self.application.add_error_handler(self._error)
        self._delivery_lock = asyncio.Lock()
        self._admitted = False

    async def leave(self, chat_id: int) -> None:
        await self.application.bot.leave_chat(chat_id)

    async def reply(self, chat_id: int, text: str) -> None:
        if chat_id not in self.settings.telegram_allowed_user_ids:
            raise DataIntegrityError("SEC-51: response target is not an owner private chat")
        if len(text.encode("utf-16-le")) // 2 > 4096:
            raise DataIntegrityError("GD-05: message exceeds Telegram boundary")
        await self.application.bot.send_message(chat_id, text, parse_mode="HTML")

    async def notify(self, text: str, urgent: bool) -> None:
        from html import escape

        # Normal digests/alerts are persisted and replayed by their job paths.
        if quiet_hours(self.clock.now()) and not urgent:
            self.state.ledger.append(
                SecurityEvent, kind="QUIET_NOTICE_QUEUED", detail={"text": text}
            )
            return
        for owner in self.settings.telegram_allowed_user_ids:
            await self.reply(owner, escape(text))

    def keyboard(
        self, proposal_id: UUID, chat_id: int, *, ticket: bool = False
    ) -> InlineKeyboardMarkup:
        items: tuple[tuple[str, Action], ...] = (
            (("I placed it", "P"), ("Skip", "S"))
            if ticket
            else (("Approve", "A"), ("Reject", "R"), ("Details", "D"))
        )
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=callback_data(action, proposal_id, chat_id, self.settings),
                    )
                    for label, action in items
                ]
            ]
        )

    async def deliver(self, alert_id: UUID, chat_id: int) -> bool:
        if not self._admitted or chat_id not in self.settings.telegram_allowed_user_ids:
            raise ConfigurationError("SEC-51: private bot admission required before delivery")
        async with self._delivery_lock:
            self.state.ledger.verify_chain()
            with Session(self.state.engine) as session:
                alert = session.get(Alert, alert_id)
            if alert is None:
                raise DataIntegrityError("GD-05: cannot deliver an unknown alert")
            if self.state.ledger.current_alert_status(alert_id) != "PENDING":
                return False
            if self.clock.now() >= alert.expires_at:
                self.state.ledger.append(
                    ApprovalEvent, alert_id=alert_id, action="EXPIRED", reasons=[]
                )
                return False
            if quiet_hours(self.clock.now()) or self.state.current() != SystemState.RUNNING:
                return False
            try:
                message = await self.application.bot.send_message(
                    chat_id,
                    self._updated_card(alert),
                    parse_mode="HTML",
                    reply_markup=self.keyboard(alert.proposal_id, chat_id),
                )
                self.state.ledger.append(
                    AlertEvent,
                    alert_id=alert_id,
                    state="SENT",
                    telegram_chat_id=chat_id,
                    telegram_message_id=message.message_id,
                    reason="private delivery confirmed",
                )
                return True
            except Exception as exc:
                self.state.halt_for_error(exc)
                self.state.ledger.append(
                    SecurityEvent,
                    kind="TELEGRAM_DELIVERY_FAILED",
                    detail={"alert_id": str(alert_id), "error_type": type(exc).__name__},
                )
                raise ProviderError("GD-05: Telegram delivery failed; entries halted") from None

    def _updated_card(self, alert: Alert) -> str:
        from html import escape

        with Session(self.state.engine) as session:
            note = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "ALERT_ANNOTATED",
                    SecurityEvent.detail["alert_id"].as_string() == str(alert.id),
                )
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
        text = (
            alert.card_text
            if note is None
            else alert.card_text + "\nUpdate: " + escape(note.detail["note"])
        )
        if len(text.encode("utf-16-le")) // 2 > 4096:
            raise DataIntegrityError("GD-05: annotated card exceeds message boundary")
        return text

    async def annotate(self, alert_id: UUID, note: str) -> bool:
        from backend.core.content import sanitize_text

        if not isinstance(note, str) or not 1 <= len(note) <= 600 or note != sanitize_text(note):
            raise DataIntegrityError("GD-05: annotation must be bounded public text")
        async with self.gate._lock:
            with Session(self.state.engine) as session:
                alert = session.get(Alert, alert_id)
                delivery = session.scalar(
                    select(AlertEvent)
                    .where(AlertEvent.alert_id == alert_id, AlertEvent.state == "SENT")
                    .limit(1)
                )
            if alert is None or self.state.ledger.current_alert_status(alert_id) not in {
                "PENDING",
                "SENT",
            }:
                return False
            if alert.config_hash != self.settings.config_hash:
                error = DataIntegrityError("GD-05: annotation alert policy differs")
                self.state.halt_for_error(error)
                raise error
            record = self.state.ledger.append(
                SecurityEvent,
                kind="ALERT_ANNOTATED",
                detail={"alert_id": str(alert_id), "note": note},
            )
            if delivery is not None and not quiet_hours(self.clock.now()):
                try:
                    await self._edit(
                        self._updated_card(alert),
                        delivery,
                        proposal_id=alert.proposal_id,
                    )
                    self.state.ledger.append(
                        SecurityEvent,
                        kind="ANNOTATION_DELIVERED",
                        detail={"note_id": str(record.id)},
                    )
                except Exception as exc:
                    self.state.halt_for_error(exc)
                    raise ProviderError(
                        "GD-05: annotation delivery failed; entries halted"
                    ) from None
            return True

    async def _edit(
        self, text: str, delivery: AlertEvent, *, proposal_id: UUID | None = None
    ) -> None:
        chat, message = delivery.telegram_chat_id, delivery.telegram_message_id
        if (
            not self._admitted
            or type(chat) is not int
            or chat not in self.settings.telegram_allowed_user_ids
            or type(message) is not int
            or message <= 0
        ):
            raise ConfigurationError("SEC-51: edit requires an admitted owner private binding")
        await self.application.bot.edit_message_text(
            text,
            chat_id=chat,
            message_id=message,
            parse_mode="HTML",
            reply_markup=None if proposal_id is None else self.keyboard(proposal_id, chat),
        )

    async def flush_annotations(self) -> None:
        if quiet_hours(self.clock.now()):
            return
        async with self.gate._lock:
            with Session(self.state.engine) as session:
                notes = tuple(
                    session.scalars(
                        select(SecurityEvent)
                        .where(SecurityEvent.kind == "ALERT_ANNOTATED")
                        .order_by(SecurityEvent.seq)
                    )
                )
                sent = {
                    row.detail["note_id"]
                    for row in session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "ANNOTATION_DELIVERED")
                    )
                }
            latest = {row.detail["alert_id"]: row for row in notes}
            for key, note in latest.items():
                if (
                    str(note.id) in sent
                    or self.state.ledger.current_alert_status(UUID(key)) != "SENT"
                ):
                    continue
                with Session(self.state.engine) as session:
                    alert = session.get(Alert, UUID(key))
                    delivery = session.scalar(
                        select(AlertEvent)
                        .where(AlertEvent.alert_id == UUID(key), AlertEvent.state == "SENT")
                        .limit(1)
                    )
                if alert is None or delivery is None:
                    error = DataIntegrityError("GD-05: queued annotation lost delivery provenance")
                    self.state.halt_for_error(error)
                    raise error
                try:
                    await self._edit(
                        self._updated_card(alert), delivery, proposal_id=alert.proposal_id
                    )
                    self.state.ledger.append(
                        SecurityEvent, kind="ANNOTATION_DELIVERED", detail={"note_id": str(note.id)}
                    )
                except Exception as exc:
                    self.state.halt_for_error(exc)
                    raise ProviderError("GD-05: queued annotation failed; entries halted") from None

    async def expire_alerts(self) -> int:
        """Consume expired cards even during HALT; terminal clicks remain closed."""
        count = 0
        self.state.ledger.verify_chain()
        async with self.gate._lock:
            with Session(self.state.engine) as session:
                alerts = tuple(
                    session.scalars(
                        select(Alert).where(
                            Alert.expires_at <= self.clock.now(),
                            ~select(AlertEvent.id)
                            .where(
                                AlertEvent.alert_id == Alert.id,
                                AlertEvent.state.in_(
                                    ("APPROVED", "REJECTED", "EXPIRED", "REVALIDATION_FAILED")
                                ),
                            )
                            .exists(),
                        )
                    )
                )
            for alert in alerts:
                with transaction(self.state.engine) as session:
                    latest = self.state.ledger._latest_alert_event(session, alert.id)
                    if latest is None or latest.state not in {"PENDING", "SENT"}:
                        continue
                    self.state.ledger.append_in_session(
                        session, ApprovalEvent, alert_id=alert.id, action="EXPIRED", reasons=[]
                    )
                count += 1
                if latest.state == "SENT":
                    try:
                        await self._edit("Expired. No ticket.", latest)
                    except Exception as exc:
                        self.state.halt_for_error(exc)
                        self.state.ledger.append(
                            SecurityEvent,
                            kind="EXPIRED_CARD_EDIT_FAILED",
                            detail={"alert_id": str(alert.id), "error_type": type(exc).__name__},
                        )
                        raise ProviderError(
                            "GD-05: expiry edit failed; card already closed"
                        ) from None
        return count

    async def invalidate(self, alert_id: UUID, reason: str) -> bool:
        """Changed public facts consume an undelivered or delivered setup."""
        from backend.core.content import sanitize_text

        if (
            not isinstance(reason, str)
            or not 1 <= len(reason) <= 600
            or reason != sanitize_text(reason)
        ):
            raise DataIntegrityError("GD-05: invalidation requires bounded public evidence")
        self.state.ledger.verify_chain()
        async with self.gate._lock:
            with transaction(self.state.engine) as session:
                latest = self.state.ledger._latest_alert_event(session, alert_id)
                if latest is None or latest.state not in {"PENDING", "SENT"}:
                    return False
                self.state.ledger.append_in_session(
                    session,
                    ApprovalEvent,
                    alert_id=alert_id,
                    action="REVALIDATION_FAILED",
                    reasons=[{"rule_id": "PREMARKET", "message": reason}],
                )
            if latest.state == "SENT":
                from html import escape

                try:
                    await self._edit("Setup closed: " + escape(reason) + "\nNo ticket.", latest)
                except Exception as exc:
                    self.state.halt_for_error(exc)
                    raise ProviderError("GD-05: closed-card edit failed; entries halted") from None
        return True

    async def flush_pending(self) -> None:
        await self.flush_annotations()
        if not quiet_hours(self.clock.now()):
            with Session(self.state.engine) as session:
                notices = tuple(
                    session.scalars(
                        select(SecurityEvent)
                        .where(SecurityEvent.kind == "QUIET_NOTICE_QUEUED")
                        .order_by(SecurityEvent.seq)
                    )
                )
                sent = {
                    row.detail["notice_id"]
                    for row in session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "QUIET_NOTICE_DELIVERED")
                    )
                }
            for notice in notices:
                if str(notice.id) not in sent:
                    await self.notify(notice.detail["text"], False)
                    self.state.ledger.append(
                        SecurityEvent,
                        kind="QUIET_NOTICE_DELIVERED",
                        detail={"notice_id": str(notice.id)},
                    )
        with Session(self.state.engine) as session:
            ids = tuple(
                session.scalars(
                    select(Alert.id)
                    .where(
                        ~select(AlertEvent.id)
                        .where(AlertEvent.alert_id == Alert.id, AlertEvent.state != "PENDING")
                        .exists()
                    )
                    .order_by(Alert.seq)
                )
            )
        # Each proposal binds one original actionable message and one owner.
        for alert_id in ids:
            await self.deliver(alert_id, self.settings.telegram_allowed_user_ids[0])

    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if (
            query is None
            or query.message is None
            or query.data is None
            or not isinstance(query.data, str)
        ):
            self.state.ledger.append(SecurityEvent, kind="CALLBACK_MALFORMED_UPDATE", detail={})
            return
        chat = query.message.chat
        admitted = await self.security.admit(
            user_id=query.from_user.id, chat_id=chat.id, chat_type=chat.type, command="/callback"
        )
        if not admitted.accepted:
            return
        answered = False

        async def acknowledge(text: str) -> None:
            nonlocal answered
            await query.answer(text)
            answered = True

        result = ClickResult.model_validate(
            await self.gate.handle(
                CallbackClick(
                    user_id=query.from_user.id,
                    chat_id=chat.id,
                    chat_type=chat.type,
                    message_id=query.message.message_id,
                    data=query.data,
                ),
                acknowledge=acknowledge,
            )
        )
        if result.status == "IGNORED":
            return
        if not answered:
            await query.answer(
                "Expired or already handled." if result.status == "HANDLED" else "Recorded."
            )
        if result.status == "HANDLED":
            return
        proposal_id = UUID(query.data.split(":")[2])
        markup = (
            self.keyboard(proposal_id, chat.id, ticket=result.status == "TICKET")
            if result.status in {"TICKET", "DETAILS"}
            else None
        )
        await query.edit_message_text(
            cast(str, result.text), parse_mode="HTML", reply_markup=markup
        )
        for page in result.continuation:
            await self.reply(chat.id, page)

    async def _command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        from html import escape

        user, chat, message = update.effective_user, update.effective_chat, update.effective_message
        if user is None or chat is None or message is None:
            return
        text = message.text or ""
        admission = await self.security.admit(
            user_id=user.id, chat_id=chat.id, chat_type=chat.type, command=text
        )
        if not admission.accepted:
            return
        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0]
        if command in {"/halt", "/pause"}:
            from backend.core.content import sanitize_text

            self.state.escalate(
                SystemState.HALTED if command == "/halt" else SystemState.REDUCE_ONLY,
                "Telegram operator " + command + ": " + sanitize_text(argument)[:280],
            )
            self.state.ledger.append(
                SecurityEvent,
                kind="TELEGRAM_HALT" if command == "/halt" else "TELEGRAM_PAUSE",
                telegram_user_id=user.id,
                detail={},
            )
            await self.reply(
                chat.id, "Entries stopped. Held exits and protection remain available."
            )
        elif command in self.commands:
            for page in await self.commands[command](argument):
                await self.reply(chat.id, page)
        else:
            await self.reply(
                chat.id,
                escape(
                    "Use /help for available private commands. Resets and upgrades require the host."
                ),
            )

    async def _error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        self.state.halt_for_error(
            error if isinstance(error, Exception) else ProviderError("Telegram handler failed")
        )
        self.state.ledger.append(
            SecurityEvent,
            kind="TELEGRAM_HANDLER_FAILED",
            detail={"error_type": type(error).__name__},
        )

    async def start(self) -> None:
        await self.application.initialize()
        me = await self.application.bot.get_me()
        webhook = await self.application.bot.get_webhook_info()
        findings = bot_security_findings(
            me.to_dict(), webhook.to_dict(), mode=self.settings.execution_mode
        )
        for finding in findings:
            await self.notify(finding, "URGENT" in finding)
        # Polling cannot coexist with a webhook. Preserve a configured webhook
        # and require the owner to remove it, instead of silently clearing it.
        if webhook.url:
            raise ConfigurationError("SEC-34: remove the configured webhook before private polling")
        for owner in self.settings.telegram_allowed_user_ids:
            chat = await self.application.bot.get_chat(owner)
            if chat.type != "private" or chat.id != owner:
                raise ConfigurationError("SEC-51: Telegram recipient is not an owner private chat")
        await self.application.start()
        updater = self.application.updater
        if updater is None:
            raise ConfigurationError("GD-05: polling updater unavailable")
        await updater.start_polling(
            timeout=20,
            poll_interval=1,
            bootstrap_retries=0,
            drop_pending_updates=False,
            allowed_updates=("message", "callback_query"),
        )
        self._admitted = True

    async def stop(self) -> None:
        self._admitted = False
        updater = self.application.updater
        if updater is not None and updater.running:
            await updater.stop()
        if self.application.running:
            await self.application.stop()
        await self.application.shutdown()
