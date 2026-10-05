"""R-04: exact Decimal money and signed-64-bit micro-unit storage."""

from decimal import Decimal, InvalidOperation, localcontext

from backend.core.errors import DataIntegrityError

MONEY_SCALE = 1_000_000
MIN_SCALED_MONEY = -(2**63)
MAX_SCALED_MONEY = 2**63 - 1
MoneyInput = Decimal | str | int
CENT = Decimal("0.01")


def validate_cent_price(value: Decimal) -> Decimal:
    """R-13/R-02: require a positive exact Decimal cent price at boundaries.

    Reject sub-cent input instead of silently rounding a proposed price. General
    account money and costs still use R-04 micro-units, independently of prices.
    """
    if not isinstance(value, Decimal):
        raise DataIntegrityError("R-13: price must be a Decimal")
    result = decimal_money(value)
    if result <= 0:
        raise DataIntegrityError("R-13: price must be positive")
    with localcontext() as context:
        context.prec = 40
        quantized = result.quantize(CENT)
    if result != quantized:
        raise DataIntegrityError("R-13: price has sub-cent precision")
    return quantized


def decimal_money(value: MoneyInput) -> Decimal:
    """R-04: accept exact values only, with finite micro-unit precision."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise DataIntegrityError("money requires Decimal, decimal text, or integer")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise DataIntegrityError("money is not valid decimal text") from exc
    if not result.is_finite():
        raise DataIntegrityError("money must be finite")
    _scaled(result)
    return result


def _scaled(value: Decimal) -> int:
    """R-04: scale exactly without ambient Decimal-context rounding."""
    if value == 0:
        return 0
    if value < Decimal("-9223372036854.775808") or value > Decimal("9223372036854.775807"):
        raise DataIntegrityError("money exceeds signed 64-bit storage")
    parts = value.as_tuple()
    trailing_zeros = 0
    for digit in reversed(parts.digits):
        if digit != 0:
            break
        trailing_zeros += 1
    if not isinstance(parts.exponent, int) or parts.exponent + trailing_zeros < -6:
        raise DataIntegrityError("money has precision below one micro-unit")
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + 10)
        scaled = value * MONEY_SCALE
        if scaled != scaled.to_integral_value():
            raise DataIntegrityError("money has precision below one micro-unit")
        if scaled < MIN_SCALED_MONEY or scaled > MAX_SCALED_MONEY:
            raise DataIntegrityError("money exceeds signed 64-bit storage")
        return int(scaled)


def money_to_scaled(value: MoneyInput) -> int:
    """R-04: convert validated money into exact integer micro-units."""
    return _scaled(decimal_money(value))


def scaled_to_money(value: int) -> Decimal:
    """R-04: recover exact money; reject coercion and integer overflow."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataIntegrityError("scaled money must be an integer")
    if value < MIN_SCALED_MONEY or value > MAX_SCALED_MONEY:
        raise DataIntegrityError("scaled money exceeds signed 64-bit storage")
    with localcontext() as context:
        context.prec = 40
        return Decimal(value) / MONEY_SCALE
