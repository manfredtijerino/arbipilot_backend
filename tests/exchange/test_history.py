"""Reading Binance's archive files. The zips are built here; no network."""

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from exchange.history import (
    HistoryError,
    checksum_matches,
    file_name,
    file_url,
    from_units,
    load_candles,
    minute_of,
    months_between,
    read_rows,
    to_units,
)

JAN_2025 = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp()) * 1000  # milliseconds
DEC_2024 = int(datetime(2024, 12, 1, tzinfo=UTC).timestamp()) * 1000


def zipped(text: str, name: str = "BTCUSDT-1m-2024-12.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def row(
    stamp: int, o: str = "100.5", h: str = "101", low: str = "99.25", c: str = "100"
) -> str:
    return f"{stamp},{o},{h},{low},{c},12.5,{stamp + 59999},1250,7,6,600,0"


def test_prices_become_exact_whole_units() -> None:
    assert to_units("42283.58000000") == 4_228_358_000_000
    assert to_units("0.00000001") == 1
    assert from_units(4_228_358_000_000) == Decimal("42283.58")


@pytest.mark.parametrize("text", ["0", "-1", "1e5", "abc", "", "0.000000001", "NaN"])
def test_a_strange_price_is_refused(text: str) -> None:
    with pytest.raises(HistoryError):
        to_units(text)


def test_months_run_across_a_year_end() -> None:
    assert months_between((2023, 11), (2024, 2)) == [
        (2023, 11),
        (2023, 12),
        (2024, 1),
        (2024, 2),
    ]
    assert len(months_between((2023, 11), (2026, 10))) == 36
    assert months_between((2024, 5), (2024, 4)) == []


def test_the_archive_address_is_built_from_fixed_parts() -> None:
    assert file_name("BTCUSDT", 2025, 1) == "BTCUSDT-1m-2025-01.zip"
    assert file_url("BTCUSDT", 2025, 1) == (
        "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/"
        "BTCUSDT-1m-2025-01.zip"
    )


def test_the_checksum_must_match_the_file_and_its_name() -> None:
    content = b"some bytes"
    digest = hashlib.sha256(content).hexdigest()
    assert checksum_matches(content, f"{digest}  a.zip\n", "a.zip")
    assert checksum_matches(content, f"{digest.upper()}  a.zip", "a.zip")
    assert not checksum_matches(content + b"!", f"{digest}  a.zip", "a.zip")
    assert not checksum_matches(content, f"{digest}  b.zip", "a.zip")
    assert not checksum_matches(content, digest, "a.zip")
    assert not checksum_matches(content, "", "a.zip")


def test_rows_before_2025_are_in_milliseconds() -> None:
    rows = read_rows(zipped(row(DEC_2024) + "\n" + row(DEC_2024 + 60_000)))
    assert rows[0] == (
        DEC_2024 // 60_000,
        to_units("100.5"),
        to_units("101"),
        to_units("99.25"),
        to_units("100"),
    )
    assert rows[1][0] == rows[0][0] + 1


def test_rows_from_2025_are_in_microseconds() -> None:
    rows = read_rows(zipped(row(JAN_2025 * 1000)))
    assert rows[0][0] == JAN_2025 // 60_000 == minute_of(2025, 1)


def test_a_header_line_and_blank_lines_are_skipped() -> None:
    text = "open_time,open,high,low,close\n\n" + row(DEC_2024) + "\n"
    assert len(read_rows(zipped(text))) == 1


@pytest.mark.parametrize(
    "text",
    [
        "",  # nothing
        "open_time,open,high,low,close\n",  # only a header
        row(DEC_2024 + 1),  # not on a whole minute
        row(DEC_2024, h="99"),  # the high is under the open
        row(DEC_2024, low="100.75"),  # the low is over the close
        row(DEC_2024, c="1e2"),
    ],
)
def test_a_damaged_file_is_refused(text: str) -> None:
    with pytest.raises(HistoryError):
        read_rows(zipped(text))


def test_something_that_is_not_a_zip_is_refused() -> None:
    with pytest.raises(HistoryError, match="could not be opened"):
        read_rows(b"<html>not found</html>")
    two = io.BytesIO()
    with zipfile.ZipFile(two, "w") as archive:
        archive.writestr("a.csv", row(DEC_2024))
        archive.writestr("b.csv", row(DEC_2024))
    with pytest.raises(HistoryError, match="exactly one CSV"):
        read_rows(two.getvalue())


def test_months_load_into_one_timeline_with_gaps_left_empty(tmp_path: Path) -> None:
    december = (
        row(DEC_2024) + "\n" + row(DEC_2024 + 120_000, c="100.25")
    )  # minute 1 missing
    january = row(JAN_2025 * 1000, c="100.75")
    (tmp_path / "BTCUSDT-1m-2024-12.zip").write_bytes(zipped(december))
    (tmp_path / "BTCUSDT-1m-2025-01.zip").write_bytes(zipped(january))
    candles = load_candles("BTCUSDT", (2024, 12), (2025, 1), tmp_path)
    assert len(candles) == (31 + 31) * 24 * 60
    assert candles.close[0] == to_units("100") and candles.close[1] == 0
    assert candles.close[2] == to_units("100.25") and candles.low[2] == to_units(
        "99.25"
    )
    january_start = candles.index_of(2025, 1)
    assert january_start == 31 * 24 * 60
    assert candles.close[january_start] == to_units("100.75")
    assert candles.present == 3
    assert candles.time_of(january_start) == datetime(2025, 1, 1, tzinfo=UTC)
    head = candles.head(2)
    assert len(head) == 2 and head.first_minute == candles.first_minute


def test_a_month_that_is_not_downloaded_is_named(tmp_path: Path) -> None:
    with pytest.raises(HistoryError, match="BTCUSDT-1m-2024-12.zip is not downloaded"):
        load_candles("BTCUSDT", (2024, 12), (2024, 12), tmp_path)


def test_a_candle_from_another_month_is_refused(tmp_path: Path) -> None:
    (tmp_path / "BTCUSDT-1m-2024-12.zip").write_bytes(zipped(row(JAN_2025 * 1000)))
    with pytest.raises(HistoryError, match="outside its month"):
        load_candles("BTCUSDT", (2024, 12), (2024, 12), tmp_path)


def test_a_candle_from_a_neighbouring_loaded_month_is_refused(tmp_path: Path) -> None:
    (tmp_path / "BTCUSDT-1m-2024-12.zip").write_bytes(zipped(row(JAN_2025 * 1000)))
    (tmp_path / "BTCUSDT-1m-2025-01.zip").write_bytes(zipped(row(JAN_2025 * 1000)))
    with pytest.raises(HistoryError, match="2024-12.zip holds a candle outside"):
        load_candles("BTCUSDT", (2024, 12), (2025, 1), tmp_path)


def test_the_same_minute_twice_is_refused(tmp_path: Path) -> None:
    twice = row(DEC_2024) + "\n" + row(DEC_2024)
    (tmp_path / "BTCUSDT-1m-2024-12.zip").write_bytes(zipped(twice))
    with pytest.raises(HistoryError, match="same minute twice"):
        load_candles("BTCUSDT", (2024, 12), (2024, 12), tmp_path)
