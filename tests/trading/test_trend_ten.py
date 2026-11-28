"""The ten-coin trend test, on small hand-built daily price histories.

Prices are plain whole numbers; the code does not care what one unit is
worth. No real price is used here.
"""

import random
from array import array
from fractions import Fraction as F

import pytest

from exchange.history import Candles
from trading import trend
from trading.trend import FEE_STANDARD, SLIPPAGE, STAKE, Params
from trading.trend_ten import (
    AT_PERIOD_END,
    BY_SIGNAL,
    COIN_REMOVED,
    MAX_OPEN,
    MONEY,
    RULE,
    Costs,
    Outcome,
    Trade,
    beats_hold,
    hold_trades,
    last_candle,
    outcome,
    pass_mark,
    replay,
    seen_closes,
)

SHORT = Params(buy_days=3, sell_days=2)
FLAT = [100] * 12
# Closes above the three days before on day 3: bought at day 4's open.
UP = [100, 100, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190]


def days(closes: list[int], symbol: str, opens: list[int] | None = None) -> Candles:
    """Daily candles; 0 is a day without a candle. Without `opens`, each day
    opens at the close before it."""
    if opens is None:
        opens = [closes[0], *closes[:-1]]
        opens = [o if c else 0 for o, c in zip(opens, closes, strict=True)]
    highs = [max(o, c) for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) for o, c in zip(opens, closes, strict=True)]
    columns = [array("q", column) for column in (opens, highs, lows, closes)]
    return Candles(symbol, 0, *columns, step=1440)


def free(*symbols: str) -> Costs:
    return Costs(F(0), dict.fromkeys(symbols, F(0)))


def short(series: list[Candles], end: int = 12, max_open: int = MAX_OPEN):  # noqa: ANN201
    return replay(series, 0, end, rule=SHORT, max_open=max_open)


def brief(trades: tuple[Trade, ...]) -> list[tuple]:
    return [(t.symbol, t.buy_day, t.sell_day, t.ended) for t in trades]


# --- what was fixed in the roadmap ---


def test_the_fixed_numbers() -> None:
    assert (RULE.buy_days, RULE.sell_days) == (20, 20)
    assert (MAX_OPEN, STAKE, MONEY) == (3, 24, 72)
    assert MAX_OPEN * STAKE == MONEY


# --- the costs ---


def test_an_order_fills_worse_by_the_slippage_plus_half_the_spread() -> None:
    costs = Costs(FEE_STANDARD, {"A": F(2, 1000), "B": F(0)})
    assert costs.worse("A") == SLIPPAGE + F(1, 1000)
    assert costs.worse("B") == SLIPPAGE
    trade = Trade("A", 1, 5, 100, 110, STAKE)
    worse, keep = F(15, 10000), F(999, 1000)
    coins = STAKE / (100 * (1 + worse)) * keep
    assert trade.coins(costs) == coins
    assert trade.profit(costs) == coins * 110 * (1 - worse) * keep - STAKE
    # A wider spread costs more; a flat price still loses money.
    assert trade.profit(costs) < Trade("B", 1, 5, 100, 110, STAKE).profit(costs)
    assert Trade("B", 1, 5, 100, 100, STAKE).profit(costs) < 0


def test_with_no_spread_the_costs_are_those_of_stage_7b() -> None:
    old = trend.Trade("A", 1, 5, 100, 110)
    new = Trade("A", 1, 5, 100, 110, STAKE)
    assert new.profit(Costs(FEE_STANDARD, {"A": F(0)})) == old.profit(FEE_STANDARD)


# --- the same rule as stage 7b ---


def test_with_room_for_every_coin_it_trades_exactly_as_stage_7b() -> None:
    """Random prices, three coins, three places: the shared pot never gets in
    the way, so every trade and every day's money must equal stage 7b's."""
    rule = Params(buy_days=5, sell_days=4)
    for seed in range(30):
        rng = random.Random(seed)
        series = []
        for symbol in ("A", "B", "C"):
            price, closes, opens = 1000, [], []
            for _ in range(150):
                opens.append(max(1, price + rng.randint(-15, 15)))
                price = max(1, price + rng.randint(-60, 60))
                closes.append(price)
            series.append(days(closes, symbol, opens))
        start, end = 10, 150
        new = replay(series, start, end, rule=rule)
        old = [t for c in series for t in trend.trades_of(c, rule, start, end)]
        assert new.dropped == 0
        assert sorted(
            (t.symbol, t.buy_day, t.sell_day, t.buy_price, t.sell_price)
            for t in new.trades
        ) == sorted(
            (t.symbol, t.buy_day, t.sell_day, t.buy_price, t.sell_price) for t in old
        )
        assert sum(t.ended == AT_PERIOD_END for t in new.trades) == sum(
            t.at_period_end for t in old
        )
        mine = outcome(series, new.trades, start, end, free("A", "B", "C"))
        theirs = trend.outcome(series, old, start, end, F(0))
        assert mine.profit == theirs.profit
        assert mine.curve == theirs.curve


