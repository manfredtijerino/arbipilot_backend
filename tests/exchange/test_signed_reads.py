"""Signed, read-only Binance calls. A fake transport answers; no network."""

import hashlib
import hmac
from collections.abc import Callable
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest

from config.settings import Settings
from exchange import rest_client
from exchange.config import TESTNET_REST_URL
from exchange.rest_client import (
    ACCOUNT_PATH,
    KEY_RESTRICTIONS_PATH,
    ExchangeCheckError,
    configured_keys,
    fetch_account,
    fetch_key_restrictions,
    signed_get,
)

NOW_MS = 1_800_000_000_000
MAINNET = "https://api.binance.com"


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rest_client, "_now_ms", lambda: NOW_MS)


@pytest.fixture
def testnet_key(make_settings: Callable[..., Settings]) -> rest_client.BinanceKey:
    settings = make_settings(
        binance_testnet_key="test-key", binance_testnet_secret="test-secret"
    )
    (key,) = configured_keys(settings)
    return key


def client_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- which keys, and where each may go ---


def test_no_keys_when_env_has_none(make_settings: Callable[..., Settings]) -> None:
    assert configured_keys(make_settings()) == []


def test_each_key_is_tied_to_its_own_host(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        app_env="production",
        postgres_db="arbipilot_prod",
        binance_base_url=MAINNET,
        binance_testnet_key="test-key",
        binance_testnet_secret="test-secret",
        binance_read_key="read-key",
        binance_read_secret="read-secret",
        binance_api_key="trade-key",
        binance_api_secret="trade-secret",
    )
    keys = {key.name: key.base_url for key in configured_keys(settings)}
    assert keys == {"testnet": TESTNET_REST_URL, "read": MAINNET, "trade": MAINNET}


def test_a_mainnet_key_with_a_wrong_address_is_refused(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        app_env="production",
        postgres_db="arbipilot_prod",
        binance_base_url="https://example.test",
        binance_read_key="read-key",
        binance_read_secret="read-secret",
    )
    with pytest.raises(ExchangeCheckError, match="not one of Binance's own"):
        configured_keys(settings)


def test_the_key_never_shows_when_printed(testnet_key: rest_client.BinanceKey) -> None:
    assert "test-key" not in repr(testnet_key)
    assert "test-secret" not in repr(testnet_key)


# --- the signature ---


async def test_the_request_is_signed_the_way_binance_documents(
    testnet_key: rest_client.BinanceKey,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"canTrade": True})

    async with client_answering(handler) as client:
        assert await fetch_account(testnet_key, client) == {"canTrade": True}

    (request,) = seen
    assert request.method == "GET"
    assert request.url.host == "testnet.binance.vision"
    assert request.url.path == ACCOUNT_PATH
    assert request.headers["X-MBX-APIKEY"] == "test-key"
    query = urlsplit(str(request.url)).query
    signed_part, _, signature = query.rpartition("&signature=")
    assert dict(parse_qsl(signed_part)) == {
        "recvWindow": "5000",
        "timestamp": str(NOW_MS),
    }
    expected = hmac.new(b"test-secret", signed_part.encode(), hashlib.sha256)
    assert signature == expected.hexdigest()
    # The secret itself never travels.
    assert "test-secret" not in str(request.url)
    assert "test-secret" not in str(request.headers)


async def test_only_the_listed_read_addresses_can_be_signed(
    testnet_key: rest_client.BinanceKey,
) -> None:
    async with client_answering(lambda r: httpx.Response(200, json={})) as client:
        for path in (
            "/api/v3/order",
            "/sapi/v1/capital/withdraw/apply",
            "/api/v3/time",
        ):
            with pytest.raises(ValueError):
                await signed_get(testnet_key, path, client)


async def test_the_key_settings_address_is_never_asked_of_the_testnet(
    testnet_key: rest_client.BinanceKey,
) -> None:
    async with client_answering(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError):
            await fetch_key_restrictions(testnet_key, client)
    assert KEY_RESTRICTIONS_PATH.startswith("/sapi/")


async def test_half_a_key_pair_is_refused_before_any_request(
    make_settings: Callable[..., Settings],
) -> None:
    (key,) = configured_keys(make_settings(binance_testnet_key="test-key"))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be sent")

    async with client_answering(handler) as client:
        with pytest.raises(ExchangeCheckError, match="one half"):
            await fetch_account(key, client)


