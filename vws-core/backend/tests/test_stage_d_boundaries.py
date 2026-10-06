"""DAT-09/DAT-12/SEC-31: public citations, configured destinations and broker proof."""

import asyncio
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlunsplit

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.config import NewsConfig, Settings
from backend.core.content import headline_digest, headline_stable_id
from backend.core.database import NewsHeadlineRecord, PortfolioState, SchemaMeta, create_schema
from backend.core.errors import (
    DatabaseError,
    DataIntegrityError,
    LedgerIntegrityError,
    ProviderError,
)
from backend.core.ledger import Ledger
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.async_reader import AsyncAlpacaReader
from backend.data.boundary import ReadBoundary
from backend.data.liquidity import BalanceReading, FakeLiquiditySource, LiquidityGate
from backend.domain.models import PortfolioSnapshot
from backend.net.egress import build_allowlist
from backend.tests.test_broker_state import NOW, FakeClient, provider
from backend.tests.test_read_boundary import Broker, boundary


def news_fields(clock: FrozenClock, **changes: Any) -> dict[str, Any]:
    """DAT-09: exactly bound fixture public evidence, no account or raw article."""
    title = "Company reports annual results"
    digest = headline_digest(title)
    values: dict[str, Any] = {
        "provider": "FAKE",
        "provider_id": "headline-1",
        "headline": title,
        "headline_sha256": digest,
        "stable_id": headline_stable_id("FAKE", "headline-1", digest),
        "published_at": clock.now(),
        "details": {"symbols": ["AAPL"], "summary_allowed": True},
    }
    values.update(changes)
    return values


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "UNKNOWN"},
        {"provider_id": " bad"},
        {"provider_id": ""},
        {"provider_id": "x\n"},
        {"provider_id": "x" * 281},
        {"headline": "<b>Untrusted</b>"},
        {"headline": ""},
        {"headline": "x" * 281},
        {"headline_sha256": "a" * 64},
        {"stable_id": "b" * 64},
        {"stable_id": "no-digest"},
        {"details": {"symbols": ["aapl"], "summary_allowed": True}},
        {"details": {"symbols": ["AAPL", "AAPL"], "summary_allowed": True}},
        {"details": {"symbols": ["AAPL"], "summary_allowed": 1}},
        {"details": {"symbols": ["AAPL"]}},
        {"details": {"symbols": ["AAPL"], "summary_allowed": True, "cash": "100"}},
    ],
)
def test_DAT_09_invalid_news_cannot_enter_ledger(
    engine: Engine, clock: FrozenClock, changes: dict[str, Any]
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(DataIntegrityError):
        ledger.append(NewsHeadlineRecord, **news_fields(clock, **changes))
    ledger.verify_chain()
    with Session(engine) as session:
        assert session.scalar(select(NewsHeadlineRecord)) is None


def test_DAT_09_publication_time_and_digest_remain_bound(
    engine: Engine, clock: FrozenClock
) -> None:
    ledger = Ledger(engine, clock)
    with pytest.raises(DataIntegrityError, match="future"):
        ledger.append(
            NewsHeadlineRecord,
            **news_fields(clock, published_at=clock.now() + timedelta(seconds=1)),
        )
    digest = headline_digest("Company reports annual results")
    ledger.append(
        NewsHeadlineRecord,
        **news_fields(
            clock,
            provider_id=None,
            stable_id=headline_stable_id("FAKE", None, digest),
            details={"symbols": [], "summary_allowed": False},
        ),
    )
    ledger.verify_chain()
    with pytest.raises(LedgerIntegrityError):
        ledger.append(NewsHeadlineRecord, **news_fields(clock))
    ledger.verify_chain()


def test_R_02_old_schema_requires_explicit_migration(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(update(SchemaMeta).values(version=2))
    with pytest.raises(DatabaseError, match="incompatible"):
        create_schema(engine)
    with engine.connect() as connection:
        assert connection.scalar(select(SchemaMeta.version)) == 2


@pytest.mark.parametrize("reported", ["MARGIN", "UNKNOWN", None, 1, {}, ["CASH"]])
def test_DAT_12_reported_account_type_mismatch_halts_before_remaining_reads(
    engine: Engine, reported: object
) -> None:
    client = FakeClient()
    client.account["account_type"] = reported
    broker = provider(client)
    clock = FrozenClock(NOW)
    settings = Settings()
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    reads = ReadBoundary(
        settings,
        state,
        clock,
        broker,
        LiquidityGate(
            settings,
            FakeLiquiditySource(
                BalanceReading(
                    available=Decimal("3000"), current=Decimal("4000"), currency="USD", as_of=NOW
                )
            ),
            clock,
        ),
        account_id=client.account["id"],
    )
    with pytest.raises(DataIntegrityError):
        reads.portfolio()
    assert client.call_count == 1
    assert broker.last_flags is None
    assert state.current() == SystemState.HALTED
    assert SystemStateStore(engine, clock, ConsoleNotifier()).current() == SystemState.HALTED


def test_DAT_12_reported_account_type_matches_explicit_attestation() -> None:
    client = FakeClient()
    client.account["account_type"] = "CASH"
    assert provider(client).snapshot(NOW).account_type == "CASH"


@pytest.mark.parametrize(
    "url",
    [
        urlunsplit(("http", "news.example.com", "/rss", "", "")),
        "https://127.0.0.1/rss",
        "https://user:pass@news.example.com/rss",
        "https://news.example.com:8080/rss",
        "https://news.example.com/rss#secret",
        "https://news.example.com/\n",
    ],
)
def test_SEC_31_RSS_grants_reject_unsafe_destinations(url: str) -> None:
    with pytest.raises(ValidationError):
        NewsConfig(rss_urls=(url,))


def test_DAT_09_SEC_31_only_selected_public_provider_expands_egress() -> None:
    assert Settings().news_provider == "ALPACA"
    assert "newsapi.org" not in build_allowlist()
    assert "newsapi.org" in build_allowlist(news_provider="NEWSAPI")
    news = NewsConfig(rss_urls=("https://news.example.com/rss",))
    assert "news.example.com" in build_allowlist(rss_urls=news.rss_urls)
    with pytest.raises(ValidationError):
        NewsConfig(rss_urls=news.rss_urls * 2)


@pytest.mark.asyncio
async def test_DAT_08_account_and_funding_reads_use_shared_async_boundary(engine: Engine) -> None:
    reads = boundary(engine)
    reader = AsyncAlpacaReader(reads.clock, reads.state)
    account = await reads.portfolio_async(reader)
    funding = await reads.funding_async(reader, refresh=True)
    assert account.snapshot.account_id == reads.account_id
    assert funding.deployable == Decimal("1500")
    assert not reader.tripped and reads.state.current() == SystemState.RUNNING


@pytest.mark.asyncio
async def test_DAT_08_account_failure_in_worker_persists_halt(engine: Engine) -> None:
    reads = boundary(engine)
    reads.broker.last_flags = None
    reader = AsyncAlpacaReader(reads.clock, reads.state)
    with pytest.raises(DataIntegrityError):
        await reads.portfolio_async(reader)
    assert reader.tripped
    assert SystemStateStore(engine, reads.clock, ConsoleNotifier()).current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_DAT_08_late_account_read_never_publishes_portfolio_marks(engine: Engine) -> None:
    started, release = threading.Event(), threading.Event()

    class SlowBroker(Broker):
        def snapshot(self, now: datetime) -> PortfolioSnapshot:
            started.set()
            assert release.wait(3)
            return super().snapshot(now)

    reads = boundary(engine, broker=SlowBroker())
    reader = AsyncAlpacaReader(reads.clock, reads.state, deadline_seconds=0.2)
    task = asyncio.create_task(reads.portfolio_async(reader))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        with pytest.raises(ProviderError, match="deadline"):
            await task
        assert reader.tripped and reads.state.current() == SystemState.HALTED
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*reader._workers, return_exceptions=True), 3)
    with Session(engine) as session:
        assert session.scalar(select(PortfolioState)) is None
    reads.state.ledger.verify_chain()
