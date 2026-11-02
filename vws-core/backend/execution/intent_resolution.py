"""Fix G-a: SELECT-only local snapshots and non-authorizing broker evidence."""

import json
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.engine import make_url

from backend.core.clock import Clock
from backend.core.config import Settings
from backend.core.errors import ConfigurationError
from backend.execution.models import (
    TERMINAL_STATUSES,
    IntentBrokerSnapshot,
    IntentDryRun,
    IntentOrderView,
    IntentSnapshot,
    ModeOverride,
    payload_instant,
)
from backend.ops.process import ProcessLock

QUIESCENCE_LINE = "Quiescence: UNVERIFIED (standalone panic not coordinated). A later apply would REFUSE until panic coordination is built."
CHAIN_LINE = "Ledger chain NOT verified by dry-run; a later apply must verify it."

_MESSAGES = {
    "FIX_G_PAPER_ONLY": "Only PAPER evidence is permitted.",
    "FIX_G_SYSTEM_ACTIVE": "The system must already be HALTED or PAUSED.",
    "FIX_G_HOST_CONFIRMATION_REQUIRED": "An interactive host CLI is required.",
    "FIX_G_REASON_REQUIRED": "A bounded printable operator and reason are required.",
    "FIX_G_UNKNOWN_INTENT": "The intent does not exist.",
    "FIX_G_ENVIRONMENT_MISMATCH": "The intent environment differs.",
    "FIX_G_ACCOUNT_MISMATCH": "The bound account differs.",
    "FIX_G_INTENT_NOT_SUBMITTED": "The intent is not unresolved SUBMITTED.",
    "FIX_G_QUIESCENCE_UNVERIFIED": "The local snapshot or change check is unverified.",
    "FIX_G_LOOKUP_UNVERIFIED": "A bound broker GET could not be verified.",
    "FIX_G_LIVE_ORDER": "The broker order is not terminal.",
    "FIX_G_PROOF_INCOMPLETE": "The evidence is incomplete.",
    "FIX_G_CONTRADICTION": "The evidence contradicts prior or current observations.",
}


class IntentRefusal(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code + ": " + _MESSAGES[code])


class ProofReads(Protocol):
    async def open_orders(self) -> tuple[IntentOrderView, ...]: ...

    async def snapshot(self, intent: IntentSnapshot) -> IntentBrokerSnapshot: ...


class SnapshotWaiter(Protocol):
    async def wait(self) -> None: ...


