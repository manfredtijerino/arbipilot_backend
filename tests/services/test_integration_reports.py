"""The detailed connection reports. Every outside call is replaced by a fake."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from ai.client import AICheckError
from config.database import DatabaseCheckError, DatabaseFacts
from config.settings import Settings
from exchange.rest_client import BinanceKey, ExchangeCheckError
from monitoring.healthchecks import HealthchecksError
from monitoring.server_info import MachineFacts, ServerInfoError
from services import integration_service as service
from telegram_bot.alerts import TelegramCheckError
from tests.conftest import FakeClock

MAINNET = "https://api.binance.com"

ACCOUNT = {
    "canTrade": True,
    "canWithdraw": True,
    "commissionRates": {"maker": "0.00100000", "taker": "0.00100000"},
    "balances": [
        {"asset": "BTC", "free": "1.00000000", "locked": "0.00000000"},
        {"asset": "USDT", "free": "250.10000000", "locked": "49.90000000"},
        {"asset": "BNB", "free": "0.02500000", "locked": "0.00000000"},
    ],
}
SAFE_READ_KEY = {
    "ipRestrict": True,
    "enableWithdrawals": False,
    "enableSpotAndMarginTrading": False,
    "enableInternalTransfer": False,
    "permitsUniversalTransfer": False,
    "enableMargin": False,
    "enableFutures": False,
    "enableVanillaOptions": False,
    "enablePortfolioMarginTrading": False,
}
SAFE_TRADE_KEY = {**SAFE_READ_KEY, "enableSpotAndMarginTrading": True}


def async_returning(value: Any) -> Callable:
    async def fake(*args: Any, **kwargs: Any) -> Any:
        return value

    return fake


def async_raising(error: Exception) -> Callable:
    async def fake(*args: Any, **kwargs: Any) -> None:
        raise error

    return fake


@pytest.fixture
def laptop(make_settings: Callable[..., Settings]) -> Settings:
    """Development: only the testnet key, public data from the real exchange."""
    return make_settings(
        binance_base_url=MAINNET,
        binance_testnet_key="test-key",
        binance_testnet_secret="test-secret",
    )


@pytest.fixture
def server(make_settings: Callable[..., Settings]) -> Settings:
    """Production: all three keys."""
    return make_settings(
        app_env="production",
        postgres_db="arbipilot_prod",
        binance_base_url=MAINNET,
        binance_testnet_key="test-key",
        binance_testnet_secret="test-secret",
        binance_read_key="read-key",
        binance_read_secret="read-secret",
        binance_api_key="trade-key",
        binance_api_secret="trade-secret",
        expected_public_ip="203.0.113.7",
    )


@pytest.fixture
def binance(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A pretend Binance. Tests change what it answers per key name."""
    world: dict[str, Any] = {
        "account": {name: ACCOUNT for name in ("testnet", "read", "trade")},
        "restrictions": {"read": SAFE_READ_KEY, "trade": SAFE_TRADE_KEY},
        "asked_restrictions": [],
    }

    async def fake_account(key: BinanceKey, client: object) -> dict:
        answer = world["account"][key.name]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def fake_restrictions(key: BinanceKey, client: object) -> dict:
        world["asked_restrictions"].append(key.name)
        return world["restrictions"][key.name]

    monkeypatch.setattr(service, "check_exchange", async_returning(60))
    monkeypatch.setattr(service, "fetch_account", fake_account)
    monkeypatch.setattr(service, "fetch_key_restrictions", fake_restrictions)
    return world


# --- Binance ---


async def test_laptop_reports_the_testnet_key(laptop: Settings, binance: dict) -> None:
    report = await service.binance_report(laptop)
    assert (report.status, report.detail) == ("ok", "")
    assert report.reachable and report.clock_difference_ms == 60
    assert report.host == "api.binance.com"
    (key,) = report.keys
    assert (key.name, key.exchange, key.ok, key.valid) == (
        "testnet",
        "testnet",
        True,
        True,
    )
    assert key.trading_allowed is True
    assert (key.maker_fee, key.taker_fee) == ("0.00100000", "0.00100000")
    # The testnet cannot answer these two, and the report says so.
    assert key.withdrawals_enabled is None and key.ip_restricted is None
    assert "cannot be checked here" in key.detail
    assert binance["asked_restrictions"] == []


