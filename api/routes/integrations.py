"""`/integrations`: one check per outside service. Login needed for all of them.

Each answers 200 when the service works (or is switched off on this machine on
purpose) and 503 when it does not, with the same body either way, so a status
test in Postman notices a failure without reading the body.

None can be run in a loop: a read's answer is reused for 15 seconds, and the
two that send something answer 429 when asked again within a minute.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.dependencies import SettingsDep, current_user
from api.schemas.integrations import (
    ActionResponse,
    BalancesResponse,
    BinanceResponse,
    ClaudeResponse,
    DatabaseResponse,
    ServerResponse,
)
from services import integration_service

router = APIRouter(
    prefix="/integrations",
    tags=["Connections"],
    dependencies=[Depends(current_user)],  # every route in this file
)


def _answer(schema: type[BaseModel], report: object) -> JSONResponse:
    body = schema.model_validate(report)
    failed = body.status == "failed"  # type: ignore[attr-defined]
    return JSONResponse(
        status_code=503 if failed else 200, content=body.model_dump(mode="json")
    )


def _throttle(request: Request) -> integration_service.CheckThrottle:
    return request.app.state.check_throttle


def _failure(schema: type[BaseModel]) -> dict:
    return {503: {"model": schema, "description": "The check failed"}}


@router.get(
    "/binance", response_model=BinanceResponse, responses=_failure(BinanceResponse)
)
async def binance(request: Request, settings: SettingsDep) -> JSONResponse:
    """Binance: reachable, clocks agree, every key valid and safe."""
    report = await _throttle(request).cached(
        "binance", lambda: integration_service.binance_report(settings)
    )
    return _answer(BinanceResponse, report)


@router.get(
    "/binance/balances",
    response_model=BalancesResponse,
    responses=_failure(BalancesResponse),
)
async def binance_balances(request: Request, settings: SettingsDep) -> JSONResponse:
    """The Spot balances of USDT and BNB."""
    report = await _throttle(request).cached(
        "balances", lambda: integration_service.balances_report(settings)
    )
    return _answer(BalancesResponse, report)


@router.get(
    "/database", response_model=DatabaseResponse, responses=_failure(DatabaseResponse)
)
async def database(request: Request, settings: SettingsDep) -> JSONResponse:
    """The database: name, version, and the migration its tables are at."""
    report = await _throttle(request).cached(
        "database", lambda: integration_service.database_report(settings)
    )
    return _answer(DatabaseResponse, report)


@router.get(
    "/claude", response_model=ClaudeResponse, responses=_failure(ClaudeResponse)
)
async def claude(request: Request, settings: SettingsDep) -> JSONResponse:
    """The Claude API: key accepted, model available. Costs no tokens."""
    report = await _throttle(request).cached(
        "claude", lambda: integration_service.claude_report(settings)
    )
    return _answer(ClaudeResponse, report)


@router.get(
    "/server", response_model=ServerResponse, responses=_failure(ServerResponse)
)
async def server(request: Request, settings: SettingsDep) -> JSONResponse:
    """The machine the app runs on: address, uptime, memory, disk, clock."""
    report = await _throttle(request).cached(
        "server",
        lambda: integration_service.server_report(
            settings, request.app.state.started_at
        ),
    )
    return _answer(ServerResponse, report)


@router.post(
    "/telegram/test", response_model=ActionResponse, responses=_failure(ActionResponse)
)
async def telegram_test(request: Request, settings: SettingsDep) -> JSONResponse:
    """Send one test message to the owner's Telegram. At most once a minute."""
    _throttle(request).start_action("telegram")
    return _answer(ActionResponse, await integration_service.telegram_test(settings))


@router.post(
    "/healthchecks/test",
    response_model=ActionResponse,
    responses=_failure(ActionResponse),
)
async def healthchecks_test(request: Request, settings: SettingsDep) -> JSONResponse:
    """Send one test ping to Healthchecks.io. At most once a minute."""
    _throttle(request).start_action("healthchecks")
    return _answer(
        ActionResponse, await integration_service.healthchecks_test(settings)
    )
