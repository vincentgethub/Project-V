"""DAT-10: verified SDK contracts and conservative symbol/date gap evidence."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest
from alpaca.data.requests import CorporateActionsRequest
from pydantic import ValidationError
from sqlalchemy import Engine

from backend.core.clock import FrozenClock
from backend.core.config import Settings
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.corporate_actions import (
    AlpacaCorporateActionsProvider,
    CorporateActionEvidence,
    CorporateActionsResult,
    FakeCorporateActionsProvider,
)
from backend.data.news import AlpacaNewsProvider, NewsStore
from backend.domain.models import ProviderStatus
from backend.net import http
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import TimeoutSession

START = date(2026, 9, 1)
END = date(2026, 9, 29)


@pytest.fixture(autouse=True)
def configured_sdk_policy(
    engine: Engine, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http, "_policy", EgressPolicy(build_allowlist(), Ledger(engine, clock)))


class FakeClient:
    def __init__(self, response: object, *, pages: int = 1, fail: bool = False) -> None:
        self._session = TimeoutSession(30, policy=http._policy)
        self._retry = 3
        self.response, self.pages, self.fail = response, pages, fail
        self.requests: list[CorporateActionsRequest] = []
        self.threads: list[int] = []

    def get_corporate_actions(self, request_params: CorporateActionsRequest) -> object:
        self.requests.append(request_params)
        self.threads.append(threading.get_ident())
        for _ in range(self.pages):
            callback = self._session._before_request
            assert callback is not None
            callback()
        if self.fail:
            raise RuntimeError("synthetic upstream failure")
        return self.response


def _row(**values: Any) -> dict[str, Any]:
    return {
        "id": str(UUID(int=1)),
        "symbol": "AAPL",
        "ex_date": "2026-09-28",
        "process_date": "2026-09-29",
        **values,
    }


def _provider(
    engine: Engine, clock: FrozenClock, raw: object, *, fail: bool = False, pages: int = 1
) -> tuple[AlpacaCorporateActionsProvider, AsyncAlpacaReader, FakeClient]:
    reader = AsyncAlpacaReader(clock, SystemStateStore(engine, clock, ConsoleNotifier()))
    client = FakeClient(raw, fail=fail, pages=pages)
    return (
        AlpacaCorporateActionsProvider(
            Settings(_env_file=None), reader, Ledger(engine, clock), client=client
        ),
        reader,
        client,
    )


@pytest.mark.asyncio
async def test_DAT_10_process_date_never_substitutes_for_ex_date(
    engine: Engine, clock: FrozenClock
) -> None:
    provider, reader, client = _provider(engine, clock, {"forward_splits": [_row()]}, pages=2)
    result = await provider.fetch(("AAPL",), START, END)
    assert result.known_actions == frozenset({("AAPL", date(2026, 9, 28))})
    assert ("AAPL", END) not in result.known_actions
    assert (
        result.process_start == START
        and result.process_end == END
        and result.fetched_at == clock.now()
    )
    assert (
        result.actions[0].process_date == END
        and result.actions[0].effective_date_field == "ex_date"
    )
    assert client._retry == 0 and reader.bucket.available == 178
    assert all(value != threading.get_ident() for value in client.threads)
    assert client.requests[0].symbols == ["AAPL"] and client.requests[0].start == START


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,symbol_field,date_field",
    [
        ("forward_splits", "symbol", "ex_date"),
        ("reverse_splits", "symbol", "ex_date"),
        ("cash_dividends", "symbol", "ex_date"),
        ("stock_dividends", "symbol", "ex_date"),
        ("spin_offs", "source_symbol", "ex_date"),
        ("rights_distributions", "source_symbol", "ex_date"),
        ("unit_splits", "old_symbol", "effective_date"),
        ("cash_mergers", "acquiree_symbol", "effective_date"),
        ("stock_mergers", "acquiree_symbol", "effective_date"),
        ("stock_and_cash_mergers", "acquiree_symbol", "effective_date"),
    ],
)
async def test_DAT_10_verified_pinned_action_fields_only(
    engine: Engine, clock: FrozenClock, kind: str, symbol_field: str, date_field: str
) -> None:
    row = {
        "id": str(UUID(int=1)),
        symbol_field: "AAPL",
        date_field: "2026-09-28",
        "process_date": "2026-09-29",
    }
    provider, _, _ = _provider(engine, clock, {kind: [row]})
    result = await provider.fetch(("AAPL",), START, END)
    assert result.status == ProviderStatus.OK and result.known_actions == frozenset(
        {("AAPL", date(2026, 9, 28))}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["name_changes", "redemptions", "worthless_removals", "unsupported_type"]
)
async def test_DAT_10_no_verified_effective_date_is_unavailable_not_gap_clearance(
    engine: Engine, clock: FrozenClock, kind: str
) -> None:
    provider, _, _ = _provider(engine, clock, {kind: [_row()]})
    result = await provider.fetch(("AAPL",), START, END)
    assert result.status == ProviderStatus.UNAVAILABLE and result.known_actions == frozenset()
    assert "SUSPECT" in result.reason


@pytest.mark.asyncio
async def test_DAT_10_incomplete_action_date_leaves_symbol_suspect(
    engine: Engine, clock: FrozenClock
) -> None:
    provider, _, _ = _provider(engine, clock, {"forward_splits": [_row(ex_date=None)]})
    result = await provider.fetch(("AAPL",), START, END)
    assert result.status == ProviderStatus.UNAVAILABLE and not result.known_actions


@pytest.mark.asyncio
async def test_DAT_10_read_failure_is_unavailable_and_halts_sdk_boundary(
    engine: Engine, clock: FrozenClock
) -> None:
    provider, reader, _ = _provider(engine, clock, {}, fail=True)
    result = await provider.fetch(("AAPL",), START, END)
    assert result.status == ProviderStatus.UNAVAILABLE and not result.known_actions
    assert reader.state.current() == SystemState.HALTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        None,
        {1: []},
        {"forward_splits": {}},
        {"forward_splits": [None]},
        {"forward_splits": [{}]},
        {"forward_splits": [_row()] * 1001},
    ],
)
async def test_DAT_10_malformed_or_unbounded_action_batch_rejected(
    engine: Engine, clock: FrozenClock, raw: object
) -> None:
    provider, _, _ = _provider(engine, clock, raw)
    if raw == {"forward_splits": [{}]}:
        assert (await provider.fetch(("AAPL",), START, END)).status == ProviderStatus.UNAVAILABLE
    else:
        with pytest.raises(DataIntegrityError):
            await provider.fetch(("AAPL",), START, END)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "values",
    [
        {"id": "not-uuid"},
        {"id": 1},
        {"symbol": "aapl"},
        {"symbol": "MSFT"},
        {"ex_date": "2026-09-30"},
        {"ex_date": "invalid"},
        {"ex_date": 1},
        {"process_date": "2026-09-30"},
        {"process_date": "2026-08-31"},
        {"process_date": None},
    ],
)
async def test_DAT_10_unbound_future_or_invalid_action_is_rejected(
    engine: Engine, clock: FrozenClock, values: dict[str, Any]
) -> None:
    provider, reader, _ = _provider(engine, clock, {"forward_splits": [_row(**values)]})
    with pytest.raises(DataIntegrityError):
        await provider.fetch(("AAPL",), START, END)
    assert reader.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_DAT_10_duplicate_action_identity_is_idempotent_but_conflict_fails(
    engine: Engine, clock: FrozenClock
) -> None:
    provider, _, _ = _provider(engine, clock, {"forward_splits": [_row(), _row()]})
    assert len((await provider.fetch(("AAPL",), START, END)).actions) == 1
    conflicted, _, _ = _provider(
        engine, clock, {"forward_splits": [_row(), _row(ex_date="2026-09-27")]}
    )
    with pytest.raises(DataIntegrityError):
        await conflicted.fetch(("AAPL",), START, END)


@pytest.mark.asyncio
async def test_DAT_10_empty_success_cannot_explain_any_gap(
    engine: Engine, clock: FrozenClock
) -> None:
    provider, _, _ = _provider(engine, clock, {"forward_splits": [], "new_unknown_type": []})
    result = await provider.fetch(("AAPL",), START, END)
    assert result.status == ProviderStatus.OK and not result.known_actions


def _evidence(**values: Any) -> CorporateActionEvidence:
    return CorporateActionEvidence.model_validate(
        {
            "provider_id": UUID(int=1),
            "kind": "forward_splits",
            "symbol": "AAPL",
            "effective_date": date(2026, 9, 28),
            "process_date": END,
            "effective_date_field": "ex_date",
            **values,
        }
    )


@pytest.mark.asyncio
async def test_DAT_10_fake_requires_same_provenance_and_unknown_is_not_clear(
    clock: FrozenClock,
) -> None:
    result = await FakeCorporateActionsProvider(clock, (_evidence(),)).fetch(("AAPL",), START, END)
    assert result.known_actions == frozenset({("AAPL", date(2026, 9, 28))})
    unavailable = await FakeCorporateActionsProvider(clock, available=False).fetch(
        ("AAPL",), START, END
    )
    assert unavailable.status == ProviderStatus.UNAVAILABLE and not unavailable.known_actions
    with pytest.raises(DataIntegrityError):
        await FakeCorporateActionsProvider(
            clock, (_evidence(effective_date=date(2026, 9, 30)),)
        ).fetch(("AAPL",), START, END)


@pytest.mark.parametrize(
    "values",
    [
        {"effective_date_field": "process_date"},
        {"effective_date_field": "effective_date"},
        {"kind": "name_changes"},
        {"symbol": "aapl"},
    ],
)
def test_DAT_10_action_schema_forbids_guessed_fields(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _evidence(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"status": "UNAVAILABLE"},
        {"symbols": ("MSFT",)},
        {"symbols": ("AAPL", "AAPL")},
        {"process_start": date(2026, 9, 30)},
        {"process_end": date(2026, 9, 30)},
        {"actions": (_evidence(), _evidence())},
    ],
)
def test_DAT_10_result_revalidates_copied_coverage(
    clock: FrozenClock, values: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        CorporateActionsResult.model_validate(
            {
                "provider": "FAKE",
                "status": "OK",
                "fetched_at": clock.now(),
                "symbols": ("AAPL",),
                "process_start": START,
                "process_end": END,
                "actions": (_evidence(),),
                "reason": "fixture",
                **values,
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "symbols,start,end",
    [
        ((), START, END),
        (("aapl",), START, END),
        (("AAPL", "AAPL"), START, END),
        (("AAPL",), END, START),
        (("AAPL",), START, date(2026, 9, 30)),
    ],
)
async def test_DAT_10_invalid_query_rejected_before_io(
    clock: FrozenClock, symbols: tuple[str, ...], start: date, end: date
) -> None:
    with pytest.raises(DataIntegrityError):
        await FakeCorporateActionsProvider(clock).fetch(symbols, start, end)


def test_DAT_10_fake_fixture_flags_strict(clock: FrozenClock) -> None:
    with pytest.raises(ConfigurationError):
        FakeCorporateActionsProvider(clock, available=1)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_DAT_06_news_and_actions_share_one_bound_budget(
    engine: Engine, clock: FrozenClock
) -> None:
    reader = AsyncAlpacaReader(clock, SystemStateStore(engine, clock, ConsoleNotifier()))
    ledger = Ledger(engine, clock)
    actions = AlpacaCorporateActionsProvider(
        Settings(_env_file=None),
        reader,
        ledger,
        client=FakeClient({"forward_splits": [_row()]}, pages=2),
    )

    class NewsClientFixture:
        def __init__(self) -> None:
            self._session = TimeoutSession(30, policy=http._policy)
            self._retry = 3

        def get_news(self, request_params: Any) -> object:
            callback = self._session._before_request
            assert callback is not None
            callback()
            return {"news": []}

    news = AlpacaNewsProvider(
        Settings(_env_file=None), reader, NewsStore(ledger), client=NewsClientFixture()
    )
    await news.fetch(("AAPL",), clock.now() - timedelta(days=1), clock.now())
    await actions.fetch(("AAPL",), START, END)
    assert reader.bucket.available == 177


def test_DAT_06_corporate_reader_policy_cannot_use_wrong_plan(
    engine: Engine, clock: FrozenClock
) -> None:
    reader = AsyncAlpacaReader(clock, SystemStateStore(engine, clock, ConsoleNotifier()))
    with pytest.raises(DataIntegrityError):
        AlpacaCorporateActionsProvider(
            Settings(_env_file=None, alpaca_data_plan="ALGO_TRADER_PLUS"),
            reader,
            Ledger(engine, clock),
            client=FakeClient({}),
        )
    assert reader.state.current() == SystemState.HALTED
