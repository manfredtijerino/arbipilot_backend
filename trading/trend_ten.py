"""The trend rule on ten coins: one shared pot, at most three trades open.

The rule, the coins, the costs and the pass mark were fixed in
`docs/build-roadmap.md` (stage 7c) before any price of the seven new coins
was downloaded. This file only carries them out. It is a replay of past
prices; nothing here is used by the live bot.

- The rule of stage 7b: buy after a close above the highest close of the 20
  days before, sell after a close below the lowest close of the 20 days
  before. A signal at the close of day D is an order at the OPEN of day D+1.
- Each trade is 24 USDT, one per coin, at most 3 open at once.
- A morning's sales happen first and free their places. Then the buy signals
  are served largest coin first; one that finds no place is dropped, and the
  coin needs a new signal on a later day.
- Every order fills worse by 0.05% plus half the coin's measured spread, and
  pays the fee.
- A coin removed from Binance is sold at the close of its last candle.
- Buy-and-hold, the thing to beat, pays the same costs on the same coins.

Prices are whole numbers of price units and money is a `Fraction` of USDT,
so nothing is rounded until a result is printed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from exchange.history import Candles
from trading.trend import (
    MIN_TRADES,
    SHARE_OF_HOLD_DROP,
    SHARE_OF_HOLD_PROFIT,
    SLIPPAGE,
    STAKE,
    Params,
    is_new_high,
    is_new_low,
    worst_drop,
)

RULE = Params(buy_days=20, sell_days=20)  # the one chosen in stage 7b
MAX_OPEN = 3  # trades open at once, as `max_open_positions` today
MONEY = Fraction(72)  # what the bot and buy-and-hold each start with

# Why a trade ended.
BY_SIGNAL = "signal"
AT_PERIOD_END = "period end"
COIN_REMOVED = "coin removed"


@dataclass(frozen=True)
class Costs:
    """What every order pays: the fee, and a worse fill."""

    fee: Fraction
    spreads: Mapping[str, Fraction]  # each coin's whole spread, as a share

    def worse(self, symbol: str) -> Fraction:
        """How much worse than its price an order fills: 0.05% plus half the
        coin's spread (a buyer pays the upper half, a seller loses the lower)."""
        return SLIPPAGE + self.spreads[symbol] / 2


@dataclass(frozen=True)
class Trade:
    """Some USDT of one coin bought on one day and sold on a later (or the
    same) day."""

    symbol: str
    buy_day: int  # the day whose open was the buy
    sell_day: int  # the day of the sale
    buy_price: int  # in price units
    sell_price: int  # an open after a sell signal, or a closing price
    stake: Fraction  # USDT paid
    ended: str = BY_SIGNAL

    def coins(self, costs: Costs) -> Fraction:
        """What the stake bought, at the worse price and minus the fee.

        In "coins per price unit": times a price in units, it is USDT.
        """
        paid = self.buy_price * (1 + costs.worse(self.symbol))
        return self.stake / paid * (1 - costs.fee)

    def profit(self, costs: Costs) -> Fraction:
        """USDT won or lost on the stake, after both orders' costs."""
        got = self.sell_price * (1 - costs.worse(self.symbol))
        return self.coins(costs) * got * (1 - costs.fee) - self.stake


def last_candle(candles: Candles, end: int) -> int:
    """The last day before `end` that has a candle, or -1 when there is none.

    A coin whose last candle is before the period's last day was removed
    from Binance during the period.
    """
    for day in range(min(end, len(candles)) - 1, -1, -1):
        if candles.close[day] > 0:
            return day
    return -1


@dataclass(frozen=True)
class Replay:
    trades: tuple[Trade, ...]
    dropped: int  # buy signals that found no free place (or no candle)


