"""H/J boundary: consume verified account evidence, never invent empty history.

Stage J produces the account-bound tax/history context. A missing context is
UNAVAILABLE until that stage has supplied complete evidence; no ticket passes
by treating absent lots, external accounts or fills as an empty verified set.
"""

from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.money import decimal_money
from backend.core.system_state import SystemStateStore
from backend.domain.compliance_models import ExternalAccount, TaxLot, TradeRecord
from backend.domain.models import FrozenModel, UTCDateTime


class AccountContext(FrozenModel):
    account_id: str = Field(min_length=1, max_length=128)
    cohort: Literal["PAPER", "LIVE"]
    as_of: UTCDateTime
    lots: tuple[TaxLot, ...] = Field(max_length=10000)
    history: tuple[TradeRecord, ...] = Field(max_length=100000)
    accounts: tuple[ExternalAccount, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def bound_accounts(self) -> "AccountContext":
        names = {row.account_id for row in self.accounts}
        if (
            len(names) != len(self.accounts)
            or self.account_id not in names
            or any(row.account_id not in names for row in self.lots)
            or any(row.account_id not in names for row in self.history)
        ):
            raise ValueError("Account context does not bind every owned account")
        if len({row.lot_id for row in self.lots}) != len(self.lots) or len(
            {row.trade_id for row in self.history}
        ) != len(self.history):
            raise ValueError("Account context contains duplicate identities")
        if any(row.acquired_at > self.as_of for row in self.lots) or any(
            row.ts > self.as_of for row in self.history
        ):
            raise ValueError("Account context contains future evidence")
        return self


class LedgerAccountContext:
    def __init__(
        self, state: SystemStateStore, account_id: str, cohort: Literal["PAPER", "LIVE"]
    ) -> None:
        self.state, self.account_id, self.cohort = state, account_id, cohort

    def read(self) -> AccountContext:
        self.state.ledger.verify_chain()
        with Session(self.state.engine) as session:
            record = session.scalar(
                select(SecurityEvent)
                .where(
                    SecurityEvent.kind == "ACCOUNT_RESEARCH_CONTEXT",
                    SecurityEvent.detail["account_id"].as_string() == self.account_id,
                    SecurityEvent.detail["cohort"].as_string() == self.cohort,
                )
                .order_by(SecurityEvent.seq.desc())
                .limit(1)
            )
        if record is None:
            raise ProviderError(
                "Stage J account, lot and trade history evidence is UNAVAILABLE; entry tickets are blocked"
            )
        try:
            payload = dict(record.detail)
            payload["as_of"] = datetime.fromisoformat(payload["as_of"])
            lots, trades = [], []
            for source in payload["lots"]:
                row = dict(source)
                row["lot_id"] = UUID(row["lot_id"])
                row["acquired_at"] = datetime.fromisoformat(row["acquired_at"])
                for name in ("acquisition_trade_id",):
                    row[name] = None if row[name] is None else UUID(row[name])
                row["funding_settlement_date"] = (
                    None
                    if row["funding_settlement_date"] is None
                    else date.fromisoformat(row["funding_settlement_date"])
                )
                row["holding_period_start"] = (
                    None
                    if row["holding_period_start"] is None
                    else datetime.fromisoformat(row["holding_period_start"])
                )
                lots.append(TaxLot.model_validate(row))
            for source in payload["history"]:
                row = dict(source)
                row["trade_id"] = UUID(row["trade_id"])
                row["price"] = decimal_money(row["price"])
                row["ts"] = datetime.fromisoformat(row["ts"])
                row["acquisition_trade_id"] = (
                    None
                    if row["acquisition_trade_id"] is None
                    else UUID(row["acquisition_trade_id"])
                )
                row["holding_period_start"] = (
                    None
                    if row["holding_period_start"] is None
                    else datetime.fromisoformat(row["holding_period_start"])
                )
                trades.append(TradeRecord.model_validate(row))
            payload["lots"], payload["history"] = tuple(lots), tuple(trades)
            checked = AccountContext.model_validate(payload)
            now = ensure_utc(self.state.clock.now())
            if (
                checked.account_id != self.account_id
                or checked.cohort != self.cohort
                or checked.as_of > record.ts
                or not timedelta(0) <= now - checked.as_of <= timedelta(seconds=30)
            ):
                raise ValueError("Account context binding or freshness differs")
            return checked
        except Exception:
            raise DataIntegrityError(
                "Account/tax research evidence could not be verified"
            ) from None
