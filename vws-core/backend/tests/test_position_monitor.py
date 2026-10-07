"""R-09/GD-04: fresh held caps and warnings survive an entry halt."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from backend.agents.position_monitor import Protection, distance_to_stop, monitor
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.domain.models import EarningsInfo, EarningsStatus, MarketStatus, Position
from backend.tests.test_swarm_and_callbacks import (  # noqa: F401
    Harness,
    make_research_harness,
)


@pytest.mark.parametrize(
    "scenario,expected,urgent",
    [
        ("stop", "STOP_BREACHED", True),
        ("target", "TARGET_REACHED", False),
        ("suspect", "SUSPECT", False),
        ("earnings", "EARNINGS_BLACKOUT", False),
        ("ordinary", None, False),
        ("missing", None, False),
        ("ticket", "OPEN_TICKET_WARNING", True),
    ],
)
def test_GD_04_held_and_open_ticket_warnings(
    harness: Harness, scenario: str, expected: str | None, urgent: bool
) -> None:
    h = harness
    h.state.escalate(SystemState.HALTED, "held exit monitor test")
    positions = (
        {}
        if scenario in {"missing", "ticket"}
        else {"NVDA": Position(qty=3, avg_cost=Decimal(100), last_price=Decimal(100))}
    )
    snapshot = h.request.portfolio.model_copy(update={"positions": positions})
    changes: dict[str, Any] = {"last_price": Decimal(100)}
    if scenario in {"stop", "ticket"}:
        changes["last_price"] = Decimal(95)
    elif scenario == "target":
        changes["last_price"] = Decimal(110)
    elif scenario == "suspect":
        changes["status"] = MarketStatus.SUSPECT
    elif scenario == "earnings":
        changes["earnings"] = EarningsInfo(
            date=h.clock.now().date(), status=EarningsStatus.KNOWN, source="dated fixture"
        )
    result = monitor(
        Protection(
            symbol="NVDA",
            qty=9,
            stop=Decimal(95),
            target=Decimal(110),
            kind="OPEN_TICKET" if scenario == "ticket" else "HELD",
        ),
        snapshot,
        h.request.market.model_copy(update=changes),
        now=h.clock.now(),
        quote_feed="IEX",
        settings=h.settings,
        calendar=h.swarm.risk.cro.calendar,
    )
    if expected is None:
        assert result == ()
    else:
        assert len(result) == 1 and result[0].reason == expected and result[0].urgent is urgent
        assert result[0].qty == (0 if scenario == "ticket" else 3)
        assert "IEX last trade" in result[0].text
    assert h.state.current() == SystemState.HALTED


@pytest.mark.parametrize(
    "bad", ["old_quote", "future_quote", "old_broker", "future_broker", "feed", "levels"]
)
def test_GD_04_monitor_rejects_unverifiable_evidence(harness: Harness, bad: str) -> None:
    h = harness
    market, portfolio = h.request.market, h.request.portfolio
    protection = Protection(symbol="NVDA", qty=9, stop=Decimal(95), target=Decimal(110))
    shift = timedelta(seconds=h.settings.stale_quote_seconds + 1)
    if bad in {"old_quote", "future_quote"}:
        market = market.model_copy(
            update={"last_price_ts": h.clock.now() + (shift if bad == "future_quote" else -shift)}
        )
    elif bad in {"old_broker", "future_broker"}:
        portfolio = portfolio.model_copy(
            update={"as_of": h.clock.now() + (shift if bad == "future_broker" else -shift)}
        )
    elif bad == "levels":
        protection = protection.model_copy(update={"target": Decimal(94)})
    with pytest.raises(DataIntegrityError):
        monitor(
            protection,
            portfolio,
            market,
            now=h.clock.now(),
            quote_feed="SIP" if bad == "feed" else "IEX",  # type: ignore[arg-type]
            settings=h.settings,
            calendar=h.swarm.risk.cro.calendar,
        )


def test_GD_04_distance_is_exact_and_invalid_price_is_typed() -> None:
    assert distance_to_stop(Decimal(100), Decimal(95)) == Decimal(5)
    assert distance_to_stop(Decimal(100), Decimal(105)) == Decimal(-5)
    with pytest.raises(DataIntegrityError):
        distance_to_stop(Decimal("100.001"), Decimal(95))
