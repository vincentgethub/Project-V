"""EV/ER: actual weekly job, local report proof, masking and no external sends."""

import asyncio
import threading
from datetime import UTC, datetime
from decimal import Decimal
from html import unescape
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.agents.briefing import DeskCommands, PositionView
from backend.core.clock import FrozenClock
from backend.core.config import Settings, load_yaml_config
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.fee_schedule import load_fee_schedule
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.domain.tax_profile import TaxProfile
from backend.evaluation.evidence import OutcomeEvidence
from backend.evaluation.outcomes import Outcome
from backend.evaluation.publication import WeeklyInputs, WeeklyPublisher
from backend.evaluation.weekly import WeeklyReport, build_weekly_report, save_report
from backend.tests import test_edge as edge_golden
from backend.tests import test_weekly_equity as golden

calendar = golden.calendar
history = golden.history
results = golden.results
edge_outcomes = edge_golden.outcomes


class Source:
    def __init__(self, values: WeeklyInputs) -> None:
        self.values = values

    async def weekly_inputs(self) -> WeeklyInputs:
        return self.values

    async def read(self) -> PositionView:
        raise DataIntegrityError("This test has no broker holdings source")


class Notices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    async def notify(self, text: str, urgent: bool) -> None:
        self.calls.append((text, urgent))


def composition(
    engine: Engine,
    root: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
) -> tuple[WeeklyPublisher, Source, Notices]:  # noqa: F811
    project = Path(__file__).resolve().parents[2]
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    state = SystemStateStore(
        engine, FrozenClock(datetime(2026, 10, 8, 21, tzinfo=UTC)), ConsoleNotifier()
    )
    source = Source(
        WeeklyInputs(
            context=golden.context(config_sha256=config.config_hash),
            outcomes=results,
            history=history,
            fees=load_fee_schedule(project / "config/fees.yaml"),
            cost_policy=config.cm,
            tax_profile=TaxProfile(),
        )
    )
    notices = Notices()
    return (
        WeeklyPublisher(
            state,
            Settings(telegram_mask_amounts=True),
            config,
            "paper-test",
            calendar,
            root,
            source,
            notices.notify,
        ),
        source,
        notices,
    )


