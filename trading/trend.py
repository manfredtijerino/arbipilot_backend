"""The trend test: "buy a new high, sell a new low" replayed over daily candles.

The rules, the four combinations, the periods and the pass mark were fixed in
`docs/build-roadmap.md` (stage 7b) before any result existed. This file only
carries them out.

- A buy signal: a day's close is ABOVE the highest close of the N days before.
- A sell signal: a day's close is BELOW the lowest close of the M days before.
- A signal at the close of day D is an immediate order at the OPEN of day D+1.
- Every order fills 0.05% worse than its price and pays a fee.
- Each trade is 24 USDT. A trade open on the last day is sold at that close.
- Buy-and-hold, the thing to beat, pays the same costs on the same dates.

Prices are whole numbers of price units and money is a `Fraction` of USDT,
so nothing is rounded until a result is printed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from exchange.history import Candles

STAKE = Fraction(24)  # USDT per trade: 8% of 300
SLIPPAGE = Fraction(5, 10000)  # every order fills 0.05% worse
FEE_STANDARD = Fraction(1, 1000)  # 0.1% per order: the fee that decides
FEE_WITH_BNB = Fraction(75, 100000)  # 0.075%: reported only

# The procedure and the pass mark.
MIN_TRADES = 20
SHARE_OF_HOLD_PROFIT = Fraction(1, 2)
SHARE_OF_HOLD_DROP = Fraction(1, 2)


@dataclass(frozen=True)
class Params:
    buy_days: int  # N: a close above the highest close of this many days
    sell_days: int  # M: a close below the lowest close of this many days

    @property
    def label(self) -> str:
        return f"buy>{self.buy_days}d high, sell<{self.sell_days}d low"


# The four combinations fixed before the test was run, in their listed order.
ALL_PARAMS = (Params(20, 10), Params(20, 20), Params(55, 10), Params(55, 20))


def _earlier(closes: Sequence[int], day: int, count: int) -> Sequence[int] | None:
    """The `count` closes before `day`, or None when any close is missing."""
    if day - count < 0 or closes[day] <= 0:
        return None
    window = closes[day - count : day]
    return window if min(window) > 0 else None


def is_new_high(closes: Sequence[int], day: int, count: int) -> bool:
    """Is this day's close above the highest close of the `count` days before?"""
    window = _earlier(closes, day, count)
    return window is not None and closes[day] > max(window)


def is_new_low(closes: Sequence[int], day: int, count: int) -> bool:
    """Is this day's close below the lowest close of the `count` days before?"""
    window = _earlier(closes, day, count)
    return window is not None and closes[day] < min(window)


def require_every_day(series: Sequence[Candles], first: int, end: int) -> None:
    """Refuse to go on when a pair has no candle on a day that is used.

    A missing day would count a holding as worth nothing that day and would
    silently switch signals off, so the test only runs on complete data.
    """
    for candles in series:
        if len(candles) < end or min(candles.close[first:end], default=0) <= 0:
            raise ValueError(f"{candles.symbol}: a day is missing from the data")


@dataclass(frozen=True)
class Trade:
    """24 USDT bought on one day and sold on a later (or the same) day."""

    symbol: str
    buy_day: int  # the day whose open was the buy
    sell_day: int  # the day of the sale
    buy_price: int  # in price units
    sell_price: int  # the open after the sell signal, or the last day's close
    at_period_end: bool = False  # sold only because the period ended

    def coins(self, fee: Fraction) -> Fraction:
        """What 24 USDT bought, 0.05% worse and minus the fee.

        In "coins per price unit": times a price in units, it is USDT.
        """
        return STAKE / (self.buy_price * (1 + SLIPPAGE)) * (1 - fee)

    def profit(self, fee: Fraction) -> Fraction:
        """USDT won or lost on the 24 USDT, after both orders' costs."""
        sold = self.coins(fee) * self.sell_price * (1 - SLIPPAGE) * (1 - fee)
        return sold - STAKE


def trades_of(candles: Candles, params: Params, start: int, end: int) -> list[Trade]:
    """One pair's trades in the period of days `start` up to `end` (not included).

    Signals are read at the close of days inside the period, and the order
    is at the next day's open, which must be inside the period too.
    """
    closes, opens, symbol = candles.close, candles.open, candles.symbol
    trades: list[Trade] = []
    bought: tuple[int, int] | None = None  # (day, price) of the open trade
    for day in range(start, end - 1):
        if bought is None:
            signal = is_new_high(closes, day, params.buy_days)
        else:
            signal = is_new_low(closes, day, params.sell_days)
        if not signal:
            continue
        price = opens[day + 1]
        if price <= 0:
            raise ValueError(f"{symbol}: no candle on the day of an order")
        if bought is None:
            bought = (day + 1, price)
        else:
            trades.append(Trade(symbol, bought[0], day + 1, bought[1], price))
            bought = None
    if bought is not None:
        trades.append(_sold_at_the_end(candles, bought[0], bought[1], end))
    return trades


