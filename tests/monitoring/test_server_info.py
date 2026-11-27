"""Facts about the machine. The public address comes from a fake transport."""

from collections.abc import Callable

import httpx
import pytest

from monitoring.server_info import ServerInfoError, fetch_public_ip, read_machine


def client_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_the_machine_facts_make_sense() -> None:
    facts = read_machine()
    assert facts.machine_uptime_seconds >= 0
    assert 0 < facts.memory_available_mb <= facts.memory_total_mb
    assert 0 < facts.disk_free_gb <= facts.disk_total_gb


async def test_the_public_address_is_read_as_an_address() -> None:
    async with client_answering(
        lambda r: httpx.Response(200, text="203.0.113.7\n")
    ) as c:
        assert await fetch_public_ip(c) == "203.0.113.7"


@pytest.mark.parametrize("answer", ["", "<html>hello</html>", "999.1.1.1"])
async def test_a_strange_answer_is_refused(answer: str) -> None:
    async with client_answering(lambda r: httpx.Response(200, text=answer)) as client:
        with pytest.raises(ServerInfoError, match="strange"):
            await fetch_public_ip(client)


async def test_an_unreachable_service_is_explained() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with client_answering(down) as client:
        with pytest.raises(ServerInfoError, match="could not find out"):
            await fetch_public_ip(client)
    async with client_answering(lambda r: httpx.Response(503)) as client:
        with pytest.raises(ServerInfoError, match="could not find out"):
            await fetch_public_ip(client)
