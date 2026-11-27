"""Request and response shapes for the trading endpoints (`/trading/...`).

Money and shares are text, never JSON numbers.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.schemas.market import Money
from exchange.numbers import positive_decimal


class _View(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RiskLimitsView(_View):
    """The owner's limits, exactly as written in `decisions.yaml`."""

    max_position_pct_equity: Money
    daily_loss_pause_pct: Money
    max_open_positions: int
    max_positions_per_symbol: int
    max_orders_per_minute: int


class RiskUsage(_View):
    equity: Money
    equity_source: str
    max_position_value: Money
    day: str
    day_start_equity: Money
    day_profit_or_loss: Money
    daily_loss_limit_value: Money
    entries_paused: bool
    pause_reason: str
    open_positions: int
    orders_last_minute: int


class RiskResponse(BaseModel):
    """`GET /trading/risk`"""

    limits: RiskLimitsView
    usage: RiskUsage


class PositionItem(_View):
    symbol: str
    quantity: Money
    cost: Money  # paid for it, fees included
    price: Money | None  # the last known best bid; null when none is known
    price_stale: bool  # that price is missing or too old to act on
    value: Money | None
    profit_or_loss: Money | None  # value minus cost, before the selling fee
    opened_at: datetime


class PositionsResponse(_View):
    """`GET /trading/positions`"""

    source: str
    cash: Money
    equity: Money | None  # null when a held pair has no known price
    prices_stale: bool  # a held pair's price is missing or too old
    positions: list[PositionItem]


class FillItem(_View):
    id: uuid.UUID
    client_order_id: str
    symbol: str
    side: str
    quantity: Money
    price: Money
    notional: Money
    fee: Money
    realized_pnl: Money | None  # only on a sale
    cash_after: Money
    risk_outcome: str
    risk_code: str
    created_at: datetime


class FillsResponse(BaseModel):
    """`GET /trading/fills`"""

    limit: int
    offset: int
    fills: list[FillItem]


class PaperOrderRequest(BaseModel):
    """`POST /trading/orders/test` (development only)"""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Z0-9]{2,20}$")
    side: Literal["BUY", "SELL"]
    # Text, like every amount. Leave both out to buy as much as the limits
    # allow, or to sell everything held.
    quantity: Decimal | None = None
    amount_usdt: Decimal | None = None

    @field_validator("quantity", "amount_usdt", mode="before")
    @classmethod
    def _plain_positive_text(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError('write the amount as text, like "24"')
        return positive_decimal(value)

    @model_validator(mode="after")
    def _one_size_only(self) -> "PaperOrderRequest":
        if self.quantity is not None and self.amount_usdt is not None:
            raise ValueError("give quantity or amount_usdt, not both")
        if self.side == "SELL" and self.amount_usdt is not None:
            raise ValueError("a sale is sized by quantity, not amount_usdt")
        return self


class PaperOrderResponse(BaseModel):
    outcome: str  # approved, reduced or rejected
    code: str
    reason: str
    fill: FillItem | None  # null when nothing was traded
