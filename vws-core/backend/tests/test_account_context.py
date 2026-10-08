"""H/J: missing and stale account evidence cannot become verified empty sets."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from backend.core.clock import FrozenClock
from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError, ProviderError
from backend.core.notifier import ConsoleNotifier
from backend.core.system_state import SystemStateStore
from backend.domain.compliance_models import ExternalAccount, TaxLot, TaxStatus, TradeRecord
from backend.domain.models import Side
from backend.ops.account_context import AccountContext, LedgerAccountContext


def evidence(clock: FrozenClock) -> AccountContext:
    trade = uuid4()
    return AccountContext(
        account_id="synthetic-paper",
        cohort="PAPER",
        as_of=clock.now(),
        accounts=(
            ExternalAccount(account_id="synthetic-paper", tax_status=TaxStatus.TAXABLE),
            ExternalAccount(account_id="synthetic-roth", tax_status=TaxStatus.ROTH),
        ),
        lots=(
            TaxLot(
                lot_id=uuid4(),
                account_id="synthetic-paper",
                symbol="AAPL",
                qty=2,
                acquired_at=clock.now() - timedelta(days=5),
                cost_basis=Decimal("123.00"),
                funding_settlement_date=(clock.now() - timedelta(days=4)).date(),
                acquisition_trade_id=trade,
            ),
        ),
        history=(
            TradeRecord(
                trade_id=trade,
                account_id="synthetic-paper",
                symbol="AAPL",
                side=Side.BUY,
                qty=2,
                price=Decimal("123.00"),
                ts=clock.now() - timedelta(days=5),
            ),
        ),
    )


def test_H_J_verified_context_roundtrips_exact_lots_and_all_accounts(
    engine: Engine, clock: FrozenClock
) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    original = evidence(clock)
    state.ledger.append(
        SecurityEvent, kind="ACCOUNT_RESEARCH_CONTEXT", detail=original.model_dump(mode="json")
    )
    assert LedgerAccountContext(state, "synthetic-paper", "PAPER").read() == original
    state.ledger.verify_chain()


@pytest.mark.parametrize(
    "fault", ["missing", "different_account", "live", "stale", "extra", "future", "corrupt_lot"]
)
def test_H_J_unverified_context_never_yields_empty_pass(
    engine: Engine, clock: FrozenClock, fault: str
) -> None:
    state = SystemStateStore(engine, clock, ConsoleNotifier())
    payload = evidence(clock).model_dump(mode="json")
    if fault == "different_account":
        payload["account_id"] = "unrelated"
    if fault == "live":
        payload["cohort"] = "LIVE"
    if fault == "stale":
        payload["as_of"] = (clock.now() - timedelta(seconds=31)).isoformat()
    if fault == "future":
        payload["as_of"] = (clock.now() + timedelta(seconds=1)).isoformat()
    if fault == "extra":
        payload["invented_pass"] = True
    if fault == "corrupt_lot":
        payload["lots"][0]["cost_basis"] = "NaN"
    if fault != "missing":
        state.ledger.append(SecurityEvent, kind="ACCOUNT_RESEARCH_CONTEXT", detail=payload)
    with pytest.raises((ProviderError, DataIntegrityError)):
        LedgerAccountContext(state, "synthetic-paper", "PAPER").read()
