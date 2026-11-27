"""The Healthchecks.io ping. A fake transport answers; no network."""

from collections.abc import Callable

import httpx
import pytest

from config.settings import Settings
from monitoring import healthchecks
from monitoring.healthchecks import HealthchecksError, ping_url, send_ping

PING = "https://hc-ping.com/test-check-id"


def client_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_empty_means_not_configured(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert not healthchecks.is_configured(settings)
    with pytest.raises(HealthchecksError, match="not configured"):
        ping_url(settings)


@pytest.mark.parametrize(
    "url",
    [
        "http://hc-ping.com/test-check-id",  # not https
        "https://example.test/test-check-id",  # another host
        "https://hc-ping.com.example.test/id",  # looks alike
        "https://user@hc-ping.com/test-check-id",
        "https://hc-ping.com:8443/test-check-id",
        "https://hc-ping.com/",  # no check id
        "https://hc-ping.com/test-check-id?x=1",
    ],
)
def test_only_the_real_ping_host_is_accepted(
    make_settings: Callable[..., Settings], url: str
) -> None:
    with pytest.raises(HealthchecksError) as refused:
        ping_url(make_settings(healthchecks_ping_url=url))
    assert "test-check-id" not in str(refused.value)  # the address is a secret


async def test_a_ping_is_one_get_to_the_address(
    make_settings: Callable[..., Settings],
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="OK")

    async with client_answering(handler) as client:
        await send_ping(make_settings(healthchecks_ping_url=PING), client)
    assert [(r.method, str(r.url)) for r in seen] == [("GET", PING)]


@pytest.mark.parametrize(
    ("status", "text", "expected"),
    [
        (200, "OK (not found)", "does not know"),
        (404, "not found", "does not know"),
        (200, "OK (rate limited)", "limiting"),
        (429, "rate limited", "limiting"),
        (500, "oops", "status 500"),
        (200, "something else", "status 200"),
    ],
)
async def test_a_ping_that_did_not_count_is_a_failure(
    make_settings: Callable[..., Settings], status: int, text: str, expected: str
) -> None:
    async with client_answering(lambda r: httpx.Response(status, text=text)) as client:
        with pytest.raises(HealthchecksError) as failed:
            await send_ping(make_settings(healthchecks_ping_url=PING), client)
    assert expected in str(failed.value)
    assert "test-check-id" not in str(failed.value)


async def test_network_failures_are_explained(
    make_settings: Callable[..., Settings],
) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {PING}")

    settings = make_settings(healthchecks_ping_url=PING)
    async with client_answering(timeout) as client:
        with pytest.raises(HealthchecksError, match="in time"):
            await send_ping(settings, client)
    async with client_answering(down) as client:
        with pytest.raises(HealthchecksError) as failed:
            await send_ping(settings, client)
    assert str(failed.value) == "could not reach Healthchecks.io"
