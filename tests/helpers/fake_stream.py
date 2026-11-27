"""A pretend Binance stream for tests: scripted connections, no network."""

import asyncio
from typing import Any

from websockets.exceptions import ConnectionClosedOK


class FakeSocket:
    """One connection. Hands out its messages, then behaves as scripted.

    An item that is an exception is raised instead of returned. When the
    items run out the socket stays silent, like a dead line.
    """

    def __init__(self, items: list[Any]) -> None:
        self._items = list(items)
        self._closed = asyncio.Event()
        self.close_calls = 0

    async def recv(self) -> Any:
        if self._closed.is_set():
            raise ConnectionClosedOK(None, None)
        if self._items:
            item = self._items.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        await self._closed.wait()  # silent until someone closes it
        raise ConnectionClosedOK(None, None)

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


class _Connection:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome

    async def __aenter__(self) -> FakeSocket:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeConnect:
    """Each call opens the next scripted connection (a FakeSocket or an error)."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.urls: list[str] = []

    def __call__(self, url: str) -> _Connection:
        self.urls.append(url)
        if not self._outcomes:
            raise AssertionError("the test scripted no further connection")
        return _Connection(self._outcomes.pop(0))


class ScriptedSleep:
    """Records each wait and ends the run loop after the allowed number."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        if len(self.delays) >= self.allowed:
            raise asyncio.CancelledError
        await asyncio.sleep(0)


def book(
    symbol: str, bid: str, ask: str, bid_qty: str = "1.5", ask_qty: str = "2.5"
) -> str:
    return (
        f'{{"stream":"{symbol.lower()}@bookTicker","data":{{"u":1,"s":"{symbol}",'
        f'"b":"{bid}","B":"{bid_qty}","a":"{ask}","A":"{ask_qty}"}}}}'
    )


def trade(symbol: str, price: str, quantity: str = "0.01", maker: bool = False) -> str:
    return (
        f'{{"stream":"{symbol.lower()}@aggTrade","data":{{"e":"aggTrade",'
        f'"E":1800000000100,"s":"{symbol}","a":7,"p":"{price}","q":"{quantity}",'
        f'"f":7,"l":7,"T":1800000000000,"m":{"true" if maker else "false"},"M":true}}}}'
    )
