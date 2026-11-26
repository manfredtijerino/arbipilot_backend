"""Queries on the `refresh_tokens` table."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import RefreshToken
from database.repositories.errors import DuplicateRow


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, user_id: uuid.UUID, token_hash: str, expires_at: datetime
    ) -> None:
        """Raises DuplicateRow if the same token hash is already stored."""
        self._session.add(
            RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        )
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            raise DuplicateRow from None

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return await self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    async def revoke(self, token_id: uuid.UUID, now: datetime) -> bool:
        """Cancel one token. False if it was already cancelled.

        One statement, so the same token cannot be swapped twice by two
        requests arriving together.
        """
        revoked = await self._session.scalar(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(RefreshToken.id)
        )
        return revoked is not None

    async def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
