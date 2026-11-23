"""The connection checks: database, Binance, Claude API and Telegram.

Startup (`server.py`) and `GET /health/ready` both use these functions, so the
two can never disagree about what "connected" means. Every check returns a
`CheckResult`; none of them raises, and no detail ever contains a secret.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from ai.client import AICheckError, check_claude
from config.database import DatabaseCheckError, check_database
from config.settings import Settings
from exchange.rest_client import ExchangeCheckError, check_exchange
from telegram_bot.alerts import TelegramCheckError, check_telegram

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
