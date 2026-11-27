"""The trend test, on small hand-built daily price histories.

Prices are plain whole numbers; the code does not care what one unit is worth.
"""

import random
from array import array
from fractions import Fraction as F

import pytest

from exchange.history import Candles
from trading.trend import (
    ALL_PARAMS,
    FEE_STANDARD,
    FEE_WITH_BNB,
    SLIPPAGE,
    STAKE,
    Outcome,
    Params,
    Trade,
    choose,
    hold,
    is_new_high,
    is_new_low,
    outcome,
    pass_mark,
    require_every_day,
    run,
    trades_of,
    worst_drop,
)

SHORT = Params(buy_days=3, sell_days=2)
NO_FEE = F(0)


def days(
    closes: list[int], opens: list[int] | None = None, symbol: str = "BTCUSDT"
) -> Candles:
    """Daily candles. Without `opens`, each day opens at the close before it."""
    if opens is None:
        opens = [closes[0], *closes[:-1]]
    highs = [max(o, c) for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) for o, c in zip(opens, closes, strict=True)]
    columns = [array("q", column) for column in (opens, highs, lows, closes)]
    return Candles(symbol, 0, *columns, step=1440)


# --- the signals ---


def test_a_new_high_must_be_above_the_earlier_days_not_equal() -> None:
    assert is_new_high([10, 12, 11, 13], 3, 3)
    assert not is_new_high([10, 13, 11, 13], 3, 3)  # equal to the highest
    assert not is_new_high([10, 14, 11, 13], 3, 3)
    assert is_new_high([99, 12, 11, 13], 3, 2)  # only the 2 days before count


def test_a_new_low_must_be_below_the_earlier_days_not_equal() -> None:
    assert is_new_low([10, 12, 11, 9], 3, 3)
    assert not is_new_low([10, 9, 11, 9], 3, 3)
    assert is_new_low([1, 12, 11, 9], 3, 2)


def test_the_day_itself_is_not_one_of_the_earlier_days() -> None:
    # If day 3 counted in its own window, 13 could never be above the highest.
    assert is_new_high([10, 10, 10, 13], 3, 3)
    assert is_new_low([10, 10, 10, 7], 3, 3)


def test_no_signal_without_every_earlier_day() -> None:
    assert not is_new_high([10, 11, 13], 2, 3)  # only 2 days before
    assert not is_new_high([10, 0, 11, 13], 3, 3)  # a missing day in the window
    assert not is_new_low([10, 0, 11, 9], 3, 3)
    assert not is_new_high([10, 11, 12, 0], 3, 3)  # the day itself is missing


# --- one trade and its costs ---


def test_the_order_is_at_the_next_days_open_never_at_the_signal_price() -> None:
    closes = [100, 100, 100, 110, 120, 130, 90, 95, 95]
    opens = [100, 100, 100, 100, 111, 121, 131, 88, 95]
    (trade,) = trades_of(days(closes, opens), SHORT, 0, 9)
    # Day 3 closes at 110, above 100: bought at day 4's open, 111, not at 110.
    assert (trade.buy_day, trade.buy_price) == (4, 111)
    # Day 6 closes at 90, below the lowest of days 4 and 5: sold at day 7's open.
    assert (trade.sell_day, trade.sell_price, trade.at_period_end) == (7, 88, False)


def test_the_costs_of_a_trade_are_exact() -> None:
    trade = Trade("BTCUSDT", 1, 5, 100, 110)
    assert (
        trade.profit(NO_FEE)
        == STAKE * (F(110) * (1 - SLIPPAGE)) / (F(100) * (1 + SLIPPAGE)) - STAKE
    )
    # +10% on 24 USDT is 2.40; the two worse fills and two fees take about 0.08.
    with_fee = trade.profit(FEE_STANDARD)
    assert with_fee == STAKE * F(110 * 9995, 100 * 10005) * F(999, 1000) ** 2 - STAKE
    assert F(232, 100) < with_fee < F(233, 100)
    assert trade.profit(FEE_WITH_BNB) > with_fee
    flat = Trade("BTCUSDT", 1, 5, 100, 100)
    assert flat.profit(FEE_STANDARD) < 0  # no price change still costs money


