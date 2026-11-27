"""The backtest: the dip strategy replayed over past one-minute candles.

The rules, the 12 combinations, the data split and the pass mark were fixed
in `docs/build-roadmap.md` (stage 7a) before any result existed. This file
only carries them out. Where a one-minute candle cannot say what happened,
the answer that is worse for the strategy is assumed:

- a waiting buy fills only when a minute's low is BELOW its price;
- a waiting sell fills only when a minute's high is ABOVE its price, and
  never in the minute the buy filled;
- a minute that reaches both the stop and the target counts as the stop;
- every immediate sell fills 0.05% worse than its price.

Prices are whole numbers of price units and every ratio is a `Fraction`, so
nothing is rounded until a result is printed.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from exchange.history import Candles
from trading.strategy import Dip, find_dips

ORDER_LIFE_MINUTES = 2  # a waiting buy that has not filled is cancelled
TIME_LIMIT_MINUTES = 120  # sell whatever happened
PAUSE_AFTER_LOSS_MINUTES = 30  # on every pair
TOGETHER_K = 2  # "the other pairs are dipping too"
TARGET_FLOOR = Fraction(45, 10000)  # 0.45%: three times the round-trip fee
SLIPPAGE = Fraction(5, 10000)  # 0.05% worse on every immediate sell
FEE_WITH_BNB = Fraction(75, 100000)  # 0.075% per side
FEE_STANDARD = Fraction(1, 1000)  # 0.1% per side

# The procedure and the pass mark, also fixed before the backtest was run.
TUNING_MIN_TRADES = 200
HIDDEN_MIN_TRADES = 100
HIDDEN_MIN_AVERAGE = Fraction(5, 10000)  # +0.05% per trade at the 0.075% fee

# The 12 combinations fixed before the backtest was run.
K_VALUES = (2, 3, 4)
TARGET_SHARES = (Fraction(1, 2), Fraction(1))
STOP_MULTIPLES = (1, 2)


@dataclass(frozen=True)
class Params:
    k: int  # dip size, in standard deviations
    target_share: Fraction  # target as a share of the dip distance
    stop_multiple: int  # stop as a multiple of the dip distance

    @property
    def label(self) -> str:
        share = "half" if self.target_share == Fraction(1, 2) else "full"
        return f"K={self.k} target={share} stop={self.stop_multiple}x"


ALL_PARAMS = tuple(
    Params(k, share, stop)
    for k in K_VALUES
    for share in TARGET_SHARES
    for stop in STOP_MULTIPLES
)


@dataclass(frozen=True)
class Order:
    """A waiting buy that was placed (filled or not)."""

    symbol: str
    signal_index: int  # the minute whose close was the dip
    price: int
    distance: Fraction


@dataclass(frozen=True)
class Trade:
    symbol: str
    signal_index: int
    fill_index: int
    exit_index: int
    entry: int  # price units
    exit: Fraction  # price units, after slippage
    kind: str  # target, stop or time

    def profit(self, fee: Fraction) -> Fraction:
        """Profit as a share of the trade's size, after a fee on each side."""
        return (self.exit * (1 - fee) - self.entry * (1 + fee)) / self.entry


@dataclass
class Run:
    orders: list[Order] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)


@dataclass(frozen=True)
class Summary:
    trades: int
    orders: int
    wins: int
    average_with_bnb: Fraction  # average profit per trade at the 0.075% fee
    average_standard: Fraction  # at the 0.1% fee
    by_kind: dict[str, int]

    @property
    def win_rate(self) -> Fraction:
        return Fraction(self.wins, self.trades) if self.trades else Fraction(0)


def summarise(run: Run) -> Summary:
    trades = run.trades
    count = len(trades)
    kinds: dict[str, int] = {}
    for trade in trades:
        kinds[trade.kind] = kinds.get(trade.kind, 0) + 1

    def average(fee: Fraction) -> Fraction:
        if not count:
            return Fraction(0)
        return sum((t.profit(fee) for t in trades), Fraction(0)) / count

    return Summary(
        trades=count,
        orders=len(run.orders),
        wins=sum(1 for t in trades if t.profit(FEE_WITH_BNB) > 0),
        average_with_bnb=average(FEE_WITH_BNB),
        average_standard=average(FEE_STANDARD),
        by_kind=kinds,
    )


def choose(results: Sequence[tuple[Params, Summary]]) -> Params | None:
    """The tuning winner: the best average at the 0.075% fee among the
    combinations with enough trades and a positive average. None = failed.
    On an exact tie the earlier combination wins."""
    best: tuple[Params, Summary] | None = None
    for params, summary in results:
        if summary.trades < TUNING_MIN_TRADES or summary.average_with_bnb <= 0:
            continue
        if best is None or summary.average_with_bnb > best[1].average_with_bnb:
            best = (params, summary)
    return best[0] if best else None


