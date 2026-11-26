"""AI settings: model, timeouts and (from Day 3) the daily budget.

The model name always comes from `ANTHROPIC_MODEL` in `.env`, never from code.
"""

from config.settings import Settings

# Seconds to wait for the connection check (it sends no prompt and costs nothing).
CHECK_TIMEOUT_SECONDS = 10


def model_name(settings: Settings) -> str:
    """The configured model, or an empty string when none is set."""
    return settings.anthropic_model.strip()
