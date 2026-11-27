"""`/api/v1/trading/...`: the limits, the paper account and pretend orders.

Each route: success, no token, bad input. The paper account lives in the
in-memory store and the prices are set by hand; nothing leaves the machine.
"""

from collections.abc import Callable
from decimal import Decimal as D

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.decisions import DecisionsError, parse_decisions
from config.server import create_app
from config.settings import Settings
from database.models import PaperPosition
from services.market_service import MarketData
from tests.api.conftest import error_code
from tests.config.test_decisions import changed
from tests.conftest import FakeClock
from tests.helpers.memory_store import MemoryStore
from tests.helpers.paper import ASK, BID, live_market, opener, set_price

BASE = "/api/v1/trading"
URL = f"{BASE}/risk"
ORDERS = f"{BASE}/orders/test"
BUY = {"symbol": "BTCUSDT", "side": "BUY"}
SELL = {"symbol": "BTCUSDT", "side": "SELL"}
DOGE = {"symbol": "DOGEUSDT", "side": "BUY"}


@pytest.fixture
def market(
    app: FastAPI, make_settings: Callable[..., Settings], fake_clock: FakeClock
) -> MarketData:
    """One live BTC price, set by hand."""
    app.state.market = live_market(make_settings, fake_clock.now)
    return app.state.market


# --- GET /trading/risk ---