def test_no_second_buy_while_a_trade_is_open() -> None:
    closes = [100, 100, 100, 110, 120, 130, 140, 150]
    trades = trades_of(days(closes), SHORT, 0, 8)
    assert [(t.buy_day, t.at_period_end) for t in trades] == [(4, True)]


def test_a_trade_open_on_the_last_day_is_sold_at_that_close() -> None:
    closes = [100, 100, 100, 110, 120, 130]
    (trade,) = trades_of(days(closes), SHORT, 0, 6)
    assert (trade.sell_day, trade.sell_price, trade.at_period_end) == (5, 130, True)


def test_a_signal_on_the_last_day_has_no_next_day_and_is_ignored() -> None:
    closes = [100, 100, 100, 100, 100, 110]
    assert trades_of(days(closes), SHORT, 0, 6) == []
    # One more day in the period and the same signal is traded.
    assert len(trades_of(days([*closes, 111]), SHORT, 0, 7)) == 1


def test_a_period_uses_earlier_days_only_to_look_back() -> None:
    closes = [100, 100, 100, 110, 120, 130, 140, 150, 160]
    # The period starts on day 5. The signal of day 3 is before it: no order
    # from it. Day 5's close (130) is above days 2 to 4, so day 6 buys.
    (trade,) = trades_of(days(closes), SHORT, 5, 9)
    assert trade.buy_day == 6
    # A period that ends on day 4 never sees the later days.
    (early,) = trades_of(days(closes), SHORT, 0, 5)
    assert (early.buy_day, early.sell_day, early.sell_price) == (4, 4, 120)


def test_an_order_day_without_a_candle_is_an_error() -> None:
    closes = [100, 100, 100, 110, 0, 130]
    with pytest.raises(ValueError, match="no candle on the day of an order"):
        trades_of(days(closes, [100, 100, 100, 100, 0, 110]), SHORT, 0, 6)


def test_buy_again_after_a_sale() -> None:
    closes = [100, 100, 100, 110, 120, 90, 95, 96, 130, 140, 150]
    trades = trades_of(days(closes), SHORT, 0, 11)
    assert [(t.buy_day, t.sell_day) for t in trades] == [(4, 6), (9, 10)]


# --- counting the money ---


def test_buy_and_hold_buys_the_first_open_and_sells_the_last_close() -> None:
    btc = days([100, 150, 50, 200], [80, 100, 150, 50])
    held = hold([btc], 0, 4, FEE_STANDARD)
    (trade,) = held.trades
    assert (trade.buy_day, trade.buy_price, trade.sell_day) == (0, 80, 3)
    assert (trade.sell_price, trade.at_period_end) == (200, True)
    assert held.profit == trade.profit(FEE_STANDARD) == held.curve[-1] - STAKE
    coins = trade.coins(FEE_STANDARD)
    assert held.curve[:3] == (coins * 100, coins * 150, coins * 50)
    assert held.worst_drop == F(2, 3)  # from 150 down to 50


def test_buy_and_hold_and_the_bot_pay_the_same_costs() -> None:
    btc = days([100, 100, 100, 110, 120, 130, 140])
    # Hold from day 4: bought at day 4's open (110), sold at the last close.
    held = hold([btc], 4, 7, FEE_STANDARD)
    assert held.trades == (Trade("BTCUSDT", 4, 6, 110, 140, True),)
    # The bot sees day 4's close (a new high) and buys at day 5's open.
    bot = run([btc], SHORT, 4, 7, FEE_STANDARD)
    assert bot.trades == (Trade("BTCUSDT", 5, 6, 120, 140, True),)
    assert bot.curve[0] == STAKE  # day 4: still only the 24 USDT
    # The same prices in and out cost both exactly the same.
    same = Trade("BTCUSDT", 5, 6, 120, 140, True)
    assert bot.profit == same.profit(FEE_STANDARD) < same.profit(F(0))
    bought_at_110 = Trade("BTCUSDT", 4, 6, 110, 140, True)
    assert held.profit == bought_at_110.profit(FEE_STANDARD)
    assert held.profit == STAKE * F(140 * 9995, 110 * 10005) * F(999, 1000) ** 2 - STAKE


