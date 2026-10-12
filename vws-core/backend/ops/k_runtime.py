"""XK-03..07: host composition of registered evidence and reducing controls."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.briefing import PositionView
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
from backend.data.data_layer import BatchBars
from backend.domain.models import (
    MarketStatus,
    Playbook,
    PortfolioSnapshot,
    SizeEvidence,
    TradeProposal,
    snapshot_hash,
)
from backend.evaluation.evidence import OutcomeEvidence, recorded_publication
from backend.evaluation.outcomes import Outcome
from backend.notifications.callbacks import FreshInputs
from backend.ops.desk_source import ConnectedDeskSource
from backend.ops.macro_events import MacroCalendar
from backend.ops.trading_controls import (
    ControlScope,
    TradingControls,
)
from backend.risk.overlays import fit_open_risk
from backend.risk.portfolio_sizing import PortfolioSizer, PortfolioSizing


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
        self.last_sizing: dict[str, PortfolioSizing] = {}
        self._sizer: PortfolioSizer | None = None
        self._sizer_batch: BatchBars | None = None
        self._sizer_policy: str | None = None
        self.entry_variant_allowed: Callable[[], bool] | None = None
        self.playbook_allowed: Callable[[Playbook], bool] | None = None

    def evidence(
        self,
        symbol: str,
        score: Decimal,
        base_qty: int,
        portfolio: PortfolioSnapshot,
        instant: datetime,
    ) -> SizeEvidence:
        """No network inside the hunter; use only its verified completed daily batch."""
        account = PortfolioSnapshot.model_validate(portfolio)
        batch = self.source._batch
        if (
            account.account_id != self.scope.account_id
            or batch is None
            or (
                self.source.calendar.session_close(batch.through)
                + timedelta(minutes=self.config.schedule.daily_scan_delay_minutes)
                > instant
            )
        ):
            raise DataIntegrityError("PR/RS: bound completed daily sizing evidence unavailable")
        policy_hash = self.config.config_hash
        if (
            self._sizer is None
            or self._sizer_batch is not batch
            or self._sizer_policy != policy_hash
        ):
            mappings = {}
            for adjustment in ("SPLIT", "ALL"):
                mappings[adjustment] = {
                    row.symbol: tuple((bar.session_date, bar.close) for bar in row.bars)
                    for row in batch.entries
                    if row.adjustment == adjustment and row.status == MarketStatus.OK
                }
            self._sizer = PortfolioSizer(
                mappings["SPLIT"], mappings["ALL"], self.source.registry, self.config, batch.through
            )
            self._sizer_batch, self._sizer_policy = batch, policy_hash
        ramp = Decimal(1)
        if self.scope.environment == "LIVE":
            if account.high_water_mark <= 0:
                raise DataIntegrityError("XK-06: ramp baseline is unavailable")
            with localcontext() as precision:
                precision.prec = 80
                drawdown = max(
                    Decimal(0), (account.high_water_mark - account.equity) / account.high_water_mark
                )
            ramp = self.controls.observe_ramp(actual_resolved(self.ledger, self.scope), drawdown)[
                0
            ].multiplier
        result = self._sizer.assess(
            symbol,
            score,
            base_qty,
            account,
            auto=self.source.settings.execution_mode != "MANUAL",
            ramp=ramp,
        )
        self.last_sizing[symbol] = result
        return result.factors

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
        if self.entry_variant_allowed is not None and self.entry_variant_allowed() is not True:
            raise ExecutionDisabledError(
                "EX-06: configured exit needs current registered WORKING evidence"
            )
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
        if self.playbook_allowed is not None and self.playbook_allowed(playbook) is not True:
            raise ExecutionDisabledError(
                "EG-01: AUTO earnings-gap requires registered WORKING evidence"
            )
        if self.controls.paused(playbook):
            raise ExecutionDisabledError("XK-05: playbook paused; host re-enable required")
        await self.source.daily(tuple(sorted({checked.symbol, *fresh.portfolio.positions})))
        if self.scope.environment == "LIVE":
            await self.observe_ramp(fresh.portfolio)
        raw_size = signal.structured_thesis["setup"].get("size_evidence")
        prior = None if raw_size is None else SizeEvidence.model_validate(raw_size)
        factors = self.evidence(
            checked.symbol,
            Decimal(signal.structured_thesis["setup"]["score"]),
            checked.qty if prior is None else prior.base_qty,
            fresh.portfolio,
            self.ledger.clock.now(),
        )
        limits = self.source.settings
        cap = (
            min(limits.portfolio_max_open_risk, limits.live_max_open_risk)
            if self.scope.environment == "LIVE"
            else limits.portfolio_max_open_risk
        )
        allowed = fit_open_risk(min(checked.qty, factors.qty), checked, fresh.portfolio, cap)
        self.ledger.append(
            SecurityEvent,
            kind="ENTRY_SIZE_CHECK",
            detail={
                "proposal_id": str(checked.proposal_id),
                "scope": self.scope.model_dump(mode="json"),
                "config_sha256": self.config.config_hash,
                "snapshot_sha256": snapshot_hash(fresh.portfolio),
                "factors": factors.model_dump(mode="json"),
                "original_qty": checked.qty,
                "allowed_qty": allowed,
            },
        )
        return allowed

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
        lines = list(self.macro.warnings(self.ledger.clock.now()))
        if self.last_sizing:
            latest = next(reversed(self.last_sizing.values()))
            lines.append(
                "Regime: "
                + latest.regime
                + " · Top sectors: "
                + (", ".join(latest.relative_strength.top_sectors) or "UNVERIFIED")
            )
        if self.config.rs.use_breadth and len(self.config.watchlist) < 50:
            lines.append("Breadth WARN: fewer than 50 watchlist symbols; the estimate is noisy.")
        return tuple(lines)

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
