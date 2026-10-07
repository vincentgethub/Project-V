"""DQ-01: contradictory invalidation evidence and concurrent fetches fail closed."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.data.split_cache import KIND, SplitEpoch, _epochs, current_epochs, observe_splits
from backend.tests.test_adjustment_data import actions

NOW = datetime(2026, 9, 29, 21, tzinfo=UTC)


@pytest.mark.parametrize("fault", ["detail", "timestamp", "future", "effective_date", "duplicate"])
def test_DQ_01_bad_durable_epoch_is_typed(engine: Engine, fault: str) -> None:
    ledger = Ledger(engine, FrozenClock(NOW))
    epoch = SplitEpoch(
        action_id=UUID(int=1), symbol="AAPL", effective_date=date(2026, 9, 28), observed_at=NOW
    )
    data = epoch.model_dump(mode="json")
    if fault == "detail":
        data["extra"] = "unsupported"
    elif fault == "future":
        data["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif fault == "effective_date":
        data["effective_date"] = "2026-09-30"
    ts = NOW + timedelta(seconds=1) if fault in {"timestamp", "future"} else NOW
    ledger.append(SecurityEvent, kind=KIND, detail=data, ts=ts)
    if fault == "duplicate":
        ledger.append(SecurityEvent, kind=KIND, detail=data, ts=NOW)
    ledger.verify_chain()
    with Session(engine) as session, pytest.raises(DataIntegrityError):
        current_epochs(session, NOW)


def test_DQ_01_epoch_bound_refuses_overflow(
    monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    with Session(engine) as session:
        monkeypatch.setattr(session, "scalars", lambda query: [object()] * 10001)
        with pytest.raises(DataIntegrityError):
            _epochs(session, NOW)


def test_DQ_01_non_split_actions_do_not_invalidate_and_future_evidence_is_refused(
    engine: Engine,
) -> None:
    ledger = Ledger(engine, FrozenClock(NOW))
    evidence = actions(NOW)
    dividend = evidence.actions[0].model_copy(update={"kind": "cash_dividends"})
    assert observe_splits(ledger, evidence.model_copy(update={"actions": (dividend,)}), NOW) == {}
    with pytest.raises(DataIntegrityError):
        observe_splits(
            ledger, evidence.model_copy(update={"fetched_at": NOW + timedelta(seconds=1)}), NOW
        )
    first = observe_splits(ledger, evidence, NOW)
    changed = evidence.actions[0].model_copy(update={"symbol": "SPY"})
    with pytest.raises(DataIntegrityError):
        observe_splits(ledger, evidence.model_copy(update={"actions": (changed,)}), NOW)
    assert observe_splits(ledger, evidence, NOW) == first


@pytest.mark.asyncio
async def test_DQ_01_split_during_warm_fetch_cannot_publish_stale_cache(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.data.market_calendar import MarketCalendar
    from backend.tests.test_async_reader import MovingClock
    from backend.tests.test_batch_data import _provider

    calendar = MarketCalendar(start=date(2026, 9, 1), end=date(2026, 10, 31))
    provider, reader, calls = _provider(engine, calendar, monkeypatch, MovingClock(NOW))
    await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
    original = provider._store

    def race(*args: Any, **kwargs: Any) -> Any:
        observe_splits(provider.ledger, actions(NOW), NOW)
        return original(*args, **kwargs)

    monkeypatch.setattr(provider, "_store", race)
    with pytest.raises(DataIntegrityError):
        await provider.completed_daily_bars(("AAPL",), date(2026, 9, 25))
    assert len(calls) == 1 and reader.tripped
    provider.ledger.verify_chain()