def test_the_bots_money_is_counted_every_day() -> None:
    closes = [100, 100, 100, 110, 120, 130, 90, 95, 95]
    opens = [100, 100, 100, 100, 111, 121, 131, 88, 95]
    eth = days([50] * 9, symbol="ETHUSDT")  # never trades
    result = run([days(closes, opens), eth], SHORT, 0, 9, NO_FEE)
    (trade,) = result.trades
    coins, profit = trade.coins(NO_FEE), trade.profit(NO_FEE)
    assert result.curve == (
        *[2 * STAKE] * 4,  # no trade yet: 24 USDT for each of the two pairs
        2 * STAKE + coins * 120 - STAKE,  # day 4: open, counted at the close
        2 * STAKE + coins * 130 - STAKE,
        2 * STAKE + coins * 90 - STAKE,  # the day of the sell signal
        2 * STAKE + profit,  # day 7: sold at the open
        2 * STAKE + profit,
    )
    assert result.profit == profit and profit < 0


def test_the_money_of_several_pairs_is_added_up() -> None:
    closes = [100, 100, 100, 110, 120, 130, 140]
    btc, eth = days(closes), days(closes, symbol="ETHUSDT")
    one = run([btc], SHORT, 0, 7, FEE_STANDARD)
    two = run([btc, eth], SHORT, 0, 7, FEE_STANDARD)
    assert [t.symbol for t in two.trades] == ["BTCUSDT", "ETHUSDT"]
    assert two.profit == 2 * one.profit
    assert two.curve == tuple(2 * money for money in one.curve)


def test_bought_and_sold_on_the_last_day_counts_only_on_that_day() -> None:
    closes = [100, 100, 100, 100, 110, 115]
    result = run([days(closes)], SHORT, 0, 6, FEE_STANDARD)
    (trade,) = result.trades
    assert (trade.buy_day, trade.sell_day, trade.at_period_end) == (5, 5, True)
    assert result.curve == (*[STAKE] * 5, STAKE + trade.profit(FEE_STANDARD))


def test_a_missing_day_stops_the_test() -> None:
    whole, holed = days([100] * 6), days([100, 100, 0, 100, 100, 100])
    require_every_day([whole], 0, 6)
    require_every_day([holed], 3, 6)  # the hole is before the days used
    with pytest.raises(ValueError, match="a day is missing"):
        require_every_day([whole, holed], 0, 6)
    with pytest.raises(ValueError, match="a day is missing"):
        require_every_day([whole], 0, 7)  # the data ends too early
    gap = days([100, 100, 100, 110, 0, 130], [100, 100, 100, 100, 111, 120])
    with pytest.raises(ValueError, match="inside a trade is missing"):
        run([gap], SHORT, 0, 6, FEE_STANDARD)


def test_the_worst_drop_is_from_an_earlier_high() -> None:
    assert worst_drop([F(100), F(120), F(90), F(150), F(120)]) == F(1, 4)
    assert worst_drop([F(100), F(110), F(120)]) == 0
    assert worst_drop([F(50), F(100)]) == 0  # a low before the high is no drop
    assert worst_drop([]) == 0


# --- the procedure and the pass mark ---


def made(profits: list[F], curve: list[int] | None = None) -> Outcome:
    trades = tuple(Trade("BTCUSDT", i, i + 1, 100, 100) for i in range(len(profits)))
    return Outcome(trades, tuple(profits), tuple(F(x) for x in curve or [72]))


def test_the_winner_needs_20_trades_and_a_profit_above_zero() -> None:
    a, b, c, d = ALL_PARAMS
    results = [
        (a, made([F(5)] * 19)),  # the most money, one trade short
        (b, made([F(1)] * 20)),
        (c, made([F(2)] * 30)),
        (d, made([F(3)] * 20)),  # a tie with c: the one listed first wins
    ]
    assert choose(results) == c
    assert choose(results[:2]) == b
    assert choose(results[:1]) is None
    assert choose([(a, made([F(0)] * 20)), (b, made([F(-1)] * 25))]) is None


