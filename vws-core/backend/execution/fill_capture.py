"""AX-26/40: canonical fill capture independent of order execution."""

from sqlalchemy import select

from backend.core.database import ExecutionFillRecord, ExecutionOrderRecord, transaction
from backend.core.errors import ReconciliationError
from backend.data.fill_polling import ObservedFill
from backend.execution.modes import ModeStore
from backend.execution.storage import bindings


class ExecutionFillCapture:
    def __init__(self, modes: ModeStore) -> None:
        self.modes, self.state = modes, modes.state

    def record(self, observation: ObservedFill) -> ExecutionFillRecord:
        try:
            fill = ObservedFill.model_validate(observation)
            self.state.ledger.verify_chain()
            with transaction(self.state.engine) as session:
                proved = bindings(session)
                matching = tuple(
                    key for key, row in proved.items() if row.order_id == fill.broker_order_id
                )
                if len(matching) != 1:
                    raise ReconciliationError(
                        "Unknown broker fill; manual trading belongs in a different account"
                    )
                instruction = session.get(ExecutionOrderRecord, matching[0])
                if (
                    instruction is None
                    or fill.account_id != self.modes.account_id
                    or instruction.account_id != fill.account_id
                    or instruction.environment != self.modes.environment
                    or instruction.symbol != fill.symbol
                    or instruction.side != fill.side.value
                ):
                    raise ReconciliationError("Broker fill account, symbol or side differs")
                previous = session.scalar(
                    select(ExecutionFillRecord).where(
                        ExecutionFillRecord.broker_fill_id == fill.broker_fill_id
                    )
                )
                if previous is not None:
                    if (
                        previous.execution_order_id != instruction.id
                        or previous.qty != fill.qty
                        or previous.price != fill.price
                        or previous.filled_at != fill.filled_at
                    ):
                        raise ReconciliationError(
                            "Repeated broker fill changed its identity or values"
                        )
                    return previous
                return self.state.ledger.record_fill(
                    instruction.order_id,
                    execution_order_id=instruction.id,
                    broker_fill_id=fill.broker_fill_id,
                    qty=fill.qty,
                    price=fill.price,
                    filled_at=fill.filled_at,
                    session=session,
                )
        except Exception as error:
            self.state.halt_for_error(error)
            raise ReconciliationError("Auto fill failed closed; inspect account evidence") from None
