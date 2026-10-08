"""FN-02/05: bounded immutable observed account activities."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.core.errors import DataIntegrityError
from backend.data.history import canonical_bytes
from backend.domain.models import FrozenModel, Money, SessionDate, Symbol, UTCDateTime
from backend.tax.models import Environment, TaxFill

EXTERNAL_TYPES = frozenset({"CSD", "CSW", "JNLC"})
CORPORATE_TYPES = frozenset({"MA", "NC", "REORG", "SC", "SSO", "SSP", "PTC", "PTR"})


class Activity(FrozenModel):
    account_id: str = Field(min_length=1, max_length=128)
    env: Environment
    activity_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:._-]+$")
    type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")
    amount: Money
    date: SessionDate
    observed_at: UTCDateTime
    occurred_at: UTCDateTime | None
    source: Literal["BROKER", "CSV"]
    symbol: Symbol | None = None
    fill: TaxFill | None = None
    broker_order_id: UUID | None = None
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str | None = Field(default=None, min_length=1, max_length=280)

    @model_validator(mode="after")
    def bound(self) -> Self:
        if self.occurred_at is not None and (
            self.occurred_at > self.observed_at or self.occurred_at.date() != self.date
        ):
            raise ValueError("FN-02: activity date/time contradicts observation")
        if (
            self.date > self.observed_at.date()
            or (self.type == "CSD" and self.amount <= 0)
            or (self.type == "CSW" and self.amount >= 0)
        ):
            raise ValueError("FN-02: activity sign or date contradicts funding evidence")
        if (self.type == "FILL") != (self.fill is not None):
            raise ValueError("TX-02: FILL requires its exact executed evidence")
        if (self.type == "FILL") != (self.broker_order_id is not None):
            raise ValueError("TX-02: only FILL binds its broker order identity")
        if self.fill is not None and (
            self.fill.account_id,
            self.fill.env,
            self.fill.activity_id,
            self.fill.symbol,
            self.fill.ts,
        ) != (self.account_id, self.env, self.activity_id, self.symbol, self.occurred_at):
            raise ValueError("TX-01: fill ownership, symbol or execution differs")
        if self.note is not None and not self.note.isprintable():
            raise ValueError("FN-02: activity notes require bounded plain text")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> Activity:
        try:
            values = dict(payload)
            values["date"] = date.fromisoformat(str(values["date"]))
            values["observed_at"] = datetime.fromisoformat(str(values["observed_at"]))
            if values["occurred_at"] is not None:
                values["occurred_at"] = datetime.fromisoformat(str(values["occurred_at"]))
            raw = values["fill"]
            if raw is not None:
                if not isinstance(raw, dict):
                    raise ValueError("invalid fill payload")
                values["fill"] = TaxFill.from_payload(raw)
            return cls.model_validate(values)
        except Exception:
            raise DataIntegrityError("FN-02: stored activity cannot be verified") from None
