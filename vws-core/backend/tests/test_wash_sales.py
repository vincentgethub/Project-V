"""R-02/R-03/R-04/R-05/R-13, CMP-01/CMP-02: tax matching boundaries and faults."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.core.errors import DataIntegrityError
from backend.domain.compliance_models import (
    ExternalAccount,
    Form8949Row,
    TaxLot,
    TaxStatus,
    TradeRecord,
    WashAdjustment,
)
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import AssetClass, Instrument, Side
from backend.risk.wash_sales import WashSaleMatcher, trade_day

NOW = datetime(2026, 10, 2, 16, tzinfo=UTC)
OLD = NOW - timedelta(days=100)
ACCOUNTS = (
    ExternalAccount(account_id="tax", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="other", tax_status=TaxStatus.TAXABLE),
    ExternalAccount(account_id="ira", tax_status=TaxStatus.IRA),
    ExternalAccount(account_id="roth", tax_status=TaxStatus.ROTH),
)


def registry(*, grouped: bool = False) -> InstrumentRegistry:
    """CMP-01/CMP-02: fixture identities are explicit, never inferred."""
    names = tuple(
        Instrument(
            symbol=name,
            asset_class=AssetClass.STOCK,
            gics_sector="Information Technology",
            is_leveraged=False,
            is_inverse=False,
            tradable=True,
        )
        for name in ("AAA", "BBB", "CCC")
    )
    return InstrumentRegistry(names, identical_groups={"paired": ("AAA", "BBB")} if grouped else {})


def buy(
    identifier: int,
    *,
    qty: int = 100,
    ts: datetime = NOW,
    price: Decimal = Decimal("10.00"),
    account: str = "other",
    symbol: str = "AAA",
    drip: bool = False,
) -> TradeRecord:
    """CMP-01/CMP-02: executed replacement fixture."""
    return TradeRecord(
        trade_id=UUID(int=identifier),
        account_id=account,
        symbol=symbol,
        side=Side.BUY,
        qty=qty,
        price=price,
        ts=ts,
        is_drip=drip,
    )


def sale(
    identifier: int,
    *,
    qty: int = 100,
    ts: datetime = NOW,
    loss: Decimal = Decimal("100.00"),
    price: Decimal = Decimal("9.00"),
    account: str = "tax",
    symbol: str = "AAA",
    held_from: datetime | None = OLD,
    origin: UUID | None = None,
) -> TradeRecord:
    """CMP-02: one attested acquisition-lot disposal."""
    return TradeRecord(
        trade_id=UUID(int=identifier),
        account_id=account,
        symbol=symbol,
        side=Side.SELL,
        qty=qty,
        price=price,
        ts=ts,
        realized_loss=loss,
        holding_period_start=held_from,
        acquisition_trade_id=origin,
    )


def adjustment() -> WashAdjustment:
    """CMP-02: valid matched evidence for standalone exporter fault tests."""
    return WashSaleMatcher(registry()).adjustments((sale(1), buy(2)), ACCOUNTS)[0]


def marked_lot(
    identifier: int, *, account: str = "ira", symbol: str = "AAA", acquired: datetime = NOW
) -> TaxLot:
    return TaxLot(
        lot_id=UUID(int=identifier),
        account_id=account,
        symbol=symbol,
        qty=3,
        acquired_at=acquired,
        cost_basis=Decimal("12.50"),
    )


@pytest.mark.parametrize("account", ["ira", "roth", "merrill", "401k"])
@pytest.mark.parametrize(
    "offset,review", [(-31, False), (-30, True), (0, True), (30, True), (31, False)]
)
def test_TX_marked_outside_accounts_review_inclusive_window(
    account: str, offset: int, review: bool
) -> None:
    lot = marked_lot(20, account=account, acquired=NOW + timedelta(days=offset))
    loss = sale(1, loss=Decimal("0.01"))
    result = WashSaleMatcher(registry()).marked_external_lots(loss, (lot,))
    assert result == ((lot,) if review else ())
    # Awareness must not invent a retirement classification, disallowance or basis change.
    assert lot.cost_basis == Decimal("12.50") and lot.qty == 3
    assert loss.realized_loss == Decimal("0.01")


def test_TX_marked_lots_use_declared_identity_and_external_ownership() -> None:
    lots = (
        marked_lot(20, symbol="BBB"),
        marked_lot(21, symbol="CCC"),
        marked_lot(22, account="tax"),
        marked_lot(23, account="merrill"),
    )
    matcher = WashSaleMatcher(registry(grouped=True))
    assert matcher.marked_external_lots(sale(1), lots) == (lots[0], lots[3])
    assert matcher.marked_external_lots(sale(1, loss=Decimal(0)), lots) == ()
    assert matcher.marked_external_lots(sale(1), ()) == ()


def test_TX_marked_window_uses_exchange_date_across_utc_midnight() -> None:
    sold = datetime(2026, 10, 3, 1, tzinfo=UTC)  # October 2 in New York.
    day30 = marked_lot(20, acquired=datetime(2026, 11, 1, 23, tzinfo=UTC))
    day31 = marked_lot(21, acquired=datetime(2026, 11, 2, 23, tzinfo=UTC))
    assert WashSaleMatcher(registry()).marked_external_lots(sale(1, ts=sold), (day30, day31)) == (
        day30,
    )


@pytest.mark.parametrize(
    "case", ["buy", "mutable", "duplicate", "unknown", "forged_lot", "forged_sale"]
)
def test_TX_marked_awareness_refuses_invalid_evidence(case: str) -> None:
    lot = marked_lot(20)
    trade = sale(1)
    lots: tuple[TaxLot, ...] = (lot,)
    if case == "buy":
        trade = buy(1)
    elif case == "mutable":
        lots = cast(tuple[TaxLot, ...], [lot])
    elif case == "duplicate":
        lots = (lot, lot)
    elif case == "unknown":
        lots = (marked_lot(20, symbol="ZZZ"),)
    elif case == "forged_lot":
        lots = (lot.model_copy(update={"qty": 0}),)
    else:
        trade = trade.model_copy(update={"qty": 0})
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(registry()).marked_external_lots(trade, lots)


def test_cmp_02_same_time_replacements_have_stable_share_priority() -> None:
    earlier_id = buy(2, qty=1, account="ira")
    later_id = buy(3, qty=1, account="other")
    rows = WashSaleMatcher(registry()).adjustments((later_id, sale(1, qty=1), earlier_id), ACCOUNTS)
    assert len(rows) == 1
    assert rows[0].replacement_trade_id == earlier_id.trade_id and rows[0].permanent_loss


def test_cmp_02_partial_replacements_cannot_overallocate_remaining_loss() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (
            sale(1, qty=3, loss=Decimal("6")),
            buy(2, qty=1),
            buy(3, qty=5, ts=NOW + timedelta(days=1)),
        ),
        ACCOUNTS,
    )
    assert [(row.qty, row.disallowed_loss) for row in rows] == [
        (1, Decimal("2")),
        (2, Decimal("4")),
    ]


def test_cmp_02_fifo_disposal_spanning_purchases_keeps_only_retained_shares() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, qty=2, account="tax", ts=NOW - timedelta(days=3)),
            buy(2, qty=2, account="tax", ts=NOW - timedelta(days=2)),
            sale(3, qty=3, loss=Decimal(0), held_from=None),
            sale(4, account="other", qty=1, loss=Decimal("4"), ts=NOW + timedelta(days=1)),
        ),
        ACCOUNTS,
    )
    assert len(rows) == 1
    assert rows[0].replacement_trade_id == UUID(int=2)
    assert rows[0].qty == 1 and rows[0].disallowed_loss == Decimal("4")


def test_cmp_02_one_execution_with_gain_and_loss_slices_has_only_a_loss_snapshot() -> None:
    loss = sale(3, qty=1, price=Decimal("10"), loss=Decimal("5"), origin=UUID(int=1))
    gain = sale(
        4,
        qty=1,
        price=Decimal("10"),
        loss=Decimal(0),
        origin=UUID(int=2),
        held_from=OLD + timedelta(days=1),
    )
    history = (
        buy(1, account="tax", qty=1, ts=OLD, price=Decimal("15")),
        buy(2, account="tax", qty=1, ts=OLD + timedelta(days=1), price=Decimal("5")),
        loss.model_copy(update={"execution_id": UUID(int=100)}),
        gain.model_copy(update={"execution_id": UUID(int=100)}),
    )
    matcher = WashSaleMatcher(registry())
    ordered, _ = matcher._inputs(history, ACCOUNTS)
    loss_snapshots = matcher._survivors(ordered)
    assert set(loss_snapshots) == {loss.trade_id}
    assert loss_snapshots[loss.trade_id] == {UUID(int=1): 0, UUID(int=2): 0}
    assert matcher.adjustments(history, ACCOUNTS) == ()


@pytest.mark.parametrize(
    "first,assigned,requested,expected",
    [(0, [(2, 4)], 3, ((0, 2), (4, 5))), (4, [(0, 2), (5, 6)], 2, ((4, 5), (6, 7)))],
)
def test_cmp_02_retained_share_ranges_skip_previous_matches_without_reusing_them(
    first: int,
    assigned: list[tuple[int, int]],
    requested: int,
    expected: tuple[tuple[int, int], ...],
) -> None:
    # Seven acquired shares; disposed prefixes and already washed ranges are unavailable.
    assert WashSaleMatcher._available_slices(first, 7, assigned, requested) == expected


@pytest.mark.parametrize("offset,expected", [(-31, 0), (-30, 100), (0, 100), (30, 100), (31, 0)])
def test_cmp_01_cmp_02_inclusive_day_30_and_31(offset: int, expected: int) -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (buy(2, ts=NOW + timedelta(days=offset)), sale(1)), ACCOUNTS
    )
    assert sum(row.qty for row in rows) == expected


def test_cmp_02_partial_loss_does_not_absorb_unmatched_loss() -> None:
    rows = WashSaleMatcher(registry()).adjustments((sale(1), buy(2, qty=10)), ACCOUNTS)
    assert len(rows) == 1
    assert rows[0].disallowed_loss == Decimal("10.00")
    assert rows[0].cost_basis == Decimal("100.00")
    assert rows[0].adjusted_basis == Decimal("110.00")
    exported = WashSaleMatcher.form_8949_rows(rows)
    assert exported[0].proceeds == Decimal("90.00")
    assert exported[0].adjustment == Decimal("10.00")
    assert exported[0].gain_or_loss == 0
    assert exported[0].code == "W"


def test_cmp_02_irs_publication_550_example_chronological_matching() -> None:
    acquired = datetime(2024, 9, 20, 16, tzinfo=UTC)
    sold = datetime(2025, 1, 3, 16, tzinfo=UTC)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, ts=acquired, price=Decimal("50.00"), account="tax"),
            buy(2, qty=50, ts=datetime(2024, 12, 13, 16, tzinfo=UTC), price=Decimal("55.00")),
            buy(3, qty=25, ts=datetime(2024, 12, 20, 16, tzinfo=UTC), price=Decimal("45.00")),
            sale(4, ts=sold, price=Decimal("40.00"), loss=Decimal("1000.00"), held_from=acquired),
        ),
        ACCOUNTS,
    )
    assert [row.qty for row in rows] == [50, 25]
    assert [row.disallowed_loss for row in rows] == [Decimal("500"), Decimal("250")]
    assert [row.adjusted_basis for row in rows] == [Decimal("3250"), Decimal("1375")]
    exported = WashSaleMatcher.form_8949_rows(rows)
    assert sum(row.adjustment for row in exported) == Decimal("750")
    assert sum(row.proceeds for row in exported) == Decimal("3000")
    assert sum(row.cost_basis for row in exported) == Decimal("3750")


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_cmp_01_ira_roth_permanent_loss_no_basis_increase(account: str) -> None:
    row = WashSaleMatcher(registry()).adjustments((sale(1), buy(2, account=account)), ACCOUNTS)[0]
    assert row.permanent_loss
    assert row.adjusted_basis is None
    assert row.disallowed_loss == Decimal("100")


@pytest.mark.parametrize("account", ["ira", "roth"])
def test_cmp_02_ira_roth_loss_sales_have_no_taxable_loss_deduction(account: str) -> None:
    assert (
        WashSaleMatcher(registry()).adjustments((sale(1, account=account), buy(2)), ACCOUNTS) == ()
    )


def test_cmp_01_identical_group_and_drip_other_accounts() -> None:
    rows = WashSaleMatcher(registry(grouped=True)).adjustments(
        (sale(1), buy(2, qty=25, symbol="BBB", drip=True), buy(3, symbol="CCC")), ACCOUNTS
    )
    assert len(rows) == 1
    assert rows[0].replacement_trade_id == UUID(int=2)
    assert rows[0].qty == 25


def test_cmp_02_loss_lot_cannot_replace_its_own_disposed_shares() -> None:
    acquired = NOW - timedelta(days=10)
    original = buy(1, account="tax", ts=acquired)
    loss = sale(2, held_from=acquired, origin=original.trade_id)
    assert WashSaleMatcher(registry()).adjustments((loss, original), ACCOUNTS) == ()


def test_cmp_02_retained_shares_of_original_purchase_can_replace_sold_slice() -> None:
    acquired = NOW - timedelta(days=10)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, account="tax", ts=acquired),
            sale(2, qty=50, loss=Decimal("50"), held_from=acquired),
        ),
        ACCOUNTS,
    )
    assert len(rows) == 1
    assert rows[0].qty == 50


def test_cmp_02_disposed_before_loss_purchase_is_not_available() -> None:
    acquired = NOW - timedelta(days=10)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, ts=acquired),
            sale(
                2, account="other", loss=Decimal(0), ts=NOW - timedelta(days=5), held_from=acquired
            ),
            sale(3),
        ),
        ACCOUNTS,
    )
    assert rows == ()


def test_cmp_02_later_disposal_does_not_erase_prior_valid_match() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (
            sale(1),
            buy(2, ts=NOW + timedelta(days=1)),
            sale(3, account="other", loss=Decimal(0), ts=NOW + timedelta(days=2), held_from=None),
        ),
        ACCOUNTS,
    )
    assert len(rows) == 1
    assert rows[0].replacement_trade_id == UUID(int=2)


def test_cmp_02_shared_capacity_does_not_reuse_retained_previously_matched_shares() -> None:
    acquired = NOW - timedelta(days=1)
    rows = WashSaleMatcher(registry()).adjustments(
        (
            buy(1, ts=acquired),
            sale(2, qty=75, loss=Decimal("75")),
            sale(
                3,
                qty=25,
                account="other",
                loss=Decimal(0),
                ts=NOW + timedelta(days=1),
                held_from=acquired,
            ),
            sale(4, ts=NOW + timedelta(days=2)),
        ),
        ACCOUNTS,
    )
    assert [row.qty for row in rows] == [75, 25]
    assert sum(row.qty for row in rows) == 100
    assert sum(row.disallowed_loss for row in rows) == 100


def test_cmp_02_multiple_loss_sales_exhaust_replacement_capacity() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (sale(1), sale(2, ts=NOW + timedelta(days=1)), buy(3, qty=150, ts=NOW + timedelta(days=2))),
        ACCOUNTS,
    )
    assert [row.qty for row in rows] == [100, 50]
    assert [row.disallowed_loss for row in rows] == [Decimal("100"), Decimal("50")]


def test_cmp_02_micro_loss_proportions_and_full_residual_are_exact() -> None:
    rows = WashSaleMatcher(registry()).adjustments(
        (
            sale(1, qty=3, loss=Decimal("1.000001")),
            buy(2, qty=1),
            buy(3, qty=1),
            buy(4, qty=1),
            buy(5),
        ),
        ACCOUNTS,
    )
    assert [row.disallowed_loss for row in rows] == [
        Decimal("0.333333"),
        Decimal("0.333334"),
        Decimal("0.333334"),
    ]
    assert sum(row.disallowed_loss for row in rows) == Decimal("1.000001")


def test_r_02_cmp_02_loss_smaller_than_micro_allocation_fails_typed() -> None:
    with pytest.raises(DataIntegrityError, match="micro-unit"):
        WashSaleMatcher(registry()).adjustments(
            (sale(1, qty=100, loss=Decimal("0.000001")), buy(2, qty=1)), ACCOUNTS
        )


def test_r_04_cmp_02_ambient_decimal_precision_cannot_change_matching() -> None:
    matcher = WashSaleMatcher(registry())
    history = (sale(1, qty=3, loss=Decimal("1.000001")), buy(2, qty=2))
    expected = matcher.adjustments(history, ACCOUNTS)
    with localcontext() as context:
        context.prec = 2
        assert matcher.adjustments(history, ACCOUNTS) == expected
        assert matcher.form_8949_rows(expected)[0].gain_or_loss == 0


def test_r_05_cmp_02_holding_period_tacking_uses_calendar_days_across_dst() -> None:
    ny = ZoneInfo("America/New_York")
    acquired = datetime(2026, 10, 15, 0, 30, tzinfo=ny).astimezone(UTC)
    sold = datetime(2026, 11, 4, 0, 30, tzinfo=ny).astimezone(UTC)
    replacement = datetime(2026, 11, 5, 0, 30, tzinfo=ny).astimezone(UTC)
    row = WashSaleMatcher(registry()).adjustments(
        (sale(1, ts=sold, held_from=acquired), buy(2, ts=replacement)), ACCOUNTS
    )[0]
    assert trade_day(row.holding_period_start) == date(2026, 10, 16)
    assert row.holding_period_start.astimezone(ny).hour == 0


def test_r_05_cmp_02_utc_midnight_window_uses_new_york_trade_date() -> None:
    assert trade_day(datetime(2026, 10, 2, 1, tzinfo=UTC)) == date(2026, 10, 1)


@given(
    qty=st.integers(1, 10000),
    replacement_qty=st.integers(1, 10000),
    loss_micro=st.integers(10000, 10000000),
)
def test_r_03_r_04_cmp_02_property_partial_matches_are_proportional_and_deterministic(
    qty: int, replacement_qty: int, loss_micro: int
) -> None:
    matcher = WashSaleMatcher(registry())
    loss = Decimal(loss_micro) / 1000000
    history = (sale(1, qty=qty, loss=loss), buy(2, qty=replacement_qty))
    rows = matcher.adjustments(history, ACCOUNTS)
    assert rows == matcher.adjustments(tuple(reversed(history)), ACCOUNTS)
    assert sum(row.qty for row in rows) == min(qty, replacement_qty)
    expected_micro = loss_micro * min(qty, replacement_qty) // qty
    assert sum(row.disallowed_loss for row in rows) == Decimal(expected_micro) / 1000000
    assert sum(row.disallowed_loss for row in rows) <= loss


@pytest.mark.parametrize("bad_price", [Decimal("9.001"), Decimal("NaN"), Decimal(0), 9.0, "9.00"])
def test_r_13_cmp_02_execution_price_requires_decimal_cents(bad_price: object) -> None:
    with pytest.raises(ValidationError):
        TradeRecord.model_validate({**buy(1).model_dump(), "price": bad_price})


@pytest.mark.parametrize("bad_qty", [True, 1.0, "1", 0, -1])
def test_r_01_cmp_02_quantity_is_strict_positive_integer(bad_qty: object) -> None:
    with pytest.raises(ValidationError):
        TradeRecord.model_validate({**buy(1).model_dump(), "qty": bad_qty})


def test_r_04_cmp_02_fractional_cent_tax_basis_is_preserved() -> None:
    lot = TaxLot(
        lot_id=UUID(int=1),
        account_id="tax",
        symbol="AAA",
        qty=3,
        acquired_at=OLD,
        cost_basis=Decimal("10.333333"),
        funding_settlement_date=date(2026, 7, 1),
    )
    assert lot.cost_basis == Decimal("10.333333")


def test_r_02_cmp_02_tax_lot_preserves_actual_date_and_explicit_tacked_start() -> None:
    lot = TaxLot(
        lot_id=UUID(int=1),
        account_id="tax",
        symbol="AAA",
        qty=3,
        acquired_at=NOW - timedelta(days=10),
        cost_basis=Decimal("10.333333"),
        acquisition_trade_id=UUID(int=2),
        holding_period_start=OLD,
    )
    assert lot.acquired_at == NOW - timedelta(days=10)
    assert lot.holding_period_start == OLD
    assert TaxLot.model_validate(lot) == lot
    same_start = lot.model_copy(
        update={"holding_period_start": lot.acquired_at, "acquisition_trade_id": None}
    )
    assert TaxLot.model_validate(same_start).holding_period_start == lot.acquired_at


@pytest.mark.parametrize(
    "changes",
    [
        {"holding_period_start": NOW + timedelta(days=1)},
        {"holding_period_start": OLD, "acquisition_trade_id": None},
        {"holding_period_start": datetime(2026, 7, 1)},
    ],
)
def test_r_02_r_05_cmp_02_tax_lot_rejects_future_unidentified_or_naive_tacking(
    changes: dict[str, object],
) -> None:
    lot = TaxLot(
        lot_id=UUID(int=1),
        account_id="tax",
        symbol="AAA",
        qty=1,
        acquired_at=NOW,
        cost_basis=Decimal("10.00"),
    )
    with pytest.raises(ValidationError):
        TaxLot.model_validate(lot.model_copy(update=changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"side": Side.BUY},
        {"holding_period_start": None},
        {"holding_period_start": NOW + timedelta(days=1)},
    ],
)
def test_r_02_cmp_02_loss_sale_requires_consistent_holding_evidence(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TradeRecord.model_validate({**sale(1).model_dump(), **changes})


def test_r_02_cmp_02_buy_cannot_reference_disposal_and_drip_is_buy_only() -> None:
    with pytest.raises(ValidationError, match="acquisition reference"):
        TradeRecord.model_validate({**buy(1).model_dump(), "acquisition_trade_id": UUID(int=2)})
    with pytest.raises(ValidationError, match="DRIP"):
        TradeRecord.model_validate({**sale(1).model_dump(), "is_drip": True})


@pytest.mark.parametrize("changes", [{"qty": True}, {"price": Decimal("9.001")}, {"side": "FAKE"}])
def test_r_02_cmp_02_forged_trade_models_fail_typed(changes: dict[str, object]) -> None:
    forged = buy(1).model_copy(update=changes)
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(registry()).adjustments((forged,), ACCOUNTS)


def test_r_02_cmp_02_invalid_history_ownership_ids_and_symbol_fail_typed() -> None:
    matcher = WashSaleMatcher(registry())
    for history, accounts in (
        ((buy(1), buy(1)), ACCOUNTS),
        ((buy(1, account="unknown"),), ACCOUNTS),
        ((buy(1, symbol="ZZZ"),), ACCOUNTS),
        ((buy(1),), (*ACCOUNTS, ACCOUNTS[0])),
        ((buy(1),), (ACCOUNTS[0].model_copy(update={"tax_status": "FAKE"}),)),
    ):
        with pytest.raises(DataIntegrityError):
            matcher.adjustments(history, accounts)
    with pytest.raises(DataIntegrityError):
        matcher.adjustments(cast(tuple[TradeRecord, ...], [buy(1)]), ACCOUNTS)
    with pytest.raises(DataIntegrityError):
        matcher.adjustments((), cast(tuple[ExternalAccount, ...], list(ACCOUNTS)))


def test_r_02_cmp_02_disposal_origin_wrong_account_missing_and_oversized_fail_typed() -> None:
    acquired = NOW - timedelta(days=5)
    original = buy(1, account="tax", ts=acquired)
    matcher = WashSaleMatcher(registry())
    for history in (
        (sale(2, origin=UUID(int=99)),),
        (original, sale(2, account="other", origin=original.trade_id)),
        (original, sale(2, origin=original.trade_id, held_from=NOW - timedelta(days=1))),
        (original, sale(2, qty=101, origin=original.trade_id, held_from=acquired)),
        (original, buy(3, account="tax", ts=acquired), sale(2, held_from=acquired)),
    ):
        with pytest.raises(DataIntegrityError):
            matcher.adjustments(history, ACCOUNTS)


def test_cmp_02_explicit_origin_can_supply_tacked_earlier_holding_start() -> None:
    acquired = NOW - timedelta(days=5)
    original = buy(1, account="tax", ts=acquired)
    rows = WashSaleMatcher(registry()).adjustments(
        (original, sale(2, held_from=OLD, origin=original.trade_id), buy(3)), ACCOUNTS
    )
    assert rows[0].acquired_date == trade_day(acquired)
    assert trade_day(rows[0].holding_period_start) == trade_day(OLD)


def test_r_02_cmp_02_registry_ingress_forgery_and_unexpected_fault_are_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(cast(InstrumentRegistry, None))

    def fault(_: InstrumentRegistry) -> InstrumentRegistry:
        raise RuntimeError("registry failure")

    monkeypatch.setattr(InstrumentRegistry, "validated_copy", fault)
    with pytest.raises(DataIntegrityError, match="registry"):
        WashSaleMatcher(registry())


def test_r_02_cmp_02_matching_unexpected_fault_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    matcher = WashSaleMatcher(registry())

    def fault(_: tuple[TradeRecord, ...]) -> dict[UUID, dict[UUID, int]]:
        raise RuntimeError("inventory failure")

    monkeypatch.setattr(matcher, "_survivors", fault)
    with pytest.raises(DataIntegrityError, match="matching"):
        matcher.adjustments((sale(1), buy(2)), ACCOUNTS)


def test_r_02_cmp_02_tied_disposal_without_original_metadata_is_unverifiable() -> None:
    with pytest.raises(DataIntegrityError, match="Tied"):
        WashSaleMatcher(registry()).adjustments(
            (buy(1, account="tax"), sale(2, loss=Decimal(0), held_from=None)), ACCOUNTS
        )


def test_r_02_cmp_02_adjustment_helper_cannot_guess_missing_holding_period() -> None:
    forged = sale(1).model_copy(update={"holding_period_start": None})
    with pytest.raises(DataIntegrityError, match="holding-period"):
        WashSaleMatcher._adjustment(forged, buy(2), 1, Decimal("1"), {"other": TaxStatus.TAXABLE})


def test_r_02_cmp_02_exporter_revalidates_and_rejects_duplicate_slices() -> None:
    row = adjustment()
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher.form_8949_rows((row, row))
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher.form_8949_rows(cast(tuple[WashAdjustment, ...], [row]))
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher.form_8949_rows(
            (row.model_copy(update={"disallowed_loss": Decimal("999")}),)
        )
    assert WashSaleMatcher.form_8949_rows(()) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"cost_basis": Decimal("1")},
        {"acquired_date": date(2030, 1, 1)},
        {"permanent_loss": True},
        {"adjusted_basis": None},
        {"adjusted_basis": Decimal("100")},
    ],
)
def test_r_02_cmp_02_wash_adjustment_internal_totals_are_checked(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WashAdjustment.model_validate({**adjustment().model_dump(), **changes})


def test_r_02_cmp_02_form_8949_model_checks_totals_and_dates() -> None:
    row = WashSaleMatcher.form_8949_rows((adjustment(),))[0]
    with pytest.raises(ValidationError):
        Form8949Row.model_validate({**row.model_dump(), "gain_or_loss": Decimal("1")})
    with pytest.raises(ValidationError):
        Form8949Row.model_validate({**row.model_dump(), "date_acquired": date(2030, 1, 1)})
