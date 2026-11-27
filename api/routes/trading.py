"""`/trading`: the risk limits and, in later stages, the trading controls.

Login needed. Nothing here can change a limit: limits change only in
`decisions.yaml`, by the owner's decision.
"""

from fastapi import APIRouter, Depends, Request

from api.dependencies import current_user
from api.schemas.trading import RiskLimitsView, RiskResponse, RiskUsage
from services import clock

router = APIRouter(
    prefix="/trading",
    tags=["Trading control"],
    dependencies=[Depends(current_user)],  # every route in this file
)


@router.get("/risk", response_model=RiskResponse)
async def risk(request: Request) -> RiskResponse:
    """The owner's limits and how much of each is used right now."""
    state = request.app.state
    report = state.risk.report(state.account(), clock.utc_now())
    usage = RiskUsage.model_validate(
        {**vars(report), "equity_source": state.account_source}
    )
    return RiskResponse(
        limits=RiskLimitsView.model_validate(report.limits), usage=usage
    )
