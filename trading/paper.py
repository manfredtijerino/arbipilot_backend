"""Pretend fills: what a buy or a sell does to the paper wallet.

Only orders that fill at once are modelled here: a buy fills at the best
ask, a sale at the best bid, and the fee from `decisions.yaml` is charged in
USDT. Nothing in this file talks to the database or to Binance; it is plain
arithmetic on `Decimal`, so every case can be tested exactly.

Not modelled yet: waiting (maker) orders, the delay between deciding and
filling, and an order bigger than what is offered at the best price.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal

from exchange.filters import floor_to_step
from trading.fees import FEE_STEP, cost_of_buying, fee_for, proceeds_of_selling
from trading.risk import Side

ZERO = Decimal(0)


@dataclass(frozen=True)
class Holding:
    """What is held of one pair."""

    quantity: Decimal  # of the coin
    cost: Decimal  # everything paid for it, fees included, in USDT


@dataclass(frozen=True)
class Fill:
    """One pretend buy or sell, and what the wallet looks like after it."""

    side: Side
    quantity: Decimal
    price: Decimal
    notional: Decimal  # quantity times price
    fee: Decimal  # USDT
    cash_after: Decimal
    holding_after: Holding  # quantity 0 when nothing is left
    realized_pnl: Decimal | None  # only on a sale


def fill_price(side: Side, bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    """What an at-once order pays or gets: a buy the ask, a sale the bid."""
    price = ask if side is Side.BUY else bid
    return price if price is not None and price > 0 else None


def order_value(quantity: Decimal, price: Decimal, side: Side) -> Decimal:
    """Quantity times price, in USDT with 8 decimals like every amount here.

    When the product has more decimals, a buy is rounded up and a sale down:
    the pretend wallet is never flattered.
    """
    rounding = ROUND_UP if side is Side.BUY else ROUND_DOWN
    return (quantity * price).quantize(FEE_STEP, rounding=rounding)


def quantity_that_fits(
    quantity: Decimal, price: Decimal, cash: Decimal, rate: Decimal, step: Decimal
) -> Decimal:
    """The most that can be bought, up to `quantity`, with the fee paid too.

    The risk engine cuts an order to the free cash; the fee comes on top, so
    an order using all the cash is cut once more, by whole steps.
    """

    def cost(amount: Decimal) -> Decimal:
        return cost_of_buying(order_value(amount, price, Side.BUY), rate)

    if cost(quantity) <= cash:
        return quantity
    fits = min(quantity, floor_to_step(cash / (price * (1 + rate)), step))
    while fits > 0 and cost(fits) > cash:
        fits -= step
    return max(fits, ZERO)


def buy(
    cash: Decimal,
    held: Holding | None,
    quantity: Decimal,
    price: Decimal,
    rate: Decimal,
) -> Fill:
    """Buy `quantity` at `price`: the coins and the fee leave the wallet."""
    notional = order_value(quantity, price, Side.BUY)
    spent = cost_of_buying(notional, rate)
    if quantity <= 0 or price <= 0 or spent > cash:
        raise ValueError("the buy does not fit the wallet")
    before = held or Holding(ZERO, ZERO)
    after = Holding(before.quantity + quantity, before.cost + spent)
    return Fill(
        Side.BUY, quantity, price, notional, spent - notional, cash - spent, after, None
    )


def sell(
    cash: Decimal, held: Holding, quantity: Decimal, price: Decimal, rate: Decimal
) -> Fill:
    """Sell `quantity` at `price`: its value minus the fee enters the wallet."""
    if quantity <= 0 or price <= 0 or quantity > held.quantity:
        raise ValueError("more is being sold than is held")
    notional = order_value(quantity, price, Side.SELL)
    received = proceeds_of_selling(notional, rate)
    if quantity == held.quantity:
        cost_sold = held.cost  # everything: no rounding can be left behind
    else:
        share = held.cost * quantity / held.quantity
        cost_sold = share.quantize(FEE_STEP, rounding=ROUND_HALF_EVEN)
    after = Holding(held.quantity - quantity, held.cost - cost_sold)
    return Fill(
        Side.SELL,
        quantity,
        price,
        notional,
        fee_for(notional, rate),
        cash + received,
        after,
        received - cost_sold,
    )
