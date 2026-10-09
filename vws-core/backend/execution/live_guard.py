"""AX-40/41: verified local history and host-only live unlock; no SDK imports."""

from collections.abc import Callable
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import ensure_utc
from backend.core.config import Settings
from backend.core.database import AutoJobRun, JobRun, SecurityEvent, SystemEvent
from backend.core.errors import ConfigurationError, ExecutionDisabledError
from backend.core.system_state import SystemStateStore
from backend.data.market_calendar import MarketCalendar
from backend.evaluation.evidence import recorded_publication
from backend.execution.control_evidence import JobBinding, LiveEnable
from backend.execution.policy import require_live_limits

LIVE_WARNING = (
    "Auto mode places real orders without asking you each time. In AUTO_LIVE it trades your real money, "
    "and you can lose money, including more than a stop-loss suggests (gaps, halts, outages). "
    "Nothing in this software predicts or guarantees profits; paper results don't predict live results. "
    "Auto mode works only with Alpaca. Start with AUTO_PAPER, keep live limits small, "
    "and use /halt or /manual any time to stop new trades."
)
LIVE_PHRASE = "I UNDERSTAND THIS TRADES REAL MONEY"
_NY = ZoneInfo("America/New_York")


class LiveGuard:
    def __init__(
        self,
        settings: Settings,
        state: SystemStateStore,
        calendar: MarketCalendar,
        account_id: str,
        effective_hash: Callable[[], str],
        *,
        validation_ready: Callable[[], bool] | None = None,
        feeds_healthy: Callable[[], bool] | None = None,
        security_reasons: Callable[[], tuple[str, ...]] | None = None,
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.state, self.calendar, self.account_id = state, calendar, account_id
        self.effective_hash, self.validation_ready, self.feeds_healthy = (
            effective_hash,
            validation_ready,
            feeds_healthy,
        )
        self.security_reasons = security_reasons

    def _history(self) -> tuple[str | None, list[str]]:
        self.state.ledger.verify_chain()
        now = ensure_utc(self.state.clock.now())
        with Session(self.state.engine) as session:
            auto = tuple(
                session.scalars(
                    select(AutoJobRun)
                    .where(
                        AutoJobRun.job == "auto_entry",
                        AutoJobRun.environment == "PAPER",
                        AutoJobRun.outcome == "PASS",
                    )
                    .order_by(AutoJobRun.seq)
                )
            )
            events = tuple(session.scalars(select(SecurityEvent).order_by(SecurityEvent.seq)))
            daily = {
                str(row.id): row
                for row in session.scalars(
                    select(JobRun).where(
                        JobRun.job == "daily_scan",
                        JobRun.outcome == "PASS",
                    )
                )
            }
            halts = tuple(session.scalars(select(SystemEvent).where(SystemEvent.state == "HALTED")))
        bound = tuple(
            JobBinding.model_validate(row.detail)
            for row in events
            if row.kind == "DESK_JOB_BINDING"
        )
        accounts = {row.account_id for row in auto}
        sessions = {}
        for account in accounts:
            auto_days = {
                row.started_at.astimezone(_NY).date() for row in auto if row.account_id == account
            }
            daily_days = {
                daily[str(item.job_run_id)].started_at.astimezone(_NY).date()
                for item in bound
                if item.environment == "PAPER"
                and item.account_id == account
                and str(item.job_run_id) in daily
            }
            sessions[account] = sorted(
                day for day in auto_days & daily_days if self.calendar.is_session(day)
            )
        qualified = [
            account
            for account, days in sessions.items()
            if len(days) >= self.settings.auto_live_min_paper_sessions
        ]
        reasons = []
        if len(qualified) != 1:
            return None, [
                "AX-40: select one verified paper account with at least 20 successful paired XNYS sessions"
            ]
        paper = qualified[0]
        days = sessions[paper]
        threshold = self.calendar.session_close(
            days[self.settings.auto_live_min_paper_sessions - 1]
        )
        reports = [
            row
            for row in events
            if row.kind == "WEEKLY_REPORT"
            and row.detail.get("account_id") == paper
            and row.detail.get("cohort") == "PAPER"
            and threshold < row.ts <= now
        ]
        if not reports:
            reasons.append("AX-40: a Stage G report after the twentieth paper session is required")
        else:
            for row in reports:
                recorded_publication(row.detail)
        last_five = self.calendar.session_open(days[-5])
        if any(last_five <= row.created_at <= now for row in halts):
            reasons.append("AX-40: a HALT occurred in the last five paper sessions")
        if not any(
            row.kind == "HOST_ACCOUNTING_READY"
            and row.detail.get("account_id") == self.account_id
            and row.detail.get("environment") == "LIVE"
            and row.detail.get("config_hash") == self.settings.config_hash
            for row in events
        ):
            reasons.append(
                "AX-40: Stage J account activity, P&L and tax capture must be verified for this live account"
            )
        if not any(
            row.kind == "KILL_SWITCH_DRILL_PASSED"
            and timedelta(0) <= now - row.ts <= timedelta(days=45)
            for row in events
        ):
            reasons.append(
                "AX-40: a passed scratch-account kill-switch drill within 45 days is required"
            )
        return paper, reasons

    def reasons(self, *, require_unlock: bool = True) -> tuple[str, ...]:
        require_live_limits(self.settings)
        paper, findings = self._history()
        if self.security_reasons is None:
            findings.append("Amendment 03 section 10: live security evidence is unavailable")
        else:
            findings.extend(self.security_reasons())
        if self.validation_ready is None or self.validation_ready() is not True:
            findings.append(
                "Amendment 05: registered validation must produce a current READY verdict"
            )
        if self.feeds_healthy is None or self.feeds_healthy() is not True:
            findings.append(
                "Amendment 06: all required realtime feeds must be healthy for at least five sessions"
            )
        if require_unlock:
            with Session(self.state.engine) as session:
                latest = session.scalar(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind.in_(("LIVE_ENABLED", "LIVE_DISABLED")))
                    .order_by(SecurityEvent.seq.desc())
                    .limit(1)
                )
            if latest is None or latest.kind != "LIVE_ENABLED":
                findings.append("AX-41: explicit host enable-live has not been recorded")
            else:
                proof = LiveEnable.model_validate(latest.detail)
                if (
                    proof.account_id != self.account_id
                    or proof.paper_account_id != paper
                    or proof.config_hash != self.settings.config_hash
                    or proof.effective_hash != self.effective_hash()
                ):
                    findings.append("AX-41: live unlock account or configuration binding changed")
        return tuple(findings)

    def assert_ready(self) -> None:
        findings = self.reasons()
        if findings:
            raise ExecutionDisabledError("AUTO_LIVE locked: " + "; ".join(findings))

    def enable(self, *, operator: str, phrase: str) -> None:
        if (
            self.settings.execution_mode != "AUTO_LIVE"
            or phrase != LIVE_PHRASE
            or not operator.strip()
            or len(operator) > 128
        ):
            raise ConfigurationError(
                "Live enable requires AUTO_LIVE, an operator and the exact real-money phrase"
            )
        findings = self.reasons(require_unlock=False)
        if findings:
            raise ExecutionDisabledError("AUTO_LIVE locked: " + "; ".join(findings))
        paper, _ = self._history()
        if paper is None:
            raise ExecutionDisabledError("AUTO_LIVE paper history remains unverified")
        proof = LiveEnable(
            account_id=self.account_id,
            paper_account_id=paper,
            operator=operator,
            config_hash=self.settings.config_hash,
            effective_hash=self.effective_hash(),
        )
        self.state.ledger.append(
            SecurityEvent, kind="LIVE_ENABLED", detail=proof.model_dump(mode="json")
        )
