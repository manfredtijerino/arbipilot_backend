"""Runs the trend test fixed in docs/build-roadmap.md, stage 7b.

Run from the project folder (after `python scripts/backtest_download.py daily`):

    python scripts/trend_run.py choosing   # the 4 combinations, 2018-01 to 2022-10
    python scripts/trend_run.py hidden     # the chosen one, 2022-11 to 2026-10, ONCE

The hidden run writes its result to `docs/trend-hidden-result.txt` and
refuses to run when that file exists: the hidden period is looked at once.
"""

import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exchange.history import Candles, load_candles  # noqa: E402
from trading.trend import (  # noqa: E402
    ALL_PARAMS,
    FEE_STANDARD,
    FEE_WITH_BNB,
    Outcome,
    Params,
    choose,
    hold,
    pass_mark,
    require_every_day,
    run,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
FIRST_DATA_MONTH = (2017, 11)
LAST_MONTH = (2026, 10)
CHOOSING_START = (2018, 1)
HIDDEN_START = (2022, 11)
RESULT_FILE = Path(__file__).resolve().parent.parent / "docs/trend-hidden-result.txt"


def usdt(value: Fraction) -> str:
    return f"{value:+.2f} USDT"


def line(label: str, result: Outcome, reported: Outcome) -> str:
    profits = result.profits
    wins = sum(1 for profit in profits if profit > 0)
    ended = sum(1 for trade in result.trades if trade.at_period_end)
    return (
        f"{label:<32} trades={len(profits):<4} wins={wins:<4} "
        f"profit@0.1%={usdt(result.profit):<15} "
        f"profit@0.075%={usdt(reported.profit):<15} "
        f"worst drop={result.worst_drop * 100:.1f}%  "
        f"without best={usdt(result.profit_without_best)}  "
        f"(sold at period end: {ended})"
    )


def both_fees(series: list[Candles], params: Params | None, start: int, end: int):  # noqa: ANN201
    """The outcome at the fee that decides and at the reported one."""
    if params is None:
        return hold(series, start, end, FEE_STANDARD), hold(
            series, start, end, FEE_WITH_BNB
        )
    return run(series, params, start, end, FEE_STANDARD), run(
        series, params, start, end, FEE_WITH_BNB
    )


def choosing(series: list[Candles]) -> tuple[Params | None, list[str]]:
    start = series[0].index_of(*CHOOSING_START)
    end = series[0].index_of(*HIDDEN_START)
    out = [
        "CHOOSING PERIOD 2018-01-01 to 2022-10-31 (72 USDT, 24 per pair)",
        line("buy-and-hold", *both_fees(series, None, start, end)),
    ]
    results = []
    for params in ALL_PARAMS:
        decides, reported = both_fees(series, params, start, end)
        results.append((params, decides))
        out.append(line(params.label, decides, reported))
    chosen = choose(results)
    out.append(
        f"chosen: {chosen.label}"
        if chosen
        else "chosen: none (no combination with 20 trades and a profit above "
        "zero): the idea FAILED; the hidden period is not run"
    )
    return chosen, out


def hidden(series: list[Candles], params: Params) -> list[str]:
    start, end = series[0].index_of(*HIDDEN_START), len(series[0])
    held, held_reported = both_fees(series, None, start, end)
    bot, bot_reported = both_fees(series, params, start, end)
    marks = pass_mark(bot, held)
    out = [
        "HIDDEN PERIOD 2022-11-01 to 2026-10-31 (run once; 72 USDT, 24 per pair)",
        line("buy-and-hold", held, held_reported),
        line(params.label, bot, bot_reported),
    ]
    for symbol in SYMBOLS:
        profits = [
            profit
            for trade, profit in zip(bot.trades, bot.profits, strict=True)
            if trade.symbol == symbol
        ]
        out.append(
            f"  {symbol}: {len(profits)} trades, {usdt(sum(profits, Fraction(0)))}"
        )
    out += [f"{name}: {'yes' if ok else 'NO'}" for name, ok in marks.items()]
    out.append("RESULT: " + ("PASS" if all(marks.values()) else "FAIL"))
    return out


def main(argv: list[str]) -> int:
    if argv[1:] not in (["choosing"], ["hidden"]):
        print("usage: python scripts/trend_run.py choosing|hidden")
        return 2
    if argv[1] == "hidden" and RESULT_FILE.exists():
        print(f"Refused: the hidden period was already run (see {RESULT_FILE.name}).")
        return 1
    series = [
        load_candles(symbol, FIRST_DATA_MONTH, LAST_MONTH, interval="1d")
        for symbol in SYMBOLS
    ]
    # Every day from the first one a signal can look back to must exist.
    longest = max(params.buy_days for params in ALL_PARAMS)
    first_used = series[0].index_of(*CHOOSING_START) - longest
    require_every_day(series, first_used, len(series[0]))
    chosen, out = choosing(series)
    if argv[1] == "hidden" and chosen is not None:
        # The marker is written first: even a crash counts as "looked at".
        RESULT_FILE.write_text("the hidden run was started\n")
        out += ["", *hidden(series, chosen)]
        RESULT_FILE.write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
