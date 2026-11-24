"""Which database a migration run may touch. No database is contacted."""

from collections.abc import Callable

import pytest

from config.settings import Settings
from database.migrations.safety import (
    MigrationRefused,
    choose_database,
    confirm_connected_database,
    refuse_production_downgrade,
)


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


def test_no_option_means_this_machines_own_database(settings: Settings) -> None:
    assert choose_database(settings, {}) == "arbipilot_dev"


def test_target_test_means_the_test_database(settings: Settings) -> None:
    assert choose_database(settings, {"target": "test"}) == "arbipilot_test"
    assert choose_database(settings, {}, preset_target="test") == "arbipilot_test"


@pytest.mark.parametrize("value", ["tset", "", "prod", "arbipilot_prod", "dev"])
def test_a_wrong_target_value_is_refused(settings: Settings, value: str) -> None:
    with pytest.raises(MigrationRefused, match="Unknown target"):
        choose_database(settings, {"target": value})


@pytest.mark.parametrize("key", ["targt", "Target", "db", "database"])
def test_a_misspelled_option_never_falls_back_to_the_main_database(
    settings: Settings, key: str
) -> None:
    with pytest.raises(MigrationRefused, match="Unknown -x option"):
        choose_database(settings, {key: "test"})


def test_the_test_target_needs_a_database_ending_in_test(settings: Settings) -> None:
    wrong = settings.model_copy(update={"postgres_test_db": "arbipilot_dev"})
    with pytest.raises(MigrationRefused, match="ending in _test"):
        choose_database(wrong, {"target": "test"})


def test_the_test_target_is_refused_in_production(settings: Settings) -> None:
    production = settings.model_copy(update={"app_env": "production"})
    with pytest.raises(MigrationRefused, match="never used in production"):
        choose_database(production, {"target": "test"})


def test_production_refuses_a_downgrade(settings: Settings) -> None:
    production = settings.model_copy(update={"app_env": "production"})
    with pytest.raises(MigrationRefused, match="not run in production"):
        refuse_production_downgrade(production, "downgrade")
    refuse_production_downgrade(production, "upgrade")  # allowed
    refuse_production_downgrade(settings, "downgrade")  # development may


def test_a_different_database_than_the_chosen_one_stops_the_run() -> None:
    confirm_connected_database("arbipilot_test", "arbipilot_test")
    with pytest.raises(MigrationRefused, match="Nothing ran"):
        confirm_connected_database("arbipilot_test", "arbipilot_dev")


def test_settings_cannot_be_changed_after_they_are_loaded(settings: Settings) -> None:
    with pytest.raises(Exception, match="frozen"):
        settings.postgres_db = "arbipilot_prod"
