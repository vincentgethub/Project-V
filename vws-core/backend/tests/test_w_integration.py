"""W: physical learning, scoped feed evidence and private command boundaries."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.config import LearningJournalConfig, LessonProposalConfig, Settings, YamlConfig
from backend.core.ledger import Ledger
from backend.data.fee_schedule import load_fee_schedule
from backend.learning.journal import Cause
from backend.learning.proposals import ProposalStore, mine
from backend.learning.service import LearningService
from backend.ops.macro_events import MacroCalendar
from backend.realtime.desk import RealtimeDesk
from backend.realtime.models import FeedHealth, HealthStatus
from backend.realtime.reader import RealtimeReader
from backend.realtime.schedules import Schedules
from backend.realtime.storage import RealtimeStore
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from backend.tests.test_telegram_security import Bot, MovingClock, guard
from backend.tests.test_v_verdict_source import SCOPE as PHYSICAL_SCOPE
from backend.tests.test_v_verdict_source import close_split_trade
from backend.tests.test_w_core import CAL, HASH, SCOPE, event, health
from backend.tests.test_w_learning_feeds import baseline as baseline
from backend.tests.test_w_learning_feeds import losses, proof_and_run

harness = make_research_harness
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_LJ_connected_actual_split_loss_is_one_trade_and_replay_dedupes(
    harness: Harness,
) -> None:
    h = harness
    await close_split_trade(h)
    learning = LearningService(
        h.state.ledger,
        PHYSICAL_SCOPE,
        h.config,
        CAL,
        load_fee_schedule(ROOT / "config/fees.yaml"),
        ROOT,
    )
    assert learning.sync() >= 2
    rows = learning.journal.rows()
    losses_seen = tuple(row for row in rows if row.trigger == "LOSS")
    assert len(losses_seen) == 1
    actual_r = losses_seen[0].observation.r_after_costs
    assert actual_r is not None and actual_r < 0
    assert all(row.cause_tag in {Cause.UNCLASSIFIED, Cause.SLIPPAGE_ABOVE_MODEL} for row in rows)
    assert len({row.observation.proposal_id for row in rows}) == 1
    frozen = learning.journal.replay()
    assert learning.sync() == 0 and learning.journal.replay() == frozen


def test_AC_cached_health_cannot_heal_newer_outage(engine: Engine, clock: FrozenClock) -> None:
    store = RealtimeStore(Ledger(engine, clock), SCOPE, HASH)
    old = health(clock.now() - timedelta(seconds=1))[0]
    store.mark(old)
    outage = FeedHealth(
        feed="clock",
        status=HealthStatus.UNAVAILABLE,
        observed_at=clock.now(),
        detail="Synthetic outage",
    )
    store.mark(outage)
    store.mark(old)
    assert store.health() == (outage,)


@pytest.mark.parametrize("command", ["/journal", "/lessons", "/events", "/regret"])
@pytest.mark.asyncio
async def test_W_commands_are_private_owner_only_and_heavy(engine: Engine, command: str) -> None:
    bot, clock = Bot(), MovingClock()
    security = guard(engine, clock, bot)
    assert not (
        await security.admit(user_id=999, chat_id=999, chat_type="private", command=command)
    ).accepted
    assert not (
        await security.admit(user_id=123, chat_id=-456, chat_type="group", command=command)
    ).accepted
    for _ in range(5):
        assert (
            await security.admit(user_id=123, chat_id=123, chat_type="private", command=command)
        ).accepted
    assert not (
        await security.admit(user_id=123, chat_id=123, chat_type="private", command=command)
    ).accepted


@pytest.mark.parametrize("status", ["DECLINED", "ABANDONED", "ACCEPTED_FOR_TESTING"])
def test_LP_host_review_remains_in_suggestions_never_reopens(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path, status: Any
) -> None:
    proof, run = proof_and_run(positive=True)
    proposed = mine(
        losses(clock.now(), 15),
        proof,
        (run,),
        baseline,
        LearningJournalConfig(),
        LessonProposalConfig(),
        calendar=CAL,
    ).proposals[0]
    (tmp_path / "docs").mkdir()
    (tmp_path / "data").mkdir()
    progress = tmp_path / "docs/PROGRESS.md"
    progress.write_text("# Progress\n## Suggestions\n", encoding="utf-8")
    store = ProposalStore(Ledger(engine, clock), SCOPE)
    assert store.publish(proposed, tmp_path)
    store.resolve_review(proposed.id, status, "fixture owner", tmp_path)
    assert store.open() == () and status in progress.read_text(encoding="utf-8")
    assert not store.publish(proposed, tmp_path)
    assert "OPEN, awaiting" not in progress.read_text(encoding="utf-8")
    assert not (tmp_path / "config").exists()


def test_LP_duplicate_at_progress_line_limit_is_still_idempotent(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path
) -> None:
    proof, run = proof_and_run(positive=True)
    proposed = mine(
        losses(clock.now(), 15),
        proof,
        (run,),
        baseline,
        LearningJournalConfig(),
        LessonProposalConfig(),
        calendar=CAL,
    ).proposals[0]
    (tmp_path / "docs").mkdir()
    (tmp_path / "data").mkdir()
    progress = tmp_path / "docs/PROGRESS.md"
    progress.write_text("# Progress\n## Suggestions\n" + "line\n" * 57, encoding="utf-8")
    store = ProposalStore(Ledger(engine, clock), SCOPE)
    assert store.publish(proposed, tmp_path)
    assert len(progress.read_text(encoding="utf-8").splitlines()) == 60
    assert not store.publish(proposed, tmp_path)


def test_RT_missing_macro_is_warning_manual_and_block_auto(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path
) -> None:
    config = baseline
    store = RealtimeStore(Ledger(engine, clock), SCOPE, config.config_hash)
    schedules = Schedules(
        store.ledger, MacroCalendar(tmp_path / "missing.csv"), tmp_path / "events_policy.yaml"
    )
    for row in health(clock.now()):
        store.mark(row)
    desk = RealtimeDesk(store, config, CAL, schedules, lambda: False)
    assert not desk.context("NVDA").blocked and desk.context("NVDA").warnings
    desk.automatic = lambda: True
    assert desk.context("NVDA").blocked


@pytest.mark.parametrize("kind", ["HALT", "HALT_NEWS", "NEWS_NEG", "DILUTION", "DELIST"])
def test_RT_hard_exit_only_confirmed_configured_events(
    engine: Engine, clock: FrozenClock, baseline: YamlConfig, tmp_path: Path, kind: str
) -> None:
    store = RealtimeStore(Ledger(engine, clock), SCOPE, baseline.config_hash)
    schedules = Schedules(
        store.ledger, MacroCalendar(tmp_path / "missing.csv"), tmp_path / "events_policy.yaml"
    )
    desk = RealtimeDesk(store, baseline, CAL, schedules, lambda: True)
    row = event(clock.now(), kind=kind, feed="ca" if kind == "DELIST" else "news")
    store.receive(row)
    result = desk.hard_exit("NVDA", clock.now() - timedelta(days=1))
    assert (result is not None) == (kind == "DELIST")
    if result:
        assert result == ("DELIST", store.key(row))
    assert desk.hard_exit("NVDA", clock.now() + timedelta(seconds=1)) is None


@pytest.mark.parametrize("key", ["LJ", "LP", "RT", "EVENTS_POLICY", "MIN_TAG_N", "CLOCK_SKEW_MS"])
def test_W_yaml_settings_cannot_silently_use_environment(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv(key, "1")
    with pytest.raises(ValidationError, match="YAML-only"):
        Settings(_env_file=None, broker_account_type="CASH")


@pytest.mark.asyncio
async def test_RT_FRED_success_cache_does_not_poll_again_before_session_close(
    clock: FrozenClock,
) -> None:
    calls = []
    expected = CAL.last_completed_session(clock.now())

    async def observed(key: object) -> dict[str, object]:
        calls.append(key)
        return {"observations": [{"date": expected.isoformat(), "value": "20"}]}

    reader: Any = RealtimeReader.__new__(RealtimeReader)
    reader.clock, reader.calendar = clock, CAL
    reader.fred_key = SecretStr("PUBLIC_SYNTHETIC_FRED_FIXTURE")
    reader.reads = SimpleNamespace(fred_observations=observed)
    reader._fred_day, reader._cache = None, {}
    first = await reader.poll("fred")
    second = await reader.poll("fred")
    assert len(calls) == 1 and first == second
