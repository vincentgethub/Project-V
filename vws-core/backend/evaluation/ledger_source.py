"""EV-01/02: immutable proposal costs feed the actual weekly job."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from backend.core.config import Settings, YamlConfig
from backend.core.errors import ConfigurationError, DataIntegrityError
from backend.core.system_state import SystemStateStore
from backend.data.history import FrozenHistory, validate_history
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel
from backend.evaluation.costs import FeeSchedule
from backend.evaluation.ledger_inputs import collect_tracked_setups
from backend.evaluation.outcomes import _simulate
from backend.evaluation.publication import WeeklyInputs
from backend.evaluation.registry import refuse_registered_holdout
from backend.evaluation.security_summary import weekly_security
from backend.evaluation.weekly import ReportContext


class WeeklyHistory(FrozenModel):
    context: ReportContext
    history: FrozenHistory


class WeeklyHistorySource(Protocol):
    async def weekly_history(self) -> WeeklyHistory: ...


class LedgerWeeklySource:
    def __init__(
        self,
        state: SystemStateStore,
        settings: Settings,
        config: YamlConfig,
        account_id: str,
        calendar: MarketCalendar,
        history_source: WeeklyHistorySource,
        fees: FeeSchedule,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.config = YamlConfig.model_validate(config)
        self.config.assert_settings_consistent(self.settings)
        if not isinstance(account_id, str) or not 1 <= len(account_id) <= 128:
            raise ConfigurationError("EV-02: weekly source requires a managed account")
        self.state, self.account_id, self.calendar = state, account_id, calendar
        self.history_source, self.fees = history_source, FeeSchedule.model_validate(fees)

    def _build(self, evidence: WeeklyHistory) -> WeeklyInputs:
        try:
            bound = WeeklyHistory.model_validate(evidence)
            context = bound.context
            refuse_registered_holdout(self.state.ledger, context.start, context.end)
            if (
                context.account_id != self.account_id
                or context.cohort != ("PAPER" if self.settings.paper_trading else "LIVE")
                or context.config_sha256 != self.config.config_hash
            ):
                raise ValueError("weekly source account/mode/configuration differs")
            validate_history(bound.history.bundle, self.calendar)
            tracked = collect_tracked_setups(
                self.state.ledger, self.settings, context, self.calendar
            )
            if any(item.provenance.cost_context.policy != self.config.cm for item in tracked):
                raise ValueError("recorded costs use a different policy")
            baseline = None
            if tracked and tracked[0].provenance.initial_equity > 0:
                baseline = tracked[0].provenance.initial_equity
            if context.initial_equity is not None and context.initial_equity != baseline:
                raise ValueError("weekly seed differs from the earliest recorded equity")
            context = ReportContext.model_validate(
                {**context.model_dump(), "initial_equity": baseline}
            )
            from backend.evaluation.calibrated_costs import snapshot as cost_snapshot
            from backend.ops.trading_controls import ControlScope

            cost_scope = ControlScope(
                account_id=self.account_id,
                environment="PAPER" if self.settings.paper_trading else "LIVE",
            )
            calibration = cost_snapshot(self.state.ledger, cost_scope.environment, scope=cost_scope)
            outcomes = tuple(
                _simulate(
                    type(item.setup).model_validate(
                        {
                            **item.setup.model_dump(),
                            "variant": "baseline"
                            if self.config.exits.variant == "BASELINE"
                            else self.config.exits.variant,
                        }
                    ),
                    bound.history,
                    calibration.context(item.provenance.cost_context),
                    self.fees,
                    self.config.evaluation,
                    None,
                    context.end,
                    exit_variant=self.config.exits.variant,
                )
                for item in tracked
            )
            return WeeklyInputs(
                context=context,
                outcomes=outcomes,
                history=bound.history,
                fees=self.fees,
                cost_policy=self.config.cm,
                tax_profile=self.settings.tax_profile,
                security=weekly_security(
                    self.state.ledger,
                    self.settings,
                    datetime.combine(
                        context.start, datetime.min.time(), ZoneInfo("America/New_York")
                    ),
                ),
                calibration=calibration,
            )
        except DataIntegrityError:
            raise
        except Exception:
            raise DataIntegrityError("EV-02: weekly ledger inputs are unverifiable") from None

    async def weekly_inputs(self) -> WeeklyInputs:
        return await asyncio.to_thread(self._build, await self.history_source.weekly_history())
