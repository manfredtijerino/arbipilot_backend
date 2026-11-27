"""Binance addresses per trading mode.

`shadow` and `live` read the real exchange. `testnet` uses the fake exchange.
The address is checked here, in one place, so a typo in `.env` can never send
a request (and later a key) to the wrong host.
"""

from urllib.parse import urlsplit

from config.settings import Settings

# Binance Spot testnet REST host (checked against the live host 2026-11-16).
TESTNET_REST_URL = "https://testnet.binance.vision"

# The real exchange's REST hosts, from Binance's Spot API documentation.
MAINNET_REST_HOSTS = frozenset(
    {
        "api.binance.com",
        "api-gcp.binance.com",
        "api1.binance.com",
        "api2.binance.com",
        "api3.binance.com",
        "api4.binance.com",
    }
)

# Seconds to wait for a public Binance answer.
REQUEST_TIMEOUT_SECONDS = 10

# Largest allowed gap between Binance's clock and ours, in milliseconds.
# Signed requests are rejected by Binance when the clocks disagree too much.
# A technical tolerance, not a risk limit; moves to decisions.yaml when that
# file is created.
MAX_CLOCK_DRIFT_MS = 1000


class ExchangeConfigError(Exception):
    """A Binance setting is missing or wrong. The message is safe to show."""


def mainnet_rest_url(settings: Settings) -> str:
    """The real exchange's REST address, without a trailing slash.

    `BINANCE_BASE_URL` must be https and one of the real exchange's hosts.
    """
    base_url = settings.binance_base_url.strip().rstrip("/")
    if not base_url:
        raise ExchangeConfigError("not configured (BINANCE_BASE_URL is empty in .env)")
    parts = urlsplit(base_url)
    if parts.scheme != "https":
        raise ExchangeConfigError("BINANCE_BASE_URL must start with https://")
    try:
        extras = parts.port is not None or parts.username or parts.password
    except ValueError:  # a port that is not a number
        extras = True
    if (
        parts.hostname not in MAINNET_REST_HOSTS
        or extras
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ExchangeConfigError(
            "BINANCE_BASE_URL is not one of Binance's own addresses "
            "(expected https://api.binance.com)"
        )
    # Built again from the checked host, so nothing else from `.env` survives.
    return f"https://{parts.hostname}"


def rest_base_url(settings: Settings) -> str:
    """The REST address for the current trading mode.

    `testnet` always uses the testnet host. `shadow` and `live` use the real
    exchange.
    """
    if settings.trading_mode == "testnet":
        return TESTNET_REST_URL
    return mainnet_rest_url(settings)