def test_the_limits_need_a_login(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    bad = client.get(URL, headers={"Authorization": "Bearer nonsense"})
    assert bad.status_code == 401


def test_the_owner_reads_his_limits_and_their_use(
    client: TestClient, auth: dict
) -> None:
    response = client.get(URL, headers=auth)
    assert response.status_code == 200
    assert response.json() == {
        "limits": {
            "max_position_pct_equity": "0.08",
            "daily_loss_pause_pct": "0.02",
            "max_open_positions": 3,
            "max_positions_per_symbol": 1,
            "max_orders_per_minute": 8,
        },
        "usage": {
            "equity": "300.00000000",
            "equity_source": "paper account",
            "max_position_value": "24.00000000",
            "day": "2026-01-01",
            "day_start_equity": "300.00000000",
            "day_profit_or_loss": "0.00000000",
            "daily_loss_limit_value": "6.00000000",
            "entries_paused": False,
            "pause_reason": "",
            "open_positions": 0,
            "orders_last_minute": 0,
        },
    }


def test_a_bad_day_shows_as_paused(
    client: TestClient,
    auth: dict,
    fake_clock: FakeClock,
    market: MarketData,
    store: MemoryStore,
) -> None:
    client.get(URL, headers=auth)  # the day starts at 300
    fake_clock.advance(minutes=10)
    # Now 270 in cash and BTC worth 24 at a bid of 60000: 294 in all.
    store.paper.account.cash = D("270")
    set_price(market, "BTCUSDT", "60000.00", "60000.01", fake_clock.now)
    store.paper.held["BTCUSDT"] = PaperPosition(
        symbol="BTCUSDT",
        quantity=D("0.0004"),
        cost=D("30"),
        opened_at=fake_clock.now,
        updated_at=fake_clock.now,
    )
    usage = client.get(URL, headers=auth).json()["usage"]
    assert D(usage["equity"]) == D("294") and D(usage["day_profit_or_loss"]) == -6
    assert usage["entries_paused"] is True and "2%" in usage["pause_reason"]
    assert usage["open_positions"] == 1
    assert store.paper.risk_state.daily_pause is True  # written down


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_no_request_can_change_a_limit(
    client: TestClient, auth: dict, method: str
) -> None:
    body = {"max_position_pct_equity": "0.5"}
    response = client.request(method, URL, headers=auth, json=body)
    assert response.status_code == 405
    assert client.get(URL, headers=auth).json()["limits"][
        "max_position_pct_equity"
    ] == ("0.08")


def test_the_app_uses_the_limits_it_is_given(
    make_settings: Callable[..., Settings],
) -> None:
    decisions = parse_decisions(changed("risk", "max_open_positions", 2))
    app = create_app(make_settings(), decisions)
    assert app.state.risk.limits.max_open_positions == 2


def test_the_app_does_not_start_without_readable_limits(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise DecisionsError("decisions.yaml could not be read")

    monkeypatch.setattr("config.server.load_decisions", broken)
    with pytest.raises(DecisionsError):
        create_app(make_settings())


def test_a_database_problem_is_said_plainly(
    app: FastAPI, client: TestClient, auth: dict
) -> None:
    class Down:
        async def __aenter__(self) -> None:
            raise OSError("no route to the database")

        async def __aexit__(self, *args: object) -> None:
            return None

    app.state.paper.open_store = Down
    for path in ("risk", "positions", "fills"):
        response = client.get(f"{BASE}/{path}", headers=auth)
        assert response.status_code == 503
        assert error_code(response) == "database_unavailable"
        assert "no route" not in response.text


# --- POST /trading/orders/test (development only) ---


@pytest.mark.parametrize("path", ["positions", "fills"])
def test_the_paper_account_needs_a_login(client: TestClient, path: str) -> None:
    assert client.get(f"{BASE}/{path}").status_code == 401
    assert client.post(ORDERS, json=BUY).status_code == 401


def test_a_pretend_buy_then_a_pretend_sale(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    bought = client.post(ORDERS, headers=auth, json=BUY)
    assert bought.status_code == 200
    body = bought.json()
    assert (body["outcome"], body["code"]) == ("reduced", "position_cap")
    fill = body["fill"]
    assert (fill["side"], fill["price"]) == ("BUY", ASK)
    assert fill["quantity"] == "0.00040000"  # text, never a JSON number
    assert (D(fill["fee"]), D(fill["cash_after"])) == (
        D("0.02395841"),
        D("276.01763759"),
    )
    assert fill["realized_pnl"] is None and fill["risk_outcome"] == "reduced"

    wallet = client.get(f"{BASE}/positions", headers=auth).json()
    assert wallet["source"] == "paper account"
    assert D(wallet["cash"]) == D("276.01763759")
    assert D(wallet["equity"]) == D("299.97603759")
    (position,) = wallet["positions"]
    assert (position["symbol"], position["quantity"]) == ("BTCUSDT", "0.00040000")
    assert (D(position["cost"]), position["price"]) == (D("23.98236241"), BID)
    assert D(position["profit_or_loss"]) == D("-0.02396241")

    usage = client.get(URL, headers=auth).json()["usage"]
    assert usage["open_positions"] == 1 and usage["orders_last_minute"] == 1
    assert D(usage["day_profit_or_loss"]) == D("-0.02396241")

    sold = client.post(ORDERS, headers=auth, json=SELL)
    assert sold.json()["outcome"] == "approved"
    assert D(sold.json()["fill"]["realized_pnl"]) == D("-0.04792081")
    after = client.get(f"{BASE}/positions", headers=auth).json()
    assert after["positions"] == [] and after["cash"] == after["equity"]
    assert D(after["cash"]) == D("299.95207919")

    fills = client.get(f"{BASE}/fills", headers=auth).json()
    assert (fills["limit"], fills["offset"]) == (50, 0)
    assert [f["side"] for f in fills["fills"]] == ["SELL", "BUY"]  # newest first
    one = client.get(f"{BASE}/fills?limit=1&offset=1", headers=auth).json()
    assert [f["side"] for f in one["fills"]] == ["BUY"]


def test_a_refused_order_says_why_and_trades_nothing(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    client.post(ORDERS, headers=auth, json=BUY)
    again = client.post(ORDERS, headers=auth, json=BUY)
    assert again.status_code == 200
    body = again.json()
    assert (body["outcome"], body["code"], body["fill"]) == (
        "rejected",
        "position_exists",
        None,
    )
    unknown = client.post(ORDERS, headers=auth, json=DOGE)
    assert unknown.json()["code"] == "unknown_symbol"


def test_an_empty_account_shows_300_and_no_positions(
    client: TestClient, auth: dict
) -> None:
    wallet = client.get(f"{BASE}/positions", headers=auth).json()
    assert wallet == {
        "source": "paper account",
        "cash": "300.00000000",
        "equity": "300.00000000",
        "prices_stale": False,
        "positions": [],
    }
    assert client.get(f"{BASE}/fills", headers=auth).json()["fills"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"symbol": "BTCUSDT"},  # no side
        {"symbol": "BTCUSDT", "side": "HOLD"},
        {"symbol": "btcusdt", "side": "BUY"},
        {"symbol": "BTCUSDT", "side": "BUY", "amount_usdt": 24},  # not text
        {"symbol": "BTCUSDT", "side": "BUY", "amount_usdt": "-5"},
        {"symbol": "BTCUSDT", "side": "BUY", "amount_usdt": "1e3"},
        {"symbol": "BTCUSDT", "side": "BUY", "amount_usdt": "5", "quantity": "1"},
        {"symbol": "BTCUSDT", "side": "SELL", "amount_usdt": "5"},
        {"symbol": "BTCUSDT", "side": "BUY", "live": True},  # unknown field
    ],
)
def test_a_badly_written_order_is_refused(
    client: TestClient, auth: dict, market: MarketData, store: MemoryStore, body: dict
) -> None:
    response = client.post(ORDERS, headers=auth, json=body)
    assert response.status_code == 422
    assert store.paper.filled == []


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "limit=many"])
def test_a_bad_page_of_fills_is_refused(
    client: TestClient, auth: dict, query: str
) -> None:
    assert client.get(f"{BASE}/fills?{query}", headers=auth).status_code == 422


