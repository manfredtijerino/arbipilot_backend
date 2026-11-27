"""Response shapes for the market data endpoints (`/market/...`).

Prices, quantities and order values are text, never JSON numbers. Times are
ISO 8601 in UTC.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, PlainSerializer

# A Decimal that travels as plain text: "0.00001000", never 1e-05 and never a float.
Money = Annotated[
    Decimal, PlainSerializer(lambda value: format(value, "f"), return_type=str)
]


class _View(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SymbolItem(_View):
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    trading: bool
    min_order_value: Money
    tick_size: Money
    step_size: Money
    min_quantity: Money


class SymbolsResponse(_View):
    """`GET /market/symbols`"""

    loaded_at: datetime
    stale: bool
    symbols: list[SymbolItem]


class TickerResponse(_View):
    """`GET /market/ticker/{symbol}`"""

    symbol: str
    bid: Money | None
    bid_quantity: Money | None
    ask: Money | None
    ask_quantity: Money | None
    last_price: Money | None
    last_quantity: Money | None
    last_trade_at: datetime | None
    updated_at: datetime
    age_ms: int
    last_trade_age_ms: int | None
    stale: bool


class RecordingInfo(_View):
    enabled: bool
    active: bool
    file: str | None
    lines_written: int
    folder_megabytes: float
    detail: str


class StreamStatusResponse(_View):
    """`GET /market/stream/status`"""

    status: Literal["connected", "connecting", "not_configured"]
    detail: str
    host: str
    streams: list[str]
    connected_since: datetime | None
    last_message_at: datetime | None
    last_message_age_ms: int | None
    messages_received: int
    messages_ignored: int
    reconnects: int
    recording: RecordingInfo
