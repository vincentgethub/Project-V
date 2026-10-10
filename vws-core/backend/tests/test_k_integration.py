"""XK: host-facing goldens, private document binding and watch refusal."""

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from telegram import InputFile
from telegram.error import NetworkError

from backend.agents.briefing import PositionView
from backend.agents.desk import Desk
from backend.agents.jobs import ScanCycle
from backend.core.clock import FrozenClock
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EgressDeniedError,
    ExecutionDisabledError,
)
from backend.core.system_state import SystemState
from backend.domain.models import BlackoutWindow, Decision, MarketStatus
from backend.net.egress import EgressPolicy, build_allowlist
from backend.net.http import TelegramRequest
from backend.notifications.telegram_bot import TelegramBot
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.html_report import (
    REPORT_PREFIX,
    ReportSnapshot,
    html_report,
    monthly_csv,
    save_html,
    validate_report,
)
from backend.ops.journal import Journal
from backend.ops.k_runtime import ExtraControls, actual_resolved, tracker_outcomes
from backend.ops.macro_events import MacroCalendar
from backend.ops.trading_controls import ControlScope
from backend.ops.watch import WatchDesk
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_funding_and_pnl import golden
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness
from backend.tests.test_telegram_flow import API, make

harness = make_research_harness


def scope(h: Harness) -> ControlScope:
    return ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER")


def snapshot(h: Harness) -> ReportSnapshot:
    days = tuple(
        row.model_copy(
            update={
                "observation": row.observation.model_copy(
                    update={"account_id": scope(h).account_id}
                )
            }
        )
        for row in golden(FrozenClock(h.clock.now()))
    )
    spy = tuple(
        (date.fromisoformat(day), Decimal(price))
        for day, price in (
            ("2026-09-22", "100"),
            ("2026-09-23", "101"),
            ("2026-09-24", "102"),
            ("2026-09-25", "103"),
            ("2026-09-28", "104"),
        )
    )
    return ReportSnapshot(
        scope=scope(h),
        as_of=h.clock.now(),
        days=days,
        spy=spy,
        portfolio=h.request.portfolio,
        trades=(),
        tax=("ST -60.00; LT 0.00. Rates unset: totals only. Estimates; 1099-B wins.",),
        health=("MANUAL PAPER · healthy offline fixtures",),
        edge=("UNPROVEN: no real trading edge established",),
    )


def test_XK_08_html_and_monthly_csv_match_exact_accounting_golden(
    harness: Harness, tmp_path: Path
) -> None:
    source = snapshot(harness)
    payload = html_report(source)
    text = payload.decode()
    assert "Account TWR -1.00%; SPY 4.00%" in text
    assert "2026-09-25: $-160.00" in text and "ST -60.00; LT 0.00" in text
    assert all(token not in text.lower() for token in ("<script", "http:", "https:", "javascript:"))
    assert ReportSnapshot.recorded(source.model_dump(mode="json")) == source
    assert save_html(tmp_path, source).read_bytes() == payload
    csv = monthly_csv(source, "2026-09").decode()
    assert "day_pnl,-160" in csv and "TWR,-0.01" in csv and "SPY close (price only),104" in csv
    assert "tax_ytd" in csv and "health" in csv and "edge" in csv


@pytest.mark.parametrize(
    "attack",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        '<svg onload ="alert(1)"></svg>',
        '<meta http-equiv="refresh" content="0; url=secret">',
        '<style>@import "secret";</style>',
        "<iframe></iframe>",
        '<a href="secret">link</a>',
    ],
)
def test_XK_08_validator_refuses_active_content(attack: str) -> None:
    with pytest.raises(DataIntegrityError):
        validate_report(REPORT_PREFIX + attack.encode())


class Documents(API):
    def __init__(self) -> None:
        super().__init__()
        self.documents: list[bytes] = []

    async def http(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("sendDocument"):
            self.documents.append(await request.aread())
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "message_id": 654,
                        "date": 1790780400,
                        "chat": {"id": 123, "type": "private"},
                        "document": {
                            "file_id": "offline",
                            "file_unique_id": "offline-doc",
                            "file_name": "latest.html",
                            "mime_type": "text/html",
                        },
                    },
                },
            )
        return await super().http(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "stranger", "unadmitted", "unsafe", "other_file"])
