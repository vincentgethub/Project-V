"""GV: independent query/fee boundary checks over a real resolved paper ledger."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.core.config import YamlConfig
from backend.core.database import ExecutionFillRecord, ExecutionOrderRecord, Order, Signal
from backend.core.errors import DataIntegrityError
from backend.data.fee_schedule import load_fee_schedule
from backend.domain.models import Side
from backend.evaluation import physical
from backend.evaluation.physical import resolved_trades
from backend.tax.models import TaxFill
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from backend.tests.test_v_verdict_source import SCOPE, close_split_trade

harness = make_research_harness
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "order_bound",
        "fill_bound",
        "future_fill",
        "wrong_account",
        "missing_order",
        "missing_signal",
        "missing_approval",
        "oversell",
        "sale_before_buy",
        "missing_stop",
        "unfinished_root",
        "different_policy",
        "no_entry",
    ],
)
async def test_GV_physical_projections_cannot_invent_resolved_or_current_trades(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    h = harness
    await close_split_trade(h)
    original_scalars, original_get = Session.scalars, Session.get
    with Session(h.state.engine) as session:
        instructions = tuple(session.query(ExecutionOrderRecord))
        order_id = instructions[0].order_id
        sides = {row.id: row.side for row in instructions}

    def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        rows = original_scalars(session, statement, *args, **kwargs)
        entity = statement.column_descriptions[0]["entity"]
        if entity not in {ExecutionOrderRecord, ExecutionFillRecord}:
            return rows
        projected = [SimpleNamespace(**vars(row)) for row in rows]
        if fault == "order_bound" and entity is ExecutionOrderRecord:
            return [projected[0]] * 100001
        if fault == "fill_bound" and entity is ExecutionFillRecord:
            return [projected[0]] * 100001
        if entity is ExecutionFillRecord:
            if fault == "future_fill":
                projected[-1].filled_at = h.clock.now() + timedelta(seconds=1)
            elif fault == "oversell":
                projected[-1].qty += 1
            elif fault == "sale_before_buy":
                first_sale = next(
                    row for row in projected if sides[row.execution_order_id] == "SELL"
                )
                first_sale.filled_at = min(row.filled_at for row in projected) - timedelta(
                    seconds=1
                )
        elif fault in {"missing_stop", "no_entry"}:
            for row in projected:
                if row.role == "ENTRY":
                    if fault == "missing_stop":
                        row.stop_price = None
                    else:
                        row.role = "TARGET"
        return projected

    def get(session: Session, model: Any, identity: Any, *args: Any, **kwargs: Any) -> Any:
        row = original_get(session, model, identity, *args, **kwargs)
        if model is Order and identity == order_id:
            if fault == "missing_order":
                return None
            if fault == "wrong_account":
                row = SimpleNamespace(**vars(row))
                row.account_id = "another-paper"
        if model is Signal and fault == "missing_signal":
            return None
        return row

    # Only the detached collector projections are faulted. The canonical ledger
    # verifier is tested independently and owner storage is never touched.
    monkeypatch.setattr(h.state.ledger, "verify_chain", lambda: {})
    monkeypatch.setattr(Session, "scalars", scalars)
    monkeypatch.setattr(Session, "get", get)
    if fault == "missing_approval":
        monkeypatch.setattr(physical, "approval_evidence", lambda *args: None)
    elif fault == "unfinished_root":
        monkeypatch.setattr(physical, "bindings", lambda *args: {})
    config = YamlConfig.model_validate({**h.config.model_dump(), "exits": {"variant": "BASELINE"}})
    schedule = load_fee_schedule(ROOT / "config/fees.yaml")
    if fault in {"unfinished_root", "different_policy", "no_entry"}:
        assert (
            resolved_trades(
                h.state.ledger,
                SCOPE,
                schedule,
                config=config if fault == "different_policy" else None,
            )
            == ()
        )
    else:
        with pytest.raises(DataIntegrityError, match="GV:"):
            resolved_trades(h.state.ledger, SCOPE, schedule)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize("kind", ["BROKER", "MODELED", "mismatch"])
async def test_GV_actual_attributed_fees_win_and_identity_must_match(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    h = harness
    await close_split_trade(h)
    with Session(h.state.engine) as session:
        instructions = {row.id: row for row in session.query(ExecutionOrderRecord)}
        fills = tuple(session.query(ExecutionFillRecord))
    tax = tuple(
        TaxFill(
            fill_id=row.id,
            activity_id=row.broker_fill_id,
            account_id=SCOPE.account_id,
            env="PAPER",
            symbol=instructions[row.execution_order_id].symbol,
            side=Side(instructions[row.execution_order_id].side),
            qty=row.qty,
            price=row.price + Decimal("0.01") if kind == "mismatch" else row.price,
            fees=Decimal("0.50"),
            ts=row.filled_at,
            fee_source="MODELED" if kind == "MODELED" else "BROKER",
            payload_sha256="a" * 64,
        )
        for row in fills
    )
    monkeypatch.setattr(physical, "read_fills", lambda *args, **kwargs: tax)
    if kind == "mismatch":
        with pytest.raises(DataIntegrityError, match="identity differs"):
            resolved_trades(h.state.ledger, SCOPE, load_fee_schedule(ROOT / "config/fees.yaml"))
        return
    result = resolved_trades(h.state.ledger, SCOPE, load_fee_schedule(ROOT / "config/fees.yaml"))
    assert len(result) == 1 and result[0].modeled_fees == (kind == "MODELED")
    assert result[0].net_money == -result[0].initial_risk - Decimal("2.00")
