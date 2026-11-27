"""Saves the price stream to files, and reads them back.

A recording is test data: one night of real prices replays in a test in
seconds, so trading tests never need the network.

Format: one line per message, compressed. Each line is
`{"t": <when it arrived, in milliseconds>, "m": <the message as Binance sent it>}`.
A new file starts each time the app starts and each UTC day:
`market-YYYYMMDD-HHMMSS.jsonl.gz`. A file is never added to after a restart,
because a file cut short by a crash would be damaged by it.

Recording is off unless `MARKET_RECORDING=true`. It stops by itself when the
folder reaches `MAX_FOLDER_BYTES` or the disk has less than `MIN_FREE_BYTES`
left.
"""

import gzip
import logging
import shutil
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from exchange.numbers import read_json

logger = logging.getLogger(__name__)

RECORDINGS_FOLDER = Path(__file__).resolve().parent.parent / "recordings"

# The folder never grows past this. About a week of three busy pairs.
MAX_FOLDER_BYTES = 2 * 1024 * 1024 * 1024

# Recording stops when the disk has less than this left for everything else.
MIN_FREE_BYTES = 1024 * 1024 * 1024

# Seconds between writing the buffered lines to disk and checking the size.
FLUSH_SECONDS = 5


class Recorder:
    def __init__(
        self,
        folder: Path = RECORDINGS_FOLDER,
        max_folder_bytes: int = MAX_FOLDER_BYTES,
        min_free_bytes: int = MIN_FREE_BYTES,
    ) -> None:
        self._folder = folder
        self._max_folder_bytes = max_folder_bytes
        self._min_free_bytes = min_free_bytes
        self._file: IO[str] | None = None
        self._day = ""
        self._last_flush: datetime | None = None
        self.path: Path | None = None
        self.lines_written = 0
        self.stopped_reason = ""

    @property
    def active(self) -> bool:
        return not self.stopped_reason

    def folder_bytes(self) -> int:
        total = 0
        try:
            for file in self._folder.glob("market-*.jsonl.gz"):
                total += file.stat().st_size
        except OSError:  # no folder, or a file vanished while counting
            pass
        return total

    def write(self, raw: str, received_at: datetime) -> None:
        """Save one message. Never raises: a full disk must not stop prices."""
        if not self.active or "\n" in raw or "\r" in raw:
            return  # one message is one line
        try:
            day = received_at.strftime("%Y%m%d")
            if day != self._day:
                self._open(day, received_at)
            if self._file is None:
                return
            milliseconds = int(received_at.timestamp() * 1000)
            self._file.write(f'{{"t":{milliseconds},"m":{raw}}}\n')
            self.lines_written += 1
            if (
                self._last_flush is None
                or (received_at - self._last_flush).total_seconds() >= FLUSH_SECONDS
            ):
                self._last_flush = received_at
                self._file.flush()
                if self.folder_bytes() >= self._max_folder_bytes:
                    self._stop("the recordings folder reached its size limit")
                elif shutil.disk_usage(self._folder).free < self._min_free_bytes:
                    self._stop("the disk is nearly full")
        except Exception as exc:  # noqa: BLE001 - whatever it is, prices go on
            self._stop(f"could not write the file ({type(exc).__name__})")

    def _open(self, day: str, now: datetime) -> None:
        self.close()
        self._folder.mkdir(parents=True, exist_ok=True)
        self.path = self._folder / f"market-{now:%Y%m%d-%H%M%S}.jsonl.gz"
        self._file = gzip.open(self.path, "at", encoding="utf-8")
        self._day = day

    def _stop(self, reason: str) -> None:
        self.stopped_reason = reason
        logger.warning("market recording stopped: %s", reason)
        self.close()

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:  # noqa: BLE001, S110 - nothing more can be done
                pass
            self._file = None
            self._day = ""


def read_recording(path: Path) -> Iterator[tuple[datetime, Any]]:
    """Each recorded message with the time it arrived, in the order recorded.

    Numbers with a point come back as `Decimal`, never as floats. A file cut
    short by a crash is read up to the cut.
    """
    with gzip.open(path, "rt", encoding="utf-8") as file:
        try:
            for line in file:
                if not line.strip():
                    continue
                row = read_json(line)
                yield datetime.fromtimestamp(row["t"] / 1000, UTC), row["m"]
        except (EOFError, zlib.error, ValueError):
            # The app was stopped mid-write: the file ends early. Everything
            # before the cut has already been handed out.
            return
