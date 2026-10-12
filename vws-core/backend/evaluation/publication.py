"""EV-02/ER-03: account-bound weekly job; local evidence precedes private delivery."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from collections.abc import Awaitable, Callable
from html import escape, unescape
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field

from backend.agents.briefing import pages
from backend.agents.orchestrator import JobCounts
from backend.core.config import CostModelConfig, Settings, YamlConfig
from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError, DataIntegrityError, SafetyError
from backend.core.system_state import SystemStateStore
from backend.data.data_layer import _eligible_session
from backend.data.history import FrozenHistory
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel
from backend.domain.tax_profile import TaxProfile
from backend.evaluation.calibrated_costs import CostCalibration
from backend.evaluation.calibrated_costs import snapshot as cost_snapshot
from backend.evaluation.costs import FeeSchedule
from backend.evaluation.evidence import OutcomeEvidence, save_outcomes
from backend.evaluation.fill_quality import QualityBucket
from backend.evaluation.outcomes import Outcome
from backend.evaluation.security_summary import WeeklySecurity
from backend.evaluation.weekly import (
    ReportContext,
    WeeklyReport,
    build_weekly_report,
    render_weekly,
    report_csv,
    save_report,
)
from backend.ops.trading_controls import ControlScope


class WeeklyInputs(FrozenModel):
    context: ReportContext
    outcomes: tuple[Outcome, ...] = Field(max_length=100000)
    history: FrozenHistory
    fees: FeeSchedule
    cost_policy: CostModelConfig
    tax_profile: TaxProfile
    security: WeeklySecurity | None = None
    calibration: CostCalibration = Field(
        default_factory=CostCalibration, exclude_if=lambda v: v.scope is None
    )


class WeeklySource(Protocol):
    async def weekly_inputs(self) -> WeeklyInputs: ...


class WeeklyPublisher:
    def __init__(
        self,
        state: SystemStateStore,
        settings: Settings,
        config: YamlConfig,
        account_id: str,
        calendar: MarketCalendar,
        root: Path,
        source: WeeklySource,
        notify: Callable[[str, bool], Awaitable[None]],
    ) -> None:
        checked = Settings.validated_copy(settings)
        policy = YamlConfig.model_validate(config)
        policy.assert_settings_consistent(checked)
        if not isinstance(account_id, str) or not 1 <= len(account_id) <= 128:
            raise ConfigurationError("EV-02: an explicit managed account binding is required")
        self.state, self.settings, self.config = state, checked, policy
        self.account_id, self.calendar, self.root = account_id, calendar, root
        self.source, self.notify = source, notify
        self._lock = asyncio.Lock()

    def _quality_table(self) -> tuple[QualityBucket, ...]:
        from zoneinfo import ZoneInfo

        from backend.evaluation.tca_store import calibration, capture_pending, inventory

        physical_scope = ControlScope(
            account_id=self.account_id,
            environment="PAPER" if self.settings.paper_trading else "LIVE",
        )
        capture_pending(self.state.ledger, physical_scope)
        fills = inventory(self.state.ledger, physical_scope)
        months = tuple(
            sorted(
                {
                    row.filled_at.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m")
                    for row in fills
                }
            )
        )[-12:]
        table: list[QualityBucket] = []
        floors = self.config.cm.spread_floor_bps
        for month in months:
            for bucket, floor in (("HIGH", floors.high), ("MID", floors.mid), ("LOW", floors.low)):
                table.append(calibration(self.state.ledger, physical_scope, month, bucket, floor))
        return tuple(table)

    def _publish(self, inputs: WeeklyInputs, cancelled: threading.Event) -> WeeklyReport:
        self.state.ledger.verify_chain()
        bound = WeeklyInputs.model_validate(inputs)
        expected: Literal["PAPER", "LIVE"] = "PAPER" if self.settings.paper_trading else "LIVE"
        if (
            bound.context.account_id != self.account_id
            or bound.context.cohort != expected
            or bound.context.config_sha256 != self.config.config_hash
            or bound.cost_policy != self.config.cm
            or bound.calibration
            != cost_snapshot(
                self.state.ledger,
                expected,
                scope=ControlScope(account_id=self.account_id, environment=expected),
            )
        ):
            raise DataIntegrityError("EV-02: weekly account/mode/configuration binding differs")
        tail = _eligible_session(self.calendar, self.state.clock.now(), 30)
        if bound.context.end > tail or any(
            series.sessions[-1] > tail for series in bound.history.bundle.series
        ):
            raise DataIntegrityError(
                "EV-02: weekly history contains uncompleted or future sessions"
            )
        if bound.security is not None and bound.security.as_of > self.state.clock.now():
            raise DataIntegrityError("SEC-72: weekly security evidence is in the future")
        report = build_weekly_report(
            bound.context,
            bound.outcomes,
            bound.history,
            self.calendar,
            bound.fees,
            bound.cost_policy,
            bound.tax_profile,
            security=bound.security,
            calibration=bound.calibration,
        )
        table = self._quality_table()
        if bound.calibration != cost_snapshot(
            self.state.ledger,
            expected,
            scope=ControlScope(account_id=self.account_id, environment=expected),
        ):
            raise DataIntegrityError(
                "XA-01: costs changed during publication; rebuild the report with current calibration"
            )
        if table:
            report = WeeklyReport.model_validate(
                {**report.model_dump(), "fill_quality": tuple(table)}
            )
        if expected == "PAPER":
            from backend.evaluation.fill_quality import drift_rows

            report = WeeklyReport.model_validate(
                {
                    **report.model_dump(),
                    "drift": drift_rows(
                        self.state.ledger,
                        self.settings,
                        self.config,
                        ControlScope(account_id=self.account_id, environment="PAPER"),
                        bound.fees,
                    ),
                }
            )
        if cancelled.is_set():
            raise DataIntegrityError("EV-02: canceled weekly work cannot publish")
        json_path, csv_path = save_report(self.root, report)
        evidence = OutcomeEvidence(
            report=report,
            outcomes=tuple(sorted(bound.outcomes, key=lambda item: item.setup.alert_id.hex)),
        )
        outcomes_path = save_outcomes(self.root, evidence)
        text = render_weekly(report, mask_amounts=self.settings.telegram_mask_amounts)
        if cancelled.is_set():
            raise DataIntegrityError("EV-02: canceled report cannot claim a ledger publication")
        # Ledger holds the canonical report proof; display amounts are rebuilt
        # from that proof under the current masking policy by /report and /edge.
        self.state.ledger.append(
            SecurityEvent,
            kind="WEEKLY_REPORT",
            detail={
                "account_id": self.account_id,
                "cohort": expected,
                "report_sha256": report.sha256,
                "manifest_sha256": report.manifest_sha256,
                "report": report.model_dump(mode="json"),
                "outcome_evidence": evidence.model_dump(mode="json"),
                "outcomes_sha256": evidence.sha256,
                "outcomes_filename": outcomes_path.name,
                "json_filename": json_path.name,
                "csv_filename": csv_path.name,
                "csv_sha256": hashlib.sha256(report_csv(report)).hexdigest(),
                "text": text,
            },
        )
        return report

    async def __call__(self) -> JobCounts:
        """A halt suppresses entries, not reporting. No source or settings are changed."""
        async with self._lock:
            cancelled = threading.Event()
            try:
                async with asyncio.timeout(60):
                    await asyncio.to_thread(self._quality_table)
                    inputs = await self.source.weekly_inputs()
                    report = await asyncio.to_thread(self._publish, inputs, cancelled)
                for page in pages(
                    escape(render_weekly(report, mask_amounts=self.settings.telegram_mask_amounts))
                ):
                    await self.notify(unescape(page), False)
                return JobCounts(
                    counts={
                        "report_cards": len(report.cards),
                        "resolved": sum(
                            card.n
                            for card in report.cards
                            if card.key.fundamentals_status is None
                            and card.key.disposition
                            not in {"CRO_VETO", "RS_FILTER", "PR_FILTER", "SZ_FILTER"}
                        ),
                    }
                )
            except asyncio.CancelledError:
                cancelled.set()
                await asyncio.shield(
                    asyncio.to_thread(
                        self.state.halt_for_error,
                        DataIntegrityError("EV-02: weekly report canceled"),
                    )
                )
                raise
            except Exception as error:
                cancelled.set()
                await asyncio.to_thread(self.state.halt_for_error, error)
                if isinstance(error, SafetyError):
                    raise error from None
                raise DataIntegrityError(
                    "EV-02: weekly publication failed; entries halted"
                ) from None
