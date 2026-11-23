from decimal import Decimal

import pytest

import config.settings as settings_module
from config.environment import GuardRailError
from config.settings import (
    UNRECOGNISED,
    SettingsError,
    get_settings,
    is_set,
    load_settings,
    safe_key_name,
)
from tests.conftest import FAKE_JWT_SECRET

BASE = {
    "app_env": "development",
    "trading_mode": "shadow",
    "jwt_secret": FAKE_JWT_SECRET,
}


def test_valid_settings_load(make_settings):
    settings = make_settings()
    assert settings.app_env == "development"
    assert settings.is_development and not settings.is_production
    assert settings.port == 3000
    assert settings.postgres_sslmode == "require"


def test_fees_are_exact_decimals(make_settings):
    settings = make_settings()
    assert settings.fee_maker == Decimal("0.00075")
    assert settings.fee_taker == Decimal("0.00075")
    assert isinstance(settings.fee_maker, Decimal)


def test_missing_required_key_is_named():
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=None, app_env="development", trading_mode="shadow")
    assert "JWT_SECRET" in str(error.value)


def test_invalid_value_is_reported_without_showing_it():
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=None, **{**BASE, "app_env": "staging-typo"})
    message = str(error.value)
    assert "APP_ENV" in message
    assert "staging-typo" not in message


def test_invalid_number_is_reported_without_showing_it():
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=None, **BASE, port="not-a-number-hunter2")
    assert "PORT" in str(error.value)
    assert "hunter2" not in str(error.value)


# --- JWT_SECRET length ---


def test_jwt_secret_at_the_minimum_length_is_accepted():
    load_settings(_env_file=None, **{**BASE, "jwt_secret": "x" * 32})


@pytest.mark.parametrize("secret", ["", "short-test-value", "x" * 31])
def test_short_or_empty_jwt_secret_is_refused_without_showing_it(secret):
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=None, **{**BASE, "jwt_secret": secret})
    assert "JWT_SECRET" in str(error.value)
    if secret:
        assert secret not in str(error.value)


# --- FRONTEND_ORIGINS ---


def test_frontend_origins_become_a_list(make_settings):
    assert make_settings().frontend_origin_list == []
    settings = make_settings(
        frontend_origins="http://localhost:5173, https://example.test"
    )
    assert settings.frontend_origin_list == [
        "http://localhost:5173",
        "https://example.test",
    ]


@pytest.mark.parametrize("origins", ["*", "http://localhost:5173,*"])
def test_wildcard_frontend_origin_is_refused(origins):
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=None, **BASE, frontend_origins=origins)
    assert "FRONTEND_ORIGINS" in str(error.value)


# --- the .env file ---


def env_file(tmp_path, extra: str = ""):
    path = tmp_path / ".env"
    path.write_text(
        "APP_ENV=development\nTRADING_MODE=shadow\n"
        f"JWT_SECRET={FAKE_JWT_SECRET}\nPOSTGRES_DB=arbipilot_dev\n{extra}"
    )
    return path


def test_misspelled_key_stops_loading_and_is_named(tmp_path):
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=env_file(tmp_path, "JWT_SECRT=oops-test-value\n"))
    assert "JWT_SECRT" in str(error.value)
    assert "oops-test-value" not in str(error.value)


def test_a_value_pasted_as_a_key_is_never_echoed(tmp_path):
    # A line ending in "=" is read as a key; its text must not reach the error.
    line = "wrapped-test-value/with+odd:chars==\n"
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=env_file(tmp_path, line))
    message = str(error.value)
    assert "wrapped-test-value" not in message.lower()
    assert UNRECOGNISED in message


def test_a_line_without_equals_is_ignored_by_the_loader(tmp_path):
    # The settings loader skips it (scripts/env_status.py flags it instead).
    line = "pasted-test-value-on-its-own-line-0123456789\n"
    settings = load_settings(_env_file=env_file(tmp_path, line))
    assert settings.postgres_db == "arbipilot_dev"


def test_safe_key_name():
    assert safe_key_name("jwt_secret") == "JWT_SECRET"
    assert safe_key_name("POSTGRES_DB") == "POSTGRES_DB"
    assert safe_key_name("JWT_SECRT") == "JWT_SECRT"  # a typo of a real key
    assert safe_key_name("abc-def-123") == UNRECOGNISED
    assert safe_key_name("x" * 60) == UNRECOGNISED
    assert safe_key_name("") == UNRECOGNISED


@pytest.mark.parametrize(
    "pasted",
    [
        "abcdef0123456789abcdef0123456789abcdef01",  # 40-character hex
        "Testpassword123",
        "ANOTHERTESTVALUE",
    ],
)
def test_a_secret_that_looks_like_a_key_name_is_not_echoed(pasted):
    assert safe_key_name(pasted) == UNRECOGNISED


@pytest.mark.parametrize(
    "name", ["arbipilot_prod?options=x_dev", "arbipilot_prod#_dev", "a b_dev"]
)
def test_database_names_allow_only_plain_characters(name):
    with pytest.raises(SettingsError) as error:
        load_settings(_env_file=None, **BASE, postgres_db=name)
    assert "POSTGRES_DB" in str(error.value)
    assert "options" not in str(error.value)


def test_database_names_are_stripped(make_settings):
    assert make_settings(postgres_db="  arbipilot_dev ").postgres_db == "arbipilot_dev"


# --- secrets stay hidden ---


def test_secrets_are_hidden_when_settings_are_printed(make_settings):
    settings = make_settings(postgres_password="test-pass-visible")
    shown = repr(settings) + str(settings)
    assert FAKE_JWT_SECRET not in shown
    assert "test-pass-visible" not in shown


def test_is_set(make_settings):
    settings = make_settings(binance_testnet_key="test-key", postgres_host="  ")
    assert is_set(settings.binance_testnet_key)
    assert not is_set(settings.binance_api_key)
    assert not is_set(settings.postgres_host)


# --- get_settings always applies the guard rails ---


def test_get_settings_runs_the_guard_rails(monkeypatch, make_settings):
    get_settings.cache_clear()
    monkeypatch.setattr(
        settings_module,
        "load_settings",
        lambda: make_settings(postgres_db="arbipilot_prod"),
    )
    with pytest.raises(GuardRailError):
        get_settings()
    get_settings.cache_clear()


def test_get_settings_returns_valid_settings(monkeypatch, make_settings):
    get_settings.cache_clear()
    monkeypatch.setattr(settings_module, "load_settings", lambda: make_settings())
    assert get_settings().postgres_db == "arbipilot_dev"
    get_settings.cache_clear()
