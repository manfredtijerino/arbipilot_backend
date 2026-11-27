"""`/api/v1/trading/risk`: success, no token, bad input."""

from collections.abc import Callable
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.decisions import DecisionsError, parse_decisions
from config.server import create_app
from config.settings import Settings
from tests.config.test_decisions import changed
from tests.conftest import FakeClock
from trading.account import AccountSnapshot, Position

URL = "/api/v1/trading/risk"


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
            "equity": "300",
            "equity_source": "paper starting balance (no trades yet)",
            "max_position_value": "24.00",
            "day": "2026-01-01",
            "day_start_equity": "300",
            "day_profit_or_loss": "0",
            "daily_loss_limit_value": "6.00",
            "entries_paused": False,
            "pause_reason": "",
            "open_positions": 0,
            "orders_last_minute": 0,
        },
    }


def test_a_bad_day_shows_as_paused(
    app: FastAPI, client: TestClient, auth: dict, fake_clock: FakeClock
) -> None:
    client.get(URL, headers=auth)  # the day starts at 300
    fake_clock.advance(minutes=10)
    app.state.account = lambda: AccountSnapshot(
        cash=Decimal("270"),
        positions={"BTCUSDT": Position("BTCUSDT", Decimal("0.0004"), Decimal("24"))},
    )
    usage = client.get(URL, headers=auth).json()["usage"]
    assert usage["equity"] == "294" and usage["day_profit_or_loss"] == "-6"
    assert usage["entries_paused"] is True and "2%" in usage["pause_reason"]
    assert usage["open_positions"] == 1


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
