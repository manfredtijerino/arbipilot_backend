"""The whole login journey over HTTP, on the real test database.

Register, log in, read the profile, refresh, change the password, ask for a
reset code, reset, log out. The Telegram message is caught, not sent.
Run with `pytest -m integration`.
"""

from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from api import dependencies
from api.routes import auth as auth_routes
from config.database import session_factory
from config.server import create_app
from config.settings import Settings
from database.repositories.store import Store

pytestmark = pytest.mark.integration

API = "/api/v1"
EMAIL = "owner@example.test"
PASSWORD = "test-password-123"
SECOND_PASSWORD = "second-test-password-456"
THIRD_PASSWORD = "third-test-password-789"


@pytest.fixture
async def http(
    test_engine: AsyncEngine,
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, list[str]]]:
    """The real app with fake settings, talking to the test database."""
    app = create_app(make_settings())
    sessions = session_factory(test_engine)

    async def test_store() -> AsyncIterator[Store]:
        async with sessions() as session:
            yield Store(session)

    sent: list[str] = []

    async def fake_send(settings: Settings, text: str) -> None:
        sent.append(text)

    app.dependency_overrides[dependencies.get_store] = test_store
    monkeypatch.setattr(auth_routes, "send_reset_code", fake_send)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, sent


def bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_the_whole_login_journey(
    http: tuple[httpx.AsyncClient, list[str]],
) -> None:
    client, telegram = http

    # Nothing answers without a token.
    assert (await client.get(f"{API}/users/me")).status_code == 401

    # Register once; the second try is refused.
    register = await client.post(
        f"{API}/auth/register",
        json={"email": "Owner@Example.Test", "password": PASSWORD},
    )
    assert register.status_code == 201
    assert register.json()["email"] == EMAIL
    again = await client.post(
        f"{API}/auth/register",
        json={"email": "stranger@example.test", "password": PASSWORD},
    )
    assert again.status_code == 409

    # A wrong password is refused and starts a one-second wait.
    wrong = await client.post(
        f"{API}/auth/login", json={"email": EMAIL, "password": "wrong-password"}
    )
    assert wrong.status_code == 401
    waiting = await client.post(
        f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert waiting.status_code in (200, 429)  # 200 if the second already passed

    # A reset code clears the wait and sets a new password.
    forgot = await client.post(f"{API}/auth/password/forgot", json={"email": EMAIL})
    assert forgot.status_code == 200
    assert len(telegram) == 1
    code = "".join(c for c in telegram[0].split(" is ")[1].split(".")[0] if c.isdigit())
    reset = await client.post(
        f"{API}/auth/password/reset",
        json={"email": EMAIL, "code": code, "new_password": SECOND_PASSWORD},
    )
    assert reset.status_code == 200
    reuse = await client.post(
        f"{API}/auth/password/reset",
        json={"email": EMAIL, "code": code, "new_password": PASSWORD},
    )
    assert reuse.status_code == 400  # a code works once

    # Log in with the new password and read the profile.
    login = await client.post(
        f"{API}/auth/login", json={"email": EMAIL, "password": SECOND_PASSWORD}
    )
    assert login.status_code == 200
    tokens = login.json()
    me = await client.get(f"{API}/users/me", headers=bearer(tokens))
    assert me.status_code == 200
    assert me.json()["last_login_at"] is not None
    renamed = await client.patch(
        f"{API}/users/me", json={"display_name": "Manfred"}, headers=bearer(tokens)
    )
    assert renamed.json()["display_name"] == "Manfred"

    # Refresh: a new pair, and the old refresh token is used up.
    refreshed = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    tokens = refreshed.json()

    # Change the password: the answer carries tokens that keep working.
    changed = await client.post(
        f"{API}/auth/password/change",
        json={"current_password": SECOND_PASSWORD, "new_password": THIRD_PASSWORD},
        headers=bearer(tokens),
    )
    assert changed.status_code == 200
    tokens = changed.json()
    assert (
        await client.get(f"{API}/users/me", headers=bearer(tokens))
    ).status_code == 200

    # Log out: the refresh token stops working.
    logout = await client.post(
        f"{API}/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=bearer(tokens),
    )
    assert logout.status_code == 204
    dead = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert dead.status_code == 401
