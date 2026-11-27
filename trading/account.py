"""What the account holds at one moment, as the risk engine sees it.

A snapshot is built by whoever tracks the money (the paper account from
stage 7, Binance balances in testnet and live) and handed to the risk engine
with each order. All amounts are in the quote asset (USDT) and are `Decimal`.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal  # how much of the coin is held
    value: Decimal  # what it is worth now, at the best bid
    # How much of `quantity` is already locked in exit orders still waiting.
    reserved: Decimal = Decimal(0)


@dataclass(frozen=True)
class AccountSnapshot:
    cash: Decimal  # free USDT, not reserved by any order
    positions: dict[str, Position] = field(default_factory=dict)
    # USDT reserved by entry orders that have not filled yet, per pair.
    pending_entries: dict[str, Decimal] = field(default_factory=dict)

    @property
    def equity(self) -> Decimal:
        """Everything the account is worth: cash, reserved cash and coins."""
        held = sum((position.value for position in self.positions.values()), Decimal(0))
        reserved = sum(self.pending_entries.values(), Decimal(0))
        return self.cash + held + reserved

    def is_open(self, symbol: str) -> bool:
        """Is there a trade, or an entry order still waiting, in this pair?"""
        position = self.positions.get(symbol)
        held = position is not None and position.quantity > 0
        return held or self.pending_entries.get(symbol, Decimal(0)) > 0

    @property
    def open_symbols(self) -> set[str]:
        return {
            symbol
            for symbol in (*self.positions, *self.pending_entries)
            if self.is_open(symbol)
        }


def starting_account(cash: Decimal) -> AccountSnapshot:
    """An account that holds only cash and has never traded."""
    return AccountSnapshot(cash=cash)
