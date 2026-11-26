"""The login queries against the real test database (`pytest -m integration`).

The in-memory store used by the unit tests copies these rules; this file
proves the real SQL follows them. Few tests, many checks each: every question
to the database travels to Tokyo and back.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from config.database import session_factory
from database.models import User
from database.repositories.errors import DuplicateRow
from database.repositories.store import Store

pytestmark = pytest.mark.integration

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FAKE_HASH = "test-hash"


async def saved_user(store: Store) -> User:
    user = User(email="owner@example.test", password_hash=FAKE_HASH)
    await store.users.add(user)
    await store.commit()
    return user


async def fresh(store: Store, user_id: uuid.UUID, session: AsyncSession) -> User:
    """Read the row again from the database, not from the session's memory."""
    session.expire_all()
    return await store.users.get_by_id(user_id)


async def test_users_queries(session: AsyncSession) -> None:
    store = Store(session)
    assert await store.users.count() == 0
    user_id = (await saved_user(store)).id
    assert await store.users.count() == 1
    assert (await store.users.get_by_email("owner@example.test")).id == user_id
    assert await store.users.get_by_email("nobody@example.test") is None

    # A second account is refused, and the session still works afterwards.
    with pytest.raises(DuplicateRow):
        await store.users.add(User(email="other@example.test", password_hash=FAKE_HASH))
    assert await store.users.count() == 1

    # Wrong passwords: the wait doubles, 1 s, 2 s, 4 s.
    waits = []
    for _ in range(3):
        await store.users.record_failed_login(user_id, NOW, 900)
        await store.commit()
        row = await fresh(store, user_id, session)
        waits.append((row.locked_until - NOW).total_seconds())
    assert waits == [1, 2, 4]
    assert row.failed_login_count == 3

    # The wait never passes the cap (here 3 s), however many failures.
    await store.users.record_failed_login(user_id, NOW, 3)
    await store.commit()
    row = await fresh(store, user_id, session)
    assert row.locked_until - NOW == timedelta(seconds=3)

    await store.users.record_successful_login(user_id, NOW)
    await store.commit()
    row = await fresh(store, user_id, session)
    assert (row.failed_login_count, row.locked_until) == (0, None)
    assert row.last_login_at == NOW

    await store.users.record_failed_login(user_id, NOW, 900)
    await store.users.set_password(user_id, "new-test-hash", NOW)
    updated = await store.users.set_display_name(user_id, "Manfred")
    await store.commit()
    assert updated.display_name == "Manfred"
    row = await fresh(store, user_id, session)
    assert row.password_hash == "new-test-hash"
    assert row.password_changed_at == NOW
    assert (row.failed_login_count, row.locked_until) == (0, None)
    assert row.updated_at >= row.created_at


async def test_refresh_token_queries(session: AsyncSession) -> None:
    store = Store(session)
    user = await saved_user(store)
    later = NOW + timedelta(days=7)
    await store.tokens.add(user.id, "a" * 64, later)
    await store.tokens.add(user.id, "b" * 64, later)
    await store.commit()

    first = await store.tokens.get_by_hash("a" * 64)
    assert first.user_id == user.id and first.revoked_at is None
    assert await store.tokens.get_by_hash("c" * 64) is None

    # A token can be cancelled once; the second try reports "already done".
    assert await store.tokens.revoke(first.id, NOW) is True
    assert await store.tokens.revoke(first.id, NOW) is False

    await store.tokens.revoke_all_for_user(user.id, NOW)
    await store.commit()
    session.expire_all()
    second = await store.tokens.get_by_hash("b" * 64)
    assert second.revoked_at == NOW


async def test_reset_code_queries(session: AsyncSession) -> None:
    store = Store(session)
    user_id = (await saved_user(store)).id
    later = NOW + timedelta(minutes=10)
    assert await store.codes.get_live(user_id) is None

    await store.codes.add(user_id, FAKE_HASH, later, NOW)
    await store.commit()
    live = await store.codes.get_live(user_id)
    assert live.attempts == 0 and live.created_at.tzinfo is not None

    # Guesses are counted one by one, by the database.
    assert await store.codes.add_attempt(live.id) == 1
    assert await store.codes.add_attempt(live.id) == 2

    # A code is used up once.
    assert await store.codes.mark_used(live.id, NOW) is True
    assert await store.codes.mark_used(live.id, NOW) is False
    assert await store.codes.get_live(user_id) is None

    # With the old one used, a new one may be issued. Both are counted, and
    # the newest is found whatever its state.
    await store.codes.add(user_id, FAKE_HASH, later, NOW + timedelta(minutes=2))
    await store.commit()
    assert await store.codes.count_since(user_id, NOW - timedelta(seconds=1)) == 2
    assert await store.codes.count_since(user_id, NOW + timedelta(minutes=1)) == 1
    assert (await store.codes.get_latest(user_id)).created_at == NOW + timedelta(
        minutes=2
    )

    # A second unused code is refused without the database's own error text.
    with pytest.raises(DuplicateRow):
        await store.codes.add(user_id, FAKE_HASH, later, NOW + timedelta(minutes=3))

    await store.codes.cancel_live(user_id, NOW)
    await store.commit()
    assert await store.codes.get_live(user_id) is None
    assert (await store.codes.get_latest(user_id)).used_at == NOW


async def test_locking_the_user_makes_a_second_request_wait(
    test_engine: AsyncEngine,
) -> None:
    """The lock behind "login operations happen one after the other" is real.

    One session locks the owner's row. A second session asking for the same
    lock must wait; here it gives up after half a second, which proves it was
    made to wait. Once the first session commits, the second gets the row.
    """
    sessions = session_factory(test_engine)
    async with sessions() as first, sessions() as second:
        user_id = (await saved_user(Store(first))).id
        assert await Store(first).users.get_by_id(user_id, lock=True) is not None

        await second.execute(text("SET lock_timeout = '500ms'"))
        with pytest.raises(DBAPIError):
            await Store(second).users.get_by_id(user_id, lock=True)
        await second.rollback()

        await first.commit()  # lets go of the lock
        assert await Store(second).users.get_by_id(user_id, lock=True) is not None
        await second.commit()
