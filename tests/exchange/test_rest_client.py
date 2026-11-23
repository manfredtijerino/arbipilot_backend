"""Binance connection check. A fake transport answers; no network."""

from collections.abc import Callable, Iterator

import httpx
import pytest

from config.settings import Settings
from exchange import rest_client
from exchange.config import (
    MAX_CLOCK_DRIFT_MS,
    TESTNET_REST_URL,
    ExchangeConfigError,
    rest_base_url,
)
from exchange.rest_client import CLOCK_SAMPLES, ExchangeCheckError, check_exchange

NOW_MS = 1_800_000_000_000
MAINNET = "https://api.binance.com"


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(binance_base_url=MAINNET + "/")


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rest_client, "_now_ms", lambda: NOW_MS)


def clock_reading(monkeypatch: pytest.MonkeyPatch, readings: list[int]) -> None:
    """Make our clock return these values, one per reading."""
    values: Iterator[int] = iter(readings)
    monkeypatch.setattr(rest_client, "_now_ms", lambda: next(values))


def client_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def server_time(ms: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json={"serverTime": ms})


# --- which address ---


def test_shadow_uses_the_configured_address(settings: Settings) -> None:
    assert rest_base_url(settings) == MAINNET


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_testnet_always_uses_the_testnet_address(
    make_settings: Callable[..., Settings], app_env: str
) -> None:
    production = app_env == "production"
    settings = make_settings(
        app_env=app_env,
        postgres_db="arbipilot_prod" if production else "arbipilot_dev",
        postgres_test_db="" if production else "arbipilot_test",
        trading_mode="testnet",
        binance_base_url=MAINNET,
    )
    assert rest_base_url(settings) == TESTNET_REST_URL


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("", "not configured"),
        ("http://api.binance.com", "https://"),
        ("https://api.binance.com.test.invalid", "not one of Binance's"),
        ("https://binance.test.invalid", "not one of Binance's"),
        ("https://api.binance.com/somewhere", "not one of Binance's"),
        # The fake exchange must never be used while the mode says shadow or live.
        (TESTNET_REST_URL, "not one of Binance's"),
    ],
)
def test_a_wrong_address_is_refused(
    make_settings: Callable[..., Settings], address: str, expected: str
) -> None:
    with pytest.raises(ExchangeConfigError, match=expected):
        rest_base_url(make_settings(binance_base_url=address))


async def test_a_wrong_address_fails_the_check_without_calling(
    make_settings: Callable[..., Settings],
) -> None:
    def must_not_call(request: httpx.Request) -> httpx.Response:
        raise AssertionError("called the network")

    async with client_answering(must_not_call) as client:
        with pytest.raises(ExchangeCheckError, match="https://"):
            await check_exchange(
                make_settings(binance_base_url="http://api.binance.com"), client
            )


# --- the call ---


async def test_calls_the_public_time_endpoint_without_any_key(
    settings: Settings,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"serverTime": NOW_MS})

    async with client_answering(handler) as client:
        assert await check_exchange(settings, client) == 0
    # One request to open the connection, then the clock readings.
    assert len(seen) == 1 + CLOCK_SAMPLES
    assert {str(request.url) for request in seen} == {f"{MAINNET}/api/v3/time"}
    assert all("x-mbx-apikey" not in request.headers for request in seen)


# --- the clock ---


@pytest.mark.parametrize("drift", [MAX_CLOCK_DRIFT_MS, -MAX_CLOCK_DRIFT_MS])
async def test_drift_exactly_at_the_limit_is_allowed(
    settings: Settings, drift: int
) -> None:
    async with client_answering(server_time(NOW_MS + drift)) as client:
        assert await check_exchange(settings, client) == drift


@pytest.mark.parametrize(
    ("drift", "direction"),
    [(MAX_CLOCK_DRIFT_MS + 1, "behind"), (-MAX_CLOCK_DRIFT_MS - 1, "ahead of")],
)
async def test_drift_over_the_limit_is_refused_and_says_which_way(
    settings: Settings, drift: int, direction: str
) -> None:
    async with client_answering(server_time(NOW_MS + drift)) as client:
        with pytest.raises(ExchangeCheckError, match=f"ms {direction} Binance"):
            await check_exchange(settings, client)


async def test_drift_is_measured_from_the_middle_of_the_round_trip(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every reading: sent at +0, answered at +400. Binance stamps +200, the
    # middle, so the clocks agree exactly.
    clock_reading(monkeypatch, [NOW_MS, NOW_MS + 400] * CLOCK_SAMPLES)
    async with client_answering(server_time(NOW_MS + 200)) as client:
        assert await check_exchange(settings, client) == 0


async def test_the_fastest_reading_is_the_one_used(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Round trips of 3000, 100 and 3000 ms. Binance always says NOW + 50, which
    # is the middle of the fast one only.
    clock_reading(
        monkeypatch,
        [NOW_MS, NOW_MS + 3000, NOW_MS, NOW_MS + 100, NOW_MS, NOW_MS + 3000],
    )
    async with client_answering(server_time(NOW_MS + 50)) as client:
        assert await check_exchange(settings, client) == 0


async def test_a_slow_connection_is_blamed_on_the_network_not_the_clock(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow = 2 * MAX_CLOCK_DRIFT_MS + 2
    clock_reading(monkeypatch, [NOW_MS, NOW_MS + slow] * CLOCK_SAMPLES)
    async with client_answering(server_time(NOW_MS + slow // 2)) as client:
        with pytest.raises(ExchangeCheckError, match="too slow to compare clocks"):
            await check_exchange(settings, client)


# --- failures ---


async def test_error_status_is_reported(settings: Settings) -> None:
    async with client_answering(lambda request: httpx.Response(451)) as client:
        with pytest.raises(ExchangeCheckError, match="status 451"):
            await check_exchange(settings, client)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectError("no route"), "could not reach Binance"),
        (httpx.InvalidURL("bad address"), "could not reach Binance"),
        (httpx.ReadTimeout("slow"), "in time"),
    ],
)
async def test_network_failures_are_reported(
    settings: Settings, error: Exception, expected: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    async with client_answering(handler) as client:
        with pytest.raises(ExchangeCheckError, match=expected):
            await check_exchange(settings, client)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={}),
        httpx.Response(200, json={"serverTime": "soon"}),
        httpx.Response(200, json={"serverTime": True}),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, text="<html>maintenance</html>"),
    ],
)
async def test_unreadable_answer_is_reported(
    settings: Settings, response: httpx.Response
) -> None:
    async with client_answering(lambda request: response) as client:
        with pytest.raises(ExchangeCheckError, match="could not read"):
            await check_exchange(settings, client)
