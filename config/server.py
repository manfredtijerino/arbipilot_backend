"""Server setup: host, port, the FastAPI app, and the startup report.

`server.py` calls these in order. Nothing here prints; the report only builds
the status lines, so every line is true by the time it is shown.
"""

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import register_error_handlers
from api.router import api_router
from config.database import dispose_engine
from config.decisions import Decisions, load_decisions
from config.settings import Settings
from config.version import APP_VERSION
from services import clock
from services.integration_service import CheckResult, CheckThrottle, ReadinessCache
from services.market_service import MarketData
from trading.account import starting_account
from trading.risk import RiskEngine

OK = "✔"
FAILED = "✖"


def server_host(settings: Settings) -> str:
    """Development listens on the laptop only. The container listens on all of
    its own addresses; Docker decides what the outside can reach."""
    return "0.0.0.0" if settings.is_production else "127.0.0.1"  # noqa: S104


def bind_port(settings: Settings) -> socket.socket:
    """Open the port and start accepting connections. Raises OSError if it is taken."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((server_host(settings), settings.port))
        sock.listen(128)
        sock.setblocking(False)
    except OSError:
        sock.close()
        raise
    return sock


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The price stream runs for as long as the app serves. Only `server.py`
    # switches it on, so tests that build the app never open a connection.
    if app.state.background_work:
        app.state.market.start()
    try:
        yield
        await app.state.market.stop()
    finally:
        await dispose_engine()


def create_app(settings: Settings, decisions: Decisions | None = None) -> FastAPI:
    """Build the API. The interactive docs pages are off: they would be
    endpoints without login."""
    app = FastAPI(
        title="ArbiPilot backend",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    # When this app object was made; `GET /integrations/server` reports the uptime.
    app.state.started_at = clock.utc_now()
    app.state.readiness = ReadinessCache()
    # Keeps the `/integrations` checks from being run in a loop.
    app.state.check_throttle = CheckThrottle()
    # The database session maker. Made on the first request that needs it.
    app.state.sessions = None
    # Live prices and pair rules. Created here, started by the lifespan.
    app.state.market = MarketData(settings)
    app.state.background_work = False
    # The owner's limits and the one gate every order passes. An unreadable
    # `decisions.yaml` raises here: the app does not start without its limits.
    app.state.decisions = decisions if decisions is not None else load_decisions()
    app.state.risk = RiskEngine(app.state.decisions.risk)
    # Where the account's value comes from. Until the paper account exists
    # (stage 7) it is the starting balance from `decisions.yaml`.
    paper_cash = app.state.decisions.shadow.starting_equity_usdt
    app.state.account = lambda: starting_account(paper_cash)
    app.state.account_source = "paper starting balance (no trades yet)"
    # Off until `server.py` has seen the Claude API check pass at startup.
    # This is only the startup result: the trading loop (Day 3) keeps its own
    # live switch in the risk engine and must not rely on this alone.
    app.state.new_entries_enabled = False

    origins = settings.frontend_origin_list
    if origins:  # empty until the frontend exists; never "*"
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    register_error_handlers(app)
    app.include_router(api_router)
    return app


@dataclass(frozen=True)
class StartupReport:
    """What the startup checks found, and the lines that say so."""

    settings: Settings
    port_error: str | None
    checks: list[CheckResult] = field(default_factory=list)

    def _check(self, name: str) -> CheckResult:
        for check in self.checks:
            if check.name == name:
                return check
        return CheckResult(name, False, "the check did not run")

    @property
    def claude_ok(self) -> bool:
        return self._check("claude").ok

    @property
    def fatal(self) -> bool:
        """The app must not start without its port, its database or Binance.
        A Claude failure is not fatal: the app starts with new entries off."""
        return (
            self.port_error is not None
            or not self._check("database").ok
            or not self._check("binance").ok
        )

    def lines(self) -> list[str]:
        port = self.settings.port
        database = self._check("database")
        binance = self._check("binance")
        claude = self._check("claude")

        lines = [
            f"{OK} Running on port {port}"
            if self.port_error is None
            else f"{FAILED} Port {port} failed: {self.port_error}",
            f"{OK} Database connected successfully ({database.detail})"
            if database.ok
            else f"{FAILED} Database connection failed: {database.detail}",
            f"{OK} Server connected successfully"
            if binance.ok
            else f"{FAILED} Server connection failed: {binance.detail}",
            f"{OK} Claude API connected successfully"
            if claude.ok
            else f"{FAILED} Claude API connection failed: {claude.detail}",
            f"Environment: {self.settings.app_env.upper()}",
            f"Mode: {self.settings.trading_mode.upper()}",
        ]
        if self.settings.trading_mode == "live":
            lines.append(f"Live confirmed for: {self.settings.live_confirm.strip()}")
        return lines

    def telegram_text(self) -> str:
        """The same lines for the owner's Telegram, with the outcome on top."""
        if self.fatal:
            headline = "ArbiPilot did NOT start"
        elif not self.claude_ok:
            headline = "ArbiPilot started - new entries are DISABLED (Claude API down)"
        else:
            headline = "ArbiPilot started"
        return "\n".join([headline, *self.lines()])
