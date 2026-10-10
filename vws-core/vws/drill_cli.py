"""XK-01: explicit host drill opens only a fresh scratch ledger, never owner storage."""

from datetime import datetime
from pathlib import Path

from backend.core.clock import SystemClock
from backend.core.config import Settings
from backend.core.errors import DataIntegrityError
from backend.ops.drill import TelegramDrillSender, read_proof, run_drill, seal_proof
from backend.security.secrets import SecretStore
from vws.host_config import load_host_settings


def verified_drill(
    project: Path, settings: Settings, store: SecretStore, now: datetime, days: int
) -> bool:
    path = project / "data/drills/latest.enc"
    key = store.get("VWS_BACKUP_KEY")
    if key is None or not path.is_file():
        return False
    proof = read_proof(path, key)
    return proof.recipients == settings.telegram_allowed_user_ids and proof.eligible(now, days)


async def execute(project: Path, operator: str, env_file: Path | None, store: SecretStore) -> str:
    selected = env_file if env_file is not None else project / ".env"
    settings = load_host_settings(project, selected, store)
    key = store.get("VWS_BACKUP_KEY")
    if key is None:
        raise DataIntegrityError(
            "XK-01: setup's native backup key is required to verify the drill proof"
        )
    clock = SystemClock()
    proof = await run_drill(
        clock,
        operator,
        settings.telegram_allowed_user_ids,
        TelegramDrillSender(settings),
        delivery="REAL",
    )
    root = project / "data/drills"
    if (
        root.parent.is_symlink()
        or root.parent.resolve(strict=True) != root.parent.absolute()
        or root.is_symlink()
    ):
        raise DataIntegrityError("XK-01: drill proof directory must be a direct local path")
    root.mkdir(exist_ok=True)
    digest = seal_proof(root / "latest.enc", proof, key)
    return (
        "DRILL PASS · scratch HALT, cancellation, protection, private Telegram and CLI reset verified. Proof "
        + digest[:16]
    )
