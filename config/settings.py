"""Every `.env` key, typed and commented.

This is the only file that reads `.env`. Everything else imports `get_settings()`.
Secret fields use `SecretStr`, so printing or logging the settings never shows them.
"""

import re
from decimal import Decimal
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

EMPTY = SecretStr("")
JWT_SECRET_MIN_LENGTH = 32

# What a real key name looks like. A secret pasted on its own line in `.env`
# is read as a "key", so anything else is never printed.
KEY_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,40}")
UNRECOGNISED = "(unrecognised entry in .env)"


def safe_key_name(name: str) -> str:
    """The name if it is a real key or a near-miss of one, otherwise a placeholder.

    Only names close to a real key are echoed (so the typo `JWT_SECRT` is shown),
    because a short pasted secret can look exactly like a key name.
    """
    upper = name.upper()
    known = [field.upper() for field in Settings.model_fields]
    if KEY_NAME.fullmatch(upper) and get_close_matches(upper, known, n=1, cutoff=0.8):
        return upper
    return UNRECOGNISED


class SettingsError(Exception):
    """A `.env` key is missing or invalid. The message names keys, never values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="forbid",  # a misspelled key in .env stops the app
        hide_input_in_errors=True,  # validation errors never echo a value
        frozen=True,  # nothing can change a setting after the guard rails ran
    )

    # --- The app ---
    # Which machine this is: the laptop (development) or the server (production).
    app_env: Literal["development", "production"]
    # The port the API listens on.
    port: int = 3000
    # shadow = pretend orders, testnet = fake exchange, live = real money.
    trading_mode: Literal["shadow", "testnet", "live"]
    # Must hold today's UTC date (YYYY-MM-DD) for live mode to start. Empty otherwise.
    live_confirm: str = ""

    # --- Database (Lightsail managed PostgreSQL) ---
    # Laptop: the public endpoint. Server: the private endpoint.
    postgres_host: str = ""
    postgres_port: int = 5432
    # arbipilot_dev on the laptop, arbipilot_prod on the server.
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: SecretStr = EMPTY
    # TLS is always required.
    postgres_sslmode: Literal["require", "verify-ca", "verify-full"] = "require"
    # Laptop only: the database integration tests may wipe.
    postgres_test_db: str = ""
    # Laptop only: password of the read-only production user, for the owner's pgAdmin.
    pgadmin_readonly_password: SecretStr = EMPTY

    # --- Login ---
    # Signs the login tokens. Generated per machine; never shared between them.
    jwt_secret: SecretStr

    # --- Binance ---
    # Testnet key (fake exchange): set on both machines.
    binance_testnet_key: SecretStr = EMPTY
    binance_testnet_secret: SecretStr = EMPTY
    # Mainnet read-only key: server only. Must be empty on the laptop.
    binance_read_key: SecretStr = EMPTY
    binance_read_secret: SecretStr = EMPTY
    # Mainnet trade key: server only. Must be empty on the laptop.
    binance_api_key: SecretStr = EMPTY
    binance_api_secret: SecretStr = EMPTY
    # REST and WebSocket addresses (testnet mode swaps both to the testnet hosts).
    binance_base_url: str = ""
    binance_ws_url: str = ""
    # The pairs the bot watches, comma-separated. Each must end in USDT.
    market_symbols: str = "BTCUSDT,ETHUSDT,BNBUSDT"
    # true = save every price message to recordings/ (test data for later).
    # Off by default: the files grow by hundreds of megabytes a day.
    market_recording: bool = False
    # Fee per side with the BNB discount on.
    fee_maker: Decimal = Decimal("0.00075")
    fee_taker: Decimal = Decimal("0.00075")

    # --- AI (Claude API) ---
    anthropic_api_key: SecretStr = EMPTY
    # The model name is configuration, never code.
    anthropic_model: str = ""

    # --- Telegram ---
    # Laptop: the development bot. Server: the production bot.
    telegram_bot_token: SecretStr = EMPTY
    # Only messages from this Telegram user are obeyed.
    telegram_owner_id: str = ""

    # --- Monitoring ---
    # Healthchecks.io ping address. Server only; empty on the laptop.
    healthchecks_ping_url: SecretStr = EMPTY
    # The address the Binance keys are locked to. Server only.
    expected_public_ip: str = ""

    # --- Frontend ---
    # Comma-separated browser addresses allowed to call the API. Never "*".
    frontend_origins: str = ""

    @field_validator(
        "postgres_host", "postgres_db", "postgres_user", "postgres_test_db"
    )
    @classmethod
    def _strip_spaces(cls, value: str) -> str:
        return value.strip()

    @field_validator("postgres_db", "postgres_test_db")
    @classmethod
    def _plain_database_name(cls, value: str) -> str:
        # Letters, digits and underscores only, so a name can never smuggle
        # extra connection options past the _dev / _prod rules.
        if not re.fullmatch(r"[A-Za-z0-9_]*", value):
            raise ValueError("may contain only letters, digits and underscores")
        return value

    @field_validator("market_symbols")
    @classmethod
    def _valid_symbol_list(cls, value: str) -> str:
        symbols = [part.strip().upper() for part in value.split(",") if part.strip()]
        if not 1 <= len(symbols) <= 20:
            raise ValueError("must list between 1 and 20 pairs")
        if len(set(symbols)) != len(symbols):
            raise ValueError("lists a pair twice")
        for symbol in symbols:
            if not re.fullmatch(r"[A-Z0-9]{2,15}USDT", symbol):
                raise ValueError("each pair must look like BTCUSDT")
        return ",".join(symbols)

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_is_long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < JWT_SECRET_MIN_LENGTH:
            raise ValueError(f"must be at least {JWT_SECRET_MIN_LENGTH} characters")
        return value

    @field_validator("frontend_origins")
    @classmethod
    def _no_wildcard_origin(cls, value: str) -> str:
        if "*" in value:
            raise ValueError('must list exact addresses, never "*"')
        return value

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def market_symbol_list(self) -> tuple[str, ...]:
        return tuple(self.market_symbols.split(","))

    @property
    def frontend_origin_list(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def database_is_configured(self) -> bool:
        """True when every value needed to reach the database is filled in."""
        return all(
            is_set(value)
            for value in (
                self.postgres_host,
                self.postgres_db,
                self.postgres_user,
                self.postgres_password,
            )
        )

    def database_url(self, database: str | None = None) -> URL:
        """The connection address, built from the separate `.env` values.

        `database` may only be this machine's own database (the default) or
        its test database. Any other name is refused, so no code path can
        build an address for a database this machine must not touch.

        Never log or print it with the password: `str(url)` and `repr(url)`
        show `***` in its place, and that is the only form allowed in output.
        """
        database = database or self.postgres_db
        if database not in {self.postgres_db, self.postgres_test_db} or not database:
            raise ValueError("only POSTGRES_DB or POSTGRES_TEST_DB may be connected to")
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=database,
        )


def is_set(value: SecretStr | str) -> bool:
    """True when a setting holds a non-empty value."""
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    return bool(raw.strip())


def load_settings(**overrides: Any) -> Settings:
    """Read and validate the settings. Raises SettingsError naming the bad keys."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = [
            f"{safe_key_name('.'.join(str(part) for part in error['loc']))}: "
            f"{error['msg']}"
            for error in exc.errors(
                include_input=False, include_url=False, include_context=False
            )
        ]
        # `from None` drops the original error so no value can travel with it.
        raise SettingsError("Invalid .env settings -> " + "; ".join(problems)) from None


@lru_cache
def get_settings() -> Settings:
    """The settings for this process, read once and checked by the guard rails.

    Every entry point (the server, scripts, migrations) gets its settings here,
    so none of them can skip the development vs production rules.
    """
    from config.environment import check_guard_rails  # avoids a circular import

    settings = load_settings()
    check_guard_rails(settings)
    return settings
