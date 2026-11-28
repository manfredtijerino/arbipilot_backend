"""`/api/v1/trading/status`, `/kill`, `/resume` and `/api/v1/orders`.

Each route: success, no token, bad input. Everything runs on the in-memory
store with a price set by hand; nothing leaves the machine.
"""

from collections.abc import Callable
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.server import create_app
from config.settings import Settings
from services.market_service import MarketData
from tests.api.conftest import error_code
from tests.conftest import FakeClock
from tests.helpers.memory_store import MemoryStore
from tests.helpers.paper import live_market, opener

BASE = "/api/v1/trading"
STATUS, KILL, RESUME = f"{BASE}/status", f"{BASE}/kill", f"{BASE}/resume"
TEST_ORDER = f"{BASE}/orders/test"
ORDERS = "/api/v1/orders"
BUY = {"symbol": "BTCUSDT", "side": "BUY"}
SELL = {"symbol": "BTCUSDT", "side": "SELL"}


@pytest.fixture
def market(
    app: FastAPI, make_settings: Callable[..., Settings], fake_clock: FakeClock
) -> MarketData:
    app.state.market = live_market(make_settings, fake_clock.now)
    return app.state.market


@pytest.mark.parametrize(
    ("method", "url"),
    [("GET", STATUS), ("POST", KILL), ("POST", RESUME), ("GET", ORDERS)],
)
def test_every_route_needs_a_login(client: TestClient, method: str, url: str) -> None:
    assert client.request(method, url).status_code == 401
    bad = client.request(method, url, headers={"Authorization": "Bearer nonsense"})
    assert bad.status_code == 401


def test_the_status_of_a_running_bot(
    app: FastAPI, client: TestClient, auth: dict
) -> None:
    response = client.get(STATUS, headers=auth)
    assert response.status_code == 200
    body = response.json()
    started = datetime.fromisoformat(body.pop("app_started_at"))
    assert started == app.state.started_at and started.tzinfo is not None
    assert body == {
        "environment": "development",
        "trading_mode": "shadow",
        "state": "running",
        "pause_reason": "",
        "kill_switch": False,
        "kill_reason": "",
        "daily_loss_pause": False,
        "equity": "300.00000000",
        "prices_stale": False,
        "open_positions": 0,
        "day": "2026-01-01",
        "day_profit_or_loss": "0.00000000",
    }


def test_kill_then_a_buy_is_refused_a_sale_works_and_resume_opens_again(
    client: TestClient, auth: dict, market: MarketData, store: MemoryStore
) -> None:
    assert client.post(TEST_ORDER, headers=auth, json=BUY).json()["fill"] is not None

    killed = client.post(KILL, headers=auth, json={"reason": "testing the button"})
    assert killed.status_code == 200
    body = killed.json()
    assert (body["state"], body["kill_switch"]) == ("paused", True)
    assert body["kill_reason"] == "testing the button"
    assert store.paper.risk_state.outside_pause == "testing the button"
    assert client.get(STATUS, headers=auth).json()["state"] == "paused"
    assert client.get(f"{BASE}/risk", headers=auth).json()["usage"]["entries_paused"]

    sale = client.post(TEST_ORDER, headers=auth, json=SELL).json()
    assert sale["fill"]["side"] == "SELL"  # closing is never blocked
    refused = client.post(TEST_ORDER, headers=auth, json=BUY).json()
    assert (refused["code"], refused["fill"]) == ("trading_paused", None)

    resumed = client.post(RESUME, headers=auth)
    assert resumed.status_code == 200
    assert (resumed.json()["state"], resumed.json()["kill_switch"]) == (
        "running",
        False,
    )
    assert client.post(TEST_ORDER, headers=auth, json=BUY).json()["fill"] is not None


def test_kill_works_without_a_body_and_twice(client: TestClient, auth: dict) -> None:
    first = client.post(KILL, headers=auth)
    assert first.status_code == 200
    assert first.json()["kill_reason"] == "stopped by the owner"
    again = client.post(KILL, headers=auth, json={})
    assert again.status_code == 200 and again.json()["kill_switch"] is True
    # Resume twice is harmless too.
    assert client.post(RESUME, headers=auth).json()["state"] == "running"
    assert client.post(RESUME, headers=auth).json()["state"] == "running"


@pytest.mark.parametrize(
    "body",
    [
        {"reason": "x" * 2001},
        {"reason": 5},
        {"reason": "ok", "resume_at": "tomorrow"},
        {"limit": "0.5"},
    ],
)
def test_a_badly_written_kill_is_refused_and_stops_nothing(
    client: TestClient, auth: dict, body: dict
) -> None:
    response = client.post(KILL, headers=auth, json=body)
    assert response.status_code == 422 and error_code(response) == "invalid_input"
    assert client.get(STATUS, headers=auth).json()["state"] == "running"


