"""Binance REST calls.

Two kinds, both read-only:
- the public connection check (server time and clock drift), which sends no key;
- signed reads of the account, used by the connection checks.

Nothing here places an order, and the only signed addresses allowed are the
ones in `SIGNED_READ_PATHS`. A key is only ever sent to the host it belongs
to: the testnet key to the testnet, the mainnet keys to the real exchange.
"""

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import SecretStr

from config.settings import Settings, is_set
from exchange.config import (
    MAINNET_REST_HOSTS,
    MAX_CLOCK_DRIFT_MS,
    REQUEST_TIMEOUT_SECONDS,
    TESTNET_REST_URL,
    ExchangeConfigError,
    mainnet_rest_url,
    rest_base_url,
)

logger = logging.getLogger(__name__)

# How many times the clock is read. The fastest answer is the most accurate.
CLOCK_SAMPLES = 3


class ExchangeCheckError(Exception):
    """The Binance check failed. The message is safe to show the owner."""


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


async def fetch_server_time_ms(base_url: str, client: httpx.AsyncClient) -> int:
    """Binance's clock in milliseconds, from the public `GET /api/v3/time`."""
    response = await client.get(f"{base_url}/api/v3/time")
    response.raise_for_status()
    server_time = response.json()["serverTime"]
    if isinstance(server_time, bool) or not isinstance(server_time, int):
        raise ValueError("serverTime is not a whole number")
    return server_time


