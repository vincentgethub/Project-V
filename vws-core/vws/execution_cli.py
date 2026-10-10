"""AX-02/41: explicit host mode commands through pure policy, never the SDK executor."""

import getpass
from contextlib import AsyncExitStack
from dataclasses import replace
from typing import Literal

from backend.core.database import SecurityEvent
from backend.core.errors import ConfigurationError
from backend.data.market_calendar import MarketCalendar
from backend.execution.live_guard import LIVE_PHRASE, LIVE_WARNING, LiveGuard
from backend.execution.modes import ModeStore, assert_auto_binding
from backend.ops.doctor import DoctorResult
from backend.ops.read_checks import ReadChecksClient
from backend.security.secrets import SecretStore
from vws import security_cli
from vws.drill_cli import verified_drill


async def panic_cancel(context: security_cli.SecurityContext, store: SecretStore) -> None:
    """SEC-73: bounded best effort only after the local HALT is committed."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.core.config import load_yaml_config
    from backend.core.database import ExecutionOrderRecord
    from backend.core.system_state import SystemState
    from backend.data.async_reader import AsyncTokenBucket
    from backend.domain.instruments import InstrumentRegistry
    from backend.execution.models import AutoPrerequisites
    from backend.execution.worker import SingleAttemptWorker
    from backend.notifications.callbacks import FreshInputs
    from backend.risk.boundary import RiskBoundary
    from backend.risk.compliance import ComplianceEngine
    from backend.risk.compliance_boundary import ComplianceBoundary
    from backend.risk.risk_cro import ChiefRiskOfficer
    from vws.host_config import load_host_settings

    if context.state.current() != SystemState.HALTED:
        raise ConfigurationError("Panic broker access requires local HALT first")
    context.ledger.verify_chain()
    settings = load_host_settings(security_cli.PROJECT, context.env_file, store)
    if settings.execution_mode == "MANUAL":
        return
    with Session(context.engine) as session:
        accounts = set(
            session.scalars(
                select(ExecutionOrderRecord.account_id).where(
                    ExecutionOrderRecord.environment
                    == ("PAPER" if settings.paper_trading else "LIVE")
                )
            )
        )
    if not accounts:
        return
    if len(accounts) != 1:
        raise ConfigurationError("Panic cannot prove a single managed broker account")
    bound = replace(context, settings=settings, settings_source=None)
    registry = InstrumentRegistry.from_csv(security_cli.PROJECT / "config")
    config = load_yaml_config(
        security_cli.PROJECT / "config/config.yaml",
        allowed_symbols=registry.symbols,
        settings=settings,
    )
    calendar = MarketCalendar()
    security_cli.configure_egress(bound)
    worker = SingleAttemptWorker(
        AsyncTokenBucket(context.ledger.clock, plan=settings.alpaca_data_plan)
    )

    class NoEntryOrExitAnalysis:
        async def refresh(self, symbol: str) -> FreshInputs:
            raise ConfigurationError("Panic cannot admit entries or discretionary exits")

    async def notice(text: str, urgent: bool) -> None:
        print(text)

    recovery = None
    try:
        # AX-11: MANUAL returns above, before the concrete module is imported.
        from backend.execution.alpaca_executor import ProtectionRecovery

        modes = ModeStore(settings, context.state, next(iter(accounts)))
        now = context.ledger.clock.now()
        recovery = ProtectionRecovery(
            settings,
            config,
            context.state,
            modes,
            NoEntryOrExitAnalysis(),
            RiskBoundary(
                ChiefRiskOfficer(settings, registry, calendar), context.state, context.ledger.clock
            ),
            ComplianceBoundary(
                ComplianceEngine(settings, registry, calendar), context.state, context.ledger.clock
            ),
            calendar,
            worker,
            store,
            AutoPrerequisites(
                account_id=modes.account_id,
                environment=modes.environment,
                config_hash=settings.config_hash,
                doctor_fully_green=False,
                watchdog_enabled=False,
                backup_chain_verified=False,
                backup_verified_at=now,
                telegram_verified_at=now,
                clock_verified_at=now,
            ),
            policy=security_cli._require_network_policy(bound, config),
            notify=notice,
        )
        await recovery.cancel_unfilled_entries()
    finally:
        if recovery is not None:
            await recovery.close()
        else:
            await worker.aclose()


async def execute(
    context: security_cli.SecurityContext,
    store: SecretStore,
    action: Literal["resume-auto", "enable-live", "disable-live"],
    operator: str,
) -> None:
    settings = context.settings
    if not operator.strip() or len(operator) > 128 or not operator.isprintable():
        raise ConfigurationError("Host mode action requires a bounded operator name")
    if action == "disable-live":
        context.ledger.append(SecurityEvent, kind="LIVE_DISABLED", detail={"operator": operator})
        print("Automatic live entries disabled locally. Held exits and broker stops continue.")
        return
    assert_auto_binding(settings, store)
    if settings.execution_mode == "MANUAL":
        raise ConfigurationError("Configured MANUAL cannot be upgraded by an ops command")
    security_cli.configure_egress(context)
    from backend.core.config import load_yaml_config
    from backend.domain.instruments import InstrumentRegistry

    config = load_yaml_config(
        security_cli.PROJECT / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(security_cli.PROJECT / "config").symbols,
        settings=settings,
    )
    reads = ReadChecksClient(
        security_cli._require_network_policy(context, config), context.ledger.clock
    )
    account = await reads.account(settings, settings.broker_api_key, settings.broker_secret_key)
    modes = ModeStore(settings, context.state, str(account.account_id))
    result = await security_cli.doctor_result(context, store)
    if action == "resume-auto":
        if not result.fully_green:
            raise ConfigurationError("Host resume requires fully green doctor checks")
        modes.resume(operator=operator, phrase=input("Type RESUME: "))
        print(
            "Host resume recorded. Restart the host to replace any protection-only recovery service."
        )
        return
    print(LIVE_WARNING)
    for name in (
        "live_max_order_notional",
        "live_max_daily_orders",
        "live_max_open_positions",
        "live_max_gross_exposure_pct",
        "live_max_risk_per_trade",
        "live_daily_loss_limit",
    ):
        print(f"{name.upper()}: {settings.model_dump()[name]}")
    readiness = DoctorResult(
        checks=tuple(
            row for row in result.checks if row.name not in {"live_unlock", "auto_fully_green"}
        )
    )
    if not readiness.fully_green:
        raise ConfigurationError("Live enable requires every other doctor observation fully green")
    from vws.runtime_cli import compose

    async with AsyncExitStack() as resources:
        await compose(context, store, readiness, resources=resources, accounting_only=True)
    guard = LiveGuard(
        settings,
        context.state,
        MarketCalendar(),
        modes.account_id,
        context.config_hash,
        security_reasons=security_cli.live_security_guard(context, store),
        drill_ready=lambda: verified_drill(
            security_cli.PROJECT, settings, store, context.ledger.clock.now(), 45
        ),
    )
    guard.enable(operator=operator, phrase=getpass.getpass(f"Type {LIVE_PHRASE}: "))
    print("Config-bound live approval recorded. Re-run doctor before an explicit host restart.")
