"""TX-07/09: explicit host exports from immutable evidence; no network calls."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.database import SecurityEvent, TaxEvent
from backend.core.errors import DataIntegrityError
from backend.domain.instruments import InstrumentRegistry
from backend.ops.anchors import controlled_path
from backend.tax.accounting import TaxBook, build_tax_book
from backend.tax.imports import import_fills
from backend.tax.models import Environment, TaxFill, TaxIncome
from backend.tax.reconcile import load_mapping, read_1099, reconcile, reconciliation_csv, summary
from backend.tax.reports import AnnualTax, render_report, save_report
from backend.tax.service import managed_accounts
from backend.tax.storage import read_fills
from vws.security_cli import SecurityContext


def _instant(payload: dict[str, object], field: str) -> datetime:
    try:
        value = payload[field]
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError("bounded UTC accounting time required")
        return ensure_utc(datetime.fromisoformat(value))
    except Exception:
        raise DataIntegrityError("TX-10: accounting checkpoint time is UNVERIFIED") from None


def evidence(
    context: SecurityContext, project: Path, env: Environment
) -> tuple[TaxBook, tuple[TaxIncome, ...], datetime]:
    context.ledger.verify_chain()
    with Session(context.engine) as session:
        full = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "TAX_FULL_HISTORY_CAPTURED",
                SecurityEvent.detail["cohort"].as_string() == env,
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if full is None:
            raise DataIntegrityError(
                "TX-01: complete bound account history is UNVERIFIED; run the configured read-only accounting cycle first"
            )
        account_id = full.detail["account_id"]
        checkpoint = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "ACCOUNT_ACTIVITIES_CAPTURED",
                SecurityEvent.detail["account_id"].as_string() == account_id,
                SecurityEvent.detail["cohort"].as_string() == env,
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if checkpoint is None:
            raise DataIntegrityError("TX-01: activity checkpoint is unavailable")
        through = _instant(checkpoint.detail, "until")
        if through > checkpoint.ts or through > context.ledger.clock.now():
            raise DataIntegrityError("TX-10: account history checkpoint is in the future")
        verified = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "J_ACCOUNTING_VERIFIED",
                SecurityEvent.detail["account_id"].as_string() == account_id,
                SecurityEvent.detail["cohort"].as_string() == env,
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if verified is None or verified.seq <= checkpoint.seq:
            raise DataIntegrityError("TX-01: successful bound account reconciliation is UNVERIFIED")
        verified_as_of = _instant(verified.detail, "as_of")
        if (
            not timedelta(0) <= through - verified_as_of <= timedelta(seconds=30)
            or verified_as_of > verified.ts
        ):
            raise DataIntegrityError("TX-01: account reconciliation checkpoint differs")
        verified_book_sha256 = verified.detail["book_sha256"]
    owners = managed_accounts(project, account_id, context.settings.broker_state_source)
    fills: list[TaxFill] = []
    for owner in owners:
        if owner.source == "CSV":
            if owner.fills_csv is None:
                raise DataIntegrityError("TX-01: owner CSV is UNVERIFIED")
            supplied = Path(owner.fills_csv)
            import_fills(
                context.ledger,
                owner,
                supplied if supplied.is_absolute() else project / supplied,
                env,
            )
        fills.extend(read_fills(context.ledger, owner.id, env, csv=owner.source == "CSV"))
    book = build_tax_book(
        tuple(fills), owners, InstrumentRegistry.from_csv(project / "config"), env
    )
    if book.sha256 != verified_book_sha256:
        raise DataIntegrityError(
            "TX-01: changed accounting evidence needs a verified read-only cycle"
        )
    with Session(context.engine) as session:
        rows = tuple(
            session.scalars(
                select(TaxEvent)
                .where(
                    TaxEvent.kind == "INCOME",
                    TaxEvent.env == env,
                    TaxEvent.account_id.in_(tuple(owner.id for owner in owners)),
                )
                .order_by(TaxEvent.seq)
            )
        )
    income = {(row.account_id, row.source_id): TaxIncome.from_payload(row.payload) for row in rows}
    return book, tuple(income.values()), through


def report(
    context: SecurityContext, project: Path, year: int, account: str, simulate: bool
) -> tuple[AnnualTax, Path]:
    env: Environment = "PAPER" if simulate else "LIVE"
    book, income, through = evidence(context, project, env)
    totals, files = render_report(
        book,
        income,
        context.settings.tax_profile,
        InstrumentRegistry.from_csv(project / "config"),
        year,
        through.date(),
        account=account,
        simulate=simulate,
    )
    root = controlled_path(project / "data/tax")
    root.mkdir(exist_ok=True, mode=0o700)
    destination = save_report(root, totals, files)
    context.ledger.append(
        SecurityEvent,
        kind="TAX_REPORT_EXPORTED",
        detail={
            "year": year,
            "account_ids": totals.accounts,
            "cohort": env,
            "book_sha256": book.sha256,
            "path": str(destination),
            "notice": totals.notice,
        },
    )
    return totals, destination


def reconcile_broker(
    context: SecurityContext, project: Path, year: int, official: Path, mapping: Path
) -> tuple[Path, str]:
    book, _income, _through = evidence(context, project, "LIVE")
    primary = tuple(owner.id for owner in book.accounts if owner.source == "ALPACA")
    if len(primary) != 1:
        raise DataIntegrityError("TX-09: one bound managed account is required")
    verified = load_mapping(mapping)
    rows = reconcile(book, read_1099(official, verified), year, primary[0])
    payload = reconciliation_csv(rows)
    identity = hashlib.sha256(book.sha256.encode("ascii") + payload).hexdigest()
    root = controlled_path(project / "data/tax")
    root.mkdir(exist_ok=True, mode=0o700)
    for name in (
        str(year),
        "LIVE",
        hashlib.sha256(primary[0].encode("utf-8")).hexdigest()[:16],
        identity,
    ):
        root = controlled_path(root / name)
        root.mkdir(exist_ok=True, mode=0o700)
    destination = controlled_path(root / f"reconcile_{year}.csv")
    if destination.exists():
        with destination.open("rb") as stream:
            if stream.read(len(payload) + 1) != payload:
                raise DataIntegrityError("TX-10: existing reconciliation export differs")
    else:
        with destination.open("xb") as stream:
            stream.write(payload)
    result = summary(rows)
    context.ledger.append(
        SecurityEvent,
        kind="TAX_1099_RECONCILED",
        detail={
            "year": year,
            "account_id": primary[0],
            "cohort": "LIVE",
            "book_sha256": book.sha256,
            "export_sha256": hashlib.sha256(payload).hexdigest(),
            "path": str(destination),
            "summary": result,
        },
    )
    return destination, result
