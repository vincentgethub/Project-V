"""Fix G-a: read-only evidence, conservative refusals and explicit side effects."""

import ast
import asyncio
import hashlib
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from backend.core.config import Settings
from backend.execution.intent_resolution import (
    CHAIN_LINE,
    QUIESCENCE_LINE,
    IntentRefusal,
    ProofReads,
    SnapshotReader,
    dry_run,
)
from backend.execution.models import IntentBrokerSnapshot, IntentDryRun, IntentOrderView
from backend.ops.process import ProcessLock
from vws import __main__ as cli

NOW = datetime(2026, 11, 1, 20, tzinfo=UTC)
INTENT = UUID(int=1)
ORDER = UUID(int=2)
BROKER = UUID(int=3)
AUDIT = UUID(int=4)


class FixtureClock:
    def __init__(self) -> None:
        self.current = NOW
        self.wait_seconds = 60

    def now(self) -> datetime:
        return self.current


class EvidenceWithOpenOrders(IntentBrokerSnapshot):
    open_orders: tuple[IntentOrderView, ...] = ()


class AdvancingWaiter:
    def __init__(self, clock: FixtureClock) -> None:
        self.clock = clock

    async def wait(self) -> None:
        self.clock.current += timedelta(seconds=self.clock.wait_seconds)


class Reads:
    def __init__(self, clock: FixtureClock) -> None:
        self.clock = clock
        self.calls = 0
        self.status: str | None = "canceled"
        self.filled_qty = 0
        self.position = 0
        self.change_open = False
        self.open_calls = 0
        self.baseline_orders: tuple[IntentOrderView, ...] = ()
        self.snapshot_orders: tuple[tuple[IntentOrderView, ...], ...] = ((), ())
        self.snapshot_count = 0
        self.change_snapshot = False
        self.submit_calls = self.cancel_calls = self.replace_calls = 0
        self.error: Exception | None = None
        self.after: Any = None

    @property
    def gap(self) -> int:
        return self.clock.wait_seconds

    @gap.setter
    def gap(self, value: int) -> None:
        self.clock.wait_seconds = value

    def submit_order(self, *args: Any, **kwargs: Any) -> None:
        self.submit_calls += 1
        raise AssertionError("Dry run must never submit")

    def cancel_order_by_id(self, *args: Any, **kwargs: Any) -> None:
        self.cancel_calls += 1
        raise AssertionError("Dry run must never cancel")

    def replace_order_by_id(self, *args: Any, **kwargs: Any) -> None:
        self.replace_calls += 1
        raise AssertionError("Dry run must never replace")

    async def open_orders(self) -> tuple[IntentOrderView, ...]:
        self.calls += 1
        self.open_calls += 1
        if self.change_open and self.open_calls > 1:
            return (self.order("new"),)
        return self.baseline_orders

    def order(self, status: str) -> IntentOrderView:
        return IntentOrderView.model_validate(
            {
                "order_id": BROKER,
                "client_order_id": "test-intent",
                "symbol": "SPY",
                "side": "buy",
                "qty": 1,
                "filled_qty": self.filled_qty,
                "status": status,
            }
        )

    async def snapshot(self, intent: Any) -> IntentBrokerSnapshot:
        self.calls += 1
        if self.error is not None:
            raise self.error
        first = self.snapshot_count == 0
        self.snapshot_count += 1
        if not first:
            if self.after is not None:
                self.after()
        return EvidenceWithOpenOrders(
            observed_at=self.clock.now(),
            order=None if self.status is None else self.order(self.status),
            not_found=self.status is None,
            position_qty=self.position + (1 if self.change_snapshot and not first else 0),
            fill_qty=self.filled_qty,
            activity_ids=(),
            complete=True,
            open_orders=self.snapshot_orders[0 if first else 1],
        )


