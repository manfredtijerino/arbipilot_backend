"""Shared test helpers. Unit tests never read the real `.env`.

Only the integration tests do (see `tests/database/conftest.py`), and only to
reach the `arbipilot_test` database.
"""

from collections.abc import Callable
from typing import Any

import pytest

from config.settings import Settings

SETTINGS_KEYS = [name.upper() for name in Settings.model_fields]

# Fake, and long enough to pass the minimum-length rule.
FAKE_JWT_SECRET = "test-jwt-secret-for-unit-tests-only"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any real setting from the process so a test only sees its own values."""
    for key in SETTINGS_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Build development settings with fake values; pass keywords to change any."""

    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "development",
            "trading_mode": "shadow",
            "jwt_secret": FAKE_JWT_SECRET,
            "postgres_db": "arbipilot_dev",
            "postgres_test_db": "arbipilot_test",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return build


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real Argon2, with tiny settings so the tests stay fast."""
    from argon2 import PasswordHasher

    from services import security

    monkeypatch.setattr(
        security, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )
    monkeypatch.setattr(security, "_decoy", None)


@pytest.fixture(autouse=True)
def forget_unknown_email_waits() -> None:
    from services import auth_service

    auth_service.unknown_email_waits.clear()


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> "datetime":  # noqa: F821
        return self.now

    def advance(self, **kwargs: float) -> None:
        from datetime import timedelta

        self.now += timedelta(**kwargs)


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    from services import clock

    fake = FakeClock()
    monkeypatch.setattr(clock, "utc_now", fake)
    return fake
