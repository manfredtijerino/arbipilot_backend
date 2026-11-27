"""Each pair's trading rules, read from a pretend `exchangeInfo` answer."""

from decimal import Decimal
from typing import Any

import pytest

from exchange.filters import RulesError, parse_exchange_info


def entry(symbol: str = "BTCUSDT", **changes: Any) -> dict[str, Any]:
    base = {
        "symbol": symbol,
        "status": "TRADING",
        "baseAsset": symbol.removesuffix("USDT"),
        "quoteAsset": "USDT",
        "isSpotTradingAllowed": True,
        "filters": [
            {
                "filterType": "PRICE_FILTER",
                "minPrice": "0.01",
                "maxPrice": "1000000",
                "tickSize": "0.01000000",
            },
            {
                "filterType": "LOT_SIZE",
                "minQty": "0.00001000",
                "maxQty": "9000",
                "stepSize": "0.00001000",
            },
            {
                "filterType": "NOTIONAL",
                "minNotional": "5.00000000",
                "applyMinToMarket": True,
                "maxNotional": "9000000",
                "avgPriceMins": 5,
            },
        ],
    }
    base.update(changes)
    return base


def without(filters: list[dict], name: str) -> list[dict]:
    return [f for f in filters if f["filterType"] != name]


def test_rules_are_read_as_exact_decimals() -> None:
    rules = parse_exchange_info({"symbols": [entry()]}, ("BTCUSDT",))["BTCUSDT"]
    assert (rules.base_asset, rules.quote_asset, rules.status) == (
        "BTC",
        "USDT",
        "TRADING",
    )
    assert rules.trading is True
    assert (
        rules.min_order_value == Decimal("5")
        and str(rules.min_order_value) == "5.00000000"
    )
    assert str(rules.tick_size) == "0.01000000"
    assert str(rules.step_size) == "0.00001000"
    assert str(rules.min_quantity) == "0.00001000"


def test_the_older_name_for_the_minimum_is_also_read() -> None:
    filters = without(entry()["filters"], "NOTIONAL") + [
        {
            "filterType": "MIN_NOTIONAL",
            "minNotional": "10.00000000",
            "applyToMarket": True,
        }
    ]
    rules = parse_exchange_info({"symbols": [entry(filters=filters)]}, ("BTCUSDT",))
    assert rules["BTCUSDT"].min_order_value == Decimal("10")


def test_only_the_watched_pairs_are_kept_in_the_order_asked() -> None:
    body = {"symbols": [entry("ETHUSDT"), entry("DOGEUSDT"), entry("BTCUSDT")]}
    rules = parse_exchange_info(body, ("BTCUSDT", "ETHUSDT"))
    assert list(rules) == ["BTCUSDT", "ETHUSDT"]


@pytest.mark.parametrize(
    ("changes", "trading"),
    [
        ({"status": "HALT"}, False),
        ({"status": "BREAK"}, False),
        ({"isSpotTradingAllowed": False}, False),
        ({"isSpotTradingAllowed": "true"}, False),
        ({}, True),
    ],
)
def test_a_pair_is_tradable_only_when_open_for_spot(
    changes: dict, trading: bool
) -> None:
    rules = parse_exchange_info({"symbols": [entry(**changes)]}, ("BTCUSDT",))
    assert rules["BTCUSDT"].trading is trading


def test_a_missing_pair_fails_the_whole_answer() -> None:
    with pytest.raises(RulesError, match="no trading rules for ETHUSDT"):
        parse_exchange_info({"symbols": [entry()]}, ("BTCUSDT", "ETHUSDT"))


@pytest.mark.parametrize(
    "broken",
    [
        {"filters": without(entry()["filters"], "NOTIONAL")},  # no minimum at all
        {"filters": without(entry()["filters"], "LOT_SIZE")},
        {"filters": without(entry()["filters"], "PRICE_FILTER")},
        {"filters": "none"},
        {"filters": [{"filterType": "PRICE_FILTER", "tickSize": "0"}]},
        {"baseAsset": ""},
        {"baseAsset": "<b>BTC</b>"},
        {"quoteAsset": "usdt"},
        {"status": "T" * 31},
        {"status": None},
    ],
)
def test_rules_that_cannot_be_read_are_never_guessed(broken: dict) -> None:
    with pytest.raises(RulesError, match="BTCUSDT"):
        parse_exchange_info({"symbols": [entry(**broken)]}, ("BTCUSDT",))


@pytest.mark.parametrize("value", ["0", "-5", "5e0", 5.0, 5, None, "", "NaN"])
def test_a_strange_minimum_is_refused(value: object) -> None:
    filters = without(entry()["filters"], "NOTIONAL") + [
        {"filterType": "NOTIONAL", "minNotional": value}
    ]
    with pytest.raises(RulesError):
        parse_exchange_info({"symbols": [entry(filters=filters)]}, ("BTCUSDT",))


def test_a_broken_pair_nobody_watches_is_skipped() -> None:
    body = {"symbols": [entry("DOGEUSDT", filters=[]), "junk", entry()]}
    assert list(parse_exchange_info(body, ("BTCUSDT",))) == ["BTCUSDT"]


@pytest.mark.parametrize("body", [None, [], {}, {"symbols": "none"}, "text"])
def test_an_unreadable_answer_is_refused(body: object) -> None:
    with pytest.raises(RulesError, match="could not read"):
        parse_exchange_info(body, ("BTCUSDT",))
