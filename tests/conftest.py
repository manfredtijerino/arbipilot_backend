"""Shared test helpers. Tests never read the real `.env`."""

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
