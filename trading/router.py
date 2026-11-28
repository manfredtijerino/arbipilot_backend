"""The order router: where an order approved by the risk engine is sent.

There is one road for every order: asked for, checked by the risk engine,
routed here, filled, written down. Only the last stretch differs by mode,
and this file is the only place that knows which stretch belongs to which
mode.

- `shadow`: the paper account. Pretend money, real prices, no order sent.
- `testnet` and `live`: not built. They are refused here, by name, until the
  owner starts that work; nothing else may send an order to Binance.
"""

from enum import StrEnum


class Destination(StrEnum):
    PAPER = "paper"


def destination(mode: str) -> Destination | None:
    """Where orders go in this trading mode; None when that road is not built."""
    return Destination.PAPER if mode == "shadow" else None
