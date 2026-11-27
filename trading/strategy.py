"""The dip rule: when is a price "a dip", and how deep is it.

One piece of arithmetic, used by the backtest and (if the strategy passes)
by the live bot, so both decide the same way.

A minute's close is a dip of size K when it is at least K standard deviations
below the average of the last 60 closes, that minute included. The standard
deviation is that of the same 60 closes.

Everything is done in whole numbers (price units), so the answer is exact:
with S the sum of the 60 closes and Q the sum of their squares,

    average - close        = (S - 60*close) / 60
    standard deviation^2   = (60*Q - S*S) / 3600

so "average - close >= K * standard deviation" is the same as

    S - 60*close > 0   and   (S - 60*close)^2 >= K^2 * (60*Q - S*S)

with no division and no square root.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction

WINDOW = 60  # closes in the average: the last hour


@dataclass(frozen=True)
class Dip:
    """One minute whose close is under the hour's average."""

    index: int  # which minute
    close: int  # in price units
    below: int  # S - 60*close: how far under the average, times 60
    spread: int  # 60*Q - S*S: the variance, times 3600
    total: int  # S: the sum of the 60 closes

    def at_least(self, k: int) -> bool:
        """Is the close at least `k` standard deviations under the average?"""
        return self.below * self.below >= k * k * self.spread

    @property
    def distance(self) -> Fraction:
        """(average - close) / average, exactly."""
        return Fraction(self.below, self.total)


def find_dips(closes: Sequence[int], smallest_k: int) -> Iterator[Dip]:
    """Every minute at least `smallest_k` standard deviations under its average.

    A close of 0 means "no candle that minute"; a dip is only reported when
    all 60 minutes of its window exist. Each answer depends only on the
    closes up to and including its own minute.
    """
    total = squares = run = 0
    for index, close in enumerate(closes):
        if close <= 0:
            total = squares = run = 0  # the window must be unbroken
            continue
        total += close
        squares += close * close
        run += 1
        if run > WINDOW:
            old = closes[index - WINDOW]
            total -= old
            squares -= old * old
            run = WINDOW
        if run < WINDOW:
            continue
        below = total - WINDOW * close
        if below <= 0:
            continue
        spread = WINDOW * squares - total * total
        if below * below >= smallest_k * smallest_k * spread:
            yield Dip(index, close, below, spread, total)
