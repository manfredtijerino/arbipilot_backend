"""Queries on the `users` table."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from database.repositories.errors import DuplicateRow

# 2 to the power of this is far above any wait we use; it only stops the
# arithmetic from overflowing after a very long run of failures.
LARGEST_EXPONENT = 20


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count(self) -> int:
        return await self._session.scalar(select(func.count()).select_from(User)) or 0

    async def _one(self, condition: object, lock: bool) -> User | None:
        query = select(User).where(condition)
        if lock:
            # FOR UPDATE: any other request wanting this row waits until this
            # one commits. populate_existing: read the row fresh, never from
            # the session's memory.
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self._session.scalar(query)

    async def get_by_id(self, user_id: uuid.UUID, lock: bool = False) -> User | None:
        """`lock=True` makes every other login operation on this user wait
        until this one commits, so they happen one after the other."""
        return await self._one(User.id == user_id, lock)

    async def get_by_email(self, email: str, lock: bool = False) -> User | None:
        """`email` must already be in lowercase (the table only holds lowercase)."""
        return await self._one(User.email == email, lock)

    async def add(self, user: User) -> None:
        """Save a new user. Raises DuplicateRow if an account already exists."""
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise DuplicateRow from None

    async def record_failed_login(
        self, user_id: uuid.UUID, now: datetime, longest_wait_seconds: int
    ) -> None:
        """Count one wrong password and set the wait before the next try.

        One statement, so two wrong guesses arriving together are both counted.
        The wait doubles each time: 1 s, 2 s, 4 s ... up to the longest wait.
        (Inside an UPDATE the right-hand side sees the count before the +1.)
        """
        exponent = func.least(User.failed_login_count, LARGEST_EXPONENT)
        wait_seconds = func.least(func.power(2, exponent), longest_wait_seconds)
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                failed_login_count=User.failed_login_count + 1,
                locked_until=now + func.make_interval(0, 0, 0, 0, 0, 0, wait_seconds),
            )
        )

    async def record_successful_login(self, user_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(failed_login_count=0, locked_until=None, last_login_at=now)
        )

    async def set_password(
        self, user_id: uuid.UUID, password_hash: str, now: datetime
    ) -> None:
        """Store a new hash, note when it changed, and clear any wait."""
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                password_hash=password_hash,
                password_changed_at=now,
                failed_login_count=0,
                locked_until=None,
            )
        )

    async def upgrade_password_hash(
        self, user_id: uuid.UUID, password_hash: str
    ) -> None:
        """Replace the hash of the same password with a stronger one."""
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    async def set_display_name(
        self, user_id: uuid.UUID, display_name: str | None
    ) -> User | None:
        return await self._session.scalar(
            update(User)
            .where(User.id == user_id)
            .values(display_name=display_name)
            .returning(User)
            .execution_options(populate_existing=True)
        )
