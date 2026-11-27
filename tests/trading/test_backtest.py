"""The backtest simulator, on small hand-built price histories.

Prices here are plain whole numbers (10 000 = "100.00"); the simulator does
not care what one unit is worth.
"""

import random
from array import array
from fractions import Fraction as F

import pytest

from exchange.history import Candles
from trading.backtest import (
    ALL_PARAMS,
    FEE_STANDARD,
    FEE_WITH_BNB,
    SLIPPAGE,
    Params,
    Summary,
    Trade,
    _play_out,
    choose,
    pass_mark,
    simulate,
    summarise,
)
from trading.strategy import Dip

Row = tuple[int, int, int, int]  # open, high, low, close

FULL = Params(k=4, target_share=F(1), stop_multiple=1)
HALF = Params(k=4, target_share=F(1, 2), stop_multiple=1)
FLAT: Row = (10_000, 10_000, 10_000, 10_000)

# A dip at minute 0 with a distance of exactly 1%: entry 10 000,
# target 10 100 (full) and stop 9 900 (1x).
ONE_PERCENT = Dip(index=0, close=10_000, below=60, spread=1, total=6_000)


def candles(rows: list[Row], symbol: str = "BTCUSDT") -> Candles:
    """Candles from (open, high, low, close) rows; (0, 0, 0, 0) = missing."""
    columns = [array("q", column) for column in zip(*rows, strict=True)]
    return Candles(symbol, 0, *columns)


def play(*rows: Row, params: Params = FULL) -> tuple[int, Trade | None]:
    """Minute 0 is the dip's own minute; `rows` are the minutes after it."""
    return _play_out(candles([FLAT, *rows]), ONE_PERCENT, params)


FILL: Row = (10_000, 10_050, 9_999, 10_020)  # trades through 10 000
TOUCH: Row = (10_010, 10_050, 10_000, 10_020)  # only touches 10 000
QUIET: Row = (10_020, 10_050, 9_950, 10_020)  # between stop and target
ABOVE: Row = (10_020, 10_101, 9_950, 10_050)  # trades above the target


# --- the buy ---


def test_touching_the_price_is_not_a_fill() -> None:
    free_from, trade = play(TOUCH, TOUCH, FILL)
    assert trade is None and free_from == 2  # the order died after 2 minutes


def test_trading_through_the_price_is_a_fill_in_either_minute() -> None:
    assert play(FILL, QUIET, ABOVE)[1].fill_index == 1
    late = play(TOUCH, FILL, ABOVE)[1]
    assert late.fill_index == 2 and late.entry == 10_000


def test_the_order_is_gone_in_the_third_minute() -> None:
    assert play(TOUCH, TOUCH, FILL, ABOVE)[1] is None


def test_a_missing_minute_cannot_fill_the_order() -> None:
    assert play((0, 0, 0, 0), (0, 0, 0, 0))[1] is None


# --- the winning sell ---


def test_the_target_fills_only_when_the_price_trades_above_it() -> None:
    touched: Row = (10_020, 10_100, 9_950, 10_050)  # high exactly at 10 100
    free_from, trade = play(FILL, touched, ABOVE)
    assert (trade.kind, trade.exit_index, free_from) == ("target", 3, 3)
    assert trade.exit == 10_100  # the target itself: no slippage on a waiting sell


def test_a_win_is_never_counted_in_the_minute_the_buy_filled() -> None:
    spike: Row = (10_000, 10_500, 9_999, 10_020)  # fills and flies over the target
    _, trade = play(spike, QUIET, ABOVE)
    assert trade.exit_index == 3  # not minute 1


def test_the_profit_of_a_win_is_exact() -> None:
    _, trade = play(FILL, ABOVE)
    # +1%, minus a fee on the 10 000 bought and on the 10 100 sold.
    assert trade.profit(FEE_WITH_BNB) == F(1, 100) - FEE_WITH_BNB * F(201, 100)
    assert trade.profit(FEE_WITH_BNB) == F(84925, 10_000_000)  # 0.84925%
    assert trade.profit(FEE_STANDARD) == F(799, 100_000)  # 0.799%


