"""Runs the ten-coin trend test fixed in docs/build-roadmap.md, stage 7c.

Run from the project folder, ONCE:

    python scripts/trend_ten_run.py run

It downloads the daily candles of the ten coins by itself (the seven new
coins are not looked at before), replays the rule, and writes the full
result to `docs/trend-ten-result.txt`. It refuses to run when that file
exists, and when the ten measured spreads are not filled in below.
"""

import asyncio
import sys
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from exchange.history import (  # noqa: E402
    HISTORY_FOLDER,
    Candles,
    HistoryError,
    checksum_matches,
    file_name,
    file_url,
    load_candles,
    months_between,
)
from trading.trend import FEE_STANDARD, FEE_WITH_BNB  # noqa: E402
from trading.trend_ten import (  # noqa: E402
    AT_PERIOD_END,
    COIN_REMOVED,
    MAX_OPEN,
    RULE,
    Costs,
    Outcome,
    hold_trades,
    last_candle,
    outcome,
    pass_mark,
    replay,
)

# The ten, in rank order (largest first), as fixed in the roadmap.
TEN = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "SOLUSDT",
    "MATICUSDT",
    "DOTUSDT",
    "SHIBUSDT",
)
SEVEN = TEN[3:]  # the coins nobody has opened
# The only coin that may end before the period does. Known before any candle
# was opened, from Binance's own pair list on 2026-11-27 (see the roadmap):
# MATICUSDT is not trading any more; the other nine are. For any other coin,
# data that stops early is a broken download, not a removed coin.
MAY_END_EARLY = ("MATICUSDT",)

# Each coin's measured spread, in percent, exactly as printed by
# `spread_measure.py summary`. Filled in (and committed) after the 7 days of
# measuring and before this script is run. Empty means: not measured yet.
SPREAD_PERCENT: dict[str, str] = {}
LARGEST_SPREAD_PERCENT = Fraction(5)  # anything above is a typing mistake

FIRST_MONTH = (2022, 10)  # October 2022: only the 20 earlier days
PERIOD_START = (2022, 11)
LAST_MONTH = (2026, 10)
DAYS_BEFORE = 31  # every day of October 2022 must be there
RESULT_FILE = Path(__file__).resolve().parent.parent / "docs/trend-ten-result.txt"

PAUSE_SECONDS = 0.3  # be gentle with the archive
LARGEST_FILE = 1024 * 1024  # a month of daily candles is a few KB

Month = tuple[int, int]


class NotReady(Exception):
    """The run cannot start. Nothing was calculated and nothing was looked at."""


def spreads() -> dict[str, Fraction]:
    """The ten spreads as shares (0.01% is 1/10000), or NotReady."""
    if set(SPREAD_PERCENT) != set(TEN):
        raise NotReady("the ten measured spreads are not filled in yet")
    out = {}
    for symbol in TEN:
        try:
            percent = Fraction(SPREAD_PERCENT[symbol])
        except (ValueError, ZeroDivisionError):
            raise NotReady(f"{symbol}: the spread is not a number") from None
        if not 0 < percent <= LARGEST_SPREAD_PERCENT:
            raise NotReady(f"{symbol}: the spread is not between 0% and 5%")
        out[symbol] = percent / 100
    # A coin that could not be measured carries the largest of the others.
    for symbol in MAY_END_EARLY:
        others = max(value for name, value in out.items() if name != symbol)
        if out[symbol] != others:
            raise NotReady(f"{symbol}: its spread must be the largest of the others")
    return out


# --- the download ---


async def _get(client: httpx.AsyncClient, url: str, name: str) -> bytes | None:
    """The file, or None when the archive does not have it (404)."""
    try:
        response = await client.get(url)
    except httpx.HTTPError as error:
        raise NotReady(f"{name}: {type(error).__name__}") from None
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise NotReady(f"{name}: the archive answered {response.status_code}")
    if len(response.content) > LARGEST_FILE:
        raise NotReady(f"{name}: the file is larger than expected")
    return response.content


