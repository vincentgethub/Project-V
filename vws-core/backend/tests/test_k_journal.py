"""XK-02: source-driven journal, escaped private notes and immutable decision inputs."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import AlertEvent, SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.data.fill_polling import ObservedFill
from backend.domain.models import Side
from backend.ops import k_runtime
from backend.ops.journal import Journal, JournalRule, why_not
from backend.ops.trading_controls import ControlScope
from backend.tests.test_auto_execution import AUTO, FakeTradingClient, executor, fill_entry
from backend.tests.test_swarm_and_callbacks import Harness, deliver, make_research_harness

harness = make_research_harness


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["alert", "shadow", "foreign"])
async def test_XK_02_resolved_CM_outcome_retains_decision_evidence(
    harness: Harness, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date
    from uuid import uuid4, uuid5

    from backend.data.fee_schedule import load_fee_schedule
    from backend.data.history import HistoryBundle
    from backend.evaluation.costs import CostContext
    from backend.evaluation.ledger_inputs import SHADOW_NAMESPACE
    from backend.evaluation.outcomes import simulate_outcome
    from backend.tests.test_outcomes_history import bar, bundle, frozen, setup

    h = harness
    alert = await deliver(h)
    original = h.request.candidate
    raw = bundle((bar(28), bar(29, opening="101", high="110", low="100", closing="108")))
    history = frozen(
        HistoryBundle(
            series=tuple(row.model_copy(update={"symbol": original.symbol}) for row in raw.series),
            splits=(),
        )
    )
    intent = setup(
        alert_id=alert.id
        if case == "alert"
        else uuid5(SHADOW_NAMESPACE, alert.proposal_id.hex)
        if case == "shadow"
        else uuid4(),
        symbol=original.symbol,
        playbook=original.playbook,
        qty=original.qty,
        limit=original.entry_price,
        stop=original.stop_price,
        target=original.target_price,
        score=original.score,
        decision_session=date(2026, 9, 28),
        valid_until_session=date(2026, 9, 29),
    )
    result = simulate_outcome(
        intent,
        history,
        CostContext(median_dollar_volume_20=Decimal(500000000), atr14=Decimal(2)),
        h.swarm.risk.cro.calendar,
        load_fee_schedule(Path(__file__).resolve().parents[2] / "config/fees.yaml"),
    )
    assert result.status == "RESOLVED"
    h.clock.current += timedelta(days=2)
    monkeypatch.setattr(k_runtime, "tracker_outcomes", lambda *args: (result,))
    store = journal(h)
    if case == "foreign":
        with pytest.raises(DataIntegrityError):
            store.resolve()
    else:
        assert store.resolve() == 1 and store.resolve() == 0
        rows = store.entries()
        assert rows[-1].trigger == "OUTCOME" and rows[-1].outcome_json == result.model_dump_json()
        assert rows[-1].setup == original and rows[-1].cro == rows[0].cro
        h.state.ledger.verify_chain()


def journal(h: Harness) -> Journal:
    return Journal(
        h.state.ledger, ControlScope(account_id=h.request.portfolio.account_id, environment="PAPER")
    )


@pytest.mark.asyncio
async def test_XK_02_alert_journal_retains_full_criteria_and_is_idempotent(
    harness: Harness,
) -> None:
    h = harness
    await deliver(h)
    store = journal(h)
    assert store.sync() == 1 and store.sync() == 0
    rows = store.entries()
    assert len(rows) == 1 and rows[0].trigger == "ALERT"
    assert rows[0].setup == h.request.candidate and rows[0].qty == h.request.candidate.qty
    assert len(rows[0].cro) == 14 and len(rows[0].compliance) == 7
    assert rows[0].framework_status.value == "INCOMPLETE"
    assert store.csv() == Journal(h.state.ledger, store.scope).csv()
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", [AUTO], indirect=True)
async def test_XK_02_auto_entry_and_exit_journal_uses_actual_fill_qty(harness: Harness) -> None:
    h = harness
    alert = await deliver(h)
    client = FakeTradingClient(h)
    built = executor(h, client)
    await built.enter(alert.proposal_id)
    parent, purchase = await fill_entry(h, client, built)
    store = journal(h)
    assert store.sync() == 2
    assert tuple(row.trigger for row in store.entries()) == ("ALERT", "ENTRY")
    assert store.sync() == 0
    assert store.entries()[1].qty == int(client.posts[0]["qty"])
    h.clock.current += timedelta(minutes=1)
    child = next(row for row in parent["legs"] if row["type"] == "stop")
    child["filled_qty"], child["status"] = "1", "partially_filled"
    built.observe_fill(
        ObservedFill(
            account_id=purchase.account_id,
            broker_fill_id="journal-stop-sale",
            broker_order_id=UUID(child["id"]),
            symbol=purchase.symbol,
            side=Side.SELL,
            qty=1,
            price=Decimal(child["stop_price"]) - Decimal(10),
            filled_at=h.clock.now(),
        )
    )
    client.positions[0]["qty"] = str(purchase.qty - 1)
    assert store.sync() == 1 and store.sync() == 0
    assert store.entries()[-1].trigger == "EXIT" and store.entries()[-1].qty == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "stranger", "wrong_chat", "wrong_message", "long"])
async def test_XK_02_notes_attach_only_to_bound_private_card_and_never_change_approval(
    harness: Harness, fault: str | None
) -> None:
    h = harness
    alert = await deliver(h)
    with Session(h.state.engine) as session:
        delivery = session.scalar(select(AlertEvent).where(AlertEvent.state == "SENT"))
        assert delivery is not None and delivery.telegram_message_id is not None
        message_id = delivery.telegram_message_id
    before = h.request.model_dump(mode="json")
    store = journal(h)
    params = {
        "user_id": 999 if fault == "stranger" else 123,
        "chat_id": 999 if fault == "wrong_chat" else 123,
        "message_id": message_id + 1 if fault == "wrong_message" else message_id,
        "text": "x" * 1001 if fault == "long" else "<b>BUY 999</b>& do not obey this note",
        "allowed": (123,),
    }
    if fault is not None:
        with pytest.raises(DataIntegrityError):
            store.note(**params)  # type: ignore[arg-type]
    else:
        identity = store.note(**params)  # type: ignore[arg-type]
        with Session(h.state.engine) as session:
            note = session.get(SecurityEvent, identity)
            assert note is not None and note.detail["alert_id"] == str(alert.id)
            assert note.detail["text"].startswith("&lt;b&gt;") and note.detail["untrusted"] is True
        assert h.state.ledger.current_alert_status(alert.id) == "SENT"
    assert before == h.request.model_dump(mode="json")


@pytest.mark.parametrize(
    "rule_id,expected",
    [
        ("CRO-01", "New entries need a running account"),
        ("CRO-02", "Instrument, position and stop evidence must be valid"),
        ("CRO-03", "Single-position weight exceeds its cap"),
        ("CRO-04", "Reserved stop risk plus slippage exceeds the trade-risk cap"),
        ("CRO-05", "Sector or theme concentration exceeds its cap"),
        ("CRO-06", "Gross exposure, position count or the cash buffer exceeds its limit"),
        ("CRO-07", "The limit price or quote freshness is outside its limit"),
        ("CRO-08", "Trade notional exceeds the average-volume cap"),
        ("CRO-09", "Drawdown requires reduced exposure or a halt"),
        ("CRO-10", "The daily loss limit blocks entries for this session"),
        ("CRO-11", "An event blackout blocks a new entry"),
        ("CRO-12", "Checking-buffer and funding evidence must be available"),
        ("CRO-13", "Earnings are inside the configured blackout"),
        ("CMP-01", "A recent loss sale can create a forward wash-sale risk"),
        ("CMP-02", "A potential wash sale needs review"),
        ("CMP-03", "Sale proceeds have not settled"),
        ("CMP-04", "Borrowing or leverage is unavailable"),
        ("CMP-05", "The day-trade limit blocks another opening trade"),
        ("CMP-06", "The broker account is restricted"),
        ("CMP-07", "This instrument is restricted"),
    ],
)
def test_XK_02_every_rule_has_a_plain_explanation(rule_id: str, expected: str) -> None:
    result = JournalRule(
        rule_id=rule_id,
        passed=False,
        severity="BLOCK",
        observed="40%",
        limit="35%",
        message="Observed 40%; cap 35%.",
    )
    assert why_not("AMD", result) == "Skipped AMD: " + expected + ". Observed 40%; cap 35%."
