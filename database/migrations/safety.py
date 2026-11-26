"""The safety rules for running migrations, kept apart so they can be tested.

`env.py` (which Alembic runs) calls these before it connects to anything.
"""

from collections.abc import Mapping

from config.database import DatabaseCheckError, name_of_test_database
from config.settings import Settings

TEST_TARGET = "test"
ALLOWED_OPTIONS = {"target"}


class MigrationRefused(Exception):
    """This migration run is not allowed. The message is safe to show."""


def choose_database(
    settings: Settings, options: Mapping[str, str], preset_target: str | None = None
) -> str:
    """Which database this run migrates.

    No option: this machine's own database. `-x target=test`: the test
    database. Anything else is refused, including a misspelled option name,
    which would otherwise fall back to the machine's own database without a word.
    """
    unknown = set(options) - ALLOWED_OPTIONS
    if unknown:
        raise MigrationRefused(
            'Unknown -x option. The only one allowed is "-x target=test".'
        )
    target = preset_target if preset_target is not None else options.get("target")
    if target is None:
        return settings.postgres_db
    if target != TEST_TARGET:
        raise MigrationRefused(
            'Unknown target. The only one allowed is "-x target=test".'
        )
    try:
        return name_of_test_database(settings)
    except DatabaseCheckError as exc:
        raise MigrationRefused(str(exc)) from None


def refuse_production_downgrade(settings: Settings, command: str | None) -> None:
    """A downgrade deletes tables. On the server that would delete real records."""
    if settings.is_production and command == "downgrade":
        raise MigrationRefused(
            "Downgrades are not run in production. Take a snapshot and write a "
            "new migration instead."
        )


def confirm_connected_database(expected: str, actual: object) -> None:
    """Stop unless the database we reached is the one we chose."""
    if actual != expected:
        raise MigrationRefused(
            f"Connected to {actual!r} but meant to migrate {expected!r}. Nothing ran."
        )
