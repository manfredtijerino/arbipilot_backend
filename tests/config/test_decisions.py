"""`decisions.yaml`: the owner's limits load exactly, and nothing odd gets in."""

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from config.decisions import (
    DECISIONS_FILE,
    DecisionsError,
    load_decisions,
    parse_decisions,
)

GOOD: dict[str, Any] = {
    "risk": {
        "max_position_pct_equity": "0.08",
        "daily_loss_pause_pct": "0.02",
        "max_open_positions": 3,
        "max_positions_per_symbol": 1,
        "max_orders_per_minute": 8,
    },
    "shadow": {"starting_equity_usdt": "300"},
}


def changed(block: str, key: str, value: Any) -> dict[str, Any]:
    data = copy.deepcopy(GOOD)
    data[block][key] = value
    return data


def test_the_real_file_holds_the_owners_decisions() -> None:
    """Decided by the owner on 2026-11-27. Changing a value here needs his word."""
    decisions = load_decisions()
    assert decisions.risk.max_position_pct_equity == Decimal("0.08")
    assert decisions.risk.daily_loss_pause_pct == Decimal("0.02")
    assert decisions.risk.max_open_positions == 3
    assert decisions.risk.max_positions_per_symbol == 1
    assert decisions.risk.max_orders_per_minute == 8
    assert decisions.shadow.starting_equity_usdt == Decimal("300")


def test_numbers_are_exact_decimals() -> None:
    risk = parse_decisions(GOOD).risk
    assert type(risk.max_position_pct_equity) is Decimal
    assert str(risk.max_position_pct_equity) == "0.08"


def test_limits_cannot_be_changed_while_the_app_runs() -> None:
    decisions = parse_decisions(GOOD)
    with pytest.raises(Exception, match="frozen"):
        decisions.risk.max_position_pct_equity = Decimal("0.5")


@pytest.mark.parametrize(
    ("block", "key", "value", "expected"),
    [
        ("risk", "max_position_pct_equity", 0.08, "in quotes"),  # a bare float
        ("risk", "max_position_pct_equity", "8%", "max_position_pct_equity"),
        ("risk", "max_position_pct_equity", "0", "above 0"),
        ("risk", "max_position_pct_equity", "-0.08", "max_position_pct_equity"),
        ("risk", "max_position_pct_equity", "0.8", "at most 0.25"),  # a slipped zero
        ("risk", "max_position_pct_equity", "0.26", "at most 0.25"),
        ("risk", "daily_loss_pause_pct", "0.2", "at most 0.10"),
        ("risk", "daily_loss_pause_pct", "0.100001", "at most 0.10"),
        ("risk", "daily_loss_pause_pct", 2, "in quotes"),
        ("risk", "max_open_positions", 0, "from 1 to 10"),
        ("risk", "max_open_positions", 11, "from 1 to 10"),
        ("risk", "max_open_positions", "3", "max_open_positions"),
        ("risk", "max_open_positions", 3.0, "max_open_positions"),
        ("risk", "max_open_positions", True, "max_open_positions"),
        ("risk", "max_positions_per_symbol", 2, "from 1 to 1"),
        ("risk", "max_orders_per_minute", 0, "from 1 to 60"),
        ("risk", "max_orders_per_minute", 61, "from 1 to 60"),
        ("shadow", "starting_equity_usdt", 300, "in quotes"),
        ("shadow", "starting_equity_usdt", "0", "above 0"),
        ("shadow", "starting_equity_usdt", "1000000", "at most 100000"),
    ],
)
def test_a_wrong_value_is_refused_and_named(
    block: str, key: str, value: Any, expected: str
) -> None:
    with pytest.raises(DecisionsError, match=expected) as error:
        parse_decisions(changed(block, key, value))
    assert f"{block}.{key}" in str(error.value)


@pytest.mark.parametrize(
    ("value", "accepted"), [("0.25", True), ("0.250001", False), ("0.00000001", True)]
)
def test_the_edge_of_the_typing_mistake_guard(value: str, accepted: bool) -> None:
    data = changed("risk", "max_position_pct_equity", value)
    if accepted:
        assert parse_decisions(data).risk.max_position_pct_equity == Decimal(value)
    else:
        with pytest.raises(DecisionsError):
            parse_decisions(data)


def test_positions_can_never_add_up_to_more_than_the_account() -> None:
    data = changed("risk", "max_position_pct_equity", "0.25")
    data["risk"]["max_open_positions"] = 4  # exactly the whole account: allowed
    assert parse_decisions(data).risk.max_open_positions == 4
    data["risk"]["max_open_positions"] = 5
    with pytest.raises(DecisionsError, match="more than the whole account"):
        parse_decisions(data)


def test_a_missing_limit_is_named() -> None:
    data = copy.deepcopy(GOOD)
    del data["risk"]["daily_loss_pause_pct"]
    with pytest.raises(DecisionsError, match="risk.daily_loss_pause_pct: is missing"):
        parse_decisions(data)


