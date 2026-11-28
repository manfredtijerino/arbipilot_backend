"""One short conversation with the database: every repository sharing one
session, saved together by `commit()`."""

from sqlalchemy.ext.asyncio import AsyncSession

from database.repositories.order_repository import OrderRepository
from database.repositories.paper_repository import PaperRepository
from database.repositories.password_reset_code_repository import (
    PasswordResetCodeRepository,
)
from database.repositories.refresh_token_repository import RefreshTokenRepository
from database.repositories.user_repository import UserRepository


class Store:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.codes = PasswordResetCodeRepository(session)
        self.paper = PaperRepository(session)
        self.orders = OrderRepository(session)

    async def commit(self) -> None:
        """Save everything done so far. Without it, nothing is kept."""
        await self._session.commit()
