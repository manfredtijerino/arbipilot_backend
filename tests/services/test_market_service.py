"""The market data service: loading rules, running the stream, recording."""

import asyncio
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from config.settings import Settings
from exchange.numbers import read_json
from exchange.recorder import Recorder, read_recording
from services import market_service
from services.errors import MarketNotReady, UnknownSymbol
from services.market_service import MarketData
from tests.conftest import FakeClock
from tests.exchange.test_filters import entry
from tests.helpers.fake_stream import FakeConnect, FakeSocket, book, trade

WS = "wss://stream.binance.com:9443"


def client_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        binance_ws_url=WS,
        binance_base_url="https://api.binance.com",
        market_symbols="BTCUSDT",
    )


async def test_rules_load_and_are_listed(
    settings: Settings, fake_clock: FakeClock
) -> None:
    market = MarketData(settings)
    with pytest.raises(MarketNotReady, match="still being read"):
        market.list_symbols()
    async with client_answering(
        lambda request: httpx.Response(200, json={"symbols": [entry()]})
    ) as client:
        assert await market.load_rules(client) is True
    view = market.list_symbols()
    assert view.loaded_at == fake_clock.now
    assert [rules.symbol for rules in view.symbols] == ["BTCUSDT"]
    assert view.symbols[0].min_order_value == Decimal("5")


async def test_a_failed_refresh_keeps_the_rules_already_loaded(
    settings: Settings,
) -> None:
    market = MarketData(settings)
    async with client_answering(
        lambda request: httpx.Response(200, json={"symbols": [entry()]})
    ) as client:
        await market.load_rules(client)
    async with client_answering(lambda request: httpx.Response(500)) as client:
        assert await market.load_rules(client) is False
    assert market.rules_error and market.list_symbols().symbols[0].symbol == "BTCUSDT"


async def test_a_first_failure_is_explained(settings: Settings) -> None:
    market = MarketData(settings)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with client_answering(down) as client:
        assert await market.load_rules(client) is False
    with pytest.raises(MarketNotReady, match="could not reach Binance"):
        market.list_symbols()


def test_ticker_errors(settings: Settings) -> None:
    market = MarketData(settings)
    with pytest.raises(UnknownSymbol):
        market.ticker("ETHUSDT")
    with pytest.raises(MarketNotReady, match="BTCUSDT"):
        market.ticker(" btcusdt ")