def replay(
    series: Sequence[Candles],
    start: int,
    end: int,
    rule: Params = RULE,
    max_open: int = MAX_OPEN,
    stake: Fraction = STAKE,
) -> Replay:
    """The bot's trades over days `start` up to `end` (not included).

    `series` is in rank order, largest coin first. Signals are read at the
    close of days inside the period; the order is at the next day's open.
    """
    last = {candles.symbol: last_candle(candles, end) for candles in series}
    held: dict[str, tuple[int, int]] = {}  # symbol -> (day, price) of the buy
    to_sell: set[str] = set()  # sell signals waiting for their open
    to_buy: set[str] = set()  # buy signals of the day before
    trades: list[Trade] = []
    dropped = 0

    def sell(symbol: str, day: int, price: int, ended: str) -> None:
        buy_day, buy_price = held.pop(symbol)
        to_sell.discard(symbol)
        trades.append(Trade(symbol, buy_day, day, buy_price, price, stake, ended))

    for day in range(start, end):
        # The morning. Sales first: they free their places.
        for candles in series:
            # A sale on a day without a candle waits for the next candle.
            if candles.symbol in to_sell and candles.open[day] > 0:
                sell(candles.symbol, day, candles.open[day], BY_SIGNAL)
        # Then the buy signals, largest coin first.
        for candles in series:
            if candles.symbol not in to_buy:
                continue
            if len(held) < max_open and candles.open[day] > 0:
                held[candles.symbol] = (day, candles.open[day])
            else:
                dropped += 1  # it needs a new signal on a later day
        to_buy.clear()

        # The close of the day.
        for candles in series:
            symbol, closes = candles.symbol, candles.close
            if day == last[symbol]:
                # The coin's last candle: the period ended, or it was removed.
                if symbol in held:
                    ended = AT_PERIOD_END if day == end - 1 else COIN_REMOVED
                    sell(symbol, day, closes[day], ended)
            elif day > last[symbol] or day == end - 1:
                continue  # no candle any more, or no next day for an order
            elif symbol in held:
                if is_new_low(closes, day, rule.sell_days):
                    to_sell.add(symbol)
            elif is_new_high(closes, day, rule.buy_days):
                to_buy.add(symbol)
    return Replay(tuple(trades), dropped)


def hold_trades(
    series: Sequence[Candles], start: int, end: int, money: Fraction = MONEY
) -> list[Trade]:
    """Buy-and-hold: the money split equally over the coins, each bought at
    the first day's open and sold at the last close (a removed coin at the
    close of its last candle)."""
    stake = money / len(series)
    trades = []
    for candles in series:
        if candles.open[start] <= 0:
            raise ValueError(f"{candles.symbol}: no candle on the first day")
        day = last_candle(candles, end)
        ended = AT_PERIOD_END if day == end - 1 else COIN_REMOVED
        trades.append(
            Trade(
                candles.symbol,
                start,
                day,
                candles.open[start],
                candles.close[day],
                stake,
                ended,
            )
        )
    return trades


@dataclass(frozen=True)
class Outcome:
    """What one way of using the money did over the period, at given costs."""

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


def seen_closes(candles: Candles, end: int) -> list[int]:
    """Each day's close; on a day without a candle, the last close seen."""
    seen, out = 0, []
    for day in range(end):
        if day < len(candles) and candles.close[day] > 0:
            seen = candles.close[day]
        out.append(seen)
    return out


def outcome(
    series: Sequence[Candles],
    trades: Sequence[Trade],
    start: int,
    end: int,
    costs: Costs,
    money: Fraction = MONEY,
) -> Outcome:
    """Count the money every day at the close.

    A finished trade adds its profit from its sale day on; an open one adds
    what its coins are worth at that close, minus the USDT paid.
    """
    closes = {candles.symbol: seen_closes(candles, end) for candles in series}
    profits = tuple(trade.profit(costs) for trade in trades)
    curve = [money] * (end - start)
    for trade, profit in zip(trades, profits, strict=True):
        coins, prices = trade.coins(costs), closes[trade.symbol]
        for day in range(trade.buy_day, trade.sell_day):
            curve[day - start] += coins * prices[day] - trade.stake
        for day in range(trade.sell_day, end):
            curve[day - start] += profit
    return Outcome(tuple(trades), profits, tuple(curve))


def beats_hold(bot: Outcome, held: Outcome) -> bool:
    """Condition (c), in the wording of stage 7b: at least buy-and-hold's
    profit; or at least half of it with at most half of its worst drop."""
    if bot.profit >= held.profit:
        return True
    return (
        bot.profit >= SHARE_OF_HOLD_PROFIT * held.profit
        and bot.worst_drop <= SHARE_OF_HOLD_DROP * held.worst_drop
    )


def pass_mark(
    bot_ten: Outcome, hold_ten: Outcome, bot_seven: Outcome, hold_seven: Outcome
) -> dict[str, bool]:
    """The five conditions, at the 0.1% fee. All must be true."""
    enough = min(len(bot_ten.trades), len(bot_seven.trades)) >= MIN_TRADES
    return {
        f"(a) at least {MIN_TRADES} trades in both runs": enough,
        "(b) ten coins: profit above zero": bot_ten.profit > 0,
        "(c) ten coins: at least hold's profit, or half of it with half the drop": (
            beats_hold(bot_ten, hold_ten)
        ),
        "(d) ten coins: profit above zero without the best trade": (
            bot_ten.profit_without_best > 0
        ),
        "(e) seven new coins alone: the same as (c)": (
            beats_hold(bot_seven, hold_seven)
        ),
    }
