"""Telegram settings: who the bot talks to and how long it waits."""

from config.settings import Settings, is_set

# Seconds to wait for Telegram before giving up on a message.
REQUEST_TIMEOUT_SECONDS = 10


def is_configured(settings: Settings) -> bool:
    """True when both the bot token and the owner's ID are filled in."""
    return is_set(settings.telegram_bot_token) and is_set(settings.telegram_owner_id)
