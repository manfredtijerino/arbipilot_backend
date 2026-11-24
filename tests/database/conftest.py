"""Setup for the integration tests. They use the `arbipilot_test` database only.

Run them with `pytest -m integration`. Plain `pytest` skips them.
Never run pytest with `--showlocals` (`-l`): on a connection error it would
print the local variables of the database driver, which include the password.

Three locks keep the tests away from development and production data:
1. The database name comes from `name_of_test_database`, which refuses any
   name that does not end in `_test`.
2. Before a test wipes anything, the database is asked for its own name, and
   the run stops unless that name ends in `_test` too.
3. Tests get only `test_engine` and `session`, both already tied to the test
   database. The laptop's settings (whose default database is the development
   one) stay inside this file.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from config.database import (
    create_engine,
    describe_failure,
    name_of_test_database,
    session_factory,
)
from config.settings import Settings, get_settings
from database import models  # noqa: F401 - registers the tables
from database.base import Base
from database.migrations.safety import MigrationRefused

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


@pytest.fixture(scope="session")
def _laptop_settings() -> Settings:
    """The laptop's real settings. For this file only: do not use it in a test."""
    settings = get_settings()
    if not settings.database_is_configured:
        pytest.skip("the database is not configured in .env")
    return settings


@pytest.fixture(scope="session")
def migrated_test_database(_laptop_settings: Settings) -> str:
    """Apply every migration to the test database, once per test run."""
    name = name_of_test_database(_laptop_settings)
    config = Config(str(ALEMBIC_INI))
    config.attributes.update(
        target="test", settings=_laptop_settings, keep_logging=True
    )
    try:
        command.upgrade(config, "head")
    except MigrationRefused as refusal:
        pytest.exit(f"test database not ready: {refusal}", 1)
    return name


@pytest.fixture
async def test_engine(
    _laptop_settings: Settings, migrated_test_database: str
) -> AsyncIterator[AsyncEngine]:
    """An engine on the test database, with every table emptied first."""
    engine = create_engine(_laptop_settings, database=migrated_test_database)
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    reason = None
    try:
        async with engine.begin() as connection:
            actual = await connection.scalar(text("SELECT current_database()"))
            if not str(actual).endswith("_test"):
                pytest.exit(f"refusing to wipe {actual!r}: not a test database", 1)
            await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    except Exception as exc:  # noqa: BLE001 - one safe line, no driver text
        reason = describe_failure(exc, _laptop_settings, migrated_test_database)
    if reason is not None:
        await engine.dispose()
        pytest.fail(f"could not prepare the test database: {reason}", pytrace=False)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with session_factory(test_engine)() as session:
        yield session
