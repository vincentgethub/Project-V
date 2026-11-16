"""Spec MS:3: no options trading, ever. Pins the existing structural guards.

There is no options code path to disable; these tests keep it that way:
OCC option symbols cannot pass symbol validation, the asset-class enum and
instrument allowlist have no option class, broker reads refuse non-us_equity
positions and orders, and the options-exercise call is in the banned list.
"""

import ast
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError, ProviderError, ReconciliationError
from backend.core.execution_policy import BANNED_EXECUTION_METHODS
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, Instrument, validate_symbol
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor
from backend.tests.test_broker_state import NOW, FakeClient, provider
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness

harness = make_research_harness
PROJECT = Path(__file__).resolve().parents[2]

# OCC/OSI option symbols: root + YYMMDD + C/P + 8-digit strike, plus vendor prefixes.
OPTION_SYMBOLS = (
    "SPY261218C00600000",
    "AAPL261218P00185000",
    "F261218C00012000",
    "O:SPY261218C00600000",
    "SPY 261218C00600000",
    "SPY_121826C600",
)
EXERCISE = "exercise_options_position"


@pytest.mark.parametrize("symbol", OPTION_SYMBOLS)
def test_OPTIONS_occ_symbols_never_pass_symbol_validation(symbol: str) -> None:
    with pytest.raises(ValueError):
        validate_symbol(symbol)


def test_OPTIONS_shortest_occ_symbol_exceeds_the_symbol_length_limit() -> None:
    # One-letter root + 6 date digits + C/P + 8 strike digits = 16 > 15 allowed.
    assert len("F261218C00012000") == 16
    validate_symbol("ABCDEFGHIJKLMNO")
    with pytest.raises(ValueError):
        validate_symbol("ABCDEFGHIJKLMNOP")


def test_OPTIONS_asset_classes_contain_no_option_class() -> None:
    assert {member.value for member in AssetClass} == {
        "STOCK",
        "BROAD_ETF",
        "SECTOR_ETF",
        "COMMODITY_ETF",
        "CASH_EQUIV",
    }


@pytest.mark.parametrize("asset_class", ["OPTION", "OPTIONS", "us_option", "us_equity"])
def test_OPTIONS_instrument_allowlist_rejects_non_equity_classes(asset_class: str) -> None:
    with pytest.raises(ValidationError):
        Instrument.model_validate(
            {
                "symbol": "SPY",
                "asset_class": asset_class,
                "gics_sector": "Broad",
                "is_leveraged": False,
                "is_inverse": False,
                "tradable": True,
            }
        )


def test_OPTIONS_shipped_instrument_file_lists_only_equities_and_etfs() -> None:
    registry = InstrumentRegistry.from_csv(PROJECT / "config")
    assert registry.symbols
    assert {registry.get(symbol).asset_class for symbol in registry.symbols} <= {
        AssetClass.STOCK,
        AssetClass.BROAD_ETF,
        AssetClass.SECTOR_ETF,
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"asset_class": "us_option"},
        {"asset_class": "us_option", "symbol": "AAPL261218P00185000"},
    ],
)
def test_OPTIONS_broker_snapshot_refuses_option_positions(fields: dict[str, Any]) -> None:
    client = FakeClient()
    client.positions[0].update(fields)
    with pytest.raises((DataIntegrityError, ProviderError)):
        provider(client).snapshot(NOW)


def test_OPTIONS_broker_snapshot_refuses_option_orders() -> None:
    client = FakeClient()
    assert client.orders
    client.orders[0]["asset_class"] = "us_option"
    with pytest.raises((DataIntegrityError, ProviderError)):
        provider(client).snapshot(NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
@pytest.mark.parametrize(
    "row",
    [
        {"symbol": "SPY", "qty": "1", "side": "long", "asset_class": "us_option"},
        {"symbol": "SPY261218C00600000", "qty": "1", "side": "long", "asset_class": "us_equity"},
    ],
)
async def test_OPTIONS_executor_reconciliation_refuses_option_positions(
    harness: Harness, row: dict[str, str]
) -> None:
    client = FakeTradingClient(harness)
    built = executor(harness, client)
    client.positions = [row]
    with pytest.raises(ReconciliationError):
        await built._positions()
    await built.close()


def test_OPTIONS_exercise_call_is_banned_and_never_named_in_authored_source() -> None:
    assert EXERCISE in BANNED_EXECUTION_METHODS
    guard = PROJECT / "backend/core/execution_policy.py"
    offenders = []
    for root in ("backend", "vws", "scripts"):
        for path in sorted((PROJECT / root).rglob("*.py")):
            if "tests" in path.parts or path == guard:
                continue
            if EXERCISE in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(PROJECT).as_posix())
    assert offenders == []


def test_OPTIONS_no_authored_source_imports_alpaca_option_interfaces() -> None:
    offenders = []
    for root in ("backend", "vws", "scripts"):
        for path in sorted((PROJECT / root).rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("alpaca"):
                    names = [alias.name for alias in node.names]
                    if "option" in (node.module or "").lower() or any(
                        "option" in name.lower() for name in names
                    ):
                        offenders.append(f"{path.relative_to(PROJECT).as_posix()}:{node.lineno}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("alpaca") and "option" in alias.name.lower():
                            offenders.append(
                                f"{path.relative_to(PROJECT).as_posix()}:{node.lineno}"
                            )
    assert offenders == []
