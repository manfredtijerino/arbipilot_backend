"""Database connection: the address, TLS, and safe failure messages. No network."""

from collections.abc import Callable

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError

from config import database
from config.database import DatabaseCheckError, check_database, describe_failure
from config.settings import Settings

FAKE_PASSWORD = "test-db-password"


@pytest.fixture
def db_settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        postgres_host="db.test.invalid",
        postgres_user="arbipilot_dev",
        postgres_password=FAKE_PASSWORD,
    )


def test_url_is_built_from_the_separate_values(db_settings: Settings) -> None:
    url = db_settings.database_url()
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "db.test.invalid"
    assert url.port == 5432
    assert url.database == "arbipilot_dev"
    assert url.username == "arbipilot_dev"


def test_url_never_shows_the_password_as_text(db_settings: Settings) -> None:
    url = db_settings.database_url()
    assert FAKE_PASSWORD not in str(url)
    assert FAKE_PASSWORD not in repr(url)


def test_engine_always_uses_tls(
    db_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_create(url: object, **kwargs: object) -> str:
        seen.update(kwargs)
        return "engine"

    monkeypatch.setattr(database, "create_async_engine", fake_create)
    database.create_engine(db_settings)
    assert seen["connect_args"]["ssl"] == "require"


@pytest.mark.parametrize("missing", ["postgres_host", "postgres_password"])
async def test_unconfigured_database_fails_without_connecting(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    values = {
        "postgres_host": "db.test.invalid",
        "postgres_user": "arbipilot_dev",
        "postgres_password": FAKE_PASSWORD,
    }
    values[missing] = ""

    def must_not_connect(settings: Settings) -> None:
        raise AssertionError("tried to connect")

    monkeypatch.setattr(database, "get_engine", must_not_connect)
    with pytest.raises(DatabaseCheckError, match="not configured"):
        await check_database(make_settings(**values))


class _FakeConnection:
    def __init__(self, error: BaseException | None) -> None:
        self.error = error
        self.statements: list[str] = []

    async def __aenter__(self) -> "_FakeConnection":
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


class _FakeEngine:
    def __init__(self, error: BaseException | None = None) -> None:
        self.connection = _FakeConnection(error)

    def connect(self) -> _FakeConnection:
        return self.connection


async def test_check_runs_select_1_and_returns_the_database_name(
    db_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr(database, "get_engine", lambda settings: engine)
    assert await check_database(db_settings) == "arbipilot_dev"
    assert engine.connection.statements == ["SELECT 1"]


async def test_failure_message_never_contains_the_driver_text(
    db_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A driver error that (wrongly) carries the password must not leak it.
    error = OSError(f"connect failed postgresql://user:{FAKE_PASSWORD}@host")
    monkeypatch.setattr(database, "get_engine", lambda settings: _FakeEngine(error))
    with pytest.raises(DatabaseCheckError) as caught:
        await check_database(db_settings)
    assert FAKE_PASSWORD not in str(caught.value)
    assert "host unreachable" in str(caught.value)
    assert caught.value.__cause__ is None  # the original error does not travel


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConnectionRefusedError("x"), "host unreachable"),
        (TimeoutError("x"), "timed out"),
        (asyncpg.InvalidPasswordError("x"), "refused the user name or password"),
        (asyncpg.InvalidCatalogNameError("x"), "arbipilot_dev does not exist"),
        (RuntimeError("x"), "unexpected database error (RuntimeError)"),
    ],
)
def test_each_failure_gets_a_plain_reason(
    db_settings: Settings, error: BaseException, expected: str
) -> None:
    assert expected in describe_failure(error, db_settings)


def test_reason_is_found_inside_a_wrapped_error(db_settings: Settings) -> None:
    wrapped = DBAPIError("SELECT 1", None, asyncpg.InvalidPasswordError("x"))
    assert "refused" in describe_failure(wrapped, db_settings)


# --- Which database may be named (stage 2) ---


def test_url_can_point_at_the_test_database(db_settings: Settings) -> None:
    assert db_settings.database_url("arbipilot_test").database == "arbipilot_test"


@pytest.mark.parametrize("name", ["arbipilot_prod", "postgres", "dbmaster"])
def test_url_refuses_any_other_database(db_settings: Settings, name: str) -> None:
    with pytest.raises(ValueError, match="POSTGRES_DB or POSTGRES_TEST_DB"):
        db_settings.database_url(name)


def test_engine_for_migrations_keeps_no_connection_open(
    db_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_create(url: object, **kwargs: object) -> str:
        seen.update(kwargs, url=url)
        return "engine"

    monkeypatch.setattr(database, "create_async_engine", fake_create)
    database.create_engine(db_settings, database="arbipilot_test", pooled=False)
    assert seen["poolclass"] is database.NullPool
    assert seen["url"].database == "arbipilot_test"
    assert seen["connect_args"]["ssl"] == "require"
    assert seen["hide_parameters"] is True


def test_test_database_name_is_given_when_it_ends_in_test(
    db_settings: Settings,
) -> None:
    assert database.name_of_test_database(db_settings) == "arbipilot_test"


def test_test_database_name_refuses_an_empty_name(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(postgres_test_db="")
    with pytest.raises(DatabaseCheckError, match="ending in _test"):
        database.name_of_test_database(settings)


def test_test_database_name_refuses_a_name_not_ending_in_test(
    db_settings: Settings,
) -> None:
    # The guard rails stop this at startup; this check must hold on its own too.
    settings = db_settings.model_copy(update={"postgres_test_db": "arbipilot_dev"})
    with pytest.raises(DatabaseCheckError, match="ending in _test"):
        database.name_of_test_database(settings)


def test_test_database_is_never_used_in_production(db_settings: Settings) -> None:
    settings = db_settings.model_copy(update={"app_env": "production"})
    with pytest.raises(DatabaseCheckError, match="never used in production"):
        database.name_of_test_database(settings)
