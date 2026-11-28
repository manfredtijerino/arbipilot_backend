"""Measure each coin's spread: the gap between the best buy and sell price.

The ten-coin trend test (`docs/build-roadmap.md`, stage 7c) charges every
order half of its coin's spread. Binance does not publish past spreads, so
they are measured now: once a minute, for 7 days, from Binance's public best
bid and ask.

    python3 spread_measure.py measure          # 7 days, writes samples.csv
    python3 spread_measure.py summary          # the ten averages

This file runs by itself on the server, outside the app: it uses only
Python's own library (3.12 or newer), no key, no `.env` and no database. It
only reads public prices and writes one file next to itself.
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

# The ten pairs, in the rank order fixed in the roadmap.
SYMBOLS = (
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
URL = "https://api.binance.com/api/v3/ticker/bookTicker"
MINUTES = 7 * 24 * 60  # 7 days
INTERVAL_SECONDS = 60
TIMEOUT_SECONDS = 10
LONGEST_WAIT_SECONDS = 600  # after Binance says "slow down"
SAMPLES_FILE = "samples.csv"

Fetch = Callable[[], list[dict]]


def request_url(symbols: Iterable[str] = SYMBOLS) -> str:
    """The address of one question: the best bid and ask of every pair that
    is trading right now. A pair that is not trading is left out by Binance."""
    wanted = json.dumps(list(symbols), separators=(",", ":"))
    query = urllib.parse.urlencode({"symbols": wanted, "symbolStatus": "TRADING"})
    return f"{URL}?{query}"


def fetch() -> list[dict]:
    """Ask Binance once. Raises on any network or HTTP problem."""
    request = urllib.request.Request(  # noqa: S310 - a fixed https address
        request_url(), headers={"User-Agent": "spread-measure"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        answer = json.loads(response.read())
    if not isinstance(answer, list):
        raise ValueError("Binance answered something that is not a list")
    return answer


def rows_of(answer: list[dict], at: datetime) -> list[tuple[str, str, str, str]]:
    """The lines to write for one answer: time, pair, bid, ask, as received.

    Only the ten pairs are kept, and only entries that carry both prices as
    text. Whether a sample counts is decided later, in `spread_of`.
    """
    stamp = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for entry in answer:
        if not isinstance(entry, dict):
            continue
        symbol, bid, ask = (entry.get(k) for k in ("symbol", "bidPrice", "askPrice"))
        if symbol in SYMBOLS and isinstance(bid, str) and isinstance(ask, str):
            rows.append((stamp, symbol, bid, ask))
    return rows


def wait_after(error: Exception) -> float:
    """How long to stay quiet after a failed question, in seconds.

    When Binance says "too many requests" (429) or blocks the address (418)
    it also says for how long; that is obeyed, up to ten minutes at a time.
    """
    if isinstance(error, urllib.error.HTTPError) and error.code in (418, 429):
        try:
            asked = float(error.headers.get("Retry-After", ""))
        except (TypeError, ValueError):
            asked = INTERVAL_SECONDS
        return min(max(asked, INTERVAL_SECONDS), LONGEST_WAIT_SECONDS)
    return 0.0


def measure(
    out: Path,
    minutes: int = MINUTES,
    ask_binance: Fetch = fetch,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> int:
    """Ask once a minute for `minutes` minutes and add the answers to `out`.

    A failed question is written to the log and skipped: the minute is lost,
    not made up. It stops when the time is over, however many questions
    were answered. Returns how many were.
    """
    start = clock()
    end = start + minutes * INTERVAL_SECONDS
    asked = answered = 0
    log(f"{now():%Y-%m-%dT%H:%M:%SZ} start: {minutes} minutes, writing {out.name}")
    with out.open("a", newline="") as file:
        writer = csv.writer(file)
        while clock() < end:
            quiet = 0.0
            asked += 1
            try:
                rows = rows_of(ask_binance(), now())
                writer.writerows(rows)
                file.flush()
                answered += 1
            except (OSError, ValueError) as error:
                # Network, HTTP and unreadable answers. The type only: an
                # error text can hold an address.
                log(f"{now():%Y-%m-%dT%H:%M:%SZ} missed: {type(error).__name__}")
                quiet = wait_after(error)
            if asked % 60 == 0:
                log(f"{now():%Y-%m-%dT%H:%M:%SZ} asked {asked}, answered {answered}")
            # The next full minute counted from the start, never sooner: after
            # a long wait the lost minutes are skipped, not asked in a burst.
            elapsed = clock() - start
            to_next_minute = INTERVAL_SECONDS - elapsed % INTERVAL_SECONDS
            sleep(max(to_next_minute, quiet))
    log(f"{now():%Y-%m-%dT%H:%M:%SZ} done: {answered} of {asked} answered")
    return answered


def spread_of(bid: str, ask: str) -> Fraction | None:
    """One sample's spread: (ask - bid) / the middle price. None when the
    sample does not count (no bid, or an ask below the bid)."""
    try:
        low, high = Fraction(bid), Fraction(ask)
    except (ValueError, ZeroDivisionError):
        return None
    if low <= 0 or high < low:
        return None
    return (high - low) / ((high + low) / 2)


def summarise(lines: Iterable[list[str]]) -> dict[str, tuple[int, Fraction]]:
    """Each pair's number of counted samples and its average spread.

    A pair with no sample at all (it does not trade any more) gets the
    largest average among the others, as fixed in the roadmap.
    """
    totals = {symbol: [0, Fraction(0)] for symbol in SYMBOLS}
    for line in lines:
        if len(line) != 4 or line[1] not in totals:
            continue
        spread = spread_of(line[2], line[3])
        if spread is not None:
            totals[line[1]][0] += 1
            totals[line[1]][1] += spread
    averages = {s: total / count for s, (count, total) in totals.items() if count}
    if not averages:
        raise ValueError("no sample counts: nothing was measured")
    largest = max(averages.values())
    return {s: (totals[s][0], averages.get(s, largest)) for s in SYMBOLS}


def report(result: dict[str, tuple[int, Fraction]]) -> list[str]:
    lines = ["pair        samples   average spread"]
    for symbol, (count, spread) in result.items():
        note = "" if count else "   (not trading: the largest of the others)"
        lines.append(f"{symbol:<10} {count:>8}   {float(spread * 100):.5f}%{note}")
    return lines


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=["measure", "summary"])
    parser.add_argument("--file", default=SAMPLES_FILE)
    parser.add_argument("--minutes", type=int, default=MINUTES)
    options = parser.parse_args(arguments)
    path = Path(options.file)
    if options.what == "measure":
        measure(path, options.minutes)
        return 0
    with path.open(newline="") as file:
        result = summarise(csv.reader(file))
    print("\n".join(report(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
