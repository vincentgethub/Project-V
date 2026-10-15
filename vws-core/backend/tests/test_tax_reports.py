"""TX-06..10: simulated labels, netting, immutable imports and 1099-B differences."""

from __future__ import annotations

import csv
import io
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import TaxEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.compliance_models import TaxStatus
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
from backend.tax.reports import _cell, _csv, _net_terms, annual, render_report, save_report
from backend.tax.storage import read_fills
from backend.tests.test_tax_accounting import account, fill
from backend.tests.test_wash_sales import exact_tax_error, registry


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


@pytest.mark.parametrize("text", ["+SUM(A1)", "-2+3", "@SUM(A1)", "\t=1", "\r=1"])
def test_TX_10_csv_text_cannot_be_interpreted_as_a_spreadsheet_formula(text: str) -> None:
    payload = _csv(("description",), ((text,),), SIMULATED)
    row = list(csv.reader(io.StringIO(payload.decode())))[1]
    assert row[1] == "'" + text
    assert row[-1] == NOTICE


def test_TX_10_csv_uses_exact_fixed_decimal_and_handles_embedded_newlines() -> None:
    assert _cell(Decimal("1E+2")) == "100"
    payload = _csv(("description", "amount"), (("line1\r\nline2", Decimal("-1.20")),), SIMULATED)
    assert payload.endswith(b"\n") and not payload.endswith(b"\r\n")
    rows = list(csv.reader(io.StringIO(payload.decode(), newline="")))
    assert rows[0][-1] == "notice"
    assert rows[1][1:3] == ["line1\r\nline2", "-1.20"]


@pytest.mark.parametrize(
    "st,lt,result",
    [
        ("-.25", ".10", ("-.15", "0")),
        (".10", "-.25", ("0", "-.15")),
        (".25", ".10", (".25", ".10")),
        ("-.25", "-.10", ("-.25", "-.10")),
        ("-.25", "1.25", ("0", "1")),
        ("1.25", "-.25", ("1", "0")),
    ],
)
def test_TX_07_schedule_d_offsets_only_opposite_terms(
    st: str,
    lt: str,
    result: tuple[str, str],
) -> None:
    assert _net_terms(Decimal(st), Decimal(lt)) == tuple(Decimal(value) for value in result)


@pytest.mark.parametrize(
    "st_price,lt_price,deduction,carry_st,carry_lt",
    [("9", "5", "3000", "0", "3000"), ("11", "5", "3000", "0", "1000"), ("15", "9", "0", "0", "0")],
)
def test_TX_07_long_term_carryover_consumes_only_unused_short_term_deduction(
    st_price: str,
    lt_price: str,
    deduction: str,
    carry_st: str,
    carry_lt: str,
) -> None:
    book = build_tax_book(
        (
            fill(1, day=-500, qty=1000, owner="long"),
            fill(2, side=Side.SELL, qty=1000, price=lt_price, owner="long"),
            fill(3, day=-100, qty=1000),
            fill(4, side=Side.SELL, qty=1000, price=st_price),
        ),
        (account(), account("long")),
        registry(),
        "PAPER",
    )
    totals = annual(book, (), TaxProfile(), 2026, date(2027, 2, 1), simulate=True)
    assert (
        totals.loss_deduction_estimate,
        totals.carryover_st_estimate,
        totals.carryover_lt_estimate,
    ) == (
        Decimal(deduction),
        Decimal(carry_st),
        Decimal(carry_lt),
    )