@pytest.fixture
def case(tmp_path: Path) -> tuple[SnapshotReader, Reads, FixtureClock, Settings]:
    database = tmp_path / "ledger.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE execution_orders (id TEXT, order_id TEXT, client_order_id TEXT, "
            "account_id TEXT, environment TEXT, symbol TEXT, side TEXT, qty INTEGER, seq INTEGER);"
            "CREATE TABLE order_events (order_id TEXT, state TEXT, created_at TEXT, seq INTEGER);"
            "CREATE TABLE execution_fills (execution_order_id TEXT, qty INTEGER);"
            "CREATE TABLE system_control (id INTEGER, state TEXT, version INTEGER);"
            "CREATE TABLE system_events (id TEXT, state TEXT, seq INTEGER);"
            "CREATE TABLE security_events (id TEXT, kind TEXT, detail TEXT, seq INTEGER);"
        )
        connection.execute(
            "INSERT INTO execution_orders VALUES (?,?,?,?,?,?,?,?,?)",
            (INTENT.hex, ORDER.hex, "test-intent", "account", "PAPER", "SPY", "BUY", 1, 1),
        )
        connection.execute(
            "INSERT INTO order_events VALUES (?,?,?,?)",
            (ORDER.hex, "SUBMITTED", (NOW - timedelta(minutes=10)).isoformat(), 2),
        )
        connection.execute("INSERT INTO system_control VALUES (1,'HALTED',1)")
        connection.execute("INSERT INTO system_events VALUES (?,'HALTED',3)", (UUID(int=5).hex,))
        connection.execute("INSERT INTO security_events VALUES (?,'TEST','{}',4)", (AUDIT.hex,))
    (tmp_path / "data").mkdir(mode=0o700)
    (tmp_path / "data" / "runtime.lock").write_bytes(b"0")
    settings = Settings(
        db_url=SecretStr("sqlite:///" + str(database)),
        broker_api_key=SecretStr("TEST_ONLY_PAPER_ID"),
        broker_secret_key=SecretStr("TEST_ONLY_PAPER_SECRET"),
    )
    clock = FixtureClock()
    return SnapshotReader(settings, tmp_path), Reads(clock), clock, settings


async def run(
    case: tuple[SnapshotReader, ProofReads, FixtureClock, Settings], **options: Any
) -> Any:
    reader, broker, clock, _ = case
    args: dict[str, Any] = dict(
        intent_id=INTENT,
        account="account",
        environment="PAPER",
        operator="Owner",
        reason="Review stuck intent",
        host=True,
        waiter=AdvancingWaiter(clock),
    )
    args.update(options)
    return await dry_run(reader, broker, clock, **args)


def change(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings], sql: str, args: tuple[Any, ...] = ()
) -> None:
    with sqlite3.connect(case[0].path) as connection:
        connection.execute(sql, args)


@pytest.mark.asyncio
async def test_G1_unknown_intent(case: Any) -> None:
    with pytest.raises(IntentRefusal, match="FIX_G_UNKNOWN_INTENT"):
        await run(case, intent_id=UUID(int=90))
    assert case[1].calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value,code",
    [("account_id", "other", "ACCOUNT_MISMATCH"), ("environment", "LIVE", "ENVIRONMENT_MISMATCH")],
)
async def test_G2_binding(case: Any, field: str, value: str, code: str) -> None:
    sql = {
        "account_id": "UPDATE execution_orders SET account_id=?",
        "environment": "UPDATE execution_orders SET environment=?",
    }[field]
    change(case, sql, (value,))
    with pytest.raises(IntentRefusal, match="FIX_G_" + code):
        await run(case)
    assert case[1].calls == 0


@pytest.mark.asyncio
async def test_G3_not_submitted(case: Any) -> None:
    change(case, "UPDATE order_events SET state='FILLED'")
    with pytest.raises(IntentRefusal, match="FIX_G_INTENT_NOT_SUBMITTED"):
        await run(case)


@pytest.mark.asyncio
async def test_G3_running_refuses_before_broker(case: Any) -> None:
    change(case, "UPDATE system_control SET state='RUNNING'")
    change(case, "UPDATE system_events SET state='RUNNING'")
    with pytest.raises(IntentRefusal, match="FIX_G_SYSTEM_ACTIVE"):
        await run(case)
    assert case[1].calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["new", "partially_filled", "pending_cancel", "held"])
