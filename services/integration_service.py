"""The connection checks: database, Binance, Claude API and Telegram.

Startup (`server.py`) and `GET /health/ready` both use the short checks at the
top, so the two can never disagree about what "connected" means. Every check
returns a `CheckResult`; none of them raises, and no detail ever contains a
secret.

The second half holds the detailed reports behind `/integrations/...`: one per
outside service, each saying "ok" or exactly what is wrong. They never raise
either, and they only read: nothing here places an order or moves money.
"""

import asyncio
import logging
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from ai.client import AICheckError, check_claude
from config.database import (
    DatabaseCheckError,
    check_database,
    read_database_facts,
)
from config.settings import Settings
from database.migrations.head import latest_migration
from exchange.config import REQUEST_TIMEOUT_SECONDS, ExchangeConfigError, rest_base_url
from exchange.rest_client import (
    BinanceKey,
    ExchangeCheckError,
    check_exchange,
    configured_keys,
    fetch_account,
    fetch_key_restrictions,
)
from monitoring import healthchecks, server_info
from services import clock
from services.errors import TooManyRequests
from telegram_bot.alerts import TelegramCheckError, check_telegram, send_alert

logger = logging.getLogger(__name__)

# `GET /health/ready` needs no login, so its answer is reused for a short time.
# Otherwise anyone who can reach the port could make the app call Binance,
# Anthropic and Telegram as fast as they like.
READINESS_CACHE_SECONDS = 15


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome. `detail` is a plain sentence, safe to show."""

    name: str
    ok: bool
    detail: str = ""


def _unexpected(name: str, exc: Exception) -> CheckResult:
    """A check must never raise: an error nobody planned for is a failed check.

    Only the error's type is logged and shown, because its text is not ours
    and could contain an address or a key.
    """
    logger.error("check=%s unexpected error type=%s", name, type(exc).__name__)
    return CheckResult(name, False, f"unexpected error ({type(exc).__name__})")


async def database_check(settings: Settings) -> CheckResult:
    try:
        database = await check_database(settings)
    except DatabaseCheckError as exc:
        return CheckResult("database", False, str(exc))
    except Exception as exc:  # see _unexpected
        return _unexpected("database", exc)
    return CheckResult("database", True, database)


async def binance_check(settings: Settings) -> CheckResult:
    try:
        await check_exchange(settings)
    except ExchangeCheckError as exc:
        return CheckResult("binance", False, str(exc))
    except Exception as exc:  # see _unexpected
        return _unexpected("binance", exc)
    return CheckResult("binance", True)


async def claude_check(settings: Settings) -> CheckResult:
    try:
        model = await check_claude(settings)
    except AICheckError as exc:
        return CheckResult("claude", False, str(exc))
    except Exception as exc:  # see _unexpected
        return _unexpected("claude", exc)
    return CheckResult("claude", True, model)


async def telegram_check(settings: Settings) -> CheckResult:
    try:
        await check_telegram(settings)
    except TelegramCheckError as exc:
        return CheckResult("telegram", False, str(exc))
    except Exception as exc:  # see _unexpected
        return _unexpected("telegram", exc)
    return CheckResult("telegram", True)


async def run_startup_checks(settings: Settings) -> list[CheckResult]:
    """The three checks behind the startup lines, run at the same time."""
    return list(
        await asyncio.gather(
            database_check(settings),
            binance_check(settings),
            claude_check(settings),
        )
    )


async def run_all_checks(settings: Settings) -> list[CheckResult]:
    """All four checks, run at the same time."""
    return list(
        await asyncio.gather(
            database_check(settings),
            binance_check(settings),
            claude_check(settings),
            telegram_check(settings),
        )
    )


class ReadinessCache:
    """Remembers the last full check for a few seconds."""

    def __init__(self, max_age_seconds: float = READINESS_CACHE_SECONDS) -> None:
        self._max_age = max_age_seconds
        self._lock = asyncio.Lock()
        self._results: list[CheckResult] | None = None
        self._checked_at = 0.0

    async def get(self, settings: Settings) -> list[CheckResult]:
        # The lock makes simultaneous callers share one round of checks.
        async with self._lock:
            age = time.monotonic() - self._checked_at
            if self._results is None or age >= self._max_age:
                self._results = await run_all_checks(settings)
                self._checked_at = time.monotonic()
            return self._results


# --- Detailed reports, one per outside service (`/integrations/...`) ---

Status = Literal["ok", "failed", "not_configured"]

# The two assets the bot needs: USDT to trade with, BNB to pay fees.
BALANCE_ASSETS = ("USDT", "BNB")

TELEGRAM_TEST_TEXT = "Test message from ArbiPilot. Telegram is connected."


def _join(problems: list[str]) -> str:
    return "; ".join(problems)


# What a money amount or a fee rate from Binance looks like: digits, perhaps a
# point and more digits. No sign, no exponent, no spaces, nothing else.
_PLAIN_NUMBER = re.compile(r"\d{1,20}(\.\d{1,20})?")

# Hard rule 7: Spot trading only. On a mainnet key each of these must be off.
FORBIDDEN_PERMISSIONS = {
    "enableInternalTransfer": "internal transfers",
    "permitsUniversalTransfer": "universal transfers",
    "enableMargin": "margin",
    "enableFutures": "futures",
    "enableVanillaOptions": "options",
    "enablePortfolioMarginTrading": "portfolio margin",
}


def _decimal_text(value: Any) -> str | None:
    """A number Binance sent as text, checked and returned as text."""
    if not isinstance(value, str) or not _PLAIN_NUMBER.fullmatch(value):
        return None
    return format(Decimal(value), "f")


def _flag(value: Any) -> bool | None:
    """True or False only when Binance really said so; anything else is unknown.

    A missing or strange answer must never be read as "safe".
    """
    return value if isinstance(value, bool) else None


@dataclass(frozen=True)
class KeyReport:
    """One Binance key. `None` means "could not be checked here"."""

    name: str  # testnet, read or trade
    exchange: str  # testnet or mainnet
    ok: bool
    valid: bool
    trading_allowed: bool | None = None
    withdrawals_enabled: bool | None = None
    ip_restricted: bool | None = None
    # Margin, futures, options and transfers are all off (mainnet keys only).
    spot_only: bool | None = None
    # The account's fee per side, before the BNB discount.
    maker_fee: str | None = None
    taker_fee: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class BinanceReport:
    status: Status
    detail: str
    host: str
    reachable: bool
    clock_difference_ms: int | None = None
    keys: list[KeyReport] = field(default_factory=list)


def _host(settings: Settings) -> str:
    try:
        return urlsplit(rest_base_url(settings)).hostname or ""
    except ExchangeConfigError:
        return ""


async def _key_report(key: BinanceKey, client: httpx.AsyncClient) -> KeyReport:
    exchange = "testnet" if key.is_testnet else "mainnet"
    try:
        account = await fetch_account(key, client)
        restrictions = (
            None if key.is_testnet else await fetch_key_restrictions(key, client)
        )
    except ExchangeCheckError as exc:
        return KeyReport(key.name, exchange, ok=False, valid=False, detail=str(exc))

    rates = account.get("commissionRates")
    rates = rates if isinstance(rates, dict) else {}
    maker_fee, taker_fee = (
        _decimal_text(rates.get("maker")),
        _decimal_text(rates.get("taker")),
    )
    account_can_trade = _flag(account.get("canTrade"))
    problems: list[str] = []
    notes: list[str] = []
    spot_only = None
    if maker_fee is None or taker_fee is None:
        problems.append("Binance did not report the fee rates")

    if restrictions is None:
        trading = account_can_trade
        withdrawals = ip_restricted = None
        notes.append(
            "the testnet has no withdrawals and no IP lock, so those two "
            "cannot be checked here"
        )
        if trading is not True:
            problems.append("the testnet key is not allowed to trade")
    else:
        trading = _flag(restrictions.get("enableSpotAndMarginTrading"))
        withdrawals = _flag(restrictions.get("enableWithdrawals"))
        ip_restricted = _flag(restrictions.get("ipRestrict"))
        if withdrawals is True:
            problems.append("WITHDRAWALS ARE ENABLED on this key: turn them off")
        elif withdrawals is None:
            problems.append("could not confirm that withdrawals are disabled")
        if ip_restricted is False:
            problems.append("the key is not locked to an IP address")
        elif ip_restricted is None:
            problems.append("could not confirm the key is locked to an IP address")
        if trading is None:
            problems.append("could not confirm the key's trading permission")
        elif key.name == "read" and trading:
            problems.append("the read key is allowed to trade; it should only read")
        elif key.name == "trade" and not trading:
            problems.append("the trade key is not allowed to trade")
        if key.name == "trade" and account_can_trade is not True:
            problems.append("the account itself is not allowed to trade")
        spot_only = True
        for field_name, label in FORBIDDEN_PERMISSIONS.items():
            switched_on = _flag(restrictions.get(field_name))
            if switched_on is True:
                spot_only = False
                problems.append(f"{label} are switched on; this bot is Spot only")
            elif switched_on is None:
                spot_only = None if spot_only else spot_only
                problems.append(f"could not confirm {label} are off")

    return KeyReport(
        key.name,
        exchange,
        ok=not problems,
        valid=True,
        trading_allowed=trading,
        withdrawals_enabled=withdrawals,
        ip_restricted=ip_restricted,
        spot_only=spot_only,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        detail=_join(problems or notes),
    )


async def binance_report(
    settings: Settings, client: httpx.AsyncClient | None = None
) -> BinanceReport:
    """Reachable, clocks agree, and every key in `.env` is valid and safe."""
    host = _host(settings)
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        try:
            drift_ms = await check_exchange(settings, client)
        except ExchangeCheckError as exc:
            return BinanceReport("failed", str(exc), host, reachable=False)
        try:
            keys = configured_keys(settings)
        except ExchangeCheckError as exc:
            return BinanceReport(
                "failed", str(exc), host, reachable=True, clock_difference_ms=drift_ms
            )
        if not keys:
            return BinanceReport(
                "failed",
                "no Binance key is set in .env",
                host,
                reachable=True,
                clock_difference_ms=drift_ms,
            )
        reports = list(await asyncio.gather(*(_key_report(k, client) for k in keys)))
    except Exception as exc:  # see _unexpected
        return BinanceReport(
            "failed", _unexpected("binance", exc).detail, host, reachable=False
        )
    finally:
        if owns_client:
            await client.aclose()
    problems = [f"{r.name} key: {r.detail}" for r in reports if not r.ok]
    return BinanceReport(
        "failed" if problems else "ok",
        _join(problems),
        host,
        reachable=True,
        clock_difference_ms=drift_ms,
        keys=reports,
    )


@dataclass(frozen=True)
class Balance:
    asset: str
    free: str  # can be used now
    locked: str  # held by open orders
    total: str


@dataclass(frozen=True)
class BalancesReport:
    status: Status
    detail: str
    # Where the numbers come from: testnet (pretend money) or mainnet.
    exchange: str | None = None
    balances: list[Balance] = field(default_factory=list)


def account_key(settings: Settings) -> BinanceKey | None:
    """The key that reads the account for the current machine and mode.

    Testnet mode reads the testnet. Otherwise the mainnet read key is used.
    The laptop holds no mainnet key, so there the testnet key is used and the
    answer says so. Production never falls back to the testnet by itself.
    """
    keys = {key.name: key for key in configured_keys(settings)}
    if settings.trading_mode == "testnet":
        return keys.get("testnet")
    if "read" in keys:
        return keys["read"]
    return keys.get("testnet") if settings.is_development else None


def _balances(account: dict[str, Any]) -> list[Balance]:
    rows = account.get("balances")
    if not isinstance(rows, list):
        # A strange answer must never be shown as "the account is empty".
        raise ExchangeCheckError("Binance sent a balance we could not read")
    found: dict[str, tuple[Decimal, Decimal]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("asset") not in BALANCE_ASSETS:
            continue
        free, locked = _decimal_text(row.get("free")), _decimal_text(row.get("locked"))
        if free is None or locked is None:
            raise ExchangeCheckError("Binance sent a balance we could not read")
        found[row["asset"]] = (Decimal(free), Decimal(locked))
    zero = (Decimal(0), Decimal(0))
    return [
        Balance(
            asset,
            free=format(free, "f"),
            locked=format(locked, "f"),
            total=format(free + locked, "f"),
        )
        for asset in BALANCE_ASSETS
        for free, locked in [found.get(asset, zero)]
    ]


async def balances_report(
    settings: Settings, client: httpx.AsyncClient | None = None
) -> BalancesReport:
    """The Spot balances of USDT and BNB. Money stays text, never a float."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        key = account_key(settings)
        if key is None:
            return BalancesReport(
                "failed", "no Binance key for reading the account is set in .env"
            )
        exchange = "testnet" if key.is_testnet else "mainnet"
        balances = _balances(await fetch_account(key, client))
    except ExchangeCheckError as exc:
        return BalancesReport("failed", str(exc))
    except Exception as exc:  # see _unexpected
        return BalancesReport("failed", _unexpected("balances", exc).detail)
    finally:
        if owns_client:
            await client.aclose()
    detail = "pretend money on the Binance testnet" if key.is_testnet else ""
    return BalancesReport("ok", detail, exchange, balances)