def test_recording_is_off_unless_asked(
    settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    assert MarketData(settings).recorder is None
    status = MarketData(settings).stream_status().recording
    assert (status.enabled, status.active, status.file) == (False, False, None)
    on = MarketData(make_settings(binance_ws_url=WS, market_recording=True))
    assert isinstance(on.recorder, Recorder)


async def test_start_streams_prices_records_them_and_stop_ends_it(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_rules(self: MarketData) -> None:  # keep this test off the network
        await asyncio.Event().wait()

    monkeypatch.setattr(MarketData, "_keep_rules_loaded", no_rules)
    socket = FakeSocket([book("BTCUSDT", "100", "101")])  # then stays open
    market = MarketData(
        settings, connect=FakeConnect([socket]), recorder=Recorder(tmp_path)
    )
    market.start()
    market.start()  # a second start changes nothing
    for _ in range(20):
        await asyncio.sleep(0)
    ticker = market.ticker("BTCUSDT")
    assert (ticker.bid, ticker.ask, ticker.stale) == (
        Decimal("100"),
        Decimal("101"),
        False,
    )
    status = market.stream_status()
    assert status.status == "connected" and status.messages_received == 1
    assert status.recording.enabled and status.recording.lines_written == 1
    await market.stop()
    await market.stop()  # safe twice
    assert market.stream_status().status == "connecting"
    assert market.ticker("BTCUSDT").stale is True  # the stream is down
    rows = list(read_recording(market.recorder.path))
    assert len(rows) == 1 and rows[0][1]["data"]["b"] == "100"


class Waits:
    """Records each wait of the rules loop and ends it after `allowed`."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)
        if len(self.seconds) >= self.allowed:
            raise asyncio.CancelledError


async def test_the_rules_loop_retries_then_refreshes(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes = [False, RuntimeError("boom"), True]

    async def load(self: MarketData, client: httpx.AsyncClient) -> bool:
        assert client.follow_redirects is False
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(MarketData, "load_rules", load)
    waits = Waits(3)
    with pytest.raises(asyncio.CancelledError):
        await MarketData(settings, sleep=waits)._keep_rules_loaded()
    assert waits.seconds == [5, 15, market_service.RULES_REFRESH_SECONDS]


async def test_the_rules_loop_stays_away_as_long_as_binance_says(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = [
        httpx.Response(429, headers={"Retry-After": "120"}),
        httpx.Response(418, headers={"Retry-After": "999999"}),  # capped at an hour
        httpx.Response(500),
    ]
    transport = httpx.MockTransport(lambda request: answers.pop(0))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        market_service.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport),
    )
    waits = Waits(3)
    with pytest.raises(asyncio.CancelledError):
        await MarketData(settings, sleep=waits)._keep_rules_loaded()
    assert waits.seconds == [120, 3600, 60]


async def test_rules_too_old_to_trust_are_marked_stale(
    settings: Settings, fake_clock: FakeClock
) -> None:
    market = MarketData(settings)
    async with client_answering(
        lambda request: httpx.Response(200, json={"symbols": [entry()]})
    ) as client:
        await market.load_rules(client)
    assert market.list_symbols().stale is False
    fake_clock.advance(seconds=market_service.RULES_MAX_AGE_SECONDS + 1)
    assert market.list_symbols().stale is True


# --- is the bid and ask fresh? ---


def priced(settings: Settings, fake_clock: FakeClock) -> MarketData:
    market = MarketData(settings)
    market.stream.connected = True
    assert market.state.apply(read_json(book("BTCUSDT", "100", "101")), fake_clock.now)
    return market


def test_the_ten_second_edge(settings: Settings, fake_clock: FakeClock) -> None:
    market = priced(settings, fake_clock)
    fake_clock.advance(seconds=10)
    assert market.ticker("BTCUSDT").stale is False
    fake_clock.advance(milliseconds=1)
    assert market.ticker("BTCUSDT").stale is True


def test_a_fresh_trade_does_not_make_an_old_bid_and_ask_fresh(
    settings: Settings, fake_clock: FakeClock
) -> None:
    market = priced(settings, fake_clock)
    fake_clock.advance(seconds=30)
    assert market.state.apply(read_json(trade("BTCUSDT", "100.5")), fake_clock.now)
    ticker = market.ticker("BTCUSDT")
    assert ticker.stale is True
    assert (ticker.age_ms, ticker.last_trade_age_ms) == (30_000, 0)


def test_a_trade_alone_is_not_a_price_yet(
    settings: Settings, fake_clock: FakeClock
) -> None:
    market = MarketData(settings)
    market.stream.connected = True
    assert market.state.apply(read_json(trade("BTCUSDT", "100.5")), fake_clock.now)
    with pytest.raises(MarketNotReady):
        market.ticker("BTCUSDT")


def test_after_a_reconnect_the_bid_and_ask_must_arrive_again(
    settings: Settings, fake_clock: FakeClock
) -> None:
    market = priced(settings, fake_clock)
    market.state.connection_lost()  # the stream dropped and came back
    assert market.state.apply(read_json(trade("BTCUSDT", "100.5")), fake_clock.now)
    assert market.ticker("BTCUSDT").stale is True  # a trade is not enough
    assert market.state.apply(read_json(book("BTCUSDT", "102", "103")), fake_clock.now)
    assert market.ticker("BTCUSDT").stale is False
