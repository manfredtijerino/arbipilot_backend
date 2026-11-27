"""Shared pieces for the paper-account tests: a market with one live price,
and a way to hand the service an in-memory store."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

from config.settings import Settings
from exchange.filters import SymbolRules
from exchange.numbers import read_json
from services.market_service import MarketData
from tests.helpers.fake_stream import book
from tests.helpers.memory_store import MemoryStore

WS = "wss://stream.binance.com:9443"
BID, ASK = "59896.00000000", "59896.01000000"


def rules(symbol: str) -> SymbolRules:
    return SymbolRules(
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        status="TRADING",
        trading=True,
        min_order_value=Decimal("5.00000000"),
        tick_size=Decimal("0.01000000"),
        step_size=Decimal("0.00001000"),
        min_quantity=Decimal("0.00001000"),
    )


def set_price(
    market: MarketData, symbol: str, bid: str, ask: str, now: datetime
) -> None:
    assert market.state.apply(read_json(book(symbol, bid, ask)), now)
    market.stream.last_message_at = now


def live_market(make_settings: Callable[..., Settings], now: datetime) -> MarketData:
    """Rules loaded for two pairs, a BTC price received, the stream 'connected'."""
    market = MarketData(
        make_settings(binance_ws_url=WS, market_symbols="BTCUSDT,ETHUSDT")
    )
    market.rules = {symbol: rules(symbol) for symbol in ("BTCUSDT", "ETHUSDT")}
    market.rules_loaded_at = now
    assert market.stream is not None
    market.stream.connected = True
    market.stream.connected_since = now
    market.stream.connections = 1
    set_price(market, "BTCUSDT", BID, ASK, now)
    return market


def opener(store: MemoryStore) -> Callable[[], object]:
    @asynccontextmanager
    async def open_store() -> AsyncIterator[MemoryStore]:
        yield store

    return open_store
