"""Loads and checks `decisions.yaml`: the owner's risk limits.

The limits live in one readable file and nowhere else. This module reads the
file once, refuses anything missing, misspelt or absurd, and hands out an
object that cannot be changed while the app runs.

A value that fails a check stops the app from starting: trading with a
guessed or half-read limit is worse than not trading.
"""

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from exchange.numbers import to_decimal

DECISIONS_FILE = Path(__file__).resolve().parent.parent / "decisions.yaml"

# Typing-mistake guards, not limits: "0.8" instead of "0.08" must never load.
# The owner's real limits are the values in the file, far below these.
HIGHEST_POSITION_PCT = Decimal("0.25")
HIGHEST_DAILY_LOSS_PCT = Decimal("0.10")
HIGHEST_OPEN_POSITIONS = 10
HIGHEST_ORDERS_PER_MINUTE = 60
HIGHEST_STARTING_EQUITY = Decimal("100000")


class DecisionsError(Exception):
    """`decisions.yaml` is missing or invalid. The message says what to fix."""


class _Strict(BaseModel):
    # Unknown keys are refused (a misspelt limit must not be silently ignored),
    # nothing is converted behind our back, and nothing can be changed later.
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _exact(value: Any) -> Decimal:
    """Text such as "0.08" as an exact Decimal. A bare 0.08 is refused."""
    if not isinstance(value, str):
        raise ValueError('write the number in quotes, like "0.08"')
    return to_decimal(value)


def _share(value: Decimal, highest: Decimal) -> Decimal:
    if not Decimal(0) < value <= highest:
        raise ValueError(f"must be above 0 and at most {highest}")
    return value


def _count(value: int, highest: int) -> int:
    if type(value) is not int or not 1 <= value <= highest:
        raise ValueError(f"must be a whole number from 1 to {highest}")
    return value


class RiskLimits(_Strict):
    max_position_pct_equity: Decimal
    daily_loss_pause_pct: Decimal
    max_open_positions: int
    max_positions_per_symbol: int
    max_orders_per_minute: int

    @field_validator("max_position_pct_equity", "daily_loss_pause_pct", mode="before")
    @classmethod
    def _text_to_decimal(cls, value: Any) -> Decimal:
        return _exact(value)

    @field_validator("max_position_pct_equity")
    @classmethod
    def _position_share(cls, value: Decimal) -> Decimal:
        return _share(value, HIGHEST_POSITION_PCT)

    @field_validator("daily_loss_pause_pct")
    @classmethod
    def _loss_share(cls, value: Decimal) -> Decimal:
        return _share(value, HIGHEST_DAILY_LOSS_PCT)

    @field_validator("max_open_positions")
    @classmethod
    def _open_positions(cls, value: int) -> int:
        return _count(value, HIGHEST_OPEN_POSITIONS)

    @field_validator("max_positions_per_symbol")
    @classmethod
    def _per_symbol(cls, value: int) -> int:
        # The engine keeps one position per pair; more would need new code.
        return _count(value, 1)

    @field_validator("max_orders_per_minute")
    @classmethod
    def _orders_per_minute(cls, value: int) -> int:
        return _count(value, HIGHEST_ORDERS_PER_MINUTE)

    @model_validator(mode="after")
    def _never_more_than_the_account(self) -> "RiskLimits":
        if self.max_position_pct_equity * self.max_open_positions > 1:
            raise ValueError(
                "max_position_pct_equity times max_open_positions is more than "
                "the whole account"
            )
        return self


class ShadowAccount(_Strict):
    starting_equity_usdt: Decimal

    @field_validator("starting_equity_usdt", mode="before")
    @classmethod
    def _text_to_decimal(cls, value: Any) -> Decimal:
        return _exact(value)

    @field_validator("starting_equity_usdt")
    @classmethod
    def _sensible(cls, value: Decimal) -> Decimal:
        if not Decimal(0) < value <= HIGHEST_STARTING_EQUITY:
            raise ValueError(f"must be above 0 and at most {HIGHEST_STARTING_EQUITY}")
        return value


class Decisions(_Strict):
    risk: RiskLimits
    shadow: ShadowAccount


def _explain(error: ValidationError) -> str:
    """Which keys are wrong and why. Key names and our words only."""
    lines = []
    for problem in error.errors():
        key = ".".join(str(part) for part in problem["loc"]) or "the file"
        kind = problem["type"]
        if kind == "missing":
            reason = "is missing"
        elif kind == "extra_forbidden":
            reason = "is not a known key (check the spelling)"
        elif kind == "value_error":
            reason = str(problem["ctx"]["error"])
        else:
            reason = "has the wrong kind of value"
        lines.append(f"{key}: {reason}")
    return "; ".join(lines)


def parse_decisions(data: Any) -> Decisions:
    if not isinstance(data, dict):
        raise DecisionsError("decisions.yaml must hold the `risk` and `shadow` blocks")
    try:
        return Decisions.model_validate(data)
    except ValidationError as exc:
        raise DecisionsError(f"decisions.yaml: {_explain(exc)}") from None


class _PlainLoader(yaml.SafeLoader):
    """YAML with the clever parts switched off.

    The file is a short list of limits. Anything that could make the app
    load a value other than the one a person reads in the file is refused:
    a key written twice (YAML would silently keep the last), references and
    merges, and whole numbers in any spelling but plain digits (YAML reads
    `010` as 8 and `1:00` as 60).
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise _Refused("a merge key (<<) is not allowed")
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, str):
                raise _Refused("every key must be plain text")
            if key in seen:
                raise _Refused(f"the key `{key}` is written twice")
            seen.add(key)
        return super().construct_mapping(node, deep)

    def construct_yaml_int(self, node: yaml.ScalarNode) -> int:
        if not _PLAIN_COUNT.fullmatch(node.value):
            raise _Refused("write whole numbers as plain digits, like 3")
        return int(node.value)


class _Refused(Exception):
    """The file uses something this loader does not allow."""


_PLAIN_COUNT = re.compile(r"[1-9][0-9]{0,3}")
_PlainLoader.add_constructor("tag:yaml.org,2002:int", _PlainLoader.construct_yaml_int)
_PlainLoader.add_constructor("tag:yaml.org,2002:map", _PlainLoader.construct_yaml_map)


def _read_yaml(text: str) -> Any:
    for event in yaml.parse(text, Loader=_PlainLoader):
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            raise _Refused("references (& and *) are not allowed")
    return yaml.load(text, Loader=_PlainLoader)  # noqa: S506 - a SafeLoader subclass


def load_decisions(path: Path = DECISIONS_FILE) -> Decisions:
    """Read and check the file. Raises DecisionsError with what to fix."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise DecisionsError(f"{path.name} could not be read") from None
    try:
        data = _read_yaml(text)
    except _Refused as exc:
        raise DecisionsError(f"{path.name}: {exc}") from None
    except (yaml.YAMLError, ValueError, RecursionError):
        raise DecisionsError(f"{path.name} is not valid YAML") from None
    return parse_decisions(data)