async def test_XK_08_transport_sends_only_generated_private_html(
    harness: Harness, fault: str | None
) -> None:
    h, api = harness, Documents()
    policy = EgressPolicy(build_allowlist(), h.state.ledger)
    token = h.settings.telegram_bot_token.get_secret_value()
    bot = TelegramBot(
        h.settings,
        h.state,
        h.clock,
        h.gate,
        policy,
        {},
        transport=TelegramRequest(
            token, policy, transport=httpx.MockTransport(api.http), document_chats=(123,)
        ),
        polling_transport=TelegramRequest(token, policy, transport=httpx.MockTransport(api.http)),
    )
    await bot.application.initialize()
    bot._admitted = fault != "unadmitted"
    try:
        payload = html_report(snapshot(h))
        if fault in {"stranger", "unadmitted"}:
            with pytest.raises(ConfigurationError):
                await bot.document(999 if fault == "stranger" else 123, payload)
        elif fault == "unsafe":
            with pytest.raises(DataIntegrityError):
                await bot.document(123, b"<script>unsafe</script>")
        elif fault == "other_file":
            with pytest.raises(NetworkError) as denied:
                await bot.application.bot.send_document(
                    123, InputFile(b"secret", filename="private.txt")
                )
            assert isinstance(denied.value.__cause__, EgressDeniedError)
        else:
            await bot.document(123, payload)
            assert len(api.documents) == 1 and payload in api.documents[0]
    finally:
        await bot.application.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XK_09_immutable_watch_card_never_orders(harness: Harness) -> None:
    h = harness
    h.request = h.request.model_copy(update={"manual_only": True})
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    with pytest.raises(ExecutionDisabledError, match="watch"):
        await built.enter(alert.proposal_id)
    assert not client.posts and h.state.current() == SystemState.RUNNING
    bot = make(h, API())
    h.gate.bind_auto(built, built.modes)
    assert not bot._auto_eligible(alert) and "Read-only watch card" in bot._updated_card(alert)


@pytest.mark.asyncio
async def test_XK_09_ten_daily_requests_known_symbols_and_no_executor(harness: Harness) -> None:
    h = harness

    class Source:
        registry = h.swarm.risk.cro.registry
        calls = 0

        async def scan(self, symbols: tuple[str, ...]) -> ScanCycle:
            assert symbols == ("NVDA",)
            self.calls += 1
            return ScanCycle(as_of=h.clock.now(), symbols_scanned=1, requests=())

    source = Source()
    watch = WatchDesk(
        Desk(h.swarm),
        cast(ConnectedDeskSource, source),
        make(h, API()),
        Journal(h.state.ledger, scope(h)),
    )
    assert "instruments.csv" in (await watch("UNKNOWN", 123))[0]
    for _ in range(10):
        assert "no eligible setup" in (await watch("NVDA", 123))[0]
    assert "limit reached" in (await watch("NVDA", 123))[0] and source.calls == 10
    assert h.gate.executor is None
    with pytest.raises(DataIntegrityError):
        await watch("NVDA", 999)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["quiet", "pending", "macro", "halt"])
async def test_XK_07_briefing_silent_unless_something_matters(
    harness: Harness, tmp_path: Path, case: str
) -> None:
    h = harness
    path = tmp_path / "macro_events.csv"
    day = h.clock.now().date().isoformat()
    path.write_text(
        "date,et_time,event,source\n"
        + (
            f"{day},08:30,CPI,https://www.bls.gov/schedule/news_release/cpi.htm\n"
            if case == "macro"
            else ""
        )
    )
    stamp = h.clock.now().timestamp()
    os.utime(path, (stamp, stamp))

    async def daily(symbols: tuple[str, ...]) -> Any:
        assert symbols == ("SPY",)
        return SimpleNamespace(status_for=lambda *args: MarketStatus.OK)

    source = cast(
        ConnectedDeskSource, SimpleNamespace(calendar=h.swarm.risk.cro.calendar, daily=daily)
    )

    async def notice(text: str, urgent: bool) -> None:
        raise AssertionError("building briefing must not send")

    extras = ExtraControls(h.state.ledger, scope(h), h.config, source, MacroCalendar(path), notice)
    if case == "halt":
        h.state.escalate(SystemState.HALTED, "scratch overnight halt")
    text = await extras.briefing(
        PositionView(portfolio=h.request.portfolio, quotes=(), protections=()),
        int(case == "pending"),
    )
    assert (text is None) == (case == "quiet")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["macro", "mutable", "unbounded"])
async def test_XK_04_reuses_CRO_11_and_invalid_windows_halt(harness: Harness, case: str) -> None:
    h = harness
    result = await h.swarm.run(h.request)
    assert result.proposal is not None
    window = BlackoutWindow(
        start=h.clock.now() - timedelta(minutes=1),
        end=h.clock.now() + timedelta(minutes=1),
        reason="Macro CPI",
    )

    def callback() -> Any:
        return (
            (window,) if case == "macro" else (window,) * 501 if case == "unbounded" else [window]
        )

    h.swarm.risk.additional_blackouts = callback
    if case == "macro":
        verdict = h.swarm.risk.evaluate(
            result.proposal, h.request.portfolio, h.request.market, deployable=h.request.capital
        )
        assert verdict.decision == Decision.VETOED
        assert not next(rule for rule in verdict.results if rule.rule_id == "CRO-11").passed
    else:
        with pytest.raises(DataIntegrityError):
            h.swarm.risk.evaluate(
                result.proposal, h.request.portfolio, h.request.market, deployable=h.request.capital
            )
        assert h.state.current() == SystemState.HALTED


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XK_06_open_physical_trade_never_advances_ramp(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    await fill_entry(h, client, built)
    assert actual_resolved(h.state.ledger, scope(h)) == 0
    assert tracker_outcomes(h.state.ledger, scope(h)) == ()


@pytest.mark.parametrize("month", ["2026-9", "2026-13", "../config"])
def test_XK_08_month_requires_canonical_date(harness: Harness, month: str) -> None:
    with pytest.raises(DataIntegrityError):
        monthly_csv(snapshot(harness), month)