class SnapshotReader:
    def __init__(self, settings: Settings, project: Path) -> None:
        self.project = project
        self.settings = settings
        try:
            url = make_url(settings.db_url.get_secret_value())
            if url.get_backend_name() != "sqlite" or url.database in {None, "", ":memory:"}:
                raise ValueError("Local SQLite required")
            selected = Path(str(url.database))
            self.path = selected if selected.is_absolute() else project / selected
        except Exception:
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            if self.path.is_symlink():
                raise ValueError("Direct local database required")
            with self.path.open("rb") as source:
                header = source.read(100)
            if len(header) != 100 or not header.startswith(b"SQLite format 3\x00"):
                raise ValueError("Existing SQLite database required")
            if header[18:20] == b"\x02\x02":
                # Never create missing WAL coordination sidecars or use immutable=1:
                # ignoring a concurrent WAL would make the displayed ledger stale.
                for suffix in ("-wal", "-shm"):
                    sidecar = self.path.with_name(self.path.name + suffix)
                    if not sidecar.is_file() or sidecar.is_symlink():
                        raise ValueError("Existing WAL sidecars required")
            uri = self.path.resolve(strict=True).as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
        except Exception:
            if connection is not None:
                connection.close()
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None
        try:
            yield connection
        finally:
            connection.close()

    def read(self, intent_id: UUID, account: str, environment: str) -> IntentSnapshot:
        try:
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM execution_orders WHERE id=?", (intent_id.hex,)
                ).fetchone()
                if row is None:
                    raise IntentRefusal("FIX_G_UNKNOWN_INTENT")
                if row["account_id"] != account:
                    raise IntentRefusal("FIX_G_ACCOUNT_MISMATCH")
                if row["environment"] != environment:
                    raise IntentRefusal("FIX_G_ENVIRONMENT_MISMATCH")
                event = connection.execute(
                    "SELECT state,created_at FROM order_events WHERE order_id=? ORDER BY seq DESC LIMIT 1",
                    (row["order_id"],),
                ).fetchone()
                if event is None or event["state"] != "SUBMITTED":
                    raise IntentRefusal("FIX_G_INTENT_NOT_SUBMITTED")
                submitted = connection.execute(
                    "SELECT created_at FROM order_events WHERE order_id=? AND state='SUBMITTED' ORDER BY seq LIMIT 1",
                    (row["order_id"],),
                ).fetchone()
                audit = connection.execute(
                    "SELECT id,seq FROM security_events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                control = connection.execute(
                    "SELECT state,version FROM system_control WHERE id=1"
                ).fetchone()
                history = connection.execute(
                    "SELECT id,state FROM system_events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                count = connection.execute("SELECT COUNT(*) FROM system_events").fetchone()[0]
                if control["version"] != count or control["state"] != (
                    history["state"] if history else "RUNNING"
                ):
                    raise ValueError("Unverified projection")
                positions = connection.execute(
                    "SELECT COALESCE(SUM(CASE WHEN e.side='BUY' THEN f.qty ELSE -f.qty END),0) FROM execution_fills f JOIN execution_orders e ON e.id=f.execution_order_id WHERE e.account_id=? AND e.environment=? AND e.symbol=?",
                    (account, environment, row["symbol"]),
                ).fetchone()[0]
                filled = connection.execute(
                    "SELECT COALESCE(SUM(qty),0) FROM execution_fills WHERE execution_order_id=?",
                    (intent_id.hex,),
                ).fetchone()[0]
                broker_id = None
                pause_owner = None
                mode = self.settings.execution_mode
                override_mode = None
                paused = False
                contradiction = False
                records = connection.execute(
                    "SELECT kind,detail FROM security_events ORDER BY seq"
                ).fetchmany(100001)
                if len(records) > 100000:
                    raise ValueError("Unbounded evidence")
                for record in records:
                    detail = json.loads(record["detail"])
                    if (
                        record["kind"] == "EXECUTION_ORDER_OBSERVED"
                        and UUID(detail["execution_order_id"]) == intent_id
                    ):
                        broker_id = UUID(detail["broker_order"]["order_id"])
                    if (
                        record["kind"] == "EXECUTION_ATTEMPT_CONTRADICTION"
                        and detail.get("client_order_id") == row["client_order_id"]
                    ):
                        contradiction = True
                    if (
                        record["kind"] == "EXECUTION_MODE_OVERRIDE"
                        and detail.get("account_id") == account
                        and detail.get("environment") == environment
                    ):
                        override = ModeOverride.model_validate(detail)
                        override_mode = override.mode
                        paused = override.paused
                        pause_owner = override.actor if paused else None
                        ranks = {"MANUAL": 0, "AUTO_PAPER": 1, "AUTO_LIVE": 2}
                        mode = (
                            override.mode
                            if ranks[override.mode] <= ranks[self.settings.execution_mode]
                            else self.settings.execution_mode
                        )
                return IntentSnapshot.model_validate(
                    {
                        "intent_id": intent_id,
                        "order_id": UUID(row["order_id"]),
                        "client_order_id": row["client_order_id"],
                        "account": account,
                        "environment": environment,
                        "symbol": row["symbol"],
                        "side": row["side"].lower(),
                        "qty": row["qty"],
                        "submitted_at": payload_instant(submitted["created_at"]),
                        "broker_order_id": broker_id,
                        "position_qty": positions,
                        "filled_qty": filled,
                        "audit_id": UUID(audit["id"]),
                        "audit_seq": audit["seq"],
                        "state": control["state"],
                        "state_id": UUID(history["id"]) if history else None,
                        "state_version": control["version"],
                        "mode": mode,
                        "override_mode": override_mode,
                        "paused": paused,
                        "pause_owner": pause_owner,
                        "contradiction": contradiction,
                    }
                )
        except IntentRefusal:
            raise
        except Exception:
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None

    def submitted(self) -> tuple[tuple[UUID, str, str], ...]:
        try:
            with self.connect() as connection:
                rows = connection.execute(
                    "SELECT e.id,e.account_id,e.environment FROM execution_orders e WHERE (SELECT o.state FROM order_events o WHERE o.order_id=e.order_id ORDER BY o.seq DESC LIMIT 1)='SUBMITTED' ORDER BY e.seq"
                ).fetchmany(100001)
                if len(rows) > 100000:
                    raise ValueError("Unbounded inventory")
                result = []
                for row in rows:
                    if re.fullmatch(r"[A-Za-z0-9-]{1,128}", row[1]) is None or row[2] not in {
                        "PAPER",
                        "LIVE",
                    }:
                        raise ValueError("Unverified display binding")
                    result.append((UUID(row[0]), row[1], row[2]))
                return tuple(result)
        except Exception:
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None


def validate_request(environment: str, operator: str, reason: str, host: bool) -> None:
    if environment != "PAPER":
        raise IntentRefusal("FIX_G_PAPER_ONLY")
    if not host:
        raise IntentRefusal("FIX_G_HOST_CONFIRMATION_REQUIRED")
    if any(
        not isinstance(value, str)
        or not value.strip()
        or not value.isprintable()
        or len(value) > 280
        for value in (operator, reason)
    ):
        raise IntentRefusal("FIX_G_REASON_REQUIRED")


def _classify(
    intent: IntentSnapshot, first: IntentBrokerSnapshot, second: IntentBrokerSnapshot
) -> IntentDryRun:
    if intent.contradiction:
        raise IntentRefusal("FIX_G_CONTRADICTION")
    for seen in (first, second):
        if (
            not seen.complete
            or seen.position_qty != intent.position_qty
            or seen.fill_qty != intent.filled_qty
        ):
            raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
        if seen.order is not None:
            order = seen.order
            if (order.client_order_id, order.symbol, order.side, order.qty) != (
                intent.client_order_id,
                intent.symbol,
                intent.side,
                intent.qty,
            ) or intent.broker_order_id not in {None, order.order_id}:
                raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED")
            if order.status not in TERMINAL_STATUSES:
                raise IntentRefusal("FIX_G_LIVE_ORDER")
            if order.filled_qty != intent.filled_qty:
                raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
            if order.status == "filled" and order.filled_qty != order.qty:
                raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
    if (first.order, first.not_found, first.position_qty, first.fill_qty, first.activity_ids) != (
        second.order,
        second.not_found,
        second.position_qty,
        second.fill_qty,
        second.activity_ids,
    ):
        raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
    outcome: Literal["TERMINAL", "QUALIFIED_NOT_FOUND"] = "TERMINAL"
    if first.order is None:
        if intent.broker_order_id is not None:
            raise IntentRefusal("FIX_G_CONTRADICTION")
        if (
            not first.not_found
            or not second.not_found
            or intent.filled_qty
            or first.fill_qty
            or first.observed_at - intent.submitted_at < timedelta(minutes=10)
            or second.observed_at - first.observed_at < timedelta(seconds=60)
        ):
            raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
        outcome = "QUALIFIED_NOT_FOUND"
    return IntentDryRun(
        intent_id=intent.intent_id,
        account=intent.account,
        outcome=outcome,
        status=None if first.order is None else first.order.status,
        pause_owner=intent.pause_owner,
    )


async def dry_run(
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
    waiter: SnapshotWaiter,
    announce: Callable[[str], None] = print,
) -> IntentDryRun:
    validate_request(environment, operator, reason, host)
    if re.fullmatch(r"[A-Za-z0-9-]{1,128}", account) is None:
        raise IntentRefusal("FIX_G_ACCOUNT_MISMATCH")
    try:
        lock_path = reader.project / "data" / "runtime.lock"
        if not lock_path.is_file() or lock_path.is_symlink() or lock_path.stat().st_size == 0:
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
        with ProcessLock(lock_path):
            before = reader.read(intent_id, account, environment)
            if before.state != "HALTED" and before.pause_owner is None:
                raise IntentRefusal("FIX_G_SYSTEM_ACTIVE")
            opened = await broker.open_orders()
            first = await broker.snapshot(before)
            announce("waiting 60s for second snapshot")
            await waiter.wait()
            second = await broker.snapshot(before)
            final_opened = await broker.open_orders()
            try:
                after = reader.read(intent_id, account, environment)
            except Exception:
                raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None
            order_sets = (
                frozenset(opened),
                frozenset(first.open_orders),
                frozenset(second.open_orders),
                frozenset(final_opened),
            )
            if after != before or any(orders != order_sets[0] for orders in order_sets[1:]):
                raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
            if (
                second.observed_at > clock.now()
                or first.observed_at < before.submitted_at
                or second.observed_at < first.observed_at
                or second.taken_at - first.taken_at < timedelta(seconds=60)
            ):
                raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
            return _classify(before, first, second)
    except IntentRefusal:
        raise
    except (OSError, sqlite3.Error, ConfigurationError):
        raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None
    except Exception:
        raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED") from None
