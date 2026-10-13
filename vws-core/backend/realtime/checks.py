"""AC-04: explicit read-only doctor probes and durable learning write proof."""

from datetime import date
from pathlib import Path

from backend.core.config import Settings, YamlConfig
from backend.core.system_state import SystemStateStore
from backend.data.broker_clock import BrokerTimeVerifier
from backend.data.market_calendar import MarketCalendar
from backend.learning.proposals import ProposalStore
from backend.ops.doctor import Check
from backend.ops.macro_events import MacroCalendar
from backend.ops.read_checks import ReadChecksClient
from backend.ops.trading_controls import ControlScope
from backend.realtime.desk import RealtimeDesk
from backend.realtime.models import REQUIRED, HealthStatus
from backend.realtime.policy import health_at
from backend.realtime.reader import RealtimeReader
from backend.realtime.schedules import Schedules
from backend.realtime.storage import RealtimeStore
from backend.realtime.supervisor import Supervisor
from backend.security.secrets import SecretStore


async def checklist(
    settings: Settings,
    config: YamlConfig,
    state: SystemStateStore,
    calendar: MarketCalendar,
    secrets: SecretStore,
    reads: ReadChecksClient,
    project: Path,
    account_id: str,
) -> tuple[Check, ...]:
    scope = ControlScope(
        account_id=account_id, environment="PAPER" if settings.paper_trading else "LIVE"
    )
    store = RealtimeStore(state.ledger, scope, config.config_hash)
    macro = MacroCalendar(project / "config/macro_events.csv")
    schedules = Schedules(state.ledger, macro, project / "config/events_policy.yaml")
    desk = RealtimeDesk(
        store, config, calendar, schedules, lambda: settings.execution_mode != "MANUAL"
    )

    async def clock_read() -> object:
        return await reads.broker_clock(
            settings, settings.broker_api_key, settings.broker_secret_key
        )

    async def calendar_read(start: date, end: date) -> object:
        return await reads.broker_calendar(
            settings, settings.broker_api_key, settings.broker_secret_key, start, end
        )

    async def symbols() -> tuple[str, ...]:
        return tuple(sorted(config.watchlist))

    async def no_dispatch(event: object) -> None:
        return None  # Doctor has no order or event-action capability.

    key = secrets.get("FRED_API_KEY")
    reader = RealtimeReader(
        settings,
        config.rt,
        reads,
        store,
        BrokerTimeVerifier(settings, calendar, state.clock, state, clock_read, calendar_read),
        calendar,
        symbols,
        symbols,
        macro,
        schedules.confirmed,
        fred_key=key,
    )
    supervisor = Supervisor(store, config.rt, reader, no_dispatch, symbols, state)
    try:
        for feed in (*REQUIRED, "fred", "macro"):
            await supervisor.once(feed)
    finally:
        await reader.aclose()
    health = {row.feed: row for row in store.health()}
    automatic = settings.execution_mode != "MANUAL"
    rows = []
    for name in (*REQUIRED, "ca", "edgar", "fred", "macro"):
        value = health.get(name)
        status = (
            HealthStatus.UNAVAILABLE
            if value is None
            else health_at(value, state.clock.now(), config.rt)
        )
        age = (
            "no heartbeat"
            if value is None
            else f"heartbeat age {int((state.clock.now() - value.observed_at).total_seconds())}s"
        )
        required = automatic and (
            name in REQUIRED
            or name == "macro"
            or name == "fred"
            and config.events_policy.vix_stress != "annotate"
        )
        rows.append(
            Check(
                name="fred" if name == "fred" else "rt_" + name,
                status="PASS"
                if status == HealthStatus.OK
                else "WARN"
                if status == HealthStatus.DEGRADED
                else "UNVERIFIED",
                required=required,
                message=f"Realtime + learning: {name} {status.value}; {age}.",
                fix="Use setup for credentials; verify feed entitlement, host clock and HTTPS access. Confirm quarterly schedules on the host.",
            )
        )
    desk.journal_write_probe()
    rows.append(
        Check(
            name="learning_journal",
            status="PASS",
            required=automatic,
            message=f"Realtime + learning: append-only journal write OK; {len(ProposalStore(state.ledger, scope).open())} open proposals.",
            fix="Inspect ledger integrity and writable data storage; proposals never apply themselves.",
        )
    )
    rows.append(
        Check(
            name="rt_identification",
            status="PASS"
            if settings.sec_user_agent is not None and key is not None
            else "UNVERIFIED",
            required=automatic,
            message=f"Realtime + learning: SEC_USER_AGENT {'set' if settings.sec_user_agent is not None else 'unset'}; FRED key {'present' if key is not None else 'absent'}.",
            fix="Enter SEC name/contact and FRED key through vws setup only. Presence does not certify feed health.",
        )
    )
    return tuple(rows)
