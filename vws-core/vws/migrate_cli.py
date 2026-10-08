"""OPS-05: explicit host migration, without ordinary current-schema startup."""

from pathlib import Path

from backend.core.clock import SystemClock
from backend.core.database import create_database
from backend.core.errors import ConfigurationError
from backend.ops.migrations import MigrationResult, MigrationRunner
from backend.security.permissions import check_permissions
from backend.security.secrets import SecretStore
from vws import security_cli
from vws.host_config import load_host_settings


def execute(operator: str, env_file: Path | None, store: SecretStore) -> MigrationResult:
    project = security_cli.PROJECT
    selected = project / ".env" if env_file is None else env_file
    settings = load_host_settings(project, selected, store)
    path = security_cli.local_database_path(settings)
    if path is None or not path.is_file():
        raise ConfigurationError(
            "Migration requires an existing local SQLite ledger; PostgreSQL needs its documented backup procedure"
        )
    directory = security_cli.backup_directory(settings)
    check_permissions(
        env_file=selected,
        data_dir=project / "data",
        logs_dir=project / "logs",
        backups_dir=directory,
        db_path=path,
        mode=settings.execution_mode,
    )
    engine = create_database(settings.db_url.get_secret_value())
    try:
        return MigrationRunner(engine, SystemClock(), store, directory).run(operator)
    finally:
        engine.dispose()
