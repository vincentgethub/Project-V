"""XA-01: genuine physical receipts survive quality faults; no invented quotes."""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import ExecutionFillRecord, ExecutionOrderRecord, Order, Signal
from backend.core.errors import DataIntegrityError
from backend.evaluation import tca_store
from backend.evaluation.tca_store import ArrivalEvidence, capture_pending, inventory, record_arrival
from backend.ops.trading_controls import ControlScope
from backend.tests.query_faults import selects_kind
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness
SCOPE = ControlScope(account_id="offline-paper", environment="PAPER")


async def uncaptured(h: Harness, monkeypatch: pytest.MonkeyPatch) -> ExecutionFillRecord:
    capture = tca_store.capture
    monkeypatch.setattr(tca_store, "capture", lambda *args: None)
    alert = await deliver(h)
    client = FakeTradingClient(h)
    ex = executor(h, client)
    await ex.enter(alert.proposal_id)
    await fill_entry(h, client, ex)
    monkeypatch.setattr(tca_store, "capture", capture)
    with Session(h.state.engine) as session:
        fill = session.scalar(select(ExecutionFillRecord))
        assert fill is not None
    h.state.ledger.verify_chain()
    assert inventory(h.state.ledger, SCOPE) == ()
    return fill


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XA_stop_receipt_does_not_use_a_stale_trigger_quote(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decimal import Decimal
    from uuid import UUID

    from backend.data.fill_polling import ObservedFill
    from backend.domain.models import Side

    h = harness
    capture = tca_store.capture
    monkeypatch.setattr(tca_store, "capture", lambda *a: None)
    alert = await deliver(h)
    client = FakeTradingClient(h)
    ex = executor(h, client)
    await ex.enter(alert.proposal_id)
    raw, bought = await fill_entry(h, client, ex)
    stop = next(leg for leg in raw["legs"] if leg["type"] == "stop")
    stop["status"], stop["filled_qty"] = "filled", stop["qty"]
    for child in raw["legs"]:
        if child["type"] == "limit":
            child["status"] = "canceled"
    with Session(h.state.engine) as session:
        instruction = session.scalar(
            select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.client_order_id == stop["client_order_id"]
            )
        )
        assert instruction is not None
    record_arrival(h.state.ledger, instruction, h.source.inputs.market, 30)
    market = h.source.inputs.market
    assert market is not None
    record_arrival(
        h.state.ledger,
        instruction,
        market.model_copy(update={"last_price": market.last_price + 1}),
        30,
    )
    h.clock.current += timedelta(seconds=31)
    await ex._read_bound(instruction)
    ex.observe_fill(
        ObservedFill(
            account_id=bought.account_id,
            broker_fill_id="stale-trigger-stop",
            broker_order_id=UUID(stop["id"]),
            symbol=bought.symbol,
            side=Side.SELL,
            qty=bought.qty,
            price=Decimal(stop["stop_price"]),
            filled_at=h.clock.now(),
        )
    )
    monkeypatch.setattr(tca_store, "capture", capture)
    with Session(h.state.engine) as session:
        receipt = session.scalar(
            select(ExecutionFillRecord).where(
                ExecutionFillRecord.execution_order_id == instruction.id
            )
        )
        assert receipt is not None
    row = capture(h.state.ledger, receipt)
    assert row.is_stop and row.arrival_price is None and row.unavailable_reason is not None
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "instruction",
        "order",
        "signal",
        "arrival_bound",
        "arrival_scope",
        "arrival_time",
        "arrival_after_fill",
    ],
)
async def test_XA_capture_refuses_unbound_or_unbounded_evidence_and_labels_missing_model(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    h = harness
    fill = await uncaptured(h, monkeypatch)
    original_get, original_scalars = Session.get, Session.scalars
    # Canonical chain verification above is independent of these detached read
    # faults. No stored instruction, receipt or ledger row is changed.
    monkeypatch.setattr(h.state.ledger, "_verify_in_session", lambda *args: {})

    def get(session: Session, model: Any, identity: Any, *args: Any, **kwargs: Any) -> Any:
        if (
            (fault == "instruction" and model is ExecutionOrderRecord)
            or (fault == "order" and model is Order)
            or (fault == "signal" and model is Signal)
        ):
            return None
        return original_get(session, model, identity, *args, **kwargs)

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        found = original_scalars(session, statement, *args, **kwargs)
        if not selects_kind(statement, "ORDER_ARRIVAL"):
            return found
        rows = [SimpleNamespace(**vars(row)) for row in found]
        if fault == "arrival_bound":
            return rows * 101
        if fault in {"arrival_scope", "arrival_time", "arrival_after_fill"}:
            row = rows[0]
            proof = ArrivalEvidence.recorded(row.detail)
            changed = (
                {"scope": ControlScope(account_id="other", environment="PAPER")}
                if fault == "arrival_scope"
                else {"observed_at": h.clock.now() + timedelta(seconds=1)}
            )
            row.detail = ArrivalEvidence.model_validate(
                proof.model_copy(update=changed)
            ).model_dump(mode="json")
            if fault == "arrival_after_fill":
                row.created_at = h.clock.now() + timedelta(seconds=1)
        return rows

    monkeypatch.setattr(Session, "get", get)
    monkeypatch.setattr(Session, "scalars", scalars)
    if fault in {"order", "signal", "arrival_after_fill"}:
        row = tca_store.capture(h.state.ledger, fill)
        assert row.unavailable_reason is not None and row.modeled_price is None
    else:
        with pytest.raises(DataIntegrityError, match="XA-01:"):
            tca_store.capture(h.state.ledger, fill)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("case", ["fill", "instruction", "price", "bound"])
async def test_XA_quality_inventory_requires_its_original_physical_identity(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    h = harness
    fill = await uncaptured(h, monkeypatch)
    tca_store.capture(h.state.ledger, fill)
    h.state.ledger.verify_chain()
    monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
    original_get, original_scalars = Session.get, Session.scalars

    def get(session: Session, model: Any, identity: Any, *args: Any, **kwargs: Any) -> Any:
        row = original_get(session, model, identity, *args, **kwargs)
        if (
            case == "fill"
            and model is ExecutionFillRecord
            or case == "instruction"
            and model is ExecutionOrderRecord
        ):
            return None
        if case == "price" and model is ExecutionFillRecord:
            row = SimpleNamespace(**vars(row))
            row.price += 1
        return row

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        rows = original_scalars(session, statement, *args, **kwargs)
        return (
            list(rows) * 100001
            if case == "bound" and selects_kind(statement, "FILL_QUALITY")
            else rows
        )

    monkeypatch.setattr(Session, "get", get)
    monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises(DataIntegrityError, match="XA-01:"):
        inventory(h.state.ledger, SCOPE)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("case", ["normal", "fill_bound", "quality_bound", "future"])
async def test_XA_legacy_receipt_backfill_is_bounded_and_idempotent(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    h = harness
    fill = await uncaptured(h, monkeypatch)
    if case == "quality_bound":
        tca_store.capture(h.state.ledger, fill)
    if case != "normal":
        h.state.ledger.verify_chain()
        monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
        original = Session.scalars

        def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
            found = original(session, statement, *args, **kwargs)
            entity = statement.column_descriptions[0]["entity"]
            if case == "quality_bound" and selects_kind(statement, "FILL_QUALITY"):
                return list(found) * 100001
            if entity is ExecutionFillRecord:
                rows = [SimpleNamespace(**vars(row)) for row in found]
                if case == "fill_bound":
                    return rows * 100001
                rows[0].filled_at = h.clock.now() + timedelta(seconds=1)
                return rows
            return found

        monkeypatch.setattr(Session, "scalars", scalars)
        with pytest.raises(DataIntegrityError, match="XA-01:"):
            capture_pending(h.state.ledger, SCOPE)
    else:
        capture_pending(h.state.ledger, SCOPE)
        capture_pending(h.state.ledger, SCOPE)
        assert len(inventory(h.state.ledger, SCOPE)) == 1
        with Session(h.state.engine) as session:
            instruction = session.get(ExecutionOrderRecord, fill.execution_order_id)
            assert instruction is not None
        record_arrival(h.state.ledger, instruction, None, 30)
        record_arrival(h.state.ledger, instruction, h.source.inputs.market, 30)
        record_arrival(h.state.ledger, instruction, h.source.inputs.market, 30)
        stale = h.source.inputs.market.model_copy(
            update={"last_price_ts": h.clock.now() - timedelta(seconds=31)}
        )
        record_arrival(h.state.ledger, instruction, stale, 30)
        with pytest.raises(DataIntegrityError, match="known liquidity"):
            tca_store.calibration(h.state.ledger, SCOPE, "2026-09", "invalid", 2)  # type: ignore[arg-type]
        h.state.ledger.verify_chain()


@pytest.mark.parametrize("seconds", [-1, 31])
def test_XA_arrival_proof_cannot_be_stale_or_future(harness: Harness, seconds: int) -> None:
    from decimal import Decimal
    from uuid import UUID

    with pytest.raises(ValidationError, match="stale or future"):
        ArrivalEvidence(
            execution_order_id=UUID(int=1),
            scope=SCOPE,
            quote=Decimal(100),
            quoted_at=harness.clock.now() - timedelta(seconds=seconds),
            observed_at=harness.clock.now(),
            stale_seconds=30,
        )
