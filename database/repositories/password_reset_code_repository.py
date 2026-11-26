"""Queries on the `password_reset_codes` table."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import PasswordResetCode
from database.repositories.errors import DuplicateRow


class PasswordResetCodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_live(self, user_id: uuid.UUID) -> PasswordResetCode | None:
        """The user's unused code, if any. The table allows at most one."""
        return await self._session.scalar(
            select(PasswordResetCode).where(
                PasswordResetCode.user_id == user_id,
                PasswordResetCode.used_at.is_(None),
            )
        )

    async def cancel_live(self, user_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(PasswordResetCode)
            .where(
                PasswordResetCode.user_id == user_id,
                PasswordResetCode.used_at.is_(None),
            )
            .values(used_at=now)
        )

    async def get_latest(self, user_id: uuid.UUID) -> PasswordResetCode | None:
        """The newest code of any state: unused, used or cancelled."""
        return await self._session.scalar(
            select(PasswordResetCode)
            .where(PasswordResetCode.user_id == user_id)
            .order_by(PasswordResetCode.created_at.desc())
            .limit(1)
        )

    async def count_since(self, user_id: uuid.UUID, since: datetime) -> int:
        """How many codes were issued to this user after `since`."""
        return (
            await self._session.scalar(
                select(func.count())
                .select_from(PasswordResetCode)
                .where(
                    PasswordResetCode.user_id == user_id,
                    PasswordResetCode.created_at > since,
                )
            )
            or 0
        )

    async def add(
        self, user_id: uuid.UUID, code_hash: str, expires_at: datetime, now: datetime
    ) -> None:
        """Raises DuplicateRow if the user already has an unused code."""
        self._session.add(
            PasswordResetCode(
                user_id=user_id,
                code_hash=code_hash,
                expires_at=expires_at,
                # The app's clock, the same one the limits are checked against.
                created_at=now,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise DuplicateRow from None

    async def add_attempt(self, code_id: uuid.UUID) -> int:
        """Count one guess and return the new total, in one statement."""
        attempts = await self._session.scalar(
            update(PasswordResetCode)
            .where(PasswordResetCode.id == code_id)
            .values(attempts=PasswordResetCode.attempts + 1)
            .returning(PasswordResetCode.attempts)
        )
        return attempts or 0

    async def mark_used(self, code_id: uuid.UUID, now: datetime) -> bool:
        """Use the code up. False if it was already used."""
        used = await self._session.scalar(
            update(PasswordResetCode)
            .where(PasswordResetCode.id == code_id, PasswordResetCode.used_at.is_(None))
            .values(used_at=now)
            .returning(PasswordResetCode.id)
        )
        return used is not None