@pytest.mark.asyncio
async def test_EV_02_actual_job_publishes_account_bound_proof_and_private_edge(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
) -> None:  # noqa: F811
    publisher, source, notices = composition(engine, tmp_path, calendar, history, results)
    publisher.state.escalate(SystemState.HALTED, "entries halted; reports still available")
    counts = await publisher()
    assert counts.counts == {"report_cards": 2, "resolved": 5}
    assert notices.calls and all(not urgent for _, urgent in notices.calls)
    with Session(engine) as session:
        event = session.scalar(select(SecurityEvent).where(SecurityEvent.kind == "WEEKLY_REPORT"))
        assert event is not None
        report = WeeklyReport.from_recorded(event.detail["report"])
        evidence = OutcomeEvidence.from_recorded(event.detail["outcome_evidence"])
        assert evidence.sha256 == event.detail["outcomes_sha256"] and len(evidence.outcomes) == 5
        assert (tmp_path / event.detail["outcomes_filename"]).is_file()
        assert (
            report.sha256 == event.detail["report_sha256"]
            and event.detail["account_id"] == "paper-test"
        )
    commands = DeskCommands(publisher.state, publisher.settings, "paper-test", calendar, source)
    text = unescape("\n".join(await commands.edge("")))
    assert "UNPROVEN" in text and "too few trades to judge" in text and "$•••" in text
    assert "/edge" in commands.handlers() and "/edge" in "".join(await commands.help(""))
    other = DeskCommands(publisher.state, publisher.settings, "another-paper", calendar, source)
    assert "No weekly report" in "".join(await other.report(""))
    assert publisher.state.current() == SystemState.HALTED
    unmasked = DeskCommands(
        publisher.state,
        publisher.settings.model_copy(update={"telegram_mask_amounts": False}),
        "paper-test",
        calendar,
        source,
    )
    assert "$•••" not in unescape("\n".join(await unmasked.report("")))
    assert tuple(Outcome.from_recorded(item.model_dump(mode="json")) for item in results) == results
    publisher.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_EV_02_corrupt_report_proof_is_refused(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # noqa: F811
    publisher, source, _ = composition(engine, tmp_path, calendar, history, results)
    await publisher()
    original = Session.scalar

    def injected(session: Session, *args: Any, **kwargs: Any) -> Any:
        row = original(session, *args, **kwargs)
        if isinstance(row, SecurityEvent) and row.kind == "WEEKLY_REPORT":
            row.detail = {**row.detail, "outcomes_sha256": "f" * 64}
        return row

    monkeypatch.setattr(Session, "scalar", injected)
    commands = DeskCommands(publisher.state, publisher.settings, "paper-test", calendar, source)
    with pytest.raises(DataIntegrityError):
        await commands.edge("")
    publisher.state.ledger.verify_chain()


def test_EV_02_cancellation_after_files_never_claims_publication(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # noqa: F811
    import backend.evaluation.publication as module

    publisher, source, _ = composition(engine, tmp_path, calendar, history, results)
    canceled = threading.Event()
    original = save_report

    def stopped(*args: Any, **kwargs: Any) -> tuple[Path, Path]:
        paths = original(*args, **kwargs)
        canceled.set()
        return paths

    monkeypatch.setattr(module, "save_report", stopped)
    with pytest.raises(DataIntegrityError):
        publisher._publish(source.values, canceled)
    with Session(engine) as session:
        assert (
            session.scalar(select(SecurityEvent).where(SecurityEvent.kind == "WEEKLY_REPORT"))
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["account", "mode", "config", "policy", "future", "notify"])
async def test_EV_02_bad_publication_halts_and_never_claims_a_good_run(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    fault: str,
) -> None:  # noqa: F811
    publisher, source, notices = composition(engine, tmp_path, calendar, history, results)
    if fault in {"account", "mode", "config"}:
        changes = (
            {"account_id": "other"}
            if fault == "account"
            else ({"cohort": "LIVE"} if fault == "mode" else {"config_sha256": "f" * 64})
        )
        source.values = source.values.model_copy(
            update={"context": source.values.context.model_copy(update=changes)}
        )
    elif fault == "policy":
        source.values = source.values.model_copy(
            update={
                "cost_policy": source.values.cost_policy.model_copy(
                    update={"max_participation": Decimal(".005")}
                )
            }
        )
    elif fault == "future":
        publisher.state.clock = FrozenClock(datetime(2026, 10, 7, 21, tzinfo=UTC))
    else:

        async def failing_notify(text: str, urgent: bool) -> None:
            raise RuntimeError("offline injected delivery failure")

        publisher.notify = failing_notify
    with pytest.raises(DataIntegrityError):
        await publisher()
    assert publisher.state.current() == SystemState.HALTED and not notices.calls
    with Session(engine) as session:
        records = tuple(
            session.scalars(select(SecurityEvent).where(SecurityEvent.kind == "WEEKLY_REPORT"))
        )
        assert len(records) == (1 if fault == "notify" else 0)


@pytest.mark.asyncio
async def test_EV_02_cancellation_prevents_worker_publication(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # noqa: F811
    import backend.evaluation.publication as module

    publisher, _, notices = composition(engine, tmp_path, calendar, history, results)
    original = build_weekly_report
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow(*args: Any, **kwargs: Any) -> WeeklyReport:
        entered.set()
        if not release.wait(5):
            raise RuntimeError("test release timed out")
        try:
            return original(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(module, "build_weekly_report", slow)
    task = asyncio.create_task(publisher())
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    assert await asyncio.to_thread(finished.wait, 5)
    assert publisher.state.current() == SystemState.HALTED and not notices.calls
    assert not list(tmp_path.glob("weekly_*"))


def test_EV_02_recorded_payloads_do_not_accept_inexact_prices(results: tuple[Outcome, ...]) -> None:  # noqa: F811
    raw = results[0].model_dump(mode="json")
    raw["setup"]["limit"] = 8.0
    with pytest.raises(DataIntegrityError):
        Outcome.from_recorded(raw)
    with pytest.raises(DataIntegrityError):
        WeeklyReport.from_recorded({})


def test_EV_02_publisher_requires_an_account(
    engine: Engine,
    tmp_path: Path,
    calendar: MarketCalendar,
    history: FrozenHistory,
    results: tuple[Outcome, ...],
) -> None:  # noqa: F811
    publisher, source, notices = composition(engine, tmp_path, calendar, history, results)
    with pytest.raises(ConfigurationError):
        WeeklyPublisher(
            publisher.state,
            publisher.settings,
            publisher.config,
            "",
            calendar,
            tmp_path,
            source,
            notices.notify,
        )
