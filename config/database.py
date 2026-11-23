"""Database connection and its health check.

One engine per process, created the first time it is needed. Every connection
uses TLS. Error messages name the problem in plain words and never contain the
password or the connection address.
"""

import asyncio
import logging

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config.settings import Settings

logger = logging.getLogger(__name__)

# Seconds to wait for the database before calling it unreachable. The laptop is
# far from Tokyo, so this is generous.
CONNECT_TIMEOUT_SECONDS = 10

_engine: AsyncEngine | None = None


class DatabaseCheckError(Exception):
    """The database check failed. The message is safe to show the owner."""


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the engine. Nothing connects until the first query."""
    return create_async_engine(
        settings.database_url(),
        pool_pre_ping=True,  # replace a connection the server has dropped
        hide_parameters=True,  # errors never show the values sent with a query
        connect_args={
            "ssl": settings.postgres_sslmode,  # TLS always: require or stricter
            "timeout": CONNECT_TIMEOUT_SECONDS,
        },
    )


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


def describe_failure(exc: BaseException, settings: Settings) -> str:
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
        return f"the database {settings.postgres_db} does not exist"
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