async def test_G4_live_order(case: Any, status: str) -> None:
    case[1].status = status
    with pytest.raises(IntentRefusal, match="FIX_G_LIVE_ORDER"):
        await run(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_G5_http_failure_is_not_absence(
    case: Any, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    from backend.core.database import create_database, create_schema
    from backend.core.ledger import Ledger
    from backend.net.egress import EgressPolicy, build_allowlist
    from backend.net.http import make_client
    from backend.ops import read_checks

    engine = create_database("sqlite://")
    create_schema(engine)
    policy = EgressPolicy(build_allowlist(), Ledger(engine, case[2]))

    def factory(purpose: str, **kwargs: Any) -> Any:
        return make_client(
            purpose, transport=httpx.MockTransport(lambda request: httpx.Response(status)), **kwargs
        )

    monkeypatch.setattr(read_checks, "make_client", factory)
    source = read_checks.IntentReadClient(case[3], "account", policy, case[2])
    with pytest.raises(IntentRefusal, match="FIX_G_LOOKUP_UNVERIFIED"):
        await source.open_orders()
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["canceled", "expired", "rejected"])
async def test_G6_terminal_raw_status(case: Any, status: str) -> None:
    case[1].status = status
    result = await run(case)
    assert result.outcome == "TERMINAL" and result.status == status
    assert not result.apply_allowed


@pytest.mark.asyncio
async def test_G6_filled_without_full_fill_is_not_proof(case: Any) -> None:
    case[1].status = "filled"
    with pytest.raises(IntentRefusal, match="FIX_G_PROOF_INCOMPLETE"):
        await run(case)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["none", "age", "gap", "snapshots", "position"])
async def test_G7_qualified_absence(case: Any, fault: str) -> None:
    case[1].status = None
    if fault == "age":
        change(
            case,
            "UPDATE order_events SET created_at=?",
            ((NOW - timedelta(minutes=9, seconds=59)).isoformat(),),
        )
    if fault == "gap":
        case[1].gap = 59
    if fault == "snapshots":
        case[1].change_snapshot = True
    if fault == "position":
        case[1].position = 1
    if fault != "none":
        with pytest.raises(IntentRefusal, match="FIX_G_PROOF_INCOMPLETE"):
            await run(case)
    else:
        assert (await run(case)).outcome == "QUALIFIED_NOT_FOUND"


@pytest.mark.asyncio
async def test_G12_G21_no_order_calls_or_db_writes(case: Any) -> None:
    before = case[0].path.read_bytes()
    await run(case)
    assert (case[1].submit_calls, case[1].cancel_calls, case[1].replace_calls) == (0, 0, 0)
    assert before == case[0].path.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"host": False}, {"operator": ""}, {"reason": "\nsecret"}])
async def test_G15_host_and_reason(case: Any, options: dict[str, Any]) -> None:
    code = "FIX_G_HOST_CONFIRMATION_REQUIRED" if "host" in options else "FIX_G_REASON_REQUIRED"
    with pytest.raises(IntentRefusal, match=code):
        await run(case, **options)
    assert case[1].calls == 0


@pytest.mark.asyncio
async def test_G16_QA1_lock_held(case: Any) -> None:
    with ProcessLock(case[0].project / "data" / "runtime.lock"):
        with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
            await run(case)
    assert case[1].calls == 0


@pytest.mark.asyncio
async def test_G18_secret_canary(case: Any) -> None:
    case[1].error = ValueError("SECRET_CANARY_NOT_FOR_OUTPUT")
    with pytest.raises(IntentRefusal) as caught:
        await run(case)
    assert "SECRET_CANARY" not in str(caught.value)


@pytest.mark.asyncio
async def test_G20_live_refused_before_reads(case: Any) -> None:
    with pytest.raises(IntentRefusal, match="FIX_G_PAPER_ONLY"):
        await run(case, environment="LIVE")
    assert case[1].calls == 0


def test_G22_host_parser_no_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    from vws import intent_cli

    called: list[dict[str, Any]] = []

    def execute(**options: Any) -> int:
        called.append(options)
        return 0

    monkeypatch.setattr(intent_cli, "execute", execute)
    args = [
        "ops",
        "clear-intent",
        "--intent",
        str(INTENT),
        "--account",
        "account",
        "--environment",
        "PAPER",
        "--operator",
        "Owner",
        "--reason",
        "review",
    ]
    assert cli.main(args) == 0 and len(called) == 1
    with pytest.raises(SystemExit):
        cli.main([*args, "--apply"])