def pass_mark(summary: Summary) -> dict[str, bool]:
    """The three conditions on the hidden period. All must be true."""
    return {
        f"at least {HIDDEN_MIN_TRADES} trades": summary.trades >= HIDDEN_MIN_TRADES,
        "average at 0.075% at least +0.05%": (
            summary.average_with_bnb >= HIDDEN_MIN_AVERAGE
        ),
        "average at 0.1% not negative": summary.average_standard >= 0,
    }


def _play_out(candles: Candles, dip: Dip, params: Params) -> tuple[int, Trade | None]:
    """Place the buy after `dip` and follow it to its end.

    Returns the minute from which the pair is free again, and the trade if
    the buy filled.
    """
    price, distance = dip.close, dip.distance
    last = len(candles) - 1
    fill = None
    for index in range(dip.index + 1, dip.index + 1 + ORDER_LIFE_MINUTES):
        if index > last:
            break
        low = candles.low[index]
        if low and low < price:  # traded through, not merely touched
            fill = index
            break
    if fill is None:
        return dip.index + ORDER_LIFE_MINUTES, None

    stop = price * (1 - params.stop_multiple * distance)
    target = price * (1 + params.target_share * distance)

    def sold(index: int, at: Fraction, kind: str) -> tuple[int, Trade]:
        if kind != "target":  # an immediate sale fills a little worse
            at = at * (1 - SLIPPAGE)
        return index, Trade(candles.symbol, dip.index, fill, index, price, at, kind)

    # The minute the buy filled: a win is never counted, a stop is.
    if candles.open[fill] <= stop:  # it opened under the stop: sold at the open
        return sold(fill, Fraction(candles.open[fill]), "stop")
    if candles.low[fill] <= stop:
        return sold(fill, stop, "stop")
    deadline = fill + TIME_LIMIT_MINUTES
    for index in range(fill + 1, last + 1):
        low = candles.low[index]
        if not low:
            continue  # no candle that minute
        opened = candles.open[index]
        if opened <= stop:  # it opened under the stop: sold at the open
            return sold(index, Fraction(opened), "stop")
        if low <= stop:  # the stop wins when both were reached
            return sold(index, stop, "stop")
        if candles.high[index] > target:
            return sold(index, target, "target")
        if index >= deadline:
            return sold(index, Fraction(candles.close[index]), "time")
    # The data ended with the trade still open: it is not counted.
    return last + 1, None


def simulate(
    series: Sequence[Candles],
    params: Params,
    first_signal: int = 0,
    last_signal: int | None = None,
) -> Run:
    """Run the strategy over the pairs together, in the order things happened.

    Only dips whose minute is from `first_signal` up to `last_signal`
    (not included) open orders. The pairs must share one timeline.
    """
    if len({candles.first_minute for candles in series}) != 1:
        raise ValueError("the pairs must start at the same minute")
    end = min(len(candles) for candles in series)
    last_signal = end if last_signal is None else min(last_signal, end)

    # Each pair's dips of at least 2 standard deviations, found once.
    dips_by_pair = [list(find_dips(candles.close, TOGETHER_K)) for candles in series]
    dipping = [{dip.index for dip in dips} for dips in dips_by_pair]
    events = sorted(
        (
            (dip.index, pair, dip)
            for pair, dips in enumerate(dips_by_pair)
            for dip in dips
            if first_signal <= dip.index < last_signal and dip.at_least(params.k)
        ),
        key=lambda event: event[:2],
    )

    run = Run()
    free_from = [0] * len(series)  # the minute each pair is free again
    loss_exits: list[int] = []  # minutes at which a losing trade ended
    for minute, pair, dip in events:
        if minute < free_from[pair]:
            continue  # an order or a trade already exists in this pair
        loss_exits = [x for x in loss_exits if x + PAUSE_AFTER_LOSS_MINUTES > minute]
        if any(x <= minute for x in loss_exits):
            continue  # the pause after a loss, on every pair
        if params.target_share * dip.distance < TARGET_FLOOR:
            continue  # the target would be too close to the fees
        others = [other for other in range(len(series)) if other != pair]
        together = bool(others) and all(minute in dipping[other] for other in others)
        if together and any(free_from[other] > minute for other in others):
            continue  # the whole market is dipping: one bet, not three
        candles = series[pair]
        run.orders.append(Order(candles.symbol, minute, dip.close, dip.distance))
        free_from[pair], trade = _play_out(candles, dip, params)
        if trade is not None:
            run.trades.append(trade)
            # "A loss" = money lost after fees, at the 0.075% fee.
            if trade.profit(FEE_WITH_BNB) < 0:
                loss_exits.append(trade.exit_index)
    return run