async def measure_clock(base_url: str, client: httpx.AsyncClient) -> tuple[int, int]:
    """Returns (round trip in ms, Binance's clock minus ours in ms).

    The first request only opens the connection, so the slow handshake is not
    counted. Then the clock is read a few times and the fastest answer kept:
    the shorter the round trip, the less the network can distort the result.
    Each reading is compared with the middle of its own round trip.
    """
    await fetch_server_time_ms(base_url, client)
    best: tuple[int, int] | None = None
    for _ in range(CLOCK_SAMPLES):
        sent_ms = _now_ms()
        server_ms = await fetch_server_time_ms(base_url, client)
        received_ms = _now_ms()
        sample = (received_ms - sent_ms, server_ms - (sent_ms + received_ms) // 2)
        if best is None or sample[0] < best[0]:
            best = sample
    assert best is not None  # CLOCK_SAMPLES is at least 1
    return best


async def check_exchange(
    settings: Settings, client: httpx.AsyncClient | None = None
) -> int:
    """Check Binance is reachable and our clock agrees with it.

    Returns Binance's clock minus ours in milliseconds (positive: our clock is
    behind), or raises ExchangeCheckError.
    """
    try:
        base_url = rest_base_url(settings)
    except ExchangeConfigError as exc:
        raise ExchangeCheckError(str(exc)) from None

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        round_trip_ms, drift_ms = await measure_clock(base_url, client)
    except httpx.TimeoutException:
        raise ExchangeCheckError("Binance did not answer in time") from None
    except httpx.HTTPStatusError as exc:
        raise ExchangeCheckError(
            f"Binance answered with status {exc.response.status_code}"
        ) from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise ExchangeCheckError("could not reach Binance") from None
    except (KeyError, ValueError, TypeError):
        raise ExchangeCheckError("Binance sent an answer we could not read") from None
    finally:
        if owns_client:
            await client.aclose()

    # The reading can be wrong by up to half the round trip. If that alone is
    # over the limit, the network is the problem, not the clock.
    if round_trip_ms // 2 > MAX_CLOCK_DRIFT_MS:
        raise ExchangeCheckError(
            f"the connection to Binance is too slow to compare clocks "
            f"(round trip {round_trip_ms} ms)"
        )
    if abs(drift_ms) > MAX_CLOCK_DRIFT_MS:
        direction = "behind" if drift_ms > 0 else "ahead of"
        raise ExchangeCheckError(
            f"this machine's clock is {abs(drift_ms)} ms {direction} Binance "
            f"(limit {MAX_CLOCK_DRIFT_MS} ms)"
        )
    logger.info(
        "binance reachable host=%s clock_drift_ms=%+d round_trip_ms=%d",
        base_url,
        drift_ms,
        round_trip_ms,
    )
    return drift_ms


# --- Signed reads (rules checked against Binance's documentation 2026-11-26) ---

ACCOUNT_PATH = "/api/v3/account"
# The key's own settings: withdrawals, IP lock, trading. The real exchange
# only; the testnet serves `/api` addresses and nothing else.
KEY_RESTRICTIONS_PATH = "/sapi/v1/account/apiRestrictions"
# The only addresses a key is ever sent to from this file. Both only read.
SIGNED_READ_PATHS = frozenset({ACCOUNT_PATH, KEY_RESTRICTIONS_PATH})

# How long after its timestamp Binance still accepts a signed request.
RECV_WINDOW_MS = 5000

# Binance's error codes, turned into sentences written here.
_REFUSALS = {
    -2014: "Binance says the key's format is wrong",
    -2015: (
        "Binance refused the key (wrong key, a caller address the key is not "
        "locked to, or a missing permission)"
    ),
    -1022: "Binance refused the signature (the secret does not match the key)",
    -1021: "Binance refused the request's time (this machine's clock is off)",
    -1002: "Binance says the key is not authorised for this request",
}


@dataclass(frozen=True)
class BinanceKey:
    """One key pair and the only host it may be sent to."""

    name: Literal["testnet", "read", "trade"]
    base_url: str
    api_key: SecretStr
    api_secret: SecretStr

    def __post_init__(self) -> None:
        # Whoever builds a key, it can only point at the host it belongs to.
        parts = urlsplit(self.base_url)
        if self.name == "testnet":
            allowed = self.base_url == TESTNET_REST_URL
        else:
            allowed = (
                self.base_url == f"https://{parts.hostname}"
                and parts.hostname in MAINNET_REST_HOSTS
            )
        if not allowed:
            raise ValueError(f"the {self.name} key may not be sent to this host")

    @property
    def is_testnet(self) -> bool:
        return self.name == "testnet"

    @property
    def is_complete(self) -> bool:
        return is_set(self.api_key) and is_set(self.api_secret)


def configured_keys(settings: Settings) -> list[BinanceKey]:
    """Every Binance key present in `.env`, each tied to its own host.

    A pair with only one half filled in is still listed, so the check can say
    so. Raises ExchangeCheckError if a mainnet key is present but
    `BINANCE_BASE_URL` is wrong.
    """
    keys: list[BinanceKey] = []
    if is_set(settings.binance_testnet_key) or is_set(settings.binance_testnet_secret):
        keys.append(
            BinanceKey(
                "testnet",
                TESTNET_REST_URL,
                settings.binance_testnet_key,
                settings.binance_testnet_secret,
            )
        )
    mainnet_pairs = (
        ("read", settings.binance_read_key, settings.binance_read_secret),
        ("trade", settings.binance_api_key, settings.binance_api_secret),
    )
    for name, api_key, api_secret in mainnet_pairs:
        if is_set(api_key) or is_set(api_secret):
            try:
                base_url = mainnet_rest_url(settings)
            except ExchangeConfigError as exc:
                raise ExchangeCheckError(str(exc)) from None
            keys.append(BinanceKey(name, base_url, api_key, api_secret))
    return keys


def _describe_refusal(response: httpx.Response) -> str:
    """Why Binance said no, in our words. Binance's own text is not passed on."""
    if response.status_code in (418, 429):
        return "Binance is limiting requests from this address; try again later"
    if response.status_code == 403:
        return "Binance's firewall blocked the request"
    try:
        code = response.json().get("code")
    except (ValueError, AttributeError):
        code = None
    if isinstance(code, int) and not isinstance(code, bool):
        return _REFUSALS.get(
            code,
            f"Binance answered with status {response.status_code} (code {code})",
        )
    return f"Binance answered with status {response.status_code}"


async def signed_get(
    key: BinanceKey, path: str, client: httpx.AsyncClient
) -> dict[str, Any]:
    """One signed read. Returns Binance's answer, or raises ExchangeCheckError.

    The request is signed the way Binance documents it: the query text is
    signed with HMAC-SHA256 using the secret, the signature is added to the
    query, and the key travels in the `X-MBX-APIKEY` header. The text that
    is signed is the very text that is sent; never hand the parameters to the
    HTTP library separately, it may reorder or re-encode them.

    `client` must not follow redirects (the library's default): a redirect
    would carry the key header to another host.

    For reads only. On an order a timeout means "outcome unknown", which
    needs different handling than the "did not answer" sentence here.
    """
    if path not in SIGNED_READ_PATHS:
        raise ValueError("this address is not on the list of signed reads")
    if not key.is_complete:
        raise ExchangeCheckError("only one half of the key pair is set in .env")
    if client.follow_redirects:
        raise ValueError("a client that follows redirects must not carry a key")
    api_key = key.api_key.get_secret_value().strip()
    api_secret = key.api_secret.get_secret_value().strip()
    query = urlencode({"recvWindow": RECV_WINDOW_MS, "timestamp": _now_ms()})
    signature = hmac.new(
        api_secret.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    try:
        response = await client.get(
            f"{key.base_url}{path}?{query}&signature={signature}",
            headers={"X-MBX-APIKEY": api_key},
        )
    except httpx.TimeoutException:
        raise ExchangeCheckError("Binance did not answer in time") from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise ExchangeCheckError("could not reach Binance") from None
    except UnicodeError:
        raise ExchangeCheckError(
            "the key contains characters a Binance key never has"
        ) from None
    if response.status_code != 200:
        raise ExchangeCheckError(_describe_refusal(response))
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ExchangeCheckError("Binance sent an answer we could not read")
    return body


async def fetch_account(key: BinanceKey, client: httpx.AsyncClient) -> dict[str, Any]:
    """The Spot account behind a key: permissions, fee rates, balances."""
    return await signed_get(key, ACCOUNT_PATH, client)


async def fetch_key_restrictions(
    key: BinanceKey, client: httpx.AsyncClient
) -> dict[str, Any]:
    """The key's own settings on the real exchange. Never call for the testnet."""
    if key.is_testnet:
        raise ValueError("the testnet has no key-settings address")
    return await signed_get(key, KEY_RESTRICTIONS_PATH, client)
