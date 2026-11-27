"""Binance's numbers become exact Decimals, or are refused."""

from decimal import Decimal

import pytest

from exchange.numbers import positive_decimal, read_json, to_decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0", "0"), ("59896.01000000", "59896.01000000"), ("0.00001000", "0.00001000")],
)
def test_plain_numbers_keep_every_digit(text: str, expected: str) -> None:
    number = to_decimal(text)
    assert isinstance(number, Decimal) and str(number) == expected


@pytest.mark.parametrize(
    "value",
    [
        "-5",
        "+5",
        "1E+3",
        "1e999999",
        "NaN",
        "Infinity",
        " 1 ",
        "1_000",
        "1.",
        ".5",
        "",
        1.5,
        1,
        None,
        True,
        ["1"],
    ],
)
def test_anything_else_is_refused(value: object) -> None:
    with pytest.raises(ValueError):
        to_decimal(value)


def test_a_price_must_be_above_zero() -> None:
    assert positive_decimal("0.01") == Decimal("0.01")
    for value in ("0", "0.00000000"):
        with pytest.raises(ValueError):
            positive_decimal(value)


def test_json_numbers_with_a_point_never_become_floats() -> None:
    parsed = read_json('{"price": 0.1, "count": 3, "text": "0.2"}')
    assert parsed == {"price": Decimal("0.1"), "count": 3, "text": "0.2"}
    assert type(parsed["price"]) is Decimal
