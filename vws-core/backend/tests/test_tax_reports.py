"""TX-06..10: simulated labels, netting, immutable imports and 1099-B differences."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import TaxEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import Side
from backend.domain.tax_profile import TaxProfile
from backend.tax.accounting import build_tax_book
from backend.tax.imports import import_fills
from backend.tax.models import NOTICE, SIMULATED, TaxIncome
from backend.tax.reconcile import (
    Broker1099,
    ColumnMapping,
    read_1099,
    reconcile,
    reconciliation_csv,
    summary,
)
from backend.tax.reports import annual, render_report, save_report
from backend.tax.storage import read_fills
from backend.tests.test_tax_accounting import account, fill
from backend.tests.test_wash_sales import registry


def test_all_simulated_export_headers_rows_and_immutable_files(tmp_path: Path) -> None:
    book = build_tax_book(
        (
            fill(1, day=-100),
            fill(2, side=Side.SELL, price="9.00"),
            fill(3, day=1, qty=4, price="8.00"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    totals, files = render_report(
        book, (), TaxProfile(), registry(), 2026, date(2026, 10, 4), simulate=True
    )
    assert totals.net_st == Decimal(-6) and totals.wash_disallowed == Decimal(4)
    assert totals.set_aside_estimate is None and not totals.wash_window_complete
    for name, data in files.items():
        assert SIMULATED in data.decode("utf-8")
        if name.endswith(".csv"):
            rows = tuple(csv.reader(io.StringIO(data.decode("utf-8"))))
            assert SIMULATED in rows[0][0] and all(
                row[0] == SIMULATED and row[-1] == NOTICE for row in rows[1:]
            )
    destination = save_report(tmp_path, totals, files)
    assert destination.name and destination.parent.parent.name == "PAPER"
    assert save_report(tmp_path, totals, files) == destination
    with pytest.raises(DataIntegrityError):
        render_report(book, (), TaxProfile(), registry(), 2026, date(2026, 10, 4))
    with pytest.raises(DataIntegrityError):
        save_report(tmp_path / "config", totals, files)


def test_netting_estimate_and_unclassified_income() -> None:
    # ST gain 50; LT loss 50 offsets it. DIV subtype is retained/unclassified.
    book = build_tax_book(
        (
            fill(1, day=-366, qty=10, price="20.00"),
            fill(2, day=-100, qty=10),
            fill(3, side=Side.SELL, qty=20, price="15.00"),
        ),
        (account(),),
        registry(),
        "PAPER",
    )
    income = TaxIncome(
        activity_id="div",
        account_id="tax",
        env="PAPER",
        type="DIVNRA",
        date=date(2026, 10, 2),
        amount=Decimal(10),
    )
    profile = TaxProfile(federal_st_rate=Decimal(".22"), federal_lt_rate=Decimal(".15"))
    totals = annual(book, (income,), profile, 2026, date(2027, 1, 30), simulate=True)
    assert (totals.net_st, totals.net_lt, totals.offset_st, totals.offset_lt) == (
        Decimal(50),
        Decimal(-50),
        Decimal(0),
        Decimal(0),
    )
    # TX-08's conservative set-aside uses positive ST/LT totals separately;
    # Schedule D cross-term netting remains a separate record-keeping result.
    assert totals.set_aside_estimate == Decimal("13.20") and totals.dividends == Decimal(10)
    assert totals.wash_window_complete


@pytest.mark.parametrize(
    "status,deduction,carry",
    [("single", "3000", "2000"), ("married_filing_separately", "1500", "3500")],
)
def test_net_loss_limit_and_carryover(status: str, deduction: str, carry: str) -> None:
    book = build_tax_book(
        (fill(1, day=-100, qty=1000), fill(2, side=Side.SELL, qty=1000, price="5.00")),
        (account(),),
        registry(),
        "PAPER",
    )
    totals = annual(
        book,
        (),
        TaxProfile.model_validate({"filing_status": status}),
        2026,
        date(2027, 2, 1),
        simulate=True,
    )
    assert totals.loss_deduction_estimate == Decimal(
        deduction
    ) and totals.carryover_st_estimate == Decimal(carry)
    assert totals.carryover_lt_estimate == 0


def test_1099_difference_strict_cent_and_no_arbitrary_match(tmp_path: Path) -> None:
    book = build_tax_book(
        (fill(1, day=-100), fill(2, side=Side.SELL, price="11.00")),
        (account(),),
        registry(),
        "PAPER",
    )
    ours = book.sales[0]
    broker = Broker1099(
        symbol="AAA",
        date_sold=date(2026, 10, 2),
        qty=10,
        proceeds=Decimal("109.99"),
        basis=Decimal(100),
        wash=Decimal(0),
        term="ST",
    )
    assert reconcile(book, (broker,), 2026, "tax")[0].status == "MATCH"
    changed = Broker1099.model_validate(
        broker.model_copy(update={"proceeds": Decimal("109.98"), "term": "LT"})
    )
    rows = reconcile(book, (changed,), 2026, "tax")
    assert rows[0].status == "DIFFERENT" and "proceeds, term" in rows[0].detail
    assert NOTICE in summary(rows) and SIMULATED.encode() in reconciliation_csv(rows, simulate=True)
    assert reconcile(book, (broker, broker), 2026, "tax")[0].status == "AMBIGUOUS"
    assert reconcile(book, (), 2026, "tax")[0].status == "UNMATCHED_LEDGER"
    path = tmp_path / "broker.csv"
    path.write_text(
        "Ticker,Sale,Shares,Proceeds,Cost,Wash,Term\nAAA,10/02/2026,10,109.99,100,0,short\n",
        encoding="utf-8",
    )
    mapping = ColumnMapping(
        symbol="Ticker",
        date_sold="Sale",
        qty="Shares",
        proceeds="Proceeds",
        basis="Cost",
        wash="Wash",
        term="Term",
        date_format="%m/%d/%Y",
        short_term_label="short",
        long_term_label="long",
    )
    assert read_1099(path, mapping) == (broker,)
    assert ours.economic_gain == Decimal(10)


def test_corrected_import_appends_versions_preserves_original_hashes(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    ledger = Ledger(engine, clock)
    owner = account()
    source = tmp_path / "fills.csv"
    prefix = "id,account_id,env,symbol,side,qty,price,fees,ts,is_drip\n"
    source.write_text(
        prefix + "one,tax,PAPER,AAA,BUY,10,10.00,1.00,2026-09-28T15:00:00+00:00,false\n",
        encoding="utf-8",
    )
    import_fills(ledger, owner, source, "PAPER")
    with Session(engine) as session:
        originals = {row.id: row.row_hash for row in session.scalars(select(TaxEvent))}
    source.write_text(
        prefix + "one,tax,PAPER,AAA,BUY,10,10.00,2.00,2026-09-28T15:00:00+00:00,false\n",
        encoding="utf-8",
    )
    import_fills(ledger, owner, source, "PAPER")
    imported = read_fills(ledger, "tax", "PAPER", csv=True)
    assert len(imported) == 1 and imported[0].fees == Decimal(2)
    with Session(engine) as session:
        all_rows = tuple(session.scalars(select(TaxEvent)))
        assert len(all_rows) == 4 and sum(row.supersedes is not None for row in all_rows) == 2
        assert all(row.row_hash == originals[row.id] for row in all_rows if row.id in originals)
    ledger.verify_chain()
