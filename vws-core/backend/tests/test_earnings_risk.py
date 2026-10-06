"""DAT-11/CRO-13: earnings estimates warn, confirmed dates block, evidence binds."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.domain.models import Decision, EarningsInfo, EarningsStatus, MarketContext, Severity
from backend.risk.risk_cro import ChiefRiskOfficer, earnings_rule
from backend.tests.test_risk_boundary import (
    NOW,
    book,
    boundary,
    boundary_cro,
    capital,
    quote,
    trade,
)

# Importing the existing explicit fixture keeps the same independent policy.
__all__ = ["boundary_cro"]


@pytest.mark.parametrize(
    "status,fields",
    [
        (EarningsStatus.KNOWN, {}),
        (EarningsStatus.KNOWN, {"date": date(2026, 10, 5), "window_start": date(2026, 10, 5)}),
        (EarningsStatus.ESTIMATED, {}),
        (EarningsStatus.ESTIMATED, {"window_start": date(2026, 10, 5)}),
        (
            EarningsStatus.ESTIMATED,
            {"window_start": date(2026, 10, 8), "window_end": date(2026, 10, 5)},
        ),
        (EarningsStatus.UNKNOWN, {"date": date(2026, 10, 5)}),
        (EarningsStatus.UNKNOWN, {"window_end": date(2026, 10, 5)}),
    ],
)
def test_DAT_11_partial_or_invented_earnings_evidence_rejected(
    status: EarningsStatus, fields: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        EarningsInfo(status=status, source="synthetic public filing", **fields)


@pytest.mark.parametrize("days,blackout", [(0, 0), (0, 2), (1, 0), (1, 2), (30, 2), (-30, 2)])
def test_CRO_13_estimates_never_claim_confirmed_clearance(
    boundary_cro: ChiefRiskOfficer, days: int, blackout: int
) -> None:
    start = NOW.date() + timedelta(days=days)
    evidence = EarningsInfo(
        status=EarningsStatus.ESTIMATED,
        source="SEC filing interval estimate",
        window_start=start,
        window_end=start + timedelta(days=15),
    )
    market = quote().model_copy(update={"earnings": evidence})
    policy = Settings(broker_account_type="CASH", earnings_blackout_sessions=blackout)
    result = earnings_rule(market, NOW, policy, boundary_cro.calendar)
    assert not result.passed and result.severity == Severity.WARN
    assert "estimated" in result.observed
    assert "overlaps" in result.message if days in {0, 1} else "unavailable" in result.message


def test_CRO_13_estimated_earnings_advisory_does_not_trap_entry_or_held_exit(
    engine: Engine, boundary_cro: ChiefRiskOfficer
) -> None:
    evidence = EarningsInfo(
        status=EarningsStatus.ESTIMATED,
        source="SEC estimate",
        window_start=NOW.date(),
        window_end=NOW.date() + timedelta(days=15),
    )
    market = quote().model_copy(update={"earnings": evidence})
    gate = boundary(engine, boundary_cro)
    result = gate.evaluate(trade(), book(), market, deployable=capital())
    assert result.decision == Decision.APPROVED
    assert not result.results[-1].passed and result.results[-1].severity == Severity.WARN
    held = gate.evaluate(trade(exit_=True), book(held=True), market)
    assert held.decision == Decision.APPROVED and len(held.results) == 2


@pytest.mark.parametrize("days,blocked", [(1, True), (7, False)])
def test_CRO_13_richer_confirmed_evidence_uses_same_session_blackout(
    boundary_cro: ChiefRiskOfficer, days: int, blocked: bool
) -> None:
    market = quote().model_copy(
        update={
            "earnings": EarningsInfo(
                date=NOW.date() + timedelta(days=days),
                status=EarningsStatus.KNOWN,
                source="manual CSV",
            )
        }
    )
    result = earnings_rule(market, NOW, boundary_cro.config, boundary_cro.calendar)
    assert result.passed is not blocked and result.severity == Severity.BLOCK


@pytest.mark.parametrize("attack", ["clear", "confirmed_as_unknown", "missing_market"])
def test_R_02_CRO_13_forged_earnings_evidence_durably_halts(
    engine: Engine, boundary_cro: ChiefRiskOfficer, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    cro = ChiefRiskOfficer(boundary_cro.config, boundary_cro.registry, boundary_cro.calendar)
    gate = boundary(engine, cro)
    market = quote()
    if attack == "clear":
        market = market.model_copy(
            update={
                "earnings": EarningsInfo(
                    status=EarningsStatus.ESTIMATED,
                    source="SEC estimate",
                    window_start=NOW.date(),
                    window_end=NOW.date() + timedelta(days=15),
                )
            }
        )
    elif attack == "confirmed_as_unknown":
        market = market.model_copy(
            update={
                "earnings": EarningsInfo(
                    status=EarningsStatus.KNOWN,
                    source="manual CSV",
                    date=NOW.date() + timedelta(days=1),
                )
            }
        )
    forged = cro.evaluate(trade(), book(), quote(), SystemState.RUNNING, NOW, deployable=capital())
    if attack == "clear":
        forged = forged.model_copy(
            update={
                "results": (
                    *forged.results[:-1],
                    forged.results[-1].model_copy(update={"passed": True}),
                )
            }
        )

    def returning(*_args: object, **_kwargs: object) -> Any:
        return forged

    monkeypatch.setattr(cro, "evaluate", returning)
    with pytest.raises(DataIntegrityError):
        gate.evaluate(
            trade(), book(), None if attack == "missing_market" else market, deployable=capital()
        )
    assert gate.state.current() == SystemState.HALTED


def test_DAT_11_conflicting_legacy_date_and_forged_estimate_fail_validation(
    boundary_cro: ChiefRiskOfficer,
) -> None:
    estimate = EarningsInfo(
        status=EarningsStatus.ESTIMATED,
        source="SEC estimate",
        window_start=NOW.date(),
        window_end=NOW.date() + timedelta(days=15),
    )
    with pytest.raises(ValidationError):
        MarketContext.model_validate(
            quote().model_copy(update={"earnings": estimate, "next_earnings_date": NOW.date()})
        )
    with pytest.raises(ValidationError):
        earnings_rule(
            quote().model_copy(
                update={"earnings": estimate.model_copy(update={"window_end": None})}
            ),
            NOW,
            Settings(broker_account_type="CASH"),
            boundary_cro.calendar,
        )


@pytest.mark.parametrize("header", ["", "a@example.com", "Project V", "Project V\r\nx@example.com"])
def test_DAT_11_SEC_contact_requires_safe_descriptive_header(header: str) -> None:
    with pytest.raises(ValidationError):
        Settings(broker_account_type="CASH", sec_user_agent=header)


def test_DAT_11_contact_and_source_settings_keep_explicit_safe_defaults() -> None:
    settings = Settings(
        broker_account_type="CASH", sec_user_agent="Project V Fixture contact@example.com"
    )
    assert settings.broker_state_source == "ALPACA" and settings.alpaca_data_plan == "BASIC"
    assert settings.llm_daily_budget_usd == Decimal(0)