def test_TX_06_08_broker_income_classes_and_all_four_rates_are_separate() -> None:
    book = build_tax_book(
        (
            fill(1, day=-500),
            fill(2, side=Side.SELL, price="12"),
            fill(3, day=-100, owner="other"),
            fill(4, side=Side.SELL, price="13", owner="other"),
        ),
        (account(), account("other")),
        registry(),
        "PAPER",
    )
    incomes = tuple(
        TaxIncome(
            activity_id=str(i),
            account_id="tax",
            env="PAPER",
            type=kind,
            date=date(2026, 10, 2),
            amount=Decimal(amount),
            dividend_class=cast(
                Literal["unclassified", "qualified", "nonqualified", "exempt"], classification
            ),
            classification_proof_sha256="b" * 64 if classification != "unclassified" else None,
        )
        for i, (kind, amount, classification) in enumerate(
            [
                ("DIV", "2", "unclassified"),
                ("DIVNRA", "3", "nonqualified"),
                ("DIV", "7", "qualified"),
                ("INT", "5", "unclassified"),
                ("FEE", "-0.03", "unclassified"),
            ]
        )
    )
    rates = TaxProfile(
        federal_st_rate=Decimal(".22"),
        federal_lt_rate=Decimal(".15"),
        state_rate=Decimal(".0495"),
        niit_rate=Decimal(".038"),
    )
    totals = annual(book, incomes, rates, 2026, date(2027, 2, 1), simulate=True)
    assert (totals.net_st, totals.net_lt) == (Decimal("30"), Decimal("20"))
    assert totals.net_capital == Decimal("50")
    assert (totals.dividends, totals.interest, totals.fees) == (
        Decimal("12"),
        Decimal("5"),
        Decimal("0.03"),
    )
    # 40 ordinary dollars at .3075 + 27 preferential dollars at .2375 = 18.7125.
    assert totals.set_aside_estimate == Decimal("18.72")
    assert totals.permanent_disallowed == 0


def test_TX_08_empty_income_and_gains_do_not_invent_a_one_dollar_tax_base() -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    totals = annual(
        book,
        (),
        TaxProfile(federal_st_rate=Decimal(".22"), federal_lt_rate=Decimal(".15")),
        2026,
        date(2027, 2, 1),
        simulate=True,
    )
    assert totals.set_aside_estimate == Decimal("0.00")
    assert totals.loss_deduction_estimate == 0 and totals.fees == 0


@pytest.mark.parametrize("extra_places", [79, 80])
def test_TX_08_exact_rate_tail_cannot_round_a_positive_cent_remainder_down(
    extra_places: int,
) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    income = TaxIncome(
        activity_id="interest",
        account_id="tax",
        env="PAPER",
        type="INT",
        date=date(2026, 10, 2),
        amount=Decimal(1),
    )
    # One dollar times a finite rate strictly above .01 requires a two-cent ceiling.
    rate = Decimal("0.01" + "0" * extra_places + "1")
    totals = annual(
        book,
        (income,),
        TaxProfile(federal_st_rate=rate, federal_lt_rate=Decimal(0)),
        2026,
        date(2027, 2, 1),
        simulate=True,
    )
    assert totals.set_aside_estimate == Decimal("0.02")


def test_TX_08_all_rates_unavailable_still_reports_totals_without_an_estimate() -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    profile = TaxProfile(
        federal_st_rate=None, federal_lt_rate=None, state_rate=None, niit_rate=None
    )
    totals = annual(book, (), profile, 2026, date(2027, 2, 1), simulate=True)
    assert totals.set_aside_estimate is None
    assert totals.net_st == 0 and totals.net_lt == 0


@pytest.mark.parametrize("day,complete", [(date(2027, 1, 29), False), (date(2027, 1, 30), True)])
def test_TX_05_export_discloses_open_or_complete_year_end_wash_window(
    day: date, complete: bool
) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    totals, files = render_report(book, (), TaxProfile(), registry(), 2026, day, simulate=True)
    assert totals.wash_window_complete == complete
    line = next(
        line
        for line in files["README.txt"].decode().splitlines()
        if line.startswith("Wash replacement window:")
    )
    assert line == (
        "Wash replacement window: complete through the required date."
        if complete
        else "Wash replacement window: still open; future purchases may change losses."
    )


@pytest.mark.parametrize("year", [1900, 9998])
def test_TX_07_supported_tax_year_endpoints(year: int) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    totals = annual(book, (), TaxProfile(), year, date(min(year + 1, 9999), 2, 1), simulate=True)
    assert totals.year == year and totals.wash_window_complete


def test_TX_01_annual_rejects_mutable_income_and_non_boolean_simulation() -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    with pytest.raises(DataIntegrityError):
        annual(
            book,
            cast(tuple[TaxIncome, ...], []),
            TaxProfile(),
            2026,
            date(2027, 2, 1),
            simulate=True,
        )
    with pytest.raises(DataIntegrityError):
        annual(book, (), TaxProfile(), 2026, date(2027, 2, 1), simulate=cast(bool, 1))