def test_G25_doctor_hints_do_not_change_checks(case: Any) -> None:
    from backend.ops.doctor import intent_hints

    assert str(INTENT) in " ".join(intent_hints(case[3], case[0].project))


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["audit", "state"])
async def test_QA2_changes_refuse(case: Any, fault: str) -> None:
    sql = (
        "UPDATE security_events SET id=?"
        if fault == "audit"
        else "UPDATE system_control SET state=?"
    )
    value = UUID(int=88).hex if fault == "audit" else "RUNNING"

    def mutate() -> None:
        change(case, sql, (value,))

    case[1].after = mutate
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        await run(case)


@pytest.mark.asyncio
async def test_QA3_protective_open_order_change(case: Any) -> None:
    case[1].change_open = True
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        await run(case)


@pytest.mark.asyncio
async def test_QA4_unreadable_id(case: Any) -> None:
    change(case, "UPDATE security_events SET id='invalid'")
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        await run(case)


@pytest.mark.asyncio
async def test_QA5_summary(case: Any) -> None:
    lines = (await run(case)).lines()
    assert QUIESCENCE_LINE in lines and CHAIN_LINE in lines


def test_QA6_connection_refuses_insert(case: Any) -> None:
    with case[0].connect() as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO system_control VALUES (2,'RUNNING',0)")


def test_QA7_QA8_missing_db_never_created_and_unchanged_bytes(case: Any) -> None:
    before = hashlib.sha256(case[0].path.read_bytes()).hexdigest()
    case[0].read(INTENT, "account", "PAPER")
    assert hashlib.sha256(case[0].path.read_bytes()).hexdigest() == before
    settings = Settings(db_url=SecretStr("sqlite:///" + str(case[0].project / "missing.sqlite3")))
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        SnapshotReader(settings, case[0].project).read(INTENT, "account", "PAPER")
    assert not (case[0].project / "missing.sqlite3").exists()


