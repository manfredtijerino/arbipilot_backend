"""`/api/v1/health` and `/api/v1/health/ready`. The connection checks are fakes."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from config.server import create_app
from config.settings import Settings
from config.version import APP_VERSION
from services import integration_service as service
from services.integration_service import CheckResult

ALL_OK = [
    CheckResult("database", True, "arbipilot_dev"),
    CheckResult("binance", True),
    CheckResult("claude", True, "test-model"),
    CheckResult("telegram", True),
]


@pytest.fixture
def checks(monkeypatch: pytest.MonkeyPatch) -> list[CheckResult]:
    """What the fake checks answer. A test may change the list before calling."""
    results = list(ALL_OK)

    async def fake_run(settings: Settings) -> list[CheckResult]:
        return results

    monkeypatch.setattr(service, "run_all_checks", fake_run)
    return results


@pytest.fixture
def client(make_settings: Callable[..., Settings], checks: list) -> TestClient:
    return TestClient(create_app(make_settings()), raise_server_exceptions=False)


def test_health_needs_no_token_and_states_the_environment(client: TestClient) -> None:
    response = client.get("/api/v1/health")  # no Authorization header
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
        "trading_mode": "shadow",
        "version": APP_VERSION,
    }


def test_ready_needs_no_token_and_lists_every_check(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    ok = {"status": "ok", "detail": ""}
    assert response.json() == {
        "status": "ok",
        "environment": "development",
        "checks": {"database": ok, "binance": ok, "claude": ok, "telegram": ok},
    }


def test_ready_is_503_and_says_why_when_a_check_fails(
    client: TestClient, checks: list[CheckResult]
) -> None:
    checks[0] = CheckResult("database", False, "not configured")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "failed"
    assert body["checks"]["database"] == {
        "status": "failed",
        "detail": "not configured",
    }
    assert body["checks"]["binance"]["status"] == "ok"


def test_bad_method_uses_the_one_error_shape(client: TestClient) -> None:
    response = client.post("/api/v1/health", json={"anything": 1})
    assert response.status_code == 405
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "This address does not accept that method.",
        }
    }


def test_unknown_address_uses_the_one_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_pages_are_off(client: TestClient, path: str) -> None:
    # They would be endpoints without login.
    assert client.get(path).status_code == 404


def test_no_browser_access_when_no_frontend_is_listed(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health", headers={"Origin": "https://elsewhere.test.invalid"}
    )
    assert "access-control-allow-origin" not in response.headers


def test_browser_access_only_for_listed_frontends(
    make_settings: Callable[..., Settings], checks: list
) -> None:
    settings = make_settings(frontend_origins="https://app.test.invalid")
    client = TestClient(create_app(settings))
    allowed = client.get(
        "/api/v1/health", headers={"Origin": "https://app.test.invalid"}
    )
    refused = client.get(
        "/api/v1/health", headers={"Origin": "https://elsewhere.test.invalid"}
    )
    assert allowed.headers["access-control-allow-origin"] == "https://app.test.invalid"
    assert "access-control-allow-origin" not in refused.headers


def test_unexpected_error_hides_the_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def explode(settings: Settings) -> list[CheckResult]:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(service, "run_all_checks", explode)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Something went wrong on the server.",
        }
    }


def test_new_entries_are_off_until_startup_turns_them_on(
    make_settings: Callable[..., Settings],
) -> None:
    assert create_app(make_settings()).state.new_entries_enabled is False