def test_half_way_back_is_half_the_distance() -> None:
    over_half: Row = (10_020, 10_051, 9_950, 10_050)
    _, trade = play(FILL, over_half, params=HALF)
    assert trade.kind == "target" and trade.exit == 10_050


# --- the losing sell ---


def test_the_stop_is_an_immediate_sale_a_little_worse_than_its_price() -> None:
    _, trade = play(FILL, (10_020, 10_050, 9_900, 9_950))  # the low touches 9 900
    assert trade.kind == "stop" and trade.exit == 9_900 * (1 - SLIPPAGE)
    loss = trade.profit(FEE_WITH_BNB)
    sold = F(9_900) * (1 - SLIPPAGE) * (1 - FEE_WITH_BNB)
    assert loss == sold / 10_000 - (1 + FEE_WITH_BNB)
    assert F(-12, 1000) < loss < F(-11, 1000)  # about -1.2%


def test_one_unit_above_the_stop_is_not_a_stop() -> None:
    _, trade = play(FILL, (10_020, 10_050, 9_901, 9_950), ABOVE)
    assert trade.kind == "target"


def test_a_minute_reaching_both_stop_and_target_counts_as_the_stop() -> None:
    _, trade = play(FILL, (10_020, 10_300, 9_900, 10_200))
    assert trade.kind == "stop"


def test_the_stop_counts_in_the_minute_the_buy_filled() -> None:
    crash: Row = (10_000, 10_010, 9_800, 9_850)
    free_from, trade = play(crash)
    assert (trade.kind, trade.fill_index, trade.exit_index) == ("stop", 1, 1)
    assert free_from == 1 and trade.exit == 9_900 * (1 - SLIPPAGE)


def test_a_minute_that_opens_under_the_stop_sells_at_the_open() -> None:
    gap: Row = (9_700, 9_750, 9_650, 9_720)
    _, trade = play(FILL, gap)
    assert trade.kind == "stop" and trade.exit == 9_700 * (1 - SLIPPAGE)


def test_a_wider_stop_is_twice_as_far() -> None:
    wide = Params(k=4, target_share=F(1), stop_multiple=2)
    survives: Row = (10_020, 10_050, 9_801, 9_950)
    assert play(FILL, survives, ABOVE, params=wide)[1].kind == "target"
    _, trade = play(FILL, (10_020, 10_050, 9_800, 9_950), params=wide)
    assert trade.kind == "stop" and trade.exit == 9_800 * (1 - SLIPPAGE)


def test_a_fill_minute_that_opens_under_the_stop_sells_at_its_open() -> None:
    gap: Row = (9_700, 9_750, 9_650, 9_720)  # the crash is already there
    free_from, trade = play(gap)
    assert (trade.kind, trade.fill_index, trade.exit_index) == ("stop", 1, 1)
    assert trade.entry == 10_000 and trade.exit == 9_700 * (1 - SLIPPAGE)
    _, late = play((0, 0, 0, 0), gap)  # the same after a missing minute
    assert late.fill_index == 2 and late.exit == 9_700 * (1 - SLIPPAGE)


def test_a_missing_minute_inside_a_trade_is_skipped() -> None:
    gone: Row = (0, 0, 0, 0)
    _, trade = play(FILL, gone, ABOVE)
    assert (trade.kind, trade.exit_index) == ("target", 3)
    # The time limit lands on a missing minute: sold at the next real close.
    _, late = play(FILL, *[QUIET] * 119, gone, QUIET)
    assert (late.kind, late.exit_index) == ("time", 122)


# --- the time limit ---


def test_after_120_minutes_it_sells_at_that_minutes_close() -> None:
    last: Row = (10_020, 10_060, 9_950, 10_040)
    free_from, trade = play(FILL, *[QUIET] * 119, last, QUIET)
    assert (trade.kind, trade.exit_index, free_from) == ("time", 121, 121)
    assert trade.exit == 10_040 * (1 - SLIPPAGE)