async def _checked(
    client: httpx.AsyncClient, url: str, name: str, content: bytes
) -> None:
    """Refuse a file that does not have the SHA-256 Binance publishes."""
    checksum = await _get(client, url + ".CHECKSUM", name)
    try:
        text = (checksum or b"").decode("ascii")
    except UnicodeDecodeError:
        text = ""
    if not checksum_matches(content, text, name):
        raise NotReady(f"{name}: the checksum does not match")


async def download(
    client: httpx.AsyncClient, folder: Path, symbols: Sequence[str] = TEN
) -> dict[str, list[Month]]:
    """Make sure every month is in `folder`, each one checked against the
    SHA-256 Binance publishes beside it (a file already there is checked
    too). Returns, per coin, the months the archive does not have."""
    folder.mkdir(exist_ok=True)
    absent: dict[str, list[Month]] = {symbol: [] for symbol in symbols}
    for symbol in symbols:
        for year, month in months_between(FIRST_MONTH, LAST_MONTH):
            name = file_name(symbol, year, month, "1d")
            target = folder / name
            url = file_url(symbol, year, month, "1d")
            if target.exists():
                await _checked(client, url, name, target.read_bytes())
                continue
            content = await _get(client, url, name)
            if content is None:
                # Really not there only when its checksum is not there either.
                if await _get(client, url + ".CHECKSUM", name) is not None:
                    raise NotReady(f"{name}: the archive has it but did not send it")
                absent[symbol].append((year, month))
                continue
            await _checked(client, url, name, content)
            partial = target.with_suffix(".part")
            partial.write_bytes(content)
            partial.rename(target)
            await asyncio.sleep(PAUSE_SECONDS)
    return absent


def check_absent(absent: Mapping[str, Sequence[Month]]) -> None:
    """Months may be missing from the archive only for the coin known to be
    removed, and only at the END of its history. Anything else stops the run."""
    months = months_between(FIRST_MONTH, LAST_MONTH)
    for symbol, missing in absent.items():
        if missing and symbol not in MAY_END_EARLY:
            raise NotReady(f"{symbol}: a month is missing from the archive")
        if missing and list(missing) != months[len(months) - len(missing) :]:
            raise NotReady(f"{symbol}: a month is missing inside its history")


def load(folder: Path, absent: Mapping[str, Sequence[Month]]) -> list[Candles]:
    try:
        return [
            load_candles(symbol, FIRST_MONTH, LAST_MONTH, folder, "1d", absent[symbol])
            for symbol in TEN
        ]
    except HistoryError as error:
        raise NotReady(str(error)) from None


def check_start(series: Sequence[Candles]) -> int:
    """Every coin must have each day of October 2022 and the first day of the
    period (the rule that picked the coins), and its last day too, unless it
    is the coin known to be removed. Returns the period's first day."""
    start = series[0].index_of(*PERIOD_START)
    if start != DAYS_BEFORE:
        raise NotReady("the data does not start on 1 October 2022")
    end = len(series[0])
    for candles in series:
        if min(candles.close[: start + 1]) <= 0 or candles.open[start] <= 0:
            raise NotReady(f"{candles.symbol}: a day is missing before the period")
        if candles.symbol not in MAY_END_EARLY and last_candle(candles, end) < end - 1:
            raise NotReady(f"{candles.symbol}: the last day of the period is missing")
    return start


# --- the result ---


def usdt(value: Fraction) -> str:
    return f"{value:+.2f} USDT"


def line(label: str, decides: Outcome, with_bnb: Outcome, wide: Outcome) -> str:
    wins = sum(1 for profit in decides.profits if profit > 0)
    return (
        f"{label:<14} trades={len(decides.profits):<4} wins={wins:<4} "
        f"profit@0.1%={usdt(decides.profit):<15} "
        f"worst drop={decides.worst_drop * 100:.1f}%  "
        f"without best={usdt(decides.profit_without_best):<15} "
        f"| reported only: @0.075%={usdt(with_bnb.profit)}, "
        f"double spread={usdt(wide.profit)}"
    )