def test_QA9_no_banned_calls_or_telegram_path() -> None:
    import backend.execution.intent_resolution as module
    from backend.notifications import telegram_bot

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    banned = {
        "current",
        "verify_chain",
        "_read",
        "halt_for_error",
        "notify",
        "transaction",
        "_observe",
        "_read_bound",
    }
    assert not [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Attribute) and n.func.attr in banned)
            or (isinstance(n.func, ast.Name) and n.func.id in banned)
        )
    ]
    assert "BEGIN IMMEDIATE" not in Path(module.__file__).read_text(encoding="utf-8")
    assert "intent_cli" not in Path(telegram_bot.__file__).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_QA10_redirect_only_egress_audit(
    case: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy import event, select
    from sqlalchemy.orm import Session

    from backend.core.database import SecurityEvent, SystemEvent, create_database, create_schema
    from backend.core.ledger import Ledger
    from backend.net.egress import EgressPolicy, build_allowlist
    from backend.net.http import make_client
    from backend.ops import read_checks

    engine = create_database("sqlite://")
    create_schema(engine)
    policy = EgressPolicy(build_allowlist(), Ledger(engine, case[2]))
    methods: list[str] = []
    writes: list[str] = []

    def record_write(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", record_write)

    def redirect(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(302, headers={"location": "https://example.com"})

    def factory(purpose: str, **kwargs: Any) -> Any:
        return make_client(purpose, transport=httpx.MockTransport(redirect), **kwargs)

    monkeypatch.setattr(read_checks, "make_client", factory)
    source = read_checks.IntentReadClient(case[3], "account", policy, case[2])
    before = case[0].path.read_bytes()
    with pytest.raises(IntentRefusal, match="FIX_G_LOOKUP_UNVERIFIED"):
        await run((case[0], source, case[2], case[3]))
    with Session(engine) as session:
        assert [row.kind for row in session.scalars(select(SecurityEvent))] == ["EGRESS_DENIED"]
        assert not list(session.scalars(select(SystemEvent)))
    assert methods == ["GET"] and before == case[0].path.read_bytes()
    assert sum(statement.startswith("INSERT INTO security_events ") for statement in writes) == 1
    assert sum(statement.startswith("UPDATE append_control ") for statement in writes) == 1
    assert len(writes) == 2, "Only the canonical audit append and its sequence allocation may write"
    assert "Dry run:" not in capsys.readouterr().out
    engine.dispose()


@pytest.mark.asyncio
async def test_G6_filled_with_captured_fills_and_position(case: Any) -> None:
    change(case, "INSERT INTO execution_fills VALUES (?,1)", (INTENT.hex,))
    case[1].filled_qty = 1
    case[1].position = 1
    case[1].status = "filled"
    result = await run(case)
    assert result.outcome == "TERMINAL" and result.status == "filled"
    assert result.apply_allowed is False


class WireReads:
    def __init__(self, script: list[httpx.Response | Exception]) -> None:
        self.script = list(script)
        self.methods: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.methods.append(request.method)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def http_source(
    case: Any, monkeypatch: pytest.MonkeyPatch, script: list[httpx.Response | Exception]
) -> tuple[Any, WireReads, Any]:
    from backend.core.database import create_database, create_schema
    from backend.core.ledger import Ledger
    from backend.net.egress import EgressPolicy, build_allowlist
    from backend.net.http import make_client
    from backend.ops import read_checks

    engine = create_database("sqlite://")
    create_schema(engine)
    wire = WireReads(script)

    def factory(purpose: str, **kwargs: Any) -> Any:
        return make_client(purpose, transport=httpx.MockTransport(wire.handle), **kwargs)

    monkeypatch.setattr(read_checks, "make_client", factory)
    client = read_checks.IntentReadClient(
        case[3], "account", EgressPolicy(build_allowlist(), Ledger(engine, case[2])), case[2]
    )
    return client, wire, engine


def raw_order(**updates: Any) -> dict[str, Any]:
    result = dict(
        id=str(BROKER),
        client_order_id="test-intent",
        symbol="SPY",
        side="buy",
        qty="1",
        filled_qty="0",
        status="canceled",
    )
    result.update(updates)
    return result


@pytest.mark.asyncio
async def test_G5_real_404_is_typed_only_after_account_binding(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, wire, engine = http_source(
        case,
        monkeypatch,
        [
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(404, text="SECRET_CANARY"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(200, json=[]),
        ],
    )
    try:
        seen = await source.snapshot(case[0].read(INTENT, "account", "PAPER"))
        assert seen.order is None and seen.not_found is True
        assert wire.methods == ["GET"] * 6
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "unauthorized",
        "forbidden",
        "rate",
        "server",
        "timeout",
        "malformed",
        "wrong_id",
        "wrong_client",
    ],
)
async def test_G5_lookup_failure_stops_further_reads(
    case: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    bad: dict[str, httpx.Response | Exception] = {
        "unauthorized": httpx.Response(401),
        "forbidden": httpx.Response(403),
        "rate": httpx.Response(429),
        "server": httpx.Response(503),
        "timeout": httpx.ReadTimeout("SECRET_CANARY"),
        "malformed": httpx.Response(200, content=b"invalid SECRET_CANARY"),
        "wrong_id": httpx.Response(200, json=raw_order(id="invalid SECRET_CANARY")),
        "wrong_client": httpx.Response(200, json=raw_order(client_order_id="other")),
    }
    source, wire, engine = http_source(
        case, monkeypatch, [httpx.Response(200, json={"id": "account"}), bad[fault]]
    )
    try:
        with pytest.raises(IntentRefusal, match="FIX_G_LOOKUP_UNVERIFIED") as caught:
            await source.snapshot(case[0].read(INTENT, "account", "PAPER"))
        assert wire.methods == ["GET", "GET"] and "SECRET_CANARY" not in str(caught.value)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_G2_account_mismatch_precedes_target_lookup(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, wire, engine = http_source(
        case, monkeypatch, [httpx.Response(200, json={"id": "other"})]
    )
    try:
        with pytest.raises(IntentRefusal, match="FIX_G_ACCOUNT_MISMATCH"):
            await source.snapshot(case[0].read(INTENT, "account", "PAPER"))
        assert wire.methods == ["GET"]
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_G5_bound_order_id_get_agrees_with_client_lookup(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    change(
        case,
        "UPDATE security_events SET kind='EXECUTION_ORDER_OBSERVED', detail=?",
        (
            json.dumps(
                {"execution_order_id": str(INTENT), "broker_order": {"order_id": str(BROKER)}}
            ),
        ),
    )
    source, wire, engine = http_source(
        case,
        monkeypatch,
        [
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(200, json=raw_order()),
            httpx.Response(200, json=raw_order()),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(200, json=[]),
        ],
    )
    try:
        seen = await source.snapshot(case[0].read(INTENT, "account", "PAPER"))
        assert seen.order is not None and seen.order.order_id == BROKER
        assert wire.methods == ["GET"] * 7
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_G5_bound_order_disappearance_is_contradiction(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    change(
        case,
        "UPDATE security_events SET kind='EXECUTION_ORDER_OBSERVED', detail=?",
        (
            json.dumps(
                {"execution_order_id": str(INTENT), "broker_order": {"order_id": str(BROKER)}}
            ),
        ),
    )
    source, wire, engine = http_source(
        case,
        monkeypatch,
        [
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(200, json=raw_order()),
            httpx.Response(404),
        ],
    )
    try:
        with pytest.raises(IntentRefusal, match="FIX_G_CONTRADICTION"):
            await source.snapshot(case[0].read(INTENT, "account", "PAPER"))
        assert wire.methods == ["GET"] * 3
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_G7_incomplete_activity_page_is_not_proof(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, wire, engine = http_source(
        case,
        monkeypatch,
        [
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(404),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[{}] * 100),
        ],
    )
    try:
        with pytest.raises(IntentRefusal, match="FIX_G_PROOF_INCOMPLETE"):
            await source.snapshot(case[0].read(INTENT, "account", "PAPER"))
        assert wire.methods == ["GET"] * 4
    finally:
        engine.dispose()


def test_G12_reader_surface_has_no_mutating_calls() -> None:
    from backend.ops import read_checks

    tree = ast.parse(Path(read_checks.__file__).read_text(encoding="utf-8"))
    node = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "IntentReadClient"
    )
    assert {
        n.name
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    } == {"open_orders", "snapshot"}
    assert not [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"post", "put", "patch", "delete"}
    ]


@pytest.mark.asyncio
async def test_G16_missing_lock_is_not_created(case: Any, tmp_path: Path) -> None:
    empty = tmp_path / "empty-project"
    empty.mkdir()
    reader = SnapshotReader(case[3], empty)
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        await run((reader, case[1], case[2], case[3]))
    assert not (empty / "data").exists()


def test_QA7_connect_failure_has_no_halt_notify_or_writable_fallback(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.core.notifier import ConsoleNotifier
    from backend.core.system_state import SystemStateStore

    calls: list[str] = []
    connections: list[str] = []

    def halt(*args: Any, **kwargs: Any) -> None:
        calls.append("halt")

    def notify(*args: Any, **kwargs: Any) -> None:
        calls.append("notify")

    def fail(database: str, **kwargs: Any) -> Any:
        connections.append(database)
        assert kwargs["uri"] is True and kwargs["timeout"] == 0
        raise sqlite3.OperationalError("SECRET_CANARY")

    monkeypatch.setattr(SystemStateStore, "halt_for_error", halt)
    monkeypatch.setattr(ConsoleNotifier, "notify", notify)
    monkeypatch.setattr(sqlite3, "connect", fail)
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED") as caught:
        case[0].read(INTENT, "account", "PAPER")
    assert len(connections) == 1 and connections[0].endswith("?mode=ro")
    assert calls == [] and "SECRET_CANARY" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["success", "live", "lookup", "audit"])
async def test_QA8_db_hash_mtime_and_rows_unchanged(case: Any, fault: str) -> None:
    if fault == "live":
        case[1].status = "new"
    if fault == "lookup":
        case[1].error = ValueError("unverified")
    if fault == "audit":
        change(case, "UPDATE security_events SET id='invalid'")

    def inventory() -> tuple[int, ...]:
        with case[0].connect() as connection:
            return tuple(
                connection.execute(sql).fetchone()[0]
                for sql in (
                    "SELECT COUNT(*) FROM execution_orders",
                    "SELECT COUNT(*) FROM order_events",
                    "SELECT COUNT(*) FROM security_events",
                    "SELECT COUNT(*) FROM system_events",
                    "SELECT COUNT(*) FROM execution_fills",
                )
            )

    before = (
        hashlib.sha256(case[0].path.read_bytes()).hexdigest(),
        case[0].path.stat().st_mtime_ns,
        inventory(),
    )
    if fault == "success":
        await run(case)
    else:
        with pytest.raises(IntentRefusal):
            await run(case)
    assert before == (
        hashlib.sha256(case[0].path.read_bytes()).hexdigest(),
        case[0].path.stat().st_mtime_ns,
        inventory(),
    )


def test_QA8_wal_requires_existing_sidecars_and_main_db_is_unchanged(
    case: Any, tmp_path: Path
) -> None:
    from shutil import copy2

    path = case[0].path
    with sqlite3.connect(path) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("INSERT INTO security_events VALUES (?,'TEST','{}',5)", (UUID(int=99).hex,))
        writer.commit()
        sidecars = tuple(path.with_name(path.name + suffix) for suffix in ("-wal", "-shm"))
        assert all(p.is_file() for p in sidecars)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        wal_before = (sidecars[0].read_bytes(), sidecars[0].stat().st_mtime_ns)
        assert case[0].read(INTENT, "account", "PAPER").audit_id == UUID(int=99)
        assert before == (path.read_bytes(), path.stat().st_mtime_ns)
        assert wal_before == (sidecars[0].read_bytes(), sidecars[0].stat().st_mtime_ns)
        assert all(p.is_file() for p in sidecars)
        missing_sidecars = tmp_path / "wal-copy.sqlite3"
        copy2(path, missing_sidecars)
        settings = Settings(db_url=SecretStr("sqlite:///" + str(missing_sidecars)))
        with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
            SnapshotReader(settings, tmp_path).read(INTENT, "account", "PAPER")
        assert not missing_sidecars.with_name(missing_sidecars.name + "-shm").exists()


@pytest.mark.asyncio
async def test_QA2_mode_change_is_part_of_snapshot(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings],
) -> None:
    import json

    detail = dict(
        account_id="account",
        environment="PAPER",
        mode="AUTO_PAPER",
        paused=True,
        action="PAUSE",
        actor="owner",
        config_hash=case[3].config_hash,
    )
    change(
        case,
        "UPDATE security_events SET kind='EXECUTION_MODE_OVERRIDE',detail=?",
        (json.dumps(detail),),
    )

    def downgrade_mode() -> None:
        change(
            case, "UPDATE security_events SET detail=?", (json.dumps({**detail, "mode": "MANUAL"}),)
        )

    case[1].after = downgrade_mode
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        await run(case)


def protective_stop(identity: int, status: str) -> IntentOrderView:
    return IntentOrderView.model_validate(
        dict(
            order_id=UUID(int=identity),
            client_order_id="protective-stop",
            symbol="SPY",
            side="sell",
            qty=1,
            filled_qty=0,
            status=status,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["added", "id", "status"])
async def test_QA3_snapshot_protective_ids_and_status(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings], fault: str
) -> None:
    stop = protective_stop(81, "new")
    if fault == "added":
        case[1].snapshot_orders = ((stop,), ())
    else:
        case[1].baseline_orders = (stop,)
        second = (
            protective_stop(82, "new") if fault == "id" else protective_stop(81, "pending_cancel")
        )
        case[1].snapshot_orders = ((stop,), (second,))
    with pytest.raises(IntentRefusal, match="FIX_G_QUIESCENCE_UNVERIFIED"):
        await run(case)


@pytest.mark.asyncio
async def test_QA3_reader_captures_protective_orders_in_snapshot(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, wire, engine = http_source(
        case,
        monkeypatch,
        [
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(200, json=raw_order()),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"id": "account"}),
            httpx.Response(
                200,
                json=[
                    raw_order(
                        id=str(UUID(int=81)),
                        client_order_id="protective-stop",
                        side="sell",
                        status="new",
                    )
                ],
            ),
        ],
    )
    try:
        seen = await source.snapshot(case[0].read(INTENT, "account", "PAPER"))
        assert wire.methods == ["GET"] * 6, "Each snapshot must collect its own open orders"
        assert [(row.order_id, row.status, row.side) for row in seen.open_orders] == [
            (UUID(int=81), "new", "sell")
        ]
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_QA11_early_waiter_cannot_authorize_terminal(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings],
) -> None:
    case[1].gap = 0
    with pytest.raises(IntentRefusal, match="FIX_G_PROOF_INCOMPLETE"):
        await run(case)


@pytest.mark.asyncio
async def test_QA11_wait_message(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    await run(case)
    assert "waiting 60s for second snapshot" in capsys.readouterr().out


class NoSecrets:
    def get(self, name: str) -> SecretStr | None:
        return None

    def set(self, name: str, value: SecretStr) -> None:
        raise AssertionError("Dry run cannot store secrets")

    def delete(self, name: str) -> None:
        raise AssertionError("Dry run cannot delete secrets")


class HostInput:
    def isatty(self) -> bool:
        return True


def test_QA11_production_wires_a_real_waiter(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Coroutine

    from backend.core.clock import Clock
    from backend.security.secrets import SecretStore
    from vws import intent_cli

    seen: list[object | None] = []

    async def capture(
        reader: SnapshotReader,
        broker: ProofReads,
        clock: Clock,
        *,
        intent_id: UUID,
        account: str,
        environment: str,
        operator: str,
        reason: str,
        host: bool,
        waiter: object | None = None,
    ) -> IntentDryRun:
        seen.append(waiter)
        return IntentDryRun(
            intent_id=intent_id,
            account=account,
            outcome="TERMINAL",
            status="canceled",
            pause_owner=None,
        )

    def settings_for_host(project: Path, env_file: Path | None, store: SecretStore) -> Settings:
        return case[3]

    def inline_capture(operation: Coroutine[object, object, IntentDryRun]) -> IntentDryRun:
        try:
            operation.send(None)
        except StopIteration as finished:
            return IntentDryRun.model_validate(finished.value)
        raise AssertionError("The explicit capture fake must not suspend")

    monkeypatch.setattr(intent_cli, "KeyringSecretStore", NoSecrets)
    monkeypatch.setattr(intent_cli, "load_host_settings", settings_for_host)
    monkeypatch.setattr(intent_cli, "dry_run", capture)
    monkeypatch.setattr(asyncio, "run", inline_capture)
    monkeypatch.setattr(sys, "stdin", HostInput())
    for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("SESSIONNAME", "Console")
    assert (
        intent_cli.execute(
            intent=str(INTENT),
            account="account",
            environment="PAPER",
            operator="Owner",
            reason="review",
        )
        == 0
    )
    assert len(seen) == 1 and seen[0] is not None, "Production must pass a real injected waiter"
    from vws.intent_cli import RealSnapshotWaiter

    assert isinstance(seen[0], RealSnapshotWaiter)


@pytest.mark.asyncio
async def test_QA11_waiter_holds_runtime_lock(
    case: tuple[SnapshotReader, Reads, FixtureClock, Settings],
) -> None:
    from backend.ops.process import ProcessBusyError

    class HoldingWaiter(AdvancingWaiter):
        held = False

        async def wait(self) -> None:
            with pytest.raises(ProcessBusyError):
                with ProcessLock(case[0].project / "data" / "runtime.lock"):
                    raise AssertionError("The resolver released its lock before waiting")
            self.held = True
            await super().wait()

    waiter = HoldingWaiter(case[2])
    await run(case, waiter=waiter)
    assert waiter.held


@pytest.mark.asyncio
async def test_QA11_real_waiter_requests_exactly_sixty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vws import intent_cli

    durations: list[float] = []

    async def fake_wait(seconds: float) -> None:
        durations.append(seconds)

    with monkeypatch.context() as scope:
        scope.setattr(asyncio, "sleep", fake_wait)
        await intent_cli.RealSnapshotWaiter().wait()
    assert durations == [60]