async def test_server_reports_all_three_keys_as_safe(
    server: Settings, binance: dict
) -> None:
    report = await service.binance_report(server)
    assert report.status == "ok"
    keys = {key.name: key for key in report.keys}
    assert set(keys) == {"testnet", "read", "trade"}
    assert keys["read"].exchange == keys["trade"].exchange == "mainnet"
    assert keys["read"].withdrawals_enabled is False and keys["read"].ip_restricted
    assert keys["read"].trading_allowed is False
    assert keys["trade"].trading_allowed is True
    assert keys["read"].spot_only is True and keys["trade"].spot_only is True
    assert keys["testnet"].spot_only is None  # the testnet cannot say
    assert sorted(binance["asked_restrictions"]) == ["read", "trade"]


async def test_withdrawals_enabled_is_a_loud_failure(
    server: Settings, binance: dict
) -> None:
    binance["restrictions"]["trade"] = {**SAFE_TRADE_KEY, "enableWithdrawals": True}
    report = await service.binance_report(server)
    assert report.status == "failed"
    assert "trade key: WITHDRAWALS ARE ENABLED" in report.detail
    trade = next(key for key in report.keys if key.name == "trade")
    assert trade.ok is False and trade.withdrawals_enabled is True


async def test_a_missing_withdrawal_answer_is_never_read_as_safe(
    server: Settings, binance: dict
) -> None:
    without = {k: v for k, v in SAFE_READ_KEY.items() if k != "enableWithdrawals"}
    binance["restrictions"]["read"] = without
    report = await service.binance_report(server)
    read = next(key for key in report.keys if key.name == "read")
    assert report.status == "failed" and read.withdrawals_enabled is None
    assert "could not confirm that withdrawals are disabled" in read.detail


@pytest.mark.parametrize("strange", ["missing", None, "false", 0, "true"])
async def test_a_missing_trading_answer_never_makes_the_read_key_look_safe(
    server: Settings, binance: dict, strange: object
) -> None:
    answer = dict(SAFE_READ_KEY)
    if strange == "missing":
        del answer["enableSpotAndMarginTrading"]
    else:
        answer["enableSpotAndMarginTrading"] = strange
    binance["restrictions"]["read"] = answer
    report = await service.binance_report(server)
    read = next(key for key in report.keys if key.name == "read")
    assert report.status == "failed" and read.ok is False
    assert read.trading_allowed is None
    assert "could not confirm the key's trading permission" in read.detail


@pytest.mark.parametrize("strange", ["missing", None, "true", 1])
async def test_a_missing_ip_lock_answer_is_never_read_as_locked(
    server: Settings, binance: dict, strange: object
) -> None:
    answer = dict(SAFE_TRADE_KEY)
    if strange == "missing":
        del answer["ipRestrict"]
    else:
        answer["ipRestrict"] = strange
    binance["restrictions"]["trade"] = answer
    report = await service.binance_report(server)
    trade = next(key for key in report.keys if key.name == "trade")
    assert report.status == "failed" and trade.ip_restricted is None
    assert "could not confirm the key is locked" in trade.detail


@pytest.mark.parametrize(
    ("field", "label"), sorted(service.FORBIDDEN_PERMISSIONS.items())
)
async def test_spot_only_every_other_permission_must_be_off(
    server: Settings, binance: dict, field: str, label: str
) -> None:
    # Switched on: a loud failure.
    binance["restrictions"]["trade"] = {**SAFE_TRADE_KEY, field: True}
    report = await service.binance_report(server)
    trade = next(key for key in report.keys if key.name == "trade")
    assert report.status == "failed" and trade.spot_only is False
    assert f"{label} are switched on; this bot is Spot only" in trade.detail
    # Not answered: not assumed to be off.
    binance["restrictions"]["trade"] = {
        k: v for k, v in SAFE_TRADE_KEY.items() if k != field
    }
    report = await service.binance_report(server)
    trade = next(key for key in report.keys if key.name == "trade")
    assert report.status == "failed" and trade.spot_only is None
    assert f"could not confirm {label} are off" in trade.detail


