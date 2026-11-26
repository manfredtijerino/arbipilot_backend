"""Response shapes for the health endpoints."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """`GET /health`: the app is alive."""

    status: Literal["ok"]
    environment: Literal["development", "production"]
    trading_mode: Literal["shadow", "testnet", "live"]
    version: str


class CheckStatus(BaseModel):
    """One connection. `detail` says why when it failed, in plain words."""

    status: Literal["ok", "failed"]
    detail: str


class ReadyChecks(BaseModel):
    database: CheckStatus
    binance: CheckStatus
    claude: CheckStatus
    telegram: CheckStatus


class ReadyResponse(BaseModel):
    """`GET /health/ready`: is everything connected?"""

    status: Literal["ok", "failed"]
    environment: Literal["development", "production"]
    checks: ReadyChecks
