"""RT: fake pinned adapters, cache/budget boundaries and public-only wording."""

from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.engine import Engine

from backend.agents.llm_client import Narrative
from backend.core.clock import FrozenClock
from backend.core.config import RealtimeConfig, Settings
from backend.core.errors import ProviderError
from backend.core.ledger import Ledger
from backend.learning.journal import MistakeJournal
from backend.learning.narrative import enrich
from backend.realtime.models import HealthStatus
from backend.realtime.reader import RealtimeReader
from backend.realtime.storage import RealtimeStore
from backend.tests.test_w_core import CAL, HASH, SCOPE, event, observation


class Reads:
    def __init__(self, ledger: Ledger) -> None:
        self.clock, self.policy = ledger.clock, SimpleNamespace(ledger=ledger)
        self.calls: list[tuple[str, dict[str, str] | None]] = []
        self.news: dict[str, Any] = {"news": [], "next_page_token": None}

    def broker_headers(self, key: object, secret: object) -> dict[str, str]:
        return {"FIXTURE": "PUBLIC_SYNTHETIC"}

    async def _get(
        self, purpose: str, url: str, *, headers: object, params: dict[str, str] | None
    ) -> dict[str, Any]:
        self.calls.append((url, params))
        if url.endswith("/news"):
            return self.news
        if "/assets/" in url:
            return {"symbol": url.rsplit("/", 1)[-1], "tradable": True, "status": "active"}
        if url.endswith("/corporate-actions"):
            return {"corporate_actions": {}, "next_page_token": None}
        raise AssertionError("Unexpected readonly endpoint")


def reader(engine: Engine, clock: FrozenClock) -> RealtimeReader:
    ledger = Ledger(engine, clock)
    store = RealtimeStore(ledger, SCOPE, HASH)
    reads: Any = Reads(ledger)

    async def symbols() -> tuple[str, ...]:
        return ("NVDA",)

    async def verify() -> object:
        return SimpleNamespace(
            timestamp=clock.now() + timedelta(microseconds=501000),
            sampled_start=clock.now(),
            sampled_end=clock.now(),
        )

    verifier: Any = SimpleNamespace(state=SimpleNamespace(engine=engine), verify=verify)
    macro: Any = SimpleNamespace(read=lambda: ())
    return RealtimeReader(
        Settings(_env_file=None, broker_account_type="CASH"),
        RealtimeConfig(),
        reads,
        store,
        verifier,
        CAL,
        symbols,
        symbols,
        macro,
        lambda: True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("feed", ["clock", "assets", "news", "ca", "macro"])
async def test_RT_bound_readonly_adapters_have_causal_heartbeat(
    engine: Engine, clock: FrozenClock, feed: Any
) -> None:
    value = reader(engine, clock)
    fake = cast(Reads, value.reads)
    status, events = await value.poll(feed)
    assert status.observed_at == clock.now()
    assert status.status == (HealthStatus.DEGRADED if feed == "clock" else HealthStatus.OK)
    if feed == "assets":
        assert status.symbols == ("NVDA",) and events[0].kind == "ASSET_ACTIVE"
    if feed == "news":
        params = fake.calls[0][1]
        assert params is not None and params["limit"] == "50"
    if feed == "ca":
        before = len(fake.calls)
        assert await value.poll("ca") == (status, events)
        assert len(fake.calls) == before
    await value.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("feed", ["edgar", "fred"])
async def test_RT_missing_credentials_stay_unavailable(
    engine: Engine, clock: FrozenClock, feed: Any
) -> None:
    with pytest.raises(ProviderError, match="setup"):
        await reader(engine, clock).poll(feed)


@pytest.mark.asyncio
async def test_RT_news_page_cap_never_certifies_partial_coverage(
    engine: Engine, clock: FrozenClock
) -> None:
    value = reader(engine, clock)
    fake = cast(Reads, value.reads)
    fake.news = {"news": [], "next_page_token": "fixture-more"}
    with pytest.raises(ProviderError, match="bound exhausted"):
        await value.poll("news")
    assert len(fake.calls) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_LJ_optional_writer_receives_only_public_text_and_never_selects_tag(
    engine: Engine, clock: FrozenClock, fails: bool
) -> None:
    ledger = Ledger(engine, clock)
    journal = MistakeJournal(ledger, SCOPE)
    journal.record(observation(clock.now()))
    store = RealtimeStore(ledger, SCOPE, HASH)
    public = event(
        clock.now(),
        kind="NEWS_NEG",
        feed="news",
        text="Public issuer reports a securities offering.",
    )
    store.receive(public)
    original_cause = journal.rows()[0].cause_tag

    class Writer:
        async def complete_json(self, name: str, payload: Any, schema: object) -> Narrative | None:
            assert set(payload.model_dump()) == {
                "ticker",
                "headlines",
                "public_fundamentals",
                "public_filing_ids",
            }
            assert SCOPE.account_id not in payload.model_dump_json()
            assert (
                "r_after_costs" not in payload.model_dump_json()
                and "qty" not in payload.model_dump_json()
            )
            if fails:
                raise ProviderError("Fixture offline writer")
            return Narrative(
                summary="Public filing context needs owner review.",
                evidence_ids=(payload.headlines[0].stable_id,),
            )

    assert await enrich(journal, store, Writer()) == 1
    assert journal.rows()[0].cause_tag == original_cause
    assert journal.rows()[0].narrative is not None
    frozen = journal.replay()
    assert await enrich(journal, store, Writer()) == 0 and journal.replay() == frozen