def test_a_huge_order_is_cut_like_any_other(
    client: TestClient, auth: dict, market: MarketData
) -> None:
    huge = {**BUY, "amount_usdt": "99999999999999999999"}
    body = client.post(ORDERS, headers=auth, json=huge).json()
    assert body["outcome"] == "rejected" and body["fill"] is None
    large = {**BUY, "amount_usdt": "5000"}
    body = client.post(ORDERS, headers=auth, json=large).json()
    assert (body["outcome"], body["code"]) == ("reduced", "position_cap")
    assert D(body["fill"]["notional"]) < D("24")


def test_a_database_problem_while_ordering_is_said_plainly(
    app: FastAPI, client: TestClient, auth: dict, market: MarketData
) -> None:
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    class Down:
        async def __aenter__(self) -> None:
            raise PoolTimeout("the pool is empty")

        async def __aexit__(self, *args: object) -> None:
            return None

    app.state.paper.open_store = Down
    response = client.post(ORDERS, headers=auth, json=BUY)
    assert response.status_code == 503
    assert error_code(response) == "database_unavailable"


def test_a_stale_price_is_shown_as_stale(
    client: TestClient, auth: dict, market: MarketData, fake_clock: FakeClock
) -> None:
    client.post(ORDERS, headers=auth, json=BUY)
    fake_clock.advance(seconds=30)
    wallet = client.get(f"{BASE}/positions", headers=auth).json()
    assert wallet["prices_stale"] is True
    assert wallet["positions"][0]["price_stale"] is True
    assert wallet["positions"][0]["price"] == BID  # the old price, marked
    usage = client.get(URL, headers=auth).json()["usage"]
    assert usage["entries_paused"] is True and "unreadable" in usage["pause_reason"]


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        (False, BUY),  # no token
        (True, BUY),  # logged in, a valid order
        (True, {"symbol": "BTCUSDT"}),  # logged in, a bad body
        (False, {"nonsense": True}),
    ],
)
def test_the_test_order_does_not_exist_in_production(
    make_settings: Callable[..., Settings],
    store: MemoryStore,
    fake_clock: FakeClock,
    tokens: dict,
    headers: bool,
    body: dict,
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
    response = prod.post(ORDERS, headers=auth if headers else {}, json=body)
    assert response.status_code == 404 and error_code(response) == "not_found"
    assert store.paper.filled == []
    # The read-only routes still work there.
    assert prod.get(f"{BASE}/positions", headers=auth).status_code == 200
