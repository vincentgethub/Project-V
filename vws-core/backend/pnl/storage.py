"""PL-01: append new daily versions atomically; never modify a historical row."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import DailyPnL, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.pnl.models import PnLDay


def record_day(ledger: Ledger, day: PnLDay) -> DailyPnL:
    checked = PnLDay.model_validate(day)
    obs = checked.observation
    if obs.as_of > ledger.clock.now():
        raise DataIntegrityError("PL-01: daily observation is in the future")
    ledger.verify_chain()
    with transaction(ledger.engine) as session:
        prior = session.scalar(
            select(DailyPnL)
            .where(
                DailyPnL.account_id == obs.account_id,
                DailyPnL.env == obs.env,
                DailyPnL.session_date == obs.session.isoformat(),
            )
            .order_by(DailyPnL.seq.desc())
            .limit(1)
        )
        payload = checked.model_dump(mode="json")
        if prior is not None and prior.payload == payload:
            return prior
        if prior is not None:
            previous = PnLDay.from_payload(prior.payload)
            equivalent = checked.observation.model_copy(
                update={"as_of": previous.observation.as_of}
            )
            if equivalent == previous.observation and checked.source == previous.source:
                return prior
        return ledger.append_in_session(
            session,
            DailyPnL,
            account_id=obs.account_id,
            env=obs.env,
            session_date=obs.session.isoformat(),
            equity=obs.equity,
            cash=obs.cash,
            long_market_value=obs.long_market_value,
            source=checked.source,
            payload=payload,
            supersedes=None if prior is None else prior.id,
        )


def read_days(ledger: Ledger, account_id: str, env: str) -> tuple[PnLDay, ...]:
    if not account_id or env not in {"PAPER", "LIVE"}:
        raise DataIntegrityError("PL-04: explicit account and environment required")
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        rows = tuple(
            session.scalars(
                select(DailyPnL)
                .where(DailyPnL.account_id == account_id, DailyPnL.env == env)
                .order_by(DailyPnL.seq)
            )
        )
    current: dict[str, PnLDay] = {}
    for row in rows:
        current[row.session_date] = PnLDay.from_payload(row.payload)
    return tuple(current[day] for day in sorted(current))
