"""Facts about the machine the app runs on: memory, disk, uptime, public address.

On the laptop this describes the laptop. In production it describes the
Lightsail server (seen from inside the container).
"""

import ipaddress
import time
from dataclasses import dataclass

import httpx
import psutil

# Amazon's "what is my address" service. Answers with the address as text.
PUBLIC_IP_URL = "https://checkip.amazonaws.com"
REQUEST_TIMEOUT_SECONDS = 10
MEGABYTE = 1024 * 1024
GIGABYTE = 1024 * MEGABYTE


class ServerInfoError(Exception):
    """A fact could not be read. The message is safe to show the owner."""


@dataclass(frozen=True)
class MachineFacts:
    machine_uptime_seconds: int
    memory_total_mb: int
    memory_available_mb: int
    disk_total_gb: float
    disk_free_gb: float


def read_machine() -> MachineFacts:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return MachineFacts(
        machine_uptime_seconds=max(0, int(time.time() - psutil.boot_time())),
        memory_total_mb=memory.total // MEGABYTE,
        memory_available_mb=memory.available // MEGABYTE,
        disk_total_gb=round(disk.total / GIGABYTE, 1),
        disk_free_gb=round(disk.free / GIGABYTE, 1),
    )


async def fetch_public_ip(client: httpx.AsyncClient | None = None) -> str:
    """The address the internet sees this machine as. Binance locks keys to it."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = await client.get(PUBLIC_IP_URL)
        response.raise_for_status()
        return str(ipaddress.ip_address(response.text.strip()))
    except httpx.HTTPError:
        raise ServerInfoError("could not find out the public address") from None
    except ValueError:
        raise ServerInfoError(
            "the public address service sent a strange answer"
        ) from None
    finally:
        if owns_client:
            await client.aclose()
