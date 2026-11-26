"""Host, port and the startup report (docs/project-brief.md section 6)."""

import socket
from collections.abc import Callable

import pytest

from config.server import StartupReport, bind_port, server_host
from config.settings import Settings
from services.integration_service import CheckResult

DATABASE_OK = CheckResult("database", True, "arbipilot_dev")
BINANCE_OK = CheckResult("binance", True)
CLAUDE_OK = CheckResult("claude", True, "test-model")


def report(
    settings: Settings,
    port_error: str | None = None,
    database: CheckResult = DATABASE_OK,
    binance: CheckResult = BINANCE_OK,
    claude: CheckResult = CLAUDE_OK,
) -> StartupReport:
    return StartupReport(settings, port_error, [database, binance, claude])


def test_development_listens_on_the_laptop_only(
    make_settings: Callable[..., Settings],
) -> None:
    assert server_host(make_settings()) == "127.0.0.1"


def test_success_prints_exactly_the_contract_lines(
    make_settings: Callable[..., Settings],
) -> None:
    result = report(make_settings())
    assert result.lines() == [
        "✔ Running on port 3000",
        "✔ Database connected successfully (arbipilot_dev)",
        "✔ Server connected successfully",
        "✔ Claude API connected successfully",
        "Environment: DEVELOPMENT",
        "Mode: SHADOW",
    ]
    assert result.fatal is False


def test_database_failure_is_fatal_and_replaces_its_line(
    make_settings: Callable[..., Settings],
) -> None:
    result = report(
        make_settings(), database=CheckResult("database", False, "not configured")
    )
    lines = result.lines()
    assert lines[1] == "✖ Database connection failed: not configured"
    # Every other result is still shown, so the owner sees everything at once.
    assert lines[0] == "✔ Running on port 3000"
    assert lines[2] == "✔ Server connected successfully"
    assert len(lines) == 6
    assert result.fatal is True


def test_binance_failure_is_fatal(make_settings: Callable[..., Settings]) -> None:
    result = report(
        make_settings(), binance=CheckResult("binance", False, "could not reach")
    )
    assert result.lines()[2] == "✖ Server connection failed: could not reach"
    assert result.fatal is True


def test_port_failure_is_fatal(make_settings: Callable[..., Settings]) -> None:
    result = report(make_settings(), port_error="Address already in use")
    assert result.lines()[0] == "✖ Port 3000 failed: Address already in use"
    assert result.fatal is True


def test_claude_failure_is_not_fatal_but_is_announced(
    make_settings: Callable[..., Settings],
) -> None:
    result = report(
        make_settings(), claude=CheckResult("claude", False, "key was refused")
    )
    assert result.lines()[3] == "✖ Claude API connection failed: key was refused"
    assert result.fatal is False
    assert result.claude_ok is False
    assert "new entries are DISABLED" in result.telegram_text()


def test_a_check_that_did_not_run_counts_as_failed(
    make_settings: Callable[..., Settings],
) -> None:
    assert StartupReport(make_settings(), None, []).fatal is True


def test_telegram_text_says_when_the_app_did_not_start(
    make_settings: Callable[..., Settings],
) -> None:
    result = report(make_settings(), database=CheckResult("database", False, "down"))
    text = result.telegram_text()
    assert text.startswith("ArbiPilot did NOT start")
    assert "✖ Database connection failed: down" in text


def test_bound_port_accepts_connections_and_a_second_bind_fails(
    make_settings: Callable[..., Settings],
) -> None:
    # Deliberate: this opens a socket on this machine's own loopback address
    # only (nothing leaves the laptop). It is the proof that the
    # "Running on port" line is true when printed.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    settings = make_settings(port=free_port)

    listening = bind_port(settings)
    try:
        with socket.create_connection(("127.0.0.1", free_port), timeout=2):
            pass
        with pytest.raises(OSError):
            bind_port(settings)
    finally:
        listening.close()
