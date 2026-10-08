"""TX-01..05: hand-computed executions, fees, partial washes and holding periods."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from backend.core.errors import DataIntegrityError
from backend.domain.compliance_models import TaxStatus
from backend.domain.models import Side
from backend.tax.accounting import anniversary, build_tax_book
from backend.tax.models import TaxAccount, TaxFill, TaxIncome
from backend.tests.test_wash_sales import registry

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)


def account(
    name: str = "tax", *, compressed: bool = False, status: TaxStatus = TaxStatus.TAXABLE
) -> TaxAccount:
    return TaxAccount(
        id=name,
        name=name,
        tax_status=status,
        source="ALPACA",
        lot_method="ALPACA_COMPRESSED_FIFO" if compressed else "FIFO",
    )


def fill(
    identifier: int,
    *,
    side: Side = Side.BUY,
    day: int = 0,
    minutes: int = 0,
    qty: int = 10,
    price: str = "10.00",
    fees: str = "0",
    owner: str = "tax",
) -> TaxFill:
    return TaxFill(
        fill_id=UUID(int=identifier),
        activity_id=f"fill-{identifier}",
        account_id=owner,
        env="PAPER",
        symbol="AAA",
        side=side,
        qty=qty,
        price=Decimal(price),
        fees=Decimal(fees),
        ts=NOW + timedelta(days=day, minutes=minutes),
        fee_source="CSV",
        payload_sha256="a" * 64,
    )


def test_empty_income_and_anniversary() -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    assert not book.sales and not book.lots and len(book.sha256) == 64
    assert anniversary(date(2024, 2, 29)) == date(2025, 2, 28)
    assert anniversary(date(2026, 2, 28)) == date(2027, 2, 28)
    assert anniversary(date(2026, 10, 2)) == date(2027, 10, 2)
    income = TaxIncome(
        activity_id="div",
        account_id="tax",
        env="PAPER",
        type="DIVNRA",
        date=date(2026, 10, 2),
        amount=Decimal("12.34"),
    )
    assert income.dividend_class == "unclassified"


def test_fifo_fees_and_partial_basis_conserve() -> None:
    book = build_tax_book(
        (
            fill(1, day=-100, qty=3, fees="0.01"),
            fill(2, side=Side.SELL, qty=2, price="12.00", fees="0.02"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    sale = book.sales[0]
    assert (sale.proceeds, sale.basis, sale.economic_gain) == (
        Decimal("23.98"),
        Decimal("20.006666"),
        Decimal("3.973334"),
    )
    assert book.lots[0].basis == Decimal("10.003334")
    assert sale.basis + book.lots[0].basis == Decimal("30.01")
    assert (
        sum((row.cost_basis * row.qty for row in book.compliance_lots()), Decimal(0))
        == book.lots[0].basis
    )


@pytest.mark.parametrize("compressed,expected", [(True, "150"), (False, "100")])
def test_same_day_weighted_average_or_fifo(compressed: bool, expected: str) -> None:
    book = build_tax_book(
        (
            fill(1),
            fill(2, minutes=1, price="20.00"),
            fill(3, side=Side.SELL, minutes=2, price="25.00"),
        ),
        (account(compressed=compressed),),
        registry(),
        "PAPER",
    )
    assert sum((row.basis for row in book.sales), Decimal(0)) == Decimal(expected)
    assert sum((row.basis for row in book.lots), Decimal(0)) == Decimal(300) - Decimal(expected)


def test_compressed_prior_day_fifo_and_intraday_roundtrip() -> None:
    book = build_tax_book(
        (
            fill(1, day=-1, qty=5),
            fill(2, price="20.00"),
            fill(3, minutes=1, price="30.00"),
            fill(4, side=Side.SELL, minutes=2, qty=15, price="40.00"),
            fill(5, minutes=3, qty=10, price="35.00"),
        ),
        (account(compressed=True),),
        registry(),
        "PAPER",
    )
    assert sum((row.basis for row in book.sales), Decimal(0)) == Decimal("300")
    assert sum((row.basis for row in book.lots), Decimal(0)) == Decimal("600")
    assert sum(row.qty for row in book.lots) == 20


@pytest.mark.parametrize("days,term", [(365, "ST"), (366, "LT")])
def test_anniversary_is_strict(days: int, term: str) -> None:
    book = build_tax_book(
        (fill(1, day=-days), fill(2, side=Side.SELL, price="11.00")),
        (account(),),
        registry(),
        "PAPER",
    )
    assert book.sales[0].term == term


@pytest.mark.parametrize("day,matched", [(30, 4), (31, 0)])
def test_proportional_rebuy_and_inclusive_window(day: int, matched: int) -> None:
    book = build_tax_book(
        (
            fill(1, day=-100),
            fill(2, side=Side.SELL, price="9.00"),
            fill(3, day=day, qty=4, price="8.00"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    assert sum((row.wash_disallowed for row in book.sales), Decimal(0)) == Decimal(matched)
    assert sum((row.basis for row in book.lots), Decimal(0)) == Decimal(32 + matched)
    if matched:
        assert book.lots[0].holding_period_start == (
            fill(3, day=day).ts.astimezone(ZoneInfo("America/New_York")) - timedelta(days=100)
        ).astimezone(UTC)


def test_wash_chain_carries_adjusted_basis_forward() -> None:
    book = build_tax_book(
        (
            fill(1, day=-100),
            fill(2, side=Side.SELL, price="9.00"),
            fill(3, day=1, price="8.00"),
            fill(4, side=Side.SELL, day=2, price="7.00"),
            fill(5, day=3, price="6.00"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    assert [row.economic_gain for row in book.sales] == [Decimal(-10), Decimal(-20)]
    assert [row.wash_disallowed for row in book.sales] == [Decimal(10), Decimal(20)]
    assert book.lots[0].basis == Decimal(80)
    assert book.lots[0].holding_period_start == fill(5, day=3).ts - timedelta(days=101)


@pytest.mark.parametrize("status", [TaxStatus.IRA, TaxStatus.ROTH])
def test_ira_rebuy_is_permanent_without_basis_addition(status: TaxStatus) -> None:
    book = build_tax_book(
        (
            fill(1, day=-100),
            fill(2, side=Side.SELL, price="9.00"),
            fill(3, day=1, owner="ira", price="8.00"),
        ),
        (account(), account("ira", status=status)),
        registry(),
        "PAPER",
    )
    assert book.sales[0].permanent_disallowed == Decimal(10)
    assert book.lots[0].basis == Decimal(80) and book.lots[0].wash_basis == 0
    assert book.lots[0].holding_period_start == book.lots[0].acquired_at


def test_disposed_sibling_slices_cannot_be_replacements() -> None:
    book = build_tax_book(
        (
            fill(1, day=-5, price="12.00"),
            fill(2, day=-4, price="11.00"),
            fill(3, side=Side.SELL, qty=20, price="9.00"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    assert len(book.sales) == 2 and not book.adjustments and not book.lots
    assert sum((row.economic_gain for row in book.sales), Decimal(0)) == Decimal(-50)


def test_retained_partial_purchase_washes_only_retained_shares() -> None:
    book = build_tax_book(
        (fill(1, day=-5, qty=10), fill(2, side=Side.SELL, qty=4, price="9.00")),
        (account(),),
        registry(),
        "PAPER",
    )
    assert sum((row.wash_disallowed for row in book.sales), Decimal(0)) == Decimal(4)
    assert sum((row.basis for row in book.lots), Decimal(0)) == Decimal(64)
    assert sum(row.qty for row in book.lots) == 6


@pytest.mark.parametrize(
    "rows",
    [
        (fill(1, side=Side.SELL),),
        (fill(1), fill(2, side=Side.SELL)),
        (fill(1), fill(1)),
        (fill(1, owner="unknown"),),
        (fill(1, day=-100), fill(2, side=Side.SELL, qty=11)),
    ],
)
def test_unverifiable_inventory_refuses(rows: tuple[TaxFill, ...]) -> None:
    with pytest.raises(DataIntegrityError):
        build_tax_book(rows, (account(),), registry(), "PAPER")
