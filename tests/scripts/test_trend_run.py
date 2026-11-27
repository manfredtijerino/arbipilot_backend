"""The trend script's two things that cannot be redone: periods and run-once."""

from array import array
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exchange.history import Candles, minute_of
from scripts import trend_run


def empty_daily() -> Candles:
    start = minute_of(*trend_run.FIRST_DATA_MONTH)
    year, month = trend_run.LAST_MONTH
    count = (minute_of(year, month + 1) - start) // 1440
    columns = [array("q", bytes(8 * count)) for _ in range(4)]
    return Candles("BTCUSDT", start, *columns, step=1440)


def test_the_periods_start_and_end_on_the_written_days() -> None:
    daily = empty_daily()
    choosing_start = daily.index_of(*trend_run.CHOOSING_START)
    hidden_start = daily.index_of(*trend_run.HIDDEN_START)
    assert choosing_start == 61  # 30 days of November + 31 of December 2017
    assert daily.time_of(choosing_start) == datetime(2018, 1, 1, tzinfo=UTC)
    assert daily.time_of(hidden_start - 1) == datetime(2022, 10, 31, tzinfo=UTC)
    assert daily.time_of(hidden_start) == datetime(2022, 11, 1, tzinfo=UTC)
    assert daily.time_of(len(daily) - 1) == datetime(2026, 10, 31, tzinfo=UTC)
    # BNB's first day, 6 November 2017 (slot 5), leaves 55 days before 2018.
    assert choosing_start - 55 == 6


def test_the_hidden_run_is_refused_when_its_result_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    result = tmp_path / "trend-hidden-result.txt"
    result.write_text("the hidden run was started\n")
    monkeypatch.setattr(trend_run, "RESULT_FILE", result)

    def no_loading(*args: object, **kwargs: object) -> None:
        raise AssertionError("the data must not even be loaded")

    monkeypatch.setattr(trend_run, "load_candles", no_loading)
    assert trend_run.main(["trend_run.py", "hidden"]) == 1
    assert "Refused" in capsys.readouterr().out
    assert result.read_text() == "the hidden run was started\n"


def test_an_unknown_word_runs_nothing(capsys: pytest.CaptureFixture) -> None:
    assert trend_run.main(["trend_run.py", "everything"]) == 2
    assert trend_run.main(["trend_run.py"]) == 2
    assert "usage" in capsys.readouterr().out


def test_the_result_file_is_the_one_named_in_the_roadmap() -> None:
    assert trend_run.RESULT_FILE.name == "trend-hidden-result.txt"
    assert trend_run.RESULT_FILE.parent.name == "docs"
