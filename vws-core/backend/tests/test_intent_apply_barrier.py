"""M8: inert apply auditing and SEC-73 HALT-first persistence."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.database import OrderEvent, SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState, SystemStateStore
from backend.execution.coordinated_intent import (
    ApplyRequest,
    BrokerInventory,
    CoordinatedResolver,
    CoordinatedSnapshotReader,
)
from backend.execution.intent_resolution import IntentRefusal, SnapshotReader, dry_run
from backend.execution.models import (
    IntentBrokerSnapshot,
    IntentDryRun,
    IntentOrderView,
    IntentSnapshot,
)
from backend.ops.quiescence import BrokerCoordination
from backend.tests.broker_flag_fakes import FakeFlagAdapter
from backend.tests.test_attempt_timeout import CountingPaperBroker, prepared_submit
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_broker_coordination import FakeSlots
from backend.tests.test_intent_resolution import AdvancingWaiter, FixtureClock
from backend.tests.test_ops_security import _ops
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness


def test_B_failed_halt_prints_static_stderr_and_never_calls_broker(
    engine: Engine,
    clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ops = _ops(engine, clock)
    calls: list[str] = []
    messages: list[str] = []

    def unavailable(self: SystemStateStore, target: SystemState, reason: str) -> SystemState:
        raise OSError("offline storage failure")

    def cancel() -> None:
        calls.append("cancel")

    monkeypatch.setattr(SystemStateStore, "escalate", unavailable)
    with pytest.raises(DataIntegrityError, match="revoke keys now"):
        ops.panic(
            "Owner",
            "offline proof",
            mode="AUTO_PAPER",
            cancel_unfilled=cancel,
            notify=messages.append,
        )
    assert "HALT_NOT_PERSISTED" in capsys.readouterr().err
    assert calls == [] and messages == []


harness = make_research_harness


class StableReads:
    def __init__(self, clock: FixtureClock) -> None:
        self.clock = clock
        self.calls = 0

    async def open_orders(self) -> tuple[IntentOrderView, ...]:
        self.calls += 1
        return ()

    async def snapshot(self, intent: IntentSnapshot) -> IntentBrokerSnapshot:
        self.calls += 1
        order = IntentOrderView(
            order_id=UUID(int=999),
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            qty=intent.qty,
            filled_qty=intent.filled_qty,
            status="canceled",
        )
        return IntentBrokerSnapshot(
            observed_at=self.clock.now(),
            order=order,
            position_qty=intent.position_qty,
            fill_qty=intent.filled_qty,
            activity_ids=(),
            complete=True,
            open_orders=(),
        )


class Inventory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.calls = 0
        self.change = "none"
        self.on_second: Callable[[], None] | None = None

    async def inventory(self) -> BrokerInventory:
        self.calls += 1
        # A second independent connection can take a writer only outside TX1/TX2.
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA busy_timeout=0")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            connection.rollback()
        if self.calls == 2 and self.on_second is not None:
            self.on_second()
        orders: tuple[IntentOrderView, ...] = ()
        positions: tuple[tuple[str, int], ...] = ()
        if self.calls == 2:
            if self.change in {"cancel", "stop"}:
                orders = (
                    IntentOrderView(
                        order_id=UUID(int=1000),
                        client_order_id="existing-protection",
                        symbol="SPY",
                        side="sell",
                        qty=1,
                        filled_qty=0,
                        status="canceled" if self.change == "cancel" else "new",
                    ),
                )
            if self.change == "position":
                positions = (("SPY", 1),)
        return BrokerInventory(open_orders=orders, positions=positions)


@dataclass
class Review:
    harness: Harness
    reader: SnapshotReader
    reads: StableReads
    inventory: Inventory
    clock: FixtureClock
    request: ApplyRequest
    resolver: CoordinatedResolver
    flag: FakeFlagAdapter
    client: CountingPaperBroker

    async def operation(self) -> IntentDryRun:
        return await dry_run(
            self.reader,
            self.reads,
            self.clock,
            intent_id=self.request.intent_id,
            account=self.request.account,
            environment="PAPER",
            operator="Owner",
            reason="offline review",
            host=True,
            waiter=AdvancingWaiter(self.clock),
            announce=lambda _text: None,
        )

    async def apply(self, phrase: str | None = None) -> None:
        expected = f"CLEAR INTENT {self.request.intent_id} PAPER {self.request.account}"

        def confirm(_prompt: str) -> str:
            return expected if phrase is None else phrase

        await self.resolver.apply(
            self.operation,
            reader=self.reader,
            broker=self.inventory,
            ledger=self.harness.state.ledger,
            state=self.harness.state,
            request=self.request,
            confirm=confirm,
            announce=lambda _text: None,
        )

    def audits(self) -> list[SecurityEvent]:
        with Session(self.harness.state.engine) as session:
            return list(
                session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "APPLY_SNAPSHOT_ATTESTATION")
                )
            )


@pytest_asyncio.fixture
async def review(harness: Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Review:
    client = CountingPaperBroker(harness)
    built, instruction, _request, _guard = await prepared_submit(harness, client, monkeypatch)
    harness.state.escalate(SystemState.HALTED, "retain original proof halt")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "runtime.lock").write_bytes(b"0")
    settings = Settings.validated_copy(
        built.settings.model_copy(
            update={
                "db_url": SecretStr(harness.state.engine.url.render_as_string(hide_password=False)),
            }
        )
    )
    reader = CoordinatedSnapshotReader(settings, tmp_path)
    clock = FixtureClock()
    flag = FakeFlagAdapter()
    coordination = BrokerCoordination(tmp_path, FakeSlots(), flag)
    coordination.initialize()
    reader.coordination = coordination
    request = ApplyRequest(
        intent_id=instruction.id,
        account=instruction.account_id,
        environment="PAPER",
        operator="Owner",
        reason="offline review",
        host=True,
    )
    return Review(
        harness,
        reader,
        StableReads(clock),
        Inventory(harness.state.engine),
        clock,
        request,
        CoordinatedResolver(coordination),
        flag,
        client,
    )


@pytest.mark.parametrize("harness", [AUTO], indirect=True)
class TestApply:
    @pytest.mark.asyncio
    async def test_A_E_F_G10_attestation_only_and_exactly_two_extra_rounds(
        self, review: Review
    ) -> None:
        with Session(review.harness.state.engine) as session:
            before = tuple((row.id, row.state) for row in session.scalars(select(OrderEvent)))
        with pytest.raises(IntentRefusal):
            await review.apply()
        assert len(review.audits()) == 1, "TX1 must durably append the inert attestation"
        assert review.inventory.calls == 2 and review.reads.calls == 4
        with Session(review.harness.state.engine) as session:
            after = tuple((row.id, row.state) for row in session.scalars(select(OrderEvent)))
        assert after == before and review.client.submit_calls == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("change", ["cancel", "stop", "position"])
    async def test_C_each_broker_change_refuses(self, review: Review, change: str) -> None:
        review.inventory.change = change
        with pytest.raises(IntentRefusal) as refusal:
            await review.apply()
        assert refusal.value.code == "FIX_G_QUIESCENCE_UNVERIFIED"
        assert len(review.audits()) == 1 and review.inventory.calls == 2
        assert review.client.submit_calls == 0

    @pytest.mark.asyncio
    async def test_G11_leftover_attestation_never_satisfies_success(self, review: Review) -> None:
        with pytest.raises(IntentRefusal):
            await review.apply()
        assert len(review.audits()) == 1
        with pytest.raises(IntentRefusal):
            await review.apply()
        assert len(review.audits()) == 1 and review.inventory.calls == 2

    @pytest.mark.asyncio
    async def test_G8_G9_attestation_path_has_no_broker_proof(self, review: Review) -> None:
        review.request = review.request.model_copy(update={"resolution": "attestation"})
        with pytest.raises(IntentRefusal):
            await review.apply()
        assert review.audits() == [] and review.inventory.calls == 0

    @pytest.mark.asyncio
    async def test_G13_G14_G17_halt_pause_and_holdings_preserved(self, review: Review) -> None:
        with Session(review.harness.state.engine) as session:
            before = tuple(
                (row.id, row.kind, row.detail) for row in session.scalars(select(SecurityEvent))
            )
        with pytest.raises(IntentRefusal):
            await review.apply()
        with Session(review.harness.state.engine) as session:
            after = tuple(
                (row.id, row.kind, row.detail)
                for row in session.scalars(select(SecurityEvent))
                if row.kind != "APPLY_SNAPSHOT_ATTESTATION"
            )
        assert after == before and review.harness.state.current() == SystemState.HALTED
        assert review.client.submit_calls == 0

    @pytest.mark.asyncio
    async def test_G23_G24_G26_confirmation_and_stale_flag_refuse(self, review: Review) -> None:
        with pytest.raises(IntentRefusal) as refusal:
            await review.apply("wrong phrase")
        assert refusal.value.code == "FIX_G_HOST_CONFIRMATION_REQUIRED"
        assert review.audits() == []
        review.flag.signaled = True
        with pytest.raises(IntentRefusal) as refusal:
            await review.apply()
        assert refusal.value.code == "FIX_G_QUIESCENCE_UNVERIFIED"
        assert review.inventory.calls == 0

    @pytest.mark.asyncio
    async def test_real_schema_reader_guard(self, review: Review) -> None:
        value = review.reader.read(review.request.intent_id, review.request.account, "PAPER")
        assert value.intent_id == review.request.intent_id
        assert value.submitted_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_D_flag_after_TX2_skips_all_post_apply_IO(
        self, review: Review, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager

        from backend.core.database import transaction
        from backend.execution import coordinated_intent as module

        original = transaction
        commits = 0

        @contextmanager
        def observed(engine: Engine) -> Iterator[Session]:
            nonlocal commits
            with original(engine) as session:
                yield session
            commits += 1
            if commits == 2:
                review.flag.signal_if_present()

        monkeypatch.setattr(module, "transaction", observed)
        with pytest.raises(IntentRefusal) as refusal:
            await review.apply()
        assert refusal.value.code == "FIX_G_QUIESCENCE_UNVERIFIED"
        assert commits == 2 and review.flag.signaled
        assert review.inventory.calls == 2 and review.client.submit_calls == 0
        assert len(review.audits()) == 1

    @pytest.mark.asyncio
    async def test_G10_audit_failure_has_no_lifecycle_effect(
        self, review: Review, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.core.database import LedgerRecord

        original = review.harness.state.ledger.append_in_session

        def unavailable(
            session: Session, model: type[LedgerRecord], **fields: object
        ) -> LedgerRecord:
            if fields.get("kind") == "APPLY_SNAPSHOT_ATTESTATION":
                raise DataIntegrityError("offline audit unavailable")
            return original(session, model, **fields)

        monkeypatch.setattr(review.harness.state.ledger, "append_in_session", unavailable)
        with pytest.raises(IntentRefusal) as refusal:
            await review.apply()
        assert refusal.value.code == "FIX_G_QUIESCENCE_UNVERIFIED"
        assert review.audits() == [] and review.inventory.calls == 1
        assert review.harness.state.current() == SystemState.HALTED
        assert review.client.submit_calls == 0

    @pytest.mark.asyncio
    async def test_F_dry_run_never_writes_attestation(self, review: Review) -> None:
        result = await review.resolver.run(review.operation)
        assert result.apply_allowed is False and result.quiescence_verified
        assert review.audits() == [] and review.reads.calls == 4

    @pytest.mark.asyncio
    async def test_clean_closed_WAL_only_under_live_proof(self, review: Review) -> None:
        import hashlib

        from backend.core.database import enable_sqlite_wal

        enable_sqlite_wal(review.harness.state.engine)
        review.harness.state.engine.dispose()
        path = review.reader.path
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        assert not path.with_name(path.name + "-wal").exists()
        assert not path.with_name(path.name + "-shm").exists()
        result = await review.resolver.run(review.operation)
        assert result.quiescence_verified and result.apply_allowed is False
        assert path.read_bytes() == before[0] and path.stat().st_mtime_ns == before[1]
        assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before[0]).digest()
        assert not path.with_name(path.name + "-wal").exists()
        assert not path.with_name(path.name + "-shm").exists()
        with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
            review.reader.read(review.request.intent_id, review.request.account, "PAPER")

    @pytest.mark.asyncio
    async def test_exactly_one_WAL_sidecar_refuses(self, review: Review) -> None:
        from backend.core.database import enable_sqlite_wal

        enable_sqlite_wal(review.harness.state.engine)
        review.harness.state.engine.dispose()
        path = review.reader.path
        path.with_name(path.name + "-wal").write_bytes(b"synthetic-sidecar")
        with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
            await review.resolver.run(review.operation, strict=True)
        assert review.audits() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("phase", [1, 2])
    @pytest.mark.parametrize("fault", ["flag", "epoch", "slot", "halt"])
    async def test_local_proof_rechecked_inside_each_transaction(
        self, review: Review, monkeypatch: pytest.MonkeyPatch, phase: int, fault: str
    ) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager

        from sqlalchemy import update

        from backend.core.database import SystemControl, transaction
        from backend.execution import coordinated_intent as module

        original = transaction
        entered = 0

        @contextmanager
        def raced(engine: Engine) -> Iterator[Session]:
            nonlocal entered
            with original(engine) as session:
                entered += 1
                if entered == phase:
                    if fault == "flag":
                        review.flag.signal_if_present()
                    elif fault == "epoch":
                        review.resolver.coordination.publish(
                            UUID(int=123456), "BEGIN", "panic", False
                        )
                    elif fault == "slot":
                        review.resolver.coordination._leases.pop().release()
                    else:
                        session.execute(
                            update(SystemControl)
                            .where(SystemControl.id == 1)
                            .values(state="RUNNING")
                        )
                        session.flush()
                yield session

        monkeypatch.setattr(module, "transaction", raced)
        with pytest.raises(IntentRefusal) as refusal:
            await review.apply()
        assert refusal.value.code == "FIX_G_QUIESCENCE_UNVERIFIED"
        assert review.inventory.calls == phase
        assert len(review.audits()) == phase - 1
        assert review.client.submit_calls == 0


class TestPanicPersistence:
    def test_B_writer_past_timeout_has_zero_callbacks(
        self, engine: Engine, clock: FrozenClock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ops = _ops(engine, clock)
        calls: list[str] = []
        messages: list[str] = []

        def cancel() -> None:
            calls.append("cancel")

        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                with pytest.raises(DataIntegrityError, match="revoke keys now"):
                    ops.panic(
                        "Owner",
                        "held writer",
                        mode="AUTO_PAPER",
                        cancel_unfilled=cancel,
                        notify=messages.append,
                    )
            finally:
                connection.rollback()
        assert "HALT_NOT_PERSISTED" in capsys.readouterr().err
        assert calls == [] and messages == []
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 10000

    def test_B_short_local_writer_then_HALT_then_callbacks(
        self, engine: Engine, clock: FrozenClock
    ) -> None:
        from threading import Event, Thread, get_ident

        from sqlalchemy import event
        from sqlalchemy.engine import Connection

        ops = _ops(engine, clock)
        attempting = Event()
        calls: list[str] = []
        errors: list[Exception] = []
        worker_id: list[int] = []

        def observe(
            connection: Connection,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            if worker_id and get_ident() == worker_id[0] and statement == "BEGIN IMMEDIATE":
                attempting.set()

        def cancel() -> None:
            with Session(engine) as session:
                from backend.core.database import SystemControl

                control = session.get(SystemControl, 1)
                assert control is not None and control.state == "HALTED"
            calls.append("cancel")

        def panic() -> None:
            worker_id.append(get_ident())
            try:
                ops.panic("Owner", "short writer", mode="AUTO_PAPER", cancel_unfilled=cancel)
            except Exception as error:
                errors.append(error)

        event.listen(Engine, "before_cursor_execute", observe)
        worker = Thread(target=panic)
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                worker.start()
                assert attempting.wait(5) and calls == []
                connection.commit()
            worker.join(5)
            assert not worker.is_alive() and errors == [] and calls == ["cancel"]
        finally:
            worker.join(5)
            event.remove(Engine, "before_cursor_execute", observe)
