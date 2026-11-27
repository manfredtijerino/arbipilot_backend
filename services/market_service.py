"""Market data as one service: the watched pairs, their rules, their live prices.

`MarketData` owns the price stream, the pair rules and the recorder. The app
creates one and starts it; the `/market` endpoints only read from it.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from config.settings import Settings
from exchange.config import (
    QUOTE_STALE_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    ExchangeConfigError,
    stream_names,
    stream_url,
)
from exchange.filters import SymbolRules
from exchange.market_stream import MarketState, MarketStream
from exchange.recorder import Recorder
from exchange.rest_client import ExchangeCheckError, fetch_symbol_rules
from services import clock
from services.errors import MarketNotReady, UnknownSymbol

logger = logging.getLogger(__name__)

# The rules are read again this often: Binance changes minimums now and then.
RULES_REFRESH_SECONDS = 6 * 60 * 60
# Seconds to wait before trying again after the rules could not be read.
RULES_RETRY_SECONDS = (5, 15, 60)
# Rules older than this are marked stale: two refreshes were missed.
RULES_MAX_AGE_SECONDS = 2 * RULES_REFRESH_SECONDS + 600
# The longest we let Binance tell us to wait.
MAX_RETRY_AFTER_SECONDS = 60 * 60


@dataclass(frozen=True)
class SymbolsView:
    loaded_at: datetime
    # True when the rules could not be refreshed for too long to be trusted.
    stale: bool
    symbols: list[SymbolRules]


@dataclass(frozen=True)
class Ticker:
    symbol: str
    bid: Decimal | None
    bid_quantity: Decimal | None
    ask: Decimal | None
    ask_quantity: Decimal | None
    last_price: Decimal | None
    last_quantity: Decimal | None
    last_trade_at: datetime | None
    # When the bid and ask last arrived, and how long ago.
    updated_at: datetime
    age_ms: int
    last_trade_age_ms: int | None
    # True when the bid and ask are too old to act on, the stream is down,
    # or the stream has not sent them again since it last reconnected.
    stale: bool


@dataclass(frozen=True)
class RecordingStatus:
    enabled: bool
    active: bool
    file: str | None
    lines_written: int
    folder_megabytes: float
    detail: str


@dataclass(frozen=True)
class StreamStatus:
    status: str  # connected, connecting or not_configured
    detail: str
    host: str
    streams: list[str]
    connected_since: datetime | None
    last_message_at: datetime | None
    last_message_age_ms: int | None
    messages_received: int
    messages_ignored: int
    reconnects: int
    recording: RecordingStatus


def _age_ms(then: datetime, now: datetime) -> int:
    return max(0, int((now - then).total_seconds() * 1000))


class MarketData:
    def __init__(
        self,
        settings: Settings,
        *,
        connect: Any | None = None,
        recorder: Recorder | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._rules_retry_after = 0
        self.symbols = settings.market_symbol_list
        self.state = MarketState(self.symbols)
        self.rules: dict[str, SymbolRules] | None = None
        self.rules_loaded_at: datetime | None = None
        self.rules_error = ""
        self.recorder = recorder
        if recorder is None and settings.market_recording:
            self.recorder = Recorder()
        self.stream: MarketStream | None = None
        self.config_error = ""
        try:
            url = stream_url(settings)
        except ExchangeConfigError as exc:
            self.config_error = str(exc)
        else:
            self.stream = MarketStream(
                url,
                self.state,
                connect=connect,
                on_raw=self.recorder.write if self.recorder else None,
            )
        self._task: asyncio.Task[None] | None = None

    # --- running ---

    def start(self) -> None:
        """Begin streaming and loading rules in the background."""
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="market-data")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.recorder is not None:
            self.recorder.close()

    async def run(self) -> None:
        jobs = [self._keep_rules_loaded()]
        if self.stream is not None:
            jobs.append(self.stream.run())
        else:
            logger.error("market stream not started: %s", self.config_error)
        await asyncio.gather(*jobs)

    async def load_rules(self, client: httpx.AsyncClient) -> bool:
        """Read the pair rules once. Old rules are kept when a refresh fails."""
        try:
            rules = await fetch_symbol_rules(self._settings, self.symbols, client)
        except ExchangeCheckError as exc:
            self.rules_error = str(exc)
            self._rules_retry_after = min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
            logger.warning("pair rules not loaded: %s", exc)
            return False
        self.rules, self.rules_loaded_at, self.rules_error = rules, clock.utc_now(), ""
        logger.info("pair rules loaded pairs=%s", ",".join(self.symbols))
        return True

    async def _keep_rules_loaded(self) -> None:
        failures = 0
        # One client for the life of the app. It must never follow redirects.
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            while True:
                try:
                    loaded = await self.load_rules(client)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - the loop must survive
                    loaded = False
                    self.rules_error = f"unexpected error ({type(exc).__name__})"
                    logger.error("pair rules: %s", self.rules_error)
                if loaded:
                    failures = 0
                    await self._sleep(RULES_REFRESH_SECONDS)
                else:
                    delay = RULES_RETRY_SECONDS[
                        min(failures, len(RULES_RETRY_SECONDS) - 1)
                    ]
                    failures += 1
                    # When Binance says how long to stay away, stay away.
                    delay = max(delay, self._rules_retry_after)
                    self._rules_retry_after = 0
                    await self._sleep(delay)

    # --- what the endpoints read ---

    def list_symbols(self) -> SymbolsView:
        if self.rules is None or self.rules_loaded_at is None:
            reason = self.rules_error or "the rules are still being read"
            raise MarketNotReady(f"The pair rules are not loaded yet: {reason}.")
        age = (clock.utc_now() - self.rules_loaded_at).total_seconds()
        return SymbolsView(
            self.rules_loaded_at, age > RULES_MAX_AGE_SECONDS, list(self.rules.values())
        )

    def ticker(self, symbol: str) -> Ticker:
        quote = self.state.quotes.get(symbol.strip().upper())
        if quote is None:
            raise UnknownSymbol
        if quote.book_updated_at is None or quote.bid is None or quote.ask is None:
            raise MarketNotReady(f"No price has arrived for {quote.symbol} yet.")
        now = clock.utc_now()
        age_ms = _age_ms(quote.book_updated_at, now)
        connected = self.stream is not None and self.stream.connected
        return Ticker(
            symbol=quote.symbol,
            bid=quote.bid,
            bid_quantity=quote.bid_quantity,
            ask=quote.ask,
            ask_quantity=quote.ask_quantity,
            last_price=quote.last_price,
            last_quantity=quote.last_quantity,
            last_trade_at=quote.last_trade_at,
            updated_at=quote.book_updated_at,
            age_ms=age_ms,
            last_trade_age_ms=(
                _age_ms(quote.trade_updated_at, now) if quote.trade_updated_at else None
            ),
            stale=(
                not connected
                or not quote.book_confirmed
                or age_ms > QUOTE_STALE_SECONDS * 1000
            ),
        )

    def _recording_status(self) -> RecordingStatus:
        recorder = self.recorder
        if recorder is None:
            return RecordingStatus(
                False, False, None, 0, 0.0, "off (MARKET_RECORDING is not true)"
            )
        return RecordingStatus(
            enabled=True,
            active=recorder.active,
            file=recorder.path.name if recorder.path else None,
            lines_written=recorder.lines_written,
            folder_megabytes=round(recorder.folder_bytes() / (1024 * 1024), 1),
            detail=recorder.stopped_reason,
        )

    def stream_status(self) -> StreamStatus:
        stream, now = self.stream, clock.utc_now()
        recording = self._recording_status()
        if stream is None:
            return StreamStatus(
                "not_configured",
                self.config_error,
                "",
                [],
                None,
                None,
                None,
                0,
                0,
                0,
                recording,
            )
        last = stream.last_message_at
        return StreamStatus(
            status="connected" if stream.connected else "connecting",
            detail="" if stream.connected else stream.last_error,
            host=stream.host,
            streams=stream_names(self.symbols),
            connected_since=stream.connected_since,
            last_message_at=last,
            last_message_age_ms=_age_ms(last, now) if last else None,
            messages_received=stream.messages_received,
            messages_ignored=stream.messages_ignored,
            reconnects=stream.reconnects,
            recording=recording,
        )