def test_a_trade_still_open_when_the_data_ends_is_not_counted() -> None:
    free_from, trade = play(FILL, QUIET, QUIET)
    assert trade is None and free_from == 4


# --- the whole strategy over several pairs ---

DIP: Row = (10_000, 10_000, 9_900, 9_900)  # close 9 900: 59/5999 = 0.98% under
ENTRY_FILL: Row = (9_900, 9_950, 9_899, 9_920)
STOP_OUT: Row = (9_920, 9_930, 9_700, 9_710)
WIN: Row = (9_920, 10_100, 9_910, 10_050)
CALM: Row = (9_920, 9_950, 9_850, 9_920)
ONE_TRADE = {59: DIP, 60: ENTRY_FILL, 61: CALM, 62: WIN}


def pair(symbol: str, events: dict[int, Row], length: int) -> Candles:
    """Flat at 10 000 except for the minutes given."""
    return candles([events.get(minute, FLAT) for minute in range(length)], symbol)


def placed(run: object) -> list[tuple[str, int]]:
    return [(order.symbol, order.signal_index) for order in run.orders]


def test_one_dip_one_order_one_trade() -> None:
    run = simulate([pair("BTCUSDT", ONE_TRADE, 70)], FULL)
    (order,), (trade,) = run.orders, run.trades
    assert (order.signal_index, order.price) == (59, 9_900)
    assert order.distance == F(59, 5999)
    assert (trade.fill_index, trade.exit_index, trade.kind) == (60, 62, "target")
    assert trade.exit == 9_900 * (1 + F(59, 5999))
    summary = summarise(run)
    assert (summary.trades, summary.orders, summary.wins) == (1, 1, 1)
    assert summary.by_kind == {"target": 1} and summary.win_rate == 1
    assert summary.average_with_bnb > summary.average_standard > 0


def test_an_empty_run_has_an_empty_summary() -> None:
    summary = summarise(simulate([pair("BTCUSDT", {}, 70)], FULL))
    assert (summary.trades, summary.win_rate, summary.average_with_bnb) == (0, 0, 0)


def test_a_target_too_close_to_the_fees_is_skipped() -> None:
    # 9 915 is 0.84% under the average: the full target clears the 0.45%
    # floor, half of it (0.42%) does not.
    edge: Row = (10_000, 10_000, 9_915, 9_915)
    shallow = pair("BTCUSDT", {59: edge}, 70)
    assert placed(simulate([shallow], FULL)) == [("BTCUSDT", 59)]
    assert placed(simulate([shallow], HALF)) == []
    deep = pair("BTCUSDT", {59: DIP}, 70)  # 0.98%: half is 0.49%
    assert placed(simulate([deep], HALF)) == [("BTCUSDT", 59)]


def test_a_dip_smaller_than_k_deviations_is_ignored() -> None:
    # An hour swinging between 9 900 and 10 100, then a close at 9 850:
    # 1.5 deviations under the average, so not a dip for K = 2.
    events: dict[int, Row] = {
        minute: (10_000, 10_100, 9_900, 10_100 if minute % 2 else 9_900)
        for minute in range(59)
    }
    events[59] = (10_000, 10_000, 9_850, 9_850)
    assert placed(simulate([pair("BTCUSDT", events, 70)], Params(2, F(1), 1))) == []
    events[59] = (10_000, 10_000, 9_700, 9_700)  # about 3 deviations
    assert placed(simulate([pair("BTCUSDT", events, 70)], Params(2, F(1), 1))) == [
        ("BTCUSDT", 59)
    ]
    assert placed(simulate([pair("BTCUSDT", events, 70)], Params(4, F(1), 1))) == []


def test_one_trade_per_pair_at_a_time() -> None:
    second_dip: Row = (9_920, 9_920, 9_800, 9_800)
    events = {59: DIP, 60: ENTRY_FILL, 61: CALM, 62: second_dip, 63: CALM, 64: WIN}
    run = simulate([pair("BTCUSDT", events, 70)], Params(2, F(1), 2))
    assert placed(run) == [("BTCUSDT", 59)]


