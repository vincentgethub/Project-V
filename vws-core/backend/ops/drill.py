"""XK-01: isolated halt/cancel/protect/reset drill and authenticated local proof."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.config import Settings
from backend.core.database import SecurityEvent, SystemEvent, create_database, create_schema
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.domain.models import FrozenModel, UTCDateTime
from backend.execution.modes import ModeStore
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import make_client
from backend.notifications.control import downgrade
from backend.ops.anchors import LedgerAnchors, controlled_path
from backend.ops.security import _operator
from backend.telegram.security import bot_security_findings


class DrillReceipt(FrozenModel):
    chat_id: int = Field(strict=True, gt=0)
    message_id: int = Field(strict=True, gt=0)
    bot_id: int = Field(strict=True, gt=0)


class DrillProof(FrozenModel):
    created_at: UTCDateTime
    operator: str = Field(strict=True, min_length=1, max_length=128)
    delivery: Literal["REAL", "OFFLINE"]
    recipients: tuple[int, ...] = Field(min_length=1, max_length=20)
    receipts: tuple[DrillReceipt, ...] = Field(min_length=1, max_length=20)
    scratch_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    steps: tuple[Literal["HALTED", "CANCELED", "PROTECTED", "DELIVERED", "RESET"], ...]

    @model_validator(mode="after")
    def complete(self) -> Self:
        if (
            tuple(row.chat_id for row in self.receipts) != self.recipients
            or len(set(self.recipients)) != len(self.recipients)
            or any(type(owner) is not int or owner <= 0 for owner in self.recipients)
            or self.steps != ("HALTED", "CANCELED", "PROTECTED", "DELIVERED", "RESET")
            or self.operator != _operator(self.operator)
        ):
            raise ValueError("XK-01: complete attributed private drill evidence required")
        return self

    def eligible(self, now: datetime, days: int) -> bool:
        if type(days) is not int or days not in {31, 45}:
            raise DataIntegrityError("XK-01: fixed drill freshness threshold required")
        return self.delivery == "REAL" and timedelta(0) <= ensure_utc(
            now
        ) - self.created_at <= timedelta(days=days)


class FakeDrillExecutor:
    """No SDK/client/secret/account binding; only scratch evidence can change."""

    def __init__(self, state: SystemStateStore) -> None:
        self.state = state
        self.unfilled = True
        self.held_qty = 1
        self.stop_qty = 1

    async def monitor(self) -> None:
        if self.state.current() != SystemState.HALTED:
            raise DataIntegrityError("XK-01: fake cancellation cannot precede durable HALT")
        self.unfilled = False
        self.state.ledger.append(
            SecurityEvent,
            kind="DRILL_CANCELLATION",
            detail={
                "unfilled_canceled": True,
                "held_qty": self.held_qty,
                "stop_qty": self.stop_qty,
            },
        )


DrillSender = Callable[[str, EgressPolicy], Awaitable[tuple[DrillReceipt, ...]]]


async def run_drill(
    clock: Clock,
    operator: str,
    recipients: tuple[int, ...],
    sender: DrillSender,
    *,
    delivery: Literal["REAL", "OFFLINE"] = "OFFLINE",
) -> DrillProof:
    actor = _operator(operator)
    engine = create_database("sqlite:///:memory:")
    try:
        create_schema(engine)
        state = SystemStateStore(engine, clock, ConsoleNotifier())
        settings = Settings(
            _env_file=None,
            execution_mode="AUTO_PAPER",
            paper_trading=True,
            broker_account_type="CASH",
            telegram_allowed_user_ids=recipients,
        )
        modes = ModeStore(settings, state, "DRILL-PAPER-FAKE")
        executor = FakeDrillExecutor(state)
        await downgrade(state, modes, executor, "HALT", actor, "DRILL /halt")
        if (
            state.current() != SystemState.HALTED
            or executor.unfilled
            or executor.stop_qty != executor.held_qty
        ):
            raise DataIntegrityError("XK-01: scratch HALT/cancellation/protection failed")
        policy = EgressPolicy(build_allowlist(mode="MANUAL"), state.ledger)
        async with asyncio.timeout(60):
            receipts = await sender(
                "DRILL · Scratch account halted; fake unfilled entry canceled; held stop protection retained. No real account was touched.",
                policy,
            )
        if not isinstance(receipts, tuple) or not 1 <= len(receipts) <= 20:
            raise DataIntegrityError("XK-01: bounded immutable delivery receipts required")
        receipts = tuple(DrillReceipt.model_validate(row) for row in receipts)
        if tuple(row.chat_id for row in receipts) != recipients:
            raise DataIntegrityError(
                "XK-01: every owner needs a verified private delivery before reset"
            )
        state.ledger.append(
            SecurityEvent,
            kind="DRILL_TELEGRAM_DELIVERED",
            detail={
                "receipts": [row.model_dump(mode="json") for row in receipts],
                "delivery": delivery,
            },
        )
        state.operator_reset(
            actor, "DRILL audited CLI reset after proven cancellation and delivery"
        )
        with Session(engine) as session:
            events = tuple(session.scalars(select(SystemEvent).order_by(SystemEvent.seq)))
        if (
            state.current() != SystemState.RUNNING
            or not any(row.state == "HALTED" for row in events)
            or events[-1].event_type != "OPERATOR_RESET"
        ):
            raise DataIntegrityError("XK-01: scratch reset lacks durable history")
        state.ledger.append(
            SecurityEvent,
            kind="KILL_SWITCH_DRILL_PASSED",
            detail={"scratch": True, "delivery": delivery, "operator": actor},
        )
        anchor = LedgerAnchors(state.ledger, clock).create()
        return DrillProof(
            created_at=clock.now(),
            operator=actor,
            delivery=delivery,
            recipients=recipients,
            receipts=receipts,
            scratch_digest=anchor.digest,
            steps=("HALTED", "CANCELED", "PROTECTED", "DELIVERED", "RESET"),
        )
    except (DataIntegrityError, ProviderError):
        raise
    except Exception:
        raise DataIntegrityError("XK-01: scratch drill failed; no PASS proof published") from None
    finally:
        engine.dispose()


class TelegramDrillSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = Settings.validated_copy(settings)
        self.settings.assert_telegram_ready()

    async def __call__(self, text: str, policy: EgressPolicy) -> tuple[DrillReceipt, ...]:
        if not text.startswith("DRILL ·"):
            raise DataIntegrityError("XK-01: drill notice must be marked DRILL")
        prefix = (
            "https://api.telegram.org/bot"
            + self.settings.telegram_bot_token.get_secret_value()
            + "/"
        )
        async with make_client(
            "telegram_api", policy=policy, allow_redirects=False, max_response_bytes=65536
        ) as client:

            async def request(method: str, payload: dict[str, object]) -> dict[str, object]:
                response = await client.post(prefix + method, json=payload)
                body = response.json()
                if (
                    response.status_code != 200
                    or not isinstance(body, dict)
                    or body.get("ok") is not True
                    or not isinstance(body.get("result"), dict)
                ):
                    raise ProviderError("XK-01: Telegram drill admission or delivery is unverified")
                return dict(body["result"])

            me, webhook = await request("getMe", {}), await request("getWebhookInfo", {})
            if me.get("is_bot") is not True or bot_security_findings(me, webhook, mode="MANUAL"):
                raise DataIntegrityError(
                    "XK-01: private bot security must be verified before drill"
                )
            receipts = []
            for owner in self.settings.telegram_allowed_user_ids:
                chat = await request("getChat", {"chat_id": owner})
                if chat.get("id") != owner or chat.get("type") != "private":
                    raise DataIntegrityError("XK-01: owner private chat could not be verified")
                message = await request("sendMessage", {"chat_id": owner, "text": text})
                returned_chat = message.get("chat")
                if (
                    not isinstance(returned_chat, dict)
                    or returned_chat.get("id") != owner
                    or returned_chat.get("type") != "private"
                ):
                    raise DataIntegrityError(
                        "XK-01: delivered DRILL message lost its private binding"
                    )
                receipts.append(
                    DrillReceipt.model_validate(
                        {
                            "chat_id": owner,
                            "message_id": message.get("message_id"),
                            "bot_id": me.get("id"),
                        }
                    )
                )
            return tuple(receipts)


def seal_proof(path: Path, proof: DrillProof, key: SecretStr) -> str:
    checked = DrillProof.model_validate(proof)
    try:
        payload = checked.model_dump_json().encode()
        destination = controlled_path(path)
        token = Fernet(key.get_secret_value().encode("ascii")).encrypt(payload)
        destination.write_bytes(token)
        restored = read_proof(destination, key)
        if restored != checked:
            raise ValueError("drill artifact verification differs")
        return hashlib.sha256(payload).hexdigest()
    except Exception:
        raise DataIntegrityError(
            "XK-01: authenticated drill artifact could not be verified"
        ) from None


def read_proof(path: Path, key: SecretStr) -> DrillProof:
    import json

    try:
        source = controlled_path(path)
        if source.stat().st_size > 65536:
            raise ValueError("drill artifact exceeds bound")
        payload = json.loads(
            Fernet(key.get_secret_value().encode("ascii")).decrypt(source.read_bytes())
        )
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        return DrillProof.model_validate(payload)
    except Exception:
        raise DataIntegrityError("XK-01: drill proof is unavailable or unauthenticated") from None