async def test_a_trade_key_on_an_account_that_cannot_trade_fails(
    server: Settings, binance: dict
) -> None:
    binance["account"]["trade"] = {**ACCOUNT, "canTrade": False}
    report = await service.binance_report(server)
    assert report.status == "failed"
    assert "trade key: the account itself is not allowed to trade" in report.detail


@pytest.mark.parametrize(
    "rates", [None, {}, {"maker": "0.001"}, {"maker": "-0.001", "taker": "0.001"}]
)
async def test_missing_or_strange_fee_rates_fail_the_key(
    laptop: Settings, binance: dict, rates: object
) -> None:
    binance["account"]["testnet"] = {**ACCOUNT, "commissionRates": rates}
    report = await service.binance_report(laptop)
    assert report.status == "failed"
    assert "Binance did not report the fee rates" in report.detail


async def test_a_wrong_address_with_mainnet_keys_is_not_called_unreachable(
    server: Settings, binance: dict
) -> None:
    broken = server.model_copy(update={"binance_base_url": "https://example.test"})
    report = await service.binance_report(broken)
    assert report.status == "failed" and report.reachable is True
    assert "not one of Binance's own" in report.detail and report.keys == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", "0"),
        ("250.10000000", "250.10000000"),
        ("0.00075", "0.00075"),
        ("-5", None),
        ("+5", None),
        ("1E+3", None),
        ("1e999999", None),
        ("NaN", None),
        ("Infinity", None),
        (" 1 ", None),
        ("1_000", None),
        ("1.", None),
        (".5", None),
        ("", None),
        (1.5, None),
        (1, None),
        (None, None),
    ],
)
def test_only_plain_numbers_as_text_are_accepted(
    text: object, expected: str | None
) -> None:
    assert service._decimal_text(text) == expected


@pytest.mark.parametrize(
    ("name", "change", "expected"),
    [
        ("read", {"ipRestrict": False}, "not locked to an IP address"),
        ("read", {"enableSpotAndMarginTrading": True}, "read key is allowed to trade"),
        ("trade", {"enableSpotAndMarginTrading": False}, "not allowed to trade"),
    ],
)
async def test_an_unsafe_key_setting_fails_the_check(
    server: Settings, binance: dict, name: str, change: dict, expected: str
) -> None:
    binance["restrictions"][name] = {**binance["restrictions"][name], **change}
    report = await service.binance_report(server)
    assert report.status == "failed" and expected in report.detail


async def test_a_refused_key_is_reported_with_the_reason(
    laptop: Settings, binance: dict
) -> None:
    binance["account"]["testnet"] = ExchangeCheckError("Binance refused the key")
    report = await service.binance_report(laptop)
    (key,) = report.keys
    assert report.status == "failed" and report.reachable
    assert (key.valid, key.ok, key.detail) == (False, False, "Binance refused the key")
    assert key.trading_allowed is None


async def test_a_testnet_key_that_cannot_trade_fails(
    laptop: Settings, binance: dict
) -> None:
    binance["account"]["testnet"] = {**ACCOUNT, "canTrade": False}
    report = await service.binance_report(laptop)
    assert report.status == "failed" and "not allowed to trade" in report.detail


async def test_unreachable_binance_stops_before_any_key_is_sent(
    laptop: Settings, binance: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service,
        "check_exchange",
        async_raising(ExchangeCheckError("could not reach Binance")),
    )
    monkeypatch.setattr(service, "fetch_account", async_raising(AssertionError("sent")))
    report = await service.binance_report(laptop)
    assert (report.status, report.reachable, report.keys) == ("failed", False, [])
    assert report.detail == "could not reach Binance"


async def test_no_key_at_all_is_a_failure(
    make_settings: Callable[..., Settings], binance: dict
) -> None:
    report = await service.binance_report(make_settings(binance_base_url=MAINNET))
    assert report.status == "failed" and "no Binance key" in report.detail


