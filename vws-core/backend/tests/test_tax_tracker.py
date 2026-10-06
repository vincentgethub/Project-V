"""TX-08 owner rates and external sale-awareness hand goldens."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.domain.compliance_models import TaxLot, TradeRecord
from backend.domain.models import Side
from backend.domain.tax_profile import TaxProfile
from backend.tax.tax_tracker import TaxTracker
from backend.tests.test_risk_cro import _registry

NOW = datetime(2026, 10, 6, 15, tzinfo=UTC)


def sale(**changes: Any) -> TradeRecord:
    return TradeRecord.model_validate(
        {
            "trade_id": UUID(int=1),
            "account_id": "alpaca-paper",
            "symbol": "AAPL",
            "side": Side.SELL,
            "qty": 5,
            "price": Decimal("90"),
            "ts": NOW,
            "realized_loss": Decimal("50"),
            "holding_period_start": NOW - timedelta(days=400),
            **changes,
        }
    )


def lot(number: int, account: str, days: int, **changes: Any) -> TaxLot:
    return TaxLot.model_validate(
        {
            "lot_id": UUID(int=number),
            "account_id": account,
            "symbol": "AAPL",
            "qty": 5,
            "acquired_at": NOW + timedelta(days=days),
            "cost_basis": Decimal("100"),
            **changes,
        }
    )


def tracker(**rates: Any) -> TaxTracker:
    return TaxTracker(Settings(broker_account_type="CASH", **rates), _registry())


def test_TX_08_owner_profile_totals_only_until_federal_rates_supplied() -> None:
    item = tracker()
    assert item.profile.filing_status == "single" and item.profile.state == "Texas"
    assert item.profile.state_rate == item.profile.niit_rate == 0
    result = item.set_aside(Decimal("1000"), Decimal("2000"))
    assert result.net_st == 1000 and result.net_lt == 2000 and result.estimate is None
    assert "not tax advice" in result.notice and "1099-B" in result.notice


@pytest.mark.parametrize(
    "st,lt,expected",
    [
        ("1000", "2000", "540"),
        ("-1000", "2000", "300"),
        ("1000", "-2000", "240"),
        ("-1", "-2", "0"),
        ("0.01", "0", "0.0024"),
    ],
)
def test_TX_08_exact_owner_override_formula(st: str, lt: str, expected: str) -> None:
    # Explicit fictional test rates; no bracket or rate is inferred.
    item = tracker(tax_fed_st_rate=Decimal("0.24"), tax_fed_lt_rate=Decimal("0.15"))
    assert item.set_aside(Decimal(st), Decimal(lt)).estimate == Decimal(expected)


def test_TX_08_state_and_niit_explicit_override() -> None:
    item = tracker(
        tax_fed_st_rate=Decimal("0.24"),
        tax_fed_lt_rate=Decimal("0.15"),
        tax_state="Owner specified state",
        tax_state_rate=Decimal("0.05"),
        tax_niit_rate=Decimal("0.038"),
    )
    assert item.set_aside(Decimal("1000"), Decimal("2000")).estimate == Decimal("804")


@pytest.mark.parametrize("invalid", [Decimal("NaN"), True, 0.1])
def test_TX_08_invalid_totals_fail_typed(invalid: Any) -> None:
    with pytest.raises(DataIntegrityError):
        tracker().set_aside(invalid, Decimal(0))


def test_TX_08_profile_revalidated_before_estimate() -> None:
    item = tracker()
    item.profile = TaxProfile.model_construct(federal_st_rate=Decimal("NaN"))
    with pytest.raises(DataIntegrityError):
        item.set_aside(Decimal(1), Decimal(2))


def test_TX_sale_prompts_all_three_external_account_types_without_login() -> None:
    item = tracker()
    marked = (
        lot(2, "owner-ira", -30),
        lot(3, "merrill-taxable", 30),
        lot(4, "owner-401k", 0),
        lot(5, "unrelated", -31),
        lot(6, "alpaca-paper", 0),
        lot(7, "other-symbol", 0, symbol="MSFT"),
        lot(8, "too-late", 31),
    )
    review = item.review_sale(sale(), marked)
    assert review.external_lot_ids == (UUID(int=2), UUID(int=3), UUID(int=4))
    assert "IRA or Roth IRA" in review.prompts[0] and "Merrill" in review.prompts[1]
    assert "401(k)" in review.prompts[2] and "not inferred" in review.prompts[3]
    assert "30 days after" in review.prompts[-1] and "1099-B" in review.notice
    clean = item.review_sale(sale(realized_loss=Decimal(0)), marked)
    assert not clean.external_lot_ids and len(clean.prompts) == 4


@pytest.mark.parametrize("invalid", ["buy", "mutable", "duplicate", "tampered", "unknown"])
def test_TX_external_awareness_invalid_evidence_fails_closed(invalid: str) -> None:
    current: Any = sale()
    marked: Any = (lot(2, "ira", 0),)
    if invalid == "buy":
        current = sale(side=Side.BUY, realized_loss=Decimal(0))
    elif invalid == "mutable":
        marked = list(marked)
    elif invalid == "duplicate":
        marked = (*marked, *marked)
    elif invalid == "tampered":
        marked = (marked[0].model_copy(update={"qty": 0}),)
    else:
        marked = (lot(2, "ira", 0, symbol="UNKNOWN"),)
    with pytest.raises(DataIntegrityError):
        tracker().review_sale(current, marked)
