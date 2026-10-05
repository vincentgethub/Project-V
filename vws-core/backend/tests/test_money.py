"""R-04: storage boundaries and absence of accidental float coercion."""

from decimal import Decimal, localcontext
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.core.errors import DataIntegrityError
from backend.core.money import (
    MAX_SCALED_MONEY,
    MIN_SCALED_MONEY,
    decimal_money,
    money_to_scaled,
    scaled_to_money,
    validate_cent_price,
)


@pytest.mark.parametrize(
    "text,scaled",
    [
        ("0", 0),
        ("1.234567", 1_234_567),
        ("-1.234567", -1_234_567),
        ("1.2300000", 1_230_000),
        ("9223372036854.775807", MAX_SCALED_MONEY),
        ("-9223372036854.775808", MIN_SCALED_MONEY),
    ],
)
def test_R_04_exact_micro_unit_boundaries(text: str, scaled: int) -> None:
    assert money_to_scaled(text) == scaled
    assert scaled_to_money(scaled) == Decimal(text)


@pytest.mark.parametrize(
    "bad",
    [
        float("1.25"),
        True,
        None,
        "NaN",
        "Infinity",
        "junk",
        "0.0000001",
        "9223372036854.775808",
        "-9223372036854.775809",
        "1e999999999",
        "1e-999999999",
    ],
)
def test_R_04_bad_money_raises_typed_error(bad: Any) -> None:
    with pytest.raises(DataIntegrityError):
        decimal_money(bad)


@pytest.mark.parametrize("bad", [True, float("1"), "1", MAX_SCALED_MONEY + 1, MIN_SCALED_MONEY - 1])
def test_R_04_scaled_money_rejects_coercion_and_overflow(bad: Any) -> None:
    with pytest.raises(DataIntegrityError):
        scaled_to_money(bad)


@given(st.integers(min_value=MIN_SCALED_MONEY, max_value=MAX_SCALED_MONEY))
def test_R_04_property_signed_integer_round_trip(value: int) -> None:
    assert money_to_scaled(scaled_to_money(value)) == value


def test_R_04_conversion_is_independent_of_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 4
        assert money_to_scaled("9223372036854.775807") == MAX_SCALED_MONEY
        assert scaled_to_money(MAX_SCALED_MONEY) == Decimal("9223372036854.775807")


@pytest.mark.parametrize("value", ["1", "1.23", "1.230000", "9223372036854.77"])
def test_R_13_cent_price_is_quantized_without_changing_value(value: str) -> None:
    with localcontext() as context:
        context.prec = 4
        result = validate_cent_price(Decimal(value))
    assert result == Decimal(value)
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize("value", ["0", "-1", "0.001", "1.231", "NaN", "Infinity"])
def test_R_13_subcent_or_invalid_price_fails_closed(value: str) -> None:
    with pytest.raises(DataIntegrityError):
        validate_cent_price(Decimal(value))


@pytest.mark.parametrize("value", [1, "1.00", float("1"), True, None])
def test_R_13_price_boundary_rejects_non_decimal(value: Any) -> None:
    with pytest.raises(DataIntegrityError):
        validate_cent_price(value)
