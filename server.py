"""Where the app starts:  python server.py

Order (docs/project-brief.md section 6):
1. Read `.env` and apply the development/production guard rails. A problem
   here prints one line and stops before anything connects.
2. Open the port, then check the database, Binance and the Claude API.
3. Print the status lines. Each one is already true when it is printed.
4. Stop with exit code 1 if the port, the database or Binance failed.
   A Claude API failure does not stop the app: it starts with new entries off.
5. Tell the owner on Telegram, then serve the API.

This file only wires things together. The logic lives in `config/`,
`services/` and the other packages.
"""

import asyncio
import logging
import socket
import sys

import uvicorn

from config.database import dispose_engine
from config.environment import GuardRailError
from config.logging import setup_logging
from config.server import FAILED, StartupReport, bind_port, create_app
from config.settings import Settings, SettingsError, get_settings
from services.integration_service import run_startup_checks
from telegram_bot.alerts import TelegramCheckError, send_alert

logger = logging.getLogger("server")


def open_port(settings: Settings) -> tuple[socket.socket | None, str | None]:
    """The listening socket, or a plain reason why the port could not be opened."""
    try:
        return bind_port(settings), None
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        return None, f"{reason} (is another copy of the app running?)"


async def notify_owner(settings: Settings, report: StartupReport) -> None:
    """Send the startup result to Telegram. A Telegram problem never stops the app."""
    try:
        await send_alert(settings, report.telegram_text())
    except TelegramCheckError as exc:
        logger.warning("startup message not sent to Telegram: %s", exc)


async def run(settings: Settings) -> int:
    """Start the app. Returns the process exit code."""
    sock, port_error = open_port(settings)
    report = StartupReport(
        settings=settings,
        port_error=port_error,
        checks=await run_startup_checks(settings),
    )
    for line in report.lines():
        print(line, flush=True)
    await notify_owner(settings, report)

    if report.fatal or sock is None:
        if sock is not None:
            sock.close()
        await dispose_engine()
        return 1

    app = create_app(settings)
    app.state.new_entries_enabled = report.claude_ok
    if not report.claude_ok:
        logger.warning("claude api unavailable: new entries are disabled")

    # log_config=None keeps our own log format (UTC, [DEV] prefix) for uvicorn too.
    server = uvicorn.Server(uvicorn.Config(app, log_config=None))
    await server.serve(sockets=[sock])
    return 0


def main() -> int:
    try:
        settings = get_settings()
    except (SettingsError, GuardRailError) as exc:
        # One clear line, then stop: nothing has connected yet.
        print(f"{FAILED} Startup refused: {exc}", flush=True)
        return 1
    setup_logging(settings)
    try:
        return asyncio.run(run(settings))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Through the logger, so the line is in our format with secrets hidden.
        logger.error("startup failed unexpectedly type=%s", type(exc).__name__)
        print(f"{FAILED} Startup failed: unexpected error ({type(exc).__name__})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
