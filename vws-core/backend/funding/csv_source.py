"""FN-02: manual funding deferred by owner, October 8 2026; no file reads."""

from datetime import datetime
from pathlib import Path

from backend.core.config import MANUAL_CSV_DISABLED_MESSAGE
from backend.core.errors import ConfigurationError
from backend.core.system_state import SystemStateStore
from backend.evaluation.costs import FeeSchedule
from backend.funding.activities import ActivityBatch
from backend.tax.models import Environment


class ManualActivitiesSource:
    """Disabled compatibility boundary; no CSV parsing or filesystem access."""

    def __init__(
        self, state: SystemStateStore, path: Path, account_id: str, env: Environment
    ) -> None:
        raise ConfigurationError(MANUAL_CSV_DISABLED_MESSAGE)

    async def read_activities(
        self, after: datetime | None, until: datetime, schedule: FeeSchedule
    ) -> ActivityBatch:
        """Refuse even a caller that bypassed the constructor."""
        raise ConfigurationError(MANUAL_CSV_DISABLED_MESSAGE)
