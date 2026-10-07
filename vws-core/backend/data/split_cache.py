"""DQ-01: append-only split epochs invalidate derived data without revising levels."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.corporate_actions import CorporateActionsResult
from backend.domain.models import FrozenModel, SessionDate, Symbol, UTCDateTime

KIND = "DATA_SPLIT_INVALIDATED"


class SplitEpoch(FrozenModel):
    action_id: UUID
    symbol: Symbol
    effective_date: SessionDate
    observed_at: UTCDateTime


def _epochs(session: Session, now: datetime) -> tuple[tuple[int, SplitEpoch], ...]:
    records = tuple(
        session.scalars(
            select(SecurityEvent)
            .where(SecurityEvent.kind == KIND)
            .order_by(SecurityEvent.seq)
            .limit(10001)
        )
    )
    if len(records) > 10000:
        raise DataIntegrityError("DQ-01: split epoch history exceeds the audit bound")
    result: list[tuple[int, SplitEpoch]] = []
    ids: set[UUID] = set()
    for record in records:
        try:
            data = record.detail
            epoch = SplitEpoch.model_validate(
                {
                    **data,
                    "action_id": UUID(data["action_id"]),
                    "effective_date": date.fromisoformat(data["effective_date"]),
                    "observed_at": datetime.fromisoformat(data["observed_at"]),
                }
            )
            if (
                epoch.observed_at != record.ts
                or epoch.observed_at > now
                or epoch.effective_date > epoch.observed_at.date()
                or epoch.action_id in ids
            ):
                raise ValueError("unbound split epoch")
        except Exception:
            raise DataIntegrityError("DQ-01: split invalidation evidence is unverifiable") from None
        ids.add(epoch.action_id)
        result.append((record.seq, epoch))
    return tuple(result)


def current_epochs(session: Session, now: datetime) -> dict[str, int]:
    """Caller verifies the ledger; the sequence is a hard cache provenance floor."""
    result: dict[str, int] = {}
    for seq, epoch in _epochs(session, ensure_utc(now)):
        result[epoch.symbol] = seq
    return result


def observe_splits(
    ledger: Ledger, actions: CorporateActionsResult | None, now: datetime
) -> dict[str, int]:
    """Serialize first observation before refetching; repeated observations are idempotent."""
    instant = ensure_utc(now)
    ledger.verify_chain()
    checked = CorporateActionsResult.model_validate(actions) if actions is not None else None
    if checked is not None and checked.fetched_at > instant:
        raise DataIntegrityError("DQ-01: split evidence is from the future")
    with transaction(ledger.engine) as session:
        prior = _epochs(session, instant)
        by_id = {epoch.action_id: epoch for _, epoch in prior}
        result = {epoch.symbol: seq for seq, epoch in prior}
        for action in () if checked is None else checked.actions:
            if action.kind not in {"forward_splits", "reverse_splits"}:
                continue
            old = by_id.get(action.provider_id)
            if old is not None:
                if (old.symbol, old.effective_date) != (action.symbol, action.effective_date):
                    raise DataIntegrityError("DQ-01: split action identity changed")
                continue
            epoch = SplitEpoch(
                action_id=action.provider_id,
                symbol=action.symbol,
                effective_date=action.effective_date,
                observed_at=instant,
            )
            record = ledger.append_in_session(
                session, SecurityEvent, kind=KIND, detail=epoch.model_dump(mode="json"), ts=instant
            )
            by_id[epoch.action_id] = epoch
            result[epoch.symbol] = record.seq
        return result
