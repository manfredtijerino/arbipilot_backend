"""Fee maths, to the last digit."""

from decimal import Decimal as D

import pytest

from trading.fees import cost_of_buying, fee_for, proceeds_of_selling

STANDARD = D("0.001")  # 0.1%
WITH_BNB = D("0.00075")  # 0.075%


def test_the_fee_is_the_share_of_the_orders_value() -> None:
    assert fee_for(D("24"), STANDARD) == D("0.024")  # 2.4 cents
    assert fee_for(D("24"), WITH_BNB) == D("0.018")
    assert fee_for(D("300"), STANDARD) == D("0.3")


def test_the_fee_is_rounded_up_never_down() -> None:
    # 0.123456789 * 0.001 = 0.000123456789 -> up to the 8th decimal.
    assert fee_for(D("0.123456789"), STANDARD) == D("0.00012346")
    assert fee_for(D("0.00000001"), STANDARD) == D("0.00000001")
    # Already exact at 8 decimals: nothing is added.
    assert fee_for(D("0.00001"), STANDARD) == D("0.00000001")


def test_nothing_costs_nothing() -> None:
    assert fee_for(D("0"), STANDARD) == 0
    assert fee_for(D("24"), D("0")) == 0


def test_a_buy_costs_the_coins_plus_the_fee() -> None:
    assert cost_of_buying(D("24"), STANDARD) == D("24.024")


def test_a_sale_brings_the_value_minus_the_fee() -> None:
    assert proceeds_of_selling(D("24"), STANDARD) == D("23.976")


def test_a_round_trip_at_the_same_price_loses_both_fees() -> None:
    spent = cost_of_buying(D("24"), STANDARD)
    back = proceeds_of_selling(D("24"), STANDARD)
    assert back - spent == D("-0.048")  # 4.8 cents on a 24 USDT trade


@pytest.mark.parametrize(
    ("notional", "rate"),
    [
        (D("-1"), STANDARD),
        (D("24"), D("-0.001")),
        (D("NaN"), STANDARD),
        (D("Infinity"), STANDARD),
        (24.0, STANDARD),
        (D("24"), 0.001),
        ("24", STANDARD),
    ],
)
def test_strange_amounts_are_refused(notional: object, rate: object) -> None:
    with pytest.raises(ValueError, match="plain amounts"):
        fee_for(notional, rate)  # type: ignore[arg-type]
