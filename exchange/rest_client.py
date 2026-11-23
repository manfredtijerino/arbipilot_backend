"""Binance REST calls.

Today this holds only the public connection check (server time and clock
drift). It sends no key and places no order. Signed requests arrive with the
Binance client on Day 2.
"""

import logging
import time

import httpx

from config.settings import Settings
from exchange.config import (
    MAX_CLOCK_DRIFT_MS,
    REQUEST_TIMEOUT_SECONDS,
    ExchangeConfigError,
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
