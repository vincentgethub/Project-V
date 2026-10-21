"""AX-11/16/20..26/31: offline physical-attempt and admission regressions."""

import asyncio
import re
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide
from pydantic import SecretStr
from requests import HTTPError, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import Settings
from backend.core.database import ExecutionOrderRecord, OrderEvent
from backend.core.errors import (
    DataIntegrityError,
    ExecutionDisabledError,
    OrderRejectedError,
    ProviderError,
    ReconciliationError,
)
from backend.core.system_state import SystemState
from backend.data.async_reader import AsyncTokenBucket
from backend.data.fill_polling import ObservedFill
from backend.domain.models import Side
from backend.execution.alpaca_executor import (
    AlpacaExecutor,
    ExactLimit,
    ExactStop,
    _require_absent_sell_unfilled,
    _require_acquisition_basis,
    _require_cancel_lifecycle,
    _require_entry_projection,
    _require_fill_parent,
    _require_fresh_cancel_roots,
    _require_oco_entry,
    _require_side,
    parse_order,
)
from backend.execution.models import AutoPrerequisites
from backend.execution.modes import ModeStore
from backend.execution.worker import SingleAttemptWorker
from backend.net.egress import EgressPolicy, build_allowlist
from backend.tests.test_security_cli import MemorySecrets
from backend.tests.test_swarm_and_callbacks import Harness, click, deliver, make_research_harness

harness = make_research_harness


def journal_existing_partial_repair(built: AlpacaExecutor) -> None:
    """Seed an explicit interrupted repair, rather than an unjournaled gap."""
    from backend.execution.stop_evidence import current_stop
    from backend.execution.storage import held_quantity

    with Session(built.state.engine) as session:
        entries = tuple(
            session.scalars(
                select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
            )
        )
        pending = [
            (row, held_quantity(session, row.id), current_stop(session, row)) for row in entries
        ]
    for entry, qty, stop in pending:
        if qty > 0:
            built._begin_protection_repair(entry, qty, stop, stop)


AUTO = {
    "execution_mode": "AUTO_PAPER",
    "auto_min_score": Decimal("7.5"),
    "broker_api_key": SecretStr("TEST_ONLY_PAPER_ID"),
    "broker_secret_key": SecretStr("TEST_ONLY_PAPER_SECRET"),
    "healthcheck_ping_url": SecretStr("https://hc-ping.com/test-only"),
}


def test_SEC_73_cancel_requires_retained_lifecycle_with_exact_integrity_message() -> None:
    with pytest.raises(ReconciliationError) as caught:
        _require_cancel_lifecycle(None)
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Cancellation has no order lifecycle"
    pending = cast(OrderEvent, SimpleNamespace(state="CANCEL_REQUESTED"))
    assert _require_cancel_lifecycle(pending) is pending


@pytest.mark.parametrize("role", [None, "STOP", "ENTRY"])
def test_EX_05_oco_stop_requires_its_managed_entry(role: str | None) -> None:
    entry = None if role is None else cast(ExecutionOrderRecord, SimpleNamespace(role=role))
    if role == "ENTRY":
        assert _require_oco_entry(entry) is entry
    else:
        with pytest.raises(ReconciliationError) as caught:
            _require_oco_entry(entry)
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == "EX-05: OCO stop child lost its held entry"


@pytest.mark.parametrize("side", [OrderSide.BUY, OrderSide.SELL])
def test_AX_23_required_side_preserves_broker_direction(side: OrderSide) -> None:
    assert _require_side(cast(Any, SimpleNamespace(side=side))) is side


def test_AX_23_required_side_refuses_missing_direction() -> None:
    with pytest.raises(
        DataIntegrityError, match=re.escape("Validated order has no side")
    ) as caught:
        _require_side(cast(Any, SimpleNamespace(side=None)))
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "Validated order has no side"


@pytest.mark.parametrize("role,parent", [("ENTRY", None), ("STOP", UUID(int=702))])
def test_XK_02_fill_parent_preserves_valid_entry_and_child_bindings(
    role: str, parent: UUID | None
) -> None:
    instruction = cast(Any, SimpleNamespace(role=role, parent_execution_id=parent))
    assert _require_fill_parent(instruction) == parent


def test_XK_02_fill_parent_refuses_orphaned_sell_with_exact_message() -> None:
    instruction = cast(Any, SimpleNamespace(role="STOP", parent_execution_id=None))
    with pytest.raises(
        ReconciliationError, match=re.escape("Fill notification lost its managed entry")
    ) as caught:
        _require_fill_parent(instruction)
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Fill notification lost its managed entry"


def test_XK_02_fill_notice_requires_acquisition_basis() -> None:
    with pytest.raises(
        ReconciliationError, match=re.escape("Fill notice has no verified acquisition basis")
    ) as caught:
        _require_acquisition_basis(())
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Fill notice has no verified acquisition basis"