def test_TX_01_annual_paper_reporting_requires_explicit_simulation() -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    with pytest.raises(DataIntegrityError):
        annual(book, (), TaxProfile(), 2026, date(2027, 2, 1))


@pytest.mark.parametrize("forgery", ["year", "cutoff"])
def test_TX_01_05_report_calendar_evidence_cannot_override_comparisons(forgery: str) -> None:
    class UntrustedYear(int):
        def __eq__(self, other: object) -> bool:
            return True

    class UntrustedCutoff(date):
        def __ge__(self, other: date) -> bool:
            return True

    book = build_tax_book(
        (fill(1, day=-500), fill(2, side=Side.SELL, day=-400, price="11")),
        (account(),),
        registry(),
        "PAPER",
    )
    clean = annual(book, (), TaxProfile(), 2026, date(2027, 1, 1), simulate=True)
    assert clean.net_st == 0 and not clean.wash_window_complete
    # A forged equality would include 2025 sales; a forged cutoff would close the wash window early.
    year = UntrustedYear(2026) if forgery == "year" else 2026
    cutoff = UntrustedCutoff(2027, 1, 1) if forgery == "cutoff" else date(2027, 1, 1)
    with pytest.raises(DataIntegrityError):
        annual(book, (), TaxProfile(), year, cutoff, simulate=True)


def test_TX_06_zero_fee_is_valid_income_evidence() -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    zero = TaxIncome(
        activity_id="fee",
        account_id="tax",
        env="PAPER",
        type="FEE",
        date=date(2026, 10, 2),
        amount=Decimal(0),
    )
    assert annual(book, (zero,), TaxProfile(), 2026, date(2027, 2, 1), simulate=True).fees == 0


def csv_records(payload: bytes) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(payload.decode(), newline=""))
    assert reader.fieldnames is not None
    return list(reader.fieldnames), list(reader)


@pytest.mark.parametrize("boxes", [("A", None), (None, "D"), ("B", "E")])
def test_TX_07_8949_rows_have_correct_term_box_status_and_wash_code(
    boxes: tuple[str | None, str | None],
) -> None:
    owner = account().model_copy(update={"form_box_st": boxes[0], "form_box_lt": boxes[1]})
    book = build_tax_book(
        (
            fill(1, day=-500, price="12"),
            fill(2, day=-100, price="8"),
            fill(3, side=Side.SELL, qty=20, price="10"),
            fill(4, day=1, qty=3, owner="ira"),
        ),
        (owner, account("ira", status=TaxStatus.IRA)),
        registry(),
        "PAPER",
    )
    _, files = render_report(
        book, (), TaxProfile(), registry(), 2026, date(2027, 2, 1), simulate=True
    )
    headers, records = csv_records(files["form8949.csv"])
    assert headers[1:-1] == [
        "account_id",
        "description",
        "date_acquired",
        "date_sold",
        "proceeds",
        "basis",
        "code",
        "adjustment",
        "gain_or_loss",
        "term",
        "box",
        "box_status",
        "permanent_disallowed",
    ]
    assert [
        (r["term"], r["code"], Decimal(r["adjustment"]), Decimal(r["permanent_disallowed"]))
        for r in records
    ] == [("LT", "W", Decimal("6"), Decimal("6")), ("ST", "", Decimal(0), Decimal(0))]
    for row in records:
        box = boxes[0] if row["term"] == "ST" else boxes[1]
        assert row["box"] == (box or "")
        assert row["box_status"] == ("OWNER_FROM_1099B" if box else "UNVERIFIED")
        assert row["account_id"] == "tax" and row["date_sold"] == "2026-10-02"