@dataclass(frozen=True)
class DatabaseReport:
    status: Status
    detail: str
    name: str | None = None
    version: str | None = None
    applied_migration: str | None = None
    latest_migration: str | None = None


async def database_report(settings: Settings) -> DatabaseReport:
    """Name, version, and whether the tables are at the migration the code expects."""
    try:
        facts = await read_database_facts(settings)
        latest = latest_migration()
    except DatabaseCheckError as exc:
        return DatabaseReport("failed", str(exc))
    except Exception as exc:  # see _unexpected
        return DatabaseReport("failed", _unexpected("database", exc).detail)
    detail = ""
    if facts.applied_migration != latest:
        detail = (
            f"the tables are at migration {facts.applied_migration or 'none'}, "
            f"the code expects {latest or 'none'}"
        )
    return DatabaseReport(
        "failed" if detail else "ok",
        detail,
        name=facts.name,
        version=facts.version,
        applied_migration=facts.applied_migration,
        latest_migration=latest,
    )


@dataclass(frozen=True)
class ClaudeReport:
    status: Status
    detail: str
    model: str | None = None
    # Both stay empty until the AI budget exists (stage 9).
    usage_today_usd: str | None = None
    daily_budget_usd: str | None = None


async def claude_report(settings: Settings) -> ClaudeReport:
    """The key is accepted and the model exists. Costs no tokens."""
    result = await claude_check(settings)
    if not result.ok:
        return ClaudeReport("failed", result.detail)
    return ClaudeReport(
        "ok", "usage against the daily budget is not tracked yet", model=result.detail
    )