def test_XK_02_fill_notice_accepts_present_acquisition_basis() -> None:
    _require_acquisition_basis(cast(Any, (object(),)))


def test_AX_25_missing_entry_projection_refuses_with_exact_integrity_error() -> None:
    with pytest.raises(
        DataIntegrityError, match=re.escape("Entry state projection is missing")
    ) as caught:
        _require_entry_projection(None)
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "Entry state projection is missing"
    projection = cast(Any, SimpleNamespace(id=1, state="RUNNING", version=0))
    assert _require_entry_projection(projection) is projection


@pytest.mark.parametrize("missing", ["parent", "target", "both"])
def test_EX_06_cancel_proof_requires_both_fresh_roots(missing: str) -> None:
    root = cast(Any, object())
    with pytest.raises(
        DataIntegrityError, match=re.escape("EX-06: fresh paper roots unavailable")
    ) as caught:
        _require_fresh_cancel_roots(
            None if missing in {"parent", "both"} else root,
            None if missing in {"target", "both"} else root,
        )
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "EX-06: fresh paper roots unavailable"


def test_EX_06_cancel_proof_preserves_both_fresh_roots() -> None:
    parent, target = cast(Any, object()), cast(Any, object())
    assert _require_fresh_cancel_roots(parent, target) == (parent, target)


def test_AX_31_absent_sell_must_have_zero_captured_shares() -> None:
    _require_absent_sell_unfilled(0)
    with pytest.raises(
        ReconciliationError, match=re.escape("Absent sell intent has captured fills")
    ) as caught:
        _require_absent_sell_unfilled(1)
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Absent sell intent has captured fills"


@pytest.mark.parametrize("raw", [None, [], "not a broker response", 1])
def test_AX_31_nonobject_broker_responses_are_rejected(raw: object) -> None:
    with pytest.raises(
        DataIntegrityError, match=re.escape("Broker order must be exact raw JSON")
    ) as caught:
        parse_order(raw)
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == "Broker order must be exact raw JSON"


def test_AX_31_native_broker_timestamp_preserves_utc_instant(clock: Any) -> None:
    raw = {
        "id": str(UUID(int=701)),
        "client_order_id": "paper-timestamp",
        "symbol": "NVDA",
        "side": "buy",
        "type": "limit",
        "order_class": "simple",
        "time_in_force": "day",
        "qty": "1",
        "filled_qty": "0",
        "status": "new",
        "limit_price": "100.00",
        "stop_price": None,
        "submitted_at": clock.now(),
        "legs": None,
    }
    order = parse_order(raw)
    assert order.submitted_at == clock.now()
    assert order.qty == 1 and order.filled_qty == 0
    assert order.limit_price == Decimal("100.00")


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("qty", True, "Broker share quantity must be exact text or integer"),
        ("qty", 1.0, "Broker share quantity must be exact text or integer"),
        ("qty", "1.5", "Broker share quantity is not a bounded whole number"),
        ("qty", "0", "Broker share quantity is not a bounded whole number"),
        ("qty", "-1", "Broker share quantity is not a bounded whole number"),
        ("qty", "2147483648", "Broker share quantity is not a bounded whole number"),
        ("filled_qty", "-1", "Broker share quantity is not a bounded whole number"),
        ("filled_qty", False, "Broker share quantity must be exact text or integer"),
        ("limit_price", True, "Broker price must retain exact money"),
        ("limit_price", 100.0, "Broker price must retain exact money"),
        ("submitted_at", None, "Broker order timestamp is unavailable"),
        ("submitted_at", "x" * 65, "Broker order timestamp is unavailable"),
        ("submitted_at", "tomorrow", "Broker order timestamp is invalid"),
        ("legs", {}, "Broker bracket leg collection is invalid"),
        ("legs", [{}, {}, {}], "Broker bracket leg collection is invalid"),
        ("id", "not-a-uuid", "Broker order identity or shape cannot be verified"),
        ("side", "short", "Broker order identity or shape cannot be verified"),
        ("status", "unrecognized", "Broker order identity or shape cannot be verified"),
        ("reject_reason", True, "Broker order identity or shape cannot be verified"),
        ("reject_reason", "x" * 513, "Broker order identity or shape cannot be verified"),
        ("failed_at", "not-an-instant", "Broker order identity or shape cannot be verified"),
        ("failed_at", "2000-01-01T00:00:00Z", "Broker order identity or shape cannot be verified"),
    ],
)
def test_AX_31_raw_broker_faults_have_exact_typed_audit_messages(
    clock: Any, field: str, value: object, message: str
) -> None:
    from backend.core.errors import DataIntegrityError

    raw = {
        "id": str(UUID(int=700)),
        "client_order_id": "paper-raw",
        "symbol": "NVDA",
        "side": "buy",
        "type": "limit",
        "order_class": "simple",
        "time_in_force": "day",
        "qty": "1",
        "filled_qty": "0",
        "status": "new",
        "limit_price": "100.00",
        "stop_price": None,
        "submitted_at": clock.now().isoformat(),
        "legs": None,
    }
    with pytest.raises(DataIntegrityError) as caught:
        parse_order({**raw, field: value})
    assert type(caught.value) is DataIntegrityError
    assert str(caught.value) == message