def test_TX_01_07_export_selection_filters_account_and_year_in_every_table() -> None:
    fills = (
        fill(1, day=-600),
        fill(2, side=Side.SELL, day=-500, price="11"),
        fill(3, day=-100),
        fill(4, side=Side.SELL, price="12"),
        fill(5, day=1),
        fill(6, day=-100, owner="other"),
        fill(7, side=Side.SELL, owner="other", price="13"),
        fill(8, day=1, owner="other"),
    )
    book = build_tax_book(fills, (account(), account("other")), registry(), "PAPER")
    incomes = tuple(
        TaxIncome(
            activity_id=str(i),
            account_id=owner,
            env="PAPER",
            type="INT",
            date=day,
            amount=Decimal(amount),
        )
        for i, (owner, day, amount) in enumerate(
            [
                ("tax", date(2025, 10, 2), "9"),
                ("tax", date(2026, 10, 2), "2"),
                ("other", date(2026, 10, 2), "7"),
            ]
        )
    )
    totals, files = render_report(
        book,
        incomes,
        TaxProfile(),
        registry(),
        2026,
        date(2027, 2, 1),
        account="tax",
        simulate=True,
    )
    assert (
        totals.accounts == ("tax",)
        and totals.net_st == Decimal("20")
        and totals.interest == Decimal("2")
    )
    for name in ("form8949.csv", "income.csv", "lots_open.csv"):
        _, records = csv_records(files[name])
        assert len(records) == 1 and records[0]["account_id"] == "tax"
    ih, ir = csv_records(files["income.csv"])
    assert ih[1:-1] == [
        "account_id",
        "date",
        "type",
        "amount",
        "dividend_class",
        "classification_proof_sha256",
    ]
    assert (
        ir[0]["date"] == "2026-10-02" and ir[0]["type"] == "INT" and Decimal(ir[0]["amount"]) == 2
    )
    lh, lr = csv_records(files["lots_open.csv"])
    assert lh[1:-1] == [
        "account_id",
        "symbol",
        "qty",
        "date_acquired",
        "holding_period_start",
        "basis",
        "wash_basis",
        "acquisition_id",
    ]
    assert lr[0]["symbol"] == "AAA" and lr[0]["qty"] == "10"
    sh, sr = csv_records(files["schedule_d_summary.csv"])
    assert sh.count("notice") == 1 and "accounts" not in sh
    assert Decimal(sr[0]["net_st"]) == 20 and Decimal(sr[0]["interest"]) == 2


def test_TX_01_live_exports_keep_estimate_label_and_multiple_owner_names() -> None:
    live = fill(1).model_copy(update={"env": "LIVE"})
    book = build_tax_book((live,), (account(), account("other")), registry(), "LIVE")
    _, files = render_report(book, (), TaxProfile(), registry(), 2026, date(2027, 2, 1))
    assert (
        files["README.txt"]
        .decode()
        .startswith("LIVE - ESTIMATE\n" + NOTICE + "\nOwner accounts: tax, other\n")
    )
    for name, payload in files.items():
        if name.endswith(".csv"):
            headers, records = csv_records(payload)
            assert headers[0] == "report_label [LIVE - ESTIMATE]"
            assert all(row[headers[0]] == "LIVE - ESTIMATE" for row in records)


@pytest.mark.parametrize("size,accepted", [(32 * 1024 * 1024, True), (32 * 1024 * 1024 + 1, False)])
def test_TX_07_export_payload_capacity_is_inclusive(
    tmp_path: Path, size: int, accepted: bool
) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    totals, files = render_report(
        book, (), TaxProfile(), registry(), 2026, date(2027, 2, 1), simulate=True
    )
    files["README.txt"] = b"x" * size
    if accepted:
        path = save_report(tmp_path, totals, files)
        assert (path / "README.txt").stat().st_size == size
    else:
        with exact_tax_error(
            "TX-07/10: tax report could not be safely published",
            detail="TX-07: bounded complete tax report required",
        ):
            save_report(tmp_path, totals, files)
        assert not tuple(tmp_path.iterdir())


def test_TX_07_bytearray_payload_refuses_before_publication(tmp_path: Path) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    totals, files = render_report(
        book, (), TaxProfile(), registry(), 2026, date(2027, 2, 1), simulate=True
    )
    files["README.txt"] = cast(bytes, bytearray(files["README.txt"]))
    with exact_tax_error(
        "TX-07/10: tax report could not be safely published",
        detail="TX-07: bounded complete tax report required",
    ):
        save_report(tmp_path, totals, files)
    assert not tuple(tmp_path.iterdir())


