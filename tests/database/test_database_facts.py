"""What the real test database says about itself (`pytest -m integration`)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from config.database import read_database_facts
from config.settings import Settings
from database.migrations.head import latest_migration

pytestmark = pytest.mark.integration


async def test_the_database_names_itself_and_its_migration(
    _laptop_settings: Settings, test_engine: AsyncEngine
) -> None:
    facts = await read_database_facts(_laptop_settings, test_engine)
    assert facts.name == _laptop_settings.postgres_test_db
    assert facts.version.split(".")[0].isdigit()
    assert facts.applied_migration == latest_migration()
