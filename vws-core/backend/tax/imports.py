"""TX-01/02/10: owner CSV evidence; never logs into another account."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5

from backend.core.config import load_exact_yaml
from backend.core.database import transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.history import canonical_bytes
from backend.domain.compliance_models import TaxLot
from backend.funding.activities import ACTIVITY_IDENTITY
from backend.tax.models import Environment, TaxAccount, TaxAccounts, TaxFill
from backend.tax.storage import ImportManifest, append_evidence

FILL_COLUMNS = (
    "id",
    "account_id",
    "env",
    "symbol",
    "side",
    "qty",
    "price",
    "fees",
    "ts",
    "is_drip",
)


def read_bytes(path: Path, limit: int) -> bytes:
    try:
        direct = path.absolute()
        if direct.is_symlink() or direct.resolve() != direct or direct.stat().st_size > limit:
            raise ValueError("bounded direct owner input required")
        with direct.open("rb") as stream:
            value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError("input exceeded its bound")
        return value
    except Exception:
        raise DataIntegrityError("TX/FN: owner input cannot be safely read") from None


def read_rows(payload: bytes, columns: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
        if (
            reader.fieldnames is None
            or len(reader.fieldnames) != len(columns)
            or set(reader.fieldnames) != set(columns)
        ):
            raise ValueError("explicit exact CSV columns required")
        rows: list[dict[str, str]] = []
        for row in reader:
            if (
                len(rows) >= 100000
                or set(row) != set(columns)
                or any(not isinstance(row[name], str) or len(row[name]) > 512 for name in columns)
            ):
                raise ValueError("bounded exact CSV row required")
            rows.append(row)
        return tuple(rows)
    except Exception:
        raise DataIntegrityError("TX/FN: CSV columns or rows cannot be verified") from None


def load_accounts(path: Path) -> TaxAccounts:
    try:
        return TaxAccounts.model_validate(load_exact_yaml(path))
    except Exception:
        raise DataIntegrityError("TX-01: owner accounts configuration is unverifiable") from None


def read_fills(
    path: Path, account: TaxAccount, env: Environment
) -> tuple[tuple[TaxFill, ...], str]:
    try:
        owner = TaxAccount.model_validate(account)
        payload = read_bytes(path, 16 * 1024 * 1024)
        output: list[TaxFill] = []
        for raw in read_rows(payload, FILL_COLUMNS):
            if (
                raw["account_id"] != owner.id
                or raw["env"] != env
                or raw["is_drip"] not in {"true", "false"}
            ):
                raise ValueError("TX-01: CSV account/environment/DRIP differs")
            quantity = Decimal(raw["qty"])
            if (
                not quantity.is_finite()
                or quantity != quantity.to_integral_value()
                or not 0 < quantity <= 10**9
            ):
                raise ValueError("TX-02: positive whole-share acquisition/disposal required")
            digest = hashlib.sha256(
                "\n".join(raw[name] for name in FILL_COLUMNS).encode("utf-8")
            ).hexdigest()
            output.append(
                TaxFill.model_validate(
                    {
                        "fill_id": uuid5(ACTIVITY_IDENTITY, f"{owner.id}/{env}/{raw['id']}"),
                        "activity_id": raw["id"],
                        "account_id": owner.id,
                        "env": env,
                        "symbol": raw["symbol"],
                        "side": raw["side"],
                        "qty": int(quantity),
                        "price": Decimal(raw["price"]),
                        "fees": Decimal(raw["fees"]),
                        "ts": datetime.fromisoformat(raw["ts"]),
                        "is_drip": raw["is_drip"] == "true",
                        "fee_source": "CSV",
                        "payload_sha256": digest,
                    }
                )
            )
        if len({row.activity_id for row in output}) != len(output):
            raise ValueError("TX-10: import repeats an activity ID")
        return tuple(output), hashlib.sha256(payload).hexdigest()
    except Exception:
        raise DataIntegrityError("TX-01/02: owner CSV fills cannot be verified") from None


def import_fills(
    ledger: Ledger, account: TaxAccount, path: Path, env: Environment
) -> ImportManifest:
    fills, digest = read_fills(path, account, env)
    if any(row.ts > ledger.clock.now() for row in fills):
        raise DataIntegrityError("TX-10: import includes future fills")
    manifest = ImportManifest(
        account_id=account.id,
        env=env,
        imported_at=ledger.clock.now(),
        fills=tuple(row.fill_id for row in fills),
        source_sha256=digest,
    )
    ledger.verify_chain()
    with transaction(ledger.engine) as session:
        for row in fills:
            append_evidence(
                ledger,
                row.account_id,
                row.env,
                "FILL",
                row.activity_id,
                row.payload_sha256,
                row.model_dump(mode="json"),
                session=session,
            )
        append_evidence(
            ledger,
            account.id,
            env,
            "IMPORT",
            "CSV_IMPORT",
            digest,
            manifest.model_dump(mode="json"),
            session=session,
        )
    return manifest


def import_marked_lots(ledger: Ledger, path: Path, env: Environment) -> tuple[TaxLot, ...]:
    """Owner-marked other-account lots, including 401(k), without guessing tax status.

    cost_basis is per share, as in the shared CMP model. Reimporting a corrected
    lot appends a new version. This is awareness evidence, not a fabricated fill.
    """
    try:
        if env not in {"PAPER", "LIVE"}:
            raise ValueError("TX: explicit marked-lot environment required")
        columns = (
            "lot_id",
            "account_id",
            "symbol",
            "qty",
            "cost_basis",
            "acquired_at",
            "funding_settlement_date",
            "acquisition_trade_id",
            "holding_period_start",
        )
        rows = read_rows(read_bytes(path, 16 * 1024 * 1024), columns)
        if any(
            not row["qty"].isascii() or not row["qty"].isdigit() or not 0 < int(row["qty"]) <= 10**9
            for row in rows
        ):
            raise ValueError("TX: bounded positive whole-share marked lot required")
        output = tuple(
            TaxLot(
                lot_id=UUID(row["lot_id"]),
                account_id=row["account_id"],
                symbol=row["symbol"],
                qty=int(row["qty"]),
                cost_basis=Decimal(row["cost_basis"]),
                acquired_at=datetime.fromisoformat(row["acquired_at"]),
                funding_settlement_date=None
                if not row["funding_settlement_date"]
                else date.fromisoformat(row["funding_settlement_date"]),
                acquisition_trade_id=None
                if not row["acquisition_trade_id"]
                else UUID(row["acquisition_trade_id"]),
                holding_period_start=None
                if not row["holding_period_start"]
                else datetime.fromisoformat(row["holding_period_start"]),
            )
            for row in rows
        )
        if len({row.lot_id for row in output}) != len(output) or any(
            row.acquired_at > ledger.clock.now() for row in output
        ):
            raise ValueError("TX: duplicate or future marked lot")
        ledger.verify_chain()
        with transaction(ledger.engine) as session:
            for row in output:
                payload = row.model_dump(mode="json")
                digest = hashlib.sha256(canonical_bytes(row)).hexdigest()
                append_evidence(
                    ledger,
                    row.account_id,
                    env,
                    "MARKED_LOT",
                    str(row.lot_id),
                    digest,
                    payload,
                    session=session,
                )
        return output
    except Exception:
        raise DataIntegrityError("TX: owner-marked external lots cannot be verified") from None
