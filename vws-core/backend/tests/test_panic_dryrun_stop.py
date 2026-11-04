"""B2-dryrun: real protective repair inside the complete G-a evidence window."""

from datetime import datetime, timedelta
from pathlib import Path
from shutil import copytree
from traceback import extract_tb
from typing import Any
from uuid import uuid4

import pytest

from backend.core.system_state import SystemState
from backend.execution import alpaca_executor
from backend.execution.coordinated_intent import CoordinatedResolver
from backend.execution.intent_resolution import IntentRefusal, SnapshotReader, dry_run
from backend.execution.models import (
    OPEN_STATUSES,
    IntentBrokerSnapshot,
    IntentOrderView,
    IntentSnapshot,
)
from backend.net.egress import EgressPolicy, build_allowlist
from backend.ops import quiescence
from backend.ops.anchors import LedgerAnchors
from backend.ops.security import ConfigDriftGuard, SecurityOps
from backend.tests.broker_flag_fakes import FakeFlagAdapter
from backend.tests.test_auto_execution import AUTO, executor, fill_entry
from backend.tests.test_broker_coordination import CountedBroker, FakeSlots
from backend.tests.test_security_cli import MemorySecrets
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from vws import execution_cli, host_config, security_cli

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_B2_dryrun_real_ensure_stop_change_refuses_at_existing_comparison(
    harness: Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker = CountedBroker(harness)
    built = executor(harness, broker)
    alert = await deliver(harness)
    await built.enter(alert.proposal_id)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    harness.state.escalate(SystemState.HALTED, "offline dry-run repair fixture")
    copytree(Path(__file__).resolve().parents[2] / "config", tmp_path / "config")
    for name in ("data", "logs", "backups"):
        (tmp_path / name).mkdir(exist_ok=True)
    (tmp_path / "data/runtime.lock").write_bytes(b"0")
    context = security_cli.SecurityContext(
        harness.settings,
        harness.state.engine,
        harness.state.ledger,
        harness.state,
        SecurityOps(harness.state.ledger, harness.state, harness.clock),
        ConfigDriftGuard(harness.state.ledger, harness.clock),
        LedgerAnchors(harness.state.ledger, harness.clock),
        None,
    )
    policy = EgressPolicy(build_allowlist(mode="AUTO_PAPER"), harness.state.ledger)
    monkeypatch.setattr(security_cli, "PROJECT", tmp_path)
    monkeypatch.setattr(host_config, "load_host_settings", lambda *_args: harness.settings)
    monkeypatch.setattr(security_cli, "configure_egress", lambda *_args: None)
    monkeypatch.setattr(security_cli, "_require_network_policy", lambda *_args: policy)
    monkeypatch.setattr(alpaca_executor, "make_execution_client", lambda *_args, **_kwargs: broker)
    slots, flag = FakeSlots(), FakeFlagAdapter()
    slots.held.update(f"slot-{index}" for index in range(8))
    flag.fail_at = "signal"  # The approved residual; broker comparison must still catch changes.
    monkeypatch.setattr(quiescence, "OSSlots", lambda _directory: slots)
    monkeypatch.setattr(quiescence, "OSFlagAdapter", lambda _directory: flag)
    ensured: list[int] = []

    class ObservedRecovery(alpaca_executor.ProtectionRecovery):
        async def _ensure_stop(self, instruction: Any, qty: int) -> None:
            before = broker.submit_calls
            await super()._ensure_stop(instruction, qty)
            ensured.append(broker.submit_calls - before)

    monkeypatch.setattr(alpaca_executor, "ProtectionRecovery", ObservedRecovery)
    store = MemorySecrets()
    store.set("ALPACA_PAPER_KEY_ID", harness.settings.broker_api_key)
    store.set("ALPACA_PAPER_SECRET", harness.settings.broker_secret_key)

    class Clock:
        current = harness.clock.now()

        def now(self) -> datetime:
            return self.current

    clock = Clock()
    # An explicitly frozen local evidence fake isolates the broker comparison,
    # even if another process's local projection were not yet visible.
    local = IntentSnapshot(
        intent_id=entry.id,
        order_id=entry.order_id,
        client_order_id=entry.client_order_id,
        account="offline-paper",
        environment="PAPER",
        symbol=entry.symbol,
        side="buy",
        qty=entry.qty,
        submitted_at=clock.now() - timedelta(minutes=11),
        broker_order_id=None,
        position_qty=0,
        filled_qty=0,
        audit_id=uuid4(),
        audit_seq=1,
        state="HALTED",
        state_id=uuid4(),
        state_version=1,
        mode="AUTO_PAPER",
        override_mode=None,
        paused=False,
        pause_owner=None,
        contradiction=False,
    )

    class FrozenLocalReader(SnapshotReader):
        def read(self, intent_id: Any, account: str, environment: str) -> IntentSnapshot:
            assert (
                intent_id == local.intent_id and account == local.account and environment == "PAPER"
            )
            return local

    reader = FrozenLocalReader(harness.settings, tmp_path)

    def view(raw: dict[str, Any]) -> IntentOrderView:
        return IntentOrderView.model_validate(
            {
                "order_id": raw["id"],
                "client_order_id": raw["client_order_id"],
                "symbol": raw["symbol"],
                "side": raw["side"],
                "qty": int(raw["qty"]),
                "filled_qty": int(raw["filled_qty"]),
                "status": raw["status"],
            }
        )

    class Reads:
        async def open_orders(self) -> tuple[IntentOrderView, ...]:
            return tuple(
                view(row) for row in broker.orders.values() if row["status"] in OPEN_STATUSES
            )

        async def snapshot(self, intent: IntentSnapshot) -> IntentBrokerSnapshot:
            raw = broker.orders[intent.client_order_id]
            return IntentBrokerSnapshot(
                observed_at=clock.now(),
                order=view(raw),
                position_qty=sum(int(row["qty"]) for row in broker.positions),
                fill_qty=int(raw["filled_qty"]),
                activity_ids=(),
                complete=True,
                open_orders=await self.open_orders(),
            )

    class Waiter:
        async def wait(self) -> None:
            await fill_entry(harness, broker, built, partial=True)
            await execution_cli.panic_cancel(context, store)
            clock.current += timedelta(seconds=60)

    try:
        with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED") as caught:
            await CoordinatedResolver(quiescence.BrokerCoordination(tmp_path, slots, flag)).run(
                lambda: dry_run(
                    reader,
                    Reads(),
                    clock,
                    intent_id=entry.id,
                    account="offline-paper",
                    environment="PAPER",
                    operator="Owner",
                    reason="offline stop-change evidence",
                    host=True,
                    waiter=Waiter(),
                ),
            )
        assert sum(ensured) == 1, "the real panic _ensure_stop must create one protective stop"
        assert any(
            row["side"] == "sell" and row["type"] == "stop" and row["status"] == "new"
            for row in broker.orders.values()
        )
        assert caught.value.__traceback__ is not None
        assert any(
            Path(frame.filename).name == "intent_resolution.py" and frame.lineno == 357
            for frame in extract_tb(caught.value.__traceback__)
        ), "existing comparison at :356 must refuse"
    finally:
        await built.close()