def test_the_order_is_at_the_next_days_open() -> None:
    closes = [100, 100, 100, 110, 120, 130, 90, 95, 95]
    opens = [100, 100, 100, 100, 111, 121, 131, 88, 95]
    (trade,) = short([days(closes, "A", opens)], end=9).trades
    assert (trade.buy_day, trade.buy_price) == (4, 111)
    assert (trade.sell_day, trade.sell_price, trade.ended) == (7, 88, BY_SIGNAL)
    assert trade.stake == 24


def test_a_trade_open_on_the_last_day_is_sold_at_that_close() -> None:
    (trade,) = short([days(UP, "A")]).trades
    assert (trade.sell_day, trade.sell_price, trade.ended) == (11, 190, AT_PERIOD_END)
    # A signal on the last day has no next day and is ignored.
    assert short([days([100, 100, 100, 110], "A")], end=4).trades == ()


# --- three places for ten coins ---


def test_at_most_three_are_open_and_the_largest_coins_are_served_first() -> None:
    series = [days(UP, name) for name in ("A", "B", "C", "D", "E")]
    result = short(series, end=6)
    # All five signal on day 3. The first three in rank order get the places.
    assert brief(result.trades) == [
        ("A", 4, 5, AT_PERIOD_END),
        ("B", 4, 5, AT_PERIOD_END),
        ("C", 4, 5, AT_PERIOD_END),
    ]
    # D and E were refused on day 4. (Day 4's own signals would be orders on
    # day 5, the last day: the signal of the day before the last is dropped
    # too, as there is still no place.)
    assert result.dropped == 4
    # The rank is the order of the list, not the name.
    backwards = short(list(reversed(series)), end=6)
    assert [t.symbol for t in backwards.trades] == ["E", "D", "C"]


def test_a_dropped_signal_is_gone_the_coin_needs_a_new_one() -> None:
    falls = [100, 100, 100, 110, 120, 90, 90, 90, 90, 90, 90, 90]  # sold on day 6
    once = [100, 100, 100, 110, 110, 110, 110, 110, 110, 110, 110, 110]
    again = [100, 100, 100, 110, 110, 110, 110, 110, 120, 120, 120, 120]
    result = short(
        [days(falls, "A"), days(UP, "B"), days(UP, "C"), days(once, "D")],
    )
    # D signalled once, on day 3, and found no place. A's sale on day 6 frees
    # one, but D's old signal does not come back.
    assert "D" not in [t.symbol for t in result.trades]
    assert result.dropped == 1
    result = short(
        [days(falls, "A"), days(UP, "B"), days(UP, "C"), days(again, "D")],
    )
    # A new high on day 8 is a new signal: bought on day 9, in the free place.
    assert ("D", 9, 11, AT_PERIOD_END) in brief(result.trades)


def test_a_mornings_sale_frees_its_place_for_a_buy_the_same_morning() -> None:
    falls = [100, 100, 100, 110, 120, 90, 90, 90, 90, 90, 90, 90]
    late = [100, 100, 100, 100, 100, 110, 110, 110, 110, 110, 110, 110]
    result = short(
        [days(late, "A"), days(falls, "B"), days(UP, "C"), days(UP, "D")],
    )
    # B, C and D hold the three places from day 4. On day 5, B makes a new
    # low and A a new high. On day 6 B is sold first, then A takes its place,
    # although A is listed (ranked) before B.
    assert ("B", 4, 6, BY_SIGNAL) in brief(result.trades)
    assert ("A", 6, 11, AT_PERIOD_END) in brief(result.trades)
    assert result.dropped == 0
    # With only the sale missing there would have been no place.
    stays = short([days(late, "A"), days(UP, "B"), days(UP, "C"), days(UP, "D")])
    assert "A" not in [t.symbol for t in stays.trades] and stays.dropped == 1


def test_one_trade_per_coin_at_a_time() -> None:
    result = short([days(UP, "A")], max_open=3)
    assert len(result.trades) == 1 and result.dropped == 0


# --- a coin removed from Binance, and missing days ---


