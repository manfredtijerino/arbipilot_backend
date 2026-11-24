"""Alembic runs this file for every migration command.

It builds the database address from `.env` (through the same settings and
guard rails as the app), connects over TLS, and applies the migration files.

Which database:
- `alembic upgrade head`                -> this machine's own database
  (`arbipilot_dev` on the laptop, `arbipilot_prod` on the server)
- `alembic -x target=test upgrade head` -> the test database, laptop only
No other database can be named. The rules are in `safety.py`.
"""

import asyncio
import logging
from functools import partial

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection

from config.database import create_engine, describe_failure
from config.environment import check_guard_rails
from config.logging import setup_logging
from config.settings import Settings, get_settings
from database import models  # noqa: F401 - registers every table on Base.metadata
from database.base import Base
from database.migrations.safety import (
    MigrationRefused,
    choose_database,
    confirm_connected_database,
    refuse_production_downgrade,
)

logger = logging.getLogger("database.migrations")

config = context.config
target_metadata = Base.metadata

# Set when a command was typed in a terminal; absent when tests call Alembic.
command_line = getattr(config, "cmd_opts", None)


def command_name() -> str | None:
    command = getattr(command_line, "cmd", None)
    return command[0].__name__ if command else None


def run_migrations(database: str, connection: Connection) -> None:
    actual = connection.execute(text("SELECT current_database()")).scalar()
    confirm_connected_database(database, actual)
    # End the read above, so Alembic opens (and commits) its own transaction.
    # Without this the migration would run inside the read's transaction and
    # be thrown away when the connection closes.
    connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # The integration tests pass their settings in; the command line reads .env.
    settings: Settings = config.attributes.get("settings") or get_settings()
    check_guard_rails(settings)  # whichever way the settings arrived
    if not config.attributes.get("keep_logging"):
        setup_logging(settings)  # the project's format, with secrets hidden
    refuse_production_downgrade(settings, command_name())
    database = choose_database(
        settings,
        context.get_x_argument(as_dictionary=True),
        config.attributes.get("target"),
    )
    logger.info(
        "migrating host=%s port=%s database=%s",
        settings.postgres_host,
        settings.postgres_port,
        database,
    )
    engine = create_engine(settings, database=database, pooled=False)
    try:
        try:
            connection = await engine.connect()
        except Exception as exc:  # noqa: BLE001 - one safe line, no driver text
            reason = describe_failure(exc, settings, database)
            raise MigrationRefused(f"Could not connect: {reason}") from None
        try:
            await connection.run_sync(partial(run_migrations, database))
        finally:
            await connection.close()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    # Offline mode prints SQL instead of running it. Tables here are changed
    # only by running migrations, so it is switched off.
    raise SystemExit("Offline mode (--sql) is not used in this project.")

try:
    asyncio.run(run_async_migrations())
except MigrationRefused as refusal:
    if command_line is None:
        raise  # called from code (the tests): let the caller see it
    raise SystemExit(f"✖ Migration refused: {refusal}") from None
