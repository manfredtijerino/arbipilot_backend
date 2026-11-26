"""Password hashes, tokens and reset codes. No database, no network."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from config.settings import Settings
from services import security
from tests.conftest import FAKE_JWT_SECRET

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PASSWORD = "test-password-123"


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


# --- Passwords ---


def test_a_hash_is_not_the_password_and_verifies() -> None:
    hashed = security.hash_password(PASSWORD)
    assert PASSWORD not in hashed
    assert hashed.startswith("$argon2id$")
    assert security.verify_password(hashed, PASSWORD) is True


def test_a_wrong_password_does_not_verify() -> None:
    assert security.verify_password(security.hash_password(PASSWORD), "other") is False


def test_the_same_password_gives_a_different_hash_each_time() -> None:
    assert security.hash_password(PASSWORD) != security.hash_password(PASSWORD)


def test_a_broken_hash_is_a_failed_check_not_a_crash() -> None:
    assert security.verify_password("not-a-hash", PASSWORD) is False


# --- Access tokens ---


def test_an_access_token_names_its_user(settings: Settings) -> None:
    token = security.create_access_token(settings, USER_ID, NOW)
    claims = security.read_access_token(settings, token, NOW + timedelta(minutes=29))
    assert claims.user_id == USER_ID
    assert claims.issued_at == NOW


def test_an_access_token_stops_working_after_30_minutes(settings: Settings) -> None:
    token = security.create_access_token(settings, USER_ID, NOW)
    with pytest.raises(security.InvalidAccessToken):
        security.read_access_token(settings, token, NOW + timedelta(minutes=30))


def test_a_token_signed_with_another_secret_is_refused(
    settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    other = make_settings(jwt_secret="another-secret-of-at-least-32-chars")
    token = security.create_access_token(other, USER_ID, NOW)
    with pytest.raises(security.InvalidAccessToken):
        security.read_access_token(settings, token, NOW)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_is_refused(settings: Settings, token: str) -> None:
    with pytest.raises(security.InvalidAccessToken):
        security.read_access_token(settings, token, NOW)


def test_a_token_with_no_signature_is_refused(settings: Settings) -> None:
    # The classic forgery: declare "no algorithm" and leave the signature off.
    payload = {"sub": str(USER_ID), "type": "access", "iat": 0, "exp": 9999999999}
    forged = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(security.InvalidAccessToken):
        security.read_access_token(settings, forged, NOW)


def test_a_token_of_another_kind_is_refused(settings: Settings) -> None:
    payload = {
        "sub": str(USER_ID),
        "type": "something-else",
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, FAKE_JWT_SECRET, algorithm="HS256")
    with pytest.raises(security.InvalidAccessToken):
        security.read_access_token(settings, token, NOW)


def test_a_token_missing_a_field_is_refused(settings: Settings) -> None:
    payload = {"sub": str(USER_ID), "type": "access", "iat": int(NOW.timestamp())}
    token = jwt.encode(payload, FAKE_JWT_SECRET, algorithm="HS256")
    with pytest.raises(security.InvalidAccessToken):
        security.read_access_token(settings, token, NOW)


# --- Refresh tokens ---


def test_a_refresh_token_is_long_random_and_stored_as_a_hash() -> None:
    token, token_hash = security.new_refresh_token()
    other, _ = security.new_refresh_token()
    assert token != other and len(token) >= 60
    assert len(token_hash) == 64 and token not in token_hash
    assert security.hash_refresh_token(token) == token_hash


# --- Reset codes ---


def test_a_reset_code_is_six_digits() -> None:
    codes = {security.new_reset_code() for _ in range(50)}
    assert all(len(code) == 6 and code.isdigit() for code in codes)
    assert len(codes) > 40  # random, not a constant


def test_a_reset_code_hash_depends_on_the_user_and_the_secret(
    settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    mine = security.hash_reset_code(settings, USER_ID, "493201")
    assert "493201" not in mine
    assert security.reset_code_matches(
        mine, security.hash_reset_code(settings, USER_ID, "493201")
    )
    assert not security.reset_code_matches(
        mine, security.hash_reset_code(settings, USER_ID, "493202")
    )
    assert mine != security.hash_reset_code(settings, uuid.uuid4(), "493201")
    other = make_settings(jwt_secret="another-secret-of-at-least-32-chars")
    assert mine != security.hash_reset_code(other, USER_ID, "493201")


def test_a_reset_code_is_shown_in_two_groups() -> None:
    assert security.format_reset_code("493201") == "493 201"
