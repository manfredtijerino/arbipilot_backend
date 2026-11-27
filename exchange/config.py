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

# Binance Spot testnet stream host (from the testnet's own page, 2026-11-27).
TESTNET_WS_URL = "wss://stream.testnet.binance.vision"

# The real exchange's stream hosts. The second serves market data only.
MAINNET_WS_HOSTS = frozenset({"stream.binance.com", "data-stream.binance.vision"})
MAINNET_WS_PORTS = (None, 443, 9443)

# Seconds without any message before the stream is treated as dead and
# reconnected. With the busiest pairs a message arrives many times a second.
STREAM_SILENCE_SECONDS = 60

# A price older than this many seconds is marked stale. A technical value,
# not a risk limit.
QUOTE_STALE_SECONDS = 10

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
    try:
        parts = urlsplit(base_url)
    except ValueError:
        raise ExchangeConfigError("BINANCE_BASE_URL is not a valid address") from None
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


def ws_base_url(settings: Settings) -> str:
    """The stream address for the current trading mode, without a trailing slash.

    `testnet` always uses the testnet host. `shadow` and `live` use
    `BINANCE_WS_URL`, which must be wss and one of the real exchange's hosts.
    """
    if settings.trading_mode == "testnet":
        return TESTNET_WS_URL
    url = settings.binance_ws_url.strip().rstrip("/")
    if not url:
        raise ExchangeConfigError("not configured (BINANCE_WS_URL is empty in .env)")
    try:
        parts = urlsplit(url)
    except ValueError:
        raise ExchangeConfigError("BINANCE_WS_URL is not a valid address") from None
    if parts.scheme != "wss":
        raise ExchangeConfigError("BINANCE_WS_URL must start with wss://")
    try:
        port = parts.port
        extras = parts.username or parts.password
    except ValueError:  # a port that is not a number
        port, extras = -1, True
    if (
        parts.hostname not in MAINNET_WS_HOSTS
        or port not in MAINNET_WS_PORTS
        or extras
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ExchangeConfigError(
            "BINANCE_WS_URL is not one of Binance's own stream addresses "
            "(expected wss://stream.binance.com:9443)"
        )
    # Built again from the checked parts, so nothing else from `.env` survives.
    return f"wss://{parts.hostname}" + (f":{port}" if port else "")


def stream_names(symbols: tuple[str, ...]) -> list[str]:
    """Two streams per pair: the best bid and ask, and every trade.

    The trades are needed later for honest paper fills: a pretend order only
    counts as filled after a real trade went through its price.
    """
    names = []
    for symbol in symbols:
        names += [f"{symbol.lower()}@bookTicker", f"{symbol.lower()}@aggTrade"]
    return names


def stream_url(settings: Settings) -> str:
    """One connection carrying every stream (Binance calls it a combined stream)."""
    names = "/".join(stream_names(settings.market_symbol_list))
    return f"{ws_base_url(settings)}/stream?streams={names}"