def test_TX_10_publication_paths_bind_year_account_environment_and_content(tmp_path: Path) -> None:
    book = build_tax_book((), (account(), account("other")), registry(), "PAPER")
    totals, files = render_report(
        book, (), TaxProfile(), registry(), 2026, date(2027, 2, 1), simulate=True
    )
    path = save_report(tmp_path, totals, files)
    assert path.relative_to(tmp_path).parts[:2] == ("2026", "PAPER")
    assert len(path.parent.name) == 16 and len(path.name) == 64
    # This fixed empty-book export is an audit address: retries must preserve it.
    assert path.relative_to(tmp_path).as_posix() == (
        "2026/PAPER/5642710c3fa4218c/"
        "8374f2549b1dab1a45c6fc25127deee10b4ecc00667d16e2cccf117ab0ad0509"
    )
    assert save_report(tmp_path, totals, dict(reversed(list(files.items())))) == path
    changed = {**files, "README.txt": files["README.txt"] + b"Owner reconciliation pending.\n"}
    assert save_report(tmp_path, totals, changed) != path
    assert (path / "README.txt").read_bytes() == files["README.txt"]


def test_TX_10_corrupt_existing_export_is_refused_without_reading_its_large_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    totals, files = render_report(
        book, (), TaxProfile(), registry(), 2026, date(2027, 2, 1), simulate=True
    )
    directory = save_report(tmp_path, totals, files)
    corrupt = directory / "form8949.csv"
    with corrupt.open("ab") as stream:
        stream.write(b"x" * 1024 * 1024)
    original_open = Path.open
    consumed = 0

    class ObservedReader:
        def __init__(self, stream: Any) -> None:
            self.stream = stream

        def read(self, size: int | None = -1) -> bytes:
            nonlocal consumed
            data = cast(bytes, self.stream.read(size))
            consumed += len(data)
            return data

    @contextmanager
    def observe(path: Path, *args: Any, **kwargs: Any) -> Iterator[Any]:
        with original_open(path, *args, **kwargs) as stream:
            yield ObservedReader(stream)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", observe)
        with exact_tax_error(
            "TX-07/10: tax report could not be safely published",
            detail="TX-10: existing immutable export differs",
            detail_type=DataIntegrityError,
        ):
            save_report(tmp_path, totals, files)
    # Corruption after the expected small CSV must not make memory use follow file size.
    assert consumed < 64 * 1024
    assert corrupt.stat().st_size > 1024 * 1024


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits require a POSIX filesystem")
def test_TX_10_new_export_directories_are_owner_private_under_permissive_umask(
    tmp_path: Path,
) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    totals, files = render_report(
        book, (), TaxProfile(), registry(), 2026, date(2027, 2, 1), simulate=True
    )
    root = tmp_path / "exports"
    prior = os.umask(0)
    try:
        path = save_report(root, totals, files)
    finally:
        os.umask(prior)
    assert all(
        stat.S_IMODE(directory.stat().st_mode) == 0o700
        for directory in (root, *path.parents[:4], path)
    )


@pytest.mark.parametrize("count,accepted", [(100000, True), (100001, False)])
def test_TX_06_income_capacity_is_exact_and_never_silently_truncates(
    count: int, accepted: bool
) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    row = TaxIncome(
        activity_id="first",
        account_id="tax",
        env="PAPER",
        type="INT",
        date=date(2026, 10, 2),
        amount=Decimal("0.000001"),
    )
    incomes = tuple(row.model_copy(update={"activity_id": f"int-{i}"}) for i in range(count))
    if accepted:
        totals = annual(book, incomes, TaxProfile(), 2026, date(2027, 2, 1), simulate=True)
        assert totals.interest == Decimal("0.100000")
    else:
        with pytest.raises(DataIntegrityError):
            annual(book, incomes, TaxProfile(), 2026, date(2027, 2, 1), simulate=True)


