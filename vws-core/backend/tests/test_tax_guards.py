"""TX/FN/PL: adversarial boundary tests for immutable accounting evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import (
    CashFlow,
    DailyPnL,
    LedgerRecord,
    SecurityEvent,
    TaxEvent,
)
from backend.core.errors import DataIntegrityError, LedgerIntegrityError
from backend.core.ledger import Ledger
from backend.data.market_calendar import MarketCalendar
from backend.domain.compliance_models import TaxLot, TaxStatus
from backend.domain.models import Side
from backend.domain.tax_profile import TaxProfile
from backend.funding.activities import parse_activity
from backend.funding.models import Activity
from backend.funding.tracker import FundingTracker
from backend.pnl.history import EquityClose, EquityHistory
from backend.pnl.models import DayInput, PnLDay, build_day, exact_ratio
from backend.pnl.stats import statistics
from backend.pnl.storage import read_days, record_day
from backend.tax import accounting
from backend.tax import service as tax_service
from backend.tax.accounting import TaxBook, _rebuild, anniversary, build_tax_book
from backend.tax.imports import (
    import_fills,
    import_marked_lots,
    load_accounts,
    read_bytes,
    read_rows,
)
from backend.tax.lots import WashSaleMatcher
from backend.tax.models import TaxAccount, TaxAccounts, TaxFill, TaxIncome, TaxSale
from backend.tax.reconcile import Broker1099, ColumnMapping, load_mapping, read_1099, reconcile
from backend.tax.reports import _cell, annual, render_report, save_report
from backend.tax.storage import ImportManifest, append_evidence, validate_record
from backend.tax.storage import read_fills as stored_fills
from backend.tests.test_accounting_service import fee_schedule, fixture, raw, state
from backend.tests.test_funding_and_pnl import activity, baseline, golden
from backend.tests.test_ledger import _all_records
from backend.tests.test_tax_accounting import account, fill
from backend.tests.test_wash_sales import ACCOUNTS, registry, sale


@pytest.mark.parametrize("value", ["wrong", "&a {symbol: symbol}\nother: *a", "[" * 21 + "]" * 21])
def test_TX_mapping_rejects_aliases_and_excessive_nesting(tmp_path: Path, value: str) -> None:
    path = tmp_path / "mapping.yaml"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        load_mapping(path)


@pytest.mark.parametrize(
    "header", ["", "symbol,symbol", "wrong", "symbol,date_sold,qty,proceeds,basis,wash,term,term"]
)
def test_TX_09_invalid_headers_never_become_empty_pass(tmp_path: Path, header: str) -> None:
    path = tmp_path / "official.csv"
    path.write_text(header + "\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        read_1099(path, mapping())


def test_TX_reconcile_filters_other_account_and_other_year() -> None:
    rows = (
        fill(1, day=-100),
        fill(2, side=Side.SELL, qty=5, price="9"),
        fill(3, day=-100, owner="other"),
        fill(4, side=Side.SELL, owner="other"),
        fill(5, day=-500),
        fill(6, side=Side.SELL, day=-400),
    )
    current = build_tax_book(rows, (account(), account("other")), registry(), "PAPER")
    differences = reconcile(current, (), 2026, "tax")
    assert len(differences) == 1 and differences[0].qty == 5


def book() -> TaxBook:
    return build_tax_book(
        (fill(1, day=-100), fill(2, side=Side.SELL, qty=5, price="9")),
        (account(),),
        registry(),
        "PAPER",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"fills": ()},
        {"accounts": (account("wrong"),)},
        {"env": "LIVE"},
        {"sales": ()},
        {"sales": (None,)},
        {"lots": (None,)},
        {"accounts": (account(), account())},
    ],
)
def test_TX_01_02_book_lineage_revalidates(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TaxBook.model_validate(book().model_copy(update=changes))


@pytest.mark.parametrize(
    "model,changes",
    [
        ("account", {"source": "CSV", "fills_csv": None}),
        ("account", {"source": "ALPACA", "fills_csv": "fills.csv"}),
        ("fill", {"is_drip": True, "side": Side.SELL}),
        ("fill", {"fees": Decimal("NaN")}),
        ("income", {"dividend_class": "qualified"}),
        ("lot", {"holding_period_start": datetime(2030, 1, 1, tzinfo=UTC)}),
        ("lot", {"wash_basis": Decimal(1000)}),
        ("sale", {"taxable_gain": Decimal(999)}),
        ("sale", {"permanent_disallowed": Decimal(999)}),
    ],
)
def test_TX_models_reject_forged_metrics(model: str, changes: dict[str, Any]) -> None:
    source = {
        "account": account(),
        "fill": fill(1),
        "income": TaxIncome(
            activity_id="div",
            account_id="tax",
            env="PAPER",
            type="DIV",
            date=date(2026, 10, 2),
            amount=Decimal(1),
        ),
        "lot": book().lots[0],
        "sale": book().sales[0],
    }[model]
    with pytest.raises(ValidationError):
        type(source).model_validate(source.model_copy(update=changes))
    with pytest.raises(DataIntegrityError):
        TaxFill.from_payload({"fill_id": "bad"})
    with pytest.raises(DataIntegrityError):
        TaxIncome.from_payload({"date": "bad"})


def test_TX_income_documented_classifications_and_defaults() -> None:
    assert account(compressed=True).lot_method == "ALPACA_COMPRESSED_FIFO"
    assert (
        TaxAccount(
            id="other",
            name="other",
            tax_status=TaxStatus.TAXABLE,
            source="CSV",
            fills_csv="fills.csv",
        ).method
        == "FIFO"
    )
    with pytest.raises(ValidationError):
        TaxAccounts(accounts=(account(), account()))
    classified = TaxIncome(
        activity_id="div",
        account_id="tax",
        env="PAPER",
        type="DIV",
        date=date(2026, 10, 2),
        amount=Decimal(1),
        dividend_class="qualified",
        classification_proof_sha256="a" * 64,
    )
    rates = TaxProfile(federal_st_rate=Decimal(".22"), federal_lt_rate=Decimal(".15"))
    assert (
        annual(book(), (classified,), rates, 2026, date(2026, 10, 2), simulate=True).dividends == 1
    )
    assert book().sales[0].realized_before_wash == Decimal(-5)
    with pytest.raises(DataIntegrityError):
        anniversary(date(9999, 1, 1))


@pytest.mark.parametrize(
    "payload",
    [
        b"x\n",
        b"date,date\n",
        b"a,b\n1\n",
        b"a,b\n1,2,3\n",
        bytes([255]),
        b"a,b\n" + b"x" * 513 + b",1\n",
    ],
)
def test_TX_owner_csv_requires_exact_bounded_columns(payload: bytes) -> None:
    with pytest.raises(DataIntegrityError):
        read_rows(payload, ("a", "b"))


def test_TX_bounded_owner_paths_and_accounts(tmp_path: Path) -> None:
    path = tmp_path / "small.csv"
    path.write_bytes(b"123")
    with pytest.raises(DataIntegrityError):
        read_bytes(path, 2)
    assert read_bytes(path, 3) == b"123"
    with pytest.raises(DataIntegrityError):
        read_bytes(tmp_path / "missing", 2)
    path.write_text("accounts: []\naccounts: []\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        load_accounts(path)


def test_TX_owner_file_growth_after_stat_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    source = tmp_path / "growing.csv"
    source.write_bytes(b"123")
    original = Path.stat

    def stale_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        result = original(self, follow_symlinks=follow_symlinks)
        if self == source:
            values = list(result)
            values[6] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", stale_stat)
    with pytest.raises(DataIntegrityError):
        read_bytes(source, 2)


def test_TX_missing_external_fill_path_cannot_be_imported(
    engine: Engine, clock: FrozenClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tax, _, _ = fixture(engine, clock, tmp_path)
    forged = account().model_copy(update={"source": "CSV", "fills_csv": None})
    monkeypatch.setattr(tax_service, "managed_accounts", lambda *args: (forged,))
    with pytest.raises(DataIntegrityError):
        tax.book()


@pytest.mark.parametrize("change", ["owner", "env", "fraction", "duplicate", "future", "drip"])
def test_TX_bad_fill_csv_is_atomic(
    engine: Engine, clock: FrozenClock, tmp_path: Path, change: str
) -> None:
    path = tmp_path / "fills.csv"
    owner = TaxAccount(
        id="tax", name="tax", tax_status=TaxStatus.TAXABLE, source="CSV", fills_csv=str(path)
    )
    record = f"one,{'wrong' if change == 'owner' else 'tax'},{'LIVE' if change == 'env' else 'PAPER'},AAA,BUY,{'1.5' if change == 'fraction' else '1'},10,0,{'2030-01-01' if change == 'future' else '2026-09-28'}T15:00:00Z,{'maybe' if change == 'drip' else 'false'}\n"
    path.write_text(
        "id,account_id,env,symbol,side,qty,price,fees,ts,is_drip\n"
        + record * (2 if change == "duplicate" else 1),
        encoding="utf-8",
    )
    ledger = Ledger(engine, clock)
    with pytest.raises(DataIntegrityError):
        import_fills(ledger, owner, path, "PAPER")
    ledger.verify_chain()


def test_TX_marked_other_account_lots_and_immutable_corrections(
    engine: Engine, clock: FrozenClock, tmp_path: Path
) -> None:
    source = tmp_path / "marks.csv"
    header = "lot_id,account_id,symbol,qty,cost_basis,acquired_at,funding_settlement_date,acquisition_trade_id,holding_period_start\n"
    source.write_text(
        header + f"{UUID(int=99)},401k,AAA,10,10.00,2026-09-28T15:00:00Z,,,\n", encoding="utf-8"
    )
    ledger = Ledger(engine, clock)
    first = import_marked_lots(ledger, source, "PAPER")
    assert len(first) == 1 and first[0].account_id == "401k"
    assert import_marked_lots(ledger, source, "PAPER") == first
    source.write_text(
        header + f"{UUID(int=99)},401k,AAA,5,10.00,2026-09-28T15:00:00Z,,,\n", encoding="utf-8"
    )
    assert import_marked_lots(ledger, source, "PAPER")[0].qty == 5
    ledger.verify_chain()
    source.write_text("bad\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        import_marked_lots(ledger, source, "PAPER")


@pytest.mark.parametrize(
    "fault",
    [
        "empty_account",
        "year",
        "paper",
        "future_income",
        "wrong_income",
        "duplicate_income",
        "future_fill",
        "fee_credit",
    ],
)
def test_TX_annual_unknown_evidence_never_becomes_totals(fault: str) -> None:
    current = book()
    income = TaxIncome(
        activity_id="div",
        account_id="tax",
        env="PAPER",
        type="DIV",
        date=date(2026, 10, 2),
        amount=Decimal(1),
    )
    inputs: dict[str, Any] = {
        "book": current,
        "incomes": (),
        "profile": TaxProfile(),
        "year": 2026,
        "as_of": date(2026, 10, 2),
        "simulate": True,
    }
    if fault == "empty_account":
        inputs["account"] = "missing"
    if fault == "year":
        inputs["year"] = 9999
    if fault == "paper":
        inputs["simulate"] = False
    if fault == "future_income":
        inputs["incomes"] = (income.model_copy(update={"date": date(2026, 10, 3)}),)
    if fault == "wrong_income":
        inputs["incomes"] = (income.model_copy(update={"env": "LIVE"}),)
    if fault == "duplicate_income":
        inputs["incomes"] = (income, income)
    if fault == "future_fill":
        inputs["as_of"] = date(2026, 10, 1)
    if fault == "fee_credit":
        inputs["incomes"] = (income.model_copy(update={"type": "FEE"}),)
    with pytest.raises(DataIntegrityError):
        annual(**inputs)


def mapping() -> ColumnMapping:
    return ColumnMapping(
        symbol="symbol",
        date_sold="date_sold",
        qty="qty",
        proceeds="proceeds",
        basis="basis",
        wash="wash",
        term="term",
    )


@pytest.mark.parametrize(
    "row",
    [
        "AAA,2026-10-02,1.5,10,10,0,ST",
        "AAA,2026-10-02,1,10,10,0,unknown",
        "AAA,bad,1,10,10,0,ST",
        "AAA,2026-10-02,1,10",
        "AAA,2026-10-02,1,10,10,0,ST,extra",
    ],
)
def test_TX_09_bad_official_csv_requires_owner_mapping(tmp_path: Path, row: str) -> None:
    path = tmp_path / "official.csv"
    path.write_text(
        "symbol,date_sold,qty,proceeds,basis,wash,term\n" + row + "\n", encoding="utf-8"
    )
    with pytest.raises(DataIntegrityError):
        read_1099(path, mapping())


def test_TX_09_unmatched_official_and_year_binding(tmp_path: Path) -> None:
    official = Broker1099(
        symbol="BBB",
        date_sold=date(2026, 10, 2),
        qty=1,
        proceeds=Decimal(10),
        basis=Decimal(10),
        wash=Decimal(0),
        term="ST",
    )
    assert {row.status for row in reconcile(book(), (official,), 2026, "tax")} == {
        "UNMATCHED_BROKER",
        "UNMATCHED_LEDGER",
    }
    with pytest.raises(DataIntegrityError):
        reconcile(book(), (official,), 2025, "tax")
    with pytest.raises(DataIntegrityError):
        reconcile(book(), (official,), 2026, "unknown")
    path = tmp_path / "mapping.yaml"
    path.write_text(
        "symbol: symbol\ndate_sold: date_sold\nqty: qty\nproceeds: proceeds\nbasis: basis\nwash: wash\nterm: term\n",
        encoding="utf-8",
    )
    assert load_mapping(path) == mapping()
    path.write_text("symbol: symbol\nsymbol: wrong\n", encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        load_mapping(path)
    with pytest.raises(ValidationError):
        ColumnMapping.model_validate(mapping().model_copy(update={"basis": "proceeds"}))


@pytest.mark.parametrize(
    "value", [True, 1.0, "NaN", "Infinity", "1e13", "1e-101", "wrong", "0" * 257]
)
def test_PL_02_ratio_rejects_nonexact_unbounded_input(value: Any) -> None:
    with pytest.raises(ValueError):
        exact_ratio(value)


@pytest.mark.parametrize(
    "change",
    [
        {"equity": Decimal(0)},
        {"cash": Decimal(0)},
        {"external_flows": Decimal(-1000)},
        {"day_pnl": Decimal(999)},
        {"source": "WRONG"},
    ],
)
def test_PL_02_revalidates_equations(clock: FrozenClock, change: dict[str, Any]) -> None:
    day = golden(clock)[0]
    with pytest.raises((ValidationError, DataIntegrityError)):
        if "day_pnl" in change or "source" in change:
            PnLDay.model_validate(day.model_copy(update=change))
        else:
            build_day(day.observation.model_copy(update=change))
    with pytest.raises(DataIntegrityError):
        PnLDay.from_payload({"observation": None})


@pytest.mark.parametrize(
    "fault", ["empty", "window", "gap", "continuity", "spy_duplicate", "spy_float", "spy_missing"]
)
def test_PL_03_unknown_series_never_returns_a_benchmark(clock: FrozenClock, fault: str) -> None:
    values = golden(clock)
    kwargs: dict[str, Any] = {}
    if fault == "empty":
        values = ()
    if fault == "gap":
        values = (values[0], values[-1])
    if fault == "continuity":
        values = (values[0], values[2])
    if fault == "spy_duplicate":
        kwargs["spy_closes"] = ((date(2026, 9, 22), Decimal(100)),) * 2
    if fault == "spy_float":
        kwargs["spy_closes"] = ((date(2026, 9, 22), 100.0),)
    if fault == "spy_missing":
        assert (
            statistics(values, "inception", MarketCalendar(), spy_closes=()).spy_price_only is None
        )
        return
    with pytest.raises(DataIntegrityError):
        statistics(
            values,
            cast(Any, "bad") if fault == "window" else "inception",
            MarketCalendar(),
            **kwargs,
        )


@pytest.mark.parametrize("fault", ["future_day", "env", "owner"])
def test_PL_04_storage_fail_closed(engine: Engine, clock: FrozenClock, fault: str) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(DataIntegrityError):
        if fault == "future_day":
            original = golden(clock)[0]
            obs = DayInput.model_validate(
                original.observation.model_copy(
                    update={"as_of": clock.now() + timedelta(seconds=1)}
                )
            )
            record_day(ledger, build_day(obs))
        else:
            read_days(
                ledger, "" if fault == "owner" else "tax", "wrong" if fault == "env" else "PAPER"
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"occurred_at": datetime(2030, 1, 1, tzinfo=UTC)},
        {"type": "FILL"},
        {"broker_order_id": UUID(int=1)},
        {"note": "bad\n"},
    ],
)
def test_FN_02_activity_shape_revalidation(clock: FrozenClock, changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Activity.model_validate(activity(clock).model_copy(update=changes))
    with pytest.raises(DataIntegrityError):
        Activity.from_payload({"date": "bad"})


@pytest.mark.parametrize("kind", ["SSP", "PTC", "UNKNOWN", "INT", "FEE"])
@pytest.mark.asyncio
async def test_FN_TX_income_unknown_and_corporate_are_evidence_only(
    engine: Engine, clock: FrozenClock, tmp_path: Path, kind: str
) -> None:
    observed = parse_activity(
        raw(kind, net_amount="-1" if kind == "FEE" else "1", symbol="AAA"),
        "tax",
        "PAPER",
        clock.now(),
        fee_schedule(),
    )
    tax, _, notices = fixture(engine, clock, tmp_path, (observed,))
    await tax.sync()
    assert "Recorded for review" in notices[0][0]
    tax.state.ledger.verify_chain()


def test_TX_10_append_session_requires_owned_transaction(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    with Session(engine) as session, pytest.raises(DataIntegrityError):
        append_evidence(ledger, "tax", "PAPER", "FILL", "one", "a" * 64, {}, session=session)
    with pytest.raises(ValidationError):
        ImportManifest(
            account_id="tax",
            env="PAPER",
            imported_at=clock.now(),
            fills=(UUID(int=1), UUID(int=1)),
            source_sha256="a" * 64,
        )
    with pytest.raises(DataIntegrityError):
        ImportManifest.from_payload({"imported_at": clock.now().isoformat(), "fills": None})


def test_TX_export_does_not_accept_forged_aggregate_or_unsafe_names(tmp_path: Path) -> None:
    current = book()
    sale = TaxSale.model_validate(
        current.sales[0].model_copy(
            update={"basis": Decimal(49), "economic_gain": Decimal(-4), "taxable_gain": Decimal(-4)}
        )
    )
    forged = TaxBook.model_validate(current.model_copy(update={"sales": (sale,)}))
    with pytest.raises(DataIntegrityError):
        render_report(forged, (), TaxProfile(), registry(), 2026, date(2026, 10, 2), simulate=True)
    assert _cell("=formula") == "'=formula" and _cell(None) == "" and _cell(Decimal(-5)) == "-5"
    totals, files = render_report(
        current, (), TaxProfile(), registry(), 2026, date(2026, 10, 2), simulate=True
    )
    with pytest.raises(DataIntegrityError):
        save_report(tmp_path, totals, {"unexpected.csv": b"x"})
    directory = save_report(tmp_path, totals, files)
    (directory / "income.csv").write_bytes(b"corrupted")
    with pytest.raises(DataIntegrityError):
        save_report(tmp_path, totals, files)


@pytest.mark.parametrize(
    "model,change",
    [
        (CashFlow, "owner"),
        (CashFlow, "future"),
        (CashFlow, "effect"),
        (DailyPnL, "owner"),
        (DailyPnL, "future"),
        (DailyPnL, "supersedes"),
        (TaxEvent, "owner"),
        (TaxEvent, "future"),
        (TaxEvent, "supersedes"),
        (TaxEvent, "unknown"),
    ],
)
def test_TX_storage_rechecks_detached_columns_and_correction_lineage(
    engine: Engine,
    clock: FrozenClock,
    model: type[LedgerRecord],
    change: str,
) -> None:
    ledger = Ledger(engine, clock)
    records = _all_records(ledger, clock)
    key = records[model].id
    with Session(engine) as session:
        record: Any = session.get(model, key)
        assert record is not None
        session.expunge(record)
    if change == "owner":
        record.account_id = "wrong"
    elif change == "future":
        record.created_at = clock.now() - timedelta(days=1000)
    elif change == "effect":
        record.baseline_effect = "SCALED"
    elif change == "supersedes":
        record.supersedes = UUID(int=9)
    elif change == "unknown":
        record.kind = "UNKNOWN"
    with Session(engine) as session, pytest.raises(LedgerIntegrityError):
        validate_record(session, record)
    ledger.verify_chain()


def test_TX_same_execution_cannot_change_price_or_clock() -> None:
    # Two valid lot slices must describe the same original broker SELL.
    first = sale(1)
    second = sale(2)
    first = first.model_copy(update={"execution_id": UUID(int=99)})
    second = second.model_copy(update={"execution_id": UUID(int=99), "price": Decimal(99)})
    with pytest.raises(DataIntegrityError):
        WashSaleMatcher(registry()).adjustments((first, second), ACCOUNTS)
    with pytest.raises(ValidationError):
        type(first).model_validate(
            first.model_copy(
                update={"side": Side.BUY, "realized_loss": Decimal(0), "execution_id": UUID(int=1)}
            )
        )


@pytest.mark.parametrize(
    "fault", ["missing_execution", "missing_interval", "rows", "interval_bound", "convergence"]
)
def test_TX_05_impossible_allocations_and_bounded_rebuild_fail_closed(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    rows = (fill(1, day=-1), fill(2, side=Side.SELL, qty=5, price="9"))
    current = build_tax_book(rows, (account(),), registry(), "PAPER")
    candidate = WashSaleMatcher(registry()).allocations(current.history, (account().ownership,))
    assert candidate
    if fault in {"missing_execution", "missing_interval"}:
        history = (
            tuple(
                row.model_copy(update={"execution_id": None}) if row.side == Side.SELL else row
                for row in current.history
            )
            if fault == "missing_execution"
            else current.history
        )
        allocations = (
            candidate
            if fault == "missing_execution"
            else tuple((adjustment, ()) for adjustment, _ in candidate)
        )
        with pytest.raises(DataIntegrityError):
            _rebuild(rows, {"tax": account()}, allocations, history, {rows[0].fill_id: {0, 5, 10}})
    else:
        if fault == "rows":
            monkeypatch.setattr(accounting, "MAX_ACCOUNTING_ROWS", 1)
        elif fault == "interval_bound":
            monkeypatch.setattr(accounting, "MAX_ACCOUNTING_ROWS", 2)
            rows = (fill(1, day=-1), fill(2))
        else:
            monkeypatch.setattr(accounting, "MAX_WASH_PASSES", 1)
        with pytest.raises(DataIntegrityError):
            build_tax_book(rows, (account(),), registry(), "PAPER")


@pytest.mark.parametrize("fault", ["missing_baseline", "scaled_amount"])
def test_FN_storage_refuses_unbound_external_scaling(
    engine: Engine, clock: FrozenClock, fault: str
) -> None:
    st = state(engine, clock)
    baseline(st.ledger)
    recorded, _ = FundingTracker(st, "tax", "PAPER").record(activity(clock))
    with Session(engine) as session:
        row = session.get(CashFlow, recorded.id)
        assert row is not None
        session.expunge(row)
    if fault == "missing_baseline":
        row.portfolio_state_id = None
    else:
        changed = activity(clock, amount="101")
        row.amount, row.payload = changed.amount, changed.model_dump(mode="json")
    with Session(engine) as session, pytest.raises(LedgerIntegrityError):
        validate_record(session, row)
    st.ledger.verify_chain()


@pytest.mark.parametrize("kind", ["INCOME", "IMPORT", "CORPORATE_ACTION", "MARKED_LOT"])
def test_TX_storage_rejects_future_kind_specific_evidence(
    engine: Engine, clock: FrozenClock, kind: str
) -> None:
    ledger = Ledger(engine, clock)
    if kind == "INCOME":
        payload = TaxIncome(
            activity_id="one",
            account_id="tax",
            env="PAPER",
            type="DIV",
            date=clock.now().date(),
            amount=Decimal(1),
        ).model_dump(mode="json")
        identity = "one"
    elif kind == "IMPORT":
        payload = ImportManifest(
            account_id="tax", env="PAPER", imported_at=clock.now(), fills=(), source_sha256="a" * 64
        ).model_dump(mode="json")
        identity = "CSV_IMPORT"
    elif kind == "CORPORATE_ACTION":
        observed = parse_activity(raw("SSP"), "tax", "PAPER", clock.now(), fee_schedule())
        payload, identity = observed.model_dump(mode="json"), observed.activity_id
    else:
        marked = TaxLot(
            lot_id=UUID(int=7),
            account_id="tax",
            symbol="AAA",
            qty=1,
            cost_basis=Decimal(10),
            acquired_at=clock.now(),
            funding_settlement_date=clock.now().date(),
            holding_period_start=clock.now(),
        )
        payload, identity = marked.model_dump(mode="json"), str(marked.lot_id)
    digest = str(payload.get("payload_sha256", "a" * 64))
    row = append_evidence(ledger, "tax", "PAPER", kind, identity, digest, payload)
    with Session(engine) as session:
        detached = session.get(TaxEvent, row.id)
        assert detached is not None
        session.expunge(detached)
    detached.created_at = clock.now() - timedelta(days=2)
    with Session(engine) as session, pytest.raises(LedgerIntegrityError):
        validate_record(session, detached)
    ledger.verify_chain()


def test_TX_storage_missing_manifest_fills_and_unsupported_record(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    manifest = ImportManifest(
        account_id="tax",
        env="PAPER",
        imported_at=clock.now(),
        fills=(UUID(int=99),),
        source_sha256="a" * 64,
    )
    with pytest.raises(LedgerIntegrityError):
        append_evidence(
            ledger,
            "tax",
            "PAPER",
            "IMPORT",
            "CSV_IMPORT",
            "a" * 64,
            manifest.model_dump(mode="json"),
        )
    with pytest.raises(DataIntegrityError):
        stored_fills(ledger, "tax", "PAPER", csv=True)
    record = ledger.append(SecurityEvent, kind="PUBLIC_FIXTURE", detail={})
    with Session(engine) as session, pytest.raises(LedgerIntegrityError):
        validate_record(session, record)
    ledger.verify_chain()


@pytest.mark.parametrize("fault", ["duplicate", "reversed", "future"])
def test_PL_history_model_rejects_overwriting_or_future_points(
    clock: FrozenClock, fault: str
) -> None:
    days: tuple[date, ...] = (date(2026, 9, 28), date(2026, 9, 29))
    if fault == "duplicate":
        days = (days[0], days[0])
    elif fault == "reversed":
        days = tuple(reversed(days))
    else:
        days = (date(2030, 1, 1),)
    with pytest.raises(ValidationError):
        EquityHistory(
            account_id="tax",
            env="PAPER",
            as_of=clock.now(),
            sha256="a" * 64,
            closes=tuple(EquityClose(session=day, equity=Decimal(100)) for day in days),
        )


def test_PL_same_observation_later_read_is_not_a_correction(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    day = golden(clock)[0]
    first = record_day(ledger, day)
    ledger.clock = FrozenClock(clock.now() + timedelta(seconds=1))
    later = build_day(day.observation.model_copy(update={"as_of": ledger.clock.now()}))
    assert record_day(ledger, later).id == first.id
    assert len(read_days(ledger, "tax", "PAPER")) == 1
    ledger.verify_chain()


@pytest.mark.parametrize("quantity", ["0", "1000000001", "1.5", "١", "1"])
def test_TX_marked_lots_bound_owner_shares_and_dates(
    engine: Engine, clock: FrozenClock, tmp_path: Path, quantity: str
) -> None:
    source = tmp_path / "marks.csv"
    source.write_text(
        "lot_id,account_id,symbol,qty,cost_basis,acquired_at,funding_settlement_date,acquisition_trade_id,holding_period_start\n"
        + f"{UUID(int=3)},other,AAA,{quantity},10.00,2030-01-01T15:00:00Z,,,\n",
        encoding="utf-8",
    )
    ledger = Ledger(engine, clock)
    with pytest.raises(DataIntegrityError):
        import_marked_lots(ledger, source, "PAPER")
    with pytest.raises(DataIntegrityError):
        import_marked_lots(ledger, source, cast(Any, "unknown"))
    ledger.verify_chain()
