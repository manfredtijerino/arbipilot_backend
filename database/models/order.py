"""The order diary: every order that was asked for, and what became of it.

One row per order, never changed afterwards. A refused order is written down
too, with what the risk engine said, so the diary shows everything the bot
tried and not only what it did.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.paper import Money


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("side in ('BUY', 'SELL')", name="side_known"),
        CheckConstraint("mode in ('shadow', 'testnet', 'live')", name="mode_known"),
        CheckConstraint("status in ('filled', 'rejected')", name="status_known"),
        CheckConstraint(
            "(status = 'filled') = (fill_id is not null)", name="filled_has_fill"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The order's ticket number, given by whoever asked for the order. The
    # database refuses a second row with the same one: a retry can never
    # become a second order, even when two copies arrive at the same moment.
    client_order_id: Mapped[str] = mapped_column(String(36), unique=True)
    mode: Mapped[str] = mapped_column(String(10))  # shadow, testnet or live
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(4))
    # What was asked for: coins, or USDT to spend, or neither ("as much as
    # allowed" for a buy, "everything" for a sale).
    requested_quantity: Mapped[Decimal | None] = mapped_column(Money)
    requested_amount: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(10))  # filled or rejected
    # What the risk engine said, and why, in the owner's words.
    risk_outcome: Mapped[str] = mapped_column(String(10))
    risk_code: Mapped[str] = mapped_column(String(30))
    risk_reason: Mapped[str] = mapped_column(String(300))
    # What was traded; empty when nothing was.
    quantity: Mapped[Decimal | None] = mapped_column(Money)
    price: Mapped[Decimal | None] = mapped_column(Money)
    fill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("paper_fills.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
