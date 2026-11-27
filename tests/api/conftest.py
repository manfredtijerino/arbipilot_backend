"""Shared setup for the API tests: the app on an in-memory store.

No database and no Telegram: the store is `MemoryStore`, and the reset-code
message is caught in a list instead of being sent.
"""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dependencies
from api.routes import auth as auth_routes
from config.server import create_app
from config.settings import Settings
from tests.conftest import FakeClock
from tests.helpers.memory_store import MemoryStore
from tests.helpers.paper import opener

EMAIL = "owner@example.test"
PASSWORD = "test-password-123"
NEW_PASSWORD = "new-test-password-456"


@pytest.fixture
def store(fake_clock: FakeClock) -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every reset-code message the app tried to send."""
    sent: list[str] = []

    async def fake_send(settings: Settings, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(auth_routes, "send_reset_code", fake_send)
    return sent


@pytest.fixture
def app(
    make_settings: Callable[..., Settings], store: MemoryStore, telegram: list[str]
) -> FastAPI:
    app = create_app(make_settings())

    async def memory_store() -> MemoryStore:
        return store

    app.dependency_overrides[dependencies.get_store] = memory_store
    app.state.paper.open_store = opener(store)  # the paper account too
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def registered(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "display_name": "Owner"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def tokens(client: TestClient, registered: dict) -> dict:
    response = client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def auth(tokens: dict) -> dict[str, str]:
    """The header a logged-in request carries."""
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def error_code(response: object) -> str:
    return response.json()["error"]["code"]
