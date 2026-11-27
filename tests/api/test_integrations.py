"""`/api/v1/integrations/...`: success, failure, no token.

The service behind each route is replaced by a fake, so nothing leaves the
machine. The service itself is tested in `tests/services/`.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services import integration_service as service
from services.integration_service import (
    ActionReport,
    Balance,
    BalancesReport,
    BinanceReport,
    ClaudeReport,
    DatabaseReport,
    KeyReport,
    ServerReport,
)
from tests.api.conftest import error_code

BASE = "/api/v1/integrations"

KEY = KeyReport(
    "testnet",
    "testnet",
    ok=True,
    valid=True,
    trading_allowed=True,
    maker_fee="0.00100000",
    taker_fee="0.00100000",
    detail="note",
)
SERVER = ServerReport(
    "ok",
    "",
    environment="development",
    app_uptime_seconds=300,
    machine_uptime_seconds=86_400,
    memory_total_mb=2048,
    memory_available_mb=1024,
    disk_total_gb=60.0,
    disk_free_gb=45.5,
    public_ip="203.0.113.7",
    clock_difference_ms=-40,
)

# method, path, the service function behind it, a good report, a failed report
ROUTES = [
    (
        "GET",
        "/binance",
        "binance_report",
        BinanceReport("ok", "", "api.binance.com", True, 60, [KEY]),
        BinanceReport("failed", "could not reach Binance", "api.binance.com", False),
    ),
    (
        "GET",
        "/binance/balances",
        "balances_report",
        BalancesReport(
            "ok", "", "testnet", [Balance("USDT", "250.1", "49.9", "300.0")]
        ),
        BalancesReport("failed", "Binance refused the key"),
    ),
    (
        "GET",
        "/database",
        "database_report",
        DatabaseReport("ok", "", "arbipilot_dev", "18.6", "0002", "0002"),
        DatabaseReport("failed", "timed out"),
    ),
    (
        "GET",
        "/claude",
        "claude_report",
        ClaudeReport("ok", "", model="test-model"),
        ClaudeReport("failed", "the Anthropic key was refused"),
    ),
    (
        "GET",
        "/server",
        "server_report",
        SERVER,
        ServerReport(**{**vars(SERVER), "status": "failed", "detail": "clock check"}),
    ),
    (
        "POST",
        "/telegram/test",
        "telegram_test",
        ActionReport("ok", "message sent; look at Telegram"),
        ActionReport("failed", "could not reach Telegram"),
    ),
    (
        "POST",
        "/healthchecks/test",
        "healthchecks_test",
        ActionReport("not_configured", "HEALTHCHECKS_PING_URL is empty"),
        ActionReport("failed", "could not reach Healthchecks.io"),
    ),
]
IDS = [path for _, path, *_ in ROUTES]


def fake(monkeypatch: pytest.MonkeyPatch, name: str, report: Any) -> list[tuple]:
    calls: list[tuple] = []

    async def function(*args: Any) -> Any:
        calls.append(args)
        return report

    monkeypatch.setattr(service, name, function)
    return calls


@pytest.mark.parametrize(("method", "path", "name", "good", "bad"), ROUTES, ids=IDS)
def test_a_working_service_answers_200_with_the_report(
    client: TestClient,
    auth: dict,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    name: str,
    good: Any,
    bad: Any,
) -> None:
    calls = fake(monkeypatch, name, good)
    response = client.request(method, BASE + path, headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == good.status and body["detail"] == good.detail
    assert len(calls) == 1


@pytest.mark.parametrize(("method", "path", "name", "good", "bad"), ROUTES, ids=IDS)
def test_a_failed_service_answers_503_with_the_reason(
    client: TestClient,
    auth: dict,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    name: str,
    good: Any,
    bad: Any,
) -> None:
    fake(monkeypatch, name, bad)
    response = client.request(method, BASE + path, headers=auth)
    assert response.status_code == 503
    assert response.json()["status"] == "failed"
    assert response.json()["detail"] == bad.detail


@pytest.mark.parametrize(("method", "path", "name", "good", "bad"), ROUTES, ids=IDS)
def test_no_token_means_nothing_is_checked_or_sent(
    client: TestClient,
    registered: dict,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    name: str,
    good: Any,
    bad: Any,
) -> None:
    calls = fake(monkeypatch, name, good)
    for headers in ({}, {"Authorization": "Bearer made-up-token"}):
        response = client.request(method, BASE + path, headers=headers)
        assert response.status_code == 401
        assert error_code(response) == "not_authenticated"
    assert calls == []


@pytest.mark.parametrize(("method", "path", "name", "good", "bad"), ROUTES, ids=IDS)
def test_the_wrong_method_is_refused(
    client: TestClient,
    auth: dict,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    name: str,
    good: Any,
    bad: Any,
) -> None:
    calls = fake(monkeypatch, name, good)
    wrong = "POST" if method == "GET" else "GET"
    response = client.request(wrong, BASE + path, headers=auth)
    assert response.status_code == 405
    assert error_code(response) == "method_not_allowed"
    assert calls == []


def test_binance_answer_has_every_field(
    client: TestClient, auth: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "binance_report", ROUTES[0][3])
    body = client.get(BASE + "/binance", headers=auth).json()
    assert body == {
        "status": "ok",
        "detail": "",
        "host": "api.binance.com",
        "reachable": True,
        "clock_difference_ms": 60,
        "keys": [
            {
                "name": "testnet",
                "exchange": "testnet",
                "ok": True,
                "valid": True,
                "trading_allowed": True,
                "withdrawals_enabled": None,
                "ip_restricted": None,
                "spot_only": None,
                "maker_fee": "0.00100000",
                "taker_fee": "0.00100000",
                "detail": "note",
            }
        ],
    }


def test_balances_are_text_not_numbers(
    client: TestClient, auth: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "balances_report", ROUTES[1][3])
    body = client.get(BASE + "/binance/balances", headers=auth).json()
    assert body["exchange"] == "testnet"
    assert body["balances"] == [
        {"asset": "USDT", "free": "250.1", "locked": "49.9", "total": "300.0"}
    ]


def test_server_route_passes_the_app_start_time(
    client: TestClient, auth: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake(monkeypatch, "server_report", SERVER)
    body = client.get(BASE + "/server", headers=auth).json()
    ((settings, started_at),) = calls
    assert isinstance(started_at, datetime) and started_at.tzinfo == UTC
    assert body["public_ip_matches"] is None and body["disk_free_gb"] == 45.5


def test_a_read_check_asked_twice_runs_once(
    client: TestClient, auth: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake(monkeypatch, "binance_report", ROUTES[0][3])
    first = client.get(BASE + "/binance", headers=auth)
    second = client.get(BASE + "/binance", headers=auth)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and len(calls) == 1


@pytest.mark.parametrize(
    ("path", "name"),
    [("/telegram/test", "telegram_test"), ("/healthchecks/test", "healthchecks_test")],
)
def test_a_second_send_within_a_minute_is_refused(
    client: TestClient,
    auth: dict,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    name: str,
) -> None:
    calls = fake(monkeypatch, name, ActionReport("ok", "sent"))
    assert client.post(BASE + path, headers=auth).status_code == 200
    again = client.post(BASE + path, headers=auth)
    assert again.status_code == 429
    assert error_code(again) == "too_many_requests"
    assert 1 <= int(again.headers["Retry-After"]) <= 60
    assert len(calls) == 1  # nothing was sent the second time


def test_a_request_without_a_token_does_not_use_up_the_minute(
    client: TestClient, auth: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = fake(monkeypatch, "telegram_test", ActionReport("ok", "sent"))
    assert client.post(BASE + "/telegram/test").status_code == 401
    assert client.post(BASE + "/telegram/test", headers=auth).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("error", [OSError("down"), TimeoutError("slow")])
def test_a_database_outage_is_a_plain_503_not_a_500(
    client: TestClient, auth: dict, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    from services import auth_service

    async def broken(*args: Any) -> None:
        raise error

    monkeypatch.setattr(auth_service, "authenticate", broken)
    response = client.get(BASE + "/database", headers=auth)
    assert response.status_code == 503
    assert error_code(response) == "database_unavailable"
    assert "down" not in response.text and "slow" not in response.text
