import logging

from config.logging import build_formatter, setup_logging


def record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="arbipilot.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=None,
        exc_info=None,
    )


def test_development_lines_start_with_dev(make_settings):
    line = build_formatter(make_settings()).format(record("shadow fill BTCUSDT"))
    assert line.startswith("[DEV] ")
    assert line.endswith("INFO arbipilot.test: shadow fill BTCUSDT")


def test_production_lines_have_no_prefix(make_settings):
    settings = make_settings(
        app_env="production", postgres_db="arbipilot_prod", postgres_test_db=""
    )
    line = build_formatter(settings).format(record("started"))
    assert not line.startswith("[DEV]")
    assert "Z INFO arbipilot.test: started" in line


def test_lines_are_single_line_with_utc_time(make_settings):
    line = build_formatter(make_settings()).format(record("one event"))
    assert "\n" not in line
    # "[DEV] 2026-11-12T10:00:00Z INFO ..."
    timestamp = line.split(" ")[1]
    assert len(timestamp) == 20 and timestamp.endswith("Z") and "T" in timestamp


def test_a_secret_setting_never_appears_in_a_line(make_settings):
    settings = make_settings(anthropic_api_key="test-key-0001")
    line = build_formatter(settings).format(record("calling with test-key-0001 now"))
    assert "test-key-0001" not in line
    assert line.endswith("calling with [hidden] now")


def test_a_telegram_address_never_shows_the_bot_token(make_settings):
    # Even a token that is not the configured one is hidden, by its shape.
    message = 'POST https://api.telegram.org/bot123456:test-token_AB/sendMessage "200"'
    line = build_formatter(make_settings()).format(record(message))
    assert "test-token_AB" not in line
    assert "bot[hidden]/sendMessage" in line


def test_a_binance_request_signature_is_hidden(make_settings):
    signature = "ab12" * 16
    message = (
        f"GET https://api.binance.com/api/v3/account?timestamp=1&signature={signature}"
    )
    line = build_formatter(make_settings()).format(record(message))
    assert signature not in line
    assert line.endswith("timestamp=1&signature=[hidden]")


def test_a_secret_inside_an_error_traceback_is_hidden(make_settings):
    settings = make_settings(telegram_bot_token="test-token-0001")
    try:
        raise RuntimeError("failed for test-token-0001")
    except RuntimeError:
        import sys

        failed = record("request failed")
        failed.exc_info = sys.exc_info()
    assert "test-token-0001" not in build_formatter(settings).format(failed)


def test_request_logging_libraries_are_quietened(make_settings):
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    try:
        setup_logging(make_settings())
        for name in ("httpx", "httpx2", "httpcore", "telegram"):
            assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
    finally:
        root.handlers[:], root.level = saved[0], saved[1]
