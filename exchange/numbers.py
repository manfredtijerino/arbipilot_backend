"""Reading the numbers Binance sends.

Binance sends prices and quantities as text. They become `Decimal` here and
never pass through a float, which would round them.
"""

import json
import re
from decimal import Decimal
from typing import Any

# Digits, perhaps a point and more digits. No sign, no exponent, no spaces.
_PLAIN_NUMBER = re.compile(r"[0-9]{1,20}(\.[0-9]{1,20})?")


def to_decimal(value: Any) -> Decimal:
    """A plain number sent as text, as a Decimal. Raises ValueError otherwise."""
    if not isinstance(value, str) or not _PLAIN_NUMBER.fullmatch(value):
        raise ValueError("not a plain number sent as text")
    return Decimal(value)


def positive_decimal(value: Any) -> Decimal:
    number = to_decimal(value)
    if number <= 0:
        raise ValueError("must be above zero")
    return number


def read_json(text: str | bytes) -> Any:
    """Parse JSON so that any number with a point becomes a Decimal, not a float."""
    return json.loads(text, parse_float=Decimal)
