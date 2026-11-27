"""Database connection and its health check.

One engine per process, created the first time it is needed. Every connection
uses TLS. Error messages name the problem in plain words and never contain the
password or the connection address.
"""

import asyncio
import logging
from dataclasses import dataclass

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from config.settings import Settings

logger = logging.getLogger(__name__)

# Seconds to wait for the database before calling it unreachable. The laptop is
# far from Tokyo, so this is generous.
CONNECT_TIMEOUT_SECONDS = 10

_engine: AsyncEngine | None = None


class DatabaseCheckError(Exception):
    """The database check failed. The message is safe to show the owner."""


def create_engine(
    settings: Settings, database: str | None = None, pooled: bool = True
) -> AsyncEngine:
    """Build the engine. Nothing connects until the first query.

    `database` is this machine's own database unless the test database is
    named (see `Settings.database_url`). Migrations and tests pass
    `pooled=False`: they connect once and must leave nothing open.
    """
    options: dict = {"pool_pre_ping": True} if pooled else {"poolclass": NullPool}
    return create_async_engine(
        settings.database_url(database),
        hide_parameters=True,  # errors never show the values sent with a query
        connect_args={
            "ssl": settings.postgres_sslmode,  # TLS always: require or stricter
            "timeout": CONNECT_TIMEOUT_SECONDS,
        },
        **options,
    )


def name_of_test_database(settings: Settings) -> str:
    """The database integration tests and test migrations may wipe.

    Refuses anything that is not clearly a test database. The development and
    test databases share one user, so this check, not the password, is what
    stops a test from wiping development data.
    """
    name = settings.postgres_test_db
    if settings.is_production:
        raise DatabaseCheckError("the test database is never used in production")
    if not name.lower().endswith("_test"):
        raise DatabaseCheckError("POSTGRES_TEST_DB must be a database ending in _test")
    return name


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Makes sessions: one short conversation with the database each.

    `expire_on_commit=False` keeps a saved row readable after the commit
    without another round trip to Tokyo.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


def get_engine(settings: Settings) -> AsyncEngine:
    """The engine for this process."""
    global _engine
    if _engine is None:
        _engine = create_engine(settings)
        logger.info(
            "database engine created host=%s port=%s database=%s",
            settings.postgres_host,
            settings.postgres_port,
            settings.postgres_db,
        )
    return _engine


async def dispose_engine() -> None:
    """Close every connection. Called when the app stops."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def _error_chain(exc: BaseException) -> list[BaseException]:
    """The error and everything it wraps (SQLAlchemy wraps the driver's errors)."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = getattr(current, "orig", None) or current.__cause__
    return chain


def describe_failure(
    exc: BaseException, settings: Settings, database: str | None = None
) -> str:
    """A plain reason for a failed connection, written by us.

    The driver's own text is never passed on, so nothing from the connection
    address can leak into a message.
    """
    chain = _error_chain(exc)

    def has(*kinds: type[BaseException]) -> bool:
        return any(isinstance(error, kinds) for error in chain)

    if has(
        asyncpg.InvalidPasswordError, asyncpg.InvalidAuthorizationSpecificationError
    ):
        return "the database refused the user name or password"
    if has(asyncpg.InvalidCatalogNameError):
        return f"the database {database or settings.postgres_db} does not exist"
    if has(TimeoutError):
        return "could not reach the managed database (timed out)"
    if has(OSError):
        return "could not reach the managed database (host unreachable)"
    return f"unexpected database error ({type(chain[-1]).__name__})"


async def check_database(settings: Settings) -> str:
    """Run `SELECT 1` over TLS. Returns the database name, or raises."""
    if not settings.database_is_configured:
        raise DatabaseCheckError(
            "not configured (POSTGRES_HOST or POSTGRES_PASSWORD is empty in .env)"
        )
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS + 5):
            async with get_engine(settings).connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - every failure becomes one safe line
        logger.warning("database check failed: %s", type(exc).__name__)
        raise DatabaseCheckError(describe_failure(exc, settings)) from None
    return settings.postgres_db


@dataclass(frozen=True)
class DatabaseFacts:
    """What the database says about itself."""

    name: str
    version: str
    # The migration the tables are at, or None when no migration ever ran.
    applied_migration: str | None


async def read_database_facts(
    settings: Settings, engine: AsyncEngine | None = None
) -> DatabaseFacts:
    """Ask the database its name, its version and its migration. Or raises.

    `engine` is this process's own engine unless a test passes another.
    """
    if not settings.database_is_configured:
        raise DatabaseCheckError(
            "not configured (POSTGRES_HOST or POSTGRES_PASSWORD is empty in .env)"
        )
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS + 5):
            async with (engine or get_engine(settings)).connect() as connection:
                name, version, has_table = (
                    await connection.execute(
                        text(
                            "SELECT current_database(), "
                            "current_setting('server_version'), "
                            "to_regclass('public.alembic_version') IS NOT NULL"
                        )
                    )
                ).one()
                applied = None
                if has_table:
                    applied = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
    except Exception as exc:  # noqa: BLE001 - every failure becomes one safe line
        logger.warning("database facts failed: %s", type(exc).__name__)
        raise DatabaseCheckError(describe_failure(exc, settings)) from None
    return DatabaseFacts(name=name, version=version, applied_migration=applied)
