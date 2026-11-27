"""Pretend fills, to the last digit."""

from decimal import Decimal as D

import pytest

from trading import paper
from trading.paper import Holding
from trading.risk import Side

RATE = D("0.001")  # 0.1%
STEP = D("0.00001")


def test_a_buy_pays_the_ask_and_a_sale_gets_the_bid() -> None:
    assert paper.fill_price(Side.BUY, D("99"), D("101")) == D("101")
    assert paper.fill_price(Side.SELL, D("99"), D("101")) == D("99")
    assert paper.fill_price(Side.BUY, D("99"), None) is None
    assert paper.fill_price(Side.SELL, None, D("101")) is None
    assert paper.fill_price(Side.SELL, D("0"), D("101")) is None


def test_a_buy_takes_the_coins_and_the_fee_out_of_the_wallet() -> None:
    fill = paper.buy(D("300"), None, D("0.0004"), D("60000"), RATE)
    assert fill.notional == D("24.0000")
    assert fill.fee == D("0.024")  # 0.1% of 24
    assert fill.cash_after == D("275.976")
    assert fill.holding_after == Holding(D("0.0004"), D("24.024"))
    assert fill.realized_pnl is None and fill.side is Side.BUY


def test_a_second_buy_adds_to_what_is_held() -> None:
    held = Holding(D("0.0004"), D("24.024"))
    fill = paper.buy(D("100"), held, D("0.0001"), D("50000"), RATE)
    assert fill.holding_after == Holding(D("0.0005"), D("24.024") + D("5.005"))
    assert fill.cash_after == D("94.995")


def test_a_buy_that_does_not_fit_is_refused() -> None:
    paper.buy(D("24.024"), None, D("0.0004"), D("60000"), RATE)  # exactly fits
    with pytest.raises(ValueError, match="does not fit"):
        paper.buy(D("24.023"), None, D("0.0004"), D("60000"), RATE)
    with pytest.raises(ValueError, match="does not fit"):
        paper.buy(D("300"), None, D("0"), D("60000"), RATE)


def test_selling_everything_shows_the_whole_profit_or_loss() -> None:
    held = Holding(D("0.0004"), D("24.024"))
    fill = paper.sell(D("275.976"), held, D("0.0004"), D("60000"), RATE)
    # The same price in and out: both fees are lost, 4.8 cents.
    assert fill.fee == D("0.024") and fill.notional == D("24.0000")
    assert fill.cash_after == D("299.952")
    assert fill.realized_pnl == D("-0.048")
    assert fill.holding_after == Holding(D("0"), D("0"))


def test_a_sale_at_a_higher_price_is_a_profit_after_both_fees() -> None:
    held = Holding(D("0.0004"), D("24.024"))
    fill = paper.sell(D("0"), held, D("0.0004"), D("66000"), RATE)
    assert fill.notional == D("26.4000") and fill.fee == D("0.0264")
    assert fill.realized_pnl == D("26.3736") - D("24.024") == D("2.3496")


def test_selling_a_part_keeps_the_rest_of_the_cost() -> None:
    held = Holding(D("0.0003"), D("18.018"))
    fill = paper.sell(D("0"), held, D("0.0001"), D("60000"), RATE)
    assert fill.holding_after == Holding(D("0.0002"), D("12.012"))
    assert fill.realized_pnl == D("5.994") - D("6.006") == D("-0.012")
    # The two parts of the cost always add up to the whole.
    odd = Holding(D("0.0003"), D("10.00000001"))
    part = paper.sell(D("0"), odd, D("0.0001"), D("60000"), RATE)
    assert part.holding_after == Holding(D("0.0002"), D("6.66666667"))
    assert part.holding_after.cost + D("3.33333334") == odd.cost


def test_an_order_value_with_too_many_decimals_never_flatters_the_wallet() -> None:
    quantity, price = D("0.00000003"), D("0.33333333")  # 0.0000000099999999
    assert paper.order_value(quantity, price, Side.BUY) == D("0.00000001")
    assert paper.order_value(quantity, price, Side.SELL) == D("0.00000000")
    assert paper.order_value(D("0.0004"), D("59896.01"), Side.BUY) == D("23.958404")
    assert str(paper.order_value(D("0.0004"), D("60000"), Side.SELL)) == "24.00000000"


def test_more_than_is_held_cannot_be_sold() -> None:
    held = Holding(D("0.0004"), D("24.024"))
    with pytest.raises(ValueError, match="more is being sold"):
        paper.sell(D("0"), held, D("0.00041"), D("60000"), RATE)
    with pytest.raises(ValueError, match="more is being sold"):
        paper.sell(D("0"), held, D("0"), D("60000"), RATE)


def test_an_order_using_all_the_cash_is_cut_to_leave_room_for_the_fee() -> None:
    price = D("60000")
    # 24 USDT of cash: 0.0004 would cost 24.024 with the fee.
    assert paper.quantity_that_fits(D("0.0004"), price, D("24"), RATE, STEP) == D(
        "0.00039"
    )
    # Exactly enough for the coins and the fee: nothing is cut.
    assert paper.quantity_that_fits(D("0.0004"), price, D("24.024"), RATE, STEP) == D(
        "0.0004"
    )
    # Plenty of cash: the asked quantity stands.
    assert paper.quantity_that_fits(D("0.0004"), price, D("300"), RATE, STEP) == D(
        "0.0004"
    )
    assert paper.quantity_that_fits(D("0.0004"), price, D("0"), RATE, STEP) == 0


def test_what_fits_can_always_be_bought() -> None:
    for cash in ("5.01", "7.77777777", "23.99999999", "24.02399999", "24.024"):
        fits = paper.quantity_that_fits(D("0.0004"), D("60000"), D(cash), RATE, STEP)
        fill = paper.buy(D(cash), None, fits, D("60000"), RATE)
        assert fill.cash_after >= 0
        more = fits + STEP
        if more <= D("0.0004"):
            with pytest.raises(ValueError):
                paper.buy(D(cash), None, more, D("60000"), RATE)