async def test_an_unplanned_error_never_escapes_or_leaks(
    laptop: Settings, binance: dict
) -> None:
    binance["account"]["testnet"] = RuntimeError("test-secret inside")
    report = await service.binance_report(laptop)
    assert report.status == "failed"
    assert report.detail == "unexpected error (RuntimeError)"


# --- balances ---


async def test_balances_are_usdt_and_bnb_as_text(
    laptop: Settings, binance: dict
) -> None:
    report = await service.balances_report(laptop)
    assert (report.status, report.exchange) == ("ok", "testnet")
    assert "pretend money" in report.detail
    usdt, bnb = report.balances
    assert (usdt.asset, usdt.free, usdt.locked, usdt.total) == (
        "USDT",
        "250.10000000",
        "49.90000000",
        "300.00000000",
    )
    assert (bnb.asset, bnb.total) == ("BNB", "0.02500000")
    assert all(isinstance(v, str) for b in report.balances for v in vars(b).values())


async def test_an_asset_binance_does_not_list_is_zero(
    laptop: Settings, binance: dict
) -> None:
    binance["account"]["testnet"] = {**ACCOUNT, "balances": []}
    report = await service.balances_report(laptop)
    assert [(b.asset, b.total) for b in report.balances] == [
        ("USDT", "0"),
        ("BNB", "0"),
    ]


@pytest.mark.parametrize("balances", ["missing", None, {}, "none"])
async def test_a_strange_balance_list_is_never_shown_as_an_empty_account(
    laptop: Settings, binance: dict, balances: object
) -> None:
    account = {k: v for k, v in ACCOUNT.items() if k != "balances"}
    if balances != "missing":
        account["balances"] = balances
    binance["account"]["testnet"] = account
    report = await service.balances_report(laptop)
    assert report.status == "failed" and report.balances == []
    assert report.detail == "Binance sent a balance we could not read"


@pytest.mark.parametrize("amount", ["-5", "1E+3", " 1", 12.5])
async def test_a_balance_that_is_not_a_plain_number_is_refused(
    laptop: Settings, binance: dict, amount: object
) -> None:
    binance["account"]["testnet"] = {
        "balances": [{"asset": "USDT", "free": amount, "locked": "0"}]
    }
    report = await service.balances_report(laptop)
    assert report.status == "failed" and report.balances == []


async def test_a_balance_that_is_not_a_number_is_refused(
    laptop: Settings, binance: dict
) -> None:
    binance["account"]["testnet"] = {
        "balances": [{"asset": "USDT", "free": "NaN", "locked": "0"}]
    }
    report = await service.balances_report(laptop)
    assert report.status == "failed" and report.balances == []


def test_which_key_reads_the_account(
    laptop: Settings, server: Settings, make_settings: Callable[..., Settings]
) -> None:
    assert service.account_key(laptop).name == "testnet"
    assert service.account_key(server).name == "read"
    testnet_mode = server.model_copy(update={"trading_mode": "testnet"})
    assert service.account_key(testnet_mode).name == "testnet"
    # Production without a read key never quietly shows testnet money.
    no_read = make_settings(
        app_env="production",
        postgres_db="arbipilot_prod",
        binance_testnet_key="test-key",
        binance_testnet_secret="test-secret",
    )
    assert service.account_key(no_read) is None
    only_trade = make_settings(
        app_env="production",
        postgres_db="arbipilot_prod",
        binance_base_url=MAINNET,
        binance_api_key="trade-key",
        binance_api_secret="trade-secret",
    )
    assert service.account_key(only_trade) is None  # the trade key never reads


async def test_balances_fail_plainly(
    laptop: Settings, binance: dict, make_settings: Callable[..., Settings]
) -> None:
    binance["account"]["testnet"] = ExchangeCheckError("Binance refused the key")
    report = await service.balances_report(laptop)
    assert (report.status, report.detail) == ("failed", "Binance refused the key")
    report = await service.balances_report(make_settings())
    assert report.status == "failed" and "no Binance key" in report.detail


# --- database ---


