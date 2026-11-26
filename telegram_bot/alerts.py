"""Sending messages to the owner, and checking the bot works.

Send-only for now: the bot does not listen for commands yet. Every message
from development starts with `[DEV]`.

Telegram's own error text can contain the bot token, so it is never passed on:
every failure is turned into a sentence written here.
"""

import logging
from typing import Any

from telegram import Bot
from telegram.error import Forbidden, InvalidToken, NetworkError, TelegramError
from telegram.request import HTTPXRequest

from config.environment import message_prefix
from config.settings import Settings
from telegram_bot.config import REQUEST_TIMEOUT_SECONDS, is_configured

logger = logging.getLogger(__name__)


class TelegramCheckError(Exception):
    """A Telegram call failed. The message is safe to show the owner."""


def build_bot(settings: Settings) -> Bot:
    request = HTTPXRequest(
        connect_timeout=REQUEST_TIMEOUT_SECONDS,
        read_timeout=REQUEST_TIMEOUT_SECONDS,
        write_timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return Bot(settings.telegram_bot_token.get_secret_value(), request=request)


def _describe(exc: TelegramError) -> str:
    if isinstance(exc, InvalidToken):
        return "the Telegram bot token was refused"
    if isinstance(exc, Forbidden):
        return "the bot may not message the owner (open the bot and press Start)"
    if isinstance(exc, NetworkError):  # includes timeouts
        return "could not reach Telegram"
    return f"Telegram refused the request ({type(exc).__name__})"


def _require_configured(settings: Settings) -> None:
    if not is_configured(settings):
        raise TelegramCheckError(
            "not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_OWNER_ID is empty in .env)"
        )


async def check_telegram(settings: Settings, bot: Any | None = None) -> None:
    """Check the bot token is accepted. Sends no message."""
    _require_configured(settings)
    bot = bot or build_bot(settings)
    try:
        async with bot:
            await bot.get_me()
    except TelegramError as exc:
        raise TelegramCheckError(_describe(exc)) from None


async def send_alert(settings: Settings, text: str, bot: Any | None = None) -> None:
    """Send one message to the owner. Raises TelegramCheckError on failure."""
    _require_configured(settings)
    bot = bot or build_bot(settings)
    try:
        async with bot:
            await bot.send_message(
                chat_id=settings.telegram_owner_id,
                text=message_prefix(settings) + text,
            )
    except TelegramError as exc:
        raise TelegramCheckError(_describe(exc)) from None
    logger.info("telegram message sent")


async def send_reset_code(settings: Settings, text: str) -> None:
    """Send the password reset code to the owner. Never raises.

    It runs after the API has already answered, so a failure is only logged:
    the owner asks for a new code a minute later.
    """
    try:
        await send_alert(settings, text)
    except TelegramCheckError as exc:
        logger.warning("reset code not delivered: %s", exc)
    except Exception as exc:  # noqa: BLE001 - a background task must not crash
        logger.error("reset code not delivered: unexpected %s", type(exc).__name__)