def test_after_a_loss_every_pair_pauses_for_30_minutes() -> None:
    btc = pair("BTCUSDT", {59: DIP, 60: ENTRY_FILL, 61: STOP_OUT}, 140)
    # The loss ends at minute 61. ETH dips at 90 (paused) and at 125 (allowed).
    eth = pair("ETHUSDT", {90: DIP, 125: DIP, 126: ENTRY_FILL}, 140)
    assert placed(simulate([btc, eth], FULL)) == [("BTCUSDT", 59), ("ETHUSDT", 125)]
    at_the_edge = pair("ETHUSDT", {91: DIP}, 140)  # exactly 30 minutes later
    assert ("ETHUSDT", 91) in placed(simulate([btc, at_the_edge], FULL))


def test_a_loss_pauses_nothing_before_it_has_happened() -> None:
    # BTC buys at minute 60 and only loses at minute 80. ETH dips at 70,
    # while that trade is still open: nobody knows about the loss yet.
    slow = {59: DIP, 60: ENTRY_FILL, **dict.fromkeys(range(61, 80), CALM), 80: STOP_OUT}
    btc = pair("BTCUSDT", slow, 140)
    eth = pair("ETHUSDT", {70: DIP, 85: DIP, 111: DIP}, 140)
    assert placed(simulate([btc, eth], Params(2, F(1), 1))) == [
        ("BTCUSDT", 59),
        ("ETHUSDT", 70),  # before the loss: allowed
        ("ETHUSDT", 111),  # 85 was inside the pause (80 to 109)
    ]


def test_a_win_pauses_nothing() -> None:
    btc = pair("BTCUSDT", ONE_TRADE, 100)
    eth = pair("ETHUSDT", {70: DIP, 71: ENTRY_FILL, 72: WIN}, 100)
    assert len(simulate([btc, eth], FULL).trades) == 2


def test_when_the_whole_market_dips_it_is_one_bet() -> None:
    three = [pair(s, ONE_TRADE, 70) for s in ("BTCUSDT", "ETHUSDT", "BNBUSDT")]
    assert placed(simulate(three, FULL)) == [("BTCUSDT", 59)]


def test_a_whole_market_dip_is_blocked_by_an_older_open_trade() -> None:
    held = {59: DIP, 60: ENTRY_FILL, **dict.fromkeys(range(61, 100), CALM)}
    btc = pair("BTCUSDT", held, 110)  # in a trade from minute 60 on
    later = {64: DIP}
    eth, bnb = pair("ETHUSDT", later, 110), pair("BNBUSDT", later, 110)
    # At minute 64 BTC is still far under its average: all three are dipping.
    assert placed(simulate([btc, eth, bnb], FULL)) == [("BTCUSDT", 59)]
    # With BNB calm it is not a whole-market dip, so ETH may trade.
    calm = pair("BNBUSDT", {}, 110)
    assert placed(simulate([btc, eth, calm], FULL)) == [
        ("BTCUSDT", 59),
        ("ETHUSDT", 64),
    ]


def test_two_pairs_dipping_while_the_third_is_calm_are_two_bets() -> None:
    series = [
        pair("BTCUSDT", ONE_TRADE, 70),
        pair("ETHUSDT", ONE_TRADE, 70),
        pair("BNBUSDT", {}, 70),
    ]
    assert placed(simulate(series, FULL)) == [("BTCUSDT", 59), ("ETHUSDT", 59)]


def test_only_dips_inside_the_asked_period_open_orders() -> None:
    events = {**ONE_TRADE, 130: DIP, 131: ENTRY_FILL, 132: WIN}
    btc = pair("BTCUSDT", events, 140)
    assert [i for _, i in placed(simulate([btc], FULL))] == [59, 130]
    assert [i for _, i in placed(simulate([btc], FULL, 0, 130))] == [59]
    assert [i for _, i in placed(simulate([btc], FULL, 100))] == [130]
    assert [i for _, i in placed(simulate([btc.head(120)], FULL))] == [59]


