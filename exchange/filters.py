"""Each pair's trading rules, read from Binance's `exchangeInfo`.

Binance refuses an order whose value is under the pair's minimum, whose
quantity is not a multiple of the step, or whose price is not a multiple of
the tick. The rules differ per pair and change over time, so they are read
from Binance and never written into the code.

Field names checked against Binance's documentation 2026-11-27.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from exchange.numbers import positive_decimal, to_decimal

# Pair, asset and status names: short, capitals, digits, underscore.
_NAME = re.compile(r"[A-Z0-9_]{1,30}")


class RulesError(Exception):
    """Binance's answer could not be turned into rules. Safe to show."""


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    base_asset: str  # what is bought and sold, e.g. BTC
    quote_asset: str  # what it is priced in, e.g. USDT
    status: str  # TRADING when the pair is open
    trading: bool  # open, and Spot trading is allowed
    min_order_value: Decimal  # smallest order, in the quote asset
    tick_size: Decimal  # prices move in steps of this
    step_size: Decimal  # quantities move in steps of this
    min_quantity: Decimal


def _filters(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = entry.get("filters")
    if not isinstance(rows, list):
        raise ValueError("no filters")
    return {
        row["filterType"]: row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("filterType"), str)
    }


def _parse_symbol(entry: Any) -> SymbolRules:
    if not isinstance(entry, dict):
        raise ValueError("not an object")
    symbol, base, quote, status = (
        entry.get("symbol"),
        entry.get("baseAsset"),
        entry.get("quoteAsset"),
        entry.get("status"),
    )
    if not all(
        isinstance(text, str) and _NAME.fullmatch(text)
        for text in (symbol, base, quote, status)
    ):
        raise ValueError("a name is missing or strange")
    filters = _filters(entry)
    price, lot = filters["PRICE_FILTER"], filters["LOT_SIZE"]
    # Binance has two names for the minimum order value; a pair carries one.
    notional = filters.get("NOTIONAL") or filters["MIN_NOTIONAL"]
    return SymbolRules(
        symbol=symbol,
        base_asset=base,
        quote_asset=quote,
        status=status,
        trading=status == "TRADING" and entry.get("isSpotTradingAllowed") is True,
        min_order_value=positive_decimal(notional.get("minNotional")),
        tick_size=positive_decimal(price.get("tickSize")),
        step_size=positive_decimal(lot.get("stepSize")),
        min_quantity=to_decimal(lot.get("minQty")),
    )


def parse_exchange_info(body: Any, symbols: tuple[str, ...]) -> dict[str, SymbolRules]:
    """The rules for exactly the pairs asked for, or RulesError.

    A pair that is missing, or whose rules cannot be read, fails the whole
    answer: trading on a guessed minimum is worse than not trading.
    """
    entries = body.get("symbols") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        raise RulesError("Binance sent trading rules we could not read")
    rules: dict[str, SymbolRules] = {}
    for entry in entries:
        try:
            parsed = _parse_symbol(entry)
        except (KeyError, ValueError, TypeError):
            name = entry.get("symbol") if isinstance(entry, dict) else None
            if name in symbols:
                raise RulesError(
                    f"Binance sent trading rules for {name} we could not read"
                ) from None
            continue
        if parsed.symbol in symbols:
            rules[parsed.symbol] = parsed
    missing = [symbol for symbol in symbols if symbol not in rules]
    if missing:
        raise RulesError(f"Binance sent no trading rules for {', '.join(missing)}")
    return {symbol: rules[symbol] for symbol in symbols}


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """The largest multiple of `step` that is not above `value`. Both positive."""
    return (value // step) * step


def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    """The smallest multiple of `step` that is not below `value`. Both positive."""
    floored = floor_to_step(value, step)
    return floored if floored == value else floored + step
