"""XK-03..07: host composition of registered evidence and reducing controls."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import PositionView
from backend.agents.indicators import ema
from backend.core.config import YamlConfig
from backend.core.database import (
    CashFlow,
    ExecutionFillRecord,
    ExecutionOrderRecord,
    SecurityEvent,
    SystemEvent,
)
from backend.core.errors import DataIntegrityError, ExecutionDisabledError
from backend.core.ledger import Ledger
from backend.domain.models import MarketStatus, Playbook, PortfolioSnapshot, TradeProposal
from backend.evaluation.evidence import OutcomeEvidence, recorded_publication
from backend.evaluation.outcomes import Outcome
from backend.notifications.callbacks import FreshInputs
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.macro_events import MacroCalendar
from backend.ops.trading_controls import (
    ControlScope,
    TradingControls,
    reduced_quantity,
    regime_multiplier,
)


def tracker_outcomes(ledger: Ledger, scope: ControlScope) -> tuple[Outcome, ...]:
    """Latest authenticated G outcome per identity, preserving paper/live binding."""
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        rows = tuple(
            session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.kind == "WEEKLY_REPORT")
                .order_by(SecurityEvent.seq)
                .limit(100001)
            )
        )
        if len(rows) > 100000:
            raise DataIntegrityError("XK-05: tracker publications exceed their bound")
        latest = {}
        for row in rows:
            if row.ts > ledger.clock.now():
                raise DataIntegrityError("XK-05: future tracker publication")
            report = recorded_publication(row.detail)
            if (
                report.context.account_id != scope.account_id
                or report.context.cohort != scope.environment
            ):
                continue
            proof = OutcomeEvidence.from_recorded(row.detail["outcome_evidence"])
            for outcome in proof.outcomes:
                latest[outcome.setup.alert_id] = outcome
        return tuple(latest[key] for key in sorted(latest, key=str))


def actual_resolved(ledger: Ledger, scope: ControlScope) -> int:
    """Count completed physical round trips; hypothetical G results never raise ramp."""
    ledger.verify_chain()
    with Session(ledger.engine) as session:
        entries = tuple(
            session.scalars(
                select(ExecutionOrderRecord)
                .where(
                    ExecutionOrderRecord.account_id == scope.account_id,
                    ExecutionOrderRecord.environment == scope.environment,
                    ExecutionOrderRecord.role == "ENTRY",
                )
                .limit(100001)
            )
        )
        if len(entries) > 100000:
            raise DataIntegrityError("XK-06: physical history exceeds its bound")
        count = 0
        for entry in entries:
            rows = tuple(
                session.execute(
                    select(ExecutionFillRecord, ExecutionOrderRecord.side)
                    .join(
                        ExecutionOrderRecord,
                        ExecutionFillRecord.execution_order_id == ExecutionOrderRecord.id,
                    )
                    .where(
                        (ExecutionOrderRecord.id == entry.id)
                        | (ExecutionOrderRecord.parent_execution_id == entry.id)
                    )
                    .limit(100001)
                )
            )
            if len(rows) > 100000 or any(fill.filled_at > ledger.clock.now() for fill, _ in rows):
                raise DataIntegrityError("XK-06: physical fills are unbounded or future")
            bought = sum(fill.qty for fill, side in rows if side == "BUY")
            sold = sum(fill.qty for fill, side in rows if side == "SELL")
            if sold > bought:
                raise DataIntegrityError("XK-06: physical round trip oversold")
            count += int(bought > 0 and bought == sold)
        return count


class ExtraControls:
    def __init__(
        self,
        ledger: Ledger,
        scope: ControlScope,
        config: YamlConfig,
        source: ConnectedDeskSource,
        macro: MacroCalendar,
        notify: Callable[[str, bool], Awaitable[None]],
    ) -> None:
        self.ledger, self.scope, self.config = ledger, scope, YamlConfig.model_validate(config)
        self.source, self.macro, self.notify = source, macro, notify
        self.controls = TradingControls(ledger, scope)

    def update_playbooks(self) -> None:
        sample = tracker_outcomes(self.ledger, self.scope)
        for playbook in Playbook:
            self.controls.evaluate_playbook(
                playbook,
                tuple(
                    row.r_multiple
                    for row in sample
                    if row.status == "RESOLVED"
                    and row.setup.playbook == playbook
                    and row.setup.variant == "baseline"
                    and row.setup.disposition == "APPROVED"
                    and row.r_multiple is not None
                ),
            )

    async def size(self, proposal: TradeProposal, inputs: FreshInputs) -> int:
        checked = TradeProposal.model_validate(proposal)
        fresh = FreshInputs.model_validate(inputs)
        if (
            checked.account_id != self.scope.account_id
            or fresh.portfolio.account_id != self.scope.account_id
        ):
            raise DataIntegrityError("XK-03/06: sizing account differs")
        self.update_playbooks()
        with Session(self.ledger.engine) as session:
            from backend.core.database import Order, Signal

            order = session.scalar(select(Order).where(Order.proposal_id == checked.proposal_id))
            signal = None if order is None else session.get(Signal, order.signal_id)
            if signal is None:
                raise DataIntegrityError("XK-05: entry has no deterministic playbook")
            playbook = Playbook(signal.structured_thesis["setup"]["playbook"])
        if self.controls.paused(playbook):
            raise ExecutionDisabledError("XK-05: playbook paused; host re-enable required")
        batch = await self.source.daily(("SPY",))
        if batch.status_for("SPY", "ALL") != MarketStatus.OK:
            raise DataIntegrityError("XK-03: SPY daily evidence is unavailable or suspect")
        spy = batch.for_symbol("SPY", "ALL")
        average = None if not spy else ema(tuple(row.close for row in spy), 200)[-1]
        regime = regime_multiplier(
            None if not spy else spy[-1].close, average, self.config.regime_filter, auto=True
        )
        ramp = Decimal(1)
        if self.scope.environment == "LIVE":
            ramp = await self.observe_ramp(fresh.portfolio)
        return reduced_quantity(checked.qty, (regime, ramp))

    async def observe_ramp(self, portfolio: PortfolioSnapshot) -> Decimal:
        bound = PortfolioSnapshot.model_validate(portfolio)
        if (
            bound.account_id != self.scope.account_id
            or bound.as_of > self.ledger.clock.now()
            or bound.high_water_mark <= 0
        ):
            raise DataIntegrityError("XK-06: ramp portfolio differs or is future")
        with localcontext() as precision:
            precision.prec = 80
            drawdown = max(
                Decimal(0), (bound.high_water_mark - bound.equity) / bound.high_water_mark
            )
        state, changed = self.controls.observe_ramp(
            actual_resolved(self.ledger, self.scope), drawdown
        )
        if changed:
            await self.notify(
                f"LIVE · Capital ramp now {state.multiplier * 100}% of computed shares; safety ceilings still apply.",
                False,
            )
        return state.multiplier

    def status(self) -> tuple[str, ...]:
        return self.macro.warnings(self.ledger.clock.now())

    async def briefing(self, view: PositionView, pending: int) -> str | None:
        checked = PositionView.model_validate(view)
        now = self.ledger.clock.now()
        day = now.astimezone(ZoneInfo("America/New_York")).date()
        lines = [f"Entries awaiting fresh checks: {pending}"] if pending else []
        for event in self.macro.read():
            if event.date == day:
                lines.append(
                    f"{event.event} today; new auto entries blocked until release + 30 minutes."
                )
        for quote in checked.quotes:
            earnings = quote.market.next_earnings_date
            if earnings is not None and day <= earnings <= self.source.calendar.add_sessions(
                day, 5
            ):
                lines.append(f"{quote.symbol}: earnings within five sessions.")
        with Session(self.ledger.engine) as session:
            halts = session.scalar(
                select(SystemEvent.id)
                .where(
                    SystemEvent.created_at >= now - timedelta(hours=16),
                    SystemEvent.state == "HALTED",
                )
                .limit(1)
            )
            withdrawals = session.scalar(
                select(CashFlow.id)
                .where(
                    CashFlow.created_at >= now - timedelta(hours=16),
                    CashFlow.account_id == self.scope.account_id,
                    CashFlow.env == self.scope.environment,
                    CashFlow.amount < Decimal(0),
                )
                .limit(1)
            )
        if halts is not None:
            lines.append("An overnight halt needs host review.")
        if withdrawals is not None:
            lines.append("An overnight withdrawal needs review.")
        lines.extend(self.status())
        if any(quote.market.status.value != "OK" for quote in checked.quotes):
            lines.append("A held symbol has stale or suspect data.")
        try:
            batch = await self.source.daily(("SPY",))
            if any(
                batch.status_for(symbol, "ALL") != MarketStatus.OK
                for symbol in ("SPY", *self.config.watchlist)
            ):
                lines.append("A required daily data source is stale or suspect.")
        except Exception as error:
            self.ledger.append(
                SecurityEvent,
                kind="K_BRIEFING_DATA_UNAVAILABLE",
                detail={"error_type": type(error).__name__},
            )
            lines.append("A required daily data source is unavailable.")
        return (
            None if not lines else "Morning briefing · " + day.isoformat() + "\n" + "\n".join(lines)
        )