def _sold_at_the_end(candles: Candles, buy_day: int, price: int, end: int) -> Trade:
    last = end - 1
    if candles.close[last] <= 0:
        raise ValueError(f"{candles.symbol}: no candle on the last day")
    return Trade(candles.symbol, buy_day, last, price, candles.close[last], True)


def hold_trades(series: Sequence[Candles], start: int, end: int) -> list[Trade]:
    """Buy-and-hold: each pair bought at the first open, sold at the last close."""
    trades = []
    for candles in series:
        if candles.open[start] <= 0:
            raise ValueError(f"{candles.symbol}: no candle on the first day")
        trades.append(_sold_at_the_end(candles, start, candles.open[start], end))
    return trades


@dataclass(frozen=True)
class Outcome:
    """What one way of using the money did over a period, at one fee."""

    trades: tuple[Trade, ...]
    profits: tuple[Fraction, ...]  # USDT, one per trade
    curve: tuple[Fraction, ...]  # the money at each day's close

    @property
    def profit(self) -> Fraction:
        return sum(self.profits, Fraction(0))

    @property
    def profit_without_best(self) -> Fraction:
        return self.profit - max(self.profits, default=Fraction(0))

    @property
    def worst_drop(self) -> Fraction:
        return worst_drop(self.curve)


def worst_drop(curve: Sequence[Fraction]) -> Fraction:
    """The largest fall from an earlier high, as a share of that high."""
    peak = worst = Fraction(0)
    for money in curve:
        if money > peak:
            peak = money
        elif peak > 0:
            worst = max(worst, (peak - money) / peak)
    return worst


def outcome(
    series: Sequence[Candles],
    trades: Sequence[Trade],
    start: int,
    end: int,
    fee: Fraction,
) -> Outcome:
    """Count the money every day at the close.

    It starts as 24 USDT per pair. A finished trade adds its profit from its
    sale day on; an open one adds what its coins are worth at that close,
    minus the 24 USDT paid.
    """
    closes = {candles.symbol: candles.close for candles in series}
    profits = tuple(trade.profit(fee) for trade in trades)
    money = [STAKE * len(series)] * (end - start)
    for trade, profit in zip(trades, profits, strict=True):
        coins, prices = trade.coins(fee), closes[trade.symbol]
        for day in range(trade.buy_day, trade.sell_day):
            if prices[day] <= 0:
                raise ValueError(f"{trade.symbol}: a day inside a trade is missing")
            money[day - start] += coins * prices[day] - STAKE
        for day in range(trade.sell_day, end):
            money[day - start] += profit
    return Outcome(tuple(trades), profits, tuple(money))


def run(
    series: Sequence[Candles], params: Params, start: int, end: int, fee: Fraction
) -> Outcome:
    """The bot's outcome for one combination over one period."""
    trades = [t for candles in series for t in trades_of(candles, params, start, end)]
    return outcome(series, trades, start, end, fee)


def hold(series: Sequence[Candles], start: int, end: int, fee: Fraction) -> Outcome:
    """Buy-and-hold's outcome over the same period, with the same costs."""
    return outcome(series, hold_trades(series, start, end), start, end, fee)


def choose(results: Sequence[tuple[Params, Outcome]]) -> Params | None:
    """The winner of the choosing period: the highest profit among those with
    at least 20 trades and a profit above zero. On a tie, the one listed
    first. None means the idea failed."""
    best: tuple[Params, Outcome] | None = None
    for params, result in results:
        if len(result.trades) < MIN_TRADES or result.profit <= 0:
            continue
        if best is None or result.profit > best[1].profit:
            best = (params, result)
    return best[0] if best else None


def pass_mark(bot: Outcome, held: Outcome) -> dict[str, bool]:
    """The four conditions on the hidden period. All must be true."""
    beats_hold = bot.profit >= held.profit
    half_with_half_the_drop = (
        bot.profit >= SHARE_OF_HOLD_PROFIT * held.profit
        and bot.worst_drop <= SHARE_OF_HOLD_DROP * held.worst_drop
    )
    return {
        f"(a) at least {MIN_TRADES} trades": len(bot.trades) >= MIN_TRADES,
        "(b) profit above zero": bot.profit > 0,
        "(c) at least hold's profit, or half of it with half the drop": (
            beats_hold or half_with_half_the_drop
        ),
        "(d) profit above zero without the best trade": bot.profit_without_best > 0,
    }