@dataclass(frozen=True)
class ActionReport:
    """The outcome of "send a test message" or "send a test ping"."""

    status: Status
    detail: str


async def telegram_test(settings: Settings) -> ActionReport:
    """Send one real message to the owner."""
    try:
        await send_alert(settings, TELEGRAM_TEST_TEXT)
    except TelegramCheckError as exc:
        return ActionReport("failed", str(exc))
    except Exception as exc:  # see _unexpected
        return ActionReport("failed", _unexpected("telegram", exc).detail)
    return ActionReport("ok", "message sent; look at Telegram")


async def healthchecks_test(settings: Settings) -> ActionReport:
    """Send one real ping. On the laptop the address is empty on purpose."""
    if not healthchecks.is_configured(settings):
        return ActionReport(
            "not_configured",
            "HEALTHCHECKS_PING_URL is empty; it is filled in on the server only",
        )
    try:
        await healthchecks.send_ping(settings)
    except healthchecks.HealthchecksError as exc:
        return ActionReport("failed", str(exc))
    except Exception as exc:  # see _unexpected
        return ActionReport("failed", _unexpected("healthchecks", exc).detail)
    return ActionReport("ok", "ping sent; Healthchecks.io shows it within a minute")


@dataclass(frozen=True)
class ServerReport:
    status: Status
    detail: str
    environment: str
    app_uptime_seconds: int
    machine_uptime_seconds: int | None = None
    memory_total_mb: int | None = None
    memory_available_mb: int | None = None
    disk_total_gb: float | None = None
    disk_free_gb: float | None = None
    public_ip: str | None = None
    expected_public_ip: str | None = None
    # None when no address is expected (the laptop).
    public_ip_matches: bool | None = None
    clock_difference_ms: int | None = None


