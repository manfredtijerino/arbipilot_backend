"""`/trading`: the risk limits, the paper account and its pretend orders.

Login needed. Nothing here can change a limit: limits change only in
`decisions.yaml`, by the owner's decision.
"""

import logging
from collections.abc import Awaitable
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from api.dependencies import current_user
from api.schemas.trading import (
    FillItem,
    FillsResponse,
    PaperOrderRequest,
    PaperOrderResponse,
    PositionsResponse,
    RiskLimitsView,
    RiskResponse,
    RiskUsage,
)
from services import clock
from services.errors import DatabaseUnavailable
from services.paper_service import SOURCE, PaperTrading
from trading.risk import Side

logger = logging.getLogger(__name__)

EIGHT_DECIMALS = Decimal("0.00000001")

router = APIRouter(
    prefix="/trading",
    tags=["Trading control"],
    dependencies=[Depends(current_user)],  # every route in this file
)


def _paper(request: Request) -> PaperTrading:
    return request.app.state.paper


Paper = Annotated[PaperTrading, Depends(_paper)]


async def _from_database[T](work: Awaitable[T]) -> T:
    """Run one piece of paper-account work; a database problem is said plainly."""
    try:
        return await work
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.error("paper account: database error type=%s", type(exc).__name__)
        raise DatabaseUnavailable from None


@router.get("/risk", response_model=RiskResponse)
async def risk(paper: Paper) -> RiskResponse:
    """The owner's limits and how much of each is used right now."""
    report = await _from_database(paper.report(clock.utc_now()))
    # Every amount with the same 8 decimals, like the rest of the paper account.
    figures = {
        name: value.quantize(EIGHT_DECIMALS) if isinstance(value, Decimal) else value
        for name, value in vars(report).items()
    }
    usage = RiskUsage.model_validate({**figures, "equity_source": SOURCE})
    return RiskResponse(
        limits=RiskLimitsView.model_validate(report.limits), usage=usage
    )


@router.get("/positions", response_model=PositionsResponse)
async def positions(paper: Paper) -> PositionsResponse:
    """What the paper account holds and is worth right now."""
    wallet = await _from_database(paper.wallet(clock.utc_now()))
    return PositionsResponse.model_validate({**vars(wallet), "source": SOURCE})


@router.get("/fills", response_model=FillsResponse)
async def fills(
    paper: Paper,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> FillsResponse:
    """The pretend buys and sells, newest first."""
    rows = await _from_database(paper.fills(limit, offset, clock.utc_now()))
    return FillsResponse(
        limit=limit, offset=offset, fills=[FillItem.model_validate(r) for r in rows]
    )


# Development only. This router is not registered at all outside development
# (see `config/server.py`), so in production the address simply does not exist.
dev_router = APIRouter(
    prefix="/trading",
    tags=["Trading control"],
    dependencies=[Depends(current_user)],
)


@dev_router.post("/orders/test", response_model=PaperOrderResponse)
async def test_order(body: PaperOrderRequest, paper: Paper) -> PaperOrderResponse:
    """One pretend order through the whole path: risk engine, then a paper
    fill at the live price. No real order is sent."""
    result = await _from_database(
        paper.place(
            body.symbol,
            Side(body.side),
            clock.utc_now(),
            quantity=body.quantity,
            amount_usdt=body.amount_usdt,
        )
    )
    decision = result.decision
    return PaperOrderResponse(
        outcome=decision.outcome,
        code=decision.code,
        reason=decision.reason,
        fill=FillItem.model_validate(result.fill) if result.fill else None,
    )
