"""The recorder writes real files in a temporary folder, and reads them back."""

import gzip
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from exchange.market_stream import MarketState
from exchange.recorder import Recorder, read_recording
from tests.helpers.fake_stream import book, trade

DAY = datetime(2026, 1, 1, 23, 59, 58, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "market-sample.jsonl.gz"


def test_what_is_written_comes_back_the_same(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    messages = [book("BTCUSDT", "100.10", "100.20"), trade("BTCUSDT", "100.15")]
    for offset, raw in enumerate(messages):
        recorder.write(raw, DAY + timedelta(milliseconds=offset * 250))
    recorder.close()
    assert recorder.path == tmp_path / "market-20260101-235958.jsonl.gz"
    rows = list(read_recording(recorder.path))
    assert [at for at, _ in rows] == [DAY, DAY + timedelta(milliseconds=250)]
    assert rows[0][1]["data"]["b"] == "100.10"  # text stays text
    assert rows[1][1]["stream"] == "btcusdt@aggTrade"
    assert recorder.lines_written == 2 and recorder.active


def test_a_new_file_starts_each_utc_day(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    recorder.write(book("BTCUSDT", "1", "2"), DAY)
    recorder.write(book("BTCUSDT", "3", "4"), DAY + timedelta(seconds=5))
    recorder.close()
    names = sorted(file.name for file in tmp_path.iterdir())
    assert names == [
        "market-20260101-235958.jsonl.gz",
        "market-20260102-000003.jsonl.gz",
    ]


def test_a_restart_starts_a_new_file(tmp_path: Path) -> None:
    for offset, price in enumerate(("1", "3")):
        recorder = Recorder(tmp_path)
        recorder.write(
            book("BTCUSDT", price, "4"), DAY - timedelta(seconds=10 * offset)
        )
        recorder.close()
    files = sorted(tmp_path.iterdir())
    assert len(files) == 2
    bids = [
        message["data"]["b"] for file in files for _, message in read_recording(file)
    ]
    assert sorted(bids) == ["1", "3"]


def test_a_file_cut_short_by_a_crash_is_read_up_to_the_cut(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    for n in range(3000):
        recorder.write(book("BTCUSDT", str(n + 1), str(n + 2)), DAY)
    recorder.close()
    whole = recorder.path.read_bytes()
    cut = tmp_path / "market-cut.jsonl.gz"
    cut.write_bytes(whole[: len(whole) // 2])
    rows = list(read_recording(cut))
    assert 0 < len(rows) < 3000
    assert [m["data"]["b"] for _, m in rows] == [str(n + 1) for n in range(len(rows))]


def test_a_message_holding_a_line_break_is_not_recorded(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path)
    recorder.write('{"a":\n1}', DAY)
    assert recorder.lines_written == 0 and recorder.path is None


def test_recording_stops_when_the_disk_is_nearly_full(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path, min_free_bytes=10**18)
    recorder.write(book("BTCUSDT", "1", "2"), DAY)
    assert not recorder.active and "nearly full" in recorder.stopped_reason


def test_any_surprise_while_writing_stops_recording_quietly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("surprise")

    monkeypatch.setattr("exchange.recorder.gzip.open", boom)
    recorder = Recorder(tmp_path)
    recorder.write(book("BTCUSDT", "1", "2"), DAY)
    assert not recorder.active and "RuntimeError" in recorder.stopped_reason


def test_recording_stops_at_the_size_limit_and_never_fills_the_disk(
    tmp_path: Path,
) -> None:
    recorder = Recorder(tmp_path, max_folder_bytes=1)
    recorder.write(book("BTCUSDT", "1", "2"), DAY)  # first write checks the size
    assert not recorder.active and "size limit" in recorder.stopped_reason
    recorder.write(book("BTCUSDT", "3", "4"), DAY)  # ignored, no error
    assert recorder.lines_written == 1


def test_a_folder_that_cannot_be_written_stops_recording_without_an_error(
    tmp_path: Path,
) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    recorder = Recorder(blocker)
    recorder.write(book("BTCUSDT", "1", "2"), DAY)
    assert not recorder.active and "could not write" in recorder.stopped_reason
    assert recorder.folder_bytes() == 0


# --- one recorded stretch of real prices, replayed ---


def replay() -> MarketState:
    state = MarketState(("BTCUSDT", "ETHUSDT", "BNBUSDT"))
    for received_at, message in read_recording(FIXTURE):
        assert state.apply(message, received_at)
    return state


def test_the_recorded_sample_is_real_and_readable() -> None:
    rows = list(read_recording(FIXTURE))
    assert len(rows) == 4000
    times = [at for at, _ in rows]
    assert times == sorted(times) and all(at.tzinfo == UTC for at in times)
    streams = {message["stream"] for _, message in rows}
    assert streams == {
        f"{pair}@{kind}"
        for pair in ("btcusdt", "ethusdt", "bnbusdt")
        for kind in ("bookTicker", "aggTrade")
    }
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as file:
        assert file.readline().startswith('{"t":')


def test_replaying_the_sample_gives_the_same_prices_every_time() -> None:
    first, second = replay(), replay()
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        quote = first.quotes[symbol]
        assert vars(quote) == vars(second.quotes[symbol])
        # Every number is an exact Decimal, and the market makes sense.
        for value in (quote.bid, quote.ask, quote.last_price, quote.last_quantity):
            assert type(value) is Decimal and value > 0
        assert quote.bid < quote.ask
        assert quote.last_trade_at is not None and quote.book_updated_at is not None