@pytest.mark.parametrize(
    "field,value",
    [
        ("side", "buy"),
        ("time_in_force", "day"),
        ("order_class", "bracket"),
        ("extended_hours", False),
        ("notional", Decimal(1)),
    ],
)
def test_AX_27_stop_repairs_refuse_unsafe_shapes_with_exact_reason(
    field: str, value: object
) -> None:
    from pydantic import ValidationError

    payload: dict[str, Any] = {
        "symbol": "NVDA",
        "qty": 3,
        "side": "sell",
        "type": "stop",
        "time_in_force": "gtc",
        "client_order_id": "vws-paper-repair",
        "stop_price": Decimal("95.00"),
    }
    with pytest.raises(ValidationError) as caught:
        ExactStop.model_validate({**payload, field: value})
    assert type(caught.value) is ValidationError
    message = {
        "order_class": "bracket orders require take_profit.limit_price.",
        "notional": "Both qty and notional can not be set.",
    }.get(field, "Stop repair requires one whole-share SELL GTC stop")
    assert caught.value.errors()[0]["msg"] == "Value error, " + message


@pytest.mark.parametrize("kind", ["bracket", "oto", "oco", "simple"])
def test_AX_23_27_exact_order_shapes_preserve_integer_shares_and_cent_text(kind: str) -> None:
    payload: dict[str, Any] = {
        "symbol": "NVDA",
        "qty": 3,
        "side": "sell" if kind in {"simple", "oco"} else "buy",
        "type": "limit",
        "time_in_force": "day" if kind == "simple" else "gtc",
        "order_class": kind,
        "client_order_id": "vws-paper-shape",
        "limit_price": Decimal("100.10"),
    }
    expected: dict[str, Any] = {
        "symbol": "NVDA",
        "qty": "3",
        "side": payload["side"],
        "type": "limit",
        "time_in_force": payload["time_in_force"],
        "order_class": kind,
        "client_order_id": "vws-paper-shape",
        "limit_price": "100.10",
    }
    if kind != "simple":
        payload["stop_loss"] = {"stop_price": Decimal("95.20")}
        expected["stop_loss"] = {"stop_price": "95.20"}
    if kind in {"bracket", "oco"}:
        target = "100.10" if kind == "oco" else "110.30"
        payload["take_profit"] = {"limit_price": Decimal(target)}
        expected["take_profit"] = {"limit_price": target}
    if kind == "oco":
        del expected["limit_price"]
    request = ExactLimit.model_validate(payload)
    assert request.to_request_fields() == expected


@pytest.mark.parametrize("kind", ["bracket", "oto", "oco", "simple"])
def test_AX_23_no_order_shape_can_serialize_without_a_side(kind: str) -> None:
    from pydantic import ValidationError

    payload: dict[str, Any] = {
        "symbol": "NVDA",
        "qty": 3,
        "side": "sell" if kind in {"simple", "oco"} else "buy",
        "time_in_force": "day" if kind == "simple" else "gtc",
        "order_class": kind,
        "client_order_id": "vws-paper-no-side",
        "limit_price": Decimal("100.10"),
    }
    if kind != "simple":
        payload["stop_loss"] = {"stop_price": Decimal("95.20")}
    if kind in {"bracket", "oco"}:
        payload["take_profit"] = {
            "limit_price": Decimal("100.10") if kind == "oco" else Decimal("110.30")
        }
    valid = ExactLimit.model_validate(payload)
    corrupt = valid.model_copy(update={"side": None})
    with pytest.raises(ValidationError) as caught:
        corrupt.to_request_fields()
    assert type(caught.value) is ValidationError
    assert (
        caught.value.errors()[0]["msg"]
        == "Value error, side is required for all order classes other than mleg."
    )


