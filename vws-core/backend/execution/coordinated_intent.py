"""Coordinated dry-run and inert, always-refused apply attestation."""

from __future__ import annotations

import getpass
import hashlib
import json
import re
import sqlite3
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, NoReturn, Protocol
from uuid import UUID

from pydantic import StrictInt
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.config import Settings
from backend.core.database import SecurityEvent, SystemControl, SystemEvent, transaction
from backend.core.database import UTCDateTime as StoredUTCDateTime
from backend.core.errors import SafetyError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemStateStore
from backend.domain.models import FrozenModel
from backend.execution.intent_resolution import IntentRefusal, SnapshotReader, validate_request
from backend.execution.models import IntentDryRun, IntentOrderView, IntentSnapshot
from backend.ops.process import ProcessBusyError, ProcessLock
from backend.ops.quiescence import BrokerCoordination, QuiescenceError
from backend.ops.read_checks import IntentReadClient

ATTESTATION_KIND = "APPLY_SNAPSHOT_ATTESTATION"


@dataclass
class CoordinationWindow:
    coordination: BrokerCoordination
    strict: bool
    verified: bool = False
    acquired: bool = False

    def require(self) -> None:
        if self.strict and not self.verified:
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")

    def check(self) -> None:
        if self.verified:
            try:
                self.coordination.check()
            except (OSError, QuiescenceError):
                self.verified = False
        self.require()


class CoordinatedResolver:
    def __init__(self, coordination: BrokerCoordination) -> None:
        self.coordination = coordination

    async def run(
        self, operation: Callable[[], Awaitable[IntentDryRun]], *, strict: bool = False
    ) -> IntentDryRun:
        with self.window(strict=strict) as proof:
            value = await operation()
        return value.model_copy(update={"quiescence_verified": proof.verified})

    async def apply(
        self,
        operation: Callable[[], Awaitable[IntentDryRun]],
        *,
        reader: SnapshotReader,
        broker: InventoryReads,
        ledger: Ledger,
        state: SystemStateStore,
        request: ApplyRequest,
        confirm: Callable[[str], str],
        announce: Callable[[str], None] = print,
    ) -> NoReturn:
        """Audit two broker rounds; neither an attestation nor this method resolves an intent."""
        validate_request(request.environment, request.operator, request.reason, request.host)
        if request.resolution != "broker":
            raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
        if (
            ledger.engine is not state.engine
            or reader.path.resolve() != Path(str(ledger.engine.url.database)).resolve()
        ):
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
        with self.window(strict=True) as proof:
            result = await operation()
            proof.check()
            if result.intent_id != request.intent_id or result.account != request.account:
                raise IntentRefusal("FIX_G_ACCOUNT_MISMATCH")
            for line in result.model_copy(update={"quiescence_verified": True}).lines():
                announce(line)
            phrase = f"CLEAR INTENT {request.intent_id} PAPER {request.account}"
            if confirm(phrase) != phrase:
                raise IntentRefusal("FIX_G_HOST_CONFIRMATION_REQUIRED")
            lock = reader.project / "data" / "runtime.lock"
            if not lock.is_file() or lock.is_symlink() or lock.stat().st_size == 0:
                raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
            with ProcessLock(lock):
                intent = reader.read(request.intent_id, request.account, request.environment)
                if intent.state != "HALTED" and not intent.paused:
                    raise IntentRefusal("FIX_G_SYSTEM_ACTIVE")
                with Session(ledger.engine) as session:
                    ledger._verify_in_session(session)
                    previous = session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == ATTESTATION_KIND)
                    ).all()
                    if any(
                        row.detail.get("intent_id") == str(intent.intent_id) for row in previous
                    ):
                        raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
                first = await broker.inventory()
                first_hash = first.digest()
                proof.check()
                try:
                    with transaction(ledger.engine) as session:
                        self._check_local(session, proof, reader, intent, intent.audit_id)
                        epoch = self.coordination._epoch
                        if epoch is None:
                            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
                        record = ledger.append_in_session(
                            session,
                            SecurityEvent,
                            kind=ATTESTATION_KIND,
                            telegram_user_id=None,
                            ts=ledger.clock.now(),
                            detail={
                                "intent_id": str(intent.intent_id),
                                "account": intent.account,
                                "environment": intent.environment,
                                "config_hash": reader.settings.config_hash,
                                "epoch": [list(item) for item in epoch],
                                "hash_a": first_hash,
                                "slot_proof": [f"slot-{i}" for i in range(8)],
                                "os_actor": getpass.getuser(),
                                "operator_hash": hashlib.sha256(
                                    request.operator.encode()
                                ).hexdigest(),
                                "reason_hash": hashlib.sha256(request.reason.encode()).hexdigest(),
                            },
                        )
                except (SQLAlchemyError, SafetyError, OSError) as error:
                    state.halt_for_error(error)
                    raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None
                second = await broker.inventory()
                second_hash = second.digest()
                if first_hash != second_hash:
                    raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
                try:
                    with transaction(ledger.engine) as session:
                        self._check_local(session, proof, reader, intent, record.id)
                        saved = session.get(SecurityEvent, record.id)
                        if (
                            saved is None
                            or saved.kind != ATTESTATION_KIND
                            or (
                                saved.detail.get("hash_a") != second_hash
                                or saved.detail.get("intent_id") != str(intent.intent_id)
                                or saved.detail.get("account") != intent.account
                                or saved.detail.get("environment") != intent.environment
                                or saved.detail.get("config_hash") != reader.settings.config_hash
                                or saved.detail.get("epoch")
                                != [list(item) for item in self.coordination._epoch or ()]
                                or saved.detail.get("slot_proof") != [f"slot-{i}" for i in range(8)]
                            )
                        ):
                            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
                        # No success/lifecycle write exists. TX2 validates only the inert TX1 audit.
                except (SQLAlchemyError, SafetyError, OSError) as error:
                    state.halt_for_error(error)
                    raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None
                # Recheck after TX2 before any possible later broker I/O. There is none here.
                proof.check()
        raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")

    @staticmethod
    def _check_local(
        session: Session,
        proof: CoordinationWindow,
        reader: SnapshotReader,
        intent: IntentSnapshot,
        expected_audit: UUID,
    ) -> None:
        proof.check()
        # The owning transaction must see its own state, not a second connection's snapshot.
        control = session.get(SystemControl, 1, populate_existing=True)
        history = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()).limit(1))
        if (
            control is None
            or control.state != intent.state
            or control.version != intent.state_version
            or (None if history is None else history.id) != intent.state_id
            or (history is not None and history.state != control.state)
        ):
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
        current = reader.read(intent.intent_id, intent.account, intent.environment)
        excluded = {"audit_id", "audit_seq"}
        if current.audit_id != expected_audit or current.model_dump(
            exclude=excluded
        ) != intent.model_dump(exclude=excluded):
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")

    @contextmanager
    def window(self, *, strict: bool) -> Iterator[CoordinationWindow]:
        proof = CoordinationWindow(self.coordination, strict)
        try:
            self.coordination.acquire_proof()
        except (OSError, QuiescenceError):
            proof.verified = False
        else:
            proof.acquired = proof.verified = True
        try:
            proof.require()
            yield proof
        finally:
            primary = sys.exception()
            try:
                if primary is None:
                    proof.check()
            finally:
                if proof.acquired:
                    try:
                        self.coordination.release_proof()
                    except (OSError, QuiescenceError) as error:
                        proof.verified = False
                        if primary is not None:
                            primary.add_note("Broker proof cleanup failed: " + type(error).__name__)
                        else:
                            proof.require()


