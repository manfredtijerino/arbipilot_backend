"""The connection checks as one service. Every real check is replaced by a fake."""

from collections.abc import Callable

import pytest

from ai.client import AICheckError
from config.database import DatabaseCheckError
from config.settings import Settings
from exchange.rest_client import ExchangeCheckError
from services import integration_service as service
from services.integration_service import CheckResult, ReadinessCache
from telegram_bot.alerts import TelegramCheckError


def returning(value: object) -> Callable:
    async def fake(settings: Settings) -> object:
        return value

    return fake


def raising(error: Exception) -> Callable:
    async def fake(settings: Settings) -> None:
        raise error

    return fake


@pytest.fixture
def all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "check_database", returning("arbipilot_dev"))
    monkeypatch.setattr(service, "check_exchange", returning(12))
    monkeypatch.setattr(service, "check_claude", returning("test-model"))
    monkeypatch.setattr(service, "check_telegram", returning(None))


async def test_all_checks_pass(
    all_ok: None, make_settings: Callable[..., Settings]
) -> None:
    results = await service.run_all_checks(make_settings())
    assert [(r.name, r.ok) for r in results] == [
        ("database", True),
        ("binance", True),
        ("claude", True),
        ("telegram", True),
    ]
    assert results[0].detail == "arbipilot_dev"


async def test_startup_checks_leave_telegram_out(
    all_ok: None, make_settings: Callable[..., Settings]
) -> None:
    results = await service.run_startup_checks(make_settings())
    assert [r.name for r in results] == ["database", "binance", "claude"]


async def test_a_failure_becomes_a_result_and_does_not_stop_the_others(
    all_ok: None,
    monkeypatch: pytest.MonkeyPatch,
    make_settings: Callable[..., Settings],
) -> None:
    monkeypatch.setattr(
        service, "check_database", raising(DatabaseCheckError("not configured"))
    )
    monkeypatch.setattr(
        service, "check_exchange", raising(ExchangeCheckError("no binance"))
    )
    monkeypatch.setattr(service, "check_claude", raising(AICheckError("no claude")))
    monkeypatch.setattr(
        service, "check_telegram", raising(TelegramCheckError("no telegram"))
    )
    results = await service.run_all_checks(make_settings())
    assert results == [
        CheckResult("database", False, "not configured"),
        CheckResult("binance", False, "no binance"),
        CheckResult("claude", False, "no claude"),
        CheckResult("telegram", False, "no telegram"),
    ]


async def test_readiness_is_reused_for_a_short_time(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    rounds = 0

    async def fake_run(settings: Settings) -> list[CheckResult]:
        nonlocal rounds
        rounds += 1
        return [CheckResult("database", True)]

    monkeypatch.setattr(service, "run_all_checks", fake_run)
    cache = ReadinessCache(max_age_seconds=60)
    await cache.get(make_settings())
    await cache.get(make_settings())
    assert rounds == 1


async def test_readiness_is_checked_again_when_it_is_old(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    rounds = 0

    async def fake_run(settings: Settings) -> list[CheckResult]:
        nonlocal rounds
        rounds += 1
        return []

    monkeypatch.setattr(service, "run_all_checks", fake_run)
    cache = ReadinessCache(max_age_seconds=0)
    await cache.get(make_settings())
    await cache.get(make_settings())
    assert rounds == 2


async def test_an_unplanned_error_is_a_failed_check_and_hides_its_text(
    all_ok: None,
    monkeypatch: pytest.MonkeyPatch,
    make_settings: Callable[..., Settings],
) -> None:
    error = RuntimeError("something with test-key inside")
    for name in ("check_database", "check_exchange", "check_claude", "check_telegram"):
        monkeypatch.setattr(service, name, raising(error))
    results = await service.run_all_checks(make_settings())
    assert [r.ok for r in results] == [False, False, False, False]
    assert {r.detail for r in results} == {"unexpected error (RuntimeError)"}
