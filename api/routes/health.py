"""`/health`: the only endpoints that need no login."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.schemas.health import CheckStatus, HealthResponse, ReadyChecks, ReadyResponse
from config.version import APP_VERSION

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Is the app alive? Says which environment and trading mode it runs in."""
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        environment=settings.app_env,
        trading_mode=settings.trading_mode,
        version=APP_VERSION,
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "A connection failed"}},
)
async def ready(request: Request) -> JSONResponse:
    """Is everything connected? 200 when all four are, 503 when any is not."""
    settings = request.app.state.settings
    results = await request.app.state.readiness.get(settings)
    all_ok = all(result.ok for result in results)
    checks = {
        result.name: CheckStatus(
            status="ok" if result.ok else "failed",
            # Only failures are explained; a success needs no detail.
            detail="" if result.ok else result.detail,
        )
        for result in results
    }
    body = ReadyResponse(
        status="ok" if all_ok else "failed",
        environment=settings.app_env,
        checks=ReadyChecks(**checks),
    )
    return JSONResponse(
        status_code=200 if all_ok else 503, content=body.model_dump(mode="json")
    )