class ApplyRequest(FrozenModel):
    intent_id: UUID
    account: str
    environment: str
    operator: str
    reason: str
    host: bool
    resolution: Literal["broker", "attestation"] = "broker"


class BrokerInventory(FrozenModel):
    open_orders: tuple[IntentOrderView, ...]
    positions: tuple[tuple[str, StrictInt], ...]

    def digest(self) -> str:
        if len({row.order_id for row in self.open_orders}) != len(self.open_orders) or len(
            {symbol for symbol, _ in self.positions}
        ) != len(self.positions):
            raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED")
        if any(
            re.fullmatch(r"[A-Z][A-Z0-9.-]{0,31}", symbol) is None
            or type(qty) is not int
            or qty < 0
            for symbol, qty in self.positions
        ):
            raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED")
        payload = {
            "open_orders": [
                row.model_dump(mode="json")
                for row in sorted(self.open_orders, key=lambda row: row.order_id)
            ],
            "positions": sorted(self.positions),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class InventoryReads(Protocol):
    async def inventory(self) -> BrokerInventory: ...


class InventoryClient:
    """Exactly two requested GET rounds; no order-mutation surface."""

    def __init__(self, client: IntentReadClient) -> None:
        self.client = client

    async def inventory(self) -> BrokerInventory:
        orders = await self.client.open_orders()
        raw = await self.client._fetch("/v2/positions")
        if not isinstance(raw, list) or len(raw) >= 500:
            raise IntentRefusal("FIX_G_PROOF_INCOMPLETE")
        positions: list[tuple[str, int]] = []
        for item in raw:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("symbol"), str)
                or item.get("side") != "long"
            ):
                raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED")
            try:
                quantity = IntentReadClient._whole(item.get("qty"))
            except (ArithmeticError, ValueError):
                raise IntentRefusal("FIX_G_LOOKUP_UNVERIFIED") from None
            positions.append((item["symbol"], quantity))
        result = BrokerInventory(open_orders=orders, positions=tuple(positions))
        result.digest()
        return result


def _utc_row(cursor: sqlite3.Cursor, values: tuple[object, ...]) -> sqlite3.Row:
    """Restore only declared ledger created_at metadata using its production SQL type."""
    row = list(values)
    for index, description in enumerate(cursor.description):
        if description[0] == "created_at" and isinstance(row[index], str):
            value = row[index]
            assert isinstance(value, str)
            row[index] = StoredUTCDateTime().process_result_value(
                datetime.fromisoformat(value), dialect()
            )
    return sqlite3.Row(cursor, tuple(row))


class CoordinatedSnapshotReader(SnapshotReader):
    """Clean-close WAL reads require live coordination plus an already-held runtime lock."""

    def __init__(self, settings: Settings, project: Path) -> None:
        super().__init__(settings, project)
        self.coordination: BrokerCoordination | None = None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.path.open("rb") as source:
                header = source.read(100)
            sidecars = [self.path.with_name(self.path.name + suffix) for suffix in ("-wal", "-shm")]
            missing = [not path.exists() for path in sidecars]
            if header[18:20] == b"\x02\x02" and any(missing):
                if not all(missing) or self.path.is_symlink() or self.coordination is None:
                    raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
                self.coordination.check()
                lock = self.project / "data" / "runtime.lock"
                if not lock.is_file() or lock.is_symlink():
                    raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
                try:
                    with ProcessLock(lock):
                        pass
                except ProcessBusyError:
                    pass
                else:
                    raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED")
                uri = self.path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"
                connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None)
                connection.row_factory = _utc_row
                try:
                    connection.execute("PRAGMA query_only=ON")
                    yield connection
                finally:
                    connection.close()
                return
        except (OSError, sqlite3.Error, QuiescenceError, ValueError):
            raise IntentRefusal("FIX_G_QUIESCENCE_UNVERIFIED") from None
        with super().connect() as connection:
            connection.row_factory = _utc_row
            yield connection
