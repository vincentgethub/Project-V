"""XK-07/08: immutable document queues, source health and real accounting projection."""

import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import PositionView
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, LedgerIntegrityError
from backend.data.data_layer import Bar, BatchBars, SymbolBars, _bars_digest, _eligible_session
from backend.domain.models import MarketStatus
from backend.ops import k_runtime
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.html_report import validate_report
from backend.ops.k_runtime import ExtraControls
from backend.ops.macro_events import MacroCalendar
from backend.ops.report_publisher import ReportPublisher
from backend.ops.trading_controls import ControlScope
from backend.tests.test_auto_execution import AUTO
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness

harness = make_research_harness


def publisher(h: Harness, root: Path) -> tuple[ReportPublisher, list[bytes]]:
    calls: list[bytes] = []

    async def positions() -> PositionView:
        return PositionView(portfolio=h.request.portfolio, quotes=(), protections=())

    async def summary(*args: Any) -> tuple[str, ...]:
        return ("Offline estimate; 1099-B wins.",)

    async def document(owner: int, payload: bytes) -> None:
        assert owner == 123
        validate_report(payload)
        calls.append(payload)

    source: Any = SimpleNamespace(positions=positions)
    account: Any = SimpleNamespace(
        state=h.state,
        calendar=h.swarm.risk.cro.calendar,
        tax=SimpleNamespace(book=lambda: SimpleNamespace(fills=())),
        tax_summary=summary,
    )
    commands: Any = SimpleNamespace(status=summary, edge=summary)
    bot: Any = SimpleNamespace(settings=h.settings, document=document)
    scope = ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER")
    return ReportPublisher(root, scope, account, source, commands, bot, lambda: ()), calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["now", "quiet", "wrong_scope", "missing_report", "future"])
async def test_XK_08_capture_and_bound_queue_restart(
    harness: Harness, tmp_path: Path, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    h.clock.current = h.clock.now().replace(hour=20)
    if case == "quiet":
        h.clock.current = h.clock.now().replace(hour=3) + timedelta(days=1)
    built, calls = publisher(h, tmp_path)
    if case in {"now", "quiet"}:
        await built.weekly()
        assert (len(calls) == 0) == (case == "quiet")
        assert (tmp_path / "latest.html").is_file()
        h.clock.current += timedelta(hours=17) if case == "quiet" else timedelta(seconds=1)
        await built.flush()
        await built.flush()
        assert len(calls) == 1
        with Session(h.state.engine) as session:
            report = session.scalar(
                select(SecurityEvent).where(SecurityEvent.kind == "NIGHTLY_HTML_REPORT")
            )
            assert report is not None and built._bytes(report.id) == calls[0]
    else:
        report = await built.capture()
        h.state.ledger.append(
            SecurityEvent,
            kind="HTML_REPORT_DOCUMENT_PENDING",
            detail={
                "scope": {
                    "account_id": "foreign" if case == "wrong_scope" else built.scope.account_id,
                    "environment": "PAPER",
                },
                "report_id": str(report.id if case != "missing_report" else uuid4()),
            },
        )
        if case == "future":
            h.clock.current -= timedelta(seconds=1)
        if case == "wrong_scope":
            await built.flush()
        else:
            with pytest.raises((DataIntegrityError, LedgerIntegrityError)):
                await built.flush()
        assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["healthy", "stale", "unavailable"])
async def test_XK_07_stale_source_matters_without_holdings(
    harness: Harness, tmp_path: Path, case: str
) -> None:
    h = harness
    path = tmp_path / "macro_events.csv"
    path.write_text("date,et_time,event,source\n")
    os.utime(path, (h.clock.now().timestamp(), h.clock.now().timestamp()))

    async def daily(symbols: tuple[str, ...]) -> Any:
        if case == "unavailable":
            raise DataIntegrityError("fake unavailable")
        return SimpleNamespace(
            status_for=lambda *args: MarketStatus.OK if case == "healthy" else MarketStatus.SUSPECT
        )

    async def notify(text: str, urgent: bool) -> None:
        raise AssertionError("no send in projection")

    source = cast(ConnectedDeskSource, SimpleNamespace(daily=daily))
    extras = ExtraControls(
        h.state.ledger,
        ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER"),
        h.config,
        source,
        MacroCalendar(path),
        notify,
    )
    result = await extras.briefing(
        PositionView(portfolio=h.request.portfolio, quotes=(), protections=()), 0
    )
    assert (result is None) == (case == "healthy")


