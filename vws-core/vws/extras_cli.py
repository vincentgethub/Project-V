"""XK-02/05/08: explicit local exports and audited host-only playbook enable."""

from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.database import SecurityEvent
from backend.core.errors import DataIntegrityError
from backend.domain.models import Playbook
from backend.ops.anchors import controlled_path
from backend.ops.html_report import ReportSnapshot, html_report, monthly_csv
from backend.ops.journal import Journal
from backend.ops.trading_controls import ControlScope, TradingControls
from vws.security_cli import SecurityContext


def host_scope(context: SecurityContext) -> ControlScope:
    context.ledger.verify_chain()
    env = "PAPER" if context.settings.paper_trading else "LIVE"
    with Session(context.engine) as session:
        row = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "J_ACCOUNTING_VERIFIED",
                SecurityEvent.detail["cohort"].as_string() == env,
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if row is None or row.ts > context.ledger.clock.now():
            raise DataIntegrityError("XK: verified bound accounting account is UNVERIFIED")
        return ControlScope.model_validate(
            {"account_id": row.detail["account_id"], "environment": env}
        )


def latest_snapshot(context: SecurityContext) -> ReportSnapshot:
    scope = host_scope(context)
    with Session(context.engine) as session:
        row = session.scalar(
            select(SecurityEvent)
            .where(
                SecurityEvent.kind == "NIGHTLY_HTML_REPORT",
                SecurityEvent.detail["scope"]["account_id"].as_string() == scope.account_id,
                SecurityEvent.detail["scope"]["environment"].as_string() == scope.environment,
            )
            .order_by(SecurityEvent.seq.desc())
            .limit(1)
        )
        if row is None:
            raise DataIntegrityError("XK-08: no bound nightly report has been recorded")
        source = ReportSnapshot.recorded(row.detail["snapshot"])
        if (
            source.scope != scope
            or source.as_of > context.ledger.clock.now()
            or sha256(html_report(source)).hexdigest() != row.detail["sha256"]
        ):
            raise DataIntegrityError("XK-08: report identity or hash differs")
        return source


def export_journal(context: SecurityContext, project: Path) -> Path:
    journal = Journal(context.ledger, host_scope(context))
    journal.sync()
    journal.resolve()
    root = project / "data/reports"
    root.mkdir(parents=True, exist_ok=True)
    target = controlled_path(root / f"journal_{journal.scope.environment.lower()}.csv")
    target.write_bytes(journal.csv())
    return target


def export_monthly(context: SecurityContext, project: Path, month: str) -> Path:
    snapshot = latest_snapshot(context)
    payload = monthly_csv(snapshot, month)
    root = project / "data/reports"
    root.mkdir(parents=True, exist_ok=True)
    target = controlled_path(root / f"monthly_{snapshot.scope.environment.lower()}_{month}.csv")
    target.write_bytes(payload)
    return target


def enable_playbook(context: SecurityContext, name: str, operator: str) -> None:
    try:
        playbook = Playbook(name)
    except ValueError:
        raise DataIntegrityError("XK-05: choose a registered playbook name") from None
    TradingControls(context.ledger, host_scope(context)).enable_playbook(playbook, operator)
