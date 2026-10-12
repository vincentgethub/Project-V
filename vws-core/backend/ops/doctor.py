"""OPS-01: plain checklist with explicit required failures and fix hints."""

import asyncio
import shutil
import sys
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.clock import Clock, ensure_utc
from backend.core.config import MANUAL_CSV_DISABLED_MESSAGE, Settings, YamlConfig
from backend.core.database import SecurityEvent, transaction
from backend.core.errors import DataIntegrityError
from backend.core.ledger import Ledger
from backend.core.system_state import SystemStateStore
from backend.data.broker_clock import BrokerTimeVerifier
from backend.data.market_calendar import MarketCalendar
from backend.domain.models import FrozenModel
from backend.evaluation.availability import GradeStore
from backend.execution.stop_readiness import live_raise_reasons
from backend.ops.host import HostFinding
from backend.ops.read_checks import PaperAccountCheck
from backend.ops.security import SecurityOps
from backend.security.secrets import RotationService, SecretStore
from backend.telegram.security import bot_security_findings


class Check(FrozenModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_]+$")
    status: Literal["PASS", "RED", "WARN", "UNVERIFIED", "NOT_REQUIRED"]
    required: bool = Field(strict=True)
    message: str = Field(min_length=1, max_length=280)
    fix: str = Field(min_length=1, max_length=280)


