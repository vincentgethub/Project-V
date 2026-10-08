"""TX-06..08/10: annual record-keeping estimates; 1099-B remains authoritative."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path

from pydantic import Field

from backend.core.errors import DataIntegrityError
from backend.data.history import canonical_bytes
from backend.domain.compliance_models import TaxStatus
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import FrozenModel, Money
from backend.domain.tax_profile import TaxProfile
from backend.ops.anchors import controlled_path
from backend.tax.accounting import TaxBook, build_tax_book
from backend.tax.lots import trade_day
from backend.tax.models import NOTICE, SIMULATED, TaxIncome


class AnnualTax(FrozenModel):
    year: int = Field(strict=True, ge=1900, le=9998)
    env: str = Field(pattern=r"^(PAPER|LIVE)$")
    accounts: tuple[str, ...] = Field(min_length=1, max_length=1000)
    net_st: Money
    net_lt: Money
    offset_st: Money
    offset_lt: Money
    net_capital: Money
    loss_deduction_limit: Money
    loss_deduction_estimate: Money = Field(ge=0)
    carryover_st_estimate: Money = Field(ge=0)
    carryover_lt_estimate: Money = Field(ge=0)
    wash_disallowed: Money = Field(ge=0)
    permanent_disallowed: Money = Field(ge=0)
    dividends: Money
    interest: Money
    fees: Money = Field(ge=0)
    set_aside_estimate: Money | None = Field(default=None, ge=0)
    wash_window_complete: bool = Field(strict=True)
    notice: str = NOTICE


def _net_terms(st: Decimal, lt: Decimal) -> tuple[Decimal, Decimal]:
    offset = min(abs(st), abs(lt)) if (st < 0 < lt or lt < 0 < st) else Decimal(0)
    return st + offset if st < 0 else st - offset, lt + offset if lt < 0 else lt - offset


def annual(
    book: TaxBook,
    incomes: tuple[TaxIncome, ...],
    profile: TaxProfile,
    year: int,
    as_of: date,
    *,
    account: str = "all",
    simulate: bool = False,
) -> AnnualTax:
    try:
        checked, rates = TaxBook.model_validate(book), TaxProfile.model_validate(profile)
        if (
            type(year) is not int
            or not 1900 <= year <= 9998
            or type(as_of) is not date
            or type(simulate) is not bool
            or (checked.env == "PAPER") != simulate
            or not isinstance(incomes, tuple)
            or len(incomes) > 100000
        ):
            raise ValueError(
                "TX-01: paper requires --simulate; live and paper reports stay separate"
            )
        owners = {row.id for row in checked.accounts}
        selected = tuple(
            row.id
            for row in checked.accounts
            if row.tax_status == TaxStatus.TAXABLE and account in {"all", row.id}
        )
        if not selected:
            raise ValueError("TX-01: no selected taxable account")
        observed = tuple(TaxIncome.model_validate(row) for row in incomes)
        if (
            len({(row.account_id, row.activity_id) for row in observed}) != len(observed)
            or any(
                row.account_id not in owners or row.env != checked.env or row.date > as_of
                for row in observed
            )
            or any(trade_day(row.ts) > as_of for row in checked.fills)
        ):
            raise ValueError("TX-01/06: income/fill source or date differs from the report")
        sales = tuple(
            row
            for row in checked.sales
            if row.account_id in selected and trade_day(row.sold_at).year == year
        )
        income = tuple(
            row for row in observed if row.account_id in selected and row.date.year == year
        )
        if any(row.type == "FEE" and row.amount > 0 for row in income):
            raise DataIntegrityError(
                "TX-06: positive fee adjustment needs verified refund attribution"
            )
        with localcontext() as precision:
            precision.prec = 80
            st = sum((row.taxable_gain for row in sales if row.term == "ST"), Decimal(0))
            lt = sum((row.taxable_gain for row in sales if row.term == "LT"), Decimal(0))
            offset_st, offset_lt = _net_terms(st, lt)
            limit = Decimal(1500 if rates.filing_status == "married_filing_separately" else 3000)
            deduction = min(limit, max(Decimal(0), -st - lt))
            remaining = deduction
            st_loss, lt_loss = max(-offset_st, Decimal(0)), max(-offset_lt, Decimal(0))
            carry_st = st_loss - min(st_loss, remaining)
            remaining -= min(st_loss, remaining)
            carry_lt = lt_loss - min(lt_loss, remaining)
            dividends = sum(
                (row.amount for row in income if row.type.startswith("DIV")), Decimal(0)
            )
            interest = sum((row.amount for row in income if row.type.startswith("INT")), Decimal(0))
            fees = sum((abs(row.amount) for row in income if row.type == "FEE"), Decimal(0))
            estimate = None
            if rates.estimate_available:
                fed_st, fed_lt, state, niit = tuple(
                    rate
                    for rate in (
                        rates.federal_st_rate,
                        rates.federal_lt_rate,
                        rates.state_rate,
                        rates.niit_rate,
                    )
                    if rate is not None
                )
                ordinary = interest + sum(
                    (
                        row.amount
                        for row in income
                        if row.type.startswith("DIV")
                        and row.dividend_class in {"unclassified", "nonqualified"}
                    ),
                    Decimal(0),
                )
                qualified = sum(
                    (
                        row.amount
                        for row in income
                        if row.type.startswith("DIV") and row.dividend_class == "qualified"
                    ),
                    Decimal(0),
                )
                estimate = (
                    max(Decimal(0), st) * (fed_st + state + niit)
                    + max(Decimal(0), lt) * (fed_lt + state + niit)
                    + max(ordinary, Decimal(0)) * (fed_st + state + niit)
                    + max(qualified, Decimal(0)) * (fed_lt + state + niit)
                ).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
            return AnnualTax(
                year=year,
                env=checked.env,
                accounts=selected,
                net_st=st,
                net_lt=lt,
                offset_st=offset_st,
                offset_lt=offset_lt,
                net_capital=st + lt,
                loss_deduction_limit=limit,
                loss_deduction_estimate=deduction,
                carryover_st_estimate=carry_st,
                carryover_lt_estimate=carry_lt,
                wash_disallowed=sum((row.wash_disallowed for row in sales), Decimal(0)),
                permanent_disallowed=sum((row.permanent_disallowed for row in sales), Decimal(0)),
                dividends=dividends,
                interest=interest,
                fees=fees,
                set_aside_estimate=estimate,
                wash_window_complete=as_of >= date(year, 12, 31) + timedelta(days=30),
            )
    except Exception:
        raise DataIntegrityError("TX-01/06..08: annual tax evidence cannot be verified") from None


def _cell(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _csv(columns: tuple[str, ...], rows: tuple[tuple[object, ...], ...], label: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow((f"report_label [{label}]", *columns, "notice"))
    for row in rows:
        writer.writerow(tuple(_cell(value) for value in (label, *row, NOTICE)))
    return output.getvalue().encode("utf-8")


def render_report(
    book: TaxBook,
    incomes: tuple[TaxIncome, ...],
    profile: TaxProfile,
    registry: InstrumentRegistry,
    year: int,
    as_of: date,
    *,
    account: str = "all",
    simulate: bool = False,
) -> tuple[AnnualTax, dict[str, bytes]]:
    # Rebuild at the export boundary: forged/mismatched totals cannot be exported.
    checked = TaxBook.model_validate(book)
    rebuilt = build_tax_book(checked.fills, checked.accounts, registry, checked.env)
    if rebuilt != checked:
        raise DataIntegrityError("TX-02/10: tax book differs from verified executed accounting")
    summary = annual(rebuilt, incomes, profile, year, as_of, account=account, simulate=simulate)
    label = SIMULATED if simulate else "LIVE - ESTIMATE"
    owners = {row.id: row for row in rebuilt.accounts}
    sales = tuple(
        row
        for row in rebuilt.sales
        if row.account_id in summary.accounts and trade_day(row.sold_at).year == year
    )
    form = tuple(
        (
            row.account_id,
            f"{row.qty} {row.symbol}",
            trade_day(row.acquired_at),
            trade_day(row.sold_at),
            row.proceeds,
            row.basis,
            "W" if row.wash_disallowed else None,
            row.wash_disallowed,
            row.taxable_gain,
            row.term,
            owners[row.account_id].form_box_st
            if row.term == "ST"
            else owners[row.account_id].form_box_lt,
            "UNVERIFIED"
            if (
                owners[row.account_id].form_box_st
                if row.term == "ST"
                else owners[row.account_id].form_box_lt
            )
            is None
            else "OWNER_FROM_1099B",
            row.permanent_disallowed,
        )
        for row in sales
    )
    income = tuple(
        (
            row.account_id,
            row.date,
            row.type,
            row.amount,
            row.dividend_class,
            row.classification_proof_sha256,
        )
        for row in incomes
        if row.account_id in summary.accounts and row.date.year == year
    )
    lots = tuple(
        (
            row.account_id,
            row.symbol,
            row.qty,
            trade_day(row.acquired_at),
            trade_day(row.holding_period_start),
            row.basis,
            row.wash_basis,
            row.acquisition_id,
        )
        for row in rebuilt.lots
        if row.account_id in summary.accounts
    )
    columns = tuple(name for name in AnnualTax.model_fields if name not in {"accounts", "notice"})
    values = tuple(summary.model_dump(mode="python")[name] for name in columns)
    # VERIFY: https://www.irs.gov/instructions/i8949 (2025 published instructions).
    # VERIFY: https://www.irs.gov/publications/p550 (ST losses used first).
    disclaimer = f"{label}\n{NOTICE}\nOwner accounts: {', '.join(summary.accounts)}\nExact book SHA256: {rebuilt.sha256}\n1099-B form boxes are UNVERIFIED until entered from broker reporting.\nCarryover and loss deduction are estimates of the maximum permitted amount; taxable-income limits and previous-year carryovers require professional reconciliation.\nWash replacement window: {'complete through the required date' if summary.wash_window_complete else 'still open; future purchases may change losses'}.\nModeled fill fees remain estimates until broker fee evidence is reconciled.\nOpen lots are as of the supplied evidence date, not a fabricated year-end snapshot.\n"
    files = {
        "form8949.csv": _csv(
            (
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
            ),
            form,
            label,
        ),
        "schedule_d_summary.csv": _csv(columns, (values,), label),
        "income.csv": _csv(
            (
                "account_id",
                "date",
                "type",
                "amount",
                "dividend_class",
                "classification_proof_sha256",
            ),
            income,
            label,
        ),
        "lots_open.csv": _csv(
            (
                "account_id",
                "symbol",
                "qty",
                "date_acquired",
                "holding_period_start",
                "basis",
                "wash_basis",
                "acquisition_id",
            ),
            lots,
            label,
        ),
        "README.txt": disclaimer.encode("utf-8"),
    }
    return summary, files


def save_report(root: Path, summary: AnnualTax, files: dict[str, bytes]) -> Path:
    """Account/environment/content-separated write-once reports, all under YYYY."""
    try:
        bound = AnnualTax.model_validate(summary)
        names = {
            "form8949.csv",
            "schedule_d_summary.csv",
            "income.csv",
            "lots_open.csv",
            "README.txt",
        }
        if set(files) != names or any(
            not isinstance(value, bytes) or len(value) > 32 * 1024 * 1024
            for value in files.values()
        ):
            raise ValueError("TX-07: bounded complete tax report required")
        identity = hashlib.sha256(
            canonical_bytes(bound) + b"".join(files[name] for name in sorted(files))
        ).hexdigest()
        accounts = hashlib.sha256("\n".join(bound.accounts).encode("utf-8")).hexdigest()[:16]
        directory = controlled_path(root)
        directory.mkdir(exist_ok=True, mode=0o700)
        for part in (str(bound.year), bound.env, accounts, identity):
            directory = controlled_path(directory / part)
            directory.mkdir(exist_ok=True, mode=0o700)
        for name in sorted(names):
            destination = controlled_path(directory / name)
            payload = files[name]
            if destination.exists():
                with destination.open("rb") as stream:
                    if stream.read(len(payload) + 1) != payload:
                        raise DataIntegrityError("TX-10: existing immutable export differs")
            else:
                with destination.open("xb") as stream:
                    stream.write(payload)
        return directory
    except Exception:
        raise DataIntegrityError("TX-07/10: tax report could not be safely published") from None