def test_a_misspelt_limit_is_refused_not_ignored() -> None:
    data = changed("risk", "max_postion_pct_equity", "0.08")
    with pytest.raises(
        DecisionsError, match="max_postion_pct_equity: is not a known key"
    ):
        parse_decisions(data)


@pytest.mark.parametrize(
    "data", [None, [], "text", 5, {}, {"risk": {}}, {"risk": None}]
)
def test_an_empty_or_strange_file_is_refused(data: Any) -> None:
    with pytest.raises(DecisionsError):
        parse_decisions(data)


def test_the_error_never_repeats_the_value_it_refused() -> None:
    with pytest.raises(DecisionsError) as error:
        parse_decisions(changed("risk", "max_position_pct_equity", "0.777"))
    assert "0.777" not in str(error.value)


def test_a_file_that_cannot_be_read_or_parsed_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DecisionsError, match="could not be read"):
        load_decisions(tmp_path / "missing.yaml")
    broken = tmp_path / "decisions.yaml"
    broken.write_text("risk: [unclosed")
    with pytest.raises(DecisionsError, match="not valid YAML"):
        load_decisions(broken)


def test_a_good_file_loads_from_disk(tmp_path: Path) -> None:
    file = tmp_path / "decisions.yaml"
    file.write_text(DECISIONS_FILE.read_text())
    assert load_decisions(file) == load_decisions()


# --- the file itself: nothing in it may be read differently from how it looks ---

FILE = """
risk:
  max_position_pct_equity: "0.08"
  daily_loss_pause_pct: "0.02"
  max_open_positions: 3
  max_positions_per_symbol: 1
  max_orders_per_minute: 8
shadow:
  starting_equity_usdt: "300"
"""


def load_text(tmp_path: Path, text: str) -> object:
    file = tmp_path / "decisions.yaml"
    file.write_text(text)
    return load_decisions(file)


def test_the_plain_file_loads(tmp_path: Path) -> None:
    assert load_text(tmp_path, FILE) == parse_decisions(GOOD)


def test_a_limit_written_twice_is_refused_not_overwritten(tmp_path: Path) -> None:
    twice = FILE.replace(
        "  max_orders_per_minute: 8",
        '  max_orders_per_minute: 8\n  max_position_pct_equity: "0.25"',
    )
    with pytest.raises(
        DecisionsError, match="max_position_pct_equity` is written twice"
    ):
        load_text(tmp_path, twice)


def test_a_second_risk_block_is_refused(tmp_path: Path) -> None:
    second = FILE + 'risk:\n  max_position_pct_equity: "0.25"\n'
    with pytest.raises(DecisionsError, match="`risk` is written twice"):
        load_text(tmp_path, second)


@pytest.mark.parametrize(
    "spelling", ["010", "0x3C", "1_0", "1:00", "+3", "0o10", "0b11", "03", "0", "-3"]
)
def test_a_whole_number_in_a_clever_spelling_is_refused(
    tmp_path: Path, spelling: str
) -> None:
    text = FILE.replace(
        "max_orders_per_minute: 8", f"max_orders_per_minute: {spelling}"
    )
    with pytest.raises(DecisionsError):
        load_text(tmp_path, text)


@pytest.mark.parametrize(
    "value", ["yes", "3.0", "8.", "1e1", "~", "[8]", "!!python/name:os.system"]
)
def test_anything_but_a_plain_whole_number_is_refused(
    tmp_path: Path, value: str
) -> None:
    text = FILE.replace("max_orders_per_minute: 8", f"max_orders_per_minute: {value}")
    with pytest.raises(DecisionsError):
        load_text(tmp_path, text)


def test_references_and_merges_are_refused(tmp_path: Path) -> None:
    anchored = FILE.replace('"0.08"', '&share "0.08"').replace('"0.02"', "*share")
    with pytest.raises(DecisionsError, match="references"):
        load_text(tmp_path, anchored)
    merged = "base: &base\n  max_open_positions: 3\n" + FILE.replace(
        "risk:\n", "risk:\n  <<: *base\n"
    )
    with pytest.raises(DecisionsError):
        load_text(tmp_path, merged)


def test_a_file_in_the_wrong_encoding_is_refused_cleanly(tmp_path: Path) -> None:
    file = tmp_path / "decisions.yaml"
    file.write_bytes(b"\xff\xfe risk")
    with pytest.raises(DecisionsError, match="could not be read"):
        load_decisions(file)


def test_an_absurdly_long_number_is_refused_cleanly(tmp_path: Path) -> None:
    text = FILE.replace(
        "max_orders_per_minute: 8", "max_orders_per_minute: " + "9" * 5000
    )
    with pytest.raises(DecisionsError):
        load_text(tmp_path, text)


def test_a_decimal_object_is_not_accepted_in_place_of_text() -> None:
    with pytest.raises(DecisionsError, match="in quotes"):
        parse_decisions(changed("risk", "max_position_pct_equity", Decimal("NaN")))


def test_the_daily_loss_guard_accepts_exactly_its_edge() -> None:
    data = changed("risk", "daily_loss_pause_pct", "0.10")
    assert parse_decisions(data).risk.daily_loss_pause_pct == Decimal("0.10")