def one_run(
    title: str, series: Sequence[Candles], start: int, spread: Mapping[str, Fraction]
) -> tuple[list[str], Outcome, Outcome]:
    """The bot and buy-and-hold on one set of coins. Returns the lines to
    print and the two outcomes at the costs that decide."""
    end = len(series[0])
    three_costs = (
        Costs(FEE_STANDARD, spread),
        Costs(FEE_WITH_BNB, spread),
        Costs(FEE_STANDARD, {symbol: 2 * value for symbol, value in spread.items()}),
    )
    played = replay(series, start, end)
    held_trades = hold_trades(series, start, end)
    bot = [outcome(series, played.trades, start, end, costs) for costs in three_costs]
    held = [outcome(series, held_trades, start, end, costs) for costs in three_costs]
    at_end = sum(1 for trade in played.trades if trade.ended == AT_PERIOD_END)
    removed = sum(1 for trade in played.trades if trade.ended == COIN_REMOVED)
    out = [
        title,
        line("buy-and-hold", *held),
        line("trend rule", *bot),
        f"  buy signals dropped (no free place, or no candle): {played.dropped}; "
        f"sold at period end: {at_end}; sold because the coin was removed: {removed}",
    ]
    for candles, kept in zip(series, held[0].profits, strict=True):
        profits = [
            profit
            for trade, profit in zip(bot[0].trades, bot[0].profits, strict=True)
            if trade.symbol == candles.symbol
        ]
        out.append(
            f"  {candles.symbol:<10} trend rule: {len(profits):>3} trades, "
            f"{usdt(sum(profits, Fraction(0))):<15} buy-and-hold: {usdt(kept)}"
        )
    return out, bot[0], held[0]


def report(series: Sequence[Candles], spread: Mapping[str, Fraction]) -> list[str]:
    """The whole result: both runs, the five conditions and the verdict."""
    start, end = check_start(series), len(series[0])
    out = [
        "TEN-COIN TREND TEST, 2022-11-01 to 2026-10-31 (run once)",
        f"rule: {RULE.label}; 24 USDT per trade, at most {MAX_OPEN} open, 72 USDT",
        "spread used, in percent: "
        + ", ".join(f"{s} {float(spread[s] * 100):.5f}" for s in TEN),
    ]
    for candles in series:
        day = last_candle(candles, end)
        if day < end - 1:
            out.append(
                f"removed from Binance during the period: {candles.symbol} "
                f"(last candle {candles.time_of(day):%Y-%m-%d})"
            )
    ten, bot_ten, hold_ten = one_run("TEN COINS", series, start, spread)
    seven_series = [candles for candles in series if candles.symbol in SEVEN]
    seven, bot_seven, hold_seven = one_run(
        "THE SEVEN NEW COINS ALONE", seven_series, start, spread
    )
    marks = pass_mark(bot_ten, hold_ten, bot_seven, hold_seven)
    out += ["", *ten, "", *seven, ""]
    out += [f"{name}: {'yes' if ok else 'NO'}" for name, ok in marks.items()]
    out.append("RESULT: " + ("PASS" if all(marks.values()) else "FAIL"))
    return out


async def fetch(folder: Path) -> dict[str, list[Month]]:
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        return await download(client, folder)


def main(argv: list[str], folder: Path = HISTORY_FOLDER) -> int:
    if argv[1:] != ["run"]:
        print("usage: python scripts/trend_ten_run.py run")
        return 2
    if RESULT_FILE.exists():
        print(f"Refused: the test was already run (see {RESULT_FILE.name}).")
        return 1
    try:
        spread = spreads()
        absent = asyncio.run(fetch(folder))
        check_absent(absent)
        series = load(folder, absent)
        check_start(series)
    except NotReady as error:
        print(f"Not started, nothing was calculated: {error}")
        return 1
    # The marker is written first: even a crash counts as "looked at".
    RESULT_FILE.write_text("the ten-coin run was started\n")
    out = report(series, spread)
    RESULT_FILE.write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
