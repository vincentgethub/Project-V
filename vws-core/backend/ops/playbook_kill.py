"""XK-05's pure condition, shared now by ER-02; persistence remains Stage K.

This function never pauses or enables anything. Callers must keep paper and
live samples separate. The fixed baseline is 30 resolved trades and negative
mean R; summing exact R signs avoids rounding a small loss into zero.
"""

from decimal import Decimal, localcontext

from backend.core.config import _bounded_exact_decimal
from backend.core.errors import DataIntegrityError

MIN_TRADES = 30


def playbook_kill_condition(r_multiples: tuple[Decimal, ...]) -> bool:
    try:
        if not isinstance(r_multiples, tuple) or len(r_multiples) > 100000:
            raise ValueError("unbounded or mutable outcome sample")
        if any(not isinstance(value, Decimal) for value in r_multiples):
            raise ValueError("exact R required")
        checked = tuple(_bounded_exact_decimal(value) for value in r_multiples)
        with localcontext() as precision:
            precision.prec = 256
            return len(checked) >= MIN_TRADES and sum(checked, Decimal(0)) < 0
    except Exception:
        raise DataIntegrityError("XK-05: invalid resolved outcome sample") from None
