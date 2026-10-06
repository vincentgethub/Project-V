"""Amendment 01 section 4.3: shared deterministic completed-session AVWAP anchor."""

from decimal import Decimal, localcontext
from enum import StrEnum

from backend.agents.indicators import _bars
from backend.core.errors import DataIntegrityError
from backend.data.data_layer import Bar


class AnchorKind(StrEnum):
    LOWEST_LOW = "LOWEST_LOW"
    GAP = "GAP"


def select_anchor(bars: tuple[Bar, ...]) -> tuple[int, AnchorKind]:
    """Lowest low of the last60; a newer >=4% gap with RVOL>=2 supersedes it.

    Equal lows choose the most recent session. Integer cross multiplication
    compares RVOL without rounding or recomputing the memo's indicator series.
    Every inspected observation was supplied by the completed-bar boundary.
    """
    checked = _bars(bars)
    if len(checked) < 60:
        raise DataIntegrityError("GD-03: AVWAP anchor needs 60 completed sessions")
    first = len(checked) - 60
    low = min(range(first, len(checked)), key=lambda i: (checked[i].low, -i))
    with localcontext() as context:
        context.prec = 80
        for index in range(len(checked) - 1, max(low, 19), -1):
            prior_volume = sum(bar.volume for bar in checked[index - 20 : index])
            if (
                prior_volume > 0
                and checked[index].volume * 20 >= 2 * prior_volume
                and abs(checked[index].open / checked[index - 1].close - 1) >= Decimal("0.04")
            ):
                return index, AnchorKind.GAP
    return low, AnchorKind.LOWEST_LOW
