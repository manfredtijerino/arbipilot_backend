"""Rules every table must follow, checked without a database."""

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from database import models  # noqa: F401 - registers the tables
from database.base import Base

TABLES = Base.metadata.tables
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def test_the_login_tables_are_defined() -> None:
    assert {"users", "refresh_tokens", "password_reset_codes"} <= set(TABLES)


def test_every_timestamp_carries_a_timezone() -> None:
    naive = [
        f"{table.name}.{column.name}"
        for table in TABLES.values()
        for column in table.columns
        if isinstance(column.type, sa.DateTime) and not column.type.timezone
    ]
    assert naive == []


def test_no_column_is_floating_point() -> None:
    # Money is NUMERIC. A float column would be a rounding bug waiting to happen.
    floats = [
        f"{table.name}.{column.name}"
        for table in TABLES.values()
        for column in table.columns
        if isinstance(column.type, sa.Float)
    ]
    assert floats == []


def test_every_table_has_a_primary_key() -> None:
    assert [t.name for t in TABLES.values() if not t.primary_key.columns] == []


def test_tokens_and_codes_are_deleted_with_their_user() -> None:
    for name in ("refresh_tokens", "password_reset_codes"):
        (foreign_key,) = TABLES[name].foreign_keys
        assert foreign_key.column.table.name == "users"
        assert foreign_key.ondelete == "CASCADE"


def test_no_table_stores_a_password_or_token_in_the_clear() -> None:
    columns = {c.name for t in TABLES.values() for c in t.columns}
    assert not columns & {"password", "token", "code"}
    assert {"password_hash", "token_hash", "code_hash"} <= columns


def test_migrations_form_one_chain() -> None:
    # Two heads would mean two migrations both claim to be the latest.
    scripts = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    assert len(scripts.get_heads()) == 1