async def server_report(settings: Settings, started_at: datetime) -> ServerReport:
    """The machine the app runs on, and whether Binance will accept its address."""
    problems: list[str] = []
    try:
        machine = server_info.read_machine()
    except Exception as exc:  # see _unexpected
        machine = None
        problems.append(f"machine facts: {_unexpected('machine', exc).detail}")

    async def public_ip() -> str | None:
        try:
            return await server_info.fetch_public_ip()
        except server_info.ServerInfoError as exc:
            problems.append(str(exc))
        except Exception as exc:  # see _unexpected
            problems.append(_unexpected("public address", exc).detail)
        return None

    async def clock_difference() -> int | None:
        try:
            return await check_exchange(settings)
        except ExchangeCheckError as exc:
            problems.append(f"clock check: {exc}")
        except Exception as exc:  # see _unexpected
            problems.append(_unexpected("clock", exc).detail)
        return None

    address, drift_ms = await asyncio.gather(public_ip(), clock_difference())
    expected = settings.expected_public_ip.strip() or None
    matches = None
    if expected and address:
        matches = address == expected
        if not matches:
            problems.append(
                "the public address is not the one Binance expects "
                "(EXPECTED_PUBLIC_IP); the mainnet keys will be refused"
            )
    return ServerReport(
        "failed" if problems else "ok",
        _join(problems),
        environment=settings.app_env,
        app_uptime_seconds=max(0, int((clock.utc_now() - started_at).total_seconds())),
        machine_uptime_seconds=machine and machine.machine_uptime_seconds,
        memory_total_mb=machine and machine.memory_total_mb,
        memory_available_mb=machine and machine.memory_available_mb,
        disk_total_gb=machine and machine.disk_total_gb,
        disk_free_gb=machine and machine.disk_free_gb,
        public_ip=address,
        expected_public_ip=expected,
        public_ip_matches=matches,
        clock_difference_ms=drift_ms,
    )


