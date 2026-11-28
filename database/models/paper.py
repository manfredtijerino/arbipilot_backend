"""The paper account's tables: pretend money, pretend trades, real records.

- `paper_account`: one row, the pretend wallet's free USDT.
- `paper_positions`: one row per pair that is held right now.
- `paper_fills`: every pretend buy and sell that happened, never changed.
- `risk_state`: one row, what the risk engine must remember over a restart.

Money is `Numeric(28, 8)`: exact, with Binance's 8 decimals.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base

Money = Numeric(28, 8)


class PaperAccount(Base):
    __tablename__ = "paper_account"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("cash >= 0", name="cash_not_negative"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, default=1
    )
    cash: Mapped[Decimal] = mapped_column(Money)  # free USDT
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("cost >= 0", name="cost_not_negative"),
    )

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(Money)  # of the coin
    # Everything paid for what is still held, fees included, in USDT.
    cost: Mapped[Decimal] = mapped_column(Money)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperFill(Base):
    __tablename__ = "paper_fills"
    __table_args__ = (
        CheckConstraint("side in ('BUY', 'SELL')", name="side_known"),
        CheckConstraint("quantity > 0 and price > 0", name="amounts_positive"),
        CheckConstraint("fee >= 0", name="fee_not_negative"),
        CheckConstraint("notional >= 0", name="notional_not_negative"),
        CheckConstraint("cash_after >= 0", name="cash_after_not_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The ticket number of the order this fill belongs to (see `orders`).
    client_order_id: Mapped[str] = mapped_column(String(36), unique=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[Decimal] = mapped_column(Money)
    price: Mapped[Decimal] = mapped_column(Money)
    notional: Mapped[Decimal] = mapped_column(Money)  # quantity times price
    fee: Mapped[Decimal] = mapped_column(Money)  # in USDT
    # Only on a sale: what came back minus what that part had cost.
    realized_pnl: Mapped[Decimal | None] = mapped_column(Money)
    cash_after: Mapped[Decimal] = mapped_column(Money)
    # What the risk engine said about the order: approved or reduced, and why.
    risk_outcome: Mapped[str] = mapped_column(String(10))
    risk_code: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RiskStateRow(Base):
    __tablename__ = "risk_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("day_start_equity >= 0", name="equity_not_negative"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, default=1
    )
    # The UTC day the daily loss is counted for; empty before the first day.
    day: Mapped[date | None] = mapped_column(Date)
    day_start_equity: Mapped[Decimal] = mapped_column(Money)
    daily_pause: Mapped[bool] = mapped_column(Boolean)
    # The kill switch's reason, or empty when trading is not paused.
    outside_pause: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
