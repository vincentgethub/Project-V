"""EV-01: real research/approval rows feed every visible tracker disposition."""

from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from backend.agents.fundamentals import FrameworkStatus
from backend.core.database import Alert, ApprovalEvent, Signal
from backend.core.errors import DataIntegrityError
from backend.core.system_state import SystemState
from backend.evaluation.ledger_inputs import collect_outcome_setups
from backend.evaluation.weekly import ReportContext
from backend.tests.test_swarm_and_callbacks import (  # noqa: F401
    Harness,
    ack,
    click,
    deliver,
    make_research_harness,
)


def scope(h: Harness, **values: Any) -> ReportContext:
    day = h.request.candidate.as_of.astimezone(ZoneInfo("America/New_York")).date()
    return ReportContext.model_validate(
        {
            "account_id": h.request.portfolio.account_id,
            "cohort": "PAPER",
            "start": day,
            "end": h.swarm.risk.cro.calendar.add_sessions(day, 1),
            "config_sha256": h.swarm.config.config_hash,
            **values,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["PENDING", "SENT", "APPROVED", "REJECTED", "EXPIRED", "REVALIDATION_FAILED"]
)
async def test_EV_01_each_alert_state_uses_recorded_levels_qty_expiry_and_facts(
    harness: Harness, state: str
) -> None:
    h = harness
    if state == "PENDING":
        result = await h.swarm.run(h.request)
        with Session(h.state.engine) as session:
            alert = session.get(Alert, result.alert_id)
            assert alert is not None
    else:
        alert = await deliver(h)
        if state in {"APPROVED", "REJECTED"}:
            await h.gate.handle(click(h, "A" if state == "APPROVED" else "R"), acknowledge=ack)
        elif state == "EXPIRED":
            h.clock.current = alert.expires_at
            h.state.ledger.append(ApprovalEvent, alert_id=alert.id, action="EXPIRED", reasons=[])
        elif state == "REVALIDATION_FAILED":
            h.state.ledger.append(
                ApprovalEvent,
                alert_id=alert.id,
                action="REVALIDATION_FAILED",
                reasons=[{"rule_id": "CRO-01", "message": "test invalidation"}],
            )
    rows = collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)
    assert len(rows) == 1
    setup = rows[0]
    assert setup.alert_id == alert.id and setup.qty == h.request.candidate.qty
    assert (
        setup.limit == h.request.candidate.entry_price
        and setup.stop == h.request.candidate.stop_price
    )
    assert setup.target == h.request.candidate.target_price
    assert setup.disposition == ("PENDING" if state == "SENT" else state)
    assert setup.fundamentals_status == FrameworkStatus.INCOMPLETE
    assert (
        setup.valid_until_session
        == alert.expires_at.astimezone(ZoneInfo("America/New_York")).date()
    )
    h.state.ledger.verify_chain()


@pytest.mark.asyncio
async def test_EV_01_cro_veto_has_distinct_shadow_identity_and_no_invented_fundamentals(
    harness: Harness,
) -> None:
    h = harness
    h.state.escalate(SystemState.HALTED, "test entry halt")
    result = await h.swarm.run(h.request)
    assert result.status == "VETOED" and result.proposal is not None
    rows = collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)
    assert len(rows) == 1 and rows[0].disposition == "CRO_VETO"
    assert rows[0].fundamentals_status == FrameworkStatus.INCOMPLETE
    assert rows[0].alert_id != result.proposal.proposal_id
    assert rows == collect_outcome_setups(
        h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar
    )
    assert h.news.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["mode", "config", "expiry", "price_float", "shares", "legacy"])
async def test_EV_01_bad_tracker_evidence_is_refused(
    harness: Harness, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    await h.swarm.run(h.request)
    if fault in {"mode", "config"}:
        invalid = scope(
            h, **({"cohort": "LIVE"} if fault == "mode" else {"config_sha256": "f" * 64})
        )
        with pytest.raises(DataIntegrityError):
            collect_outcome_setups(h.state.ledger, h.settings, invalid, h.swarm.risk.cro.calendar)
        return
    original = Session.get

    def injected(session: Session, model: Any, identity: Any, *args: Any, **kwargs: Any) -> Any:
        row = original(session, model, identity, *args, **kwargs)
        if model is Signal and row is not None:
            data = {
                **row.structured_thesis,
                "setup": dict(row.structured_thesis["setup"]),
                "evaluation_provenance": dict(row.structured_thesis["evaluation_provenance"]),
            }
            if fault == "expiry":
                data["evaluation_provenance"]["expires_at"] = "2026-10-30T20:00:00+00:00"
            elif fault == "price_float":
                data["setup"]["entry_price"] = 101.76
            elif fault == "shares":
                data["setup"]["qty"] += 1
            else:
                data.pop("evaluation_provenance")
            row.structured_thesis = data
        return row

    monkeypatch.setattr(Session, "get", injected)
    with pytest.raises(DataIntegrityError):
        collect_outcome_setups(h.state.ledger, h.settings, scope(h), h.swarm.risk.cro.calendar)


@pytest.mark.asyncio
async def test_EV_01_outside_period_and_other_accounts_are_not_mixed(harness: Harness) -> None:
    h = harness
    await h.swarm.run(h.request)
    assert (
        collect_outcome_setups(
            h.state.ledger, h.settings, scope(h, account_id="other"), h.swarm.risk.cro.calendar
        )
        == ()
    )
    future = h.swarm.risk.cro.calendar.add_sessions(scope(h).end, 1)
    shifted = scope(h, start=future, end=h.swarm.risk.cro.calendar.add_sessions(future, 1))
    assert (
        collect_outcome_setups(h.state.ledger, h.settings, shifted, h.swarm.risk.cro.calendar) == ()
    )
