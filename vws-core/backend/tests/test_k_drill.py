"""XK-01: fake account isolation, real-path mock delivery and authenticated freshness."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.net.egress import EgressPolicy
from backend.net.http import make_client
from backend.ops import drill
from backend.ops.drill import DrillReceipt, TelegramDrillSender, read_proof, run_drill, seal_proof


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["REAL", "OFFLINE"])
async def test_XK_01_isolated_drill_and_sealed_freshness(
    clock: FrozenClock, tmp_path: Path, delivery: str
) -> None:
    async def send(text: str, policy: EgressPolicy) -> tuple[DrillReceipt, ...]:
        assert text.startswith("DRILL ·") and policy.ledger.engine.url.database == ":memory:"
        return (DrillReceipt(chat_id=123, message_id=456, bot_id=99),)

    proof = await run_drill(clock, "Offline owner", (123,), send, delivery=delivery)  # type: ignore[arg-type]
    assert proof.steps == ("HALTED", "CANCELED", "PROTECTED", "DELIVERED", "RESET")
    assert proof.eligible(clock.now() + timedelta(days=45), 45) is (delivery == "REAL")
    assert not proof.eligible(clock.now() + timedelta(days=45, seconds=1), 45)
    assert not proof.eligible(clock.now() - timedelta(seconds=1), 45)
    key = SecretStr(Fernet.generate_key().decode("ascii"))
    path = tmp_path / "latest.enc"
    assert len(seal_proof(path, proof, key)) == 64
    assert read_proof(path, key) == proof
    with pytest.raises(DataIntegrityError):
        read_proof(path, SecretStr(Fernet.generate_key().decode("ascii")))
    path.write_bytes(path.read_bytes()[:-5])
    with pytest.raises(DataIntegrityError):
        read_proof(path, key)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "wrong_owner"])
async def test_XK_01_failed_delivery_never_returns_pass(clock: FrozenClock, fault: str) -> None:
    async def send(text: str, policy: EgressPolicy) -> tuple[DrillReceipt, ...]:
        return () if fault == "missing" else (DrillReceipt(chat_id=999, message_id=1, bot_id=99),)

    with pytest.raises(DataIntegrityError):
        await run_drill(clock, "Offline owner", (123,), send)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "webhook", "stranger", "nonprivate", "receipt"])
async def test_XK_01_mock_telegram_private_delivery(
    clock: FrozenClock, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    calls = []

    def response(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        value: dict[str, Any]
        if method == "getMe":
            value = {
                "id": 99,
                "is_bot": True,
                "can_join_groups": False,
                "can_read_all_group_messages": False,
            }
        elif method == "getWebhookInfo":
            value = {"url": "https://untrusted.invalid/" if fault == "webhook" else ""}
        elif method == "getChat":
            value = {
                "id": 999 if fault == "stranger" else 123,
                "type": "group" if fault == "nonprivate" else "private",
            }
        else:
            assert method == "sendMessage"
            value = {
                "message_id": 1,
                "chat": {"id": 999 if fault == "receipt" else 123, "type": "private"},
            }
        return httpx.Response(200, json={"ok": True, "result": value})

    def factory(purpose: str, **kwargs: Any) -> object:
        return make_client(purpose, **kwargs, transport=httpx.MockTransport(response))

    monkeypatch.setattr(drill, "make_client", factory)
    settings = Settings(
        _env_file=None,
        telegram_bot_token=SecretStr("offline-test-bot"),
        telegram_callback_secret=SecretStr("x" * 32),
        telegram_allowed_user_ids=(123,),
    )
    sender = TelegramDrillSender(settings)
    if fault is not None:
        with pytest.raises(DataIntegrityError):
            await run_drill(clock, "Offline owner", (123,), sender, delivery="REAL")
    else:
        proof = await run_drill(clock, "Offline owner", (123,), sender, delivery="REAL")
        assert proof.delivery == "REAL" and proof.receipts[0].message_id == 1
        assert calls == ["getMe", "getWebhookInfo", "getChat", "sendMessage"]
