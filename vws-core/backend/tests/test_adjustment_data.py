"""DQ-01/03: installed SDK adjustment isolation, durable invalidation and exclusion."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import requests
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.agents.indicators import IndicatorMemo
from backend.agents.peer_strength import BatchPeerProvider
from backend.core.database import DataSnapshot, SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.data.corporate_actions import CorporateActionEvidence, CorporateActionsResult
from backend.data.data_layer import AsyncAlpacaMarketData, BatchBars, SymbolBars, _bars_digest
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import MarketStatus, ProviderStatus
from backend.indicators.cache import IndicatorCache
from backend.tests.test_async_reader import MovingClock
from backend.tests.test_batch_data import _provider
from backend.tests.test_indicator_cache import _bars
from backend.tests.test_peer_strength import inputs


@pytest.fixture(scope="module")
def calendar() -> MarketCalendar:
    return MarketCalendar(start=date(2025, 1, 1), end=date(2027, 12, 31))


def actions(now: datetime, **values: Any) -> CorporateActionsResult:
    action = CorporateActionEvidence(
        provider_id=UUID(int=1),
        kind="forward_splits",
        symbol="AAPL",
        effective_date=date(2026, 9, 28),
        process_date=date(2026, 9, 28),
        effective_date_field="ex_date",
    )
    return CorporateActionsResult.model_validate(
        {
            "provider": "FAKE",
            "status": ProviderStatus.OK,
            "fetched_at": now,
            "symbols": ("AAPL", "SPY"),
            "process_start": date(2026, 9, 25),
            "process_end": date(2026, 9, 29),
            "actions": (action,),
            "reason": "synthetic split",
            **values,
        }
    )


@pytest.mark.asyncio
async def test_DQ_01_three_adjustments_keep_all_raw_audit_and_warm_batches(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, _, calls = _provider(engine, calendar, monkeypatch, clock)
    batch = await provider.completed_daily_evidence(("AAPL",), date(2026, 9, 25))
    assert [item["adjustment"] for item in calls] == ["raw", "split", "all"]
    assert all(item["feed"] == "sip" for item in calls)
    assert len(batch.entries) == 6
    assert batch.for_symbol("AAPL") == batch.for_symbol("AAPL", "SPLIT")
    assert batch == await provider.completed_daily_evidence(("AAPL",), date(2026, 9, 25))
    assert len(calls) == 3
    with Session(engine) as session:
        assert {row.adjustment for row in session.scalars(select(DataSnapshot))} == {
            "RAW",
            "SPLIT",
            "ALL",
        }
    provider.ledger.verify_chain()


@pytest.mark.asyncio
async def test_DQ_01_new_split_refetches_only_symbol_and_invalidates_memory_disk(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, _, calls = _provider(engine, calendar, monkeypatch, clock)
    first = await provider.completed_daily_evidence(("AAPL",), date(2026, 9, 25))
    memo, disk = IndicatorMemo(), IndicatorCache(tmp_path)
    bars = _bars()
    for symbol in ("AAPL", "SPY"):
        memo.calculate(symbol, bars, 0)
        disk.calculate(symbol, "SPLIT", bars, 0, feed="FAKE")
    invalidations: list[str] = []

    def invalidate(symbol: str) -> None:
        invalidations.append(symbol)
        memo.invalidate_symbol(symbol)
        disk.invalidate_symbol(symbol)

    provider.invalidate_indicators = invalidate
    second = await provider.completed_daily_evidence(
        ("AAPL",), date(2026, 9, 25), corporate_actions=actions(clock.now())
    )
    assert first == second and invalidations == ["AAPL"]
    assert len(calls) == 6 and all(item["symbols"] == "AAPL" for item in calls[3:])
    assert not list(tmp_path.glob("AAPL_*.npz")) and len(list(tmp_path.glob("SPY_*.npz"))) == 1
    assert all(key[0] != "AAPL" for key in memo._entries)
    await provider.completed_daily_evidence(
        ("AAPL",), date(2026, 9, 25), corporate_actions=actions(clock.now())
    )
    assert len(calls) == 6 and invalidations == ["AAPL"]
    restarted = AsyncAlpacaMarketData(
        provider.settings,
        provider.reader,
        calendar,
        provider.ledger,
        provider.client,
        invalidate_indicators=invalidate,
    )
    await restarted.completed_daily_evidence(("AAPL",), date(2026, 9, 25))
    assert len(calls) == 6 and invalidations == ["AAPL", "AAPL"]
    with Session(engine) as session:
        assert len(tuple(session.scalars(select(DataSnapshot)))) == 9
        assert (
            len(
                tuple(
                    session.scalars(
                        select(SecurityEvent).where(SecurityEvent.kind == "DATA_SPLIT_INVALIDATED")
                    )
                )
            )
            == 1
        )
    provider.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("known", [False, True])
async def test_DQ_03_ratio_changes_need_known_split_dates(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, known: bool
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, _, _ = _provider(engine, calendar, monkeypatch, clock)
    original = requests.Session.request

    def response(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        result = original(session, method, url, *args, **kwargs)
        data = json.loads(result.content)
        if kwargs["params"]["adjustment"] == "raw":
            data["bars"]["AAPL"][0].update(o="200.00", h="202.00", l="198.00", c="200.00")
        result._content = json.dumps(data).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    batch = await provider.completed_daily_evidence(
        ("AAPL",), date(2026, 9, 25), corporate_actions=actions(clock.now()) if known else None
    )
    expected = MarketStatus.OK if known else MarketStatus.SUSPECT
    assert all(entry.status == expected for entry in batch.entries if entry.symbol == "AAPL")
    assert batch.status_for("SPY") == MarketStatus.OK
    assert provider.reader.state.current() == SystemState.RUNNING


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["zero", "ohlc", "duplicate", "missing", "ratio_ohlc"])
async def test_DQ_03_every_sanity_violation_leaves_durable_suspect(
    engine: Engine, calendar: MarketCalendar, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    clock = MovingClock(datetime(2026, 9, 29, 21, tzinfo=UTC))
    provider, _, _ = _provider(engine, calendar, monkeypatch, clock)
    original = requests.Session.request

    def response(
        session: requests.Session, method: str, url: str, *args: Any, **kwargs: Any
    ) -> requests.Response:
        result = original(session, method, url, *args, **kwargs)
        data = json.loads(result.content)
        rows = data["bars"]["AAPL"]
        if fault == "zero":
            rows[0]["v"] = 0
        elif fault == "ohlc":
            rows[0]["h"] = "99.00"
        elif fault == "duplicate":
            rows.insert(0, rows[0])
        elif fault == "missing":
            rows.pop(1)
        elif kwargs["params"]["adjustment"] == "split":
            rows[0]["h"] = "102.00"
        result._content = json.dumps(data).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", response)
    if fault in {"zero", "ratio_ohlc"}:
        batch = await provider.completed_daily_evidence(("AAPL",), date(2026, 9, 25))
        assert batch.status_for("AAPL") == MarketStatus.SUSPECT
    else:
        with pytest.raises(DataIntegrityError):
            await provider.completed_daily_evidence(("AAPL",), date(2026, 9, 25))
        assert provider.reader.state.current() == SystemState.HALTED
    provider._status._reload_symbol_status()
    assert "AAPL" in provider._status._suspect
    provider.ledger.verify_chain()


@pytest.mark.asyncio
async def test_DQ_01_peer_provider_requires_all_and_ok_adjustments() -> None:
    bars, now, registry, calendar = inputs()
    entries = tuple(
        SymbolBars(symbol=symbol, bars=bars, data_sha256=_bars_digest(bars)[0])
        for symbol in ("NVDA", "XLK", "SPY")
    )
    batch = BatchBars(as_of=now, through=bars[-1].session_date, entries=entries)
    assert (
        await BatchPeerProvider(batch, registry, calendar).get("NVDA", now)
    ).status == ProviderStatus.UNAVAILABLE
    all_entries = tuple(
        SymbolBars.model_validate(row.model_copy(update={"adjustment": "ALL"})) for row in entries
    )
    complete = batch.model_copy(update={"entries": (*entries, *all_entries)})
    assert (
        await BatchPeerProvider(complete, registry, calendar).get("NVDA", now)
    ).status == ProviderStatus.OK
    suspect = complete.model_copy(
        update={
            "entries": (
                *entries,
                *(row.model_copy(update={"status": MarketStatus.SUSPECT}) for row in all_entries),
            )
        }
    )
    assert (
        await BatchPeerProvider(suspect, registry, calendar).get("NVDA", now)
    ).status == ProviderStatus.UNAVAILABLE


def test_DQ_01_memo_keys_include_adjustment_and_invalidation_preserves_other_symbols() -> None:
    bars = _bars()
    memo = IndicatorMemo()
    result = memo.calculate("AAPL", bars, 0)
    changed = (bars[0].model_copy(update={"volume": 9999}), *bars[1:])
    memo.calculate("AAPL", changed, 0, adjustment="RAW")
    memo.calculate("SPY", bars, 0)
    memo.invalidate_symbol("AAPL")
    assert memo.calculate("AAPL", changed, 0) != result
    assert any(key[0] == "SPY" for key in memo._entries)
    with pytest.raises(DataIntegrityError):
        memo.calculate("AAPL", bars, 0, adjustment="UNKNOWN")
    with pytest.raises(DataIntegrityError):
        memo.invalidate_symbol("aapl")
