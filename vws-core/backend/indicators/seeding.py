"""PF-01: one SMA seed for EMA and Wilder averages in both implementations."""

import numpy as np
from numpy.typing import NDArray


def sma_seed(values: NDArray[np.float64], period: int) -> np.float64:
    """Callers validate finite inputs and require at least period observations."""
    return np.mean(values[:period], dtype=np.float64)
