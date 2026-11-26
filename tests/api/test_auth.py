"""`/api/v1/auth`: each endpoint's success, its refusal, and one bad input."""

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import EMAIL, NEW_PASSWORD, PASSWORD, error_code
from tests.conftest import FakeClock
from tests.helpers.memory_store import MemoryStore

AUTH = "/api/v1/auth"


def code_from(text: str) -> str:
    return "".join(ch for ch in text.split(" is ")[1].split(".")[0] if ch.isdigit())


# --- POST /auth/register ---


def test_register_creates_the_owner(client: TestClient, store: MemoryStore) -> None:
    response = client.post(
        f"{AUTH}/register",
        json={"email": "Owner@Example.Test", "password": PASSWORD},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == EMAIL
    assert set(body) == {"id", "email", "display_name", "created_at", "last_login_at"}
    assert "password" not in response.text  # neither the password nor its hash


def test_register_is_refused_once_the_owner_exists(
    client: TestClient, registered: dict
) -> None:
    response = client.post(
        f"{AUTH}/register",
        json={"email": "stranger@example.test", "password": PASSWORD},
    )
    assert response.status_code == 409
    assert error_code(response) == "registration_closed"


@pytest.mark.parametrize(
    "body",
    [
        {"email": EMAIL, "password": "short"},  # under 12 characters
        {"email": "not-an-email", "password": PASSWORD},
        {"email": EMAIL},  # no password
        {"email": EMAIL, "password": PASSWORD, "is_admin": True},  # unknown field
        {"email": EMAIL, "password": "x" * 129},  # over the cap
    ],
)
def test_register_refuses_bad_input_without_echoing_it(
    client: TestClient, body: dict
) -> None:
    response = client.post(f"{AUTH}/register", json=body)
    assert response.status_code == 422
    assert error_code(response) == "invalid_input"
    for value in body.values():
        if isinstance(value, str) and len(value) > 4:
            assert value not in response.text


# --- POST /auth/login ---


def test_login_returns_both_tokens(client: TestClient, registered: dict) -> None:
    response = client.post(f"{AUTH}/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert body["access_token"] and body["refresh_token"]


def test_login_with_a_wrong_password_or_unknown_email_is_401(
    client: TestClient, registered: dict
) -> None:
    wrong = client.post(f"{AUTH}/login", json={"email": EMAIL, "password": "wrong-pw"})
    unknown = client.post(
        f"{AUTH}/login", json={"email": "nobody@example.test", "password": PASSWORD}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert error_code(wrong) == "invalid_credentials"


def test_login_during_a_wait_is_429_with_the_seconds_left(
    client: TestClient, registered: dict
) -> None:
    client.post(f"{AUTH}/login", json={"email": EMAIL, "password": "wrong-pw"})
    response = client.post(f"{AUTH}/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 429
    assert error_code(response) == "too_many_attempts"
    assert response.headers["Retry-After"] == "1"


def test_an_unknown_email_waits_exactly_like_a_real_one(
    client: TestClient, registered: dict
) -> None:
    answers = []
    for email in (EMAIL, "nobody@example.test"):
        body = {"email": email, "password": "wrong-pw"}
        first = client.post(f"{AUTH}/login", json=body)
        second = client.post(f"{AUTH}/login", json=body)
        answers.append(
            (first.status_code, second.status_code, second.headers["Retry-After"])
        )
        assert first.json() != second.json()
    assert answers[0] == answers[1] == (401, 429, "1")


def test_login_refuses_bad_input(client: TestClient) -> None:
    assert client.post(f"{AUTH}/login", json={"email": EMAIL}).status_code == 422


# --- POST /auth/refresh ---


def test_refresh_returns_a_new_pair(client: TestClient, tokens: dict) -> None:
    response = client.post(
        f"{AUTH}/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    assert response.json()["refresh_token"] != tokens["refresh_token"]


def test_refresh_with_a_used_or_unknown_token_is_401(
    client: TestClient, tokens: dict
) -> None:
    body = {"refresh_token": tokens["refresh_token"]}
    client.post(f"{AUTH}/refresh", json=body)
    again = client.post(f"{AUTH}/refresh", json=body)
    unknown = client.post(f"{AUTH}/refresh", json={"refresh_token": "made-up"})
    assert again.status_code == unknown.status_code == 401
    assert error_code(again) == "invalid_refresh_token"


def test_refresh_refuses_bad_input(client: TestClient) -> None:
    assert client.post(f"{AUTH}/refresh", json={}).status_code == 422


# --- POST /auth/logout ---


def test_logout_cancels_the_refresh_token(
    client: TestClient, tokens: dict, auth: dict
) -> None:
    body = {"refresh_token": tokens["refresh_token"]}
    response = client.post(f"{AUTH}/logout", json=body, headers=auth)
    assert response.status_code == 204
    assert response.content == b""
    assert client.post(f"{AUTH}/refresh", json=body).status_code == 401


def test_logout_needs_a_token(client: TestClient, tokens: dict) -> None:
    response = client.post(
        f"{AUTH}/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401
    assert error_code(response) == "not_authenticated"


def test_logout_refuses_bad_input(client: TestClient, auth: dict) -> None:
    assert client.post(f"{AUTH}/logout", json={}, headers=auth).status_code == 422


# --- POST /auth/password/change ---


def test_change_password_returns_new_tokens_and_ends_old_sessions(
    client: TestClient, tokens: dict, auth: dict, fake_clock: FakeClock
) -> None:
    fake_clock.advance(minutes=1)
    response = client.post(
        f"{AUTH}/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=auth,
    )
    assert response.status_code == 200
    new_auth = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get("/api/v1/users/me", headers=new_auth).status_code == 200
    assert client.get("/api/v1/users/me", headers=auth).status_code == 401
    login = client.post(
        f"{AUTH}/login", json={"email": EMAIL, "password": NEW_PASSWORD}
    )
    assert login.status_code == 200


def test_change_password_with_a_wrong_current_password_is_401(
    client: TestClient, auth: dict
) -> None:
    response = client.post(
        f"{AUTH}/password/change",
        json={"current_password": "wrong-pw", "new_password": NEW_PASSWORD},
        headers=auth,
    )
    assert response.status_code == 401
    assert error_code(response) == "invalid_credentials"


def test_change_password_needs_a_token(client: TestClient, registered: dict) -> None:
    response = client.post(
        f"{AUTH}/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401


def test_change_password_refuses_a_short_new_password(
    client: TestClient, auth: dict
) -> None:
    response = client.post(
        f"{AUTH}/password/change",
        json={"current_password": PASSWORD, "new_password": "short"},
        headers=auth,
    )
    assert response.status_code == 422


# --- POST /auth/password/forgot and /auth/password/reset ---


def test_forgot_sends_a_code_to_telegram_and_reset_uses_it(
    client: TestClient, registered: dict, telegram: list[str]
) -> None:
    forgot = client.post(f"{AUTH}/password/forgot", json={"email": EMAIL})
    assert forgot.status_code == 200
    assert len(telegram) == 1
    code = code_from(telegram[0])
    assert code not in forgot.text  # the code travels by Telegram only

    reset = client.post(
        f"{AUTH}/password/reset",
        # Typed the way Telegram shows it, with a space in the middle.
        json={
            "email": EMAIL,
            "code": f"{code[:3]} {code[3:]}",
            "new_password": NEW_PASSWORD,
        },
    )
    assert reset.status_code == 200
    login = client.post(
        f"{AUTH}/login", json={"email": EMAIL, "password": NEW_PASSWORD}
    )
    assert login.status_code == 200


def test_forgot_answers_the_same_for_an_unknown_email_and_sends_nothing(
    client: TestClient, registered: dict, telegram: list[str]
) -> None:
    unknown = client.post(
        f"{AUTH}/password/forgot", json={"email": "nobody@example.test"}
    )
    assert telegram == []
    known = client.post(f"{AUTH}/password/forgot", json={"email": EMAIL})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()


def test_forgot_refuses_bad_input(client: TestClient) -> None:
    response = client.post(f"{AUTH}/password/forgot", json={"email": "nope"})
    assert response.status_code == 422


def test_reset_with_a_wrong_code_is_400(
    client: TestClient, registered: dict, telegram: list[str]
) -> None:
    client.post(f"{AUTH}/password/forgot", json={"email": EMAIL})
    code = code_from(telegram[0])
    wrong = "000000" if code != "000000" else "111111"
    response = client.post(
        f"{AUTH}/password/reset",
        json={"email": EMAIL, "code": wrong, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400
    assert error_code(response) == "invalid_reset_code"


@pytest.mark.parametrize("code", ["12345", "abcdef", "1234567", ""])
def test_reset_refuses_a_code_that_is_not_six_digits(
    client: TestClient, code: str
) -> None:
    response = client.post(
        f"{AUTH}/password/reset",
        json={"email": EMAIL, "code": code, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 422
