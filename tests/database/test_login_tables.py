"""The login tables in the real test database (`pytest -m integration`)."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from database.base import Base
from database.models import PasswordResetCode, RefreshToken, User

pytestmark = pytest.mark.integration

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

FAKE_HASH = "test-hash"


def new_user(email: str = "owner@example.test") -> User:
    return User(email=email, password_hash=FAKE_HASH)


async def test_the_migrations_build_exactly_the_tables_in_the_code(
    test_engine: AsyncEngine,
) -> None:
    def differences(connection: Connection) -> list:
        return compare_metadata(MigrationContext.configure(connection), Base.metadata)

    async with test_engine.connect() as connection:
        assert await connection.run_sync(differences) == []


async def test_the_database_is_at_the_latest_migration(
    test_engine: AsyncEngine,
) -> None:
    (head,) = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads()
    async with test_engine.connect() as connection:
        applied = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    assert applied == head


async def test_a_user_is_saved_with_safe_defaults(session: AsyncSession) -> None:
    user = new_user()
    session.add(user)
    await session.commit()

    saved = await session.scalar(select(User).where(User.id == user.id))
    await session.refresh(saved)
    assert isinstance(saved.id, uuid.UUID)
    assert saved.failed_login_count == 0
    assert saved.locked_until is None
    assert saved.created_at.tzinfo is not None
    assert abs(datetime.now(UTC) - saved.created_at) < timedelta(minutes=5)


async def test_a_second_account_is_impossible(session: AsyncSession) -> None:
    # The bot has one owner. Even a different email is refused by the database.
    session.add(new_user("owner@example.test"))
    await session.commit()
    session.add(new_user("stranger@example.test"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_an_email_with_capitals_is_refused(session: AsyncSession) -> None:
    # The login code stores emails in lowercase; the database insists on it.
    session.add(new_user("Owner@Example.Test"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_only_one_unused_reset_code_per_user(session: AsyncSession) -> None:
    user = new_user()
    session.add(user)
    await session.flush()
    user_id = user.id
    later = datetime.now(UTC) + timedelta(minutes=10)
    first = PasswordResetCode(user_id=user_id, code_hash=FAKE_HASH, expires_at=later)
    session.add(first)
    await session.commit()

    session.add(
        PasswordResetCode(user_id=user_id, code_hash=FAKE_HASH, expires_at=later)
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    # Once the first code is used, a new one may be issued.
    first.used_at = datetime.now(UTC)
    session.add(
        PasswordResetCode(user_id=user_id, code_hash=FAKE_HASH, expires_at=later)
    )
    await session.commit()


async def test_deleting_a_user_removes_their_tokens_and_codes(
    session: AsyncSession,
) -> None:
    user = new_user()
    session.add(user)
    await session.flush()
    later = datetime.now(UTC) + timedelta(minutes=10)
    session.add_all(
        [
            RefreshToken(user_id=user.id, token_hash="a" * 64, expires_at=later),
            PasswordResetCode(user_id=user.id, code_hash=FAKE_HASH, expires_at=later),
        ]
    )
    await session.commit()

    await session.delete(user)
    await session.commit()
    tokens = await session.scalar(select(func.count()).select_from(RefreshToken))
    codes = await session.scalar(select(func.count()).select_from(PasswordResetCode))
    assert (tokens, codes) == (0, 0)


async def test_the_same_token_cannot_be_stored_twice(session: AsyncSession) -> None:
    user = new_user()
    session.add(user)
    await session.flush()
    later = datetime.now(UTC) + timedelta(days=7)
    session.add(RefreshToken(user_id=user.id, token_hash="b" * 64, expires_at=later))
    await session.commit()
    session.add(RefreshToken(user_id=user.id, token_hash="b" * 64, expires_at=later))
    with pytest.raises(IntegrityError):
        await session.commit()
