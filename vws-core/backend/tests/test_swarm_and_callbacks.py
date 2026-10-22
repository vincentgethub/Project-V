"""GD-03/06: recorded evidence, forged clicks, fresh checks and replay races."""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.agents.flow_tracker import FlowTracker
from backend.agents.indicators import IndicatorMemo
from backend.agents.llm_client import FakeLLMClient
from backend.agents.news_reader import NewsReader
from backend.agents.setup_hunter import SetupHunter
from backend.agents.swarm_runner import ResearchRequest, SwarmRunner
from backend.core.config import Settings, YamlConfig, load_yaml_config
from backend.core.database import (
    Alert,
    AlertEvent,
    ApprovalEvent,
    DataSnapshot,
    ResearchReport,
    SecurityEvent,
    SystemControl,
    SystemEvent,
    TicketEvent,
    TradeTicket,
)
from backend.core.errors import (
    ConfigurationError,
    DataIntegrityError,
    EgressDeniedError,
    ProviderError,
)
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemState, SystemStateStore
from backend.data.data_layer import AsyncAlpacaMarketData, Bar, _bars_digest
from backend.data.market_calendar import MarketCalendar
from backend.data.news import NewsProviderName, NewsResult
from backend.domain.compliance_models import ExternalAccount, TaxStatus
from backend.domain.instruments import InstrumentRegistry
from backend.domain.models import (
    AccountFlags,
    AccountType,
    CapitalStatus,
    DeployableCapital,
    MarketContext,
    MarketStatus,
    PortfolioSnapshot,
    ProviderStatus,
    TradeProposal,
)
from backend.notifications.callbacks import ApprovalGate, CallbackClick, FreshInputs, callback_data
from backend.notifications.card_formatter import details_cards, ticket_card
from backend.risk.boundary import RiskBoundary
from backend.risk.compliance import ComplianceEngine
from backend.risk.compliance_boundary import ComplianceBoundary
from backend.risk.portfolio_marks import PersistedPortfolioMarks
from backend.risk.risk_cro import ChiefRiskOfficer


class MovingClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class Source:
    def __init__(self, inputs: FreshInputs) -> None:
        self.inputs, self.calls = inputs, 0
        self.error: Exception | None = None
        self.hook: Any = None

    async def refresh(self, symbol: str) -> FreshInputs:
        self.calls += 1
        if self.hook is not None:
            self.hook()
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return self.inputs


class News:
    def __init__(self, now: datetime) -> None:
        self.now, self.calls = now, 0
        self.error: Exception | None = None

    async def fetch(self, symbols: tuple[str, ...], start: datetime, end: datetime) -> NewsResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return NewsResult(
            provider=NewsProviderName.FAKE,
            status=ProviderStatus.UNAVAILABLE,
            as_of=end,
            reason="offline no public headlines",
        )


@dataclass
class Harness:
    settings: Settings
    config: YamlConfig
    clock: MovingClock
    state: SystemStateStore
    swarm: SwarmRunner
    request: ResearchRequest
    source: Source
    news: News
    gate: ApprovalGate


@pytest.fixture(name="harness")
def make_research_harness(engine: Engine, request: pytest.FixtureRequest) -> Harness:
    project = Path(__file__).resolve().parents[2]
    fixture = json.loads((project / "backend/tests/fixtures/offline_nvda.json").read_text())
    clock = MovingClock(datetime.fromisoformat(fixture["as_of"]))
    settings = Settings(
        broker_account_type=AccountType.CASH,
        telegram_bot_token=SecretStr("123:fixture"),
        telegram_allowed_user_ids=(123,),
        telegram_callback_secret=SecretStr("offline-key-" * 4),
        **getattr(request, "param", {}),
    )
    registry = InstrumentRegistry.from_csv(project / "config")
    config = load_yaml_config(project / "config/config.yaml", allowed_symbols=registry.symbols)
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    calendar = MarketCalendar()
    risk = RiskBoundary(
        ChiefRiskOfficer(settings, registry, calendar),
        state,
        clock,
        marks=PersistedPortfolioMarks(state.ledger, "offline-paper", calendar, settings),
    )
    compliance = ComplianceBoundary(ComplianceEngine(settings, registry, calendar), state, clock)
    bars = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in fixture["bars"])
    portfolio = PortfolioSnapshot(
        account_id="offline-paper",
        account_type=AccountType.CASH,
        as_of=clock.now(),
        equity=Decimal(10000),
        cash=Decimal(10000),
        settled_cash=Decimal(10000),
        positions={},
        open_orders=(),
        high_water_mark=Decimal(10000),
        day_start_equity=Decimal(10000),
    )
    market = MarketContext(
        last_price=bars[-1].close,
        last_price_ts=clock.now(),
        adv20_usd=Decimal(100000000),
        status=MarketStatus.OK,
    )
    capital = DeployableCapital(
        checking_used=Decimal(5000),
        buffer=Decimal(1500),
        reserved=Decimal(0),
        deployable=Decimal(3500),
        status=CapitalStatus.OK,
    )
    flags = AccountFlags(
        trading_blocked=False, account_blocked=False, trade_suspended_by_user=False, status="ACTIVE"
    )
    accounts = (ExternalAccount(account_id=portfolio.account_id, tax_status=TaxStatus.TAXABLE),)
    memo = IndicatorMemo()
    candidate = (
        SetupHunter(risk.cro, config, memo)
        .hunt("NVDA", bars, portfolio, market, clock.now())
        .candidates[0]
    )
    recorded = state.ledger.append(
        DataSnapshot,
        symbol="NVDA",
        timeframe="1Day",
        feed="SIP",
        adjustment="SPLIT",
        fetched_at=clock.now(),
        range_start=bars[0].timestamp,
        range_end=bars[-1].timestamp,
        bar_count=len(bars),
        sha256=_bars_digest(bars)[0],
        bars=[row.model_dump(mode="json") for row in bars],
    )
    research_request = ResearchRequest(
        candidate=candidate,
        data_snapshot_id=recorded.id,
        portfolio=portfolio,
        market=market,
        capital=capital,
        flags=flags,
        tax_accounts=accounts,
    )
    news = News(clock.now())
    swarm = SwarmRunner(
        settings,
        config,
        risk,
        compliance,
        state,
        clock,
        NewsReader(settings, FakeLLMClient()),
        news=news,
        memo=memo,
    )
    source = Source(
        FreshInputs(
            quote_feed="IEX",
            portfolio=portfolio,
            market=market,
            capital=capital,
            flags=flags,
            tax_accounts=accounts,
        )
    )
    gate = ApprovalGate(settings, config, state, risk, compliance, clock, source)
    return Harness(settings, config, clock, state, swarm, research_request, source, news, gate)


