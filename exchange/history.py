"""Past prices: one-minute candles from Binance's public archive.

The archive (`data.binance.vision`) holds one zip per pair and month. Its
terms allow personal backtesting; nothing here is used for live trading.
Format checked against Binance's own description on 2026-11-27: columns are
open time, open, high, low, close, ...; times are milliseconds before 2025
and microseconds from 2025 on; each zip has a SHA-256 `.CHECKSUM` beside it.

Prices are kept as whole numbers of 0.00000001 (Binance never prints more
than 8 decimals), so every calculation on them is exact. No floats.
"""

import hashlib
import io
import zipfile
from array import array
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from exchange.numbers import to_decimal

ARCHIVE_HOST = "data.binance.vision"
HISTORY_FOLDER = Path(__file__).resolve().parent.parent / "history"

# One price unit is this much of the quote asset.
UNITS_PER_ONE = 10**8
MINUTE_MS = 60_000


class HistoryError(Exception):
    """An archive file is missing, damaged or not what was expected."""


def to_units(text: str) -> int:
    """A price as text, as a whole number of units. Exact, or HistoryError."""
    try:
        scaled = to_decimal(text) * UNITS_PER_ONE
    except ValueError:
        raise HistoryError("a price in the archive is not a plain number") from None
    if scaled <= 0:
        raise HistoryError("a price in the archive is zero")
    if scaled != scaled.to_integral_value():
        raise HistoryError("a price in the archive has more than 8 decimals")
    return int(scaled)


def from_units(units: int) -> Decimal:
    return Decimal(units) / UNITS_PER_ONE


def month_name(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def months_between(
    first: tuple[int, int], last: tuple[int, int]
) -> list[tuple[int, int]]:
    """Every (year, month) from `first` to `last`, both included."""
    months, (year, month) = [], first
    while (year, month) <= last:
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


# The candle sizes used here, in minutes per candle.
INTERVALS = {"1m": 1, "1d": 1440}


def file_name(symbol: str, year: int, month: int, interval: str = "1m") -> str:
    return f"{symbol}-{interval}-{month_name(year, month)}.zip"


def file_url(symbol: str, year: int, month: int, interval: str = "1m") -> str:
    name = file_name(symbol, year, month, interval)
    folder = f"data/spot/monthly/klines/{symbol}/{interval}"
    return f"https://{ARCHIVE_HOST}/{folder}/{name}"


def checksum_matches(content: bytes, checksum_text: str, name: str) -> bool:
    """Does `content` have the SHA-256 that the `.CHECKSUM` file states?"""
    parts = checksum_text.split()
    if len(parts) != 2 or parts[1] != name:
        return False
    return hashlib.sha256(content).hexdigest() == parts[0].lower()


def minute_of(year: int, month: int) -> int:
    """Minutes since 1970 at the first minute of a month (UTC)."""
    return int(datetime(year, month, 1, tzinfo=UTC).timestamp()) // 60


@dataclass
class Candles:
    """One pair's candles, one slot per candle, 0 where missing.

    Slot `i` starts at minute `first_minute + i * step` (minutes since 1970,
    UTC). `step` is 1 for one-minute candles and 1440 for daily ones.
    """

    symbol: str
    first_minute: int
    open: array
    high: array
    low: array
    close: array
    step: int = 1

    def __len__(self) -> int:
        return len(self.close)

    def index_of(self, year: int, month: int) -> int:
        return (minute_of(year, month) - self.first_minute) // self.step

    def time_of(self, index: int) -> datetime:
        minute = self.first_minute + index * self.step
        return datetime.fromtimestamp(minute * 60, UTC)

    def head(self, minutes: int) -> "Candles":
        """Only the first `minutes` minutes: what was known up to then."""
        return Candles(
            self.symbol,
            self.first_minute,
            self.open[:minutes],
            self.high[:minutes],
            self.low[:minutes],
            self.close[:minutes],
            self.step,
        )

    @property
    def present(self) -> int:
        return sum(1 for value in self.close if value)


def empty_candles(symbol: str, first_minute: int, minutes: int) -> Candles:
    def zeros() -> array:
        return array("q", bytes(8 * minutes))

    return Candles(symbol, first_minute, zeros(), zeros(), zeros(), zeros())


def read_rows(zip_bytes: bytes) -> list[tuple[int, int, int, int, int]]:
    """(minute since 1970, open, high, low, close) for each row of one zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            names = [name for name in archive.namelist() if name.endswith(".csv")]
            if len(names) != 1:
                raise HistoryError("an archive zip does not hold exactly one CSV")
            text = archive.read(names[0]).decode("ascii")
    except (zipfile.BadZipFile, UnicodeDecodeError, OSError):
        raise HistoryError("an archive zip could not be opened") from None
    rows = []
    for line in text.splitlines():
        fields = line.split(",")
        if len(fields) < 5 or not fields[0].isascii() or not fields[0].isdigit():
            continue  # a header line, or an empty one
        stamp = int(fields[0])
        # Milliseconds before 2025, microseconds from 2025 on.
        milliseconds = stamp // 1000 if stamp >= 10**14 else stamp
        if milliseconds % MINUTE_MS:
            raise HistoryError("a candle does not start on a whole minute")
        opened, high, low, close = (to_units(field) for field in fields[1:5])
        if not low <= min(opened, close) <= max(opened, close) <= high:
            raise HistoryError("a candle's high and low do not contain its prices")
        rows.append((milliseconds // MINUTE_MS, opened, high, low, close))
    if not rows:
        raise HistoryError("an archive zip holds no candles")
    return rows


def load_candles(
    symbol: str,
    first: tuple[int, int],
    last: tuple[int, int],
    folder: Path = HISTORY_FOLDER,
    interval: str = "1m",
    absent: Collection[tuple[int, int]] = (),
) -> Candles:
    """Every month from `first` to `last`, read from the downloaded zips.

    `absent` names the months the archive does not have for this pair (a
    coin removed from Binance): they are left without candles. Any other
    month whose file is not there is an error.
    """
    step = INTERVALS[interval]
    start = minute_of(*first)
    year, month = last
    end = minute_of(year + 1, 1) if month == 12 else minute_of(year, month + 1)
    candles = empty_candles(symbol, start, (end - start) // step)
    candles.step = step
    for year, month in months_between(first, last):
        if (year, month) in absent:
            continue
        path = folder / file_name(symbol, year, month, interval)
        try:
            content = path.read_bytes()
        except OSError:
            raise HistoryError(f"{path.name} is not downloaded") from None
        month_start = minute_of(year, month)
        month_end = (
            minute_of(year + 1, 1) if month == 12 else minute_of(year, month + 1)
        )
        for minute, opened, high, low, close in read_rows(content):
            if not month_start <= minute < month_end:
                raise HistoryError(f"{path.name} holds a candle outside its month")
            if (minute - start) % step:
                raise HistoryError(f"{path.name} holds a candle off its time grid")
            index = (minute - start) // step
            if candles.close[index]:
                raise HistoryError(f"{path.name} holds the same candle twice")
            candles.open[index], candles.high[index] = opened, high
            candles.low[index], candles.close[index] = low, close
    return candles
