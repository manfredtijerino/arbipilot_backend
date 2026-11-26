"""The current time, in one place, so tests can set it."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