@pytest.mark.parametrize(
    "kind,changes,message",
    [
        (
            "bracket",
            {"side": "sell"},
            "Entry requires one BUY GTC bracket with ordered cent prices",
        ),
        (
            "bracket",
            {"time_in_force": "day"},
            "Entry requires one BUY GTC bracket with ordered cent prices",
        ),
        ("bracket", {"take_profit": None}, "bracket orders require take_profit.limit_price."),
        ("oto", {"side": "sell"}, "EX-02: OTO is BUY GTC LIMIT with a protective stop only"),
        ("oto", {"stop_loss": None}, "oto orders require either take_profit or stop_loss."),
        (
            "oto",
            {"stop_loss": {"stop_price": Decimal("100.10")}},
            "EX-02: OTO is BUY GTC LIMIT with a protective stop only",
        ),
        ("oco", {"side": "buy"}, "EX-05: OCO is a protected SELL GTC exit with an exact target"),
        (
            "oco",
            {"time_in_force": "day"},
            "EX-05: OCO is a protected SELL GTC exit with an exact target",
        ),
        (
            "oco",
            {"take_profit": {"limit_price": Decimal("101.00")}},
            "EX-05: OCO is a protected SELL GTC exit with an exact target",
        ),
        ("simple", {"side": "buy"}, "Plain limits are DAY SELL exits only"),
        ("simple", {"time_in_force": "gtc"}, "Plain limits are DAY SELL exits only"),
        (
            "simple",
            {"extended_hours": False},
            "Only whole-share regular-hours equity orders are allowed",
        ),
    ],
)
def test_AX_23_27_unsafe_order_shapes_keep_exact_refusal(
    kind: str, changes: dict[str, Any], message: str
) -> None:
    import re

    from pydantic import ValidationError

    payload: dict[str, Any] = {
        "symbol": "NVDA",
        "qty": 3,
        "side": "sell" if kind in {"simple", "oco"} else "buy",
        "time_in_force": "day" if kind == "simple" else "gtc",
        "order_class": kind,
        "client_order_id": "vws-paper-shape",
        "limit_price": Decimal("100.10"),
    }
    if kind != "simple":
        payload["stop_loss"] = {"stop_price": Decimal("95.20")}
    if kind in {"bracket", "oco"}:
        payload["take_profit"] = {
            "limit_price": Decimal("100.10") if kind == "oco" else Decimal("110.30")
        }
    with pytest.raises(ValidationError, match=re.escape(message)) as caught:
        ExactLimit.model_validate({**payload, **changes})
    assert type(caught.value) is ValidationError
    assert caught.value.errors()[0]["msg"] == "Value error, " + message


def api_error(status: int) -> APIError:
    response = Response()
    response.status_code = status
    return cast(Callable[..., APIError], APIError)(
        '{"code":0,"message":"synthetic"}', HTTPError(response=response)
    )