def count(h: Harness, model: Any) -> int:
    with Session(h.state.engine) as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


async def deliver(h: Harness) -> Alert:
    result = await h.swarm.run(h.request)
    assert result.status == "ALERT" and result.alert_id is not None
    with Session(h.state.engine) as session:
        alert = session.get(Alert, result.alert_id)
        assert alert is not None
    h.state.ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=123,
        telegram_message_id=456,
        reason="fake offline delivery",
    )
    return alert


def click(h: Harness, action: str, **changes: Any) -> CallbackClick:
    from typing import cast

    from backend.notifications.callbacks import Action

    values = dict(
        user_id=123,
        chat_id=123,
        message_id=456,
        chat_type="private",
        data=callback_data(cast(Action, action), proposal(h), 123, h.settings),
    )
    return CallbackClick.model_validate({**values, **changes})


def proposal(h: Harness) -> Any:
    with Session(h.state.engine) as session:
        alert = session.scalar(select(Alert))
        assert alert is not None
        return alert.proposal_id


async def ack(text: str) -> None:
    assert text == "Re-checking…"


@pytest.mark.asyncio
async def test_GD_03_both_risk_checks_and_all_public_statuses_are_recorded(
    harness: Harness,
) -> None:
    result = await harness.swarm.run(harness.request)
    assert result.status == "ALERT" and result.context is not None
    assert set(result.unavailable) == {"fundamentals", "peers", "earnings", "iv", "flow", "news"}
    assert count(harness, ResearchReport) == 7 and harness.news.calls == 1
    assert result.context.fundamentals.framework_status.value == "INCOMPLETE"
    harness.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["quantity", "source", "future", "feed", "digest", "conflict"])
async def test_GD_03_unverifiable_candidate_halts_before_public_research(
    harness: Harness, change: str
) -> None:
    h, req = harness, harness.request
    if change == "quantity":
        req = req.model_copy(
            update={"candidate": req.candidate.model_copy(update={"qty": req.candidate.qty + 1})}
        )
    elif change == "source":
        req = req.model_copy(update={"data_snapshot_id": uuid4()})
    elif change == "future":
        req = req.model_copy(
            update={
                "candidate": req.candidate.model_copy(
                    update={"as_of": h.clock.now() + timedelta(seconds=1)}
                )
            }
        )
    else:
        with Session(h.state.engine) as session:
            source = session.get(DataSnapshot, req.data_snapshot_id)
            assert source is not None
            values = {
                key: value
                for key, value in source.__dict__.items()
                if key in DataSnapshot.__table__.columns.keys()
                and key not in {"id", "seq", "prev_hash", "row_hash", "created_at"}
            }
        if change == "feed":
            values["feed"] = "IEX"
        elif change == "digest":
            values["sha256"] = "a" * 64
        else:
            rows = tuple(AsyncAlpacaMarketData._cached_bar(row) for row in values["bars"])
            rows = (
                *rows[:-1],
                Bar.model_validate(
                    rows[-1].model_copy(update={"close": rows[-1].close - Decimal("0.01")})
                ),
            )
            values["sha256"], values["bars"] = _bars_digest(rows)
        new = h.state.ledger.append(DataSnapshot, **values)
        req = req.model_copy(update={"data_snapshot_id": new.id})
    with pytest.raises(DataIntegrityError):
        await h.swarm.run(req)
    assert h.state.current() == SystemState.HALTED and h.news.calls == 0
    assert count(h, Alert) == count(h, TradeTicket) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,halted",
    [
        (ProviderError("outage"), False),
        (TimeoutError(), False),
        (EgressDeniedError("denied"), True),
        (RuntimeError("fault"), True),
    ],
)
async def test_GD_03_provider_outage_vs_security_fault(
    harness: Harness, error: Exception, halted: bool
) -> None:
    h = harness
    h.news.error = error
    if halted:
        with pytest.raises(DataIntegrityError):
            await h.swarm.run(h.request)
        assert h.state.current() == SystemState.HALTED and count(h, Alert) == 0
    else:
        result = await h.swarm.run(h.request)
        assert "news" in result.unavailable and result.status == "ALERT"
        assert h.state.current() == SystemState.RUNNING