def test_pairs_on_different_timelines_are_refused() -> None:
    late = pair("ETHUSDT", {}, 70)
    late.first_minute = 5
    with pytest.raises(ValueError, match="same minute"):
        simulate([pair("BTCUSDT", {}, 70), late], FULL)


def test_the_twelve_combinations_are_the_ones_fixed_in_advance() -> None:
    assert len(ALL_PARAMS) == 12 == len(set(ALL_PARAMS))
    assert {p.k for p in ALL_PARAMS} == {2, 3, 4}
    assert {p.target_share for p in ALL_PARAMS} == {F(1, 2), F(1)}
    assert {p.stop_multiple for p in ALL_PARAMS} == {1, 2}
    assert FULL.label == "K=4 target=full stop=1x"
    assert HALF.label == "K=4 target=half stop=1x"


# --- the procedure and the pass mark ---


def summary(trades: int, with_bnb: F, standard: F = F(0)) -> Summary:
    return Summary(trades, trades, 0, with_bnb, standard, {})


def test_the_tuning_winner_needs_200_trades_and_a_positive_average() -> None:
    a, b, c, d = ALL_PARAMS[:4]
    results = [
        (a, summary(199, F(9, 1000))),  # the best, but one trade short
        (b, summary(200, F(2, 1000))),
        (c, summary(5000, F(3, 1000))),
        (d, summary(900, F(3, 1000))),  # a tie: the earlier one wins
    ]
    assert choose(results) == c
    assert choose(results[:2]) == b
    assert choose(results[:1]) is None
    assert choose([(a, summary(900, F(0))), (b, summary(900, F(-1, 1000)))]) is None
    assert choose([]) is None


def test_the_pass_mark_at_its_exact_edges() -> None:
    edge = F(5, 10_000)
    assert all(pass_mark(summary(100, edge, F(0))).values())
    assert list(pass_mark(summary(99, edge, F(0))).values()) == [False, True, True]
    just_under = edge - F(1, 10**40)
    assert list(pass_mark(summary(100, just_under)).values()) == [True, False, True]
    negative = F(-1, 10**40)
    assert list(pass_mark(summary(100, edge, negative)).values()) == [
        True,
        True,
        False,
    ]


# --- no peeking at the future ---


def random_pair(symbol: str, seed: int, length: int) -> Candles:
    rng = random.Random(seed)
    rows, price = [], 10**12
    for _ in range(length):
        opened = price
        # Mostly small steps, and now and then a sudden 8% drop (a deep dip).
        small = opened * rng.randint(-40, 40) // 10_000
        step = -(opened * 8 // 100) if rng.random() < 0.01 else small
        close = max(1000, opened + step)
        high = max(opened, close) + opened * rng.randint(0, 15) // 10_000
        low = min(opened, close) - opened * rng.randint(0, 15) // 10_000
        rows.append((opened, high, low, close))
        price = close
    return candles(rows, symbol)


@pytest.mark.parametrize("params", [ALL_PARAMS[0], ALL_PARAMS[5], ALL_PARAMS[11]])
def test_changing_the_future_changes_no_past_decision(params: Params) -> None:
    length, cut = 6_000, 3_500
    original = [random_pair(s, seed, length) for seed, s in enumerate("ABC")]
    changed = []
    for index, series in enumerate(original):
        other = random_pair(series.symbol, 100 + index, length)
        rows = [
            (series.open[i], series.high[i], series.low[i], series.close[i])
            if i <= cut
            else (other.open[i], other.high[i], other.low[i], other.close[i])
            for i in range(length)
        ]
        changed.append(candles(rows, series.symbol))
    first, second = simulate(original, params), simulate(changed, params)
    orders = [o for o in first.orders if o.signal_index <= cut]
    assert orders == [o for o in second.orders if o.signal_index <= cut]
    trades = [t for t in first.trades if t.exit_index <= cut]
    assert trades == [t for t in second.trades if t.exit_index <= cut]
    assert orders and trades  # the test really exercised something
    # Cutting the data off gives the same finished trades too.
    cut_off = simulate([series.head(cut + 1) for series in original], params)
    assert cut_off.trades == trades
