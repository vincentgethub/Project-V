"""CM-04: explicit file adapter; cost functions themselves are pure."""

from pathlib import Path

from backend.core.config import load_exact_yaml
from backend.core.errors import ConfigurationError
from backend.evaluation.costs import FeeSchedule


def load_fee_schedule(path: Path) -> FeeSchedule:
    try:
        return FeeSchedule.model_validate(load_exact_yaml(path))
    except Exception:
        raise ConfigurationError("CM-04: dated fee schedule could not be validated") from None