def test_a_removed_coin_is_sold_at_its_last_close_and_is_silent_afterwards() -> None:
    gone = [100, 100, 100, 110, 120, 130, 140, 0, 0, 0, 0, 0]
    series = [days(gone, "A"), days(FLAT, "B")]
    assert last_candle(series[0], 12) == 6 and last_candle(series[1], 12) == 11
    assert last_candle(days([0, 0], "C"), 2) == -1
    result = short(series)
    (trade,) = result.trades
    assert (trade.buy_day, trade.sell_day, trade.sell_price) == (4, 6, 140)
    assert trade.ended == COIN_REMOVED
    assert result.dropped == 0  # its new high on day 6 is not a signal
    # Buy-and-hold sells it on the same day at the same price.
    held = hold_trades(series, 0, 12)
    assert [(t.sell_day, t.sell_price, t.ended) for t in held] == [
        (6, 140, COIN_REMOVED),
        (11, 100, AT_PERIOD_END),
    ]
    # Its money stays in the count after it is gone.
    costs = free("A", "B")
    result_money = outcome(series, result.trades, 0, 12, costs)
    assert result_money.curve[6] == result_money.curve[11] == 72 + trade.profit(costs)


def test_a_signal_needs_every_one_of_its_earlier_days() -> None:
    hole = [100, 0, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    (trade,) = short([days(hole, "A", [100, 0, *UP[1:-1]])]).trades
    # Day 3 and day 4 look back over the missing day: no signal. Day 5 is the
    # first with three whole days before it: bought on day 6.
    assert trade.buy_day == 6


def test_a_buy_on_a_day_without_a_candle_is_dropped_and_a_sale_waits() -> None:
    no_buy_day = [100, 100, 100, 110, 0, 130, 130, 130, 130, 130, 130, 130]
    result = short([days(no_buy_day, "A", [100, 100, 100, 100, 0, *[130] * 7])])
    assert result.trades == () and result.dropped == 1
    #      day:    0    1    2    3    4    5   6  7   8   9  10  11
    closes = [100, 100, 100, 110, 120, 90, 0, 0, 80, 80, 80, 80]
    opens = [100, 100, 100, 100, 111, 121, 0, 0, 77, 80, 80, 80]
    series = [days(closes, "A", opens)]
    (trade,) = short(series).trades
    # The new low of day 5 is a sale at the next candle's open: day 8, at 77.
    assert (trade.buy_day, trade.sell_day, trade.sell_price) == (4, 8, 77)
    # On the days without a candle the money is counted at the last close seen.
    assert seen_closes(series[0], 12)[5:9] == [90, 90, 90, 80]
    money = outcome(series, [trade], 0, 12, free("A"))
    assert money.curve[5] == money.curve[6] == money.curve[7]
    # 24 USDT bought at 111, 0.05% worse (no fee and no spread here).
    assert money.curve[5] == 72 + F(24) / (111 * (1 + SLIPPAGE)) * 90 - 24


def test_a_waiting_sale_keeps_its_place() -> None:
    #       day:  0    1    2    3    4    5  6  7   8   9  10  11
    stuck = [100, 100, 100, 110, 120, 90, 0, 0, 80, 80, 80, 80]
    opens = [100, 100, 100, 100, 111, 121, 0, 0, 77, 80, 80, 80]
    late = [100, 100, 100, 100, 100, 110, 110, 110, 110, 110, 110, 110]
    series = [days(stuck, "A", opens), days(UP, "B"), days(UP, "C"), days(late, "D")]
    result = short(series)
    # A's sale waits from day 6 to day 8. D's buy on day 6 finds A still there.
    assert ("A", 4, 8, BY_SIGNAL) in brief(result.trades)
    assert "D" not in [t.symbol for t in result.trades] and result.dropped == 1


def test_a_coin_bought_on_its_last_day_is_sold_at_that_close() -> None:
    gone = [100, 100, 100, 100, 100, 110, 120, 0, 0, 0, 0, 0]
    result = short([days(gone, "A"), days(FLAT, "B")])
    # The new high of day 5 is bought at day 6's open (110), the coin's last
    # day, and sold at that day's close (120).
    (trade,) = result.trades
    assert (trade.buy_day, trade.sell_day, trade.ended) == (6, 6, COIN_REMOVED)
    assert (trade.buy_price, trade.sell_price) == (110, 120)
    # A coin that is not held and makes a new high on its last day: nothing.
    quiet = [100, 100, 100, 100, 100, 100, 120, 0, 0, 0, 0, 0]
    result = short([days(quiet, "A"), days(FLAT, "B")])
    assert result.trades == () and result.dropped == 0


# --- buy-and-hold ---


def test_buy_and_hold_splits_the_money_equally_over_the_coins() -> None:
    ten = [days(UP, f"C{i}") for i in range(10)]
    trades = hold_trades(ten, 2, 12)
    assert {t.stake for t in trades} == {F(72, 10)}  # 7.20 USDT each
    assert {(t.buy_day, t.buy_price, t.sell_day, t.sell_price) for t in trades} == {
        (2, 100, 11, 190)  # the first day's OPEN, the last day's CLOSE
    }
    seven = hold_trades(ten[3:], 2, 12)
    assert {t.stake for t in seven} == {F(72, 7)}
    assert sum(t.stake for t in seven) == sum(t.stake for t in trades) == 72
    with pytest.raises(ValueError, match="no candle on the first day"):
        hold_trades([days([0, 100, 100], "A", [0, 100, 100])], 0, 3)


def test_buy_and_hold_pays_each_coins_own_spread() -> None:
    series = [days(UP, "A"), days(UP, "B")]
    costs = Costs(FEE_STANDARD, {"A": F(0), "B": F(1, 100)})
    held = outcome(series, hold_trades(series, 0, 12), 0, 12, costs)
    assert held.profits[1] < held.profits[0]
    assert held.profit == sum(held.profits)


# --- the money, day by day ---


def test_the_money_is_counted_at_each_close() -> None:
    closes = [100, 100, 100, 110, 120, 130, 90, 95, 95]
    opens = [100, 100, 100, 100, 111, 121, 131, 88, 95]
    series = [days(closes, "A", opens)]
    result = short(series, end=9)
    money = outcome(series, result.trades, 0, 9, free("A"))
    # No fee and no spread here: only the 0.05% worse fill on both orders.
    coins = F(24) / (111 * (1 + SLIPPAGE))
    sold = coins * 88 * (1 - SLIPPAGE)
    assert money.curve[:4] == (72, 72, 72, 72)
    assert money.curve[4:7] == (
        72 + coins * 120 - 24,
        72 + coins * 130 - 24,
        72 + coins * 90 - 24,
    )
    assert money.curve[7] == money.curve[8] == 72 + sold - 24
    assert money.profit == sold - 24
    assert money.profit_without_best == 0  # one losing trade: nothing to take away
    peak = 72 + coins * 130 - 24
    assert money.worst_drop == (peak - money.curve[7]) / peak


# --- the pass mark ---


def made(profits: list[int], curve: list[int]) -> Outcome:
    trades = tuple(Trade("A", 0, 1, 1, 1, STAKE) for _ in profits)
    return Outcome(trades, tuple(F(p) for p in profits), tuple(F(c) for c in curve))


CALM = [100, 80, 120]  # a 20% drop
WILD = [100, 60, 150]  # a 40% drop


def test_condition_c_at_least_holds_profit_or_half_with_half_the_drop() -> None:
    held = made([100], WILD)
    assert beats_hold(made([100], WILD), held)  # equal profit is enough
    assert not beats_hold(made([99], WILD), held)  # less, with the same drop
    assert beats_hold(made([50], CALM), held)  # exactly half, exactly half
    assert not beats_hold(made([49], CALM), held)  # a little under half
    assert not beats_hold(made([50], [100, 79, 120]), held)  # a 21% drop
    # When holding lost money, losing less is "at least its profit".
    assert beats_hold(made([-5], WILD), made([-10], WILD))


def test_all_five_conditions_and_each_one_alone() -> None:
    good = made([2] * 25, CALM)  # 25 trades, +50
    held = made([60], WILD)

    def marks(**changes: Outcome) -> list[bool]:
        four = {"bot_ten": good, "hold_ten": held, "bot_seven": good, **changes}
        four.setdefault("hold_seven", held)
        return list(pass_mark(**four).values())

    assert marks() == [True] * 5
    few = made([50], CALM)  # the same profit in one trade
    assert marks(bot_seven=few) == [False, True, True, True, True]
    assert marks(bot_ten=made([2] * 19 + [12], CALM))[0] is True  # exactly 20
    assert marks(bot_ten=made([2] * 18 + [14], CALM))[0] is False  # 19
    lost = made([-1] * 25, CALM)
    assert marks(bot_ten=lost) == [True, False, False, False, True]
    assert marks(hold_ten=made([101], WILD)) == [True, True, False, True, True]
    one_lucky = made([-1] * 24 + [74], CALM)  # +50, but -24 without the best
    assert marks(bot_ten=one_lucky) == [True, True, True, False, True]
    assert marks(bot_ten=made([0] * 24 + [50], CALM))[3] is False  # exactly zero
    assert marks(hold_seven=made([101], WILD)) == [True, True, True, True, False]
    assert marks(bot_ten=made([0] * 25, CALM))[1] is False  # exactly zero profit
    # (e) is the wording of (c): losing less than a losing hold counts.
    seven_lost = {"bot_seven": made([-1] * 25, CALM), "hold_seven": made([-30], WILD)}
    assert marks(**seven_lost) == [True] * 5
    names = list(pass_mark(good, held, good, held))
    assert [name[:3] for name in names] == ["(a)", "(b)", "(c)", "(d)", "(e)"]