# --- Not too often ---

# A read check's answer is reused for this long, like `/health/ready`.
READ_CACHE_SECONDS = 15
# A check that sends something (a Telegram message, a ping) at most this often.
ACTION_COOLDOWN_SECONDS = 60


class CheckThrottle:
    """Keeps the connection checks from being run in a loop.

    Each check calls Binance, Anthropic, Telegram or Healthchecks.io. Binance
    counts every call against the address the trading loop also uses, so a
    script hammering these endpoints (or a stolen token) could get trading
    blocked, flood the owner's Telegram, or fake "alive" pings.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._reports: dict[str, tuple[float, Any]] = {}
        self._last_action: dict[str, float] = {}

    async def cached(self, name: str, produce: Callable[[], Awaitable[Any]]) -> Any:
        """The report from the last few seconds, or a fresh one."""
        async with self._locks[name]:  # simultaneous callers share one run
            entry = self._reports.get(name)
            if entry is None or self._now() - entry[0] >= READ_CACHE_SECONDS:
                entry = (self._now(), await produce())
                self._reports[name] = (self._now(), entry[1])
            return entry[1]

    def start_action(self, name: str) -> None:
        """Allow the action, or raise TooManyRequests with the seconds to wait."""
        last = self._last_action.get(name)
        if last is not None:
            wait = ACTION_COOLDOWN_SECONDS - (self._now() - last)
            if wait > 0:
                raise TooManyRequests(max(1, int(wait + 0.999)))
        self._last_action[name] = self._now()
