"""The live price stream against a pretend Binance. No network."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from websockets.exceptions import ConnectionClosedError, InvalidURI

from exchange import market_stream
from exchange.market_stream import RECONNECT_DELAYS, MarketState, MarketStream
from exchange.numbers import read_json
from tests.conftest import FakeClock
from tests.helpers.fake_stream import (
    FakeConnect,
    FakeSocket,
    ScriptedSleep,
    book,
    trade,
)

URL = "wss://stream.binance.com:9443/stream?streams=btcusdt@bookTicker"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def state() -> MarketState:
    return MarketState(("BTCUSDT", "ETHUSDT"))


def apply(state: MarketState, raw: str) -> bool:
    return state.apply(read_json(raw), NOW)


# --- reading messages ---


def test_a_book_message_sets_bid_and_ask(state: MarketState) -> None:
    assert apply(state, book("BTCUSDT", "59896.00000000", "59896.01000000"))
    quote = state.quotes["BTCUSDT"]
    assert (quote.bid, quote.ask) == (Decimal("59896.00"), Decimal("59896.01"))
    assert str(quote.bid) == "59896.00000000"  # every digit kept
    assert (quote.bid_quantity, quote.ask_quantity) == (Decimal("1.5"), Decimal("2.5"))
    assert quote.book_updated_at == NOW and quote.book_confirmed is True
    assert quote.last_price is None and quote.trade_updated_at is None
    assert (
        state.quotes["ETHUSDT"].book_updated_at is None
    )  # the other pair is untouched


def test_a_trade_message_sets_the_last_price(state: MarketState) -> None:
    assert apply(state, trade("ETHUSDT", "3100.50000000", "0.25000000", maker=True))
    quote = state.quotes["ETHUSDT"]
    assert (quote.last_price, quote.last_quantity) == (
        Decimal("3100.5"),
        Decimal("0.25"),
    )
    assert quote.last_trade_at == datetime.fromtimestamp(1_800_000_000, UTC)
    assert quote.buyer_was_maker is True and quote.bid is None


@pytest.mark.parametrize(
    "raw",
    [
        book("DOGEUSDT", "1", "2"),  # a pair nobody watches
        book("BTCUSDT", "0", "2"),  # a price of zero
        book("BTCUSDT", "102", "101"),  # bid above ask: never real
        book("BTCUSDT", "101", "101"),
        book("BTCUSDT", "\u0661", "2"),  # a digit, but not one of 0-9
        trade("BTCUSDT", "1").replace("1800000000000", "1" + "0" * 18),  # absurd time
        book("BTCUSDT", "-1", "2"),
        book("BTCUSDT", "1e5", "2"),
        book("BTCUSDT", "NaN", "2"),
        trade("BTCUSDT", "abc"),
        '{"stream":"btcusdt@bookTicker","data":{"s":"ETHUSDT","b":"1","B":"1","a":"2","A":"1"}}',
        '{"stream":"btcusdt@bookTicker","data":{"s":"BTCUSDT","b":1.5,"B":"1","a":"2","A":"1"}}',
        '{"stream":"btcusdt@depth","data":{"s":"BTCUSDT"}}',
        '{"stream":"btcusdt@aggTrade","data":{"s":"BTCUSDT","p":"1","q":"1","T":"now","m":true}}',
        '{"stream":"btcusdt@aggTrade","data":{"s":"BTCUSDT","p":"1","q":"1","T":1,"m":"yes"}}',
        '{"stream":"btcusdt@aggTrade","data":{"s":"BTCUSDT","p":"1","q":"1","T":1e400,"m":true}}',
        '{"result":null,"id":1}',
        '{"e":"serverShutdown","E":1}',
        "[]",
        '"text"',
        "12",
    ],
)
def test_a_strange_message_changes_nothing(state: MarketState, raw: str) -> None:
    apply(state, book("BTCUSDT", "100", "101"))
    before = vars(state.quotes["BTCUSDT"]).copy()
    assert apply(state, raw) is False
    assert vars(state.quotes["BTCUSDT"]) == before


def test_a_half_good_message_never_half_updates(state: MarketState) -> None:
    apply(state, book("BTCUSDT", "100", "101"))
    assert apply(state, book("BTCUSDT", "105", "bad")) is False
    assert state.quotes["BTCUSDT"].bid == Decimal("100")


# --- staying connected ---


async def run_until_done(stream: MarketStream) -> None:
    with pytest.raises(asyncio.CancelledError):
        await stream.run()


async def test_messages_reach_the_state_and_the_recorder(
    state: MarketState, fake_clock: FakeClock
) -> None:
    recorded: list[tuple[str, datetime]] = []
    socket = FakeSocket(
        [book("BTCUSDT", "100", "101"), "not json", book("DOGEUSDT", "1", "2")]
    )
    socket._items.append(ConnectionClosedError(None, None))
    connect = FakeConnect([socket])
    stream = MarketStream(
        URL,
        state,
        connect=connect,
        sleep=ScriptedSleep(1),
        on_raw=lambda raw, at: recorded.append((raw, at)),
    )
    await run_until_done(stream)
    assert connect.urls == [URL] and stream.host == "stream.binance.com"
    assert state.quotes["BTCUSDT"].bid == Decimal("100")
    assert (stream.messages_received, stream.messages_ignored) == (3, 2)
    assert stream.last_message_at == fake_clock.now
    # Only messages that were understood are recorded.
    assert recorded == [(book("BTCUSDT", "100", "101"), fake_clock.now)]
    assert (
        stream.connected is False
        and stream.last_error == "Binance closed the connection"
    )


async def test_it_reconnects_after_a_drop_and_keeps_the_prices(
    state: MarketState,
) -> None:
    first = FakeSocket(
        [book("BTCUSDT", "100", "101"), ConnectionClosedError(None, None)]
    )
    second = FakeSocket(
        [book("BTCUSDT", "102", "103"), ConnectionClosedError(None, None)]
    )
    sleep = ScriptedSleep(2)
    stream = MarketStream(
        URL,
        state,
        connect=FakeConnect([first, second]),
        sleep=sleep,
        good_connection_seconds=0,
    )
    await run_until_done(stream)
    assert stream.connections == 2 and stream.reconnects == 1
    assert state.quotes["BTCUSDT"].bid == Decimal("102")
    # Each connection delivered prices, so the wait stays at the shortest.
    assert sleep.delays == [RECONNECT_DELAYS[0], RECONNECT_DELAYS[0]]


async def test_the_wait_grows_while_binance_cannot_be_reached(
    state: MarketState,
) -> None:
    failures = [OSError("down")] * 9
    sleep = ScriptedSleep(9)
    stream = MarketStream(URL, state, connect=FakeConnect(failures), sleep=sleep)
    await run_until_done(stream)
    assert sleep.delays == [2, 4, 8, 16, 32, 60, 60, 60, 60]
    assert stream.connections == 0 and stream.reconnects == 0
    assert stream.last_error == "could not reach Binance"


async def test_the_wait_starts_over_after_a_good_connection(state: MarketState) -> None:
    good = FakeSocket(
        [book("BTCUSDT", "100", "101"), ConnectionClosedError(None, None)]
    )
    outcomes = [OSError("down"), OSError("down"), good, OSError("down")]
    sleep = ScriptedSleep(4)
    stream = MarketStream(
        URL,
        state,
        connect=FakeConnect(outcomes),
        sleep=sleep,
        good_connection_seconds=0,
    )
    await run_until_done(stream)
    assert sleep.delays == [2, 4, 1, 2]


async def test_a_connection_that_opens_and_closes_at_once_is_not_retried_every_second(
    state: MarketState,
) -> None:
    def flap() -> FakeSocket:
        return FakeSocket(
            [book("BTCUSDT", "100", "101"), ConnectionClosedError(None, None)]
        )

    sleep = ScriptedSleep(5)
    stream = MarketStream(
        URL, state, connect=FakeConnect([flap() for _ in range(5)]), sleep=sleep
    )
    await run_until_done(stream)
    assert sleep.delays == [2, 4, 8, 16, 32]  # prices arrived, but it never lasted


async def test_a_silent_connection_is_replaced(state: MarketState) -> None:
    silent = FakeSocket([book("BTCUSDT", "100", "101")])  # then nothing, forever
    stream = MarketStream(
        URL,
        state,
        connect=FakeConnect([silent]),
        sleep=ScriptedSleep(1),
        silence_seconds=0.01,
    )
    await run_until_done(stream)
    assert stream.connections == 1 and stream.last_error == "no message for 60 seconds"


async def test_a_drop_means_every_bid_and_ask_must_arrive_again(
    state: MarketState,
) -> None:
    socket = FakeSocket(
        [book("BTCUSDT", "100", "101"), ConnectionClosedError(None, None)]
    )
    stream = MarketStream(
        URL, state, connect=FakeConnect([socket]), sleep=ScriptedSleep(1)
    )
    await run_until_done(stream)
    quote = state.quotes["BTCUSDT"]
    assert quote.bid == Decimal("100") and quote.book_confirmed is False


async def test_a_broken_recorder_is_switched_off_and_prices_go_on(
    state: MarketState,
) -> None:
    calls: list[str] = []

    def broken(raw: str, at: datetime) -> None:
        calls.append(raw)
        raise RuntimeError("disk on fire")

    socket = FakeSocket(
        [
            book("BTCUSDT", "100", "101"),
            book("BTCUSDT", "102", "103"),
            ConnectionClosedError(None, None),
        ]
    )
    stream = MarketStream(
        URL, state, connect=FakeConnect([socket]), sleep=ScriptedSleep(1), on_raw=broken
    )
    await run_until_done(stream)
    assert len(calls) == 1  # asked once, then left alone
    assert state.quotes["BTCUSDT"].bid == Decimal("102")
    assert stream.last_error == "Binance closed the connection"


def test_the_real_connection_names_its_host_so_redirects_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict = {}

    def pretend_connect(url: str, **kwargs: object) -> None:
        seen.update(kwargs, url=url)

    monkeypatch.setattr(market_stream, "websocket_connect", pretend_connect)
    MarketStream._default_connect(URL)
    assert (seen["host"], seen["port"]) == ("stream.binance.com", 9443)
    assert seen["max_size"] == market_stream.MAX_MESSAGE_BYTES
    MarketStream._default_connect("wss://data-stream.binance.vision/stream?streams=x")
    assert (seen["host"], seen["port"]) == ("data-stream.binance.vision", 443)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvalidURI("x", "bad"), "Binance refused the connection"),
        (TimeoutError(), "Binance did not answer the connection in time"),
        (RuntimeError("secret detail"), "unexpected error (RuntimeError)"),
    ],
)
async def test_every_ending_is_described_in_our_words(
    state: MarketState, error: Exception, expected: str
) -> None:
    stream = MarketStream(
        URL, state, connect=FakeConnect([error]), sleep=ScriptedSleep(1)
    )
    await run_until_done(stream)
    assert stream.last_error == expected


async def test_a_forced_drop_closes_the_socket_and_the_stream_comes_back(
    state: MarketState,
) -> None:
    first = FakeSocket([book("BTCUSDT", "100", "101")])  # stays open
    second = FakeSocket([book("BTCUSDT", "102", "103")])
    stream = MarketStream(
        URL,
        state,
        connect=FakeConnect([first, second]),
        sleep=lambda s: asyncio.sleep(0),
    )
    assert await stream.drop() is False  # nothing to drop yet
    task = asyncio.create_task(stream.run())
    for _ in range(20):
        await asyncio.sleep(0)
    assert stream.connected and stream.connected_since is not None
    assert await stream.drop() is True and first.close_calls == 1
    for _ in range(20):
        await asyncio.sleep(0)
    assert stream.connected and stream.reconnects == 1
    assert state.quotes["BTCUSDT"].bid == Decimal("102")
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert stream.connected is False