def test_an_oddly_written_reason_never_stops_the_stop_button(
    client: TestClient, auth: dict
) -> None:
    odd = "two\nlines\x00 and \u202e hidden " + "x" * 400
    body = client.post(KILL, headers=auth, json={"reason": odd}).json()
    assert body["kill_switch"] is True
    assert body["kill_reason"].startswith("two lines and  hidden xxx")
    assert len(body["kill_reason"]) == 150


def test_a_kill_that_cannot_be_saved_still_stops_and_says_so(
    app: FastAPI, client: TestClient, auth: dict, market: MarketData, store: MemoryStore
) -> None:
    working = app.state.paper.open_store

    class Down:
        async def __aenter__(self) -> None:
            raise OSError("no route to the database")

        async def __aexit__(self, *args: object) -> None:
            return None

    app.state.paper.open_store = Down
    response = client.post(KILL, headers=auth)
    assert response.status_code == 503
    assert error_code(response) == "pause_not_saved"
    assert "no route" not in response.text
    for url, method in ((STATUS, "GET"), (RESUME, "POST"), (ORDERS, "GET")):
        down = client.request(method, url, headers=auth)
        assert down.status_code == 503
        assert error_code(down) == "database_unavailable"
    # The database is back: trading is stopped, and now it is written down.
    app.state.paper.open_store = working
    refused = client.post(TEST_ORDER, headers=auth, json=BUY).json()
    assert refused["code"] == "trading_paused"
    assert store.paper.risk_state.outside_pause == "stopped by the owner"


def test_kill_and_resume_exist_in_production_too(
    make_settings: Callable[..., Settings],
    store: MemoryStore,
    fake_clock: FakeClock,
    tokens: dict,
) -> None:
    from api import dependencies

    production = create_app(make_settings(app_env="production"))

    async def memory_store() -> MemoryStore:
        return store

    production.dependency_overrides[dependencies.get_store] = memory_store
    production.state.paper.open_store = opener(store)
    production.state.market = live_market(make_settings, fake_clock.now)
    prod = TestClient(production, raise_server_exceptions=False)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    killed = prod.post(KILL, headers=auth).json()
    assert (killed["environment"], killed["state"]) == ("production", "paused")
    assert prod.post(RESUME, headers=auth).json()["state"] == "running"
    assert prod.get(ORDERS, headers=auth).status_code == 200


# --- the order diary and ticket numbers ---


def test_the_diary_lists_every_order_newest_first(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    assert client.get(ORDERS, headers=auth).json() == {
        "limit": 50,
        "offset": 0,
        "orders": [],
    }
    bought = client.post(TEST_ORDER, headers=auth, json=BUY).json()
    refused = client.post(TEST_ORDER, headers=auth, json=BUY).json()
    body = client.get(ORDERS, headers=auth, params={"limit": 10}).json()
    newest, oldest = body["orders"]
    assert (newest["status"], newest["risk_code"]) == ("rejected", "position_exists")
    assert newest["client_order_id"] == refused["client_order_id"]
    assert (newest["fill_id"], newest["quantity"], newest["price"]) == (None,) * 3
    assert newest["risk_reason"] == refused["reason"]
    assert (oldest["status"], oldest["mode"]) == ("filled", "shadow")
    assert oldest["fill_id"] == bought["fill"]["id"]
    assert oldest["client_order_id"] == bought["client_order_id"]
    assert oldest["quantity"] == "0.00040000"
    assert oldest["requested_quantity"] is None and oldest["requested_amount"] is None
    page = client.get(ORDERS, headers=auth, params={"limit": 1, "offset": 1}).json()
    assert [o["id"] for o in page["orders"]] == [oldest["id"]]


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "limit=many"])
def test_a_bad_page_of_orders_is_refused(
    client: TestClient, auth: dict, query: str
) -> None:
    response = client.get(f"{ORDERS}?{query}", headers=auth)
    assert response.status_code == 422 and error_code(response) == "invalid_input"


def test_the_same_ticket_sent_twice_buys_once(
    client: TestClient, auth: dict, market: MarketData, store: MemoryStore
) -> None:
    order = {**BUY, "client_order_id": "my-ticket-1"}
    first = client.post(TEST_ORDER, headers=auth, json=order).json()
    again = client.post(TEST_ORDER, headers=auth, json=order).json()
    assert (first["repeated"], again["repeated"]) == (False, True)
    assert first["client_order_id"] == again["client_order_id"] == "my-ticket-1"
    assert again["fill"] == first["fill"]
    assert (again["outcome"], again["code"]) == (first["outcome"], first["code"])
    assert len(store.paper.filled) == len(store.orders.rows) == 1


@pytest.mark.parametrize("ticket", ["", "x" * 37, "has space", "semi;colon", 7])
def test_a_badly_written_ticket_is_refused(
    client: TestClient,
    auth: dict,
    market: MarketData,
    store: MemoryStore,
    ticket: object,
) -> None:
    order = {**BUY, "client_order_id": ticket}
    response = client.post(TEST_ORDER, headers=auth, json=order)
    assert response.status_code == 422 and error_code(response) == "invalid_input"
    assert store.orders.rows == []
