from datetime import date

import pytest

from config.environment import GuardRailError, check_guard_rails, message_prefix

TODAY = date(2026, 11, 12)


# --- development ---


@pytest.mark.parametrize("mode", ["shadow", "testnet"])
def test_development_allows_shadow_and_testnet(make_settings, mode):
    check_guard_rails(make_settings(trading_mode=mode), today=TODAY)


def test_development_refuses_live(make_settings):
    settings = make_settings(trading_mode="live", live_confirm="2026-11-12")
    with pytest.raises(GuardRailError, match="live mode is not allowed in development"):
        check_guard_rails(settings, today=TODAY)


def test_development_refuses_a_production_database(make_settings):
    with pytest.raises(GuardRailError, match="_prod"):
        check_guard_rails(make_settings(postgres_db="arbipilot_prod"), today=TODAY)


def test_development_allows_a_name_that_only_contains_prod(make_settings):
    # Boundary: the rule is about the ending, not the word anywhere in the name.
    check_guard_rails(make_settings(postgres_db="prod_copy_dev"), today=TODAY)


@pytest.mark.parametrize(
    "key",
    [
        "binance_api_key",
        "binance_api_secret",
        "binance_read_key",
        "binance_read_secret",
    ],
)
def test_development_refuses_mainnet_keys(make_settings, key):
    settings = make_settings(**{key: "test-key"})
    with pytest.raises(GuardRailError) as error:
        check_guard_rails(settings, today=TODAY)
    assert key.upper() in str(error.value)
    assert "test-key" not in str(error.value)


def test_development_allows_the_testnet_key(make_settings):
    settings = make_settings(
        binance_testnet_key="test-key", binance_testnet_secret="test-secret"
    )
    check_guard_rails(settings, today=TODAY)


def test_test_database_must_end_in_test(make_settings):
    with pytest.raises(GuardRailError, match="_test"):
        check_guard_rails(make_settings(postgres_test_db="arbipilot_dev"), today=TODAY)


# --- production ---


def production(make_settings, **overrides):
    values = {
        "app_env": "production",
        "postgres_db": "arbipilot_prod",
        "postgres_test_db": "",
        "binance_api_key": "test-key",
        "binance_api_secret": "test-secret",
    }
    values.update(overrides)
    return make_settings(**values)


def test_production_allows_shadow_with_mainnet_keys(make_settings):
    check_guard_rails(production(make_settings), today=TODAY)


@pytest.mark.parametrize("database", ["arbipilot_dev", "arbipilot_test"])
def test_production_refuses_dev_and_test_databases(make_settings, database):
    with pytest.raises(GuardRailError, match="production must not use"):
        check_guard_rails(production(make_settings, postgres_db=database), today=TODAY)


def test_production_refuses_a_test_database_setting(make_settings):
    settings = production(make_settings, postgres_test_db="arbipilot_test")
    with pytest.raises(GuardRailError, match="POSTGRES_TEST_DB"):
        check_guard_rails(settings, today=TODAY)


# --- live mode ---


def test_live_starts_only_with_todays_date(make_settings):
    settings = production(make_settings, trading_mode="live", live_confirm="2026-11-12")
    check_guard_rails(settings, today=TODAY)


@pytest.mark.parametrize("confirm", ["", "2026-11-11", "2026-11-13", "yes"])
def test_live_refuses_a_missing_or_wrong_date(make_settings, confirm):
    settings = production(make_settings, trading_mode="live", live_confirm=confirm)
    with pytest.raises(GuardRailError, match="LIVE_CONFIRM"):
        check_guard_rails(settings, today=TODAY)


def test_live_accepts_a_date_padded_with_spaces(make_settings):
    settings = production(
        make_settings, trading_mode="live", live_confirm=" 2026-11-12 "
    )
    check_guard_rails(settings, today=TODAY)


@pytest.mark.parametrize("missing", ["binance_api_key", "binance_api_secret"])
def test_live_refuses_to_start_without_the_trade_key(make_settings, missing):
    settings = production(
        make_settings,
        trading_mode="live",
        live_confirm="2026-11-12",
        **{missing: ""},
    )
    with pytest.raises(GuardRailError, match="BINANCE_API_KEY"):
        check_guard_rails(settings, today=TODAY)


# --- database names: empty, upper case, padded ---


@pytest.mark.parametrize("database", ["", "postgres", "arbipilot"])
def test_development_refuses_an_empty_or_unexpected_database(make_settings, database):
    with pytest.raises(GuardRailError, match="ending in _dev"):
        check_guard_rails(make_settings(postgres_db=database), today=TODAY)


@pytest.mark.parametrize("database", ["ARBIPILOT_PROD", " arbipilot_prod ", "X_Prod"])
def test_development_refuses_production_names_in_any_case(make_settings, database):
    with pytest.raises(GuardRailError, match="_prod"):
        check_guard_rails(make_settings(postgres_db=database), today=TODAY)


@pytest.mark.parametrize("database", ["", "postgres", "arbipilot"])
def test_production_refuses_an_empty_or_unexpected_database(make_settings, database):
    with pytest.raises(GuardRailError, match="ending in _prod"):
        check_guard_rails(production(make_settings, postgres_db=database), today=TODAY)


@pytest.mark.parametrize("database", ["ARBIPILOT_DEV", " arbipilot_test "])
def test_production_refuses_dev_and_test_names_in_any_case(make_settings, database):
    with pytest.raises(GuardRailError, match="production must not use"):
        check_guard_rails(production(make_settings, postgres_db=database), today=TODAY)


def test_a_mainnet_key_of_only_spaces_counts_as_empty(make_settings):
    check_guard_rails(make_settings(binance_api_key="   "), today=TODAY)


# --- the [DEV] prefix ---


def test_dev_prefix_only_in_development(make_settings):
    assert message_prefix(make_settings()) == "[DEV] "
    assert message_prefix(production(make_settings)) == ""
