"""The spread measurement: what is asked, what is written, what counts, and
the averages. Binance is replaced by made-up answers; nothing leaves the
machine and nothing really waits."""

import csv
import io
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta
from email.message import Message
from fractions import Fraction as F
from pathlib import Path

import pytest

from scripts import spread_measure as sm

START = datetime(2026, 12, 1, 0, 0, 0, tzinfo=UTC)


def entry(symbol: str, bid: str, ask: str) -> dict:
    return {
        "symbol": symbol,
        "bidPrice": bid,
        "bidQty": "1.0",
        "askPrice": ask,
        "askQty": "1.0",
    }


class Fake:
    """A clock that moves only when the script sleeps, and scripted answers."""

    def __init__(self, answers: list) -> None:
        self.answers = list(answers)
        self.seconds = 0.0
        self.slept: list[float] = []
        self.log: list[str] = []

    def ask(self) -> list[dict]:
        self.seconds += 0.5  # a question takes a moment
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def now(self) -> datetime:
        return START + timedelta(seconds=self.seconds)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.seconds += seconds

    def run(self, out: Path, minutes: int) -> int:
        return sm.measure(
            out,
            minutes,
            ask_binance=self.ask,
            now=self.now,
            clock=lambda: self.seconds,
            sleep=self.sleep,
            log=self.log.append,
        )


