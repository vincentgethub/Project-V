"""TX-10: exact versioned accounting evidence and immutable CSV import manifests."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from backend.core.database import CashFlow, DailyPnL, LedgerRecord, TaxEvent, transaction
from backend.core.errors import DataIntegrityError, LedgerIntegrityError
from backend.core.ledger import Ledger
from backend.domain.compliance_models import TaxLot
from backend.domain.models import FrozenModel, UTCDateTime
from backend.funding.models import CORPORATE_TYPES, EXTERNAL_TYPES, Activity
from backend.pnl.models import PnLDay
from backend.tax.models import Environment, TaxFill, TaxIncome


class ImportManifest(FrozenModel):
    account_id: str = Field(min_length=1, max_length=128)
    env: Environment
    imported_at: UTCDateTime
    fills: tuple[UUID, ...] = Field(max_length=100000)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(set(self.fills)) != len(self.fills):
            raise ValueError("TX-10: import manifest repeats a physical fill")
        return self

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> ImportManifest:
        values = dict(payload)
        values["imported_at"] = datetime.fromisoformat(str(values["imported_at"]))
        fills = values["fills"]
        if not isinstance(fills, (tuple, list)):
            raise DataIntegrityError("TX-10: import manifest is unavailable")
        values["fills"] = tuple(UUID(str(fill)) for fill in fills)
        return cls.model_validate(values)


def validate_record(session: Session, record: LedgerRecord) -> None:
    """Validate typed payload and correction lineage when appending or verifying."""
    if isinstance(record, CashFlow):
        row = Activity.from_payload(record.payload)
        if (
            record.account_id,
            record.env,
            record.activity_id,
            record.type,
            record.amount,
            record.date,
            record.payload_sha256,
        ) != (
            row.account_id,
            row.env,
            row.activity_id,
            row.type,
            row.amount,
            row.date.isoformat(),
            row.payload_sha256,
        ) or row.observed_at > record.created_at:
            raise LedgerIntegrityError("FN-02: activity columns differ from observed evidence")
        from backend.core.database import PortfolioState

        portfolio = (
            None
            if record.portfolio_state_id is None
            else session.get(PortfolioState, record.portfolio_state_id)
        )
        if row.type in EXTERNAL_TYPES:
            if (
                record.baseline_effect not in {"SCALED", "INCLUDED"}
                or portfolio is None
                or portfolio.account_id != row.account_id
                or portfolio.created_at > record.created_at
            ):
                raise LedgerIntegrityError("FN-03: external flow lacks bound baseline evidence")
            if record.baseline_effect == "SCALED" and (
                portfolio.cash_flow_amount != row.amount or portfolio.cash_flow_at is None
            ):
                raise LedgerIntegrityError("FN-03: applied flow differs from scaled baselines")
        elif record.baseline_effect != "NONE" or portfolio is not None:
            raise LedgerIntegrityError("FN-03: income/unknown activity cannot scale baselines")
    elif isinstance(record, DailyPnL):
        day = PnLDay.from_payload(record.payload)
        obs = day.observation
        if (
            record.account_id,
            record.env,
            record.session_date,
            record.equity,
            record.cash,
            record.long_market_value,
            record.source,
        ) != (
            obs.account_id,
            obs.env,
            obs.session.isoformat(),
            obs.equity,
            obs.cash,
            obs.long_market_value,
            day.source,
        ) or obs.as_of > record.created_at:
            raise LedgerIntegrityError("PL-01: daily columns differ from exact observation")
        previous = tuple(
            session.scalars(
                select(DailyPnL)
                .where(
                    DailyPnL.account_id == record.account_id,
                    DailyPnL.env == record.env,
                    DailyPnL.session_date == record.session_date,
                    DailyPnL.seq < record.seq,
                )
                .order_by(DailyPnL.seq)
            )
        )
        if record.supersedes != (None if not previous else previous[-1].id):
            raise LedgerIntegrityError("PL-01: correction must supersede the latest bound session")
    elif isinstance(record, TaxEvent):
        bound: tuple[str, str, str, str]
        if record.kind == "FILL":
            fill = TaxFill.from_payload(record.payload)
            bound = fill.account_id, fill.env, fill.activity_id, fill.payload_sha256
            if fill.ts > record.created_at:
                raise LedgerIntegrityError("TX-02: fill is in the future")
        elif record.kind == "INCOME":
            income = TaxIncome.from_payload(record.payload)
            bound = income.account_id, income.env, income.activity_id, record.payload_sha256
            if income.date > record.created_at.date():
                raise LedgerIntegrityError("TX-06: income is in the future")
        elif record.kind == "IMPORT":
            manifest = ImportManifest.from_payload(record.payload)
            bound = manifest.account_id, manifest.env, "CSV_IMPORT", manifest.source_sha256
            if manifest.imported_at > record.created_at:
                raise LedgerIntegrityError("TX-10: import is in the future")
            known = {
                TaxFill.from_payload(row.payload).fill_id
                for row in session.scalars(
                    select(TaxEvent).where(
                        TaxEvent.account_id == record.account_id,
                        TaxEvent.env == record.env,
                        TaxEvent.kind == "FILL",
                        TaxEvent.seq < record.seq,
                    )
                )
            }
            if not set(manifest.fills) <= known:
                raise LedgerIntegrityError("TX-10: import manifest references unavailable fills")
        elif record.kind == "CORPORATE_ACTION":
            corporate = Activity.from_payload(record.payload)
            bound = (
                corporate.account_id,
                corporate.env,
                corporate.activity_id,
                corporate.payload_sha256,
            )
            if corporate.type not in CORPORATE_TYPES or corporate.observed_at > record.created_at:
                raise LedgerIntegrityError("FN-05: corporate action evidence is unbound")
        elif record.kind == "MARKED_LOT":
            lot = dict(record.payload)
            for field in ("acquired_at", "holding_period_start"):
                if lot[field] is not None:
                    lot[field] = datetime.fromisoformat(lot[field])
            if lot["funding_settlement_date"] is not None:
                from datetime import date

                lot["funding_settlement_date"] = date.fromisoformat(lot["funding_settlement_date"])
            marked = TaxLot.model_validate(lot)
            bound = marked.account_id, record.env, str(marked.lot_id), record.payload_sha256
            if marked.acquired_at > record.created_at:
                raise LedgerIntegrityError("TX: marked external lot is in the future")
        else:
            raise LedgerIntegrityError("TX-10: unknown tax event kind")
        if (record.account_id, record.env, record.source_id, record.payload_sha256) != bound:
            raise LedgerIntegrityError("TX-10: tax event ownership/source differs")
        previous = tuple(
            session.scalars(
                select(TaxEvent)
                .where(
                    TaxEvent.account_id == record.account_id,
                    TaxEvent.env == record.env,
                    TaxEvent.kind == record.kind,
                    TaxEvent.source_id == record.source_id,
                    TaxEvent.seq < record.seq,
                )
                .order_by(TaxEvent.seq)
            )
        )
        if record.supersedes != (None if not previous else previous[-1].id):
            raise LedgerIntegrityError("TX-10: correction must supersede latest bound source")
    else:
        raise LedgerIntegrityError("FN/PL/TX: unsupported accounting record")


def append_evidence(
    ledger: Ledger,
    account_id: str,
    env: Environment,
    kind: str,
    source_id: str,
    payload_sha256: str,
    payload: dict[str, object],
    *,
    session: Session | None = None,
) -> TaxEvent:
    def append(current: Session) -> TaxEvent:
        prior = current.scalar(
            select(TaxEvent)
            .where(
                TaxEvent.account_id == account_id,
                TaxEvent.env == env,
                TaxEvent.kind == kind,
                TaxEvent.source_id == source_id,
            )
            .order_by(TaxEvent.seq.desc())
            .limit(1)
        )
        if (
            prior is not None
            and prior.payload_sha256 == payload_sha256
            and prior.payload == payload
        ):
            return prior
        if (
            prior is not None
            and kind == "IMPORT"
            and prior.payload_sha256 == payload_sha256
            and {key: value for key, value in prior.payload.items() if key != "imported_at"}
            == {key: value for key, value in payload.items() if key != "imported_at"}
        ):
            return prior
        return ledger.append_in_session(
            current,
            TaxEvent,
            account_id=account_id,
            env=env,
            kind=kind,
            source_id=source_id,
            payload_sha256=payload_sha256,
            payload=payload,
            supersedes=None if prior is None else prior.id,
        )

    if session is not None:
        bind = session.get_bind()
        if (
            not isinstance(bind, Connection)
            or bind.engine is not ledger.engine
            or not bind.in_transaction()
        ):
            raise DataIntegrityError("TX-10: bound serialized transaction required")
        return append(session)
    ledger.verify_chain()
    with transaction(ledger.engine) as current:
        return append(current)


def read_fills(
    ledger: Ledger, account_id: str, env: Environment, *, csv: bool
) -> tuple[TaxFill, ...]:
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        rows = tuple(
            session.scalars(
                select(TaxEvent)
                .where(TaxEvent.account_id == account_id, TaxEvent.env == env)
                .order_by(TaxEvent.seq)
            )
        )
    current = {
        row.source_id: TaxFill.from_payload(row.payload) for row in rows if row.kind == "FILL"
    }
    if csv:
        manifests = tuple(
            ImportManifest.from_payload(row.payload) for row in rows if row.kind == "IMPORT"
        )
        if not manifests:
            raise DataIntegrityError("TX-01: external account import is UNAVAILABLE")
        ids = set(manifests[-1].fills)
        current = {key: fill for key, fill in current.items() if fill.fill_id in ids}
    return tuple(sorted(current.values(), key=lambda fill: (fill.ts, fill.fill_id.hex)))
