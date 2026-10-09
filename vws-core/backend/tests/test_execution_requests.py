"""AX-12/15/16/23: real pinned request serialization and denied transport routes."""

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from pydantic import ValidationError

from backend.execution.alpaca_executor import ExactLimit, ExactStop, ExactStopLoss, ExactTakeProfit


def test_AX_11_MANUAL_composition_import_graph_in_fresh_offline_process() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys\nimport vws.runtime_cli\n"
                "assert 'backend.execution.alpaca_executor' not in sys.modules\n"
                "import pytest\nraise SystemExit(pytest.main(['-q', "
                "'backend/tests/test_security_cli.py::test_OPS_02_composition_builds_six_real_jobs_without_orders_or_network']))\n"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def bracket(**updates: Any) -> ExactLimit:
    values: dict[str, Any] = {
        "symbol": "NVDA",
        "qty": 19,
        "side": OrderSide.BUY,
        "time_in_force": TimeInForce.GTC,
        "order_class": OrderClass.BRACKET,
        "client_order_id": "vws-" + uuid4().hex,
        "limit_price": Decimal("128.47"),
        "take_profit": ExactTakeProfit(limit_price=Decimal("137.00")),
        "stop_loss": ExactStopLoss(stop_price=Decimal("124.20")),
    }
    return ExactLimit(**(values | updates))


def test_AX_23_pinned_SDK_bracket_keeps_Decimal_and_serializes_exact_text() -> None:
    request = bracket()
    assert type(request.qty) is int and isinstance(request.limit_price, Decimal)
    assert request.take_profit is not None and isinstance(request.take_profit.limit_price, Decimal)
    assert request.stop_loss is not None and isinstance(request.stop_loss.stop_price, Decimal)
    fields = json.loads(json.dumps(request.to_request_fields()))
    assert fields == {
        "symbol": "NVDA",
        "qty": "19",
        "side": "buy",
        "type": "limit",
        "time_in_force": "gtc",
        "order_class": "bracket",
        "client_order_id": request.client_order_id,
        "limit_price": "128.47",
        "take_profit": {"limit_price": "137.00"},
        "stop_loss": {"stop_price": "124.20"},
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"qty": True},
        {"qty": 1.5},
        {"qty": 0},
        {"limit_price": 128.47},
        {"limit_price": Decimal("128.471")},
        {"side": OrderSide.SELL},
        {"time_in_force": TimeInForce.DAY},
        {"extended_hours": False},
        {"notional": 50},
        {"take_profit": None},
        {"stop_loss": None},
        {"unexpected": "ignored?"},
    ],
)
def test_AX_23_invalid_brackets_fail_before_serialization(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        bracket(**updates)


def test_AX_23_forged_frozen_request_is_revalidated() -> None:
    forged = bracket().model_copy(update={"limit_price": 1.0})
    with pytest.raises(ValidationError):
        forged.to_request_fields()


def test_AX_27_stop_repair_and_AX_29_exit_are_exact_and_separate() -> None:
    stop = ExactStop(
        symbol="NVDA",
        qty=19,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.GTC,
        stop_price=Decimal("124.20"),
        client_order_id="vws-s-" + uuid4().hex,
    )
    assert stop.to_request_fields()["stop_price"] == "124.20"
    assert stop.to_request_fields()["qty"] == "19"
    exit_order = ExactLimit(
        symbol="NVDA",
        qty=19,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
        limit_price=Decimal("127.18"),
        client_order_id="vws-x-" + uuid4().hex + "-1",
    )
    assert exit_order.to_request_fields()["order_class"] == "simple"
    assert "stop_loss" not in exit_order.to_request_fields()
    with pytest.raises(ValidationError):
        ExactStop(
            symbol="NVDA",
            qty=19,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            stop_price=Decimal("124.20"),
            client_order_id="vws-s-" + uuid4().hex,
        )
