"""Response shapes for the trading control endpoints (`/trading/...`).

Money and shares are text, never JSON numbers.
"""

from pydantic import BaseModel, ConfigDict

from api.schemas.market import Money


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
