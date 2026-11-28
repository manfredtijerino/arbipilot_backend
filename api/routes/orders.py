"""`/orders`: the order diary. Login needed. Read-only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.dependencies import current_user
from api.routes.trading import Paper, from_database
from api.schemas.trading import OrderItem, OrdersResponse
from services import clock

router = APIRouter(
    prefix="/orders",
    tags=["Data"],
    dependencies=[Depends(current_user)],  # every route in this file
)


@router.get("", response_model=OrdersResponse)
async def orders(
    paper: Paper,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> OrdersResponse:
    """Every order that was asked for, refused ones included, newest first."""
    rows = await from_database(paper.orders(limit, offset, clock.utc_now()))
    return OrdersResponse(
        limit=limit, offset=offset, orders=[OrderItem.model_validate(r) for r in rows]
    )