class FakeTradingClient:
    """Pinned interface fake; no SDK transport or sockets are created."""

    _base_url = "https://paper-api.alpaca.markets"

    def __init__(self, h: Harness) -> None:
        self.h = h
        self.posts: list[dict[str, Any]] = []
        self.lookups: list[str] = []
        self.orders: dict[str, dict[str, Any]] = {}
        self.failure: str | None = None
        self.raise_fault: str | None = None
        self.positions: list[dict[str, Any]] = []

    def get_account(self) -> dict[str, Any]:
        return {
            "id": "offline-paper",
            "status": "ACTIVE",
            "currency": "USD",
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }

    def get_order_by_client_id(self, client_id: str) -> dict[str, Any]:
        self.lookups.append(client_id)
        if client_id not in self.orders:
            raise api_error(404)
        return self.orders[client_id]

    def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
        return self._submit_paper(order_data)

    def _submit_paper(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
        fields = order_data.to_request_fields()
        if fields["client_order_id"].startswith("vws-m-"):
            self.failure = None
            if self.raise_fault == "reject-once":
                self.failure, self.raise_fault = "reject", None
            elif self.raise_fault == "reject-both":
                self.failure = "reject"
            elif self.raise_fault in {"accepted-timeout", "ambiguous-missing"}:
                self.failure = self.raise_fault
        self.posts.append(fields)
        if self.failure == "reject":
            raise api_error(422)
        if self.failure == "ambiguous-missing":
            raise TimeoutError("synthetic timeout")
        raw = {
            **fields,
            "id": str(uuid4()),
            "filled_qty": "0",
            "status": "new",
            "submitted_at": self.h.clock.now().isoformat(),
            "legs": None,
        }
        if fields.get("order_class") == "oco":
            raw["limit_price"] = fields["take_profit"]["limit_price"]
        if "stop_loss" in fields:
            specifications = (
                (("limit", fields["take_profit"]), ("stop", fields["stop_loss"]))
                if "take_profit" in fields and fields["order_class"] != "oco"
                else (("stop", fields["stop_loss"]),)
            )
            raw["legs"] = [
                {
                    "id": str(uuid4()),
                    "client_order_id": "generated-" + uuid4().hex,
                    "symbol": fields["symbol"],
                    "side": "sell",
                    "type": kind,
                    "qty": fields["qty"],
                    "filled_qty": "0",
                    "status": "new" if fields["order_class"] == "oco" else "held",
                    "time_in_force": "gtc",
                    "order_class": "simple",
                    "legs": None,
                    "submitted_at": raw["submitted_at"],
                    **price,
                }
                for kind, price in specifications
            ]
        self.orders[fields["client_order_id"]] = raw
        if self.failure == "accepted-timeout":
            raise TimeoutError("synthetic server accepted; response lost")
        return raw

    def cancel_order_by_id(self, order_id: UUID | str) -> None:
        self._cancel_paper(order_id)

    def _cancel_paper(self, order_id: UUID | str) -> None:
        if self.raise_fault == "cancel":
            raise TimeoutError("offline unconfirmed cancellation")
        for raw in self.orders.values():
            if raw["id"] == str(order_id):
                raw["status"] = "canceled"
                for child in raw["legs"] or ():
                    child["status"] = "canceled"
                return
            for child in raw["legs"] or ():
                if child["id"] == str(order_id):
                    for leg in raw["legs"]:
                        leg["status"] = "canceled"
                    return
        raise api_error(404)

    def get_order_by_id(self, order_id: UUID | str, filter: object = None) -> dict[str, Any]:
        for raw in self.orders.values():
            if raw["id"] == str(order_id):
                return raw
            for leg in raw["legs"] or ():
                if leg["id"] == str(order_id):
                    return cast(dict[str, Any], leg)
        raise api_error(404)

    def get_orders(self, filter: object = None) -> list[dict[str, Any]]:
        return list(self.orders.values())

    def get_all_positions(self) -> list[dict[str, Any]]:
        return self.positions


def executor(
    h: Harness,
    client: FakeTradingClient,
    settings: Settings | None = None,
    *,
    constructor: type[AlpacaExecutor] = AlpacaExecutor,
    account_id: str = "offline-paper",
) -> AlpacaExecutor:
    settings = settings or h.settings
    store = MemorySecrets()
    store.set("ALPACA_PAPER_KEY_ID", settings.broker_api_key)
    store.set("ALPACA_PAPER_SECRET", settings.broker_secret_key)
    modes = ModeStore(settings, h.state, account_id)
    proof = AutoPrerequisites(
        account_id=modes.account_id,
        environment="PAPER",
        config_hash=settings.config_hash,
        doctor_fully_green=True,
        watchdog_enabled=True,
        backup_chain_verified=True,
        backup_verified_at=h.clock.now(),
        telegram_verified_at=h.clock.now(),
        clock_verified_at=h.clock.now(),
    )

    async def notify(message: str, urgent: bool) -> None:
        assert message.startswith("PAPER")

    return constructor(
        settings,
        h.config,
        h.state,
        modes,
        h.source,
        h.gate.risk,
        h.gate.compliance,
        h.gate.risk.cro.calendar,
        SingleAttemptWorker(AsyncTokenBucket(h.clock)),
        store,
        proof,
        policy=EgressPolicy(build_allowlist(mode=settings.execution_mode), h.state.ledger),
        notify=notify,
        client=client,
        entry_variant_allowed=lambda: True,  # Explicit offline fixture; never production admission.
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_16_cancelled_physical_entry_retains_intent_and_halts_without_retry(
    harness: Harness,
) -> None:
    from backend.core.database import SecurityEvent, SystemEvent

    calls: list[str] = []

    class CanceledPaperBroker(FakeTradingClient):
        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            calls.append(order_data.client_order_id)
            raise asyncio.CancelledError("Paper physical attempt canceled")

    alert = await deliver(harness)
    client = CanceledPaperBroker(harness)
    built = executor(harness, client)
    with pytest.raises(asyncio.CancelledError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is asyncio.CancelledError
    assert str(caught.value) == ""
    with Session(harness.state.engine) as session:
        intent = session.scalar(select(ExecutionOrderRecord))
        assert intent is not None and intent.role == "ENTRY"
        assert calls == [intent.client_order_id]
        halt = session.scalar(select(SystemEvent).order_by(SystemEvent.seq.desc()))
        assert halt is not None and halt.state == "HALTED"
        assert halt.reason == "Order attempt canceled; look up the client ID before any recovery"
        assert (
            tuple(
                session.scalars(
                    select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
                )
            )
            == ()
        )
    assert built._confirmed_absence(intent) is False
    assert harness.state.current() == SystemState.HALTED
    assert client.posts == []
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_rejected_broker_response_is_exact_and_never_retried(harness: Harness) -> None:
    class RejectedPaperBroker(FakeTradingClient):
        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            raw = super()._submit_paper(order_data)
            raw["status"] = "rejected"
            raw["legs"] = None
            return raw

    alert = await deliver(harness)
    client = RejectedPaperBroker(harness)
    built = executor(harness, client)
    with pytest.raises(OrderRejectedError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is OrderRejectedError
    assert str(caught.value) == "Broker order reports a confirmed rejection"
    assert len(client.posts) == 1
    assert harness.state.current() == SystemState.RUNNING
    with Session(harness.state.engine) as session:
        latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()))
        assert latest is not None and latest.state == "REJECTED"
        assert latest.reason == "broker rejection confirmed; no retry"
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_16_failed_lookup_after_ambiguous_submit_preserves_single_intent(
    harness: Harness,
) -> None:
    from backend.core.database import SecurityEvent

    class UnavailablePaperBroker(FakeTradingClient):
        def get_order_by_client_id(self, client_id: str) -> dict[str, Any]:
            if self.posts:
                self.lookups.append(client_id)
                raise TimeoutError("Paper lookup unavailable")
            return super().get_order_by_client_id(client_id)

    alert = await deliver(harness)
    client = UnavailablePaperBroker(harness)
    client.failure = "ambiguous-missing"
    built = executor(harness, client)
    with pytest.raises(ProviderError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is ProviderError
    assert str(caught.value) == "Automatic entry failed closed; inspect persisted intent"
    assert len(client.posts) == 1
    assert client.lookups == [client.posts[0]["client_order_id"]] * 2
    assert harness.state.current() == SystemState.HALTED
    with Session(harness.state.engine) as session:
        outcomes = tuple(
            session.scalars(
                select(SecurityEvent).where(SecurityEvent.kind == "EXECUTION_SUBMIT_OUTCOME")
            )
        )
        assert len(outcomes) == 1
        assert outcomes[0].detail["outcome"] == "ERROR"
        assert outcomes[0].detail["error_type"] == "TimeoutError"
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_16_accepted_canceled_attempt_is_bound_before_any_recovery_retry(
    harness: Harness,
) -> None:
    class InterruptedPaperBroker(FakeTradingClient):
        def submit_order(self, order_data: ExactLimit | ExactStop) -> dict[str, Any]:
            super()._submit_paper(order_data)
            raise asyncio.CancelledError("Paper response delivery canceled")

    alert = await deliver(harness)
    client = InterruptedPaperBroker(harness)
    built = executor(harness, client)
    with pytest.raises(asyncio.CancelledError):
        await built.enter(alert.proposal_id)
    with Session(harness.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
        assert entry is not None
    recovered = await built._read_bound(entry)
    assert recovered is not None
    assert str(recovered.order_id) == client.orders[entry.client_order_id]["id"]
    assert recovered.client_order_id == entry.client_order_id
    assert len(recovered.legs) == 2
    assert len(client.posts) == 1
    assert client.lookups == [entry.client_order_id, entry.client_order_id]
    await built.cancel_unfilled_entries()
    assert len(client.posts) == 1
    assert client.orders[entry.client_order_id]["status"] == "canceled"
    assert harness.state.current() == SystemState.HALTED
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["lookup_identity", "read_disappeared", "prepare_unavailable"])
async def test_AX_31_identity_and_availability_faults_do_not_resubmit(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    with Session(harness.state.engine) as session:
        entry = session.scalar(
            select(ExecutionOrderRecord).where(ExecutionOrderRecord.role == "ENTRY")
        )
        assert entry is not None
    if fault == "lookup_identity":
        monkeypatch.setattr(
            client, "get_order_by_client_id", lambda _: client.orders[entry.client_order_id]
        )
        with pytest.raises(ReconciliationError) as caught:
            await built._lookup("another-paper-client-id")
        expected = "Client-ID lookup returned another order"
    else:

        def unavailable(*args: Any, **kwargs: Any) -> Any:
            raise TimeoutError("Paper evidence unavailable")

        if fault == "read_disappeared":
            monkeypatch.setattr(client, "get_order_by_id", unavailable)
            with pytest.raises(ReconciliationError) as caught:
                await built._read_bound(entry)
            expected = "Previously bound broker order disappeared"
        else:
            monkeypatch.setattr(client, "get_order_by_client_id", unavailable)
            with pytest.raises(ReconciliationError) as caught:
                await built.prepare_fills(("NVDA",))
            expected = "Fill identities cannot be bound; entries halted"
            assert harness.state.current() == SystemState.HALTED
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == expected
    assert len(client.posts) == 1
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("timeout", [False, True])
async def test_AX_16_double_trigger_and_accepted_timeout_never_duplicate(
    harness: Harness, timeout: bool
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    client.failure = "accepted-timeout" if timeout else None
    first, second = executor(h, client), executor(h, client)
    results = await asyncio.gather(first.enter(alert.proposal_id), second.enter(alert.proposal_id))
    assert len(client.posts) == 1
    assert results[0].broker_order.order_id == results[1].broker_order.order_id
    assert results[0].recovered_after_ambiguity is timeout
    assert h.state.ledger.current_alert_status(alert.id) == "AUTO_APPROVED"
    assert not h.state.ledger.alert_is_actionable(alert.id)
    with Session(h.state.engine) as session:
        rows = tuple(session.scalars(select(ExecutionOrderRecord)))
        assert len(rows) == 3 and rows[0].qty == h.request.candidate.qty
        assert {row.role for row in rows} == {"ENTRY", "TARGET", "STOP"}
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_16_ambiguous_missing_order_halts_without_retry(harness: Harness) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    client.failure = "ambiguous-missing"
    with pytest.raises(ProviderError):
        await executor(harness, client).enter(alert.proposal_id)
    assert len(client.posts) == 1 and len(client.lookups) == 2
    assert harness.state.current() == SystemState.HALTED
    harness.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_reconciliation_does_not_invent_an_ambiguous_entry_outcome(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    client.failure = "ambiguous-missing"
    built = executor(harness, client)
    with pytest.raises(ProviderError) as submitted:
        await built.enter(alert.proposal_id)
    assert type(submitted.value) is ProviderError
    assert str(submitted.value) == "Automatic entry failed closed; inspect persisted intent"
    with pytest.raises(ReconciliationError) as unresolved:
        await built._reconcile()
    assert type(unresolved.value) is ReconciliationError
    assert str(unresolved.value) == "Durable order outcome remains unverifiable; no retry"
    with pytest.raises(ReconciliationError) as public_error:
        await built.reconcile()
    assert type(public_error.value) is ReconciliationError
    assert str(public_error.value) == "Broker reconciliation failed closed"
    assert harness.state.current() == SystemState.HALTED
    assert len(client.posts) == 1 and client.orders == {}
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_31_confirmed_rejection_records_rejected_without_immediate_halt(
    harness: Harness,
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    client.failure = "reject"
    with pytest.raises(OrderRejectedError):
        await executor(harness, client).enter(alert.proposal_id)
    assert len(client.posts) == 1 and harness.state.current() == SystemState.RUNNING
    with Session(harness.state.engine) as session:
        latest = session.scalar(select(OrderEvent).order_by(OrderEvent.seq.desc()))
        assert latest is not None and latest.state == "REJECTED"
    harness.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_11_downgraded_constructor_refuses_before_client_calls(harness: Harness) -> None:
    h = harness
    ModeStore(h.settings, h.state, "offline-paper").downgrade("MANUAL", actor="owner")
    client = FakeTradingClient(h)
    with pytest.raises(ExecutionDisabledError, match="effective"):
        executor(h, client)
    assert not client.posts and not client.lookups


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [{**AUTO, "auto_min_score": Decimal("10")}], indirect=True)
async def test_AX_21_lower_score_requires_private_hybrid_click(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    engine = executor(h, client)
    with pytest.raises(ExecutionDisabledError, match="hybrid"):
        await engine.enter(alert.proposal_id)
    with pytest.raises(ExecutionDisabledError, match="authenticated"):
        await engine.enter(alert.proposal_id, click=click(h, "A", user_id=999))
    result = await engine.enter(alert.proposal_id, click=click(h, "A"))
    assert result.proposal_id == alert.proposal_id and len(client.posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_43_stale_backup_refuses_before_client_calls(harness: Harness) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    harness.clock.current += timedelta(hours=26)
    with pytest.raises(ExecutionDisabledError, match="prerequisites"):
        await built.enter(uuid4())
    assert not client.posts and not client.lookups


async def fill_entry(
    h: Harness, client: FakeTradingClient, built: AlpacaExecutor, *, partial: bool = False
) -> tuple[dict[str, Any], ObservedFill]:
    raw = next(row for row in client.orders.values() if row["side"] == "buy")
    qty = 1 if partial else int(raw["qty"])
    raw["filled_qty"], raw["status"] = str(qty), "partially_filled" if partial else "filled"
    for leg in raw["legs"]:
        leg["status"] = "held" if partial else "new"
    client.positions = [
        {"symbol": raw["symbol"], "qty": str(qty), "side": "long", "asset_class": "us_equity"}
    ]
    await built.prepare_fills((raw["symbol"],))
    observed = ObservedFill(
        account_id="offline-paper",
        broker_fill_id="fixture-" + uuid4().hex,
        broker_order_id=UUID(raw["id"]),
        symbol=raw["symbol"],
        side=Side.BUY,
        qty=qty,
        price=Decimal(raw["limit_price"]) - Decimal("0.01"),
        filled_at=h.clock.now(),
    )
    built.observe_fill(observed)
    return raw, observed


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["child_of_child", "lost_nested_parent", "reused_child"])
async def test_AX_31_generated_child_identity_never_changes_its_managed_entry(
    harness: Harness, fault: str
) -> None:
    from backend.tests.test_v_execution import variant

    if fault == "reused_child":
        variant(harness, "SPLIT_1R")
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    instructions = built._instructions()
    entries = [row for row in instructions if row.role == "ENTRY"]
    child = next(row for row in instructions if row.parent_execution_id == entries[0].id)
    root = client.orders[entries[0].client_order_id]
    child_raw = next(row for row in root["legs"] if row["client_order_id"] == child.client_order_id)
    if fault == "child_of_child":
        built._register_children(child, parse_order(child_raw, parent_id=UUID(root["id"])))
    else:
        with pytest.raises(ReconciliationError) as caught:
            if fault == "lost_nested_parent":
                built._observe(entries[0], parse_order({**root, "legs": None}))
                await built._read_bound(child)
            else:
                other_root = client.orders[entries[1].client_order_id]
                built._register_children(
                    entries[1], parse_order({**other_root, "legs": [child_raw]})
                )
        assert type(caught.value) is ReconciliationError
        assert str(caught.value) == (
            "Generated broker child has no proved parent"
            if fault == "lost_nested_parent"
            else "Generated child already belongs to another entry"
        )
    assert [row.id for row in built._instructions()] == [row.id for row in instructions]
    assert len(client.posts) == len(entries)
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_16_lost_prior_order_is_not_resubmitted(harness: Harness) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    client.orders.clear()
    with pytest.raises(ExecutionDisabledError) as caught:
        await built.enter(alert.proposal_id)
    assert type(caught.value) is ExecutionDisabledError
    assert str(caught.value) == "Prior durable intent is retained; never resubmit"
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("seconds", [True, 0, 31, 1.5])
async def test_AX_24_invalid_cancel_budget_never_sends_a_cancel(
    harness: Harness, seconds: Any
) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    parent = client.orders[entry.client_order_id]
    with pytest.raises(ProviderError) as caught:
        await built._cancel_confirmed(entry, parse_order(parent), deadline_seconds=seconds)
    assert type(caught.value) is ProviderError
    assert str(caught.value) == "Cancel confirmation requires a bounded deadline"
    assert parent["status"] == "new"
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_24_cancel_cannot_claim_an_uncaptured_fill_is_reconciled(harness: Harness) -> None:
    alert = await deliver(harness)
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    await built.enter(alert.proposal_id)
    entry = next(row for row in built._instructions() if row.role == "ENTRY")
    parent = client.orders[entry.client_order_id]
    parent["filled_qty"] = "1"
    client.positions = [{"symbol": "NVDA", "qty": "1", "side": "long", "asset_class": "us_equity"}]
    with pytest.raises(ReconciliationError) as caught:
        await built._cancel_confirmed(entry, parse_order(parent))
    assert type(caught.value) is ReconciliationError
    assert str(caught.value) == "Cancellation raced a fill; capture activities before recovery"
    assert parent["status"] == "canceled"
    assert len(client.posts) == 1
    harness.state.ledger.verify_chain()
    await built.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_26_27_known_fill_is_idempotent_and_active_bracket_stop_is_retained(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    client, built = FakeTradingClient(h), None
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    _, observed = await fill_entry(h, client, built)
    first, second = built.observe_fill(observed), built.observe_fill(observed)
    assert first.id == second.id
    await built.reconcile()
    await built.monitor()
    assert len(client.posts) == 1
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("state", ["RUNNING", "HALTED", "REDUCE_ONLY", "PAUSE", "MANUAL"])
async def test_AX_24_27_30_partial_parent_canceled_then_stop_repairs_even_when_entries_blocked(
    harness: Harness, state: str
) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, _ = await fill_entry(h, client, built, partial=True)
    journal_existing_partial_repair(built)
    if state in {"HALTED", "REDUCE_ONLY"}:
        h.state.escalate(SystemState(state), "fixture state")
    elif state in {"PAUSE", "MANUAL"}:
        built.modes.downgrade("PAUSE" if state == "PAUSE" else "MANUAL", actor="fixture owner")
    await built.monitor()
    assert parent["status"] == "canceled"
    assert len(client.posts) == 2
    assert client.posts[1]["type"] == "stop" and client.posts[1]["qty"] == "1"
    assert client.posts[1]["time_in_force"] == "gtc"
    await built.monitor()
    assert len(client.posts) == 2, "An already confirmed stop must never be duplicated"
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_AX_27_failed_stop_repair_latches_halt(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built, partial=True)
    journal_existing_partial_repair(built)
    client.failure = "reject"
    with pytest.raises(ReconciliationError):
        await built.monitor()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == 2 and client.posts[1]["type"] == "stop"
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("fault", ["position", "order", "qty", "fill-side", "fill-limit"])
async def test_AX_31_reconciliation_faults_and_bad_fills_halt(harness: Harness, fault: str) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    raw, fill = await fill_entry(h, client, built)
    if fault == "fill-side":
        with pytest.raises(ReconciliationError):
            built.observe_fill(
                fill.model_copy(update={"broker_fill_id": "bad-side", "side": Side.SELL})
            )
    elif fault == "fill-limit":
        with pytest.raises(ReconciliationError):
            built.observe_fill(
                fill.model_copy(
                    update={
                        "broker_fill_id": "bad-limit",
                        "price": Decimal(raw["limit_price"]) + Decimal("0.01"),
                    }
                )
            )
    else:
        if fault == "position":
            client.positions.append(
                {"symbol": "AAPL", "qty": "1", "side": "long", "asset_class": "us_equity"}
            )
        elif fault == "qty":
            client.positions[0]["qty"] = str(int(client.positions[0]["qty"]) + 1)
        else:
            unknown = {
                **raw,
                "id": str(uuid4()),
                "client_order_id": "foreign-manual",
                "legs": None,
                "status": "new",
                "filled_qty": "0",
            }
            client.orders["foreign-manual"] = unknown
        with pytest.raises(ReconciliationError):
            await built.reconcile()
    assert h.state.current() == SystemState.HALTED
    assert len(client.posts) == 1
    h.state.ledger.verify_chain()
