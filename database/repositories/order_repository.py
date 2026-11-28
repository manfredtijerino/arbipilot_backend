"""Queries for the order diary. Nothing here decides anything."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Order
from database.repositories.errors import DuplicateRow

UNIQUE_VIOLATION = "23505"  # PostgreSQL's code for "must be unique"


def _sqlstate(exc: IntegrityError) -> str | None:
    original = exc.orig
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_client_order_id(self, client_order_id: str) -> Order | None:
        query = select(Order).where(Order.client_order_id == client_order_id)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def add(
        self,
        *,
        client_order_id: str,
        mode: str,
        symbol: str,
        side: str,
        requested_quantity: Decimal | None,
        requested_amount: Decimal | None,
        status: str,
        risk_outcome: str,
        risk_code: str,
        risk_reason: str,
        quantity: Decimal | None,
        price: Decimal | None,
        fill_id: uuid.UUID | None,
        now: datetime,
    ) -> Order:
        order = Order(
            id=uuid.uuid4(),
            client_order_id=client_order_id,
            mode=mode,
            symbol=symbol,
            side=side,
            requested_quantity=requested_quantity,
            requested_amount=requested_amount,
            status=status,
            risk_outcome=risk_outcome,
            risk_code=risk_code,
            risk_reason=risk_reason,
            quantity=quantity,
            price=price,
            fill_id=fill_id,
            created_at=now,
        )
        self._session.add(order)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if _sqlstate(exc) != UNIQUE_VIOLATION:
                raise  # another rule was broken: that is not a repeat
            # The ticket number exists already. The driver's text is not kept.
            raise DuplicateRow("orders.client_order_id") from None
        return order

    async def newest(self, limit: int, offset: int = 0) -> list[Order]:
        """The newest orders first."""
        query = (
            select(Order)
            .order_by(Order.created_at.desc(), Order.id)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(query)).scalars())
