"""`/market`: the watched pairs and their live prices. Login needed.

These only read what the app already holds in memory: no request here makes
a call to Binance.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from api.dependencies import current_user
from api.schemas.market import StreamStatusResponse, SymbolsResponse, TickerResponse
from services.market_service import MarketData

router = APIRouter(
    prefix="/market",
    tags=["Market data"],
    dependencies=[Depends(current_user)],  # every route in this file
)


def _market(request: Request) -> MarketData:
    return request.app.state.market


@router.get("/symbols", response_model=SymbolsResponse)
async def symbols(request: Request) -> SymbolsResponse:
    """The pairs the bot watches, with each pair's trading rules."""
    return SymbolsResponse.model_validate(_market(request).list_symbols())


@router.get("/ticker/{symbol}", response_model=TickerResponse)
async def ticker(
    request: Request,
    symbol: Annotated[
        str, Path(min_length=5, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    ],
) -> TickerResponse:
    """The latest price of one watched pair."""
    return TickerResponse.model_validate(_market(request).ticker(symbol))


@router.get("/stream/status", response_model=StreamStatusResponse)
async def stream_status(request: Request) -> StreamStatusResponse:
    """Is the live price stream connected, and how old is the last message?"""
    return StreamStatusResponse.model_validate(_market(request).stream_status())