# --- refusals become our own sentences ---


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (
            401,
            {"code": -2015, "msg": "Invalid API-key, IP, or permissions"},
            "refused the key",
        ),
        (400, {"code": -2014, "msg": "API-key format invalid."}, "format is wrong"),
        (400, {"code": -1022, "msg": "Signature not valid."}, "refused the signature"),
        (400, {"code": -1021, "msg": "Timestamp outside recvWindow."}, "clock is off"),
        (401, {"code": -1002, "msg": "Not authorized."}, "not authorised"),
        (400, {"code": -9999, "msg": "secret detail"}, "status 400 (code -9999)"),
        (429, {"code": -1003, "msg": "Too many requests"}, "limiting requests"),
        (418, {}, "limiting requests"),
        (403, {}, "firewall"),
        (500, "not json", "status 500"),
    ],
)
async def test_a_refusal_is_explained_in_our_words(
    testnet_key: rest_client.BinanceKey, status: int, body: object, expected: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=str(body))

    async with client_answering(handler) as client:
        with pytest.raises(ExchangeCheckError) as refused:
            await fetch_account(testnet_key, client)
    message = str(refused.value)
    assert expected in message
    # Binance's own text is never passed on, and no key ever is.
    assert "secret detail" not in message
    assert "test-key" not in message and "test-secret" not in message


async def test_network_failures_are_explained(
    testnet_key: rest_client.BinanceKey,
) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with client_answering(timeout) as client:
        with pytest.raises(ExchangeCheckError, match="in time"):
            await fetch_account(testnet_key, client)
    async with client_answering(down) as client:
        with pytest.raises(ExchangeCheckError, match="could not reach"):
            await fetch_account(testnet_key, client)


@pytest.mark.parametrize("answer", ["[]", "not json", "12"])
async def test_an_unreadable_answer_is_refused(
    testnet_key: rest_client.BinanceKey, answer: str
) -> None:
    async with client_answering(lambda r: httpx.Response(200, text=answer)) as client:
        with pytest.raises(ExchangeCheckError, match="could not read"):
            await fetch_account(testnet_key, client)


# --- mainnet keys ---


@pytest.fixture
def server_keys(
    make_settings: Callable[..., Settings],
) -> dict[str, rest_client.BinanceKey]:
    settings = make_settings(
        app_env="production",
        postgres_db="arbipilot_prod",
        binance_base_url=MAINNET,
        binance_read_key="  read-key ",  # stray spaces from .env
        binance_read_secret="read-secret\n",
        binance_api_key="trade-key",
    )
    return {key.name: key for key in configured_keys(settings)}


async def test_a_mainnet_key_goes_to_the_mainnet_and_reads_its_settings(
    server_keys: dict[str, rest_client.BinanceKey],
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"enableWithdrawals": False})

    async with client_answering(handler) as client:
        answer = await fetch_key_restrictions(server_keys["read"], client)
    assert answer == {"enableWithdrawals": False}
    (request,) = seen
    assert request.url.host == "api.binance.com"
    assert request.url.path == KEY_RESTRICTIONS_PATH
    # Stray spaces around the key and the secret are removed before use.
    assert request.headers["X-MBX-APIKEY"] == "read-key"
    signed_part, _, signature = urlsplit(str(request.url)).query.rpartition(
        "&signature="
    )
    expected = hmac.new(b"read-secret", signed_part.encode(), hashlib.sha256)
    assert signature == expected.hexdigest()


async def test_half_a_mainnet_key_pair_is_refused(
    server_keys: dict[str, rest_client.BinanceKey],
) -> None:
    async with client_answering(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ExchangeCheckError, match="one half"):
            await fetch_account(server_keys["trade"], client)


@pytest.mark.parametrize(
    ("name", "base_url"),
    [
        ("testnet", MAINNET),  # the testnet key never goes to the real exchange
        ("read", TESTNET_REST_URL),  # and a mainnet key never to the testnet
        ("trade", "https://example.test"),
        ("trade", "http://api.binance.com"),
        ("trade", "https://api.binance.com/api"),
        ("read", "https://api.binance.com@example.test"),
        ("read", "https://api.binance.com:8443"),
    ],
)
def test_a_key_cannot_be_built_for_another_host(name: str, base_url: str) -> None:
    from pydantic import SecretStr

    with pytest.raises(ValueError, match="may not be sent"):
        rest_client.BinanceKey(name, base_url, SecretStr("k"), SecretStr("s"))


async def test_a_client_that_follows_redirects_never_carries_a_key(
    testnet_key: rest_client.BinanceKey,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request must be sent")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    async with client:
        with pytest.raises(ValueError, match="redirects"):
            await fetch_account(testnet_key, client)


async def test_a_redirect_from_binance_is_a_refusal_not_followed(
    testnet_key: rest_client.BinanceKey,
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://example.test/x"})

    async with client_answering(handler) as client:
        with pytest.raises(ExchangeCheckError, match="status 302"):
            await fetch_account(testnet_key, client)
    assert seen == ["testnet.binance.vision"]