@pytest.mark.asyncio
async def test_GD_03_halt_blocks_before_paid_or_public_fanout(harness: Harness) -> None:
    h = harness
    h.state.escalate(SystemState.HALTED, "fixture halt")
    result = await h.swarm.run(h.request)
    assert result.status == "VETOED" and "CRO-01" in result.reasons
    assert h.news.calls == 0 and count(h, Alert) == 0


@pytest.mark.asyncio
async def test_GD_06_concurrent_approval_is_one_fresh_check_one_ticket(harness: Harness) -> None:
    h = harness
    await deliver(h)
    results = await asyncio.gather(
        *(h.gate.handle(click(h, "A"), acknowledge=ack) for _ in range(8))
    )
    assert [r.status for r in results].count("TICKET") == 1
    assert h.source.calls == count(h, TradeTicket) == count(h, ApprovalEvent) == 1
    text = next(r.text for r in results if r.status == "TICKET")
    assert text is not None and "BUY 9 NVDA, LIMIT $101.76, DAY" in text
    assert "After it fills: SELL STOP 9 NVDA at $99.12, GTC" in text
    assert "SELL LIMIT 9 NVDA at $107.04" in text
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        dict(user_id=999),
        dict(chat_id=999),
        dict(chat_type="group"),
        dict(message_id=457),
        dict(data="broken"),
        dict(data="v1:A:" + "a" * 32 + ":" + "0" * 16),
    ],
)
async def test_GD_06_forged_clicks_log_no_reply_or_fresh_private_access(
    harness: Harness, changes: dict[str, Any]
) -> None:
    h = harness
    await deliver(h)
    result = await h.gate.handle(click(h, "A", **changes), acknowledge=ack)
    assert result.status == "IGNORED" and result.text is None
    assert h.source.calls == count(h, TradeTicket) == 0 and count(h, SecurityEvent) >= 1


