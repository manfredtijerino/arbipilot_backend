"""Runs the backtest fixed in docs/build-roadmap.md, stage 7a.

Run from the project folder:

    python scripts/backtest_run.py tuning   # the 12 combinations, first 2 years
    python scripts/backtest_run.py hidden   # the chosen one, last year, ONCE

The hidden run writes its result to `docs/backtest-hidden-result.txt` and
refuses to run when that file exists: the hidden year is looked at once.
"""

import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exchange.history import Candles, load_candles  # noqa: E402
from trading.backtest import (  # noqa: E402
    ALL_PARAMS,
    Params,
    Run,
    Summary,
    choose,
    pass_mark,
    simulate,
    summarise,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
FIRST_MONTH = (2023, 11)
LAST_TUNING_MONTH = (2025, 10)
FIRST_HIDDEN_MONTH = (2025, 11)
LAST_MONTH = (2026, 10)
RESULT_FILE = Path(__file__).resolve().parent.parent / "docs/backtest-hidden-result.txt"


def percent(value: Fraction) -> str:
    return f"{value * 100:+.4f}%"


def line(label: str, s: Summary) -> str:
    kinds = " ".join(f"{kind}={count}" for kind, count in sorted(s.by_kind.items()))
    return (
        f"{label:<28} trades={s.trades:<6} orders={s.orders:<7} "
        f"avg@0.075%={percent(s.average_with_bnb)} "
        f"avg@0.1%={percent(s.average_standard)} "
        f"wins={s.win_rate * 100:.1f}%  {kinds}"
    )


def market_moves(series: list[Candles], start: int, end: int) -> str:
    parts = []
    for candles in series:
        closes = [c for c in candles.close[start:end] if c]
        change = Decimal(closes[-1] - closes[0]) / closes[0] * 100
        parts.append(f"{candles.symbol} {change:+.1f}%")
    return ", ".join(parts)


def tuning() -> tuple[list[tuple[Params, Summary]], list[str]]:
    series = [load_candles(s, FIRST_MONTH, LAST_TUNING_MONTH) for s in SYMBOLS]
    out = [
        "TUNING PERIOD 2023-11 to 2025-10",
        "market: " + market_moves(series, 0, len(series[0])),
        "minutes with a candle: "
        + ", ".join(f"{c.symbol} {c.present} of {len(c)}" for c in series),
    ]
    results = []
    for params in ALL_PARAMS:
        summary = summarise(simulate(series, params))
        results.append((params, summary))
        out.append(line(params.label, summary))
    return results, out


def by_quarter(series: list[Candles], run: Run, start: int) -> list[str]:
    out = []
    end = len(series[0])
    quarter = (end - start) // 4
    for number in range(4):
        low = start + number * quarter
        high = end if number == 3 else low + quarter
        part = Run(trades=[t for t in run.trades if low <= t.signal_index < high])
        part.orders = [o for o in run.orders if low <= o.signal_index < high]
        label = f"  quarter {number + 1} ({series[0].time_of(low):%Y-%m})"
        out.append(line(label, summarise(part)))
        out.append("    market: " + market_moves(series, low, high))
    return out


def hidden(params: Params) -> list[str]:
    series = [load_candles(s, FIRST_MONTH, LAST_MONTH) for s in SYMBOLS]
    start = series[0].index_of(*FIRST_HIDDEN_MONTH)
    run = simulate(series, params, first_signal=start)
    summary = summarise(run)
    marks = pass_mark(summary)
    return [
        "HIDDEN PERIOD 2025-11 to 2026-10 (run once)",
        "market: " + market_moves(series, start, len(series[0])),
        line(params.label, summary),
        *by_quarter(series, run, start),
        *(f"{name}: {'yes' if ok else 'NO'}" for name, ok in marks.items()),
        "RESULT: " + ("PASS" if all(marks.values()) else "FAIL"),
    ]


def main(argv: list[str]) -> int:
    if argv[1:] not in (["tuning"], ["hidden"]):
        print("usage: python scripts/backtest_run.py tuning|hidden")
        return 2
    if argv[1] == "hidden" and RESULT_FILE.exists():
        print(f"Refused: the hidden year was already run (see {RESULT_FILE.name}).")
        return 1
    results, out = tuning()
    chosen = choose(results)
    out.append(
        f"chosen: {chosen.label}"
        if chosen
        else "chosen: none (no combination with 200 trades and a positive "
        "average): the strategy FAILED; the hidden year is not run"
    )
    if argv[1] == "hidden" and chosen is not None:
        # The marker is written first: even a crash counts as "looked at".
        RESULT_FILE.write_text("the hidden run was started\n")
        out += ["", *hidden(chosen)]
        RESULT_FILE.write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
