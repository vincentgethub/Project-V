"""EX-06: absent, repeated, failed, stale-scope and future evidence never unlocks live."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from backend.core.errors import LedgerIntegrityError
from backend.execution.exit_variants import StopMoved, StopRaiseApproval
from backend.execution.stop_readiness import CancelSemanticsProof, raise_history_reasons

NOW = datetime(2026, 10, 11, 20, tzinfo=UTC)


def moves(count: int = 30) -> tuple[StopMoved, ...]:
    return tuple(
        StopMoved(
            approval=StopRaiseApproval(
                raise_id=uuid4(),
                entry_id=uuid4(),
                account_id="unit-paper",
                environment="PAPER",
                symbol="AAPL",
                qty=2,
                old_stop=Decimal(100),
                new_stop=Decimal(101),
                last_trade=Decimal(102),
                atr14=Decimal(2),
                quote_at=NOW - timedelta(days=1),
                checked_at=NOW - timedelta(days=1),
                session=NOW.date() - timedelta(days=2),
                history_sha256="a" * 64,
                config_hash="b" * 64,
                yaml_hash="c" * 64,
            ),
            status="APPLIED",
            confirmed_stop=Decimal(101),
            window_ms=30000,
            completed_at=NOW - timedelta(days=1),
        )
        for _ in range(count)
    )


def proof() -> CancelSemanticsProof:
    return CancelSemanticsProof(
        account_id="unit-paper",
        yaml_hash="c" * 64,
        config_hash="b" * 64,
        oto_entry_id=uuid4(),
        oto_stop_id=uuid4(),
        oco_exit_id=uuid4(),
        oco_stop_id=uuid4(),
        observed_at=NOW,
    )


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "29",
        "missing_integration",
        "wrong_account",
        "yaml",
        "settings",
        "future",
        "failed",
        "window",
        "repaired",
        "duplicate",
    ],
)
def test_EX_06_exact_count_scope_failure_window_and_cancel_proof_boundaries(fault: str) -> None:
    rows, evidence = moves(), proof()
    if fault == "29":
        rows = rows[:-1]
    elif fault == "missing_integration":
        pass
    elif fault == "wrong_account":
        evidence = evidence.model_copy(update={"account_id": "other-paper"})
    elif fault == "yaml":
        evidence = evidence.model_copy(update={"yaml_hash": "d" * 64})
    elif fault == "settings":
        evidence = evidence.model_copy(update={"config_hash": "d" * 64})
    elif fault == "future":
        rows = rows[:-1] + (
            rows[-1].model_copy(update={"completed_at": NOW + timedelta(microseconds=1)}),
        )
    elif fault in {"failed", "window", "repaired"}:
        change = (
            {"status": "FAILED", "confirmed_stop": None}
            if fault == "failed"
            else {"window_ms": 30001}
            if fault == "window"
            else {"status": "REPAIRED"}
        )
        extra = StopMoved.model_validate(rows[-1].model_copy(update=change))
        extra = extra.model_copy(
            update={"approval": extra.approval.model_copy(update={"raise_id": uuid4()})}
        )
        rows = rows + (extra,)
    elif fault == "duplicate":
        rows = (rows[0],) * 30
    if fault == "duplicate":
        with pytest.raises(LedgerIntegrityError, match="repeated raises"):
            raise_history_reasons(rows, (evidence,), yaml_hash="c" * 64, now=NOW)
        return
    reasons = raise_history_reasons(
        rows, () if fault == "missing_integration" else (evidence,), yaml_hash="c" * 64, now=NOW
    )
    assert bool(reasons) is (fault != "none")


def test_EX_06_unavailable_and_unrelated_paper_history_never_qualify() -> None:
    assert raise_history_reasons((), (), yaml_hash="c" * 64, now=NOW)
    assert raise_history_reasons(moves(), (proof(),), yaml_hash="d" * 64, now=NOW)
    foreign = tuple(
        row.model_copy(update={"approval": row.approval.model_copy(update={"account_id": "other"})})
        for row in moves(30)
    )
    assert raise_history_reasons(moves() + foreign, (proof(),), yaml_hash="c" * 64, now=NOW)