async def test_database_at_the_latest_migration(
    laptop: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = DatabaseFacts("arbipilot_dev", "18.6", "0002")
    monkeypatch.setattr(service, "read_database_facts", async_returning(facts))
    monkeypatch.setattr(service, "latest_migration", lambda: "0002")
    report = await service.database_report(laptop)
    assert (report.status, report.detail) == ("ok", "")
    assert (report.name, report.version) == ("arbipilot_dev", "18.6")
    assert report.applied_migration == report.latest_migration == "0002"


@pytest.mark.parametrize(("applied", "shown"), [("0001", "0001"), (None, "none")])
async def test_database_behind_the_code_is_a_failure(
    laptop: Settings, monkeypatch: pytest.MonkeyPatch, applied: str | None, shown: str
) -> None:
    facts = DatabaseFacts("arbipilot_dev", "18.6", applied)
    monkeypatch.setattr(service, "read_database_facts", async_returning(facts))
    monkeypatch.setattr(service, "latest_migration", lambda: "0002")
    report = await service.database_report(laptop)
    assert report.status == "failed"
    assert (
        report.detail == f"the tables are at migration {shown}, the code expects 0002"
    )


async def test_database_unreachable(
    laptop: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service, "read_database_facts", async_raising(DatabaseCheckError("timed out"))
    )
    report = await service.database_report(laptop)
    assert (report.status, report.detail, report.name) == ("failed", "timed out", None)


def test_the_latest_migration_is_read_from_the_files() -> None:
    from database.migrations.head import latest_migration

    assert latest_migration() == "0004"


# --- Claude ---


async def test_claude_ok_and_failed(
    laptop: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "check_claude", async_returning("test-model"))
    report = await service.claude_report(laptop)
    assert (report.status, report.model) == ("ok", "test-model")
    assert report.usage_today_usd is None and report.daily_budget_usd is None

    monkeypatch.setattr(
        service,
        "check_claude",
        async_raising(AICheckError("the Anthropic key was refused")),
    )
    report = await service.claude_report(laptop)
    assert (report.status, report.detail, report.model) == (
        "failed",
        "the Anthropic key was refused",
        None,
    )


# --- Telegram ---


async def test_telegram_test_sends_one_message(
    laptop: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    async def fake_send(settings: Settings, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr(service, "send_alert", fake_send)
    report = await service.telegram_test(laptop)
    assert report.status == "ok" and sent == [service.TELEGRAM_TEST_TEXT]

    monkeypatch.setattr(
        service,
        "send_alert",
        async_raising(TelegramCheckError("could not reach Telegram")),
    )
    report = await service.telegram_test(laptop)
    assert (report.status, report.detail) == ("failed", "could not reach Telegram")


# --- Healthchecks ---


async def test_healthchecks_empty_on_the_laptop_is_not_a_failure(
    laptop: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service.healthchecks, "send_ping", async_raising(AssertionError("sent"))
    )
    report = await service.healthchecks_test(laptop)
    assert report.status == "not_configured"


async def test_healthchecks_ping_ok_and_failed(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(healthchecks_ping_url="https://hc-ping.com/test-check-id")
    monkeypatch.setattr(service.healthchecks, "send_ping", async_returning(None))
    assert (await service.healthchecks_test(settings)).status == "ok"
    monkeypatch.setattr(
        service.healthchecks,
        "send_ping",
        async_raising(HealthchecksError("could not reach Healthchecks.io")),
    )
    report = await service.healthchecks_test(settings)
    assert (report.status, report.detail) == (
        "failed",
        "could not reach Healthchecks.io",
    )


# --- the machine ---

MACHINE = MachineFacts(
    machine_uptime_seconds=86_400,
    memory_total_mb=2048,
    memory_available_mb=1024,
    disk_total_gb=60.0,
    disk_free_gb=45.5,
)


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch, fake_clock: FakeClock) -> FakeClock:
    monkeypatch.setattr(service.clock, "utc_now", fake_clock)
    monkeypatch.setattr(service.server_info, "read_machine", lambda: MACHINE)
    monkeypatch.setattr(
        service.server_info, "fetch_public_ip", async_returning("203.0.113.7")
    )
    monkeypatch.setattr(service, "check_exchange", async_returning(-40))
    return fake_clock


async def test_laptop_server_report(laptop: Settings, machine: FakeClock) -> None:
    started = machine.now - timedelta(minutes=5)
    report = await service.server_report(laptop, started)
    assert (report.status, report.detail, report.environment) == (
        "ok",
        "",
        "development",
    )
    assert report.app_uptime_seconds == 300
    assert report.machine_uptime_seconds == 86_400
    assert (report.memory_total_mb, report.disk_free_gb) == (2048, 45.5)
    assert report.public_ip == "203.0.113.7" and report.clock_difference_ms == -40
    # No address is expected on the laptop, so there is nothing to compare.
    assert report.expected_public_ip is None and report.public_ip_matches is None


async def test_server_address_matches_what_binance_expects(
    server: Settings, machine: FakeClock
) -> None:
    report = await service.server_report(server, machine.now)
    assert report.status == "ok" and report.public_ip_matches is True


async def test_a_changed_address_is_a_failure(
    server: Settings, machine: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service.server_info, "fetch_public_ip", async_returning("198.51.100.9")
    )
    report = await service.server_report(server, machine.now)
    assert report.status == "failed" and report.public_ip_matches is False
    assert "not the one Binance expects" in report.detail


async def test_server_report_survives_both_outside_calls_failing(
    server: Settings, machine: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service.server_info,
        "fetch_public_ip",
        async_raising(ServerInfoError("could not find out the public address")),
    )
    monkeypatch.setattr(
        service,
        "check_exchange",
        async_raising(ExchangeCheckError("could not reach Binance")),
    )
    report = await service.server_report(server, machine.now)
    assert report.status == "failed"
    assert report.public_ip is None and report.clock_difference_ms is None
    assert report.public_ip_matches is None
    assert "could not find out the public address" in report.detail
    assert "clock check: could not reach Binance" in report.detail
    assert report.memory_total_mb == 2048  # the local facts are still there


async def test_server_report_survives_the_machine_facts_failing(
    laptop: Settings, machine: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise PermissionError("/proc is not readable")

    monkeypatch.setattr(service.server_info, "read_machine", broken)
    report = await service.server_report(laptop, machine.now)
    assert report.status == "failed"
    assert report.detail == "machine facts: unexpected error (PermissionError)"
    assert report.memory_total_mb is None and report.disk_free_gb is None
    assert report.public_ip == "203.0.113.7"  # the rest is still reported


# --- not too often ---


class Ticker:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_a_read_check_is_reused_for_fifteen_seconds() -> None:
    ticker = Ticker()
    throttle = service.CheckThrottle(now=ticker)
    runs: list[int] = []

    async def produce() -> int:
        runs.append(len(runs) + 1)
        return runs[-1]

    assert await throttle.cached("binance", produce) == 1
    ticker.now += 14
    assert await throttle.cached("binance", produce) == 1  # the same answer
    assert await throttle.cached("database", produce) == 2  # another check
    ticker.now += 1
    assert await throttle.cached("binance", produce) == 3  # fresh again
    assert runs == [1, 2, 3]


async def test_callers_at_the_same_moment_share_one_run() -> None:
    import asyncio

    throttle = service.CheckThrottle()
    runs: list[int] = []

    async def produce() -> str:
        runs.append(1)
        await asyncio.sleep(0)
        return "report"

    answers = await asyncio.gather(*(throttle.cached("x", produce) for _ in range(5)))
    assert answers == ["report"] * 5 and runs == [1]


def test_an_action_is_allowed_once_a_minute() -> None:
    from services.errors import TooManyRequests

    ticker = Ticker()
    throttle = service.CheckThrottle(now=ticker)
    throttle.start_action("telegram")
    throttle.start_action("healthchecks")  # each action has its own minute
    ticker.now += 0.5
    with pytest.raises(TooManyRequests) as refused:
        throttle.start_action("telegram")
    assert refused.value.retry_after_seconds == 60
    ticker.now += 59
    with pytest.raises(TooManyRequests) as refused:
        throttle.start_action("telegram")
    assert refused.value.retry_after_seconds == 1
    ticker.now += 0.5
    throttle.start_action("telegram")