def test_the_four_combinations_are_the_ones_fixed_in_advance() -> None:
    assert [(p.buy_days, p.sell_days) for p in ALL_PARAMS] == [
        (20, 10),
        (20, 20),
        (55, 10),
        (55, 20),
    ]
    assert STAKE == 24 and FEE_STANDARD == F(1, 1000) and SLIPPAGE == F(5, 10000)


def marks(bot: Outcome, held: Outcome) -> list[bool]:
    return list(pass_mark(bot, held).values())


def test_the_pass_mark_at_its_exact_edges() -> None:
    held = made([F(40)], [100, 40, 140])  # +40 USDT, worst drop 60%
    twenty = [F(2)] * 20  # +40 in 20 trades
    assert marks(made(twenty), held) == [True, True, True, True]
    # 19 trades: too few, though 38 USDT with no drop satisfies (c).
    assert marks(made(twenty[:19]), held) == [False, True, True, True]
    # Less than hold with a deep drop fails (c).
    deep = made([F(39, 20)] * 20, [100, 50, 139])
    assert marks(deep, held) == [True, True, False, True]
    # Half of hold's profit (20) needs at most half of hold's drop (30%).
    half = [F(1)] * 20
    assert marks(made(half, [100, 70, 120]), held) == [True, True, True, True]
    assert marks(made(half, [1000, 699, 1200]), held) == [True, True, False, True]
    just_under = [F(1)] * 19 + [F(1) - F(1, 10**30)]
    assert marks(made(just_under, [100, 70, 120]), held) == [True, True, False, True]


def test_the_pass_mark_without_the_best_trade() -> None:
    held = made([F(10)], [100, 40, 110])
    lucky = [F(45)] + [F(-5, 19)] * 19  # +40 in total, -5 without the best
    assert marks(made(lucky), held) == [True, True, True, False]
    edge = [F(40)] + [F(0)] * 19  # exactly zero without the best is not above
    assert marks(made(edge), held) == [True, True, True, False]


def test_without_the_best_trade_when_every_trade_lost() -> None:
    losers = made([F(-1), F(-2), F(-3)])
    assert losers.profit == -6 and losers.profit_without_best == -5
    assert made([]).profit_without_best == 0


def test_a_loss_never_passes_even_when_holding_lost_more() -> None:
    held = made([F(-30)], [100, 40])
    assert marks(made([F(-1)] * 20), held) == [True, False, True, False]
    assert marks(made([F(1)] * 20), held) == [True, True, True, True]


# --- no peeking at the future ---


def random_days(symbol: str, seed: int, length: int) -> Candles:
    rng = random.Random(seed)
    closes, opens, price = [], [], 10**9
    for _ in range(length):
        opened = price + price * rng.randint(-50, 50) // 10_000
        price = max(1000, opened + opened * rng.randint(-600, 620) // 10_000)
        opens.append(opened)
        closes.append(price)
    return days(closes, opens, symbol)


@pytest.mark.parametrize("params", ALL_PARAMS)
def test_changing_the_future_changes_no_past_decision(params: Params) -> None:
    length, cut = 1500, 900
    original = random_days("BTCUSDT", 1, length)
    other = random_days("BTCUSDT", 2, length)
    changed = days(
        [*original.close[: cut + 1], *other.close[cut + 1 :]],
        [*original.open[: cut + 1], *other.open[cut + 1 :]],
    )

    # Every order placed up to day `cut` used only closes up to `cut - 1`.
    def decided(candles: Candles) -> list[tuple[int, int, int, int]]:
        return [
            (t.buy_day, t.buy_price, t.sell_day, t.sell_price)
            for t in trades_of(candles, params, 60, length)
            if t.sell_day <= cut and not t.at_period_end
        ]

    assert decided(original) == decided(changed) and len(decided(original)) >= 3
    # A period that simply ends at `cut` agrees on every finished trade.
    ended = trades_of(original, params, 60, cut + 1)
    assert [
        (t.buy_day, t.buy_price, t.sell_day, t.sell_price)
        for t in ended
        if not t.at_period_end
    ] == decided(original)
    assert outcome([original], ended, 60, cut + 1, FEE_STANDARD).curve
