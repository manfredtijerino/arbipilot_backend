from config.settings import Settings
from scripts.env_status import expected_keys, main, status_rows


def test_expected_keys_come_from_the_settings_class():
    keys = expected_keys()
    assert "JWT_SECRET" in keys and "POSTGRES_PASSWORD" in keys
    assert len(keys) == len(Settings.model_fields)


def test_rows_say_set_empty_or_missing():
    env = {"APP_ENV": "development", "LIVE_CONFIRM": "", "PORT": "   "}
    rows = dict(status_rows(env, ["APP_ENV", "LIVE_CONFIRM", "PORT", "JWT_SECRET"]))
    assert rows == {
        "APP_ENV": "set",
        "LIVE_CONFIRM": "empty",
        "PORT": "empty",
        "JWT_SECRET": "MISSING",
    }


def test_unknown_keys_are_flagged():
    rows = dict(status_rows({"JWT_SECRT": "oops"}, ["JWT_SECRET"]))
    assert rows["JWT_SECRET"] == "MISSING"
    assert rows["JWT_SECRT"].startswith("UNKNOWN")


def test_a_value_pasted_as_a_key_is_not_printed():
    # python-dotenv reads a line without "=" as a key whose value is None.
    env = {"pasted-test-value-0123456789": None, "wrapped-test+value/": "="}
    text = repr(status_rows(env, ["JWT_SECRET"]))
    assert "pasted-test-value" not in text
    assert "wrapped-test" not in text
    assert text.count("unrecognised entry") == 2


def test_main_prints_names_and_statuses_only(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=development\n"
        "JWT_SECRET=test-secret-value-in-file\n"
        "LIVE_CONFIRM=\n"
        "pasted-test-value-on-its-own-line\n"
    )
    assert main(env_file) == 0
    output = capsys.readouterr().out
    assert "APP_ENV" in output and "JWT_SECRET" in output
    assert "test-secret-value-in-file" not in output
    assert "pasted-test-value" not in output
    assert "development" not in output


def test_main_reports_a_missing_file(tmp_path, capsys):
    assert main(tmp_path / ".env") == 1
    assert ".env not found" in capsys.readouterr().out


def test_values_never_appear_in_the_output():
    env = {"JWT_SECRET": "test-secret-value", "EXTRA": "test-extra-value"}
    text = repr(status_rows(env, ["JWT_SECRET"]))
    assert "test-secret-value" not in text
    assert "test-extra-value" not in text
