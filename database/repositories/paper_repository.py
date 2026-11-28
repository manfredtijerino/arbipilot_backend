"""Queries for the paper account: the wallet, what is held, the fills, and
the risk engine's saved memory. Nothing here decides anything."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import PaperAccount, PaperFill, PaperPosition, RiskStateRow

LONGEST_PAUSE_REASON = 200


class PaperRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- the wallet ---

    async def get_account(self, lock: bool = False) -> PaperAccount | None:
        """The wallet row. `lock` holds it until the commit, so two orders
        can never both spend the same cash."""
        query = select(PaperAccount).where(PaperAccount.id == 1)
        if lock:
            query = query.with_for_update()
        return (await self._session.execute(query)).scalar_one_or_none()

    async def create_account(self, cash: Decimal, now: datetime) -> PaperAccount:
        account = PaperAccount(id=1, cash=cash, created_at=now, updated_at=now)
        self._session.add(account)
        await self._session.flush()
        return account

    async def set_cash(self, cash: Decimal, now: datetime) -> None:
        account = await self.get_account(lock=True)
        if account is None:
            raise LookupError("the paper account does not exist")
        account.cash, account.updated_at = cash, now
        await self._session.flush()

    # --- what is held ---

    async def positions(self) -> list[PaperPosition]:
        query = select(PaperPosition).order_by(PaperPosition.symbol)
        return list((await self._session.execute(query)).scalars())

    async def save_position(
        self, symbol: str, quantity: Decimal, cost: Decimal, now: datetime
    ) -> None:
        """Write what is now held of one pair. Nothing held removes the row."""
        position = await self._session.get(PaperPosition, symbol)
        if quantity <= 0:
            await self._session.execute(
                delete(PaperPosition).where(PaperPosition.symbol == symbol)
            )
        elif position is None:
            self._session.add(
                PaperPosition(
                    symbol=symbol,
                    quantity=quantity,
                    cost=cost,
                    opened_at=now,
                    updated_at=now,
                )
            )
        else:
            position.quantity, position.cost, position.updated_at = quantity, cost, now
        await self._session.flush()

    # --- the fills ---

    async def add_fill(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        notional: Decimal,
        fee: Decimal,
        realized_pnl: Decimal | None,
        cash_after: Decimal,
        risk_outcome: str,
        risk_code: str,
        now: datetime,
    ) -> PaperFill:
        fill = PaperFill(
            id=uuid.uuid4(),
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            notional=notional,
            fee=fee,
            realized_pnl=realized_pnl,
            cash_after=cash_after,
            risk_outcome=risk_outcome,
            risk_code=risk_code,
            created_at=now,
        )
        self._session.add(fill)
        await self._session.flush()
        return fill

    async def fill_by_id(self, fill_id: uuid.UUID) -> PaperFill | None:
        return await self._session.get(PaperFill, fill_id)

    async def fills(self, limit: int, offset: int = 0) -> list[PaperFill]:
        """The newest fills first."""
        query = (
            select(PaperFill)
            .order_by(PaperFill.created_at.desc(), PaperFill.id)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(query)).scalars())

    # --- the risk engine's memory ---

    async def get_risk_state(self) -> RiskStateRow | None:
        return await self._session.get(RiskStateRow, 1)

    async def save_risk_state(
        self,
        day: date | None,
        day_start_equity: Decimal,
        daily_pause: bool,
        outside_pause: str,
        now: datetime,
    ) -> None:
        row = await self._session.get(RiskStateRow, 1)
        if row is None:
            row = RiskStateRow(id=1)
            self._session.add(row)
        row.day, row.day_start_equity = day, day_start_equity
        row.daily_pause = daily_pause
        row.outside_pause = outside_pause[:LONGEST_PAUSE_REASON]
        row.updated_at = now
        await self._session.flush()
