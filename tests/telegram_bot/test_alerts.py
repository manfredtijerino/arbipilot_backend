"""Telegram messages. The bot is a fake; no network."""

from collections.abc import Callable

import pytest
from telegram.error import Forbidden, InvalidToken, TimedOut

from config.settings import Settings
from telegram_bot.alerts import TelegramCheckError, check_telegram, send_alert


class _FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[str, str]] = []
        self.get_me_calls = 0

    async def __aenter__(self) -> "_FakeBot":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_me(self) -> None:
        self.get_me_calls += 1
        if self.error:
            raise self.error

    async def send_message(self, chat_id: str, text: str) -> None:
        if self.error:
            raise self.error
        self.sent.append((chat_id, text))


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(telegram_bot_token="test-token", telegram_owner_id="42")


async def test_development_message_starts_with_dev_and_goes_to_the_owner(
    settings: Settings,
) -> None:
    bot = _FakeBot()
    await send_alert(settings, "hello", bot)
    assert bot.sent == [("42", "[DEV] hello")]


async def test_production_message_has_no_prefix(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        app_env="production",
        postgres_db="arbipilot_prod",
        postgres_test_db="",
        telegram_bot_token="test-token",
        telegram_owner_id="42",
    )
    bot = _FakeBot()
    await send_alert(settings, "hello", bot)
    assert bot.sent == [("42", "hello")]


async def test_check_asks_telegram_who_the_bot_is(settings: Settings) -> None:
    bot = _FakeBot()
    await check_telegram(settings, bot)
    assert bot.get_me_calls == 1
    assert bot.sent == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        # Telegram's own text can contain the token; ours must not.
        (InvalidToken("The token `test-token` was rejected"), "token was refused"),
        (Forbidden("bot was blocked by the user"), "press Start"),
        (TimedOut(), "could not reach Telegram"),
    ],
)
async def test_failures_are_described_without_the_token(
    settings: Settings, error: Exception, expected: str
) -> None:
    for call in (check_telegram(settings, _FakeBot(error)), None):
        if call is None:
            call = send_alert(settings, "hello", _FakeBot(error))
        with pytest.raises(TelegramCheckError, match=expected) as caught:
            await call
        assert "test-token" not in str(caught.value)
        assert caught.value.__cause__ is None


async def test_missing_setting_fails_without_calling(
    make_settings: Callable[..., Settings],
) -> None:
    bot = _FakeBot()
    with pytest.raises(TelegramCheckError, match="not configured"):
        await send_alert(make_settings(telegram_bot_token="test-token"), "x", bot)
    assert bot.sent == []
