"""LJ/LP/RT: explicit masked host commands; no execution capability."""

from pathlib import Path
from uuid import UUID

from backend.core.config import YamlConfig, load_yaml_config
from backend.core.errors import DataIntegrityError
from backend.data.fee_schedule import load_fee_schedule
from backend.data.market_calendar import MarketCalendar
from backend.domain.instruments import InstrumentRegistry
from backend.execution.live_guard import LiveGuard
from backend.learning.service import LearningService
from backend.ops.macro_events import MacroCalendar
from backend.ops.trading_controls import ControlScope
from backend.realtime.models import REQUIRED, HealthStatus
from backend.realtime.policy import health_at
from backend.realtime.schedules import CONFIRM, Schedules
from backend.realtime.storage import RealtimeStore
from vws.extras_cli import host_scope
from vws.security_cli import SecurityContext


def healthy_for_live(context: SecurityContext, config: YamlConfig, account_id: str | None) -> bool:
    if account_id is None:
        return False
    calendar = MarketCalendar()
    paper = LiveGuard(
        context.settings, context.state, calendar, account_id, context.config_hash
    ).qualified_paper_account()
    if paper is None:
        return False
    current = RealtimeStore(
        context.ledger, ControlScope(account_id=account_id, environment="LIVE"), config.config_hash
    )
    rows = {row.feed: row for row in current.health()}
    if not all(
        name in rows
        and health_at(rows[name], context.ledger.clock.now(), config.rt) == HealthStatus.OK
        for name in REQUIRED
    ):
        return False
    if not set(config.watchlist).issubset(rows["assets"].symbols):
        return False
    previous = RealtimeStore(
        context.ledger, ControlScope(account_id=paper, environment="PAPER"), config.config_hash
    )
    return (
        len(previous.healthy_sessions(calendar, config.rt))
        >= context.settings.auto_live_min_rt_sessions
    )


def service(context: SecurityContext, project: Path) -> LearningService:
    config = load_yaml_config(
        project / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(project / "config").symbols,
    )
    return LearningService(
        context.ledger,
        host_scope(context),
        config,
        MarketCalendar(),
        load_fee_schedule(project / "config/fees.yaml"),
        project,
    )


def recent(context: SecurityContext, project: Path, count: int) -> str:
    return service(context, project).journal.recent(count)


def regret(context: SecurityContext, project: Path, proposal_id: str) -> str:
    try:
        identity = UUID(proposal_id)
    except ValueError:
        raise DataIntegrityError("LJ: recorded proposal UUID required") from None
    return service(context, project).regret(identity)


async def refresh_schedules(context: SecurityContext, project: Path) -> None:
    from vws.security_cli import _require_network_policy, configure_egress

    config = load_yaml_config(
        project / "config/config.yaml",
        allowed_symbols=InstrumentRegistry.from_csv(project / "config").symbols,
    )
    configure_egress(context)
    schedules = Schedules(
        context.ledger,
        MacroCalendar(project / "config/macro_events.csv"),
        project / "config/events_policy.yaml",
    )
    review = await schedules.review(_require_network_policy(context, config))
    print("Review the curated CSV against these official schedules:")
    for url, digest in review.source_sha256:
        print(url + " (SHA256 " + digest + ")")
    print("CSV SHA256: " + review.file_sha256)
    for row in schedules.macro.read():
        print(row.event + " " + row.release_at.isoformat())
    schedules.confirm(review, input("After reviewing all dates, type " + CONFIRM + ": "))
    print("Quarterly schedule confirmation recorded. The CSV was not modified.")
