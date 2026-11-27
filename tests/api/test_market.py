"""`/api/v1/market/...`: success, no token, bad input.

The app's market data is filled by hand here: no stream is opened and
nothing leaves the machine.
"""

from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.settings import Settings
from exchange.filters import SymbolRules
from exchange.numbers import read_json
from services.market_service import MarketData
from tests.api.conftest import error_code
from tests.conftest import FakeClock
from tests.helpers.fake_stream import book, trade

BASE = "/api/v1/market"
WS = "wss://stream.binance.com:9443"

RULES = SymbolRules(
    symbol="BTCUSDT",
    base_asset="BTC",
    quote_asset="USDT",
    status="TRADING",
    trading=True,
    min_order_value=Decimal("5.00000000"),
    tick_size=Decimal("0.01000000"),
    step_size=Decimal("0.00001000"),
    min_quantity=Decimal("0.00001000"),
)


@pytest.fixture
def market(
    app: FastAPI, make_settings: Callable[..., Settings], fake_clock: FakeClock
) -> MarketData:
    """Market data with rules loaded, one price received and the stream 'connected'."""
    market = MarketData(
        make_settings(binance_ws_url=WS, market_symbols="BTCUSDT,ETHUSDT")
    )
    market.rules = {"BTCUSDT": RULES}
    market.rules_loaded_at = fake_clock.now
    for raw in (
        book("BTCUSDT", "59896.00000000", "59896.01000000"),
        trade("BTCUSDT", "59896.01000000", "0.00001000"),
    ):
        assert market.state.apply(read_json(raw), fake_clock.now)
    assert market.stream is not None
    market.stream.connected = True
    market.stream.connected_since = fake_clock.now
    market.stream.last_message_at = fake_clock.now
    market.stream.messages_received = 2
    market.stream.connections = 1
    app.state.market = market
    return market


@pytest.mark.parametrize("path", ["/symbols", "/ticker/BTCUSDT", "/stream/status"])
def test_every_market_route_needs_a_login(
    client: TestClient, market: MarketData, path: str
) -> None:
    response = client.get(BASE + path)
    assert response.status_code == 401
    bad = client.get(BASE + path, headers={"Authorization": "Bearer nonsense"})
    assert bad.status_code == 401


def test_symbols_lists_each_pair_with_its_rules_as_text(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    response = client.get(BASE + "/symbols", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["symbols"] == [
        {
            "symbol": "BTCUSDT",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "status": "TRADING",
            "trading": True,
            "min_order_value": "5.00000000",
            "tick_size": "0.01000000",
            "step_size": "0.00001000",
            "min_quantity": "0.00001000",
        }
    ]
    assert body["loaded_at"].startswith("20") and body["stale"] is False


def test_symbols_answers_503_until_the_rules_are_loaded(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    market.rules, market.rules_error = None, "could not reach Binance"
    response = client.get(BASE + "/symbols", headers=auth)
    assert response.status_code == 503 and error_code(response) == "market_not_ready"
    assert "could not reach Binance" in response.json()["error"]["message"]


def test_ticker_gives_the_latest_prices_as_text(
    client: TestClient, auth: dict, market: MarketData, fake_clock: FakeClock
) -> None:
    fake_clock.advance(seconds=2)
    response = client.get(BASE + "/ticker/btcusdt", headers=auth)  # any letter case
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTCUSDT"
    assert (body["bid"], body["ask"]) == ("59896.00000000", "59896.01000000")
    assert (body["bid_quantity"], body["ask_quantity"]) == ("1.5", "2.5")
    assert (body["last_price"], body["last_quantity"]) == (
        "59896.01000000",
        "0.00001000",
    )
    assert body["age_ms"] == 2000 and body["stale"] is False
    assert body["last_trade_age_ms"] == 2000


def test_an_old_price_is_marked_stale(
    client: TestClient, auth: dict, market: MarketData, fake_clock: FakeClock
) -> None:
    fake_clock.advance(seconds=11)
    body = client.get(BASE + "/ticker/BTCUSDT", headers=auth).json()
    assert body["stale"] is True and body["age_ms"] == 11_000


def test_a_price_is_stale_whenever_the_stream_is_down(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    market.stream.connected = False
    assert client.get(BASE + "/ticker/BTCUSDT", headers=auth).json()["stale"] is True


def test_a_pair_with_no_price_yet_answers_503(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    response = client.get(BASE + "/ticker/ETHUSDT", headers=auth)
    assert response.status_code == 503 and error_code(response) == "market_not_ready"


def test_a_pair_off_the_watch_list_answers_404(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    response = client.get(BASE + "/ticker/DOGEUSDT", headers=auth)
    assert response.status_code == 404 and error_code(response) == "unknown_symbol"


@pytest.mark.parametrize(
    "symbol", ["BTC-USDT", "BTC", "A" * 21, "BTC%20USDT", "btc.usdt"]
)
def test_a_malformed_pair_name_is_refused(
    client: TestClient, auth: dict, market: MarketData, symbol: str
) -> None:
    response = client.get(f"{BASE}/ticker/{symbol}", headers=auth)
    assert response.status_code == 422


def test_stream_status_when_connected(
    client: TestClient, auth: dict, market: MarketData, fake_clock: FakeClock
) -> None:
    fake_clock.advance(milliseconds=300)
    response = client.get(BASE + "/stream/status", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "connected" and body["detail"] == ""
    assert body["host"] == "stream.binance.com"
    assert body["streams"] == [
        "btcusdt@bookTicker",
        "btcusdt@aggTrade",
        "ethusdt@bookTicker",
        "ethusdt@aggTrade",
    ]
    assert body["messages_received"] == 2 and body["reconnects"] == 0
    assert body["last_message_age_ms"] == 300
    assert body["recording"]["enabled"] is False


def test_stream_status_while_reconnecting_says_why(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    market.stream.connected, market.stream.connected_since = False, None
    market.stream.last_error = "Binance closed the connection"
    market.stream.connections = 3
    body = client.get(BASE + "/stream/status", headers=auth).json()
    assert body["status"] == "connecting"
    assert body["detail"] == "Binance closed the connection"
    assert body["connected_since"] is None and body["reconnects"] == 2


def test_a_wrong_stream_address_is_reported_not_connected_to(
    app: FastAPI, client: TestClient, auth: dict, make_settings: Callable[..., Settings]
) -> None:
    app.state.market = MarketData(make_settings(binance_ws_url="wss://example.test"))
    body = client.get(BASE + "/stream/status", headers=auth).json()
    assert body["status"] == "not_configured" and "BINANCE_WS_URL" in body["detail"]
    assert body["host"] == "" and body["streams"] == []


def test_building_the_app_opens_no_connection(app: FastAPI) -> None:
    """Only `server.py` switches the stream on; a test app never streams."""
    assert app.state.background_work is False
    with TestClient(app):
        assert app.state.market._task is None
