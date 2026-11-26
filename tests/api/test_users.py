"""`/api/v1/users/me`: success, no token, bad input."""

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import EMAIL, error_code
from tests.conftest import FakeClock

ME = "/api/v1/users/me"


def test_me_returns_the_profile_without_the_password_hash(
    client: TestClient, auth: dict
) -> None:
    response = client.get(ME, headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == EMAIL
    assert body["display_name"] == "Owner"
    assert set(body) == {"id", "email", "display_name", "created_at", "last_login_at"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer made-up-token"},
        {"Authorization": "Basic b3duZXI6cGFzcw=="},
        {"Authorization": "Bearer "},
    ],
)
def test_me_needs_a_valid_token(
    client: TestClient, tokens: dict, headers: dict
) -> None:
    response = client.get(ME, headers=headers)
    assert response.status_code == 401
    assert error_code(response) == "not_authenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_refuses_an_expired_token(
    client: TestClient, auth: dict, fake_clock: FakeClock
) -> None:
    fake_clock.advance(minutes=30)
    assert client.get(ME, headers=auth).status_code == 401


def test_me_refuses_the_refresh_token_in_place_of_the_access_token(
    client: TestClient, tokens: dict
) -> None:
    headers = {"Authorization": f"Bearer {tokens['refresh_token']}"}
    assert client.get(ME, headers=headers).status_code == 401


def test_update_me_changes_the_display_name(client: TestClient, auth: dict) -> None:
    response = client.patch(ME, json={"display_name": "  Manfred  "}, headers=auth)
    assert response.status_code == 200
    assert response.json()["display_name"] == "Manfred"
    assert client.get(ME, headers=auth).json()["display_name"] == "Manfred"


def test_update_me_can_clear_the_display_name(client: TestClient, auth: dict) -> None:
    response = client.patch(ME, json={"display_name": None}, headers=auth)
    assert response.json()["display_name"] is None


def test_update_me_needs_a_token(client: TestClient, registered: dict) -> None:
    assert client.patch(ME, json={"display_name": "x"}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},  # the field is required
        {"display_name": "x" * 101},
        {"display_name": "ok", "email": "other@example.test"},  # email cannot change
    ],
)
def test_update_me_refuses_bad_input(
    client: TestClient, auth: dict, body: dict
) -> None:
    assert client.patch(ME, json=body, headers=auth).status_code == 422
