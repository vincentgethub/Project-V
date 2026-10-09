"""SEC-73: local-first host adapters, private notices and read-only reports."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Self
from uuid import UUID

import pytest
from alpaca.trading.enums import AccountStatus
from pydantic import SecretStr

from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemState
from backend.funding.activities import ActivityBatch, parse_activity
from backend.net.egress import EgressPolicy, build_allowlist
from backend.ops.read_checks import PaperAccountCheck, ReadChecksClient
from backend.tests.test_accounting_service import fee_schedule
from backend.tests.test_security_cli import MemorySecrets, make_security_context
from vws import security_cli as module

context = make_security_context


def bound(context: module.SecurityContext, monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings.validated_copy(
        context.settings.model_copy(
            update={
                "broker_api_key": SecretStr("TEST_ONLY_PAPER_ID"),
                "broker_secret_key": SecretStr("TEST_ONLY_PAPER_SECRET"),
                "telegram_bot_token": SecretStr("123456:TEST_ONLY_abcdefghijklmnopqrstuvwxyz"),
                "telegram_callback_secret": SecretStr("TEST_ONLY_CALLBACK" * 3),
                "telegram_allowed_user_ids": (123,),
            }
        )
    )
    monkeypatch.setattr(module, "load_host_settings", lambda *args: settings)
    monkeypatch.setattr(module, "configure_egress", lambda *args: None)
    monkeypatch.setattr(module, "PROJECT", Path(__file__).resolve().parents[2])
    monkeypatch.setattr(
        module,
        "_require_network_policy",
        lambda *args: EgressPolicy(build_allowlist(), context.ledger),
    )
    return settings


@pytest.mark.asyncio
async def test_SEC_73_external_adapters_refuse_before_local_halt(
    context: module.SecurityContext,
) -> None:
    for action in (
        module.panic_notify(context, MemorySecrets(), "fixture"),
        module.panic_activities(
            context, MemorySecrets(), context.ledger.clock.now() - timedelta(days=30)
        ),
    ):
        with pytest.raises(ConfigurationError, match="HALT first"):
            await action


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "groups", "webhook", "group_chat", "wrong_chat"])
async def test_SEC_73_panic_notice_only_reaches_verified_private_owner(
    context: module.SecurityContext, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    bound(context, monkeypatch)
    context.state.escalate(SystemState.HALTED, "local fixture panic")
    sent = []

    async def read(
        self: ReadChecksClient, token: SecretStr, method: str, *, chat_id: int | None = None
    ) -> object:
        assert context.state.current() == SystemState.HALTED
        if method == "getMe":
            return {"can_join_groups": fault == "groups", "can_read_all_group_messages": False}
        if method == "getWebhookInfo":
            return {"url": "https://example.invalid" if fault == "webhook" else ""}
        return {
            "type": "group" if fault == "group_chat" else "private",
            "id": 999 if fault == "wrong_chat" else chat_id,
        }

    class Bot:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.request = kwargs["request"]

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            await self.request.shutdown()

        async def send_message(self, chat_id: int, text: str) -> None:
            sent.append((chat_id, text))

    import telegram

    monkeypatch.setattr(ReadChecksClient, "telegram", read)
    monkeypatch.setattr(telegram, "Bot", Bot)
    if fault:
        with pytest.raises(ConfigurationError):
            await module.panic_notify(context, MemorySecrets(), "HALTED fixture")
        assert sent == []
    else:
        await module.panic_notify(context, MemorySecrets(), "HALTED fixture")
        assert sent == [(123, "HALTED fixture")]
    context.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "full_page", "missing_identity"])
async def test_SEC_73_read_report_lists_nonfill_and_unrecognized_orders_only(
    context: module.SecurityContext, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    bound(context, monkeypatch)
    context.state.escalate(SystemState.HALTED, "local fixture panic")
    identity = UUID(int=1)
    now = context.ledger.clock.now()
    activity = parse_activity(
        {
            "id": "dividend",
            "activity_type": "DIV",
            "date": now.date().isoformat(),
            "net_amount": "1.00",
        },
        str(identity),
        "PAPER",
        now,
        fee_schedule(),
    )
    closed = []

    async def account(self: ReadChecksClient, *args: object) -> PaperAccountCheck:
        assert context.state.current() == SystemState.HALTED
        return PaperAccountCheck(
            account_id=identity,
            status=AccountStatus.ACTIVE,
            currency="USD",
            buying_power=Decimal(1000),
            equity=Decimal(1000),
            trading_blocked=False,
            account_blocked=False,
            trade_suspended_by_user=False,
        )

    async def orders(self: ReadChecksClient, settings: Settings) -> object:
        if fault == "full_page":
            return [{"client_order_id": "unknown"}] * 500
        return [
            {
                "client_order_id": None if fault == "missing_identity" else "other-trade",
                "id": str(UUID(int=2)),
            }
        ]

    class Source:
        def __init__(self, *args: object) -> None:
            self.client = self

        async def aclose(self) -> None:
            closed.append(True)

        async def read_activities(
            self, since: datetime, until: datetime, fees: object
        ) -> ActivityBatch:
            assert since == now - timedelta(days=30)
            return ActivityBatch(
                account_id=str(identity),
                env="PAPER",
                as_of=until,
                complete_history=False,
                activities=(activity,),
            )

    monkeypatch.setattr(ReadChecksClient, "account", account)
    monkeypatch.setattr(ReadChecksClient, "open_orders", orders)
    import backend.funding.activities as activities_module

    monkeypatch.setattr(activities_module, "AlpacaActivitiesSource", Source)
    if fault:
        with pytest.raises(DataIntegrityError):
            await module.panic_activities(context, MemorySecrets(), now - timedelta(days=30))
    else:
        output = await module.panic_activities(context, MemorySecrets(), now - timedelta(days=30))
        assert (
            len(output) == 2 and "DIV $1.00" in output[0] and "Unrecognized open order" in output[1]
        )
    assert closed == [True]
    context.ledger.verify_chain()
