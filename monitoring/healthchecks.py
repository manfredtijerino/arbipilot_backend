"""The dead-man's-switch ping to Healthchecks.io.

The app tells Healthchecks.io "I am alive"; when the pings stop, Healthchecks.io
tells the owner. Production only: `HEALTHCHECKS_PING_URL` is empty on the laptop.

The ping address is a secret (anyone holding it can fake "alive"), so it never
appears in a message or a log line.

Rules checked against Healthchecks.io's documentation 2026-11-26: a ping is a
GET to `https://hc-ping.com/<id>`; the answer is 200 with the text `OK`, and
also 200 with `OK (not found)` or `OK (rate limited)` when it did not count.
"""

import logging
from urllib.parse import urlsplit

import httpx

from config.settings import Settings, is_set

logger = logging.getLogger(__name__)

PING_HOST = "hc-ping.com"
REQUEST_TIMEOUT_SECONDS = 10


class HealthchecksError(Exception):
    """The ping failed. The message is safe to show the owner."""


def is_configured(settings: Settings) -> bool:
    return is_set(settings.healthchecks_ping_url)


def ping_url(settings: Settings) -> str:
    """The ping address, refused unless it is Healthchecks.io's own host."""
    url = settings.healthchecks_ping_url.get_secret_value().strip()
    if not url:
        raise HealthchecksError("not configured (HEALTHCHECKS_PING_URL is empty)")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != PING_HOST
        or parts.port is not None
        or parts.username is not None
        or len(parts.path) < 2
        or parts.query
        or parts.fragment
    ):
        raise HealthchecksError(
            f"HEALTHCHECKS_PING_URL must look like https://{PING_HOST}/<check id>"
        )
    return url


async def send_ping(
    settings: Settings, client: httpx.AsyncClient | None = None
) -> None:
    """Send one "I am alive" ping. Raises HealthchecksError if it did not count."""
    url = ping_url(settings)
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = await client.get(url)
    except httpx.TimeoutException:
        raise HealthchecksError("Healthchecks.io did not answer in time") from None
    except (httpx.HTTPError, httpx.InvalidURL):
        raise HealthchecksError("could not reach Healthchecks.io") from None
    finally:
        if owns_client:
            await client.aclose()
    answer = response.text.strip().lower()
    if response.status_code == 404 or "not found" in answer:
        raise HealthchecksError("Healthchecks.io does not know this check address")
    if response.status_code == 429 or "rate limited" in answer:
        raise HealthchecksError("Healthchecks.io is limiting pings; try again later")
    if response.status_code != 200 or answer != "ok":
        raise HealthchecksError(
            f"Healthchecks.io answered with status {response.status_code}"
        )
    logger.info("healthchecks ping sent")
