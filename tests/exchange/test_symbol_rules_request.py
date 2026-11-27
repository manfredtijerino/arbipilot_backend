"""The public request for pair rules, against a pretend Binance."""

from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from config.settings import Settings
from exchange.config import TESTNET_REST_URL
from exchange.rest_client import ExchangeCheckError, fetch_symbol_rules
from tests.exchange.test_filters import entry

SYMBOLS = ("BTCUSDT", "ETHUSDT")
GOOD = {"symbols": [entry("BTCUSDT"), entry("ETHUSDT")]}


def client_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_the_request_names_the_pairs_and_sends_no_key(
    make_settings: Callable[..., Settings],
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=GOOD, headers={"X-MBX-USED-WEIGHT-1M": "20"})

    settings = make_settings(binance_base_url="https://api.binance.com")
    async with client_answering(handler) as client:
        rules = await fetch_symbol_rules(settings, SYMBOLS, client)
    assert list(rules) == ["BTCUSDT", "ETHUSDT"]
    parts = urlsplit(str(seen[0].url))
    assert (parts.scheme, parts.hostname, parts.path) == (
        "https",
        "api.binance.com",
        "/api/v3/exchangeInfo",
    )
    assert parse_qs(parts.query) == {"symbols": ['["BTCUSDT","ETHUSDT"]']}
    assert "x-mbx-apikey" not in seen[0].headers


async def test_testnet_mode_asks_the_testnet(
    make_settings: Callable[..., Settings],
) -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(str(request.url).split("/api")[0])
        return httpx.Response(200, json=GOOD)

    async with client_answering(handler) as client:
        await fetch_symbol_rules(make_settings(trading_mode="testnet"), SYMBOLS, client)
    assert hosts == [TESTNET_REST_URL]


async def test_numbers_sent_as_json_numbers_are_refused_not_rounded(
    make_settings: Callable[..., Settings],
) -> None:
    body = (
        '{"symbols":[' + '{"symbol":"BTCUSDT","status":"TRADING","baseAsset":"BTC",'
        '"quoteAsset":"USDT","isSpotTradingAllowed":true,"filters":['
        '{"filterType":"PRICE_FILTER","tickSize":0.01},'
        '{"filterType":"LOT_SIZE","minQty":"0.1","stepSize":"0.1"},'
        '{"filterType":"NOTIONAL","minNotional":"5"}]}]}'
    )
    settings = make_settings(binance_base_url="https://api.binance.com")
    async with client_answering(lambda r: httpx.Response(200, content=body)) as client:
        with pytest.raises(ExchangeCheckError, match="BTCUSDT"):
            await fetch_symbol_rules(settings, ("BTCUSDT",), client)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(429, headers={"Retry-After": "30"}),
            "limiting requests.*wait 30 seconds",
        ),
        (httpx.Response(418), "limiting requests"),
        (
            httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."}),
            "MARKET_SYMBOLS",
        ),
        (httpx.Response(400, json={"code": -1100, "msg": "secret text"}), "Binance"),
        (httpx.Response(403), "firewall"),
        (httpx.Response(200, content=b"<html>"), "could not read"),
        (
            httpx.Response(200, json={"symbols": [entry("BTCUSDT")]}),
            "no trading rules for ETHUSDT",
        ),
    ],
)
async def test_a_refusal_is_explained_in_our_words(
    make_settings: Callable[..., Settings], response: httpx.Response, expected: str
) -> None:
    settings = make_settings(binance_base_url="https://api.binance.com")
    async with client_answering(lambda request: response) as client:
        with pytest.raises(ExchangeCheckError, match=expected) as error:
            await fetch_symbol_rules(settings, SYMBOLS, client)
    assert "secret text" not in str(error.value)


async def test_network_failures_are_explained(
    make_settings: Callable[..., Settings],
) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    settings = make_settings(binance_base_url="https://api.binance.com")
    for handler, expected in ((timeout, "in time"), (down, "could not reach")):
        async with client_answering(handler) as client:
            with pytest.raises(ExchangeCheckError, match=expected):
                await fetch_symbol_rules(settings, SYMBOLS, client)


async def test_a_wrong_address_in_env_makes_no_request(
    make_settings: Callable[..., Settings],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made")

    settings = make_settings(binance_base_url="https://example.test")
    async with client_answering(handler) as client:
        with pytest.raises(ExchangeCheckError):
            await fetch_symbol_rules(settings, SYMBOLS, client)


async def test_a_client_that_follows_redirects_is_refused(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(binance_base_url="https://api.binance.com")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        with pytest.raises(ValueError, match="redirects"):
            await fetch_symbol_rules(settings, SYMBOLS, client)


@pytest.mark.parametrize(
    ("header", "expected"), [("30", 30), ("9999999", 0), ("\u00b2", 0), ("soon", 0)]
)
async def test_only_a_short_plain_number_is_taken_from_retry_after(
    make_settings: Callable[..., Settings], header: str, expected: int
) -> None:
    settings = make_settings(binance_base_url="https://api.binance.com")
    response = httpx.Response(429, headers={"Retry-After": header.encode()})
    async with client_answering(lambda request: response) as client:
        with pytest.raises(ExchangeCheckError) as error:
            await fetch_symbol_rules(settings, SYMBOLS, client)
    assert error.value.retry_after == expected
    assert ("wait" in str(error.value)) is bool(expected)
