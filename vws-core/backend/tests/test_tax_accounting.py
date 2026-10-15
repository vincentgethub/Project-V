"""TX-01..05: hand-computed executions, fees, partial washes and holding periods."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from backend.core.errors import DataIntegrityError
from backend.domain.compliance_models import TaxStatus
from backend.domain.models import Side
from backend.tax import accounting
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


def test_TX_04_february_nonleap_anniversary_preserves_day() -> None:
    assert anniversary(date(2025, 2, 12)) == date(2026, 2, 12)


def test_TX_02_compliance_buckets_conserve_micro_basis_and_acquisition_evidence() -> None:
    acquired = fill(1, qty=3, fees="0.01")
    book = build_tax_book((acquired,), (account(),), registry(), "PAPER")
    lots = book.compliance_lots()
    assert [(row.qty, row.cost_basis) for row in lots] == [
        (2, Decimal("10.003333")),
        (1, Decimal("10.003334")),
    ]
    assert sum(row.qty for row in lots) == 3
    assert sum((row.qty * row.cost_basis for row in lots), Decimal(0)) == Decimal("30.01")
    assert all(row.acquisition_trade_id == acquired.fill_id for row in lots)
    assert all(row.holding_period_start == acquired.ts for row in lots)
    assert len({row.lot_id for row in lots}) == 2
    assert book.compliance_lots() == lots
    # Published acquisition references remain stable when the same ledger is replayed.
    assert [str(row.lot_id) for row in lots] == [
        "b7b071c4-6a01-5205-a50f-6fccd425b18a",
        "b7d1977a-6ddf-5796-8743-d990751007e6",
    ]


def test_TX_05_compliance_lots_preserve_tacked_period_and_original_acquisition() -> None:
    replacement = fill(3, day=1, qty=3, price="8")
    book = build_tax_book(
        (fill(1, day=-100, qty=3), fill(2, side=Side.SELL, qty=3, price="9"), replacement),
        (account(),),
        registry(),
        "PAPER",
    )
    lots = book.compliance_lots()
    assert sum((row.qty * row.cost_basis for row in lots), Decimal(0)) == Decimal("27")
    assert all(row.acquisition_trade_id == replacement.fill_id for row in lots)
    assert all(row.holding_period_start == replacement.ts - timedelta(days=100) for row in lots)


def test_TX_03_sell_fees_are_allocated_once_across_multiple_original_lots() -> None:
    book = build_tax_book(
        (
            fill(1, day=-100, qty=1),
            fill(2, day=-90, qty=2, price="12"),
            fill(3, side=Side.SELL, qty=3, price="15", fees="0.01"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    assert [row.proceeds for row in book.sales] == [Decimal("14.996667"), Decimal("29.993333")]
    assert [row.basis for row in book.sales] == [Decimal("10"), Decimal("24")]
    assert sum((row.economic_gain for row in book.sales), Decimal(0)) == Decimal("10.99")
    for sale, trade in zip(
        book.sales, (row for row in book.history if row.side == Side.SELL), strict=True
    ):
        assert trade.acquisition_trade_id == sale.acquisition_id


def test_TX_05_partial_disposals_conserve_remaining_wash_basis() -> None:
    book = build_tax_book(
        (
            fill(1, day=-100, qty=4),
            fill(2, side=Side.SELL, qty=4, price="9"),
            fill(3, day=1, qty=4, price="8"),
            fill(4, side=Side.SELL, day=2, qty=1, price="10"),
            fill(5, side=Side.SELL, day=3, qty=1, price="10"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    assert [row.basis for row in book.sales] == [Decimal("40"), Decimal("9"), Decimal("9")]
    assert [row.wash_basis for row in book.sales] == [Decimal(0), Decimal(1), Decimal(1)]
    assert [(row.qty, row.basis, row.wash_basis) for row in book.lots] == [
        (2, Decimal("18"), Decimal("2"))
    ]


def test_TX_05_wash_amount_is_invariant_to_replacement_share_segmentation() -> None:
    rows = (
        fill(1, day=-100, qty=3, price="10.01"),
        fill(2, side=Side.SELL, qty=3, price="10"),
        fill(3, day=1, qty=3, price="8"),
    )
    book = build_tax_book(rows, (account(),), registry(), "PAPER")
    allocation = (book.adjustments[0], ((0, 3),))
    sales, lots, _ = accounting._rebuild(
        rows,
        {"tax": account()},
        (allocation,),
        book.history,
        {rows[0].fill_id: {0, 3}, rows[2].fill_id: {0, 1, 3}},
    )
    assert [row.basis for row in lots] == [Decimal("8.01"), Decimal("16.02")]
    assert sum((row.wash_basis for row in lots), Decimal(0)) == Decimal("0.03")
    assert sum((row.basis for row in sales), Decimal(0)) == Decimal("30.03")
    assert all(row.holding_period_start == rows[2].ts - timedelta(days=100) for row in lots)


def test_TX_02_compressed_open_lots_conserve_uneven_pool_rounding() -> None:
    book = build_tax_book(
        (fill(1, qty=1, fees="0.01"), fill(2, qty=2, minutes=1)),
        (account(compressed=True),),
        registry(),
        "PAPER",
    )
    assert [row.basis for row in book.lots] == [Decimal("10.003333"), Decimal("20.006667")]
    assert sum((row.basis for row in book.lots), Decimal(0)) == Decimal("30.01")


def test_TX_01_live_accounting_uses_only_live_bound_fills() -> None:
    live = fill(1).model_copy(update={"env": "LIVE"})
    book = build_tax_book((live,), (account(),), registry(), "LIVE")
    assert book.env == "LIVE" and book.fills == (live,)
    assert book.lots[0].env == "LIVE" and book.lots[0].basis == Decimal("100")


def test_TX_06_drip_acquisition_remains_identified_in_shared_history() -> None:
    drip = fill(1).model_copy(update={"is_drip": True})
    book = build_tax_book((drip,), (account(),), registry(), "PAPER")
    assert book.history[0].is_drip and book.history[0].trade_id == drip.fill_id


def test_TX_05_simultaneous_cross_account_rebuy_has_available_replacement_shares() -> None:
    book = build_tax_book(
        (fill(1, day=-100), fill(2, side=Side.SELL, price="9"), fill(3, owner="other", price="8")),
        (account(), account("other")),
        registry(),
        "PAPER",
    )
    assert len(book.adjustments) == 1
    assert book.sales[0].wash_disallowed == Decimal("10") and book.sales[0].taxable_gain == 0
    assert book.lots[0].account_id == "other" and book.lots[0].basis == Decimal("90")
    assert book.lots[0].holding_period_start == fill(1, day=-100).ts


def test_TX_05_permanent_loss_is_attributed_only_to_its_own_disposal() -> None:
    book = build_tax_book(
        (
            fill(1, day=-100),
            fill(2, side=Side.SELL, price="9"),
            fill(3, day=-100, owner="other", price="8"),
            fill(4, side=Side.SELL, owner="other", price="11"),
            fill(5, day=1, owner="ira"),
        ),
        (account(), account("other"), account("ira", status=TaxStatus.IRA)),
        registry(),
        "PAPER",
    )
    assert [
        (row.account_id, row.wash_disallowed, row.permanent_disallowed, row.taxable_gain)
        for row in book.sales
    ] == [
        ("tax", Decimal("10"), Decimal("10"), Decimal(0)),
        ("other", Decimal(0), Decimal(0), Decimal("30")),
    ]


def test_TX_05_partial_washed_share_interval_preserves_undisposed_extra_basis() -> None:
    rows = (
        fill(1, day=-100, qty=4),
        fill(2, side=Side.SELL, qty=4, price="9"),
        fill(3, day=1, qty=4, price="8"),
        fill(4, side=Side.SELL, day=2, qty=1, price="10"),
    )
    book = build_tax_book(rows, (account(),), registry(), "PAPER")
    allocation = (book.adjustments[0], ((0, 4),))
    sales, lots, _ = accounting._rebuild(
        rows,
        {"tax": account()},
        (allocation,),
        book.history,
        {rows[0].fill_id: {0, 4}, rows[2].fill_id: {0, 4}},
    )
    assert sales[-1].basis == Decimal("9") and sales[-1].wash_basis == Decimal("1")
    assert [(row.qty, row.basis, row.wash_basis) for row in lots] == [
        (3, Decimal("27"), Decimal("3"))
    ]


@pytest.mark.parametrize("mutable", ["fills", "accounts"])
def test_TX_01_public_accounting_requires_immutable_evidence(mutable: str) -> None:
    rows: tuple[TaxFill, ...] = (fill(1),)
    owners: tuple[TaxAccount, ...] = (account(),)
    if mutable == "fills":
        rows = cast(tuple[TaxFill, ...], list(rows))
    else:
        owners = cast(tuple[TaxAccount, ...], list(owners))
    with pytest.raises(DataIntegrityError):
        build_tax_book(rows, owners, registry(), "PAPER")


def test_TX_01_duplicate_broker_activity_cannot_create_two_acquisitions() -> None:
    duplicate = fill(2, minutes=1).model_copy(update={"activity_id": fill(1).activity_id})
    with pytest.raises(DataIntegrityError):
        build_tax_book((fill(1), duplicate), (account(),), registry(), "PAPER")


def test_TX_01_untrusted_history_cannot_hide_its_advertised_capacity_overflow() -> None:
    class OversizedEvidence(tuple[TaxFill, ...]):
        def __len__(self) -> int:
            return 100001

    # An inconsistent collection must not become a plausible one-fill tax book.
    rows = OversizedEvidence((fill(1),))
    with pytest.raises(DataIntegrityError):
        build_tax_book(rows, (account(),), registry(), "PAPER")


def test_TX_02_row_capacity_accepts_exact_boundary_and_refuses_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a small disposable capacity to exercise the inclusive contract without a huge ledger.
    monkeypatch.setattr(accounting, "MAX_ACCOUNTING_ROWS", 2)
    rows = (fill(1, day=-100), fill(2, side=Side.SELL, price="11"))
    book = build_tax_book(rows, (account(),), registry(), "PAPER")
    assert len(book.fills) == 2 and book.sales[0].economic_gain == Decimal("10")
    with pytest.raises(DataIntegrityError):
        build_tax_book((*rows, fill(3, day=1)), (account(),), registry(), "PAPER")
