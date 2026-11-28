"""`/trading`: the stop button, the risk limits, the paper account and its
pretend orders.

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
    KillRequest,
    PaperOrderRequest,
    PaperOrderResponse,
    PositionsResponse,
    RiskLimitsView,
    RiskResponse,
    RiskUsage,
    StatusResponse,
)
from services import clock
from services.errors import DatabaseUnavailable, PauseNotSaved
from services.paper_service import SOURCE, PaperTrading, TradingStatus
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


async def from_database[T](work: Awaitable[T]) -> T:
    """Run one piece of paper-account work; a database problem is said plainly."""
    try:
        return await work
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.error("paper account: database error type=%s", type(exc).__name__)
        raise DatabaseUnavailable from None


@router.get("/risk", response_model=RiskResponse)
async def risk(paper: Paper) -> RiskResponse:
    """The owner's limits and how much of each is used right now."""
    report = await from_database(paper.report(clock.utc_now()))
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
    wallet = await from_database(paper.wallet(clock.utc_now()))
    return PositionsResponse.model_validate({**vars(wallet), "source": SOURCE})


@router.get("/fills", response_model=FillsResponse)
async def fills(
    paper: Paper,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> FillsResponse:
    """The pretend buys and sells, newest first."""
    rows = await from_database(paper.fills(limit, offset, clock.utc_now()))
    return FillsResponse(
        limit=limit, offset=offset, fills=[FillItem.model_validate(r) for r in rows]
    )


def _status_view(request: Request, status: TradingStatus) -> StatusResponse:
    equity = status.equity
    return StatusResponse(
        environment=request.app.state.settings.app_env,
        trading_mode=status.mode,
        app_started_at=request.app.state.started_at,
        state="paused" if status.paused else "running",
        pause_reason=status.pause_reason,
        kill_switch=status.kill_switch,
        kill_reason=status.kill_reason,
        daily_loss_pause=status.daily_loss_pause,
        equity=equity.quantize(EIGHT_DECIMALS) if equity is not None else None,
        prices_stale=status.prices_stale,
        open_positions=status.open_positions,
        day=status.day,
        day_profit_or_loss=status.day_profit_or_loss.quantize(EIGHT_DECIMALS),
    )


@router.get("/status", response_model=StatusResponse)
async def status(request: Request, paper: Paper) -> StatusResponse:
    """Is the bot allowed to open trades right now, and if not, why."""
    return _status_view(request, await from_database(paper.status(clock.utc_now())))


@router.post("/kill", response_model=StatusResponse)
async def kill(
    request: Request, paper: Paper, body: KillRequest | None = None
) -> StatusResponse:
    """The stop button: no new trade is opened until `resume`. Closing a
    trade stays allowed. The stop survives a restart."""
    reason = body.reason if body is not None else ""
    try:
        result = await from_database(paper.kill(reason, clock.utc_now()))
    except DatabaseUnavailable:
        raise PauseNotSaved from None
    return _status_view(request, result)


@router.post("/resume", response_model=StatusResponse)
async def resume(request: Request, paper: Paper) -> StatusResponse:
    """Undo the stop button. It does not undo the daily loss pause."""
    return _status_view(request, await from_database(paper.resume(clock.utc_now())))


# Development only. This router is not registered at all outside development
# (see `config/server.py`), so in production the address simply does not exist.
dev_router = APIRouter(
    prefix="/trading",
    tags=["Trading control"],
    dependencies=[Depends(current_user)],
)


@dev_router.post("/orders/test", response_model=PaperOrderResponse)
async def test_order(body: PaperOrderRequest, paper: Paper) -> PaperOrderResponse:
    """One test order on the road every order takes: risk engine, router,
    fill, diary. In shadow mode the fill is a pretend one at the live price.
    No real order is sent."""
    result = await from_database(
        paper.place(
            body.symbol,
            Side(body.side),
            clock.utc_now(),
            quantity=body.quantity,
            amount_usdt=body.amount_usdt,
            client_order_id=body.client_order_id,
        )
    )
    decision = result.decision
    return PaperOrderResponse(
        outcome=decision.outcome,
        code=decision.code,
        reason=decision.reason,
        fill=FillItem.model_validate(result.fill) if result.fill else None,
        client_order_id=result.order.client_order_id,
        repeated=result.repeated,
    )