def too_many(retry_after: str | None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(sm.URL, 429, "Too Many Requests", headers, None)


def read(path: Path) -> list[list[str]]:
    with path.open(newline="") as file:
        return list(csv.reader(file))


# --- what is asked ---


def test_the_ten_pairs_are_the_ones_fixed_in_the_roadmap() -> None:
    assert sm.SYMBOLS == (
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
    assert sm.MINUTES == 10080 and sm.INTERVAL_SECONDS == 60


def test_one_question_asks_for_the_ten_pairs_that_are_trading() -> None:
    url = sm.request_url()
    assert url.startswith("https://api.binance.com/api/v3/ticker/bookTicker?")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["symbolStatus"] == ["TRADING"]
    # Binance's documented format: ["BTCUSDT","BNBUSDT"], no spaces.
    assert query["symbols"] == ['["' + '","'.join(sm.SYMBOLS) + '"]']
    assert "key" not in url.lower() and "signature" not in url.lower()


# --- what is written ---


def test_an_answer_becomes_one_line_per_pair_as_received() -> None:
    answer = [
        entry("BTCUSDT", "60000.00000000", "60000.01000000"),
        entry("LTCUSDT", "80.00", "80.01"),  # not one of the ten
        {"symbol": "ETHUSDT", "bidPrice": 3000.0, "askPrice": "3000.01"},  # a number
        {"symbol": "BNBUSDT"},  # no prices
        "nonsense",
        entry("SHIBUSDT", "0.00000900", "0.00000901"),
    ]
    assert sm.rows_of(answer, START) == [
        ("2026-12-01T00:00:00Z", "BTCUSDT", "60000.00000000", "60000.01000000"),
        ("2026-12-01T00:00:00Z", "SHIBUSDT", "0.00000900", "0.00000901"),
    ]


def test_it_asks_once_a_minute_and_stops_after_the_given_minutes(
    tmp_path: Path,
) -> None:
    fake = Fake([[entry("BTCUSDT", "100", "101")]] * 3)
    out = tmp_path / "samples.csv"
    assert fake.run(out, 3) == 3
    assert fake.answers == []  # three questions, no more
    assert fake.slept == [59.5, 59.5, 59.5]  # the next full minute each time
    assert [line[0] for line in read(out)] == [
        "2026-12-01T00:00:00Z",
        "2026-12-01T00:01:00Z",
        "2026-12-01T00:02:00Z",
    ]
    assert fake.log[0].endswith("start: 3 minutes, writing samples.csv")
    assert fake.log[-1].endswith("done: 3 of 3 answered")
    assert fake.seconds == 180  # it ends when the time is over


def test_a_failed_question_loses_its_minute_and_nothing_is_made_up(
    tmp_path: Path,
) -> None:
    good = [entry("BTCUSDT", "100", "101")]
    fake = Fake([good, OSError("https://secret-looking-address"), ValueError(), good])
    out = tmp_path / "samples.csv"
    assert fake.run(out, 4) == 2
    assert len(read(out)) == 2
    missed = [line for line in fake.log if "missed" in line]
    assert [line.split("missed: ")[1] for line in missed] == ["OSError", "ValueError"]
    assert "secret" not in "".join(fake.log)  # the type only, never the text


def test_when_binance_says_slow_down_it_waits_as_long_as_asked(
    tmp_path: Path,
) -> None:
    good = [entry("BTCUSDT", "100", "101")]
    fake = Fake([too_many("180"), good, too_many("99999"), good, too_many(None)])
    out = tmp_path / "samples.csv"
    fake.run(out, 16)
    # 180 s asked; then ten minutes at most; with no number, a normal minute.
    assert fake.slept[0] == 180
    assert fake.slept[2] == 600
    assert fake.slept[4] == 60
    assert sm.wait_after(OSError()) == 0
    # After a long wait the lost minutes are skipped: no burst of questions.
    assert fake.answers == [] and min(fake.slept) > 50
    assert len(read(out)) == 2


def test_a_second_run_adds_to_the_file_instead_of_wiping_it(tmp_path: Path) -> None:
    out = tmp_path / "samples.csv"
    Fake([[entry("BTCUSDT", "100", "101")]]).run(out, 1)
    Fake([[entry("BTCUSDT", "100", "102")]]).run(out, 1)
    assert [line[3] for line in read(out)] == ["101", "102"]


# --- what counts, and the averages ---


def test_one_samples_spread_is_the_gap_over_the_middle_price() -> None:
    assert sm.spread_of("99", "101") == F(2, 100)
    assert sm.spread_of("100", "100") == 0  # no gap is still a sample
    assert sm.spread_of("60000.00", "60000.01") == F(1, 100) / F("60000.005")


@pytest.mark.parametrize(
    ("bid", "ask"),
    [("0", "101"), ("-1", "101"), ("101", "100"), ("", "101"), ("abc", "1")],
)
def test_a_sample_without_a_real_bid_or_with_a_crossed_book_does_not_count(
    bid: str, ask: str
) -> None:
    assert sm.spread_of(bid, ask) is None


def test_each_pair_gets_the_average_of_its_own_counted_samples() -> None:
    lines = [
        ["t", "BTCUSDT", "99", "101"],  # 2%
        ["t", "BTCUSDT", "199", "201"],  # 1%
        ["t", "BTCUSDT", "0", "5"],  # does not count
        ["t", "ETHUSDT", "100", "100"],  # 0%
        ["t", "LTCUSDT", "1", "2"],  # not one of the ten
        ["broken line"],
    ]
    for symbol in sm.SYMBOLS[2:]:
        lines.append(["t", symbol, "999", "1001"])  # 0.2%
    result = sm.summarise(lines)
    assert list(result) == list(sm.SYMBOLS)
    assert result["BTCUSDT"] == (2, F(3, 200))
    assert result["ETHUSDT"] == (1, F(0))
    assert result["SHIBUSDT"] == (1, F(2, 1000))


def test_a_pair_that_no_longer_trades_gets_the_largest_of_the_others() -> None:
    lines = [["t", "BTCUSDT", "999", "1001"], ["t", "SHIBUSDT", "99", "101"]]
    result = sm.summarise(lines)
    assert result["MATICUSDT"] == (0, F(2, 100))  # SHIB's, the largest
    assert result["ETHUSDT"] == (0, F(2, 100))
    assert result["BTCUSDT"] == (1, F(2, 1000))  # its own, unchanged
    with pytest.raises(ValueError, match="nothing was measured"):
        sm.summarise([])


def test_the_report_names_every_pair_and_marks_the_borrowed_one() -> None:
    result = sm.summarise([["t", "BTCUSDT", "99", "101"]])
    lines = sm.report(result)
    assert len(lines) == 11
    assert lines[1].split() == ["BTCUSDT", "1", "2.00000%"]
    assert "not trading" in lines[8] and lines[8].startswith("MATICUSDT")


def test_the_summary_command_reads_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    out = tmp_path / "samples.csv"
    out.write_text("2026-12-01T00:00:00Z,BTCUSDT,99,101\n")
    assert sm.main(["summary", "--file", str(out)]) == 0
    assert "BTCUSDT" in capsys.readouterr().out
    assert io.StringIO(out.read_text()).readline().count(",") == 3
