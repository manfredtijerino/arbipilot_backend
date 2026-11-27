"""Live prices: one connection to Binance carrying every watched pair.

Two kinds of message arrive (shapes checked against Binance's documentation
2026-11-27):
- `<pair>@bookTicker`: the best price someone will buy at (bid) and sell at
  (ask), every time either changes.
- `<pair>@aggTrade`: every trade that happened.

Binance closes each connection after 24 hours, and networks drop. So the
stream reconnects by itself, waiting a little longer after each failure, and
also when nothing has arrived for a minute. The `websockets` library answers
Binance's pings on its own.

Nothing here sends a key: these are public streams.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from exchange.config import STREAM_SILENCE_SECONDS
from exchange.numbers import positive_decimal, read_json
from services import clock

logger = logging.getLogger(__name__)

# Seconds to wait before each new connection attempt after a failure.
RECONNECT_DELAYS = (1, 2, 4, 8, 16, 32, 60)  # first failure waits 2

# A connection must last this long and deliver prices before the waiting
# schedule starts over. Otherwise a connection that opens and closes at once
# would be retried every second, forever.
GOOD_CONNECTION_SECONDS = 30

# The largest single message accepted, in bytes. Real ones are a few hundred.
MAX_MESSAGE_BYTES = 64 * 1024


@dataclass
class Quote:
    """The latest known prices of one pair. `None` until the first message."""

    symbol: str
    bid: Decimal | None = None  # the best price someone will buy at
    bid_quantity: Decimal | None = None
    ask: Decimal | None = None  # the best price someone will sell at
    ask_quantity: Decimal | None = None
    last_price: Decimal | None = None  # the price of the last trade
    last_quantity: Decimal | None = None
    last_trade_at: datetime | None = None  # Binance's time of that trade
    # True when the seller started the last trade (it "hit the bid").
    buyer_was_maker: bool | None = None
    # Our clock. Bid/ask and trades are timed apart: a fresh trade says
    # nothing about how old the bid and ask are.
    book_updated_at: datetime | None = None
    trade_updated_at: datetime | None = None
    # False from a disconnect until this connection sends a new bid and ask.
    book_confirmed: bool = False


class MarketState:
    """The latest quote of every watched pair, kept in memory."""

    def __init__(self, symbols: tuple[str, ...]) -> None:
        self.quotes: dict[str, Quote] = {symbol: Quote(symbol) for symbol in symbols}

    def apply(self, message: Any, received_at: datetime) -> bool:
        """Take one stream message. Returns False if it was not usable.

        A message is used whole or not at all: a strange price never
        half-updates a quote.
        """
        try:
            stream, data = message["stream"], message["data"]
            name, _, kind = stream.partition("@")
            quote = self.quotes[name.upper()]
            if data["s"] != quote.symbol:
                return False
            if kind == "bookTicker":
                bid, bid_quantity = (
                    positive_decimal(data["b"]),
                    positive_decimal(data["B"]),
                )
                ask, ask_quantity = (
                    positive_decimal(data["a"]),
                    positive_decimal(data["A"]),
                )
                if bid >= ask:  # a crossed book is never real on Spot
                    return False
                quote.bid, quote.bid_quantity = bid, bid_quantity
                quote.ask, quote.ask_quantity = ask, ask_quantity
                quote.book_updated_at = received_at
                quote.book_confirmed = True
            elif kind == "aggTrade":
                price, quantity = (
                    positive_decimal(data["p"]),
                    positive_decimal(data["q"]),
                )
                traded_at, maker = data["T"], data["m"]
                if type(traded_at) is not int or type(maker) is not bool:
                    return False
                trade_time = datetime.fromtimestamp(traded_at / 1000, UTC)
                quote.last_price, quote.last_quantity = price, quantity
                quote.last_trade_at = trade_time
                quote.buyer_was_maker = maker
                quote.trade_updated_at = received_at
            else:
                return False
        except (
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            OverflowError,
            OSError,
        ):
            return False
        return True

    def connection_lost(self) -> None:
        """Every bid and ask must be sent again before it counts as fresh."""
        for quote in self.quotes.values():
            quote.book_confirmed = False


class _Silence(Exception):
    """Connected, but nothing arrived for too long."""


def _describe(exc: BaseException) -> str:
    """Why the connection ended, in our words."""
    if isinstance(exc, _Silence):
        return f"no message for {STREAM_SILENCE_SECONDS} seconds"
    if isinstance(exc, TimeoutError):
        return "Binance did not answer the connection in time"
    if isinstance(exc, ConnectionClosed):
        return "Binance closed the connection"
    if isinstance(exc, WebSocketException):
        return "Binance refused the connection"
    if isinstance(exc, OSError):
        return "could not reach Binance"
    return f"unexpected error ({type(exc).__name__})"


class MarketStream:
    """Keeps the price stream connected and feeds each message to the state."""

    def __init__(
        self,
        url: str,
        state: MarketState,
        *,
        connect: Callable[[str], Any] | None = None,
        on_raw: Callable[[str, datetime], None] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        silence_seconds: float = STREAM_SILENCE_SECONDS,
        good_connection_seconds: float = GOOD_CONNECTION_SECONDS,
    ) -> None:
        self._url = url
        self._state = state
        self._connect = connect or self._default_connect
        self._on_raw = on_raw  # the recorder, when recording is on
        self._sleep = sleep
        self._silence_seconds = silence_seconds
        self._good_connection_seconds = good_connection_seconds
        self._socket: Any | None = None
        self.host = urlsplit(url).hostname or ""
        self.connected = False
        self.connected_since: datetime | None = None
        self.last_message_at: datetime | None = None
        self.messages_received = 0
        self.messages_ignored = 0
        self.connections = 0  # how many times a connection was opened
        self.last_error = ""

    @staticmethod
    def _default_connect(url: str) -> Any:
        parts = urlsplit(url)
        return websocket_connect(
            url,
            # Naming the host and port makes the library refuse a redirect
            # to any other address: prices only ever come from this host.
            host=parts.hostname,
            port=parts.port or 443,
            max_size=MAX_MESSAGE_BYTES,
            open_timeout=10,
            close_timeout=5,
            # Our own "are you there?" every 20 seconds, on top of Binance's.
            ping_interval=20,
            ping_timeout=20,
        )

    @property
    def reconnects(self) -> int:
        """How many times the connection had to be opened again."""
        return max(0, self.connections - 1)

    async def run(self) -> None:
        """Stay connected until cancelled. Never raises anything else."""
        failures = 0
        while True:
            received_before = self.messages_received
            started = time.monotonic()
            try:
                await self._one_connection()
            except asyncio.CancelledError:
                self._mark_down()
                raise
            except Exception as exc:  # noqa: BLE001 - every ending is survivable
                self.last_error = _describe(exc)
                logger.warning("market stream ended: %s", self.last_error)
            self._mark_down()
            good = (
                self.messages_received > received_before
                and time.monotonic() - started >= self._good_connection_seconds
            )
            failures = 0 if good else failures + 1
            delay = RECONNECT_DELAYS[min(failures, len(RECONNECT_DELAYS) - 1)]
            await self._sleep(delay)

    def _mark_down(self) -> None:
        self.connected = False
        self.connected_since = None
        self._state.connection_lost()

    async def _one_connection(self) -> None:
        async with self._connect(self._url) as socket:
            self._socket = socket
            self.connections += 1
            self.connected = True
            self.connected_since = clock.utc_now()
            logger.info("market stream connected host=%s", self.host)
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(
                            socket.recv(), self._silence_seconds
                        )
                    except TimeoutError:
                        raise _Silence from None
                    self._handle(raw)
            finally:
                self._socket = None

    def _handle(self, raw: str | bytes) -> None:
        received_at = clock.utc_now()
        self.last_message_at = received_at
        self.messages_received += 1
        try:
            message = read_json(raw)
        except ValueError:
            self.messages_ignored += 1
            return
        if not self._state.apply(message, received_at):
            self.messages_ignored += 1
            return
        if self._on_raw is not None:
            text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
            try:
                self._on_raw(text, received_at)
            except Exception as exc:  # noqa: BLE001 - recording must never stop prices
                self._on_raw = None
                logger.error("market recording switched off (%s)", type(exc).__name__)

    async def drop(self) -> bool:
        """Close the current connection on purpose; `run` then reconnects.

        For proving the reconnect works. Returns False when not connected.
        """
        socket = self._socket
        if socket is None:
            return False
        await socket.close()
        return True