@pytest.mark.parametrize(
    "case,detail",
    [
        ("paper_mode", "TX-01: paper requires --simulate; live and paper reports stay separate"),
        ("invalid_year", "TX-01: paper requires --simulate; live and paper reports stay separate"),
        ("no_taxable_owner", "TX-01: no selected taxable account"),
        ("unknown_selection", "TX-01: no selected taxable account"),
        ("unknown_income_owner", "TX-01/06: income/fill source or date differs from the report"),
        ("future_income", "TX-01/06: income/fill source or date differs from the report"),
        ("duplicate_income", "TX-01/06: income/fill source or date differs from the report"),
        ("future_fill", "TX-01/06: income/fill source or date differs from the report"),
        ("positive_fee", "TX-06: positive fee adjustment needs verified refund attribution"),
    ],
)
def test_TX_01_06_annual_refusals_have_exact_outer_and_retained_audit_text(
    case: str, detail: str
) -> None:
    owners = (account(status=TaxStatus.IRA),) if case == "no_taxable_owner" else (account(),)
    rows = (fill(1),) if case == "future_fill" else ()
    book = build_tax_book(rows, owners, registry(), "PAPER")
    income = TaxIncome(
        activity_id="evidence",
        account_id="tax",
        env="PAPER",
        type="INT",
        date=date(2026, 10, 2),
        amount=Decimal("1"),
    )
    incomes: tuple[TaxIncome, ...] = ()
    if case == "unknown_income_owner":
        incomes = (income.model_copy(update={"account_id": "unknown"}),)
    elif case == "future_income":
        incomes = (income.model_copy(update={"date": date(2027, 2, 2)}),)
    elif case == "duplicate_income":
        incomes = (income, income)
    elif case == "positive_fee":
        incomes = (income.model_copy(update={"type": "FEE"}),)
    cutoff = date(2026, 10, 1) if case == "future_fill" else date(2027, 2, 1)
    with exact_tax_error(
        "TX-01/06..08: annual tax evidence cannot be verified",
        detail=detail,
        detail_type=DataIntegrityError if case == "positive_fee" else ValueError,
    ):
        annual(
            book,
            incomes,
            TaxProfile(),
            9999 if case == "invalid_year" else 2026,
            cutoff,
            simulate=case != "paper_mode",
            account="unknown" if case == "unknown_selection" else "all",
        )


def test_TX_02_10_export_refusal_reports_the_exact_book_mismatch() -> None:
    book = build_tax_book((fill(1),), (account(),), registry(), "PAPER")
    changed = book.lots[0].model_copy(update={"basis": Decimal("101")})
    forged = book.model_copy(update={"lots": (changed,)})
    with exact_tax_error("TX-02/10: tax book differs from verified executed accounting"):
        render_report(forged, (), TaxProfile(), registry(), 2026, date(2027, 2, 1), simulate=True)


@pytest.mark.parametrize(
    "st,lt,expected",
    [
        ("0.000000", "1.00", ("0.000000", "1.00")),
        ("-1.00", "0.000000", ("-1.00", "0.000000")),
        ("1.00", "0.000000", ("1.00", "0.000000")),
        ("0.000000", "-1.00", ("0.000000", "-1.00")),
        ("-0.00", "1.00", ("-0.00", "1.00")),
        ("1.00", "-0.00", ("1.00", "-0.00")),
    ],
)
def test_TX_06_zero_capital_term_does_not_change_other_term_or_attested_zero_text(
    st: str, lt: str, expected: tuple[str, str]
) -> None:
    # Zero has no cross-term loss to allocate. Keep each term's own exact audit text.
    result = _net_terms(Decimal(st), Decimal(lt))
    assert tuple(_cell(value) for value in result) == expected


@pytest.mark.parametrize(
    "rate,identity",
    [
        (None, "bccd60f9bbff82ea0f393bfd45e35f438369c479bfc27b58b8caf2b269cdbf96"),
        (Decimal("1E-50"), "00b4c36e2535ff6be193104f7a4527844cff58527ad5adb6c272844bf14f8341"),
    ],
)
def test_TX_10_accepted_padded_income_export_keeps_its_existing_audit_address(
    tmp_path: Path, rate: Decimal | None, identity: str
) -> None:
    book = build_tax_book((), (account(),), registry(), "PAPER")
    income = TaxIncome(
        activity_id="padded-interest",
        account_id="tax",
        env="PAPER",
        type="INT",
        date=date(2026, 10, 2),
        amount=Decimal("1." + "0" * 120),
    )
    profile = TaxProfile() if rate is None else TaxProfile(federal_st_rate=rate)
    totals, files = render_report(
        book, (income,), profile, registry(), 2026, date(2027, 2, 1), simulate=True
    )
    assert totals.interest == Decimal("1") and totals.net_capital == Decimal("0")
    assert totals.set_aside_estimate is None  # Missing LT rate still forbids an estimate.
    # Golden 09a713b export addresses pin published audit behavior, including CSV text.
    path = save_report(tmp_path, totals, files)
    assert path.name == identity
    assert save_report(tmp_path, totals, files) == path
    assert {name: (path / name).read_bytes() for name in files} == files