class DoctorResult(FrozenModel):
    checks: tuple[Check, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_checks(self) -> "DoctorResult":
        if len({row.name for row in self.checks}) != len(self.checks):
            raise ValueError("Doctor checks must have distinct names")
        return self

    @property
    def exit_code(self) -> int:
        return int(
            any(
                row.status == "RED" or (row.required and row.status != "PASS")
                for row in self.checks
            )
        )

    @property
    def fully_green(self) -> bool:
        return all(row.status in {"PASS", "NOT_REQUIRED"} for row in self.checks)

    def lines(self) -> tuple[str, ...]:
        return tuple(f"{row.status}: {row.message} Fix: {row.fix}" for row in self.checks)


def stop_slippage_check(ledger: Ledger, settings: Settings, account_id: str | None) -> Check:
    """CM-07: read verified physical fills; no calibration or broker writes."""
    from backend.evaluation.fill_quality import monthly
    from backend.evaluation.tca_store import inventory
    from backend.ops.trading_controls import ControlScope

    values: list[Decimal] = []
    try:
        if account_id is not None:
            scope = ControlScope(
                account_id=account_id, environment="PAPER" if settings.paper_trading else "LIVE"
            )
            fills = inventory(ledger, scope)
            months = sorted(
                {
                    row.filled_at.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m")
                    for row in fills
                }
            )[-12:]
            for month in months:
                for bucket in ("HIGH", "MID", "LOW"):
                    result = monthly(scope, month, bucket, fills, Decimal(0))
                    if result.stop_p90_bps is not None:
                        values.append(result.stop_p90_bps)
        exceeded = bool(values) and max(values) > settings.stop_slippage_buffer * 10000
    except Exception:
        values, exceeded = [], False
    return Check(
        name="stop_slippage",
        status="UNVERIFIED" if not values else "WARN" if exceeded else "PASS",
        required=False,
        message="CM-07: verified stop-fill p90 exceeds the configured risk buffer."
        if exceeded
        else "CM-07: verified stop-fill p90 is within the configured risk buffer."
        if values
        else "CM-07: stop-fill arrival evidence is UNVERIFIED.",
        fix="Review the monthly fill-quality table; missing quotes are excluded and no risk setting changes automatically.",
    )


class DoctorReads(Protocol):
    async def paper_account(self, key: SecretStr, secret: SecretStr) -> PaperAccountCheck: ...
    async def account(
        self, settings: Settings, key: SecretStr, secret: SecretStr
    ) -> PaperAccountCheck: ...
    async def telegram(
        self,
        token: SecretStr,
        method: Literal["getMe", "getWebhookInfo", "getUpdates", "getChat"],
        *,
        chat_id: int | None = None,
    ) -> object: ...
    async def broker_clock(
        self, settings: Settings, key: SecretStr, secret: SecretStr
    ) -> object: ...
    async def broker_calendar(
        self, settings: Settings, key: SecretStr, secret: SecretStr, start: date, end: date
    ) -> object: ...


class Doctor:
    def __init__(
        self,
        settings: Settings,
        config: YamlConfig,
        state: SystemStateStore,
        calendar: MarketCalendar,
        clock: Clock,
        store: SecretStore,
        reads: DoctorReads,
        *,
        project: Path,
        host_findings: tuple[HostFinding, ...],
        disk_free: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
        python_version: tuple[int, int] = (sys.version_info.major, sys.version_info.minor),
    ) -> None:
        self.settings = Settings.validated_copy(settings)
        self.config = YamlConfig.model_validate(config)
        if state.clock is not clock:
            raise DataIntegrityError("Doctor must share the bound ledger clock")
        self.state, self.calendar, self.clock = state, calendar, clock
        self.store, self.reads, self.project = store, reads, project
        self.account_id: str | None = None
        self.host_findings, self.disk_free, self.python_version = (
            host_findings,
            disk_free,
            python_version,
        )

    async def run(self) -> DoctorResult:
        checks: list[Check] = []

        async def test(
            name: str,
            message: str,
            fix: str,
            action: Callable[[], Awaitable[bool]],
            *,
            required: bool = True,
        ) -> None:
            try:
                async with asyncio.timeout(60):
                    result = await action()
                status: Literal["PASS", "RED", "WARN", "UNVERIFIED", "NOT_REQUIRED"] = (
                    "PASS" if result is True else "RED" if required else "WARN"
                )
            except Exception:
                status = "RED" if required else "UNVERIFIED"
            checks.append(
                Check(
                    name=name,
                    status=status,
                    required=required,
                    message=message if status == "PASS" else message + " Unverified or failed.",
                    fix=fix,
                )
            )

        async def local_check() -> bool:
            Settings.validated_copy(self.settings)
            self.config.assert_settings_consistent(self.settings)
            return True

        async def python_check() -> bool:
            return self.python_version >= (3, 11)

        async def mode_check() -> bool:
            from backend.execution.modes import assert_auto_binding

            if self.settings.broker_state_source != "ALPACA":
                return False
            assert_auto_binding(self.settings, self.store)
            return self.settings.paper_trading or self.settings.execution_mode == "AUTO_LIVE"

        async def chain_check() -> bool:
            self.state.ledger.verify_chain()
            return True

        async def write_check() -> bool:
            with transaction(self.state.engine) as session:
                self.state.ledger._verify_in_session(session)
                self.state.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="DOCTOR_DB_PROBE",
                    telegram_user_id=None,
                    detail={},
                    ts=ensure_utc(self.clock.now()),
                )
            self.state.ledger.verify_chain()
            return True

        async def calendar_check() -> bool:
            self.calendar.is_session(
                ensure_utc(self.clock.now()).astimezone(ZoneInfo("America/New_York")).date()
            )
            return True

        async def disk_check() -> bool:
            free = self.disk_free(self.project)
            return type(free) is int and free >= 100 * 1024 * 1024

        await test(
            "python",
            "Supported Python version.",
            "Install Python 3.12 and recreate the hashed environment.",
            python_check,
        )
        await test(
            "configuration",
            "Settings and safety ceilings validated.",
            "Rerun setup; use the documented bounded values.",
            local_check,
        )
        await test(
            "mode_endpoint",
            "Execution mode, matching key pair and Alpaca endpoint agree.",
            MANUAL_CSV_DISABLED_MESSAGE + " Use only the matching keyring pair and endpoint.",
            mode_check,
        )
        await test(
            "ledger",
            "All ledger chains verified.",
            "Stop entries; follow the incident/verified-restore procedure.",
            chain_check,
        )
        await test(
            "database_writable",
            "Database accepts an immutable audit probe.",
            "Check private directory permissions, disk space and database availability.",
            write_check,
        )
        await test(
            "calendar",
            "XNYS calendar covers today.",
            "Update the pinned calendar range without guessing holidays or closes.",
            calendar_check,
        )
        await test(
            "disk_space",
            "At least 100 MiB of disk space is available.",
            "Free space on the project/data volume before startup.",
            disk_check,
        )

        try:
            prefix = "ALPACA_PAPER" if self.settings.paper_trading else "ALPACA_LIVE"
            key = self.store.get(prefix + "_KEY_ID")
            secret = self.store.get(prefix + "_SECRET")
        except Exception:
            key = secret = None

        async def account_check() -> bool:
            if key is None or secret is None:
                return False
            account = PaperAccountCheck.model_validate(
                await self.reads.paper_account(key, secret)
                if self.settings.paper_trading
                else await self.reads.account(self.settings, key, secret)
            )
            self.account_id = str(account.account_id)
            if account.status.value != "ACTIVE" or any(
                (account.account_blocked, account.trading_blocked, account.trade_suspended_by_user)
            ):
                return False
            rotation = RotationService(self.store, self.clock, self.state.ledger, {})
            ops = SecurityOps(
                self.state.ledger,
                self.state,
                self.clock,
                notify=lambda text: self.state.notifier.notify("URGENT", text),
            )
            changed = False
            for name, value in (
                (prefix + "_KEY_ID", key),
                (prefix + "_SECRET", secret),
                (
                    ("PAPER" if self.settings.paper_trading else "LIVE") + "_ACCOUNT_ID",
                    SecretStr(str(account.account_id)),
                ),
            ):
                changed = ops.observe_identity(name, rotation.fingerprint(name, value)) or changed
            return not changed

        async def time_check() -> bool:
            if key is None or secret is None:
                return False

            async def clock_read() -> object:
                return await self.reads.broker_clock(self.settings, key, secret)

            async def calendar_read(start: date, end: date) -> object:
                return await self.reads.broker_calendar(self.settings, key, secret, start, end)

            await BrokerTimeVerifier(
                self.settings, self.calendar, self.clock, self.state, clock_read, calendar_read
            ).verify()
            return True

        await test(
            "paper_account" if self.settings.paper_trading else "live_account",
            "Read-only account for the selected cohort is active and unrestricted.",
            "Rerun setup --section alpaca with the matching paper pair; resolve broker restrictions.",
            account_check,
        )
        await test(
            "clock_skew",
            "Broker clock and calendar agree within the skew ceiling.",
            "Synchronize the host clock; retry the read-only doctor check.",
            time_check,
        )

        async def telegram_check() -> bool:
            token = self.store.get("TELEGRAM_BOT_TOKEN")
            callback = self.store.get("TELEGRAM_CALLBACK_SECRET")
            chat_id = self.settings.telegram_chat_id
            if (
                token is None
                or callback is None
                or len(callback.get_secret_value().encode("utf-8")) < 32
                or chat_id is None
                or chat_id not in self.settings.telegram_allowed_user_ids
            ):
                return False
            me = await self.reads.telegram(token, "getMe")
            webhook = await self.reads.telegram(token, "getWebhookInfo")
            chat = await self.reads.telegram(token, "getChat", chat_id=chat_id)
            if isinstance(me, dict) and isinstance(webhook, dict):
                findings = bot_security_findings(
                    me, webhook, mode=self.settings.execution_mode, ledger=self.state.ledger
                )
                for finding in findings:
                    if finding.startswith("URGENT"):
                        self.state.notifier.notify("URGENT", finding)
            return (
                isinstance(me, dict)
                and me.get("is_bot") is True
                and me.get("can_join_groups") is False
                and me.get("can_read_all_group_messages") is False
                and isinstance(webhook, dict)
                and webhook.get("url") == ""
                and isinstance(chat, dict)
                and type(chat.get("id")) is int
                and chat.get("id") == chat_id
                and chat.get("type") == "private"
            )

        async def sec_check() -> bool:
            return self.settings.sec_user_agent is not None

        async def llm_check() -> bool:
            self.settings.assert_llm_call_budget_ready()
            return True

        await test(
            "telegram_private",
            "Bot identity, empty webhook and allowlisted private chat verified.",
            "Rerun setup --section telegram; disable group joining and enable BotFather privacy.",
            telegram_check,
        )
        if self.config.fundamentals.enabled:
            await test(
                "sec_identification",
                "SEC filing name and contact email are configured.",
                "Enter SEC_USER_AGENT name and email inside setup; filings stay unavailable until then.",
                sec_check,
            )
        else:
            checks.append(
                Check(
                    name="sec_identification",
                    status="UNVERIFIED",
                    required=False,
                    message="SEC access is unverified; fundamentals are disabled.",
                    fix="Enter the filing contact in setup before enabling fundamentals.",
                )
            )
        if self.settings.llm_enabled:
            await test(
                "llm_configuration",
                "Enabled public-summary configuration is complete.",
                "Configure the provider, keyring credential, exact rates and bounded budget.",
                llm_check,
            )
        else:
            checks.append(
                Check(
                    name="llm_configuration",
                    status="NOT_REQUIRED",
                    required=False,
                    message="AI summaries are off.",
                    fix="Keep off, or explicitly configure the documented provider and rates.",
                )
            )
        try:
            working = GradeStore(self.state.ledger, self.settings, self.config).exit_working()
        except Exception:
            working = False
        checks.append(
            Check(
                name="exit_validation",
                status="PASS" if working else "UNVERIFIED",
                required=self.settings.execution_mode != "MANUAL",
                message=f"EX-06: {self.config.exits.variant} exit validation "
                + (
                    "is WORKING."
                    if working
                    else "is UNVERIFIED; new tickets and auto entries are refused."
                ),
                fix="Register EXITS and run its fixed walk-forward validation; review the OOS grade before changing a setting.",
            )
        )
        if "EARNINGS_GAP" in self.config.enabled_playbooks:
            try:
                earnings_working = GradeStore(
                    self.state.ledger, self.settings, self.config
                ).earnings_working()
            except Exception:
                earnings_working = False
            manual = self.settings.execution_mode == "MANUAL"
            checks.append(
                Check(
                    name="earnings_gap",
                    status="WARN" if manual else "PASS" if earnings_working else "UNVERIFIED",
                    required=not manual,
                    message="EG-01: optional earnings-gap enabled; MANUAL evidence needs review."
                    if manual
                    else "EG-01: earnings-gap alone has registered WORKING OOS validation."
                    if earnings_working
                    else "EG-01: earnings-gap OOS grade is UNVERIFIED; AUTO entries refused.",
                    fix="Freeze submissions and ALL tapes, register PLAYBOOK and validate the earnings-gap-only variant.",
                )
            )
        if self.config.rs.use_breadth and len(self.config.watchlist) < 50:
            checks.append(
                Check(
                    name="breadth",
                    status="WARN",
                    required=False,
                    message="RS-04: breadth is noisy below 50 watchlist symbols.",
                    fix="Review the small-sample warning; breadth never relaxes a CRO rule.",
                )
            )
        if (
            self.settings.execution_mode == "AUTO_LIVE"
            and self.config.exits.variant == "SPLIT_1R_TRAIL"
        ):
            findings = live_raise_reasons(self.state.ledger, self.config)
            checks.append(
                Check(
                    name="live_stop_raises",
                    status="RED" if findings else "PASS",
                    required=True,
                    message=(
                        "; ".join(findings)
                        if findings
                        else "EX-06: paper raises and pinned OCO/OTO cancellation evidence verified."
                    )[:280],
                    fix="Complete at least 30 failure-free AUTO_PAPER raises with windows at most 30 seconds and the explicit paper integration test.",
                )
            )
        checks.append(stop_slippage_check(self.state.ledger, self.settings, self.account_id))
        # H stores the owner key only in setup. Stage W owns actual daily feed
        # health and policy. Presence alone cannot certify a healthy feed.
        checks.append(
            Check(
                name="fred",
                status="UNVERIFIED",
                required=False,
                message="FRED feed health is unverified; realtime policy is not built yet.",
                fix="Enter the FRED key only in setup; Stage W verifies required feed health.",
            )
        )
        for finding in self.host_findings:
            checks.append(
                Check(
                    name="host_" + finding.name,
                    status="UNVERIFIED" if finding.status == "UNKNOWN" else finding.status,
                    required=False,
                    message=finding.reason,
                    fix=finding.fix,
                )
            )
        try:
            self.state.ledger.verify_chain()
            with Session(self.state.engine) as session:
                last_audit = session.scalar(
                    select(SecurityEvent)
                    .where(SecurityEvent.kind.in_(("PIP_AUDIT_PASSED", "PIP_AUDIT_FAILED")))
                    .order_by(SecurityEvent.seq.desc())
                    .limit(1)
                )
            recent = last_audit is not None and timedelta(0) <= ensure_utc(
                self.clock.now()
            ) - ensure_utc(last_audit.ts) <= timedelta(days=7)
            from backend.ops.dependency_audit import lock_hashes

            recent = bool(
                recent
                and last_audit is not None
                and last_audit.detail.get("lock_hashes") == lock_hashes(self.project)
            )
        except Exception:
            last_audit, recent = None, False
        checks.append(
            Check(
                name="last_dependency_audit",
                status="UNVERIFIED"
                if last_audit is None
                else "PASS"
                if last_audit.kind == "PIP_AUDIT_PASSED" and recent
                else "WARN",
                required=False,
                message="No recorded host dependency audit."
                if last_audit is None
                else "Latest recorded host dependency audit: "
                + (
                    "passed (within seven days)."
                    if last_audit.kind == "PIP_AUDIT_PASSED" and recent
                    else "failed or stale; rerun it."
                ),
                fix="Run python -m vws ops audit-dependencies --operator NAME on this host.",
            )
        )
        return DoctorResult(checks=tuple(checks))
