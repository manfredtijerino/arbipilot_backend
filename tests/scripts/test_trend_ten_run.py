"""The ten-coin script: what is fixed, the download, and the run-once lock.

Every price here is made up, and the archive is a fake: nothing leaves the
machine and no real candle is read.
"""

import hashlib
import random
from array import array
from datetime import UTC, datetime
from fractions import Fraction as F
from pathlib import Path

import httpx
import pytest

from exchange.history import Candles, file_name, minute_of, months_between
from scripts import spread_measure
from scripts import trend_ten_run as run
from trading.trend_ten import replay

MONTHS = months_between(run.FIRST_MONTH, run.LAST_MONTH)
DAYS = (minute_of(2026, 11) - minute_of(2022, 10)) // 1440
SPREADS = dict.fromkeys(run.TEN, "0.01000")


def made_up(symbol: str, seed: int, last_day: int = DAYS - 1) -> Candles:
    """A random walk for the whole period; no candle after `last_day`."""
    rng = random.Random(seed)
    price, opens, closes = 10_000, [], []
    for day in range(DAYS):
        if day > last_day:
            opens.append(0)
            closes.append(0)
            continue
        opens.append(price)
        price = max(100, price + rng.randint(-400, 420))
        closes.append(price)
    highs = [max(o, c) for o, c in zip(opens, closes, strict=True)]
    lows = [min(o, c) for o, c in zip(opens, closes, strict=True)]
    columns = [array("q", column) for column in (opens, highs, lows, closes)]
    return Candles(symbol, minute_of(*run.FIRST_MONTH), *columns, step=1440)


