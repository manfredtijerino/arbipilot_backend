"""`server.py`: the order of startup and the exit codes. Nothing real connects."""

import socket
from collections.abc import Callable

import pytest

import server
from config.environment import GuardRailError
from config.settings import Settings, SettingsError
from services.integration_service import CheckResult
from telegram_bot.alerts import TelegramCheckError

OK_CHECKS = [
    CheckResult("database", True, "arbipilot_dev"),
    CheckResult("binance", True),
    CheckResult("claude", True, "test-model"),
]


class _Harness:
    """Replaces the port, the checks, Telegram and uvicorn with recorders."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.checks = list(OK_CHECKS)
        self.events: list[str] = []
        self.telegram: list[str] = []
        self.served_apps: list = []
        self.port_error: OSError | None = None
        self.sock = socket.socket()

        def fake_bind(settings: Settings) -> socket.socket:
            self.events.append("port")
            if self.port_error:
                raise self.port_error
            return self.sock

        async def fake_checks(settings: Settings) -> list[CheckResult]:
            self.events.append("checks")
            return self.checks

        async def fake_alert(settings: Settings, text: str) -> None:
            self.events.append("telegram")
            self.telegram.append(text)

        harness = self

        class FakeServer:
            def __init__(self, config: object) -> None:
                self.config = config

            async def serve(self, sockets: list) -> None:
                harness.events.append("serve")
                harness.served_apps.append(self.config.app)

        async def fake_dispose() -> None:
            return None

        monkeypatch.setattr(server, "bind_port", fake_bind)
        monkeypatch.setattr(server, "run_startup_checks", fake_checks)
        monkeypatch.setattr(server, "send_alert", fake_alert)
        monkeypatch.setattr(server, "dispose_engine", fake_dispose)
        monkeypatch.setattr(server.uvicorn, "Server", FakeServer)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    harness = _Harness(monkeypatch)
    yield harness
    harness.sock.close()


async def test_success_prints_the_lines_then_serves(
    harness: _Harness,
    make_settings: Callable[..., Settings],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await server.run(make_settings()) == 0
    assert capsys.readouterr().out.splitlines() == [
        "✔ Running on port 3000",
        "✔ Database connected successfully (arbipilot_dev)",
        "✔ Server connected successfully",
        "✔ Claude API connected successfully",
        "Environment: DEVELOPMENT",
        "Mode: SHADOW",
    ]
    # The port is open and the checks are done before anything is announced.
    assert harness.events == ["port", "checks", "telegram", "serve"]
    assert harness.served_apps[0].state.new_entries_enabled is True
    assert harness.telegram[0].startswith("ArbiPilot started")


async def test_database_failure_prints_everything_and_exits_1(
    harness: _Harness,
    make_settings: Callable[..., Settings],
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness.checks[0] = CheckResult("database", False, "not configured")
    assert await server.run(make_settings()) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "✖ Database connection failed: not configured"
    assert len(out) == 6
    assert "serve" not in harness.events
    assert harness.telegram[0].startswith("ArbiPilot did NOT start")


async def test_port_in_use_exits_1(
    harness: _Harness,
    make_settings: Callable[..., Settings],
    capsys: pytest.CaptureFixture[str],
) -> None:
    harness.port_error = OSError(48, "Address already in use")
    assert await server.run(make_settings()) == 1
    assert capsys.readouterr().out.startswith(
        "✖ Port 3000 failed: Address already in use"
    )
    assert "serve" not in harness.events


async def test_claude_failure_starts_with_new_entries_off(
    harness: _Harness, make_settings: Callable[..., Settings]
) -> None:
    harness.checks[2] = CheckResult("claude", False, "key was refused")
    assert await server.run(make_settings()) == 0
    assert harness.events[-1] == "serve"
    assert harness.served_apps[0].state.new_entries_enabled is False
    assert "new entries are DISABLED" in harness.telegram[0]


async def test_a_telegram_problem_does_not_stop_the_app(
    harness: _Harness,
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_alert(settings: Settings, text: str) -> None:
        raise TelegramCheckError("could not reach Telegram")

    monkeypatch.setattr(server, "send_alert", broken_alert)
    assert await server.run(make_settings()) == 0
    assert harness.events[-1] == "serve"


@pytest.mark.parametrize(
    "error",
    [
        GuardRailError("mainnet Binance keys must be empty in development"),
        SettingsError("Invalid .env settings -> JWT_SECRET: Field required"),
    ],
)
def test_a_settings_problem_prints_one_line_and_connects_to_nothing(
    harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    def refuse() -> Settings:
        raise error

    monkeypatch.setattr(server, "get_settings", refuse)
    assert server.main() == 1
    assert capsys.readouterr().out.splitlines() == [f"✖ Startup refused: {error}"]
    assert harness.events == []


def test_an_unplanned_error_exits_1_without_a_traceback(
    harness: _Harness,
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def explode(settings: Settings) -> list[CheckResult]:
        raise RuntimeError("something with test-key inside")

    monkeypatch.setattr(server, "get_settings", make_settings)
    monkeypatch.setattr(server, "setup_logging", lambda settings: None)
    monkeypatch.setattr(server, "run_startup_checks", explode)
    assert server.main() == 1
    captured = capsys.readouterr()
    assert "✖ Startup failed: unexpected error (RuntimeError)" in captured.out
    assert "test-key" not in captured.out + captured.err
