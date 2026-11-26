"""Development vs production guard rails.

`check_guard_rails()` runs whenever the settings are loaded, before anything
connects. It stops the app with one clear line when the settings would let the
laptop touch real money or production records, or let production write to a
development or test database.
"""

from datetime import UTC, date, datetime

from config.settings import Settings, is_set

DEV_PREFIX = "[DEV] "


class GuardRailError(Exception):
    """The settings break an environment rule. The app must not start."""


def message_prefix(settings: Settings) -> str:
    """Every development log line and Telegram message starts with this."""
    return DEV_PREFIX if settings.is_development else ""


def check_guard_rails(settings: Settings, today: date | None = None) -> None:
    """Raise GuardRailError on the first broken rule. `today` is a UTC date."""
    today = today or datetime.now(UTC).date()
    # Compare in lowercase so "ARBIPILOT_PROD" is treated like "arbipilot_prod".
    database = settings.postgres_db.lower()
    test_database = settings.postgres_test_db.lower()

    if settings.is_development:
        if settings.trading_mode == "live":
            raise GuardRailError("live mode is not allowed in development")
        if database.endswith("_prod"):
            raise GuardRailError(
                "development must not use a production database "
                "(POSTGRES_DB ends in _prod)"
            )
        # An allow-list, not only a deny-list: an empty or unexpected name is
        # refused too, because a database driver may fall back to a default.
        if not database.endswith("_dev"):
            raise GuardRailError(
                "development needs POSTGRES_DB to be a database ending in _dev"
            )
        mainnet_keys = {
            "BINANCE_API_KEY": settings.binance_api_key,
            "BINANCE_API_SECRET": settings.binance_api_secret,
            "BINANCE_READ_KEY": settings.binance_read_key,
            "BINANCE_READ_SECRET": settings.binance_read_secret,
        }
        present = [name for name, value in mainnet_keys.items() if is_set(value)]
        if present:
            raise GuardRailError(
                "mainnet Binance keys must be empty in development: "
                + ", ".join(present)
            )

    if settings.is_production:
        if database.endswith(("_dev", "_test")):
            raise GuardRailError(
                "production must not use a development or test database "
                "(POSTGRES_DB ends in _dev or _test)"
            )
        if not database.endswith("_prod"):
            raise GuardRailError(
                "production needs POSTGRES_DB to be a database ending in _prod"
            )
        if test_database:
            raise GuardRailError("POSTGRES_TEST_DB must not be set in production")

    if test_database and not test_database.endswith("_test"):
        raise GuardRailError("POSTGRES_TEST_DB must be a database ending in _test")

    if settings.trading_mode == "live":
        if settings.live_confirm.strip() != today.isoformat():
            raise GuardRailError(
                "live mode needs LIVE_CONFIRM set to today's UTC date (YYYY-MM-DD)"
            )
        if not (
            is_set(settings.binance_api_key) and is_set(settings.binance_api_secret)
        ):
            raise GuardRailError(
                "live mode needs BINANCE_API_KEY and BINANCE_API_SECRET to be set"
            )
