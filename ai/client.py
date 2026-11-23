"""Claude API client.

Today this holds only the connection check. It looks the configured model up
by name, which proves the key works and the model exists, and costs no tokens.
"""

import logging
from typing import Any

import anthropic

from ai.config import CHECK_TIMEOUT_SECONDS, model_name
from config.settings import Settings, is_set

logger = logging.getLogger(__name__)


class AICheckError(Exception):
    """The Claude API check failed. The message is safe to show the owner."""


def build_client(settings: Settings) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=CHECK_TIMEOUT_SECONDS,
        max_retries=1,
    )


async def check_claude(settings: Settings, client: Any | None = None) -> str:
    """Check the key is accepted and the model exists. Returns the model name."""
    if not is_set(settings.anthropic_api_key):
        raise AICheckError("not configured (ANTHROPIC_API_KEY is empty in .env)")
    model = model_name(settings)
    if not model:
        raise AICheckError("not configured (ANTHROPIC_MODEL is empty in .env)")

    owns_client = client is None
    client = client or build_client(settings)
    try:
        await _look_up_model(client, model)
    finally:
        if owns_client:
            await client.close()
    logger.info("claude api reachable model=%s", model)
    return model


async def _look_up_model(client: Any, model: str) -> None:
    """Ask for the model by name. Every failure becomes an AICheckError, so a
    Claude problem can never crash startup or the trading loop."""
    try:
        await client.models.retrieve(model)
    except anthropic.AuthenticationError:
        raise AICheckError("the Anthropic key was refused") from None
    except anthropic.PermissionDeniedError:
        raise AICheckError("the Anthropic key is not allowed to do this") from None
    except anthropic.NotFoundError:
        raise AICheckError(
            f"the model {model} is not in Anthropic's model list"
        ) from None
    except anthropic.APITimeoutError:
        raise AICheckError("the Claude API did not answer in time") from None
    except anthropic.APIConnectionError:
        raise AICheckError("could not reach the Claude API") from None
    except anthropic.APIStatusError as exc:
        raise AICheckError(
            f"the Claude API answered with status {exc.status_code}"
        ) from None
    except (anthropic.AnthropicError, ValueError, TypeError) as exc:
        # Anything else, such as an answer the library could not read.
        raise AICheckError(
            f"the Claude API check failed ({type(exc).__name__})"
        ) from None
