"""Which stream address is used, and which streams are asked for."""

from collections.abc import Callable

import pytest

from config.settings import Settings
from exchange.config import (
    TESTNET_WS_URL,
    ExchangeConfigError,
    stream_names,
    stream_url,
    ws_base_url,
)

MAINNET_WS = "wss://stream.binance.com:9443"


def test_shadow_uses_the_real_exchange_stream(
    make_settings: Callable[..., Settings],
) -> None:
    assert ws_base_url(make_settings(binance_ws_url=MAINNET_WS + "/")) == MAINNET_WS
    plain = make_settings(binance_ws_url="wss://Data-Stream.binance.vision")
    assert ws_base_url(plain) == "wss://data-stream.binance.vision"


def test_testnet_mode_always_uses_the_testnet_stream(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(trading_mode="testnet", binance_ws_url=MAINNET_WS)
    assert ws_base_url(settings) == TESTNET_WS_URL


@pytest.mark.parametrize(
    "address",
    [
        "",
        "ws://stream.binance.com:9443",  # not encrypted
        "https://stream.binance.com",
        "wss://example.test",
        "wss://stream.binance.com.example.test",
        "wss://stream.binance.com@example.test",
        "wss://user@stream.binance.com",
        "wss://stream.binance.com:1234",
        "wss://stream.binance.com:port",
        "wss://[stream.binance.com",
        "wss://stream.binance.com/ws",
        "wss://stream.binance.com?x=1",
        "wss://stream.binance.com#x",
    ],
)
def test_only_binances_own_stream_hosts_are_accepted(
    make_settings: Callable[..., Settings], address: str
) -> None:
    with pytest.raises(ExchangeConfigError):
        ws_base_url(make_settings(binance_ws_url=address))


def test_two_streams_per_pair_in_lowercase() -> None:
    assert stream_names(("BTCUSDT", "ETHUSDT")) == [
        "btcusdt@bookTicker",
        "btcusdt@aggTrade",
        "ethusdt@bookTicker",
        "ethusdt@aggTrade",
    ]


def test_one_connection_carries_every_stream(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        binance_ws_url=MAINNET_WS, market_symbols="btcusdt, ETHUSDT"
    )
    assert stream_url(settings) == (
        MAINNET_WS + "/stream?streams="
        "btcusdt@bookTicker/btcusdt@aggTrade/ethusdt@bookTicker/ethusdt@aggTrade"
    )


def test_the_default_watch_list(make_settings: Callable[..., Settings]) -> None:
    assert make_settings().market_symbol_list == ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    assert make_settings().market_recording is False


@pytest.mark.parametrize(
    "value",
    [
        "",
        " , ",
        "BTCUSDT,BTCUSDT",
        "BTC-USDT",
        "BTCUSDT;DROP",
        "BTCEUR",
        "USDT",
        ",".join(f"A{n}USDT" for n in range(21)),
    ],
)
def test_a_strange_watch_list_is_refused(
    make_settings: Callable[..., Settings], value: str
) -> None:
    with pytest.raises(ValueError):
        make_settings(market_symbols=value)
