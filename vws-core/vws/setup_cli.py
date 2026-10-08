"""WZ-01: setup composition, with no owner database opened during prompts."""

from pathlib import Path

from backend.core.clock import SystemClock
from backend.core.database import SecurityEvent, create_database, create_schema, transaction
from backend.core.errors import ConfigurationError
from backend.core.ledger import Ledger
from backend.net.egress import EgressPolicy, build_allowlist
from backend.ops.doctor import DoctorResult
from backend.ops.read_checks import ReadChecksClient
from backend.security.secrets import KeyringSecretStore
from vws import security_cli
from vws.setup import Section, SetupResult, SetupWizard, TerminalPrompts


async def execute(section: Section | None, env_file: Path | None = None) -> SetupResult:
    project = security_cli.PROJECT
    selected = project / ".env"
    if env_file is not None and env_file.absolute() != selected.absolute():
        raise ConfigurationError("Setup edits only this project's .env; use its explicit path")
    store, clock = KeyringSecretStore(), SystemClock()
    bootstrap = create_database("sqlite:///:memory:")
    create_schema(bootstrap)
    policy = EgressPolicy(build_allowlist(mode="MANUAL"), Ledger(bootstrap, clock))
    reads = ReadChecksClient(policy, clock)

    def record(names: tuple[str, ...], fingerprints: dict[str, str]) -> None:
        # This is reached only after final confirmation and reversible writes.
        # Initial SQLite storage requires its private parent before connecting.
        data = project / "data"
        if data.is_symlink():
            raise ConfigurationError("The setup data directory must not be a link")
        data.mkdir(mode=0o700, exist_ok=True)
        context = security_cli.open_context(selected, store=store)
        try:
            with transaction(context.engine) as session:
                context.ledger._verify_in_session(session)
                for name, fingerprint in fingerprints.items():
                    context.ledger.append_in_session(
                        session,
                        SecurityEvent,
                        kind="SECRET_ROTATED",
                        detail={"name": name, "fingerprint": fingerprint},
                        telegram_user_id=None,
                        ts=context.ledger.clock.now(),
                    )
                context.ledger.append_in_session(
                    session,
                    SecurityEvent,
                    kind="CONFIG_APPLIED",
                    detail={"changed_keys": list(names), "config_hash": context.config_hash()},
                    telegram_user_id=None,
                    ts=context.ledger.clock.now(),
                )
        finally:
            context.engine.dispose()

    def rolled_back(names: tuple[str, ...]) -> None:
        # Cancellation restores settings/entries, but never erases immutable
        # doctor or audit rows. Future startup detects any unacknowledged drift.
        from backend.core.notifier import ConsoleNotifier
        from backend.core.system_state import SystemStateStore
        from vws.host_config import load_host_settings

        restored_env = selected if selected.exists() else None
        settings = (
            load_host_settings(project, restored_env, store) if restored_env is not None else None
        )
        database = (
            settings.db_url.get_secret_value()
            if settings is not None
            else "sqlite:///" + str(project / "data/vws-core.sqlite3")
        )
        engine = create_database(database)
        try:
            state = SystemStateStore(engine, clock, ConsoleNotifier())
            state.ledger.append(
                SecurityEvent, kind="CONFIG_APPLY_ROLLED_BACK", detail={"changed_keys": list(names)}
            )
        finally:
            engine.dispose()

    async def doctor() -> DoctorResult:
        context = security_cli.open_context(selected, store=store)
        try:
            return await security_cli.doctor_result(context, store)
        finally:
            context.engine.dispose()

    try:
        wizard = SetupWizard(
            project,
            store,
            reads,
            TerminalPrompts(),
            clock,
            record=record,
            doctor=doctor,
            rolled_back=rolled_back,
            section=section,
        )
        return await wizard.run()
    finally:
        bootstrap.dispose()
