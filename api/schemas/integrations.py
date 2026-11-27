"""Response shapes for the connection checks (`/integrations/...`).

Every answer starts with `status` and `detail`:
- `ok`: the service works; `detail` may hold a note.
- `failed`: `detail` says what is wrong, in plain words. The HTTP status is 503.
- `not_configured`: the setting is empty on this machine on purpose.

A field that is `null` means "could not be checked here". Money and fee rates
are text, never JSON numbers.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Status = Literal["ok", "failed", "not_configured"]


class _Report(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: Status
    detail: str


class BinanceKeyStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Literal["testnet", "read", "trade"]
    exchange: Literal["testnet", "mainnet"]
    ok: bool
    valid: bool
    trading_allowed: bool | None
    withdrawals_enabled: bool | None
    ip_restricted: bool | None
    spot_only: bool | None
    maker_fee: str | None
    taker_fee: str | None
    detail: str


class BinanceResponse(_Report):
    """`GET /integrations/binance`"""

    host: str
    reachable: bool
    clock_difference_ms: int | None
    keys: list[BinanceKeyStatus]


class BalanceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset: str
    free: str
    locked: str
    total: str


class BalancesResponse(_Report):
    """`GET /integrations/binance/balances`"""

    exchange: Literal["testnet", "mainnet"] | None
    balances: list[BalanceItem]


class DatabaseResponse(_Report):
    """`GET /integrations/database`"""

    name: str | None
    version: str | None
    applied_migration: str | None
    latest_migration: str | None


class ClaudeResponse(_Report):
    """`GET /integrations/claude`"""

    model: str | None
    usage_today_usd: str | None
    daily_budget_usd: str | None


class ActionResponse(_Report):
    """`POST /integrations/telegram/test` and `/integrations/healthchecks/test`"""


class ServerResponse(_Report):
    """`GET /integrations/server`"""

    environment: Literal["development", "production"]
    app_uptime_seconds: int
    machine_uptime_seconds: int | None
    memory_total_mb: int | None
    memory_available_mb: int | None
    disk_total_gb: float | None
    disk_free_gb: float | None
    public_ip: str | None
    expected_public_ip: str | None
    public_ip_matches: bool | None
    clock_difference_ms: int | None
