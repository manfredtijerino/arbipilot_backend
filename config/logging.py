"""Log format: one line per event, UTC time, `[DEV]` first in development.

Secrets never reach the logs. Three layers make sure of it:
1. Secret settings are `SecretStr`, and no code logs a connection string.
2. The libraries that log the web addresses they call are quietened, because
   Telegram's address contains the bot token.
3. Every finished log line is searched for the value of every secret setting
   and for anything shaped like a Telegram bot address, and those are replaced
   with `[hidden]` before the line is written.
"""

import logging
import re
import time

from pydantic import SecretStr

from config.environment import message_prefix
from config.settings import Settings

HIDDEN = "[hidden]"

# These log each request's full address at INFO level. Warnings still show.
NOISY_LIBRARIES = ("httpx", "httpx2", "httpcore", "httpcore2", "telegram")

# A Telegram address looks like .../bot<numbers>:<letters>/sendMessage.
TELEGRAM_TOKEN = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

# Shorter values are not searched for: they would hide ordinary words.
SHORTEST_SECRET = 8


def secret_values(settings: Settings) -> list[str]:
    """The value of every secret setting that is filled in, longest first."""
    values = {
        value.get_secret_value().strip()
        for value in settings.__dict__.values()
        if isinstance(value, SecretStr)
    }
    return sorted(
        (value for value in values if len(value) >= SHORTEST_SECRET),
        key=len,
        reverse=True,
    )


class RedactingFormatter(logging.Formatter):
    """Formats a line, then removes any secret from it (the traceback too)."""

    def __init__(self, secrets: list[str], **kwargs: str) -> None:
        super().__init__(**kwargs)
        self._secrets = secrets

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        for secret in self._secrets:
            line = line.replace(secret, HIDDEN)
        return TELEGRAM_TOKEN.sub(f"bot{HIDDEN}", line)


def build_formatter(settings: Settings) -> logging.Formatter:
    prefix = message_prefix(settings)
    formatter = RedactingFormatter(
        secret_values(settings),
        fmt=f"{prefix}%(asctime)sZ %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime  # timestamps in UTC, not laptop time
    return formatter


def setup_logging(settings: Settings, level: int = logging.INFO) -> None:
    """Send every log line to the terminal in the project's format."""
    handler = logging.StreamHandler()
    handler.setFormatter(build_formatter(settings))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