@pytest.mark.asyncio
async def test_GD_06_details_read_only_all_rules_and_fundamentals(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    before = count(h, ApprovalEvent)
    result = await h.gate.handle(click(h, "D"), acknowledge=ack)
    assert result.status == "DETAILS" and h.source.calls == 0
    text = "\n".join((result.text or "", *result.continuation))
    assert all(f"CRO-{i:02}" in text for i in range(1, 14))
    assert all(f"CMP-{i:02}" in text for i in range(1, 8))
    assert "gross_margin" in text and "insufficient" in text.lower()
    assert (
        count(h, ApprovalEvent) == before
        and h.state.ledger.current_alert_status(alert.id) == "SENT"
    )


@pytest.mark.asyncio
async def test_GD_06_valid_hmac_unknown_proposal_is_ignored(harness: Harness) -> None:
    h = harness
    proposal_id = uuid4()
    result = await h.gate.handle(
        CallbackClick(
            user_id=123,
            chat_id=123,
            message_id=456,
            chat_type="private",
            data=callback_data("A", proposal_id, 123, h.settings),
        ),
        acknowledge=ack,
    )
    assert result.status == "IGNORED" and result.text is None
    assert h.source.calls == count(h, ApprovalEvent) == count(h, TradeTicket) == 0
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("action,expected", [("R", "REJECTED"), ("P", "HANDLED"), ("S", "HANDLED")])
async def test_GD_06_reject_and_followup_before_approval(
    harness: Harness, action: str, expected: str
) -> None:
    await deliver(harness)
    result = await harness.gate.handle(click(harness, action), acknowledge=ack)
    assert result.status == expected and harness.source.calls == count(harness, TradeTicket) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action,expected", [("P", "PLACED"), ("S", "SKIPPED")])
async def test_GD_06_followup_single_use_after_approval(
    harness: Harness, action: str, expected: str
) -> None:
    h = harness
    await deliver(h)
    assert (await h.gate.handle(click(h, "A"), acknowledge=ack)).status == "TICKET"
    assert (await h.gate.handle(click(h, action), acknowledge=ack)).status == expected
    assert (await h.gate.handle(click(h, action), acknowledge=ack)).status == "HANDLED"
    assert count(h, TicketEvent) == 1
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["expired", "price", "fault", "account", "halt_race", "expire_race", "quote_race"]
)
async def test_GD_06_fresh_failures_never_produce_ticket(harness: Harness, change: str) -> None:
    h = harness
    alert = await deliver(h)
    if change == "expired":
        h.clock.current = alert.expires_at
    elif change == "price":
        h.source.inputs = h.source.inputs.model_copy(
            update={"market": h.request.market.model_copy(update={"last_price": Decimal(80)})}
        )
    elif change == "account":
        h.source.inputs = h.source.inputs.model_copy(
            update={
                "portfolio": h.request.portfolio.model_copy(update={"account_id": "wrong-account"})
            }
        )
    elif change == "fault":
        h.source.error = ProviderError("private provider down")
    elif change == "halt_race":
        h.source.hook = lambda: h.state.escalate(SystemState.HALTED, "phone halt while checking")
    elif change == "expire_race":

        def expire() -> None:
            h.clock.current = alert.expires_at

        h.source.hook = expire
    else:

        def stale() -> None:
            h.clock.current += timedelta(seconds=h.settings.stale_quote_seconds + 1)

        h.source.hook = stale
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status in {"FAILED", "EXPIRED"} and count(h, TradeTicket) == 0
    if change in {"fault", "account"}:
        assert h.state.current() == SystemState.HALTED


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["expiry", "quote", "quote_halt"])
async def test_GD_06_deadline_crossed_after_real_checks_cannot_create_ticket(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    h = harness
    alert = await deliver(h)
    if race == "expiry":
        h.clock.current = alert.expires_at - timedelta(seconds=1)
        h.source.inputs = h.source.inputs.model_copy(
            update={
                "portfolio": h.source.inputs.portfolio.model_copy(update={"as_of": h.clock.now()}),
                "market": h.source.inputs.market.model_copy(
                    update={"last_price_ts": h.clock.now()}
                ),
            }
        )
    original = h.gate.compliance.evaluate

    def evaluate(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        h.clock.current += timedelta(
            seconds=1 if race == "expiry" else h.settings.stale_quote_seconds + 1
        )
        if race == "quote_halt":
            h.state.escalate(SystemState.HALTED, "phone halt after checks")
        return result

    monkeypatch.setattr(h.gate.compliance, "evaluate", evaluate)
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == ("EXPIRED" if race == "expiry" else "FAILED")
    assert count(h, TradeTicket) == 0
    assert h.state.ledger.current_alert_status(alert.id) == (
        "EXPIRED" if race == "expiry" else "REVALIDATION_FAILED"
    )
    assert h.state.current() == (SystemState.RUNNING if race == "expiry" else SystemState.HALTED)
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_06_missing_projection_during_commit_halts_without_ticket(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    await deliver(h)
    evaluate, scalar = h.gate.compliance.evaluate, Session.scalar
    consumed = False

    def read(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal consumed
        if not consumed and any(
            table.name == "system_control" for table in statement.get_final_froms()
        ):
            consumed = True
            return None
        return scalar(session, statement, *args, **kwargs)

    def checked(*args: Any, **kwargs: Any) -> Any:
        result = evaluate(*args, **kwargs)
        monkeypatch.setattr(Session, "scalar", read)
        return result

    monkeypatch.setattr(h.gate.compliance, "evaluate", checked)
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "FAILED" and count(h, TradeTicket) == 0
    assert consumed and h.state.current() == SystemState.HALTED


@pytest.mark.asyncio
async def test_GD_06_ticket_display_rejects_tampering_and_optional_target_is_optional(
    harness: Harness,
) -> None:
    import copy

    from backend.core.ledger import ticket_digest

    h = harness
    await deliver(h)
    assert (await h.gate.handle(click(h, "A"), acknowledge=ack)).status == "TICKET"
    with Session(h.state.engine) as session:
        stored = session.scalar(select(TradeTicket))
        assert stored is not None
        ticket = copy.copy(stored)
    ticket.limit_price += Decimal("0.01")
    with pytest.raises(DataIntegrityError, match="invalid manual ticket"):
        ticket_card(ticket, h.settings)
    ticket.ticket_sha256 = ticket_digest(ticket)
    ticket.target_price = None
    ticket.ticket_sha256 = ticket_digest(ticket)
    assert "Optional:" not in ticket_card(ticket, h.settings)
    ticket.stop_price = None
    ticket.ticket_sha256 = ticket_digest(ticket)
    with pytest.raises(DataIntegrityError):
        ticket_card(ticket, h.settings)


@pytest.mark.asyncio
async def test_GD_06_details_refuse_missing_risk_or_oversize_rule_evidence(
    harness: Harness,
) -> None:
    from backend.core.database import Order, RiskRuleResult

    h = harness
    await deliver(h)
    with Session(h.state.engine) as session:
        order = session.scalar(select(Order))
        assert order is not None
        signal_id, symbol = order.signal_id, order.symbol
    other = h.state.ledger.append(
        Order,
        proposal_id=uuid4(),
        signal_id=signal_id,
        client_order_id="no-risk-fixture",
        account_id=h.request.portfolio.account_id,
        symbol=symbol,
        side="BUY",
        intent="ENTRY",
        qty=1,
        limit_price=Decimal(100),
        stop_price=Decimal(95),
        source="SIGNAL",
    )
    alert = h.state.ledger.append(
        Alert,
        proposal_id=other.proposal_id,
        signal_id=signal_id,
        symbol=symbol,
        playbook="BASE_BREAKOUT",
        score=h.request.candidate.score,
        card_text="missing risk fixture",
        config_hash=h.settings.config_hash,
        expires_at=h.clock.now() + timedelta(hours=1),
    )
    with pytest.raises(DataIntegrityError, match="lack risk evidence"):
        details_cards(alert.id, h.state.ledger, h.settings)
    with Session(h.state.engine) as session:
        from backend.core.database import RiskDecision

        decision = session.scalar(select(RiskDecision).order_by(RiskDecision.seq.desc()).limit(1))
        first_alert = session.scalar(select(Alert).order_by(Alert.seq))
        assert decision is not None and first_alert is not None
    h.state.ledger.append(
        RiskRuleResult,
        risk_decision_id=decision.id,
        rule_id="CRO-01",
        passed=0,
        severity="WARN",
        observed={"text": "&" * 4096},
        limit={},
        message="oversize evidence",
    )
    with pytest.raises(DataIntegrityError, match="line exceeds"):
        details_cards(first_alert.id, h.state.ledger, h.settings)


@pytest.mark.asyncio
async def test_GD_05_masked_cards_ticket_and_details_hide_private_amounts(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    assert (await h.gate.handle(click(h, "A"), acknowledge=ack)).status == "TICKET"
    settings = h.settings.model_copy(update={"telegram_mask_amounts": True})
    with Session(h.state.engine) as session:
        ticket = session.scalar(select(TradeTicket))
        assert ticket is not None
        text = ticket_card(ticket, settings)
    assert "$•••" in text and "BUY 9" not in text and "$101.76" in text
    # Details refuse a policy hash different from the immutable alert.
    with pytest.raises(DataIntegrityError):
        details_cards(alert.id, h.state.ledger, settings)


@pytest.mark.asyncio
async def test_GD_03_flow_denied_egress_never_degrades_to_optional_outage() -> None:
    class Denied:
        async def get(self, symbol: str, as_of: datetime) -> Any:
            raise EgressDeniedError("denied")

    with pytest.raises(EgressDeniedError):
        await FlowTracker(Denied()).read(
            "NVDA", datetime.fromisoformat("2026-09-30T15:00:00+00:00")
        )


def test_GD_06_callback_bounds_and_constructor_policy(harness: Harness) -> None:
    h = harness
    with pytest.raises(DataIntegrityError):
        callback_data("A", uuid4(), -123, h.settings)
    with pytest.raises(ConfigurationError):
        SwarmRunner(
            h.settings,
            h.config,
            h.swarm.risk,
            h.swarm.compliance,
            h.state,
            h.clock,
            h.swarm.news_reader,
            concurrency=0,
        )
    with pytest.raises(ConfigurationError):
        SwarmRunner(
            h.settings,
            h.config,
            h.swarm.risk,
            h.swarm.compliance,
            h.state,
            h.clock,
            h.swarm.news_reader,
            offline=True,
        )


@pytest.mark.asyncio
async def test_GD_06_cancellation_halts_and_never_leaves_a_ticket(harness: Harness) -> None:
    h = harness
    await deliver(h)

    def cancel() -> None:
        raise asyncio.CancelledError

    h.source.hook = cancel
    with pytest.raises(asyncio.CancelledError):
        await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert h.state.current() == SystemState.HALTED and count(h, TradeTicket) == 0


@pytest.mark.asyncio
async def test_GD_06_another_authenticated_decision_during_refresh_wins_atomically(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)
    h.source.hook = lambda: h.state.ledger.append(
        ApprovalEvent, alert_id=alert.id, action="USER_VETOED", telegram_user_id=123, reasons=[]
    )
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert (
        result.status == "HANDLED" and count(h, TradeTicket) == 0 and count(h, ApprovalEvent) == 1
    )


@pytest.mark.asyncio
async def test_GD_06_filing_issuer_mismatch_halts(harness: Harness) -> None:
    from backend.tests.test_fundamentals import evidence, synthetic

    h = harness
    await deliver(h)
    filing = evidence(synthetic()).model_copy(update={"fetched_at": h.clock.now()})
    h.source.inputs = h.source.inputs.model_copy(
        update={"filings": filing, "expected_cik": "0001045810"}
    )
    assert (await h.gate.handle(click(h, "A"), acknowledge=ack)).status == "FAILED"
    assert h.state.current() == SystemState.HALTED and count(h, TradeTicket) == 0


@pytest.mark.asyncio
async def test_FA_08_fresh_required_fundamentals_cannot_reuse_an_earlier_pass(
    harness: Harness,
) -> None:
    import hashlib

    from backend.data.sec_edgar import SecPayload
    from backend.tests.test_fundamentals import synthetic

    h = harness
    data = synthetic()
    data["cik"] = 1045810
    for tag in ("StockholdersEquity", "LongTermDebt", "CashAndCashEquivalentsAtCarryingValue"):
        row = dict(data["facts"]["us-gaap"][tag]["units"]["USD"][0])
        row.update(end="2025-06-30", filed="2025-08-01")
        data["facts"]["us-gaap"][tag]["units"]["USD"].append(row)
    raw = json.dumps(data, separators=(",", ":")).encode()
    filing = SecPayload(
        kind="COMPANYFACTS",
        cik="0001045810",
        fetched_at=h.clock.now(),
        raw=raw,
        data_sha256=hashlib.sha256(raw).hexdigest(),
    )

    class Filings:
        async def cik_for(self, symbol: str) -> str:
            return filing.cik or ""

        async def companyfacts(self, symbol: str) -> SecPayload:
            return filing

    h.config = YamlConfig.model_validate(
        {
            **h.config.model_dump(),
            "fundamentals": {**h.config.fundamentals.model_dump(), "mode": "require"},
        }
    )
    h.swarm = SwarmRunner(
        h.settings,
        h.config,
        h.swarm.risk,
        h.swarm.compliance,
        h.state,
        h.clock,
        h.swarm.news_reader,
        news=h.news,
        fundamentals=Filings(),
    )
    h.gate = ApprovalGate(
        h.settings, h.config, h.state, h.swarm.risk, h.swarm.compliance, h.clock, h.source
    )
    await deliver(h)
    assert (await h.gate.handle(click(h, "D"), acknowledge=ack)).status == "DETAILS"
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "FAILED" and count(h, TradeTicket) == 0
    assert h.state.current() == SystemState.RUNNING


def test_GD_06_gate_refuses_unbound_clock_and_result_disclosure(harness: Harness) -> None:
    from backend.notifications.callbacks import ClickResult

    h = harness
    with pytest.raises(ConfigurationError):
        ApprovalGate(
            h.settings,
            h.config,
            h.state,
            h.swarm.risk,
            h.swarm.compliance,
            MovingClock(h.clock.now()),
            h.source,
        )
    for values in (
        {"status": "IGNORED", "text": "private"},
        {"status": "TICKET", "text": "ticket"},
        {"status": "DETAILS"},
        {"status": "DETAILS", "text": ""},
    ):
        with pytest.raises(ValueError):
            ClickResult.model_validate(values)


@pytest.mark.asyncio
async def test_R_09_manual_sell_remains_available_during_halt_with_required_fundamentals(
    harness: Harness,
) -> None:
    from backend.core.database import Order, Signal
    from backend.domain.models import Position

    h = harness
    config = YamlConfig.model_validate(
        {
            **h.config.model_dump(),
            "fundamentals": {**h.config.fundamentals.model_dump(), "mode": "require"},
        }
    )
    signal = h.state.ledger.append(
        Signal,
        agent_name="manual_exit",
        symbol="NVDA",
        direction="SELL",
        signal_type="MANUAL",
        confidence=Decimal(0),
        structured_thesis={"reason": "owner-held exit"},
        invalidation="remaining held shares must cover the sell",
        data_snapshot_id=h.request.data_snapshot_id,
        prompt_hash=None,
    )
    order = h.state.ledger.append(
        Order,
        proposal_id=uuid4(),
        signal_id=signal.id,
        client_order_id="manual-exit-fixture",
        account_id=h.request.portfolio.account_id,
        symbol="NVDA",
        side="SELL",
        intent="EXIT",
        qty=3,
        limit_price=Decimal(100),
        stop_price=None,
        target_price=None,
        source="MANUAL",
    )
    alert = h.state.ledger.append(
        Alert,
        proposal_id=order.proposal_id,
        signal_id=signal.id,
        symbol="NVDA",
        playbook="BASE_BREAKOUT",
        score=h.request.candidate.score,
        card_text="Manual held exit",
        config_hash=h.settings.config_hash,
        expires_at=h.clock.now() + timedelta(hours=1),
    )
    h.state.ledger.append(
        ResearchReport,
        alert_id=alert.id,
        agent_name="desk_policy",
        status="OK",
        payload={"yaml_hash": config.config_hash},
    )
    h.state.ledger.append(
        AlertEvent,
        alert_id=alert.id,
        state="SENT",
        telegram_chat_id=123,
        telegram_message_id=456,
        reason="offline private delivery",
    )
    h.source.inputs = h.source.inputs.model_copy(
        update={
            "portfolio": h.source.inputs.portfolio.model_copy(
                update={
                    "positions": {
                        "NVDA": Position(qty=3, avg_cost=Decimal(90), last_price=Decimal(100))
                    }
                }
            ),
            "market": h.source.inputs.market.model_copy(update={"last_price": Decimal(100)}),
        }
    )
    gate = ApprovalGate(
        h.settings, config, h.state, h.swarm.risk, h.swarm.compliance, h.clock, h.source
    )
    h.state.escalate(SystemState.HALTED, "test held exit under halt")
    result = await gate.handle(
        CallbackClick(
            user_id=123,
            chat_id=123,
            message_id=456,
            chat_type="private",
            data=callback_data("A", order.proposal_id, 123, h.settings),
        ),
        acknowledge=ack,
    )
    assert result.status == "TICKET" and "SELL 3 NVDA, LIMIT $100.00, DAY" in (result.text or "")
    assert "After it fills" not in (result.text or "") and count(h, TradeTicket) == 1
    assert h.state.current() == SystemState.HALTED
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_04_desk_cooldown_is_atomic_before_second_research(harness: Harness) -> None:
    from backend.agents.desk import Desk

    h = harness
    desk = Desk(h.swarm)
    results = await asyncio.gather(*(desk.research(h.request) for _ in range(6)))
    assert [r.status for r in results].count("ALERT") == 1
    assert [r.status for r in results].count("COOLDOWN") == 5
    assert h.news.calls == 1 and count(h, Alert) == 1


@pytest.mark.asyncio
async def test_GD_04_daily_cap_counts_other_inflight_reservations(harness: Harness) -> None:
    from backend.agents.desk import Desk

    h = harness
    for i in range(h.settings.max_alerts_per_day):
        h.state.ledger.append(
            SecurityEvent,
            kind="DESK_RESERVED",
            detail={"token": str(i), "symbol": "AAPL", "playbook": "BASE_BREAKOUT"},
        )
    assert (await Desk(h.swarm).research(h.request)).status == "DAILY_CAP"
    assert h.news.calls == count(h, Alert) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action,text,status", [("R", "Rejected. No ticket.", "REJECTED")])
async def test_GD_06_rejection_has_exact_public_acknowledgement(
    harness: Harness, action: str, text: str, status: str
) -> None:
    await deliver(harness)
    result = await harness.gate.handle(click(harness, action), acknowledge=ack)
    assert (result.status, result.text) == (status, text)
    assert count(harness, TradeTicket) == 0
    harness.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_06_expired_card_has_exact_public_acknowledgement(harness: Harness) -> None:
    alert = await deliver(harness)
    harness.clock.current = alert.expires_at
    result = await harness.gate.handle(click(harness, "A"), acknowledge=ack)
    assert (result.status, result.text) == ("EXPIRED", "Expired. No ticket.")
    assert count(harness, TradeTicket) == 0
    harness.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_06_final_expiry_has_exact_public_acknowledgement(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    alert = await deliver(h)
    h.clock.current = alert.expires_at - timedelta(seconds=1)
    h.source.inputs = h.source.inputs.model_copy(
        update={
            "portfolio": h.source.inputs.portfolio.model_copy(update={"as_of": h.clock.now()}),
            "market": h.source.inputs.market.model_copy(update={"last_price_ts": h.clock.now()}),
        }
    )
    evaluate = h.gate.compliance.evaluate

    def expire(*args: Any, **kwargs: Any) -> Any:
        result = evaluate(*args, **kwargs)
        h.clock.current += timedelta(seconds=1)
        return result

    monkeypatch.setattr(h.gate.compliance, "evaluate", expire)
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert (result.status, result.text) == ("EXPIRED", "Expired during fresh checks. No ticket.")
    assert count(h, TradeTicket) == 0
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("reduced_first", [False, True])
async def test_GD_06_late_quote_records_exact_halt_audit_and_monotonic_version(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, reduced_first: bool
) -> None:
    h = harness
    alert = await deliver(h)
    evaluate = h.gate.compliance.evaluate

    class Notices:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def notify(self, state: str, reason: str) -> None:
            self.calls.append((state, reason))

    notices = Notices()
    h.state.notifier.delegate = notices

    def stale(*args: Any, **kwargs: Any) -> Any:
        result = evaluate(*args, **kwargs)
        if reduced_first:
            h.state.escalate(SystemState.REDUCE_ONLY, "operator reduces during approval")
        h.clock.current += timedelta(seconds=h.settings.stale_quote_seconds + 1)
        return result

    monkeypatch.setattr(h.gate.compliance, "evaluate", stale)
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert (result.status, result.text) == ("FAILED", "Fresh checks vetoed this setup. No ticket.")
    assert count(h, TradeTicket) == 0 and h.state.current() == SystemState.HALTED
    assert notices.calls[-1] == ("HALTED", "GD-06: quote expired during fresh checks")
    with Session(h.state.engine) as session:
        decisions = list(
            session.scalars(select(ApprovalEvent).where(ApprovalEvent.alert_id == alert.id))
        )
        assert decisions[-1].action == "REVALIDATION_FAILED"
        assert {"rule_id": "CRO-07", "message": "quote expired during fresh checks"} in decisions[
            -1
        ].reasons
        if reduced_first:
            assert {"rule_id": "CRO-01", "message": "entries halted or reduced"} in decisions[
                -1
            ].reasons
        control = session.get(SystemControl, 1)
        assert control is not None and control.state == "HALTED"
        assert control.version == (2 if reduced_first else 1)
        events = list(
            session.scalars(
                select(SystemEvent).where(
                    SystemEvent.reason == "GD-06: quote expired during fresh checks"
                )
            )
        )
        assert len(events) == 1 and events[0].state == "HALTED" and (events[0].operator_id is None)
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_06_equal_fresh_size_preserves_complete_order_and_inputs(harness: Harness) -> None:
    h = harness
    await deliver(h)
    observed: list[Any] = []

    async def size(proposal: TradeProposal, inputs: FreshInputs) -> int:
        observed.append((proposal, inputs))
        return proposal.qty

    h.gate.size_entry = size
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "TICKET" and result.ticket_id is not None
    assert len(observed) == 1
    from backend.core.database import Order

    with Session(h.state.engine) as session:
        original = session.scalar(select(Order))
        assert original is not None and original.target_price is not None
    assert observed[0][0].target_price == original.target_price
    assert observed[0][0].qty == original.qty
    assert observed[0][1] == h.source.inputs
    with Session(h.state.engine) as session:
        ticket = session.get(TradeTicket, result.ticket_id)
        assert (
            ticket is not None
            and ticket.qty == original.qty
            and (ticket.target_price == original.target_price)
        )
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_06_fresh_fundamental_policy_uses_the_configured_sector_exemption(
    harness: Harness,
) -> None:
    from backend.core.config import YamlConfig

    h = harness
    policy = {
        **h.config.fundamentals.model_dump(),
        "mode": "require",
        "exempt_sectors": (*h.config.fundamentals.exempt_sectors, "Information Technology"),
    }
    h.config = YamlConfig.model_validate({**h.config.model_dump(), "fundamentals": policy})
    h.swarm.config = h.config
    h.gate.config = h.config
    await deliver(h)
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert result.status == "TICKET" and count(h, TradeTicket) == 1
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_06_smaller_fresh_size_has_exact_persisted_refusal_reason(
    harness: Harness,
) -> None:
    h = harness
    alert = await deliver(h)

    async def smaller(proposal: TradeProposal, inputs: FreshInputs) -> int:
        return proposal.qty - 1

    h.gate.size_entry = smaller
    result = await h.gate.handle(click(h, "A"), acknowledge=ack)
    assert (result.status, result.text) == ("FAILED", "Fresh checks vetoed this setup. No ticket.")
    with Session(h.state.engine) as session:
        events = list(
            session.scalars(select(ApprovalEvent).where(ApprovalEvent.alert_id == alert.id))
        )
        assert events[-1].action == "REVALIDATION_FAILED"
        assert events[-1].reasons == [
            {
                "rule_id": "PR-04",
                "message": "Fresh size is smaller; refresh the card before approval",
            }
        ]
    assert count(h, TradeTicket) == 0
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["issuer", "future"])
async def test_GD_06_wrong_filing_binding_has_exact_integrity_error(
    harness: Harness, fault: str
) -> None:
    import re

    from backend.core.errors import DataIntegrityError
    from backend.tests.test_fundamentals import evidence, synthetic
    from backend.tests.test_swarm_and_callbacks import proposal

    h = harness
    await deliver(h)
    filing = evidence(synthetic()).model_copy(
        update={"fetched_at": h.clock.now() + timedelta(seconds=1 if fault == "future" else 0)}
    )
    h.source.inputs = h.source.inputs.model_copy(
        update={
            "filings": filing,
            "expected_cik": filing.cik if fault == "future" else "0000000001",
        }
    )
    message = "GD-06: fresh filing issuer/time differs"
    with pytest.raises(DataIntegrityError, match=re.escape(message)) as caught:
        await h.gate._handle(click(h, "A"), "A", proposal(h), ack)
    assert type(caught.value) is DataIntegrityError and str(caught.value) == message
    assert count(h, TradeTicket) == 0
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault,kind,user",
    [("unauthorized", "CALLBACK_UNAUTHORIZED", 999), ("wire", "CALLBACK_BAD_WIRE", 123)],
)
async def test_GD_06_rejected_click_audit_retains_known_actor_and_empty_detail(
    harness: Harness, fault: str, kind: str, user: int
) -> None:
    from backend.core.database import SecurityEvent

    h = harness
    await deliver(h)
    change = (
        {"user_id": 999, "chat_id": 999} if fault == "unauthorized" else {"data": "invalid-wire"}
    )
    result = await h.gate.handle(click(h, "A", **change), acknowledge=ack)
    assert result.status == "IGNORED" and count(h, TradeTicket) == 0
    with Session(h.state.engine) as session:
        events = list(session.scalars(select(SecurityEvent).where(SecurityEvent.kind == kind)))
        assert len(events) == 1
        assert events[0].telegram_user_id == user and events[0].detail == {}
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_GD_06_click_context_is_fresh_scoped_and_restores_the_callers_context(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import UUID

    from structlog.contextvars import bound_contextvars, get_contextvars

    from backend.tests.test_swarm_and_callbacks import proposal

    h = harness
    alert = await deliver(h)
    captured: list[Any] = []
    audit = h.gate._audit

    def record(kind: str, user_id: int | None = None) -> None:
        captured.append((kind, get_contextvars().copy()))
        audit(kind, user_id)

    monkeypatch.setattr(h.gate, "_audit", record)
    with bound_contextvars(
        cycle_id="outer-cycle", proposal_id="outer-proposal", alert_id="outer-alert"
    ):
        first = await h.gate.handle(click(h, "A", data="invalid-wire"), acknowledge=ack)
        second = await h.gate.handle(click(h, "R"), acknowledge=ack)
        assert first.status == "IGNORED" and second.status == "REJECTED"
        assert {k: get_contextvars()[k] for k in ["cycle_id", "proposal_id", "alert_id"]} == {
            "cycle_id": "outer-cycle",
            "proposal_id": "outer-proposal",
            "alert_id": "outer-alert",
        }
    assert len(captured) == 2
    assert captured[0][0] == "CALLBACK_BAD_WIRE" and captured[1][0] == "CALLBACK_R"
    assert captured[0][1]["proposal_id"] is None and captured[0][1]["alert_id"] is None
    assert captured[1][1]["proposal_id"] == str(proposal(h)) and captured[1][1]["alert_id"] == str(
        alert.id
    )
    assert captured[0][1]["cycle_id"] != captured[1][1]["cycle_id"]
    assert all(UUID(c[1]["cycle_id"]).version == 4 for c in captured)
    h.state.ledger.verify_chain()
