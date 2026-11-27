"""Fee maths: what one order costs.

Binance charges a share of each order's value. The share comes from
`decisions.yaml` (`fees`), never from a number written in code. The fee is
rounded UP to Binance's smallest amount (0.00000001), so a pretend trade is
never charged less than a real one would be.
"""

from decimal import ROUND_UP, Decimal

FEE_STEP = Decimal("0.00000001")


def fee_for(notional: Decimal, rate: Decimal) -> Decimal:
    """The fee, in USDT, on an order worth `notional` USDT."""
    for value in (notional, rate):
        if type(value) is not Decimal or not value.is_finite() or value < 0:
            raise ValueError("the order value and the fee share must be plain amounts")
    return (notional * rate).quantize(FEE_STEP, rounding=ROUND_UP)


def cost_of_buying(notional: Decimal, rate: Decimal) -> Decimal:
    """Everything a buy takes out of the wallet: the coins and the fee."""
    return notional + fee_for(notional, rate)


def proceeds_of_selling(notional: Decimal, rate: Decimal) -> Decimal:
    """Everything a sale puts into the wallet: the coins' value minus the fee."""
    return notional - fee_for(notional, rate)
