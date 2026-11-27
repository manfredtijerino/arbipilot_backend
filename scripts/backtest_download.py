"""Downloads past candles for the backtests.

Run from the project folder:

    python scripts/backtest_download.py          # one-minute, 2023-11 on
    python scripts/backtest_download.py daily    # daily, 2017-11 on

Files come from Binance's public archive (no key, no login) and land in
`history/`, which git ignores. Each file is checked against the SHA-256 that
Binance publishes beside it. Files already there are skipped, so the command
can be run again after an interruption.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from exchange.history import (  # noqa: E402
    HISTORY_FOLDER,
    checksum_matches,
    file_name,
    file_url,
    months_between,
)

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
LAST_MONTH = (2026, 10)
# What to fetch: the candle size and the first month.
SETS = {"minute": ("1m", (2023, 11)), "daily": ("1d", (2017, 11))}
PAUSE_SECONDS = 0.3  # be gentle with the archive
LARGEST_FILE = 50 * 1024 * 1024


async def fetch(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"the archive answered {response.status_code}")
    if len(response.content) > LARGEST_FILE:
        raise RuntimeError("the file is larger than expected")
    return response.content


async def download(which: str = "minute", folder: Path = HISTORY_FOLDER) -> int:
    interval, first_month = SETS[which]
    folder.mkdir(exist_ok=True)
    wanted = [
        (symbol, year, month)
        for symbol in SYMBOLS
        for year, month in months_between(first_month, LAST_MONTH)
    ]
    done = 0
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        for symbol, year, month in wanted:
            name = file_name(symbol, year, month, interval)
            target = folder / name
            if target.exists():
                done += 1
                continue
            url = file_url(symbol, year, month, interval)
            try:
                content = await fetch(client, url)
                checksum = (await fetch(client, url + ".CHECKSUM")).decode("ascii")
            except (httpx.HTTPError, RuntimeError, UnicodeDecodeError) as exc:
                print(f"✖ {name}: {type(exc).__name__}: {exc}")
                continue
            if not checksum_matches(content, checksum, name):
                print(f"✖ {name}: the checksum does not match; not saved")
                continue
            partial = target.with_suffix(".part")
            partial.write_bytes(content)
            partial.rename(target)
            done += 1
            print(f"✔ {name} ({len(content) // 1024} KB)", flush=True)
            await asyncio.sleep(PAUSE_SECONDS)
    print(f"{done} of {len(wanted)} files are in {folder.name}/")
    return 0 if done == len(wanted) else 1


if __name__ == "__main__":
    which = "daily" if sys.argv[1:] == ["daily"] else "minute"
    sys.exit(asyncio.run(download(which)))