@pytest.mark.asyncio
async def test_XK_06_missing_equity_baseline_cannot_raise_ramp(
    harness: Harness, tmp_path: Path
) -> None:
    h = harness

    async def notify(text: str, urgent: bool) -> None:
        raise AssertionError("invalid baseline cannot send a step notice")

    extras = ExtraControls(
        h.state.ledger,
        ControlScope(account_id=h.request.portfolio.account_id, environment="LIVE"),
        h.config,
        cast(ConnectedDeskSource, object()),
        MacroCalendar(tmp_path / "missing.csv"),
        notify,
    )
    with pytest.raises(DataIntegrityError):
        await extras.observe_ramp(
            h.request.portfolio.model_copy(update={"high_water_mark": Decimal(0)})
        )


def test_XK_04_missing_calendar_warning_is_typed(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    with pytest.raises(DataIntegrityError):
        MacroCalendar(tmp_path / "missing.csv").warnings(datetime(2026, 10, 9, tzinfo=UTC))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["normal", "half", "no_new_entries", "paused", "unknown"])
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XK_03_05_host_sizing_uses_actual_signal_and_SPY(
    harness: Harness, tmp_path: Path, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.core.config import RegimeFilterConfig
    from backend.core.errors import ExecutionDisabledError

    h = harness
    result = await h.swarm.run(h.request)
    assert result.proposal is not None

    calendar, registry = h.swarm.risk.cro.calendar, h.swarm.risk.cro.registry
    tail = _eligible_session(calendar, h.clock.now(), h.config.schedule.daily_scan_delay_minutes)
    dates = (*calendar.previous_sessions(tail, 249), tail)
    source: Any = SimpleNamespace(
        settings=h.settings, calendar=calendar, registry=registry, _batch=None
    )

    async def daily(symbols: tuple[str, ...]) -> Any:
        bars = tuple(
            Bar(
                timestamp=calendar.session_open(day) - timedelta(hours=5, minutes=30),
                open=Decimal(100),
                high=Decimal(101),
                low=Decimal(99),
                close=Decimal(101 if case == "normal" else 99) if index == 249 else Decimal(100),
                volume=1000000,
            )
            for index, day in enumerate(dates)
        )
        source._batch = BatchBars(
            as_of=h.clock.now(),
            through=tail,
            entries=tuple(
                SymbolBars(
                    symbol=symbol,
                    adjustment=adjustment,
                    bars=bars,
                    status=MarketStatus.SUSPECT if case == "unknown" else MarketStatus.OK,
                    data_sha256=_bars_digest(bars)[0],
                )
                for symbol in ("NVDA", "SPY")
                for adjustment in ("SPLIT", "ALL")
            ),
        )
        return source._batch

    source.daily = daily

    async def notify(text: str, urgent: bool) -> None:
        raise AssertionError("paper sizing cannot raise live ramp")

    policy = h.config.model_copy(
        update={
            "regime_filter": RegimeFilterConfig(
                auto="no_new_entries" if case == "no_new_entries" else "half_size"
            )
        }
    )
    extras = ExtraControls(
        h.state.ledger,
        ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER"),
        policy,
        cast(ConnectedDeskSource, source),
        MacroCalendar(tmp_path / "missing.csv"),
        notify,
    )
    if case == "paused":
        extras.controls.evaluate_playbook(h.request.candidate.playbook, (Decimal(-1),) * 30)
        rows = tuple(
            SimpleNamespace(
                status="RESOLVED",
                setup=SimpleNamespace(
                    playbook=h.request.candidate.playbook,
                    variant="baseline",
                    disposition="APPROVED",
                ),
                r_multiple=Decimal(-1),
            )
            for _ in range(30)
        )
        monkeypatch.setattr(k_runtime, "tracker_outcomes", lambda *args: rows)
    if case in {"paused", "unknown"}:
        with pytest.raises(ExecutionDisabledError if case == "paused" else DataIntegrityError):
            await extras.size(result.proposal, await h.source.refresh(result.proposal.symbol))
    else:
        assert result.proposal.size_evidence is not None
        quantity = await extras.size(
            result.proposal, await h.source.refresh(result.proposal.symbol)
        )
        assert quantity == (
            result.proposal.qty
            if case == "normal"
            else 0
            if case == "no_new_entries"
            else min(result.proposal.qty, result.proposal.size_evidence.base_qty // 2)
        )
