"""XA/CM: malformed measurements cannot replace exact conservative costs."""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.domain.models import Playbook
from backend.evaluation.calibrated_costs import CostCalibration, snapshot
from backend.evaluation.costs import CostContext
from backend.evaluation.fill_quality import DriftCheck, monthly, percentile
from backend.ops.trading_controls import ControlScope
from backend.tests.query_faults import selects_kind
from backend.tests.test_swarm_and_callbacks import Harness, make_research_harness
from backend.tests.test_v_verdict_quality import quality

harness = make_research_harness
D = Decimal
SCOPE = ControlScope(account_id="offline-paper", environment="PAPER")


@pytest.mark.parametrize(
    "values",
    [
        {"high": D(1)},
        {"source_ids": (UUID(int=1),)},
        {"scope": SCOPE},
        {"scope": SCOPE, "source_ids": (UUID(int=1), UUID(int=1)), "observed_at": None},
    ],
)
def test_XA_calibration_cannot_claim_measurements_without_unique_scoped_sources(
    values: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        CostCalibration.model_validate(values)


@pytest.mark.parametrize(
    "volume, expected",
    [(D(500000000), D(3)), (D(50000000), D(7)), (D(49999999), D(17)), (None, D(17))],
)
def test_XA_frozen_snapshot_only_increases_its_liquidity_bucket(
    clock: FrozenClock, volume: Decimal | None, expected: Decimal
) -> None:
    row = CostCalibration(
        scope=SCOPE,
        source_ids=(UUID(int=1),),
        observed_at=clock.now(),
        high=D(3),
        mid=D(7),
        low=D(17),
    )
    context = CostContext(atr14=D(2), median_dollar_volume_20=volume)
    assert row.context(context).calibrated_half_spread_bps == expected
    higher = CostContext.model_validate(
        {
            **context.model_dump(),
            "calibrated_half_spread_bps": D(20),
            "calibration_sha256": "a" * 64,
        }
    )
    assert row.context(higher).calibrated_half_spread_bps == 20
    assert CostCalibration.recorded(row.model_dump(mode="json")) == row
    assert (
        CostCalibration.recorded(CostCalibration().model_dump(mode="json")).context(context)
        == context
    )
    with pytest.raises(ValidationError, match="snapshot hash"):
        CostContext(atr14=D(2), calibrated_half_spread_bps=D(3))


@pytest.mark.parametrize("reference", [True, D(0), D(-1), D("NaN"), D("Infinity")])
def test_XA_bad_slippage_reference_refused(clock: FrozenClock, reference: Any) -> None:
    with pytest.raises(DataIntegrityError):
        quality(clock, 1).slippage(reference)


@pytest.mark.parametrize(
    "values, quantile",
    [
        ([D(1)], D("0.5")),
        ((D("NaN"),), D("0.5")),
        ((D(1),), True),
        ((D(1),), D(-1)),
        ((D(1),), D("NaN")),
    ],
)
def test_XA_percentile_requires_finite_exact_immutable_evidence(values: Any, quantile: Any) -> None:
    with pytest.raises(DataIntegrityError):
        percentile(values, quantile)


@pytest.mark.parametrize("case", ["month", "mutable", "model", "bound"])
def test_XA_monthly_measurement_inventory_refused(clock: FrozenClock, case: str) -> None:
    row = quality(clock, 1)
    samples: Any = [row] if case == "mutable" else (row,) * 100001 if case == "bound" else (row,)
    with pytest.raises(DataIntegrityError):
        monthly(
            SCOPE,
            "bad" if case == "month" else "2026-09",
            "HIGH",
            samples,
            D("NaN") if case == "model" else D(2),
        )


def test_XA_stop_quantiles_and_other_scopes_never_mix(clock: FrozenClock) -> None:
    stop = quality(clock, 1, is_stop=True, limit_price=None)
    other = quality(clock, 2, scope=ControlScope(account_id="other", environment="LIVE"))
    month = monthly(SCOPE, "2026-09", "HIGH", (stop, other), D(2))
    assert month.n == 1 and month.stop_p90_bps == 10
    assert stop.slippage(None) is None
    drift = DriftCheck(
        scope=SCOPE, playbook=Playbook.TREND_50EMA, paper=(D(1),) * 30, oos=(D(1),) * 50, seed=1
    )
    assert drift.flag is False
    with pytest.raises(ValidationError, match="physical paper"):
        DriftCheck(scope=other.scope, playbook=Playbook.TREND_50EMA, paper=(), oos=(), seed=1)


def test_XA_snapshot_filters_other_environments_and_accounts(harness: Harness) -> None:
    ledger = harness.state.ledger
    for scope in (
        SCOPE,
        ControlScope(account_id="other", environment="PAPER"),
        ControlScope(account_id="other", environment="LIVE"),
    ):
        row = monthly(scope, "2026-09", "HIGH", (), D(2))
        ledger.append(SecurityEvent, kind="COST_CALIBRATION", detail=row.model_dump(mode="json"))
    result = snapshot(ledger, "PAPER", scope=SCOPE)
    assert result.high == 2 and result.mid == 0 and len(result.source_ids) == 1
    assert snapshot(ledger, "LIVE").scope == ControlScope(account_id="other", environment="LIVE")


@pytest.mark.parametrize("case", ["bound", "future", "mixed"])
def test_XA_cost_snapshot_refuses_unbounded_future_or_multiple_accounts(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    ledger: Ledger = harness.state.ledger
    row = monthly(SCOPE, "2026-09", "HIGH", (), D(2))
    ledger.append(SecurityEvent, kind="COST_CALIBRATION", detail=row.model_dump(mode="json"))
    if case == "mixed":
        other = type(row).model_validate(
            row.model_copy(update={"scope": ControlScope(account_id="other", environment="PAPER")})
        )
        ledger.append(SecurityEvent, kind="COST_CALIBRATION", detail=other.model_dump(mode="json"))
    else:
        original = Session.scalars

        def scalars(session: Session, statement: Any, *args: Any, **kwargs: Any) -> Any:
            result = original(session, statement, *args, **kwargs)
            if not selects_kind(statement, "COST_CALIBRATION"):
                return result
            projected = [SimpleNamespace(**vars(event)) for event in result]
            if case == "bound":
                return projected * 1001
            projected[0].created_at = ledger.clock.now() + timedelta(seconds=1)
            return projected

        monkeypatch.setattr(Session, "scalars", scalars)
    with pytest.raises(DataIntegrityError):
        snapshot(ledger, "PAPER")