def ten_series(removed_on: int = 700) -> list[Candles]:
    return [
        made_up(symbol, seed, removed_on if symbol == "MATICUSDT" else DAYS - 1)
        for seed, symbol in enumerate(run.TEN)
    ]


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Spreads filled in, a result file in a temporary folder, no pauses."""
    result = tmp_path / "trend-ten-result.txt"
    monkeypatch.setattr(run, "RESULT_FILE", result)
    monkeypatch.setattr(run, "SPREAD_PERCENT", dict(SPREADS))
    monkeypatch.setattr(run, "PAUSE_SECONDS", 0)
    return result


def never(*args: object, **kwargs: object) -> None:
    raise AssertionError("this must not be reached")


# --- what was fixed in the roadmap ---


def test_the_ten_coins_and_the_seven_new_ones() -> None:
    assert run.TEN == spread_measure.SYMBOLS  # the pairs whose spread is measured
    assert run.TEN[:3] == ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    assert run.SEVEN == (
        "XRPUSDT",
        "DOGEUSDT",
        "ADAUSDT",
        "SOLUSDT",
        "MATICUSDT",
        "DOTUSDT",
        "SHIBUSDT",
    )


def test_the_period_starts_and_ends_on_the_written_days() -> None:
    daily = made_up("BTCUSDT", 0)
    start = daily.index_of(*run.PERIOD_START)
    assert start == run.DAYS_BEFORE == 31  # October 2022 is only looked back at
    assert daily.time_of(0) == datetime(2022, 10, 1, tzinfo=UTC)
    assert daily.time_of(start) == datetime(2022, 11, 1, tzinfo=UTC)
    assert daily.time_of(len(daily) - 1) == datetime(2026, 10, 31, tzinfo=UTC)
    assert len(MONTHS) == 49


def test_the_result_file_is_the_one_named_in_the_roadmap() -> None:
    assert run.RESULT_FILE.name == "trend-ten-result.txt"
    assert run.RESULT_FILE.parent.name == "docs"


# --- the spreads ---


def test_the_spreads_are_percent_as_printed_by_the_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(run, "SPREAD_PERCENT", {**SPREADS, "BTCUSDT": "0.00123"})
    spread = run.spreads()
    assert spread["BTCUSDT"] == F(123, 10_000_000)  # 0.00123% as a share
    assert spread["SHIBUSDT"] == F(1, 10_000)
    assert list(spread) == list(run.TEN)
    # The coin that could not be measured carries the largest of the others.
    assert run.MAY_END_EARLY == ("MATICUSDT",)
    widest = {**SPREADS, "SHIBUSDT": "0.02000", "MATICUSDT": "0.02000"}
    monkeypatch.setattr(run, "SPREAD_PERCENT", widest)
    assert run.spreads()["MATICUSDT"] == F(2, 10_000)


@pytest.mark.parametrize(
    "wrong",
    [
        {},
        {s: "0.01" for s in run.TEN[:9]},  # one missing
        {**SPREADS, "LTCUSDT": "0.01"},  # one too many
        {**SPREADS, "BTCUSDT": "abc"},
        {**SPREADS, "BTCUSDT": "-0.01"},
        {**SPREADS, "BTCUSDT": "0"},  # a free spread would flatter the bot
        {**SPREADS, "MATICUSDT": "0.00900"},  # not the largest of the others
        {**SPREADS, "SHIBUSDT": "0.02000"},  # ... MATIC was not raised with it
        {**SPREADS, "BTCUSDT": "5.1"},  # 5.1%: a typing mistake
    ],
)
def test_without_all_ten_spreads_the_run_is_not_ready(
    wrong: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "SPREAD_PERCENT", wrong)
    with pytest.raises(run.NotReady):
        run.spreads()


# --- the download, against a fake archive ---


class Archive:
    """Answers like `data.binance.vision`, from a dictionary."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.asked: list[str] = []
        self.checksums: dict[str, str] = {}
        self.status = 404  # what a file that is not there answers

    def __call__(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[1]
        self.asked.append(name)
        assert request.url.host == "data.binance.vision"
        if name.endswith(".CHECKSUM"):
            of = name.removesuffix(".CHECKSUM")
            if of not in self.files and of not in self.checksums:
                return httpx.Response(self.status)
            if of not in self.files:
                return httpx.Response(200, text=self.checksums[of])
            digest = hashlib.sha256(self.files[of]).hexdigest()
            return httpx.Response(200, text=self.checksums.get(of, f"{digest}  {of}"))
        if name not in self.files:
            return httpx.Response(self.status)
        return httpx.Response(200, content=self.files[name])

    async def download(self, folder: Path) -> dict:
        transport = httpx.MockTransport(self)
        async with httpx.AsyncClient(transport=transport) as client:
            return await run.download(client, folder, ("AAAUSDT",))


def names(months: list) -> list[str]:
    return [file_name("AAAUSDT", year, month, "1d") for year, month in months]


async def test_missing_files_are_fetched_checked_and_saved(
    tmp_path: Path, ready: Path
) -> None:
    all_names = names(MONTHS)
    archive = Archive({name: name.encode() for name in all_names})
    (tmp_path / all_names[0]).write_bytes(all_names[0].encode())
    absent = await archive.download(tmp_path)
    assert absent == {"AAAUSDT": []}
    # A file already there is not fetched again, but its checksum is checked.
    assert all_names[0] not in archive.asked
    assert all_names[0] + ".CHECKSUM" in archive.asked
    assert (tmp_path / all_names[1]).read_bytes() == all_names[1].encode()
    assert len(list(tmp_path.glob("*.zip"))) == 49
    assert list(tmp_path.glob("*.part")) == []


async def test_months_the_archive_does_not_have_are_reported_not_invented(
    tmp_path: Path, ready: Path
) -> None:
    archive = Archive({name: b"x" for name in names(MONTHS[:20])})
    absent = await archive.download(tmp_path)
    assert absent == {"AAAUSDT": MONTHS[20:]}
    assert len(list(tmp_path.glob("*.zip"))) == 20
    run.check_absent({"MATICUSDT": absent["AAAUSDT"]})  # the removed coin


async def test_a_file_already_there_with_other_content_is_refused(
    tmp_path: Path, ready: Path
) -> None:
    all_names = names(MONTHS)
    archive = Archive({name: name.encode() for name in all_names})
    (tmp_path / all_names[3]).write_bytes(b"placed by hand")
    with pytest.raises(run.NotReady, match="checksum does not match"):
        await archive.download(tmp_path)


async def test_a_month_is_absent_only_when_its_checksum_is_absent_too(
    tmp_path: Path, ready: Path
) -> None:
    all_names = names(MONTHS)
    archive = Archive({name: b"x" for name in all_names[:-1]})
    archive.checksums[all_names[-1]] = f"{'0' * 64}  {all_names[-1]}"
    # The file answers 404 but its checksum exists: a hiccup, not a removal.
    with pytest.raises(run.NotReady, match="has it but did not send it"):
        await archive.download(tmp_path)


async def test_a_wrong_checksum_or_a_failing_archive_stops_before_anything(
    tmp_path: Path, ready: Path
) -> None:
    first = names(MONTHS)[0]
    archive = Archive({name: b"x" for name in names(MONTHS)})
    archive.checksums[first] = f"{'0' * 64}  {first}"
    with pytest.raises(run.NotReady, match="checksum does not match"):
        await archive.download(tmp_path)
    assert list(tmp_path.iterdir()) == []  # the bad file was not saved
    del archive.checksums[first]

    broken = Archive({})
    broken.status = 500
    with pytest.raises(run.NotReady, match="answered 500"):
        await broken.download(tmp_path)

    huge = Archive({first: b"x" * (run.LARGEST_FILE + 1)})
    with pytest.raises(run.NotReady, match="larger than expected"):
        await huge.download(tmp_path)


def test_only_the_removed_coin_may_miss_months_and_only_at_its_end() -> None:
    run.check_absent({"XRPUSDT": [], "MATICUSDT": MONTHS[-3:]})
    run.check_absent({"MATICUSDT": MONTHS[-1:]})
    for hole in (MONTHS[5:6], MONTHS[:1], [MONTHS[10], MONTHS[-1]], MONTHS[-3:-1]):
        with pytest.raises(run.NotReady, match="missing inside its history"):
            run.check_absent({"MATICUSDT": hole})
    # One 404 on a coin that still trades is a hiccup, never "removed".
    for symbol in ("XRPUSDT", "BTCUSDT"):
        with pytest.raises(run.NotReady, match="missing from the archive"):
            run.check_absent({symbol: MONTHS[-1:]})


def test_every_coin_needs_october_2022_and_the_first_day() -> None:
    series = ten_series()
    assert run.check_start(series) == 31
    for day in (0, 17, 31):
        broken = ten_series()
        broken[4].close[day] = 0
        with pytest.raises(run.NotReady, match="DOGEUSDT: a day is missing"):
            run.check_start(broken)
    # A hole after the first day is allowed (the replay's own rules handle it).
    later = ten_series()
    later[4].close[40] = 0
    assert run.check_start(later) == 31
    # Only the coin known to be removed may stop before the last day.
    cut = ten_series()
    cut[3].close[DAYS - 1] = 0
    with pytest.raises(run.NotReady, match="XRPUSDT: the last day of the period"):
        run.check_start(cut)


# --- the result ---


def test_the_report_has_both_runs_the_five_conditions_and_a_verdict(
    ready: Path,
) -> None:
    series, spread = ten_series(), run.spreads()
    out = run.report(series, spread)
    assert out == run.report(series, spread)  # the same data, the same result
    text = "\n".join(out)
    assert out[0].startswith("TEN-COIN TREND TEST, 2022-11-01 to 2026-10-31")
    assert "buy>20d high, sell<20d low; 24 USDT per trade, at most 3 open" in out[1]
    assert "MATICUSDT 0.01000" in out[2]
    # Day 700 after 1 October 2022 is 31 August 2024.
    assert (
        "removed from Binance during the period: MATICUSDT (last candle 2024-08-31)"
        in out
    )
    assert text.count("removed from Binance") == 1
    ten_at, seven_at = out.index("TEN COINS"), out.index("THE SEVEN NEW COINS ALONE")
    assert ten_at < seven_at
    ten_lines, seven_lines = out[ten_at:seven_at], out[seven_at:]
    assert sum("USDT " in line and "trend rule:" in line for line in ten_lines) == 10
    assert sum("trend rule:" in line for line in seven_lines) == 7
    assert not any("BTCUSDT" in line for line in seven_lines)
    # The trade count printed is the replay's own.
    played = replay(series, 31, DAYS)
    bot_line = next(line for line in ten_lines if line.startswith("trend rule"))
    assert f"trades={len(played.trades)} " in bot_line.replace("  ", " ")
    assert f"or no candle): {played.dropped};" in text
    marks = [line for line in out if line[:3] in ("(a)", "(b)", "(c)", "(d)", "(e)")]
    assert len(marks) == 5 and all(m.endswith((": yes", ": NO")) for m in marks)
    passed = all(m.endswith(": yes") for m in marks)
    assert out[-1] == ("RESULT: PASS" if passed else "RESULT: FAIL")


def test_the_seven_coin_run_holds_72_usdt_split_in_seven(ready: Path) -> None:
    seven = [c for c in ten_series() if c.symbol in run.SEVEN]
    _, bot, held = run.one_run("x", seven, 31, run.spreads())
    assert {t.stake for t in held.trades} == {F(72, 7)}
    assert held.curve[0] != 72 and bot.curve[0] == 72  # hold is in from day one
    assert {t.stake for t in bot.trades} == {24}
    assert {t.symbol for t in bot.trades} <= set(run.SEVEN)


def test_a_wider_spread_costs_the_bot_money(ready: Path) -> None:
    series = ten_series()
    cheap = run.one_run("x", series, 31, dict.fromkeys(run.TEN, F(0)))[1]
    dear = run.one_run("x", series, 31, dict.fromkeys(run.TEN, F(1, 100)))[1]
    assert len(cheap.trades) == len(dear.trades) > 0  # the same trades
    assert dear.profit < cheap.profit


# --- run once ---


def test_the_run_writes_its_result_once_and_then_refuses(
    ready: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    async def fetched(folder: Path) -> dict:
        return {symbol: [] for symbol in run.TEN}

    monkeypatch.setattr(run, "fetch", fetched)
    monkeypatch.setattr(run, "load", lambda folder, absent: ten_series())
    assert run.main(["trend_ten_run.py", "run"]) == 0
    written = ready.read_text()
    assert written.splitlines()[-1] in ("RESULT: PASS", "RESULT: FAIL")
    assert capsys.readouterr().out.strip() == written.strip()

    monkeypatch.setattr(run, "fetch", never)
    monkeypatch.setattr(run, "load", never)
    assert run.main(["trend_ten_run.py", "run"]) == 1
    assert "Refused" in capsys.readouterr().out
    assert ready.read_text() == written


def test_a_crash_during_the_calculation_still_counts_as_the_one_run(
    ready: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    async def fetched(folder: Path) -> dict:
        return {symbol: [] for symbol in run.TEN}

    def crash(*args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(run, "fetch", fetched)
    monkeypatch.setattr(run, "load", lambda folder, absent: ten_series())
    monkeypatch.setattr(run, "report", crash)
    with pytest.raises(RuntimeError):
        run.main(["trend_ten_run.py", "run"])
    assert ready.read_text() == "the ten-coin run was started\n"
    assert run.main(["trend_ten_run.py", "run"]) == 1  # looked at: no second run
    assert "Refused" in capsys.readouterr().out


def test_a_broken_download_of_a_trading_coin_never_becomes_a_result(
    ready: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    async def one_missing(folder: Path) -> dict:
        return {**{s: [] for s in run.TEN}, "XRPUSDT": MONTHS[-1:]}

    monkeypatch.setattr(run, "fetch", one_missing)
    monkeypatch.setattr(run, "load", never)
    assert run.main(["trend_ten_run.py", "run"]) == 1
    assert "XRPUSDT: a month is missing from the archive" in capsys.readouterr().out
    assert not ready.exists()


def test_without_the_spreads_nothing_is_downloaded_and_nothing_is_written(
    ready: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(run, "SPREAD_PERCENT", {})
    monkeypatch.setattr(run, "fetch", never)
    assert run.main(["trend_ten_run.py", "run"]) == 1
    assert "Not started, nothing was calculated" in capsys.readouterr().out
    assert not ready.exists()


def test_a_failed_download_leaves_the_one_run_unused(
    ready: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    async def failing(folder: Path) -> dict:
        raise run.NotReady("XRPUSDT-1d-2023-01.zip: the archive answered 503")

    monkeypatch.setattr(run, "fetch", failing)
    monkeypatch.setattr(run, "load", never)
    assert run.main(["trend_ten_run.py", "run"]) == 1
    assert "answered 503" in capsys.readouterr().out
    assert not ready.exists()  # it may be started again


def test_an_unknown_word_runs_nothing(capsys: pytest.CaptureFixture) -> None:
    assert run.main(["trend_ten_run.py"]) == 2
    assert run.main(["trend_ten_run.py", "hidden"]) == 2
    assert "usage" in capsys.readouterr().out
